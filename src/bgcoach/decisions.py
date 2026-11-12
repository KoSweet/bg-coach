"""Decision-level review: concrete moments with the numbers behind them.

For every BUY we rebuild the shop exactly as it was when you clicked, keep only what you could
afford, and score each card by how players at your MMR do when they play that card on that same
round (Firestone card stats). Synergy matters, so each option also gets a tribe-fit note: an
alternative that doesn't fit your board isn't recommended over one that does. An alternative is
only reported when it is clearly better (beyond the statistics' noise) and, at low HP, adds at
least as much to your board right now: the shared rules are in advice.py.

Also: costly fights (big HP loss with a weak board, and what that turn looked like) and level-ups
judged with the HP and board you had at that moment.

These are evidence for you to judge, not rules: card stats are correlations (strong players pick
strong cards), and the shop can't see what you were planning.
"""
from __future__ import annotations

from collections import Counter

from . import advice, meta
from . import version as V

MINION_COST = 3
MIN_GAMES = 150              # ignore card/turn stats with fewer games than this
FLAG_DIFF = advice.MIN_DIFF  # smallest difference worth reporting (and it must also beat the noise)


def _tribes(card: dict) -> list[str]:
    r = card.get("races") or ([card["race"]] if card.get("race") else [])
    return [x for x in r if x and x != "INVALID"]


def _board_tribes(board: list[dict], db) -> Counter:
    c = Counter()
    for m in board or []:
        for t in _tribes(db.get(m.get("card_id"))):
            if t == "ALL":
                continue
            c[t] += 1
    return c


def _fit(card_id: str, tribes: Counter, db) -> tuple[bool, str]:
    """Does this card fit the board? (shares a tribe that 2+ of your minions have, or is 'ALL')."""
    ts = _tribes(db.get(card_id))
    if "ALL" in ts:
        return True, "all tribes"
    main = {t for t, n in tribes.items() if n >= 2}
    hit = [t for t in ts if t in main]
    if hit:
        return True, f"{hit[0].title()} like {tribes[hit[0]]} of your minions"
    return (not main), ("no tribe synergy yet" if not main else "doesn't match your main tribe")


def _cost(card_id: str, db) -> int:
    c = db.get(card_id)
    return MINION_COST if c.get("type") == "MINION" else int(c.get("cost") or 0)


def buy_decisions(g: dict, bracket: int) -> list[dict]:
    cm = meta.cards(bracket)
    db = V.card_db(g.get("build") or V.current_bg_meta_build())
    out = []
    for t in g.get("turns") or []:
        rnd = t["round"]
        hp = (t["hp"] + (t.get("armor") or 0)) if t.get("hp") is not None else None
        shop = [c["card_id"] for c in t.get("shop") or []]
        board = list(t.get("board") or [])
        acts = t.get("actions") or []
        bought_this_turn = [x.get("target") for x in acts if x["type"] == "BUY"]
        for a in acts:
            if a.get("shop") is not None:
                shop = list(a["shop"])
            typ = a["type"]
            if typ == "REFRESH":
                shop = []  # unknown until the next snapshot
            elif typ == "PLAY" and a.get("card_id"):
                board.append({"card_id": a["card_id"]})
            elif typ == "BUY" and a.get("target"):
                bought = a["target"]
                gold = a.get("gold") or 0
                # a real either/or: you could afford the alternative but not both, and didn't buy it anyway
                cost_b = _cost(bought, db)
                alts = [c for c in shop if c != bought and _cost(c, db) <= gold
                        and gold - cost_b < _cost(c, db) and c not in bought_this_turn]
                if bought in shop:
                    shop.remove(bought)
                s_b = cm.stat(bought, rnd, MIN_GAMES)
                if s_b is None or not alts:
                    continue
                from . import synergy
                ctx = synergy.context([m["card_id"] for m in board], synergy.history_until(g, rnd, a.get("line")))
                lvl_b, why_b = synergy.fit(bought, ctx)
                scored = []
                for c in alts:  # the advice rules (advice.py): fit, survival, then evidence
                    s = cm.stat(c, rnd, MIN_GAMES)
                    if s is None:
                        continue
                    lvl_c, why_c = synergy.fit(c, ctx)
                    if lvl_c < lvl_b or lvl_c == 0:
                        continue  # never suggest a card that fits worse, or one off your build
                    if not advice.survives(bought, c, hp, db):
                        continue  # at low HP, never trade board strength now for a better average
                    scored.append((s.avg, c, why_c, s))
                if not scored:
                    continue
                _, best, why_best, s_best = min(scored)
                if not advice.clearly_better(s_b, s_best):
                    continue
                low = (f" You had {hp} HP, so only cards adding at least as much to your board right now "
                       f"were compared." if advice.low_hp(hp) else "")
                out.append({
                    "kind": "buy", "round": rnd, "gold": gold, "line": a.get("line"), "hp": hp,
                    "you": bought, "you_val": round(s_b.avg, 2), "you_fit": why_b, "you_n": s_b.n,
                    "better": best, "better_val": round(s_best.avg, 2), "better_fit": why_best, "better_n": s_best.n,
                    "diff": round(s_b.avg - s_best.avg, 2), "noise": round(advice.noise(s_b, s_best), 2),
                    "shop": [*alts, bought],
                    "values": {c: (round(v, 2) if (v := cm.at_turn(c, rnd, MIN_GAMES)) is not None else None)
                               for c in [*alts, bought]},
                    "calc": f"Played on round {rnd} at your MMR: {db.name(bought)} → average place {s_b.avg:.2f}; "
                            f"{db.name(best)} → {s_best.avg:.2f}: {advice.explain(s_b, s_best)}.{low}",
                })
    return out


def fight_decisions(g: dict, strength: list[dict], opponents: list[dict] | None = None) -> list[dict]:
    """Fights that cost a lot of HP while your board was behind or the opponent was highrolling,
    with the matchup (their board vs the average for their hero) and what that turn looked like."""
    from .lobby import describe_kw
    by_round = {t["round"]: t for t in g.get("turns") or []}
    opp_by_round = {f["round"]: f for f in opponents or []}
    out = []
    for s in strength:
        c = next((c for c in g.get("combats") or [] if c["round"] == s["round"]), None)
        if not c or c.get("result") != "LOSS" or (c.get("damage_taken") or 0) < 7 or s.get("ratio") is None:
            continue
        opp = opp_by_round.get(s["round"]) or {}
        if s["ratio"] >= 0.9 and not opp.get("highroll"):
            continue  # your board was fine and theirs normal: matchup/luck, not a decision
        bb = s.get("bb")
        if bb and bb["win"] >= 50:
            continue  # Bob's Buddy had you favoured: bad luck, not a decision
        t = by_round.get(s["round"]) or {}
        acts = Counter(a["type"] for a in t.get("actions") or [])
        bits = []
        if acts.get("LEVEL"):
            bits.append("you leveled up this turn")
        if acts.get("REFRESH"):
            bits.append(f"{acts['REFRESH']} refresh(es)")
        bits.append(f"{acts.get('BUY', 0)} buy(s)")
        if isinstance(t.get("gold_end"), int) and t["gold_end"] > 0:
            bits.append(f"{t['gold_end']} gold left unspent")
        hp_before = (c.get("hp_before") or 0) + (c.get("armor_before") or 0)
        them = ""
        if opp.get("stats") is not None:
            them = (f" Their board: {opp['stats']} stats"
                    + (f", {opp['ratio']:.1f}× the average for their hero" if opp.get("ratio") else "")
                    + f" ({describe_kw(opp.get('kw') or {})}).")
            if opp.get("seen_before"):
                sb = opp["seen_before"]
                them += f" You had seen this player on round {sb['round']} ({sb['stats']} stats then)."
        out.append({
            "kind": "fight", "round": s["round"], "damage": c.get("damage_taken"), "hp_before": hp_before,
            "ratio": s["ratio"], "mine": s["mine"], "meta": s["meta"], "opp": c.get("opp_hero"),
            "opp_stats": opp.get("stats"), "opp_ratio": opp.get("ratio"), "highroll": opp.get("highroll", False),
            "opp_kw": opp.get("kw"), "seen_before": opp.get("seen_before"),
            "turn": ", ".join(bits), "line": t.get("line"), "bb": bb,
            "calc": f"Your board {s['mine']} total stats vs {s['meta']:.0f} average for your hero on round {s['round']} "
                    f"= {s['ratio']:.0%}. Lost {c.get('damage_taken')} HP (had {hp_before}).{them}"
                    + (f" Bob's Buddy: {bb['win']:.0f}% win / {bb['tie']:.0f}% tie / {bb['loss']:.0f}% loss." if bb else ""),
        })
    return out


def level_decisions(g: dict, strength: list[dict]) -> list[dict]:
    """Level-ups taken while already behind and low on HP, followed by a costly loss."""
    st = {s["round"]: s for s in strength}
    combats = {c["round"]: c for c in g.get("combats") or []}
    out = []
    for t in g.get("turns") or []:
        if not any(a["type"] == "LEVEL" for a in t.get("actions") or []):
            continue
        rnd = t["round"]
        hp = (t.get("hp") or 0) + (t.get("armor") or 0)
        prev = st.get(rnd - 1, {}).get("ratio")
        c = combats.get(rnd) or {}
        now = st.get(rnd, {}).get("ratio")
        if hp <= 15 and prev is not None and prev < 0.85 and c.get("result") == "LOSS":
            out.append({
                "kind": "level", "round": rnd, "hp": hp, "ratio_before": prev, "ratio_after": now,
                "damage": c.get("damage_taken"), "line": t.get("line"),
                "calc": f"Leveled on round {rnd} with {hp} HP while your board was {prev:.0%} of the average; "
                        f"the board was {now:.0%} at the fight" + (f" and you lost {c.get('damage_taken')} HP." if now is not None else "."),
            })
    return out


def with_simulation(g: dict, ds: list[dict]) -> list[dict]:
    """Attach simulated fight results (whatif cache) and add better-positioning moments."""
    try:
        from .whatif import load
        sim = load(g["file"]) if g.get("file") else None
    except Exception:
        sim = None
    if not sim:
        return ds
    fights = sim.get("fights") or {}
    buys = {(b["round"], b["you"], b["better"]): b for b in sim.get("buys") or []}
    for d in ds:
        if d["kind"] == "buy":
            b = buys.get((d["round"], d["you"], d["better"]))
            if b:
                d["sim"] = b
                if abs(b["gain"]) <= 3:
                    d["sim_note"] = (f"Simulating that fight: {b['you_win']:.0f}% win with your buy, {b['alt_win']:.0f}% "
                                     f"with the other card: no difference for this fight (the card numbers are about "
                                     f"the whole game).")
                elif b["gain"] < 0:
                    d["sim_note"] = (f"Simulating that fight: your board {b['you_win']:.0f}% win, with the other card "
                                     f"{b['alt_win']:.0f}%: your buy was better for this fight (the card numbers are "
                                     f"about the whole game).")
                else:
                    d["sim_note"] = (f"Simulating that fight: your board {b['you_win']:.0f}% win / {b['you_loss']:.0f}% loss; "
                                     f"with the other card {b['alt_win']:.0f}% / {b['alt_loss']:.0f}% ({b['gain']:+.0f} points).")
        elif d["kind"] == "fight" and str(d["round"]) in fights:
            f = fights[str(d["round"])]
            if f.get("trusted"):  # never show a simulation that doesn't reproduce the real fight
                d["sim"] = f
                if f.get("no_counter"):
                    nc = f["no_counter"]
                    d["no_counter"] = nc
            else:
                d["sim_untrusted"] = f.get("trust_why")
    db = None
    fights_by_round = {f["round"]: f for f in ds if f["kind"] == "fight"}
    opp_hero = {c["round"]: c.get("opp_hero") for c in g.get("combats") or []}
    for c in sim.get("counters") or []:
        if db is None:
            db = V.card_db(g.get("build") or V.current_bg_meta_build())
        m = _counter_moment(c, db, fights_by_round.get(c["round"]))
        m["opp"] = m["opp"] or opp_hero.get(c["round"])
        ds.append(m)
    for p in sim.get("positions") or []:
        ds.append({"kind": "position", "round": p["round"], "actual": p["actual"], "order": p["order"],
                   "gain": p["gain"], "base_win": p["base_win"], "best_win": p["best_win"], "diff": p["gain"] / 100,
                   "calc": f"Simulated round {p['round']} fight: your order wins {p['base_win']:.0f}%, "
                           f"this order {p['best_win']:.0f}% ({p['gain']:+.0f} points), same minions."})
    return ds


LINE_WORDS = {"instead": "Instead of {undone}, buy {buy}", "skip_level": "Skip the level-up ({cost} gold), buy {buy}",
              "spare": "With your spare gold{sell}, buy {buy}"}


def _counter_moment(c: dict, db, fight: dict | None) -> dict:
    """A line that would have changed a fight you lost, in a coach's words, with the simulation."""
    from .lobby import KW_WORD
    sell = f" (selling {', '.join(db.name(x) for x in c['sold'])})" if c.get("sold") else ""
    what = LINE_WORDS[c["kind"]].format(undone=db.name(c.get("undone")), buy=db.name(c["buy"]),
                                         cost=c.get("level_cost"), sell=sell)
    kw = [KW_WORD.get(k, k.lower()) for k in c.get("buy_kw") or [] if k in KW_WORD]
    risky = []
    if c["kind"] == "skip_level":
        risky.append("you'd stay a tier lower next turn")
    if c.get("stats_change", 0) < 0:
        risky.append(f"{-c['stats_change']} fewer total stats against everyone else")
    b, n = c["base"], c["new"]
    return {"kind": "counter", "round": c["round"], "line_kind": c["kind"], "buy": c["buy"], "undone": c.get("undone"),
            "sold": c.get("sold") or [], "board": c.get("board"), "pos": c.get("pos"), "buy_kw": kw,
            "base": b, "new": n, "gain": c["gain"], "diff": c["gain"] / 100, "risky": risky,
            "what": what, "opp": (fight or {}).get("opp"), "highroll": (fight or {}).get("highroll", False),
            "calc": f"{what}{' (' + ', '.join(kw) + ')' if kw else ''}, placed {'first' if c.get('pos') == 1 else 'last'}: "
                    f"the same fight simulated goes from {b['win']:.0f}% win / {b['tie']:.0f}% tie / {b['loss']:.0f}% loss "
                    f"to {n['win']:.0f}% / {n['tie']:.0f}% / {n['loss']:.0f}%. The minion was still in your shop when the "
                    f"turn ended. Simulator check for this fight: {c.get('trust')}."
                    + (f" Risky: {', and '.join(risky)}." if risky else "")}


def card_notes(g: dict, bracket: int) -> list[dict]:
    """Card-average comparisons (buys). Context, not advice: averages can't see your situation,
    so each note says what it can't see when the card you took has a situational payoff."""
    db = V.card_db(g.get("build") or V.current_bg_meta_build())
    combats = {c["round"]: c for c in g.get("combats") or []}
    out = []
    for d in with_simulation(g, buy_decisions(g, bracket)):
        if d["kind"] != "buy":
            continue
        text = (db.get(d["you"]).get("text") or "").lower()
        prev = combats.get(d["round"] - 1) or {}
        if "lost your last combat" in text and prev.get("result") == "LOSS":
            d["situational"] = (f"{db.name(d['you'])} pays off after a lost fight, and you had lost round "
                                f"{d['round'] - 1}: the average can't see that.")
        elif "gold" in text and "gold" not in (db.get(d["better"]).get("text") or "").lower():
            d["situational"] = f"{db.name(d['you'])} is an economy card: its value is the gold it makes later, not this fight."
        out.append(d)
    return out


def all_decisions(g: dict, bracket: int, strength: list[dict], opponents: list[dict] | None = None) -> list[dict]:
    """Moments to review: fights (with the matchup), lines that would have changed a lost fight,
    minion order, risky level-ups. Card-average comparisons are separate (card_notes): context only."""
    d = fight_decisions(g, strength, opponents) + level_decisions(g, strength)
    d = with_simulation(g, d)
    countered = {x["round"] for x in d if x["kind"] == "counter"}
    for x in d:
        if x["kind"] == "fight" and x["round"] in countered:
            x["has_counter"] = True
    return sorted(d, key=lambda x: (x["round"], x["kind"] != "fight"))
