"""Compact, verified facts about recent games, for Claude Code's /review-session to coach from.

  bgcoach facts                 # your last session (games within 3 hours of each other)
  bgcoach facts --last 10       # last 10 games

Everything printed is computed from the logs + meta; the review must only use these numbers.
"""
from __future__ import annotations

import datetime as dt
import statistics as st
import sys

from . import analysis, pipeline
from . import version as V


def _session(games: list[dict], gap_hours: float = 3) -> list[dict]:
    games = sorted(games, key=lambda g: g.get("start") or "")
    if not games:
        return []
    out = [games[-1]]
    for g in reversed(games[:-1]):
        a = dt.datetime.fromisoformat(g.get("end") or g["start"])
        b = dt.datetime.fromisoformat(out[0]["start"])
        if (b - a).total_seconds() > gap_hours * 3600:
            break
        out.insert(0, g)
    return out


def main(argv: list[str] | None = None):
    import argparse
    ap = argparse.ArgumentParser(prog="bgcoach facts")
    ap.add_argument("--last", type=int, default=0)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    mine = [g for g in pipeline.load_games() if g["mine"] and "DUO" not in (g.get("game_type") or "")]
    games = sorted(mine, key=lambda g: g.get("start") or "")[-a.last:] if a.last else _session(mine)
    rep = analysis.improve_report(mine)
    b = rep["bracket"]
    db = V.card_db(V.current_bg_meta_build())
    n = lambda c: db.name(c) if c else "?"
    pct = lambda v: f"{v:.0%}" if v is not None else "?"

    print(f"# bg-coach facts ({f'last {a.last} games' if a.last else 'last session'})")
    print(f"- player MMR ~{rep['mmr']}, compared with top-{b}% players (MMR {rep['bracket_mmr']}+), "
          f"{rep['meta_games']} games, meta updated {str(rep['meta_updated'])[:10]}")
    print(f"- all-time: {rep['games']} games, average place {rep['avg_placement']}")
    if rep["focus"]:
        f = rep["focus"]
        print(f"- current #1 focus: **{f['title']}** — {f['finding']} {f['detail']}")
    print("\n## Ranked habits (all games)")
    for h in rep["habits"]:
        print(f"- −{h['cost']:.2f} places/game [{h['evidence']}, n={h['n']}] {h['title']}: {h['finding']} {h['detail']}")
    for h in rep["not_costing"]:
        print(f"- not costing [{h['evidence']}, n={h['n']}] {h['title']}: {h['detail']}")

    cr = analysis.coach_report(mine, recent=max(len(games), 1))
    in_scope = {g["file"] for g in games}
    print("\n## Decisions to learn from (games in scope, biggest first)")
    for d in [d for d in cr["decisions"] if d["file"] in in_scope][:12]:
        when = f"{d['start'][:16].replace('T', ' ')} {n(d.get('hero'))} (place {d['placement']}) round {d['round']}"
        if d.get("better"):
            extra = f" — you: {n(d['you'])}, better: {n(d['better'])}"
        elif d.get("turn"):
            extra = f" — that turn: {d['turn']}"
        else:
            extra = ""
        sim = f" Simulation: {d['sim_note']}" if d.get("sim_note") else ""
        print(f"- [{d['kind']}] {when}{extra}. {d['calc']}{sim}")
    print("\n## Your stats compared (context only: you / your top-4 games / your 5th-8th games / meta)")
    for r in cr["stats"]:
        def f_(v, r=r):
            return "-" if v is None else (f"{v:.0%}" if r["pct"] else v)
        print(f"- {r['metric']}: {f_(r['you'])} / {f_(r['top4'])} / {f_(r['bottom4'])} / {f_(r['meta'])}")
    print(f"\n## Games in scope ({len(games)})")
    places = [g["placement"] for g in games if g.get("placement")]
    if places:
        print(f"- average place {st.mean(places):.2f}; places {places}")
    hd = [g.get("hdt") or {} for g in games]
    if hd and hd[0].get("rating") and hd[-1].get("rating_after"):
        print(f"- MMR {hd[0]['rating']} → {hd[-1]['rating_after']}")
    for g in games:
        ga = analysis.game_analysis(g, b)
        hp = ga.get("hero_pick") or {}
        s = ga["strength_phase"]
        print(f"\n### {g['start'][:16].replace('T', ' ')} · {n(g.get('hero'))} · place {g.get('placement')} · "
              f"{len(g.get('turns') or [])} rounds · file {g['file']}")
        if hp:
            print(f"- hero pick: avg {hp['picked_avg']} vs best offered {n(hp['best'])} {hp['best_avg']} (loss {hp['loss']})")
        print(f"- board vs same hero: early {pct(s['early'])}, mid {pct(s['mid'])}, late {pct(s['late'])}")
        print("- per fight: " + ", ".join(f"R{x['round']} {pct(x['ratio'])} {x['result'][0] if x.get('result') else '?'}"
                                          for x in ga["strength"]))
        tr = ga["tier_round"]
        print("- tiers reached: " + ", ".join(f"T{t} R{tr[t]}" for t in sorted(tr)) +
              f"; gold unspent {ga['gold_unspent']}; HP lost by R8 {ga['hp_lost_by_r8']}; refreshes {ga['refreshes']}")
        weak = [p for p in ga["picks"] if p.get("clear")]  # beyond chance (advice.py)
        if weak:
            print("- weaker picks: " + "; ".join(f"R{p['round']} {n(p['picked'])} {p['picked_avg']} vs {n(p['best'])} {p['best_avg']}"
                                                for p in weak))
        late = sum(1 for t in g.get("turns") or [] for x in t.get("actions") or [] if x.get("applied") is False)
        if late:
            print(f"- {late} action(s) clicked as the timer ended (not applied)")


if __name__ == "__main__":
    main()
