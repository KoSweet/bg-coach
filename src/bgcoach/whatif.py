"""Simulated "what if" analysis per game (rounds 1-10, where the simulator matches Bob's Buddy).

For each saved game:
  - fight: your recorded fight, simulated (win/tie/loss %)
  - buy what-if: for each flagged buy, the same fight with the alternative card in place of the one
    you bought (alternative at its printed stats/keywords, same slot)
  - positioning: for fights you lost or were the underdog in, other orders of your minions; reported
    only when an order wins clearly more often (re-checked with more simulations)

Results are cached in data/sim/<game file>.json.  `bgcoach whatif` fills the cache; the app also runs
it in the background after each game.
"""
from __future__ import annotations

import json
import sys

from . import combat_sim, pipeline
from . import version as V
from .decisions import buy_decisions

SIM_DIR = pipeline.DATA / "sim"
VERSION = 2
MAX_ROUND = 10          # validated range (see `bgcoach sim-check`)
POS_MIN_GAIN = 10.0     # percentage points
QUICK, FULL = 300, 1500


def cache_path(file: str):
    return SIM_DIR / file


def load(file: str) -> dict | None:
    p = cache_path(file)
    if p.exists():
        d = json.loads(p.read_text(encoding="utf-8"))
        if d.get("version") == VERSION:
            return d
    return None


def _tier(g: dict, rnd: int) -> int:
    return next((t.get("tier") for t in g.get("turns") or [] if t["round"] == rnd), 3) or 3


def _alt_minion(card_id: str, db) -> dict | None:
    c = db.get(card_id)
    if c.get("type") != "MINION":
        return None
    return {"card_id": card_id, "atk": c.get("attack") or 0, "hp": c.get("health") or 1,
            "kw": combat_sim.base_keywords(card_id)}


def _orders(board: list[dict]) -> list[list[dict]]:
    """Candidate orders: every single move of one minion to another slot, plus reversed."""
    n = len(board)
    seen, out = set(), []
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            b = board[:i] + board[i + 1:]
            b.insert(j, board[i])
            key = tuple(id(x) for x in b)
            if key not in seen:
                seen.add(key)
                out.append(b)
    rev = list(reversed(board))
    if tuple(id(x) for x in rev) not in seen:
        out.append(rev)
    return out


def analyse(g: dict, bracket: int) -> dict:
    db = V.card_db(g.get("build") or V.current_bg_meta_build())
    combats = {c["round"]: c for c in g.get("combats") or []
               if c["round"] <= MAX_ROUND and c.get("my_board") and c.get("opp_board")}
    hero = g.get("hero")
    battles, meta = {}, {}

    for rnd, c in combats.items():
        battles[f"f{rnd}"] = combat_sim.build_battle(c, hero, _tier(g, rnd), sims=FULL)

    # buy what-ifs
    for d in buy_decisions(g, bracket):
        c = combats.get(d["round"])
        if not c:
            continue
        idx = next((i for i, m in enumerate(c["my_board"]) if m["card_id"] == d["you"]), None)
        alt = _alt_minion(d["better"], db)
        if idx is None or alt is None:
            continue
        board = list(c["my_board"])
        board[idx] = alt
        key = f"b{d['round']}_{d['you']}_{d['better']}"
        battles[key] = combat_sim.build_battle(c, hero, _tier(g, d["round"]), my_board=board, sims=FULL)
        meta[key] = {"round": d["round"], "you": d["you"], "better": d["better"], "slot": idx + 1}

    first = combat_sim.simulate(battles)

    # trust check per fight: the simulator must reproduce the real fight before we use its what-ifs
    from . import bobsbuddy
    sims_bb = bobsbuddy.simulations()
    trusted: dict[int, dict] = {}
    for rnd, c in combats.items():
        r = first.get(f"f{rnd}") or {}
        if r.get("win") is None:
            continue
        bb = bobsbuddy.for_game_combat(g, c, sims_bb)
        if bb:
            diff = (abs(r["win"] - bb["win"]) + abs(r["loss"] - bb["loss"])) / 2
            ok, why = diff <= 15, f"{diff:.0f} points from Bob's Buddy"
        else:
            p_actual = {"WIN": r["win"], "LOSS": r["loss"], "TIE": r["tie"]}.get(c.get("result"), 0)
            ok, why = p_actual >= 25, f"real result had {p_actual:.0f}% in the simulation"
        trusted[rnd] = {"ok": ok, "why": why, "bb": bb}

    # positioning: only where you lost or were the underdog, quick screen then confirm
    screen, pos_meta = {}, {}
    for rnd, c in combats.items():
        r = first.get(f"f{rnd}") or {}
        if r.get("win") is None or len(c["my_board"]) < 2 or not trusted.get(rnd, {}).get("ok"):
            continue
        if c.get("result") != "LOSS" and r["win"] >= 50:
            continue
        for k, order in enumerate(_orders(c["my_board"])):
            key = f"p{rnd}_{k}"
            screen[key] = combat_sim.build_battle(c, hero, _tier(g, rnd), my_board=order, sims=QUICK)
            pos_meta[key] = (rnd, order)
    quick = combat_sim.simulate(screen) if screen else {}
    best_by_round: dict[int, tuple[float, str]] = {}
    for key, r in quick.items():
        if r.get("win") is None:
            continue
        rnd = pos_meta[key][0]
        if rnd not in best_by_round or r["win"] > best_by_round[rnd][0]:
            best_by_round[rnd] = (r["win"], key)
    confirm = {}
    for rnd, (w, key) in best_by_round.items():
        if w - first[f"f{rnd}"]["win"] >= POS_MIN_GAIN:
            confirm[key] = combat_sim.build_battle(combats[rnd], hero, _tier(g, rnd), my_board=pos_meta[key][1], sims=FULL)
    confirmed = combat_sim.simulate(confirm) if confirm else {}

    out = {"version": VERSION, "fights": {}, "buys": [], "positions": []}
    for rnd in combats:
        r = first.get(f"f{rnd}")
        if r and r.get("win") is not None:
            out["fights"][str(rnd)] = {**{k: r[k] for k in ("win", "tie", "loss", "dmgWon", "dmgLost")},
                                       "trusted": trusted.get(rnd, {}).get("ok", False),
                                       "trust_why": trusted.get(rnd, {}).get("why")}
    for key, m in meta.items():
        r, base = first.get(key), first.get(f"f{m['round']}")
        if r and base and r.get("win") is not None and base.get("win") is not None                 and trusted.get(m["round"], {}).get("ok"):
            out["buys"].append({**m, "you_win": base["win"], "you_loss": base["loss"],
                                "alt_win": r["win"], "alt_loss": r["loss"], "gain": round(r["win"] - base["win"], 1)})
    for key, r in confirmed.items():
        rnd, order = pos_meta[key]
        base = first[f"f{rnd}"]
        gain = r["win"] - base["win"]
        if gain >= POS_MIN_GAIN - 2:
            out["positions"].append({"round": rnd, "order": [m["card_id"] for m in order],
                                     "actual": [m["card_id"] for m in combats[rnd]["my_board"]],
                                     "base_win": base["win"], "base_loss": base["loss"],
                                     "best_win": r["win"], "best_loss": r["loss"], "gain": round(gain, 1)})
    return out


def run(games: list[dict], bracket: int, force: bool = False, progress=print) -> int:
    if not combat_sim.available():
        progress("combat simulator not installed")
        return 0
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    done = 0
    for g in games:
        if not force and load(g["file"]):
            continue
        try:
            res = analyse(g, bracket)
        except Exception as e:  # noqa: BLE001
            from .health import record_error
            record_error("whatif", e, game=g["file"])
            continue
        cache_path(g["file"]).write_text(json.dumps(res), encoding="utf-8")
        done += 1
        progress(f"simulated {g['file']}: {len(res['fights'])} fights, {len(res['buys'])} buy what-ifs, "
                 f"{len(res['positions'])} better orders")
    return done


def main(argv=None):
    import argparse
    from . import analysis, meta
    ap = argparse.ArgumentParser(prog="bgcoach whatif")
    ap.add_argument("--last", type=int, default=20)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    games = sorted([g for g in pipeline.load_games() if g["mine"] and "DUO" not in (g.get("game_type") or "")],
                   key=lambda g: g.get("start") or "")[-a.last:]
    bracket = meta.bracket_for(analysis.player_mmr(games))
    n = run(games, bracket, a.force)
    print(f"done: {n} game(s) simulated")


if __name__ == "__main__":
    main()
