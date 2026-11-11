"""Coaching analysis: what each game tells us, and which habits cost the most across games.

Two kinds of evidence, always labelled:
- "meta"  : comparison with thousands of games at your MMR (Firestone). Hero picks, Discover picks,
            board strength vs players on the same hero.
- "yours" : comparison between your own better and worse games (small samples -> shown with n).
Nothing here is a rule; every number says how it was computed and from how many games.
"""
from __future__ import annotations

import statistics as st

from . import advice, meta
from .advice import Stat
from .replay import norm_hero

PICK_KINDS = {"DISCOVER", "TRIPLE_DISCOVER", "DARK_GIFT_PICK"}


def _stats(board: list | None) -> int:
    return sum((c.get("atk") or 0) + max(0, c.get("hp") or 0) for c in board or [])


def player_mmr(games: list[dict]) -> int | None:
    for g in reversed(games):
        h = g.get("hdt") or {}
        if h.get("rating_after") or h.get("rating"):
            return h.get("rating_after") or h.get("rating")
    return None


def game_analysis(g: dict, bracket: int) -> dict:
    hm, cm = meta.heroes(bracket), meta.cards(bracket)
    out: dict = {"bracket": bracket, "placement": g.get("placement")}

    # ---- hero pick (meta)
    offered = []
    for h in g.get("hero_offers") or []:
        m = hm.get(h)
        offered.append({"hero": h, "avg": m["avg"] if m and m["n"] >= 100 else None, "n": m["n"] if m else 0})
    known = [o for o in offered if o["avg"] is not None]
    picked = next((o for o in offered if norm_hero(o["hero"]) == norm_hero(g.get("hero"))), None)
    if picked and picked["avg"] is not None and len(known) >= 2:
        best = min(known, key=lambda o: o["avg"])
        s_p, s_b = Stat(picked["avg"], picked["n"]), Stat(best["avg"], best["n"])
        out["hero_pick"] = {"offered": offered, "picked_avg": picked["avg"], "best": best["hero"],
                            "best_avg": best["avg"], "loss": round(picked["avg"] - best["avg"], 2),
                            "clear": advice.clearly_better(s_p, s_b), "noise": round(advice.noise(s_p, s_b), 2)}

    # ---- tempo
    reach = {}
    for t in g.get("turns") or []:
        for tier in (3, 4, 5, 6):
            if tier not in reach and (t.get("tier") or 1) >= tier:
                reach[tier] = t["round"]
    out["tier_round"] = reach

    # ---- board strength vs players on the same hero (meta)
    hmeta = hm.get(g.get("hero"))
    strength = []
    for c in g.get("combats") or []:
        mine = _stats(c.get("my_board"))
        ref = hmeta["warband"].get(c["round"]) if hmeta else None
        strength.append({"round": c["round"], "mine": mine, "meta": ref,
                         "ratio": round(mine / ref, 2) if ref else None, "result": c.get("result"),
                         "wr_meta": hmeta["combat"].get(c["round"]) if hmeta else None})
    out["strength"] = strength

    # ---- Bob's Buddy odds (HDT log): separates bad luck from weak boards
    try:
        from . import bobsbuddy
        sims = bobsbuddy.simulations()
        combats = {c["round"]: c for c in g.get("combats") or []}
        for s in strength:
            c = combats.get(s["round"])
            s["bb"] = bobsbuddy.for_game_combat(g, c, sims) if c else None
    except Exception:  # HDT logs missing: just no odds
        pass
    out["luck"] = {
        "unlucky_losses": [s["round"] for s in strength if s.get("bb") and s["bb"]["win"] >= 50 and s["result"] == "LOSS"],
        "lucky_wins": [s["round"] for s in strength if s.get("bb") and s["bb"]["loss"] >= 50 and s["result"] == "WIN"],
        "fights_with_odds": sum(1 for s in strength if s.get("bb")),
    }

    def phase(lo, hi):
        r = [s["ratio"] for s in strength if s["ratio"] is not None and lo <= s["round"] <= hi]
        return round(st.median(r), 2) if r else None
    out["strength_phase"] = {"early": phase(1, 5), "mid": phase(6, 9), "late": phase(10, 99)}

    # ---- picks (meta): picked option vs the best option that passes the advice rules (advice.py)
    from . import synergy
    from . import version as V
    db = V.card_db(g.get("build") or V.current_bg_meta_build())
    picks = []
    for t in g.get("turns") or []:
        hp = (t["hp"] + (t.get("armor") or 0)) if t.get("hp") is not None else None
        for a in t.get("actions") or []:
            if a.get("type") != "CHOICE" or a.get("kind") not in PICK_KINDS:
                continue
            picked = a.get("picked")
            stats = {o: cm.stat(o, t["round"]) for o in a.get("options") or []}
            got = stats.get(picked)
            board_now = [m["card_id"] for m in t.get("board") or []] + [
                x["card_id"] for x in t.get("actions") or []
                if x["type"] == "PLAY" and x.get("card_id") and (x.get("line") or 0) < (a.get("line") or 0)]
            ctx = synergy.context(board_now, synergy.history_until(g, t["round"], a.get("line")))
            fits = {o: synergy.fit(o, ctx) for o in stats}
            lvl_p = fits.get(picked, (2, ""))[0]
            # only options that fit at least as well (never off-build) and, at low HP, help the next fight too
            known = {k: s for k, s in stats.items() if s is not None and (k == picked or (
                fits[k][0] >= lvl_p and fits[k][0] > 0 and advice.survives(picked, k, hp, db)))}
            if got is None or len(known) < 2:
                continue
            best = min(known, key=lambda k: known[k].avg)
            picks.append({"round": t["round"], "kind": a["kind"], "picked": picked, "picked_avg": round(got.avg, 2),
                          "best": best, "best_avg": round(known[best].avg, 2), "loss": round(got.avg - known[best].avg, 2),
                          "clear": best != picked and advice.clearly_better(got, known[best]),
                          "noise": round(advice.noise(got, known[best]), 2), "picked_n": got.n, "best_n": known[best].n,
                          "hp": hp, "low_hp": advice.low_hp(hp),
                          "picked_fit": fits[picked][1], "best_fit": fits[best][1],
                          "fits": {k: list(v) for k, v in fits.items()},
                          "options": {k: (round(s.avg, 2) if s else None) for k, s in stats.items()}})
    out["picks"] = picks
    out["pick_loss"] = round(sum(p["loss"] for p in picks if p["clear"]), 2)  # only differences beyond chance

    # ---- economy / HP / pace
    turns = g.get("turns") or []
    unspent = [t.get("gold_end") for t in turns if isinstance(t.get("gold_end"), int)]
    out["gold_unspent"] = sum(max(0, u) for u in unspent) if unspent else None
    out["gold_unspent_rounds"] = [t["round"] for t in turns if (t.get("gold_end") or 0) >= 2]
    hp_by8 = None
    for c in g.get("combats") or []:
        if c["round"] == 8:
            start = (turns[0].get("hp") or 0) + (turns[0].get("armor") or 0) if turns else None
            end = (c.get("hp_after") or 0) + (c.get("armor_after") or 0)
            hp_by8 = start - end if start is not None else None
    out["hp_lost_by_r8"] = hp_by8
    refreshes = sum(1 for t in turns for a in t.get("actions") or [] if a["type"] == "REFRESH")
    out["refreshes"] = refreshes
    losses = [c for c in g.get("combats") or [] if c.get("result") == "LOSS"]
    out["losses_r1_8"] = sum(1 for c in losses if c["round"] <= 8)
    return out


# ------------------------------------------------------------------ across games
def _split(games, key, threshold=None, worse_if_higher=True):
    """Average placement when a habit shows up vs when it doesn't (your own games).
    threshold=None splits at your median so both groups are a fair size."""
    if threshold is None:
        vals = [g["a"][key] for g in games if g["a"].get(key) is not None]
        if len(vals) < 6:
            return None
        threshold = st.median(vals)
    bad = [g for g in games if g["a"].get(key) is not None and
           (g["a"][key] >= threshold if worse_if_higher else g["a"][key] <= threshold)]
    good = [g for g in games if g["a"].get(key) is not None and g not in bad]
    if len(bad) < 3 or len(good) < 3:
        return None
    pb, pg = st.mean(g["placement"] for g in bad), st.mean(g["placement"] for g in good)
    return {"n_bad": len(bad), "n_good": len(good), "place_bad": round(pb, 2), "place_good": round(pg, 2),
            "diff": round(pb - pg, 2), "share": round(len(bad) / (len(bad) + len(good)), 2)}


def improve_report(games: list[dict]) -> dict:
    """Rank habits by estimated places lost per game. `games` = your solo games (pipeline dicts)."""
    games = [g for g in games if g.get("placement") and g.get("turns")]
    mmr = player_mmr(sorted(games, key=lambda g: g.get("start") or ""))
    bracket = meta.bracket_for(mmr)
    hm = meta.heroes(bracket)
    rows = [{"file": g["file"], "start": g.get("start"), "hero": g.get("hero"), "placement": g["placement"],
             "a": game_analysis(g, bracket)} for g in games]
    n = len(rows)
    habits = []

    # 1. hero choice (meta, direct estimate)
    hp = [r for r in rows if r["a"].get("hero_pick")]
    if hp:
        losses = [r["a"]["hero_pick"]["loss"] for r in hp]
        worst = sorted(hp, key=lambda r: -r["a"]["hero_pick"]["loss"])[:3]
        habits.append({
            "id": "hero_pick", "evidence": "meta", "cost": round(st.mean(losses), 2), "n": len(hp),
            "title": "Hero choice",
            "finding": f"Your picks average {st.mean(r['a']['hero_pick']['picked_avg'] for r in hp):.2f} expected "
                       f"placement; the best hero offered averaged {st.mean(r['a']['hero_pick']['best_avg'] for r in hp):.2f}.",
            "detail": f"In {sum(r['a']['hero_pick']['clear'] for r in hp)} of {len(hp)} games you took a hero "
                      f"clearly worse (at top-{bracket}% MMR, beyond chance) than the best one offered.",
            "advice": "Unless you have a specific plan, take the hero with the best average placement at your MMR "
                      "(shown on each game page).",
            "examples": [{"file": r["file"], "picked": r["hero"], "best": r["a"]["hero_pick"]["best"],
                          "loss": r["a"]["hero_pick"]["loss"]} for r in worst],
        })

    # 2. Discover / triple / Dark Gift picks (meta, direct estimate; correlational per card)
    pk = [r for r in rows if r["a"]["picks"]]
    if pk:
        per_game = [r["a"]["pick_loss"] for r in pk]
        allp = [p | {"file": r["file"]} for r in pk for p in r["a"]["picks"]]
        big = sorted([p for p in allp if p.get("clear")], key=lambda p: -p["loss"])
        habits.append({
            "id": "picks", "evidence": "meta", "cost": round(st.mean(per_game) / 3, 2), "n": len(allp),
            "title": "Discover / triple / Dark Gift picks",
            "finding": f"{len(big)} of {len(allp)} picks were clearly worse than another option offered that fit "
                       f"your build as well (≥0.25 places, beyond chance, at your MMR on that turn).",
            "detail": "Card stats are correlations (strong players pick strong cards), so the cost is shown at ⅓ weight.",
            "advice": "Before picking, check the option that wins most on that turn; the game page shows each option's number.",
            "examples": big[:3],
        })

    # 3. board strength vs same hero, by phase (meta comparison + your own outcome split)
    for ph, label in (("early", "rounds 1–5"), ("mid", "rounds 6–9"), ("late", "rounds 10+")):
        vals = [r["a"]["strength_phase"][ph] for r in rows if r["a"]["strength_phase"][ph] is not None]
        if len(vals) < 5:
            continue
        for r in rows:
            r["a"][f"str_{ph}"] = r["a"]["strength_phase"][ph]
        sp = _split(rows, f"str_{ph}", 0.8, worse_if_higher=False)
        med = st.median(vals)
        habits.append({
            "id": f"strength_{ph}", "evidence": "meta+yours", "cost": round(sp["diff"] * sp["share"], 2) if sp else 0,
            "n": len(vals), "title": f"Board strength, {label}",
            "finding": f"Your board in {label} is typically {med:.0%} of what players on the same hero at your MMR have.",
            "detail": (f"Games where it was under 80%: average place {sp['place_bad']} ({sp['n_bad']} games) vs "
                       f"{sp['place_good']} otherwise ({sp['n_good']} games).") if sp else "Not enough games to split.",
            "advice": {"early": "Early on, prioritise buying stats/tempo over economy setups; don't skip combats with an empty board.",
                       "mid": "Mid game is where your board falls behind most often: commit to a direction and spend all gold each turn.",
                       "late": "Late game: find your scaling engine/triples earlier; levels alone don't win fights."}[ph],
            "median": med,
        })

    # 4. early HP loss: a SYMPTOM (result of weak boards), reported but not ranked as a habit
    symptoms = []
    sp = _split(rows, "hp_lost_by_r8")
    if sp:
        med = st.median(r["a"]["hp_lost_by_r8"] for r in rows if r["a"].get("hp_lost_by_r8") is not None)
        symptoms.append({"title": "HP lost by round 8",
                         "finding": f"You typically lose {med:.0f} HP (incl. armor) by round 8. Games above that: "
                                    f"average place {sp['place_bad']} ({sp['n_bad']} games) vs {sp['place_good']} "
                                    f"({sp['n_good']}).",
                         "note": "This is a result of board strength in rounds 1–8, not a separate habit."})

    # 5. unspent gold (yours)
    sp = _split(rows, "gold_unspent", 4)
    if sp:
        habits.append({"id": "unspent_gold", "evidence": "yours", "cost": round(sp["diff"] * sp["share"], 2),
                       "n": sp["n_bad"] + sp["n_good"], "title": "Gold left unspent",
                       "finding": f"Ending turns with unspent gold (4+ total in a game) happened in {sp['share']:.0%} of games.",
                       "detail": f"Those games: average place {sp['place_bad']} vs {sp['place_good']} otherwise.",
                       "advice": "Spend down to 0 every turn unless you're saving for a specific level next turn."})

    # 6. tempo to tier 5 (yours)
    for r in rows:
        r["a"]["t5_round"] = r["a"]["tier_round"].get(5, 99)
    sp = _split(rows, "t5_round", 10)
    if sp:
        habits.append({"id": "tempo_t5", "evidence": "yours", "cost": round(sp["diff"] * sp["share"], 2),
                       "n": sp["n_bad"] + sp["n_good"], "title": "Reaching tier 5 late (round 10+ or never)",
                       "finding": f"That happened in {sp['share']:.0%} of your games.",
                       "detail": f"Those games: average place {sp['place_bad']} vs {sp['place_good']} otherwise.",
                       "advice": "Aim for tier 5 by round 8–9 when your HP allows it."})

    habits.sort(key=lambda h: -h["cost"])
    # trend of every phase metric, oldest -> newest, to see whether the focus is improving
    trend = [{"file": r["file"], "start": r["start"], "placement": r["placement"], "hero": r["hero"],
              "early": r["a"]["strength_phase"]["early"], "mid": r["a"]["strength_phase"]["mid"],
              "late": r["a"]["strength_phase"]["late"], "pick_loss": r["a"]["pick_loss"],
              "hero_loss": (r["a"].get("hero_pick") or {}).get("loss")}
             for r in sorted(rows, key=lambda r: r["start"] or "")]
    costly = [h for h in habits if h["cost"] >= 0.1]
    fine = [h for h in habits if h["cost"] < 0.1]
    for h in fine:  # not costing you, or linked to your BETTER games: keep, don't "fix"
        h["keep"] = True
    return {"games": n, "mmr": mmr, "bracket": bracket, "bracket_mmr": hm.mmr_floor,
            "meta_updated": hm.updated, "meta_games": hm.games,
            "avg_placement": round(st.mean(r["placement"] for r in rows), 2) if rows else None,
            "habits": costly, "not_costing": fine, "symptoms": symptoms, "trend": trend,
            "focus": costly[0] if costly else None}


# ------------------------------------------------------------------ decision-first coach report
def _median(vals):
    vals = [v for v in vals if v is not None]
    return round(st.median(vals), 2) if vals else None


def stats_table(rows: list[dict]) -> list[dict]:
    """Your numbers, side by side with your top-4 / bottom-4 games and the meta. No advice."""
    top = [r for r in rows if r["placement"] <= 4]
    bot = [r for r in rows if r["placement"] >= 5]

    def col(fn, group, mean=False):
        vals = [v for v in (fn(r) for r in group) if v is not None]
        if mean:
            return round(sum(vals) / len(vals), 2) if vals else None
        return _median(vals)

    metrics = [
        ("Average placement", lambda r: r["placement"], None, "lower is better"),
        ("Round you reach tier 4", lambda r: r["a"]["tier_round"].get(4), None, "median"),
        ("Round you reach tier 5", lambda r: r["a"]["tier_round"].get(5), None, "median, games that got there"),
        ("Round you reach tier 6", lambda r: r["a"]["tier_round"].get(6), None, "median, games that got there"),
        ("Board vs same hero, rounds 1–5", lambda r: r["a"]["strength_phase"]["early"], 1.0, "100% = meta average"),
        ("Board vs same hero, rounds 6–9", lambda r: r["a"]["strength_phase"]["mid"], 1.0, "100% = meta average"),
        ("Board vs same hero, rounds 10+", lambda r: r["a"]["strength_phase"]["late"], 1.0, "100% = meta average"),
        ("HP lost by round 8", lambda r: r["a"]["hp_lost_by_r8"], None, "incl. armor"),
        ("Refreshes per game", lambda r: r["a"]["refreshes"], None, ""),
        ("Gold left unspent per game", lambda r: r["a"]["gold_unspent"], None, "summed over turns"),
        ("Hero pick vs best offered", lambda r: (r["a"].get("hero_pick") or {}).get("loss"), 0.0, "places, 0 = best pick"),
        ("Fights lost while favoured (bad luck)", lambda r: len(r["a"]["luck"]["unlucky_losses"])
         if r["a"]["luck"]["fights_with_odds"] else None, None, "Bob's Buddy ≥50% to win, per game"),
        ("Fights won as underdog (good luck)", lambda r: len(r["a"]["luck"]["lucky_wins"])
         if r["a"]["luck"]["fights_with_odds"] else None, None, "Bob's Buddy ≥50% to lose, per game"),
    ]
    out = []
    for name, fn, meta_v, note in metrics:
        m = "luck" in name  # counts per game: an average says more than a median of mostly zeros
        out.append({"metric": name, "you": col(fn, rows, m), "top4": col(fn, top, m), "bottom4": col(fn, bot, m),
                    "meta": meta_v, "note": note, "pct": "Board" in name})
    return out


def coach_report(games: list[dict], recent: int = 20) -> dict:
    """Decisions to learn from (concrete, with maths) first; your stats as context second."""
    from .decisions import all_decisions
    base = improve_report(games)
    bracket = base["bracket"]
    games = sorted([g for g in games if g.get("placement") and g.get("turns")], key=lambda g: g.get("start") or "")
    rows = [{"file": g["file"], "start": g.get("start"), "hero": g.get("hero"), "placement": g["placement"],
             "a": game_analysis(g, bracket), "g": g} for g in games]
    decisions = []
    for r in rows[-recent:]:
        for d in all_decisions(r["g"], bracket, r["a"]["strength"]):
            decisions.append({**d, "file": r["file"], "start": r["start"], "hero": r["hero"], "placement": r["placement"]})
        hp = r["a"].get("hero_pick")
        if hp and hp.get("clear"):
            decisions.append({"kind": "hero", "round": 0, "file": r["file"], "start": r["start"], "hero": r["hero"],
                              "placement": r["placement"], "you": r["hero"], "you_val": hp["picked_avg"],
                              "better": hp["best"], "better_val": hp["best_avg"], "diff": hp["loss"],
                              "calc": f"At your MMR: your hero averages {hp['picked_avg']}, the best offered "
                                      f"averages {hp['best_avg']}: {hp['loss']:.2f} places better (chance alone "
                                      f"could explain up to {hp['noise']})."})
        for p in r["a"]["picks"]:
            if p.get("clear"):
                decisions.append({"kind": "pick", "round": p["round"], "file": r["file"], "start": r["start"],
                                  "hero": r["hero"], "placement": r["placement"], "you": p["picked"],
                                  "you_val": p["picked_avg"], "better": p["best"], "better_val": p["best_avg"],
                                  "diff": p["loss"], "pick_kind": p["kind"],
                                  "picked_fit": p.get("picked_fit"), "best_fit": p.get("best_fit"),
                                  "calc": f"{p['kind'].replace('_', ' ').title()} on round {p['round']} at your MMR: "
                                          f"your pick {p['picked_avg']}, the other option {p['best_avg']}: "
                                          f"{p['loss']:.2f} places better (chance alone could explain up to "
                                          f"{p['noise']}; {p['picked_n']:,} and {p['best_n']:,} games)."
                                          + (f" You had {p['hp']} HP, so only options adding at least as much to "
                                             f"your board right now were compared." if p.get("low_hp") else "")})

    def weight(d):  # comparable "size" of each moment
        if d["kind"] == "fight":
            return (d.get("damage") or 0) / 10 * (1 - min(d.get("ratio") or 1, 1))
        if d["kind"] == "buy" and d.get("sim"):
            g = d["sim"]["gain"]
            return (d.get("diff") or 0) * (0.3 if g <= 3 else 1) + max(0.0, g) / 100
        return d.get("diff") or 0
    decisions.sort(key=weight, reverse=True)

    # which kind of decision shows up most in your recent games
    kinds = {"buy": "Buys: an affordable, better-performing card was in the shop",
             "pick": "Discover / triple / Dark Gift picks", "hero": "Hero choice",
             "fight": "Fights lost with a board well below the same-hero average",
             "level": "Leveling while behind and low on HP",
             "position": "Minion order: another order of the same minions won clearly more often (simulated)"}
    n_recent = len(rows[-recent:]) or 1
    summary = []
    for k, label in kinds.items():
        ds = [d for d in decisions if d["kind"] == k]
        if ds:
            summary.append({"kind": k, "label": label, "count": len(ds), "per_game": round(len(ds) / n_recent, 2),
                            "total": round(sum(weight(d) for d in ds), 2)})
    summary.sort(key=lambda x: -x["total"])
    return {**{k: base[k] for k in ("games", "mmr", "bracket", "bracket_mmr", "meta_updated", "meta_games",
                                    "avg_placement", "trend")},
            "recent_games": n_recent, "decisions": decisions[:30], "decision_summary": summary,
            "stats": stats_table(rows)}
