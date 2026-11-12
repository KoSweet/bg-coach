"""Simulated "what if" analysis per game: every round the simulator reproduces (rounds 1-10 checked
against Bob's Buddy or the real result, rounds 11+ only when Bob's Buddy confirms the fight).

For each saved game:
  - fight: your recorded fight, simulated (win/tie/loss %)
  - buy what-if: for each flagged buy, the same fight with the alternative card in place of the one
    you bought (alternative at its printed stats/keywords, same slot)
  - positioning: for fights you lost or were the underdog in, other orders of your minions; reported
    only when an order wins clearly more often (re-checked with more simulations)
  - counter ("scam") lines: for fights you lost, what your end-of-turn shop and gold allowed: buy a
    minion still in the shop, selling your weakest minion(s) if you needed the gold or the space.
    Reported when it clearly changes the fight; "risky" when it lowers your total stats.
  - keep lines: a minion you sold that turn, kept on the board (in place of your weakest one if the
    board was full): the transition turn that cost a fight, scam or big stats alike.

Every what-if is only used for fights the simulator reproduces (trust check against Bob's Buddy or
the real result). Results are cached in data/sim/<game file>.json.  `bgcoach whatif` fills the
cache; the app also runs it in the background after each game.
"""
from __future__ import annotations

import json
import sys

from . import combat_sim, pipeline
from . import version as V
from .decisions import MINION_COST, buy_decisions
from .lobby import stats as board_stats

SIM_DIR = pipeline.DATA / "sim"
VERSION = 4
MAX_ROUND = 10  # trusted on its own up to here (see `bgcoach sim-check`); rounds 11+ need Bob's Buddy to agree
POS_MIN_GAIN = 10.0     # percentage points
COUNTER_MIN_GAIN = 15.0  # points of (win + half the ties)
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


def order_change(before: list[dict], after: list[dict]) -> dict:
    """The one move that turns `before` into `after` (as `_orders` makes them): which minion goes to
    which slot, or the whole board reversed."""
    n = len(before)
    key = [id(x) for x in after]
    if key == [id(x) for x in reversed(before)] and n > 2:
        return {"reverse": True, "of": n}
    moves = []  # one order can be several moves (A last = B first): say it the way a player would
    for i in range(n):
        for j in range(n):
            b = before[:i] + before[i + 1:]
            b.insert(j, before[i])
            if i != j and [id(x) for x in b] == key:
                moves.append((0 if j == 0 else 1 if j == n - 1 else 2, i, j))
    if moves:
        _, i, j = min(moves)
        return {"card_id": before[i].get("card_id"), "to": j + 1, "of": n}
    return {"order": [m.get("card_id") for m in after], "of": n}


def _score(r: dict) -> float:
    """How good a fight is for you: win% plus half the ties."""
    return r["win"] + r["tie"] / 2


def _level_cost(t: dict) -> int:
    """Gold spent on tavern-up this turn (0 if you didn't level)."""
    acts = t.get("actions") or []
    for i, a in enumerate(acts):
        if a["type"] == "LEVEL" and a.get("gold") is not None:
            after = next((x.get("gold") for x in acts[i + 1:] if x.get("gold") is not None), t.get("gold_end"))
            return max(0, a["gold"] - (after or 0))
    return 0


def _counter_variants(c: dict, t: dict, db) -> list[dict]:
    """Boards you could have fought with, using gold you had that turn on a minion that was still
    in the shop when the turn ended:
      - "instead": skip one minion you bought this turn, buy this one instead
      - "skip_level": don't tavern up this turn, buy this one (risky: you stay a tier lower)
      - "spare": your unspent gold, selling your weakest minion if you were 1–2 gold short
      - "keep": a minion you sold this turn, still on the board (in place of your weakest if full)
    The new minion goes in front or at the back (both are simulated); a kept one also where it stood."""
    board = c.get("my_board") or []
    gold = t.get("gold_end") or 0
    shop = [s for s in t.get("end_shop") or [] if db.get(s.get("card_id")).get("type") == "MINION"]
    weakest = min(range(len(board)), key=lambda i: board_stats([board[i]])) if board else None
    bought = {a.get("target") for a in t.get("actions") or [] if a["type"] == "BUY" and a.get("target")}

    lines: list[tuple[str, str | None, list[int]]] = []  # (kind, undone card, indices removed from board)
    for i, m in enumerate(board):
        if m["card_id"] in bought and not m.get("golden"):
            lines.append(("instead", m["card_id"], [i]))
            bought.discard(m["card_id"])  # one line per bought card
    if _level_cost(t) + gold >= MINION_COST:
        lines.append(("skip_level", None, [weakest] if len(board) >= 7 and weakest is not None else []))
    if gold >= MINION_COST:
        lines.append(("spare", None, [weakest] if len(board) >= 7 and weakest is not None else []))
    elif gold + 1 >= MINION_COST and weakest is not None:
        lines.append(("spare", None, [weakest]))

    out = _keep_variants(board, t, weakest)
    for s in shop:
        new = {"card_id": s["card_id"], "atk": s.get("atk") or 0, "hp": s.get("hp") or 1,
               "kw": s.get("kw") if s.get("kw") is not None else combat_sim.base_keywords(s["card_id"])}
        for kind, undone, removed in lines:
            kept = [m for i, m in enumerate(board) if i not in removed]
            sold = [board[i] for i in removed if kind != "instead"]
            for pos in sorted({0, len(kept)}):  # in front, or at the back
                out.append({"kind": kind, "buy": new, "undone": undone, "sold": sold, "pos": pos,
                            "board": [*kept[:pos], new, *kept[pos:]]})
    return out


def _keep_variants(board: list[dict], t: dict, weakest: int | None) -> list[dict]:
    """Minions sold this turn that didn't come back, kept on the board with the stats they were sold at."""
    on_board = {m["card_id"] for m in board}
    before = {m["card_id"]: m for m in t.get("board") or []}  # start of the turn: keywords and slot
    out, seen = [], set()
    for a in t.get("actions") or []:
        cid, ah = a.get("target"), a.get("target_atk_hp")
        if a["type"] != "SELL" or not cid or not ah or cid in on_board or cid in seen:
            continue
        seen.add(cid)
        full = len(board) >= 7
        if full and (weakest is None or sum(ah) <= board_stats([board[weakest]])):
            continue  # not bigger than what it would replace
        was = before.get(cid) or {}
        kept_m = {"card_id": cid, "atk": ah[0], "hp": ah[1],
                  "kw": was.get("kw") if was.get("kw") is not None else combat_sim.base_keywords(cid)}
        kept = [m for i, m in enumerate(board) if not (full and i == weakest)]
        sold = [board[weakest]] if full else []
        for pos in sorted({0, len(kept), min(max((was.get("pos") or 1) - 1, 0), len(kept))}):
            out.append({"kind": "keep", "buy": kept_m, "undone": cid, "sold": sold, "pos": pos,
                        "board": [*kept[:pos], kept_m, *kept[pos:]]})
    return out


def analyse(g: dict, bracket: int) -> dict:
    db = V.card_db(g.get("build") or V.current_bg_meta_build())
    combats = {c["round"]: c for c in g.get("combats") or [] if c.get("my_board") and c.get("opp_board")}
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
        elif rnd > MAX_ROUND:
            ok, why = False, "rounds 11+ are only used when Bob's Buddy confirms the simulation"
        else:
            p_actual = {"WIN": r["win"], "LOSS": r["loss"], "TIE": r["tie"]}.get(c.get("result"), 0)
            ok, why = p_actual >= 25, f"real result had {p_actual:.0f}% in the simulation"
        trusted[rnd] = {"ok": ok, "why": why, "bb": bb}

    # counter lines: fights you lost, with what the end-of-turn shop and your gold allowed
    turns = {t["round"]: t for t in g.get("turns") or []}
    cscreen, cmeta = {}, {}
    for rnd, c in combats.items():
        if c.get("result") != "LOSS" or not trusted.get(rnd, {}).get("ok"):
            continue
        for k, v in enumerate(_counter_variants(c, turns.get(rnd) or {}, db)):
            cscreen[f"c{rnd}_{k}"] = combat_sim.build_battle(c, hero, _tier(g, rnd), my_board=v["board"], sims=QUICK)
            cmeta[f"c{rnd}_{k}"] = (rnd, v)
    cquick = combat_sim.simulate(cscreen) if cscreen else {}
    best_c: dict[int, tuple[float, str]] = {}
    for key, r in cquick.items():
        if r.get("win") is None:
            continue
        rnd = cmeta[key][0]
        if rnd not in best_c or _score(r) > best_c[rnd][0]:
            best_c[rnd] = (_score(r), key)
    cconfirm = {key: combat_sim.build_battle(combats[rnd], hero, _tier(g, rnd), my_board=cmeta[key][1]["board"], sims=FULL)
                for rnd, (s, key) in best_c.items() if s - _score(first[f"f{rnd}"]) >= COUNTER_MIN_GAIN}
    cconfirmed = combat_sim.simulate(cconfirm) if cconfirm else {}

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

    out = {"version": VERSION, "fights": {}, "buys": [], "positions": [], "counters": []}
    pick = ("win", "tie", "loss")
    for key, r in cconfirmed.items():
        rnd, v = cmeta[key]
        base = first[f"f{rnd}"]
        gain = _score(r) - _score(base)
        if r.get("win") is None or gain < COUNTER_MIN_GAIN - 3:
            continue
        out["counters"].append({
            "round": rnd, "kind": v["kind"], "undone": v["undone"], "level_cost": _level_cost(turns.get(rnd) or {}),
            "buy": v["buy"]["card_id"], "buy_stats": [v["buy"]["atk"], v["buy"]["hp"]],
            "buy_kw": v["buy"].get("kw") or [], "sold": [m["card_id"] for m in v["sold"]], "pos": v["pos"] + 1,
            "gold": (turns.get(rnd) or {}).get("gold_end"), "board": [m["card_id"] for m in v["board"]],
            "base": {k: base[k] for k in pick}, "new": {k: r[k] for k in pick}, "gain": round(gain, 1),
            "stats_change": board_stats(v["board"]) - board_stats(combats[rnd]["my_board"]),
            "trust": trusted[rnd]["why"]})
    tried = {}
    for key in cmeta:
        tried[cmeta[key][0]] = tried.get(cmeta[key][0], 0) + 1
    countered = {c["round"] for c in out["counters"]}
    for rnd in combats:
        r = first.get(f"f{rnd}")
        if r and r.get("win") is not None:
            out["fights"][str(rnd)] = {**{k: r[k] for k in ("win", "tie", "loss", "dmgWon", "dmgLost")},
                                       "trusted": trusted.get(rnd, {}).get("ok", False),
                                       "trust_why": trusted.get(rnd, {}).get("why")}
            if rnd in tried and rnd not in countered and rnd in best_c:  # searched, nothing flips it
                best = cquick[best_c[rnd][1]]
                out["fights"][str(rnd)]["no_counter"] = {
                    "tried": tried[rnd], "best_buy": cmeta[best_c[rnd][1]][1]["buy"]["card_id"],
                    "best": {k: best[k] for k in pick}}
    for key, m in meta.items():
        r, base = first.get(key), first.get(f"f{m['round']}")
        if r and base and r.get("win") is not None and base.get("win") is not None \
                and trusted.get(m["round"], {}).get("ok"):
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
        except Exception as e:
            from .health import record_error
            record_error("whatif", e, game=g["file"])
            continue
        cache_path(g["file"]).write_text(json.dumps(res), encoding="utf-8")
        done += 1
        progress(f"simulated {g['file']}: {len(res['fights'])} fights, {len(res['buys'])} buy what-ifs, "
                 f"{len(res['positions'])} better orders, {len(res['counters'])} counter lines")
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
