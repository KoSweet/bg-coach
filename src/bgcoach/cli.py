"""bg-coach command line.

  bgcoach version            current client build, patch, BG pool
  bgcoach log [FILE|latest]  replay a Power.log (plain or .gz) and print a full timeline
  bgcoach log --live         follow the running game and print decisions as they happen
  bgcoach check              parse every archived log, compare with HDT's game history
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import gzip
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from . import version as V
from .replay import Game, Replay, norm_hero

DATA = V.DATA
GAMES_DIR = DATA / "games"
RAW = DATA / "raw"
from .pipeline import HDT_XML  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ------------------------------------------------------------------ helpers
def open_log(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def base_date_for(path: Path) -> dt.date:
    s = str(path)
    m = re.search(r"(20\d\d)[_-]?(\d\d)[_-]?(\d\d)", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return dt.date.fromtimestamp(path.stat().st_mtime)


def save_game(g: Game) -> Path:
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    stamp = g.start.strftime("%Y%m%d_%H%M%S") if g.start else "unknown"
    p = GAMES_DIR / f"{stamp}_{norm_hero(g.hero)}.json"
    p.write_text(json.dumps(g.to_dict(), indent=1, default=str), encoding="utf-8")
    return p


class Printer:
    """Human-readable timeline, shared by replay and live mode."""

    def __init__(self, live: bool = False):
        self.db: V.CardDB | None = None
        self.live = live

    def n(self, cid):
        return self.db.name(cid) if self.db else (cid or "?")

    def cards(self, lst):
        return ", ".join(self.n(c["card_id"] if isinstance(c, dict) else c) for c in lst) or "-"

    def board(self, lst):
        return "  ".join(f"{self.n(c['card_id'])}{'*' if c.get('golden') else ''} {c['atk']}/{c['hp']}"
                         for c in lst) or "(empty)"

    def __call__(self, kind: str, d: dict):
        if kind == "round":
            print(f"\n── Round {d['round']} ".ljust(70, "─"))
        elif kind == "turn_start":
            arm = f"+{d['armor']}" if d.get("armor") else ""
            print(f"   {d['hp']}{arm} HP | Tier {d['tier']} | {d['gold']} gold")
            print(f"   board: {self.board(d.get('board') or [])}")
            if d.get("hand"):
                print(f"   hand:  {self.cards(d['hand'])}")
            print(f"   shop:  {self.cards(d.get('shop') or [])}")
        elif kind == "action":
            self.action(d)
        elif kind == "choice":
            if d["kind"] == "HERO_PICK":
                return
            opts = " | ".join(self.n(c) for c in d["options"])
            print(f"   {d['kind']:<15} [{opts}] → {self.n(d['picked'])}")
        elif kind == "combat":
            opp = self.n(d.get("opp_hero"))
            res = d["result"]
            dmg = f"took {d['damage_taken']}" if res == "LOSS" else (
                f"dealt {d['damage_dealt']}" if res == "WIN" else "no damage")
            a0 = f"+{d['armor_before']}" if d.get("armor_before") else ""
            a1 = f"+{d['armor_after']}" if d.get("armor_after") else ""
            print(f"   ⚔ vs {opp}: {res} ({dmg}), HP {d['hp_before']}{a0} → {d['hp_after']}{a1}")
            if d.get("opp_board"):
                print(f"     their board: {self.board(d['opp_board'])}")
        elif kind == "tier" and self.live:
            print(f"   ▲ now Tier {d['tier']}")

    def action(self, a: dict):
        t = a["type"]
        if "shop" in a and t != "END_TURN":
            print(f"   shop: {self.cards(a['shop'])}")
        g = f"{a['gold']:>2}g T{a['tier']}"
        if t == "BUY":
            txt = f"BUY      {self.n(a.get('target'))}"
        elif t == "SELL":
            txt = f"SELL     {self.n(a.get('target'))} {a.get('target_atk_hp', '')}"
        elif t == "PLAY":
            txt = f"PLAY     {self.n(a.get('card_id'))} → slot {a.get('position', '?')}"
        elif t == "CAST":
            txt = f"CAST     {self.n(a.get('card_id'))}" + (f" → {self.n(a['target'])}" if a.get("target") else "")
        elif t == "MOVE":
            txt = f"MOVE     {self.n(a.get('card_id'))} {a['from']}→{a['to']}"
        elif t == "LEVEL":
            txt = f"LEVEL UP → Tier {a['to_tier']}"
        elif t == "HERO_POWER":
            txt = f"HERO PWR {self.n(a.get('card_id'))}" + (f" → {self.n(a['target'])}" if a.get("target") else "")
        elif t == "ACTIVATE":
            txt = f"ACTIVATE {self.n(a.get('card_id'))}"
        elif t == "CHOICE":
            return  # printed via the choice event
        elif t == "END_TURN":
            txt = "END TURN"
        elif t in ("REFRESH", "FREEZE", "DARK_GIFT", "BOB"):
            txt = t.replace("_", " ")
        else:
            txt = f"{t:<8} {self.n(a.get('card_id'))}"
        print(f"   [{g}] {txt}")

    def header(self, g: dict):
        pass


def print_game_summary(g: Game, pr: Printer):
    db = pr.db
    print("\n" + "═" * 70)
    when = g.start.strftime("%Y-%m-%d %H:%M") if g.start else "?"
    print(f" {when}  {g.game_type}  build {g.build}")
    if g.hero_offers:
        print(f" Heroes offered: {', '.join(pr.n(h) for h in g.hero_offers)}")
    print(f" Hero: {pr.n(g.hero)}   Anomaly: {pr.n(g.anomaly) if g.anomaly else '-'}")
    print(f" PLACEMENT: {g.placement}   rounds: {len(g.turns)}   complete: {g.complete}")
    print(f" Final board: {pr.board(g.final_board)}")
    c = collections.Counter(a["type"] for t in g.turns for a in t["actions"])
    print(" Actions: " + ", ".join(f"{k} {v}" for k, v in c.most_common()))
    print("═" * 70)


def replay_file(path: Path, verbose: bool = True) -> list[Game]:
    pr = Printer()
    state = {"build": None}

    def on_event(kind, d):
        if verbose:
            pr(kind, d)

    rp = Replay(base_date=base_date_for(path), on_event=on_event)
    orig_hdr = rp._game_hdr

    def hdr(body):  # load the card DB for the exact build as soon as we see it
        orig_hdr(body)
        if rp.g and rp.g.build and rp.g.build != state["build"]:
            state["build"] = rp.g.build
            pr.db = V.card_db(rp.g.build)
            if verbose:
                p = V.patch_for_build(rp.g.build)
                print(f"\n▶ New game {rp.g.start:%Y-%m-%d %H:%M}  build {rp.g.build} = patch {p.get('version')} "
                      f"({p.get('name')})")
    rp._game_hdr = hdr
    with open_log(path) as fh:
        games = rp.feed_all(fh)
    for g in games:
        if pr.db is None and g.build:
            pr.db = V.card_db(g.build)
        if verbose:
            print_game_summary(g, pr)
    return games


# ------------------------------------------------------------------ commands
def cmd_version(_args):
    build, session = V.latest_client_build()
    meta = V.current_bg_meta_build()
    print("Hearthstone Battlegrounds — version")
    if build:
        p = V.patch_for_build(build)
        print(f"  Your client build : {build}  (from {session})")
        print(f"  Patch             : {p.get('version')}  —  {p.get('name')}  (released {str(p.get('date'))[:10]})"
              + ("" if p.get("exact") else "  [nearest known patch]"))
    else:
        print("  Your client build : unknown (no Hearthstone log found)")
    mp = V.patch_for_build(meta)
    print(f"  Latest BG patch   : {meta}  —  {mp.get('version')} {mp.get('name')}")
    if build and build < meta:
        print("  ⚠ A newer build exists than your last logged session (game updated since, or update pending).")
    db = V.card_db(build or meta)
    print(f"  Card DB           : HearthstoneJSON build {db.build if db.build > 0 else 'latest'} "
          f"({len(db.by_id)} cards)")
    pool = V.blizzard_bg_pool()
    tiers = collections.Counter(c.get("battlegrounds", {}).get("tier") for c in pool["minion"])
    print(f"  Live BG pool      : {len(pool['hero'])} heroes, {len(pool['minion'])} minions "
          f"(by tier: {', '.join(f'T{t}:{n}' for t, n in sorted((k, v) for k, v in tiers.items() if k))}), "
          f"{len(pool['spell'])} spells, {len(pool['trinket'])} trinkets, {len(pool['anomaly'])} anomalies")


def latest_power_log() -> Path | None:
    sessions = sorted(V.HS_LOGS.glob("Hearthstone_*"))
    for s in reversed(sessions):
        for name in ("Power.log", "Power_old.log"):
            if (s / name).exists():
                return s / name
    return None


def cmd_log(args):
    if args.live:
        return live(Path(args.file) if args.file not in (None, "latest") else None)
    path = latest_power_log() if args.file in (None, "latest") else Path(args.file)
    if path is None or not path.exists():
        sys.exit("No Power.log found.")
    print(f"Replaying {path}")
    games = replay_file(path, verbose=not args.quiet)
    for g in games:
        print(f"saved → {save_game(g)}")


def live(follow: Path | None = None):
    pr = Printer(live=True)
    current = None
    print("Watching Hearthstone… (Ctrl+C to stop)")
    while True:
        path = follow or latest_power_log()
        if path is None:
            time.sleep(2)
            continue
        if path != current:
            current = path
            print(f"\n[log] {path}")
            rp = Replay(base_date=base_date_for(path), on_event=pr, on_game=lambda g: (
                print_game_summary(g, pr), print(f"saved → {save_game(g)}")))
            orig = rp._game_hdr

            def hdr(body, rp=rp, orig=orig):
                orig(body)
                if rp.g and rp.g.build and (pr.db is None or pr.db.build != rp.g.build):
                    pr.db = V.card_db(rp.g.build)
                    p = V.patch_for_build(rp.g.build)
                    print(f"\n▶ Game started — build {rp.g.build}, patch {p.get('version')} ({p.get('name')})")
            rp._game_hdr = hdr
            fh = open(path, encoding="utf-8", errors="replace")
            # catch up silently on what already happened, then go live
            quiet = rp.on_event
            rp.on_event = lambda k, d: None
            for line in fh:
                rp.feed(line)
            rp.on_event = quiet
            if rp.g:
                print(f"(joined a game in progress — round {(rp.turn + 1) // 2})")
        line = fh.readline()
        if not line:
            rp.flush_if_idle()
            time.sleep(0.2)
            newest = follow or latest_power_log()
            if newest != current:
                fh.close()
            continue
        rp.feed(line)


def hdt_games() -> list[dict]:
    """All games HDT ever recorded (union of live XML + archived snapshots)."""
    sources = ([HDT_XML] if HDT_XML else []) + sorted((RAW / "hdt" / "BgsLastGames").glob("*.xml.gz"))
    out = {}
    for src in sources:
        if not src.exists():
            continue
        data = gzip.open(src).read() if src.suffix == ".gz" else src.read_bytes()
        for el in ET.fromstring(data).iter("Game"):
            start = dt.datetime.fromisoformat(el.get("StartTime")[:26]).replace(tzinfo=None)
            out[start] = {
                "start": start, "hero": norm_hero(el.get("Hero")), "placement": int(el.get("Placemenent") or 0),
                "rating": el.get("Rating"), "rating_after": el.get("RatingAfter"),
                "duos": el.get("Duos") == "true",
                "board": sorted(m.findtext("CardId") for m in el.iter("Minion")),
            }
    return sorted(out.values(), key=lambda x: x["start"])


def cmd_check(args):
    logs = sorted(RAW.glob("hs/*/Power*.log.gz")) + sorted(RAW.glob("legacy/real_players_logs/*.log.gz"))
    if args.limit:
        logs = logs[-args.limit:]
    games: dict = {}
    for p in logs:
        t0 = time.time()
        try:
            gs = replay_file(p, verbose=False)
        except Exception as e:  # keep going, report
            print(f"  ERROR {p.name}: {e!r}")
            continue
        for g in gs:
            key = g.start.replace(microsecond=0) if g.start else None
            if key and key not in games:
                games[key] = g
                save_game(g)
        print(f"  parsed {p.parent.name}/{p.name}: {len(gs)} games in {time.time() - t0:.0f}s")
    hdt = hdt_games()
    print(f"\nParsed {len(games)} unique games; HDT knows {len(hdt)} games.\n")
    rows, ok = [], collections.Counter()
    for g in sorted(games.values(), key=lambda g: g.start):
        # HDT stamps StartTime when *it* notices the game (late if HDT was opened mid-game),
        # so match on the same hero within 20 minutes, nearest first.
        cands = [h for h in hdt if h["hero"] == norm_hero(g.hero)
                 and -300 < (h["start"] - g.start).total_seconds() < 1200]
        match = min(cands, key=lambda h: abs((h["start"] - g.start).total_seconds()), default=None)
        if match is None:
            rows.append((g, None, "no HDT record", (False, False, False)))
            continue
        hero_ok = norm_hero(g.hero) == match["hero"]
        place_ok = g.placement == match["placement"]
        mine = sorted(c["card_id"] for c in g.final_board)
        board_ok = mine == match["board"]
        note = []
        if not hero_ok:
            note.append(f"hero {g.hero} vs {match['hero']}")
        if not place_ok:
            note.append(f"place {g.placement} vs {match['placement']}")
        if not board_ok:
            note.append(f"board diff -{sorted(set(match['board']) - set(mine))} +{sorted(set(mine) - set(match['board']))}")
        rows.append((g, match, "; ".join(note) or "OK", (hero_ok, place_ok, board_ok)))
    # "my" account = the one HDT recorded most games for
    top = collections.Counter(g.account for g, m, *_ in rows if m).most_common(1)
    my_account = top[0][0] if top else None
    for g, m, note, *res in rows:
        k = "" if g.account == my_account else "other_"
        if m is not None:
            ok[k + "matched"] += 1
            for name, val in zip(("hero", "placement", "board"), res[0]):
                ok[k + name] += val
        if g.account != my_account:
            note = "other account (not your game)"
        elif "DUO" in (g.game_type or ""):
            note = "duos"
        elif m is None:
            note = "your game (HDT has no record)"
        mmr = f"{m['rating']}→{m['rating_after']}" if m else ""
        print(f"  {g.start:%m-%d %H:%M}  {norm_hero(g.hero):<22} place {g.placement}  {mmr:<11} {note}")
    n = ok["matched"] or 1
    print(f"\nYOUR games also recorded by HDT: {ok['matched']} -> hero {ok['hero']}/{n}, "
          f"placement {ok['placement']}/{n}, final board {ok['board']}/{n}")
    if ok["other_matched"]:
        print(f"(other account: {ok['other_matched']} matched, placement {ok['other_placement']}/{ok['other_matched']})")
    yours = [g for g, *_ in rows if g.account == my_account and "DUO" not in (g.game_type or "")]
    if yours:
        avg = sum(g.placement or 0 for g in yours) / len(yours)
        print(f"Your solo games logged: {len(yours)}, average placement {avg:.2f}")


def cmd_ui(a):
    from . import pipeline, web
    test = None
    if a.test:
        test = Path(a.test) if a.test != "newest" else next(
            (p for p in reversed(pipeline.archived_logs()) if p.parent.parent.name == "hs"), None)
        if test is None or not test.exists():
            sys.exit("No archived log to test with. Run: bgcoach import")
    web.serve(a.port, not a.no_browser, Path(a.follow) if a.follow else None, not a.no_auto_archive,
              test_log=test, speed=a.speed, overlay=not a.no_overlay)


def _windowless_logging():
    """Started without a console (pythonw / mac app): send output to data/app.log."""
    if sys.stdout is None or sys.stderr is None:
        from .paths import DATA
        DATA.mkdir(parents=True, exist_ok=True)
        f = open(DATA / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = f


def cmd_setup(a):
    from . import paths
    from .combat_sim import available
    print("bg-coach setup")
    print(f"  system           : {'Windows' if paths.IS_WIN else 'macOS' if paths.IS_MAC else sys.platform}")
    print(f"  data folder      : {paths.DATA}")
    ok_hs = paths.HS_LOGS.exists()
    print(f"  Hearthstone      : {paths.HS_DIR} {'(found)' if ok_hs else '(NOT FOUND: set BGCOACH_HS_DIR)'}")
    changed = paths.ensure_logging()
    print(f"  logging settings : {paths.log_config_path()} "
          f"{'(updated: restart Hearthstone once)' if changed else '(already OK)'}")
    print(f"  HDT (optional)   : {paths.HDT_DIR or 'not installed: no HDT match / Bob s Buddy odds'}")
    print(f"  combat simulator : {'ready' if available() else 'not installed (optional: needs Node.js, see README)'}")
    if a.shortcut and paths.IS_WIN:
        make_windows_shortcut()


def make_windows_shortcut():
    """Desktop + Start-menu shortcut that starts bg-coach without a console window."""
    import subprocess
    from .paths import REPO
    vbs = REPO / "bg-coach.vbs"
    ico = REPO / "src" / "bgcoach" / "static" / "icon.ico"
    ps = (
        "$s=(New-Object -ComObject WScript.Shell);"
        "foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){"
        "$l=$s.CreateShortcut((Join-Path $d 'bg-coach.lnk'));"
        f"$l.TargetPath='wscript.exe';$l.Arguments='\"{vbs}\"';$l.WorkingDirectory='{REPO}';"
        f"$l.IconLocation='{ico}';$l.Description='bg-coach: Battlegrounds coach';$l.Save()}}"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
    print("  shortcut         :", "created on Desktop + Start menu" if r.returncode == 0 else r.stderr.strip()[:200])


def main(argv=None):
    _windowless_logging()
    ap = argparse.ArgumentParser(prog="bgcoach")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("version").set_defaults(fn=cmd_version)
    p = sub.add_parser("log")
    p.add_argument("file", nargs="?")
    p.add_argument("--live", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_log)
    p = sub.add_parser("ui", help="open the app in your browser")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.add_argument("--follow", help="watch this log file instead of the live Hearthstone log (testing)")
    p.add_argument("--no-auto-archive", action="store_true")
    p.add_argument("--test", nargs="?", const="newest", metavar="LOG",
                   help="test mode: replay an archived game into the Live tab (default: newest archived log)")
    p.add_argument("--speed", type=int, default=8000, help="test mode: log lines per second")
    p.add_argument("--no-overlay", action="store_true", help="don't open the small always-on-top status window")
    p.set_defaults(fn=cmd_ui)
    p = sub.add_parser("share", help="build a clean zip (no personal data) to give to a friend")
    p.set_defaults(fn=lambda a: __import__("bgcoach.share", fromlist=["main"]).main())
    p = sub.add_parser("setup", help="check paths, turn on Hearthstone logging, optional shortcut")
    p.add_argument("--shortcut", action="store_true", help="Windows: create Desktop/Start-menu shortcuts")
    p.set_defaults(fn=cmd_setup)
    p = sub.add_parser("overlay", help="only the small always-on-top status window (app must be running)")
    p.add_argument("--port", type=int, default=8765)
    p.set_defaults(fn=lambda a: __import__("bgcoach.overlay", fromlist=["main"]).main(a.port))
    p = sub.add_parser("import", help="parse archived logs into games")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=lambda a: __import__("bgcoach.pipeline", fromlist=["import_all"]).import_all(force=a.force))
    p = sub.add_parser("facts", help="verified facts about your last session, for /review-session")
    p.add_argument("--last", type=int, default=0)
    p.set_defaults(fn=lambda a: __import__("bgcoach.facts", fromlist=["main"]).main(
        ["--last", str(a.last)] if a.last else []))
    p = sub.add_parser("sim-check", help="compare the combat simulator with Bob's Buddy on real fights")
    p.add_argument("--logs", type=int, default=3)
    p.add_argument("--sims", type=int, default=1000)
    p.set_defaults(fn=lambda a: __import__("bgcoach.simcheck", fromlist=["main"]).main(
        ["--logs", str(a.logs), "--sims", str(a.sims)]))
    p = sub.add_parser("whatif", help="simulate fights, buy what-ifs and positioning for recent games")
    p.add_argument("--last", type=int, default=20)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=lambda a: __import__("bgcoach.whatif", fromlist=["main"]).main(
        ["--last", str(a.last)] + (["--force"] if a.force else [])))
    p = sub.add_parser("check")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(fn=cmd_check)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
