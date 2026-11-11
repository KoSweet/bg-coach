"""Validate the combat simulator against Bob's Buddy's logged odds on real fights.

  bgcoach sim-check [--logs N] [--sims 1000]

Re-parses the newest archived session logs in memory (so fights carry minion keywords), simulates
every fight that Bob's Buddy also simulated, and reports how close the two are. The simulator is only
used for coaching if this agreement is good.
"""
from __future__ import annotations

import argparse
import statistics as st
import sys

from . import bobsbuddy, combat_sim, pipeline


def collect(n_logs: int):
    logs = [p for p in pipeline.archived_logs() if p.parent.parent.name == "hs"]
    logs = sorted(logs, key=lambda p: p.stat().st_mtime)[-n_logs:]
    sims = bobsbuddy.simulations()
    fights, seen = [], set()
    for p in logs:
        games, _ = pipeline.replay_path(p)
        for g in games:
            gd = g.to_dict()
            for c in g.combats:
                bb = bobsbuddy.for_game_combat(gd, c, sims)
                key = (gd["start"][:16], c["round"])
                if bb and c.get("my_board") and c.get("opp_board") and key not in seen:
                    seen.add(key)  # same game can be in the archived log and the app's live copy
                    fights.append((gd, c, bb))
    return fights


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bgcoach sim-check")
    ap.add_argument("--logs", type=int, default=3)
    ap.add_argument("--sims", type=int, default=1000)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    fights = collect(a.logs)
    print(f"fights with Bob's Buddy odds and both boards: {len(fights)}")
    battles = {}
    for i, (g, c, bb) in enumerate(fights):
        tier = next((t.get("tier") for t in g["turns"] if t["round"] == c["round"]), 3) or 3
        battles[str(i)] = combat_sim.build_battle(c, g["hero"], tier, sims=a.sims)
    res = combat_sim.simulate(battles)
    diffs, agree, total, rows = [], 0, 0, []
    for i, (g, c, bb) in enumerate(fights):
        r = res.get(str(i))
        if not r or r.get("error") or r.get("win") is None:
            continue
        d = abs(r["win"] - bb["win"]) + abs(r["loss"] - bb["loss"])
        diffs.append(d / 2)
        fav_bb = "W" if bb["win"] > bb["loss"] else "L" if bb["loss"] > bb["win"] else "T"
        fav_sim = "W" if r["win"] > r["loss"] else "L" if r["loss"] > r["win"] else "T"
        total += 1
        agree += fav_bb == fav_sim
        rows.append((d / 2, g["start"][:16], c["round"], bb, r, c["result"]))
    if not diffs:
        print("no comparable fights")
        return
    print(f"compared {total} fights: mean difference {st.mean(diffs):.1f} points, "
          f"median {st.median(diffs):.1f}; same favourite in {agree}/{total} ({agree / total:.0%})")
    within10 = sum(1 for d in diffs if d <= 10)
    print(f"within 10 points of Bob's Buddy: {within10}/{total} ({within10 / total:.0%})")
    for lo, hi in ((1, 5), (6, 10), (11, 99)):
        ds = [r for r in rows if lo <= r[2] <= hi]
        if ds:
            same = sum(1 for r in ds if ((r[3]["win"] > r[3]["loss"]) - (r[3]["win"] < r[3]["loss"]))
                       == ((r[4]["win"] > r[4]["loss"]) - (r[4]["win"] < r[4]["loss"])))
            print(f"  rounds {lo}-{hi if hi < 99 else '+'}: {len(ds)} fights, mean diff {st.mean(r[0] for r in ds):.1f}, "
                  f"same favourite {same}/{len(ds)}")
    print("largest disagreements:")
    for d, start, rnd, bb, r, res_ in sorted(rows, key=lambda x: -x[0])[:8]:
        print(f"  {start} R{rnd}: BB {bb['win']:.0f}/{bb['tie']:.0f}/{bb['loss']:.0f}  sim {r['win']:.0f}/{r['tie']:.0f}/{r['loss']:.0f}"
              f"  actual {res_}  (diff {d:.0f})")


if __name__ == "__main__":
    main()
