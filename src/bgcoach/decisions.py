"""Decision-level review: concrete moments with the numbers behind them.

For every BUY we rebuild the shop exactly as it was when you clicked, keep only what you could
afford, and score each card by how players at your MMR do when they play that card on that same
round (Firestone card stats). Synergy matters, so each option also gets a tribe-fit note: an
alternative that doesn't fit your board isn't recommended over one that does.

Also: costly fights (big HP loss with a weak board, and what that turn looked like) and level-ups
judged with the HP and board you had at that moment.

These are evidence for you to judge, not rules: card stats are correlations (strong players pick
strong cards), and the shop can't see what you were planning.
"""
from __future__ import annotations

from collections import Counter

from . import meta
from . import version as V

MINION_COST = 3
MIN_GAMES = 150          # ignore card/turn stats with fewer games than this
FLAG_DIFF = 0.25         # report a buy when an affordable option was this much better


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
                v_b = cm.at_turn(bought, rnd, MIN_GAMES)
                if v_b is None or not alts:
                    continue
                from . import synergy
                ctx = synergy.context([m["card_id"] for m in board], synergy.history_until(g, rnd, a.get("line")))
                lvl_b, why_b = synergy.fit(bought, ctx)
                scored = []
                for c in alts:
                    v = cm.at_turn(c, rnd, MIN_GAMES)
                    if v is None:
                        continue
                    lvl_c, why_c = synergy.fit(c, ctx)
                    if lvl_c < lvl_b or lvl_c == 0:
                        continue  # never suggest a card that fits worse, or one off your build
                    scored.append((v, c, why_c))
                if not scored:
                    continue
                v_best, best, why_best = min(scored)
                diff = round(v_b - v_best, 2)
                if diff >= FLAG_DIFF:
                    out.append({
                        "kind": "buy", "round": rnd, "gold": gold, "line": a.get("line"),
                        "you": bought, "you_val": round(v_b, 2), "you_fit": why_b,
                        "better": best, "better_val": round(v_best, 2), "better_fit": why_best,
                        "diff": diff, "shop": [c for c in alts] + [bought],
                        "values": {c: (round(v, 2) if (v := cm.at_turn(c, rnd, MIN_GAMES)) is not None else None)
                                   for c in alts + [bought]},
                        "calc": f"Played on round {rnd} at your MMR: {db.name(bought)} → average place {v_b:.2f}; "
                                f"{db.name(best)} → {v_best:.2f}. Difference {diff:+.2f} places.",
                    })
    return out


def fight_decisions(g: dict, strength: list[dict]) -> list[dict]:
    """Fights that cost a lot of HP while your board was behind, with what that turn looked like."""
    by_round = {t["round"]: t for t in g.get("turns") or []}
    out = []
    for s in strength:
        c = next((c for c in g.get("combats") or [] if c["round"] == s["round"]), None)
        if not c or c.get("result") != "LOSS" or (c.get("damage_taken") or 0) < 7 or s.get("ratio") is None:
            continue
        if s["ratio"] >= 0.9:
            continue  # board was fine: likely matchup/luck, not a decision
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
        out.append({
            "kind": "fight", "round": s["round"], "damage": c.get("damage_taken"), "hp_before": hp_before,
            "ratio": s["ratio"], "mine": s["mine"], "meta": s["meta"], "opp": c.get("opp_hero"),
            "turn": ", ".join(bits), "line": t.get("line"), "bb": bb,
            "calc": f"Your board {s['mine']} total stats vs {s['meta']:.0f} average for this hero on round {s['round']} "
                    f"= {s['ratio']:.0%}. Lost {c.get('damage_taken')} HP (had {hp_before})."
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
    except Exception:  # noqa: BLE001
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
            d["sim"] = f
    for p in sim.get("positions") or []:
        ds.append({"kind": "position", "round": p["round"], "actual": p["actual"], "order": p["order"],
                   "gain": p["gain"], "base_win": p["base_win"], "best_win": p["best_win"], "diff": p["gain"] / 100,
                   "calc": f"Simulated round {p['round']} fight: your order wins {p['base_win']:.0f}%, "
                           f"this order {p['best_win']:.0f}% ({p['gain']:+.0f} points), same minions."})
    return ds


def all_decisions(g: dict, bracket: int, strength: list[dict]) -> list[dict]:
    d = buy_decisions(g, bracket) + fight_decisions(g, strength) + level_decisions(g, strength)
    d = with_simulation(g, d)
    return sorted(d, key=lambda x: x["round"])
