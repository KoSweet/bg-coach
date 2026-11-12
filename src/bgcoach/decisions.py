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


LINE_HP = 15  # the damage cap: above it you survive any single loss before top 4


def keyword_board(board: list[dict] | None) -> bool:
    """A board that wins through keywords, not stats ("scam": venomous, poisonous, divine shields).
    Its stat total says little about its strength, so it is never judged by it."""
    kws = [set(m.get("kw") or []) for m in board or []]
    venom = sum(1 for k in kws if k & {"VENOMOUS", "POISONOUS"})
    shields = sum(1 for k in kws if "DIVINE_SHIELD" in k)
    return venom >= 2 or (venom >= 1 and shields >= 2)


def _keyword_turn(cross: dict, fought: list[tuple], hp) -> dict:
    """Turning point for a keyword board that was losing: told by its fight record, not its stats."""
    r = cross["round"]
    results = [res for _, res in fought]
    record = ", ".join(f"R{x} {res[0]}" for x, res in fought if res)
    return {"kind": "turning", "round": r, "cause": "keyword_lost",
            "what": (f"Round {r}: you dropped from {hp(cross, 'before')} to {hp(cross, 'after')} HP, below 15. Your board "
                     f"wins through keywords (venomous, divine shield), and it lost {results.count('LOSS')} of "
                     f"{len(results)} fights ({record})."),
            "habit": "A keyword board needs more keywords than their answers: add venomous or divine-shield units, "
                     "or the piece that scales them, rather than raw stats.",
            "damage": hp(cross, "before") - hp(cross, "after"), "ratios": [], "levels": [],
            "opp": cross.get("opp_hero"), "hp_before": hp(cross, "before"), "hp_after": hp(cross, "after")}


def _transition(cross: dict, combats: list[dict], t: dict) -> dict | None:
    """Stat holders sold on the turn of the fight (to make room for triples, a buy-play-sell engine,
    a new build): what they had fought with the round before, when that left the board far weaker."""
    from .lobby import stats as board_stats
    prev = next((c for c in reversed(combats) if c["round"] < cross["round"] and c.get("my_board")), None)
    if not prev:
        return None
    before, now = board_stats(prev["my_board"]), board_stats(cross.get("my_board") or [])
    left = [m.get("card_id") for m in cross.get("my_board") or []]
    pool, gone = list(prev["my_board"]), []
    for a in t.get("actions") or []:
        cid = a.get("target")
        if a["type"] != "SELL" or not cid:
            continue
        if cid in left:  # sold a copy; one is still on the board
            left.remove(cid)
            continue
        m = next((x for x in pool if x.get("card_id") == cid), None)
        if m:
            pool.remove(m)
            gone.append(m)
    gone_stats = board_stats(gone)
    if not before or now >= 0.6 * before or gone_stats < 0.4 * before:
        return None
    return {"prev": prev["round"], "before": before, "now": now, "gone": gone, "gone_stats": gone_stats}


def _and(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def _transition_turn(cross: dict, tr: dict, combats: list[dict], hp, st: dict, name) -> dict:
    r = cross["round"]
    sold = _and([name(m["card_id"]) for m in sorted(tr["gone"], key=lambda m: -(m["atk"] + m["hp"]))])
    after = [c for c in combats if c["round"] > r][:3]
    won = [c["round"] for c in after if c.get("result") == "WIN"]
    paid = (f" It paid off: you won round{'s' if len(won) > 1 else ''} {_and([str(x) for x in won])} after it, "
            f"but at {hp(cross, 'before')} HP the dip cost you {hp(cross, 'before') - hp(cross, 'after')}."
            if after and won and all(c.get("result") != "LOSS" for c in after) else "")
    out = hp(cross, "after") <= 0
    what = ((f"Round {r}: you were knocked out from {hp(cross, 'before')} HP." if out else
             f"Round {r}: you dropped from {hp(cross, 'before')} to {hp(cross, 'after')} HP, below 15.")
            + f" That turn you sold {sold}, which had fought with {tr['gone_stats']} of your {tr['before']} stats "
              f"on round {tr['prev']}: you went into this fight with {tr['now']}." + paid)
    return {"kind": "turning", "round": r, "cause": "transition", "what": what,
            "habit": ("On a transition turn at 15 HP or less, keep enough on the board to survive the fight: sell a "
                      "stat holder in the same turn you play what replaces it, or wait a turn."),
            "damage": hp(cross, "before") - hp(cross, "after"), "sold": [m["card_id"] for m in tr["gone"]],
            "ratios": [st.get(x) for x in (tr["prev"], r) if st.get(x) is not None], "levels": [],
            "opp": cross.get("opp_hero"), "hp_before": hp(cross, "before"), "hp_after": hp(cross, "after")}


def turning_point(g: dict, strength: list[dict], opponents: list[dict] | None = None, name=None) -> dict | None:
    """Where the game turned, the way a pro reviews it: the fight that took you below 15 HP, what your
    board looked like on the turns before, and what you spent those turns on. None when you never
    crossed the line, or when it was close fights with a normal board (nothing to change)."""
    combats = sorted(g.get("combats") or [], key=lambda c: c["round"])
    hp = lambda c, k: (c.get(f"hp_{k}") or 0) + (c.get(f"armor_{k}") or 0)
    cross = next((c for c in combats if c.get("result") == "LOSS" and hp(c, "before") >= LINE_HP > hp(c, "after")), None)
    if cross is None:
        return None
    r = cross["round"]
    turns = {t["round"]: t for t in g.get("turns") or []}
    st = {s["round"]: s.get("ratio") for s in strength or []}
    opp = {f["round"]: f for f in opponents or []}.get(r) or {}
    window = [x for x in range(max(1, r - 2), r + 1) if x in turns]
    ratios = [st.get(x) for x in window if st.get(x) is not None]
    acts = [a for x in window for a in turns[x].get("actions") or []]
    levels = [a.get("to_tier") for a in acts if a["type"] == "LEVEL"]
    rolls = sum(1 for a in acts if a["type"] == "REFRESH")
    buys = sum(1 for a in acts if a["type"] == "BUY")
    # judge the board by its fights first: one lost fight is not a pattern
    tr = _transition(cross, combats, turns.get(r) or {})
    if tr:  # one decision on that turn (selling the board down), not a pattern: no second loss needed
        return _transition_turn(cross, tr, combats, hp, st, name or (lambda cid: cid))
    fought = [(c["round"], c.get("result")) for c in combats if c["round"] in window]
    results = [res for _, res in fought]
    losses = results.count("LOSS")
    if losses < 2:
        return None
    if keyword_board(cross.get("my_board")):
        return _keyword_turn(cross, fought, hp)  # losing fights, told by its record, never by its stat total
    # behind = the board was under the same-hero average in that fight and clearly behind on some turn
    behind = bool(ratios) and min(ratios) < 0.85 and (st.get(r) if st.get(r) is not None else 1) < 0.9
    # levelled on a turn when the board was already behind (judged by the fight before that turn)
    levelled_behind = any(any(a["type"] == "LEVEL" for a in turns[x].get("actions") or [])
                          and (st.get(x - 1) if st.get(x - 1) is not None else st.get(x) or 1) < 0.85 for x in window)
    if opp.get("highroll") and (st.get(r) or 0) >= 0.9:
        cause, habit = "highroll", ("Against a highroller there's often nothing to fix that turn; protect your HP "
                                    "earlier when the next-opponent card shows one.")
    elif behind and levelled_behind:
        cause, habit = "levelled", ("Before levelling, ask: will I drop below 15 HP if I lose? If yes, spend the "
                                    "turn on stats (stabilize) and level when you're even again.")
    elif behind and rolls + buys >= 8:
        cause, habit = "spent", ("You spent the gold but the board still fell behind: go for big upgrades (a key "
                                 "unit, stats concentrated on one or two minions) instead of many small ones.")
    elif behind and levels:
        cause, habit = "levelled", ("Before levelling, ask: will I drop below 15 HP if I lose? If yes, spend the "
                                    "turn on stats (stabilize) and level when you're even again.")
    elif behind:
        cause, habit = "behind", ("When your board drops below about 80% of the average for your hero, buy fighting "
                                  "power (pairs, big stat units, tavern spells) before anything else.")
    else:
        return None  # normal board, normal opponent: close fights, not a decision
    trend = " → ".join(f"{v:.0%}" for v in ratios)
    did = ", ".join(x for x in (f"levelled {len(levels)}× (to tier {', '.join(map(str, levels))})" if levels else "",
                                f"rolled {rolls}×" if rolls else "", f"bought {buys} minion{'s' if buys != 1 else ''}")
                    if x)
    out = hp(cross, "after") <= 0
    what = ((f"Round {r}: you were knocked out from {hp(cross, 'before')} HP." if out else
             f"Round {r}: you dropped from {hp(cross, 'before')} to {hp(cross, 'after')} HP, below 15.")
            + (f" Their board was a highroll ({opp['ratio']:.1f}× the average for their hero)." if cause == "highroll"
               else f" On rounds {window[0]}–{r} your board was {trend} of the average for your hero, and you {did}."
               + (f" (Their board was also a highroll: {opp['ratio']:.1f}× their hero's average.)" if opp.get("highroll")
                  and opp.get("ratio") else "")))
    return {"kind": "turning", "round": r, "cause": cause, "what": what, "habit": habit,
            "damage": hp(cross, "before") - hp(cross, "after"), "ratios": ratios, "levels": levels,
            "opp": cross.get("opp_hero"), "hp_before": hp(cross, "before"), "hp_after": hp(cross, "after")}


def with_simulation(g: dict, ds: list[dict], opponents: list[dict] | None = None) -> list[dict]:
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
    combats = {c["round"]: c for c in g.get("combats") or []}
    for c in sim.get("counters") or []:
        stake = _stake(combats.get(c["round"]), c["base"]["loss"], c["new"]["loss"])
        if not stake["worth"] or (c["kind"] in ("skip_level", "keep") and not stake["below_line"]):
            continue  # a pro takes small losses for tempo: skipping a level or keeping a minion you sold to
            #           upgrade is only right when the fight cost you the 15 HP line
        if db is None:
            db = V.card_db(g.get("build") or V.current_bg_meta_build())
        m = _counter_moment(c, db, fights_by_round.get(c["round"]))
        m["opp"] = m["opp"] or (combats.get(c["round"]) or {}).get("opp_hero")
        m.update(stake)
        ds.append(m)
    seen = {f["round"]: f.get("seen_before") for f in opponents or []}
    for p in sim.get("positions") or []:
        stake = _stake(combats.get(p["round"]), p.get("base_loss", 100), p.get("best_loss", 100))
        if not seen.get(p["round"]) or not stake["worth"]:
            continue  # without having seen their board you position by default; hindsight isn't a lesson
        sb = seen[p["round"]]
        ds.append({"kind": "position", "round": p["round"], "actual": p["actual"], "order": p["order"],
                   "gain": p["gain"], "base_win": p["base_win"], "best_win": p["best_win"], "diff": p["gain"] / 100,
                   "seen_round": sb["round"], **stake,
                   "calc": f"You had seen this player's board on round {sb['round']}. Against their board, your order "
                           f"wins {p['base_win']:.0f}%, this order {p['best_win']:.0f}% (simulated), same minions: "
                           f"about {stake['saved_hp']:.0f} HP saved."})
    return ds


def _stake(c: dict | None, loss_before: float, loss_after: float) -> dict:
    """What a better line was worth in HP, the currency pros think in. Expected HP saved = the damage
    you took × how much less likely the loss becomes. Worth a lesson when it saves 5+ HP, or 3+ HP
    when that fight took you below 15 (the damage-cap line) or out of the game."""
    c = c or {}
    dmg = c.get("damage_taken") or 0
    after = (c.get("hp_after") or 0) + (c.get("armor_after") or 0)
    saved = round(dmg * max(0.0, loss_before - loss_after) / 100, 1)
    below = c.get("result") == "LOSS" and after < 15
    return {"saved_hp": saved, "hp_after": after, "below_line": below,
            "worth": saved >= 5 or (below and saved >= 3)}


LINE_WORDS = {"instead": "Instead of {undone}, buy {buy}", "skip_level": "Skip the level-up ({cost} gold), buy {buy}",
              "spare": "With your spare gold{sell}, buy {buy}",
              "keep": "Keep {buy} ({stats}) instead of selling it{replace}"}


def _counter_moment(c: dict, db, fight: dict | None) -> dict:
    """A line that would have changed a fight you lost, in a coach's words, with the simulation."""
    from .lobby import KW_WORD
    sold = ", ".join(db.name(x) for x in c.get("sold") or [])
    stats = "/".join(map(str, c.get("buy_stats") or []))
    what = LINE_WORDS[c["kind"]].format(undone=db.name(c.get("undone")), buy=db.name(c["buy"]), stats=stats,
                                         cost=c.get("level_cost"), sell=f" (selling {sold})" if sold else "",
                                         replace=f", in place of {sold}" if sold else "")
    pos, n_board = c.get("pos"), len(c.get("board") or [])
    slot = "first" if pos == 1 else "last" if pos == n_board else f"in slot {pos}"
    where = ("You sold it that turn." if c["kind"] == "keep"
             else "The minion was still in your shop when the turn ended.")
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
            "calc": f"{what}{' (' + ', '.join(kw) + ')' if kw else ''}, placed {slot}: "
                    f"the same fight simulated goes from {b['win']:.0f}% win / {b['tie']:.0f}% tie / {b['loss']:.0f}% loss "
                    f"to {n['win']:.0f}% / {n['tie']:.0f}% / {n['loss']:.0f}%. {where} "
                    f"Simulator check for this fight: {c.get('trust')}."
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
    """Moments to review, judged the way a pro would: by HP at stake, not by one fight's odds.
    - the turning point (where you crossed below 15 HP, and why)
    - lines that would have saved real HP (simulated, with what was in your shop)
    - minion order, only against a board you had already seen
    - playbook habits, and lost fights only against a real highroller (2× their hero's average)
    Card-average comparisons are separate (card_notes): context only."""
    from .playbook import check as playbook_check
    db = V.card_db(g.get("build") or V.current_bg_meta_build())
    fights = [f for f in fight_decisions(g, strength, opponents) if f.get("highroll") and (f.get("opp_ratio") or 0) >= 2]
    tp = turning_point(g, strength, opponents, db.name)
    rules = [x for x in playbook_check(g, db)  # the turning point already says it for that round
             if not (tp and x["rule"] == "level_below_cap" and x["round"] == tp["round"])]
    fights = [f for f in fights if not (tp and f["round"] == tp["round"])]  # the turning point covers it
    d = fights + rules + ([tp] if tp else [])
    d = with_simulation(g, d, opponents)
    countered = {x["round"] for x in d if x["kind"] == "counter"}
    for x in d:
        if x["kind"] in ("fight", "turning") and x["round"] in countered:
            x["has_counter"] = True
    return sorted(d, key=lambda x: (x["round"], x["kind"] != "fight"))
