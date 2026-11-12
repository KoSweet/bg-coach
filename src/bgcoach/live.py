"""Live game watcher: tails the newest Hearthstone Power.log and emits events.

Used by `bgcoach log --live` (terminal) and the UI (server-sent events).
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

from . import version as V
from .health import record_error
from .pipeline import base_date_for, hdt_games, save_game
from .replay import Replay


class LogTee:
    """Copies every log line the watcher reads into the archive (gzip, appended in closed chunks so a
    crash never corrupts it). Hearthstone empties Power.log on exit, so this is the copy that survives."""

    def __init__(self, src: Path):
        from .pipeline import RAW
        self.path = RAW / "hs" / src.parent.name / f"{src.name}.live-{time.strftime('%H%M%S')}.gz"
        self.buf: list[str] = []
        self.last = time.time()

    def add(self, line: str):
        self.buf.append(line)
        if len(self.buf) >= 20000 or time.time() - self.last > 5:
            self.flush()

    def flush(self):
        import gzip
        if self.buf:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(self.path, "at", encoding="utf-8") as fh:  # each flush = one complete member
                fh.write("".join(self.buf))
            self.buf = []
        self.last = time.time()


def latest_power_log() -> Path | None:
    for s in sorted(V.HS_LOGS.glob("Hearthstone_*"), reverse=True):
        for name in ("Power.log", "Power_old.log"):
            if (s / name).exists():
                return s / name
    return None


class LiveWatcher(threading.Thread):
    """emit(kind, data) receives: status, game_start, round, turn_start, action, choice, combat,
    tier, game_end, parse_error, error."""

    def __init__(self, emit: Callable[[str, dict], None], follow: Path | None = None):
        super().__init__(daemon=True, name="bgcoach-live")
        self._emit = emit
        self.catching_up = False
        self.follow = follow
        self.stop_flag = threading.Event()
        self.rp: Replay | None = None
        self.path: Path | None = None
        self.db: V.CardDB | None = None
        self.tee: LogTee | None = None

    def emit(self, kind: str, data: dict):
        if not self.catching_up:  # don't announce games that finished before we started watching
            self._emit(kind, data)

    def stop(self):
        self.stop_flag.set()

    def _open(self, path: Path):
        self.path = path
        rp = Replay(base_date=base_date_for(path), on_event=lambda k, d: None,
                    on_game=self._on_game, on_game_start=self._on_game_start)
        fh = open(path, encoding="utf-8", errors="replace")  # noqa: SIM115 (kept open while following)
        if self.tee:
            self.tee.flush()
        self.tee = LogTee(path) if self.follow is None else None  # don't archive test replays
        self.catching_up = True
        try:
            for line in fh:  # catch up silently
                rp.feed(line)
                if self.tee:
                    self.tee.add(line)
        finally:
            self.catching_up = False
        rp.on_event = self._on_event
        self.rp = rp
        state = {"log": str(path), "in_game": rp.g is not None,
                 "round": (rp.turn + 1) // 2 if rp.g else None}
        if rp.g is not None:
            state["snapshot"] = self.snapshot()
        self.emit("status", state)
        return fh

    def _on_game_start(self, g):
        if self.db is None or self.db.build != g.build:
            self.db = V.card_db(g.build)
        p = V.patch_for_build(g.build)
        self.emit("game_start", {"build": g.build, "patch": p.get("version"), "patch_name": p.get("name"),
                                 "start": g.start.isoformat() if g.start else None})

    def snapshot(self) -> dict:
        """Current game state (used when joining mid-game / when the UI connects)."""
        rp = self.rp
        if rp is None or rp.g is None:
            return {}
        g = rp.g
        return {"hero": g.hero, "round": (rp.turn + 1) // 2, "turns": g.turns, "combats": g.combats,
                "build": g.build, "board": rp.board(), "hand": rp.hand(), "shop": rp.shop(),
                "gold": rp._gold(), "tier": rp.tier(), "hp": rp._hp(rp._my_hero())}

    def _on_event(self, kind: str, data: dict):
        if kind == "check_failed":
            if self.tee:
                self.tee.flush()
            err = record_error("self_check", None,
                               error=f"{data.get('action')} recorded but '{data.get('expected')}' did not happen",
                               source=str(self.tee.path if self.tee else self.path), line_no=data.get("line_no"),
                               round=data.get("round"), card=data.get("card"))
            data = {**data, "error_id": err["id"]}
        rp = self.rp
        if rp is not None and rp.g is not None and kind == "next_opponent":
            data = {**data, **self._next_opponent(rp, data["lobby_id"])}
        if rp is not None and rp.g is not None and kind in ("turn_start", "action", "combat", "offers", "choice"):
            board = rp.board()
            data = {**data, "hero": rp.g.hero, "board_stats": sum(
                (c.get("atk") or 0) + max(0, c.get("hp") or 0) for c in board)}
            if kind in ("turn_start", "action"):
                data["board_full"] = board  # lets the app re-check the next fight as your board changes
            if kind == "offers":
                from .synergy import history_until
                data["board_ids"] = [c["card_id"] for c in rp.board()]
                data["history"] = history_until(rp.g.to_dict(), (rp.turn + 1) // 2)
                t = rp.g.turns[-1] if rp.g.turns else None  # health + armor at the start of this turn
                if t and t.get("hp") is not None:
                    data["my_hp"] = t["hp"] + (t.get("armor") or 0)
        self.emit(kind, data)

    @staticmethod
    def _next_opponent(rp, lobby_id: int) -> dict:
        """Who you fight next, as the game shows it: leaderboard entry + the last board you saw them with."""
        from .lobby import keywords, stats
        lb = rp.lobby().get(str(lobby_id)) or {}
        seen = [c for c in rp.g.combats if c.get("opp_lobby_id") == lobby_id and c.get("opp_board")]
        last = seen[-1] if seen else None
        board = rp.board()
        return {"opp_hero": lb.get("hero"), "opp_tier": lb.get("tier"), "opp_hp": lb.get("hp"),
                "opp_triples": lb.get("triples"), "opp_place": lb.get("place"),
                "last_seen": {"round": last["round"], "stats": stats(last["opp_board"]), "kw": keywords(last["opp_board"]),
                              "board": last["opp_board"], "hero": last.get("opp_hero")} if last else None,
                "my_hero": rp.g.hero, "my_board": board, "my_stats": stats(board), "my_tier": rp.tier()}

    def _on_game(self, g):
        from .pipeline import game_file
        if self.catching_up and game_file(g).exists():
            return  # finished before we started watching and already saved: leave it alone
        if self.follow is not None:  # test mode / custom file: show it, never save it as a real game
            self.last_test_game = g.to_dict()
            self.emit("game_end", {"file": None, "placement": g.placement, "hero": g.hero, "test": True})
            return
        if self.tee:
            self.tee.flush()
        # Problem reports read raw lines from `source` by line number. The tee copy has exactly the
        # lines the parser was fed (same numbering) and survives Hearthstone wiping its log.
        g.source = str(self.tee.path) if self.tee else str(self.path)
        try:
            p = save_game(g, hdt_games())
            self.emit("game_end", {"file": p.name, "placement": g.placement, "hero": g.hero})
        except Exception as e:
            err = record_error("live_save_failed", e, source=str(self.path))
            self.emit("error", err)

    def run(self):
        fh = None
        while not self.stop_flag.is_set():
            try:
                path = self.follow or latest_power_log()
                if path is None:
                    if not getattr(self, "_said_no_log", False):  # say it once, not every 3 seconds
                        self.emit("status", {"log": None, "in_game": False, "message": "No Hearthstone log found yet"})
                        self._said_no_log = True
                    time.sleep(3)
                    continue
                self._said_no_log = False
                if path != self.path:
                    if fh:
                        fh.close()
                    fh = self._open(path)
                line = fh.readline()
                if not line:
                    self.rp.flush_if_idle()
                    if self.tee and time.time() - self.tee.last > 5:
                        self.tee.flush()
                    time.sleep(0.2)
                    newest = self.follow or latest_power_log()
                    try:
                        truncated = self.path is not None and self.path.stat().st_size < fh.tell()
                    except OSError:
                        truncated = True
                    if newest != self.path or truncated:  # new session, or Hearthstone emptied the log
                        self.path = None  # reopen on next loop
                    continue
                self.rp.feed(line)
                if self.tee:
                    self.tee.add(line)
            except Exception as e:  # never die silently
                err = record_error("live_watcher", e, source=str(self.path), line_no=getattr(self.rp, "line_no", None))
                self.emit("error", err)
                time.sleep(2)
        if self.tee:
            self.tee.flush()
        if fh:
            fh.close()
