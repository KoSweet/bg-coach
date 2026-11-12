"""Pro playbook: principles top players teach, checked against what you actually did.

Each rule is something strong players explain in their guides (sources in `SOURCES`, paraphrased),
and each check only fires when the log shows the situation the rule is about. The rules are
fundamentals, not laws: the moment says what happened and why pros usually do it differently,
and you judge.
"""
from __future__ import annotations

TRIPLE_REWARD = "TB_BaconShop_Triples_01"
DARK_GIFTS_FROM = "2026-08-04"  # Season 14 (patch 36.2) added Dark Gifts
DAMAGE_CAP_HP = 15  # before top 4 you can't lose more than 15 in one fight: staying above it = two lives

SOURCES = {
    "jeef_tips": ("JeefHS, 10 PRO Tips to EASILY Hit 10k (2025)", "https://www.youtube.com/watch?v=5qtIFm2-zK4"),
    "jeef_level": ("JeefHS, The ULTIMATE LEVELING GUIDE (2025 Updated)", "https://www.youtube.com/watch?v=tjSsXWdgTvE"),
    "pocky": ("Pocky (11.5k MMR), Battlegrounds guide", "https://hearthstone-decks.net/?p=50353"),
    "shady_basics": ("Shadybunny, The Ultimate Beginner's Guide to Hearthstone Battlegrounds",
                     "https://www.youtube.com/watch?v=0plivGW2PPo"),
    "jeef_heroes": ("JeefHS, Ranking ALL Heroes in Hearthstone Battlegrounds", "https://www.youtube.com/watch?v=Y4sX0oqgWFE"),
    "jeef_pos": ("JeefHS, Positioning Explained by a PRO", "https://www.youtube.com/watch?v=AsnJkEs9880"),
    "jeef_every": ("JeefHS, Rank 1 Battlegrounds Player Explains EVERY Play", "https://www.youtube.com/watch?v=iUKdMA7jO4s"),
    "dark_gifts": ("Blizzard, Developer Insight: Dark Gifts",
                   "https://us.forums.blizzard.com/en/hearthstone/t/battlegrounds-developer-insight-dark-gifts/163606"),
    "game_rules": ("Battlegrounds rules: a triple reward discovers from one tier above your tavern", None),
}

RULES = {
    "early_rolls": ("Rolling in the early game", "jeef_tips",
                    "In the first five turns, build the strongest board for your gold instead of rolling: at most one roll."),
    "tier2_turn2": ("Tier 2 on turn 2", "jeef_level",
                    "Pros level on turn 2 in 80–90% of games; the exceptions are heroes with a 1-gold hero power used every turn."),
    "tier3_turn5": ("Tier 3 by turn 5", "jeef_level",
                    "Never be on tier 2 after turn 5 (unless something like a quest warps the game): you fall behind."),
    "level_below_cap": ("Levelled below the damage cap", "jeef_tips",
                        "Before levelling, ask whether you'll fall below 15 HP. If so, stabilize instead: above 15 you have two lives."),
    "triple_before_level": ("Triple reward played before levelling", "game_rules",
                            "A triple reward discovers from one tier above your tavern. Level first, then play it."),
    "freeze_unused": ("Froze the shop, bought none of it", "pocky",
                      "Freezing costs you a fresh shop: freeze only what you'll pay for next turn."),
    "gold_unspent": ("Gold left unspent", "shady_basics",
                     "Gold doesn't carry over: spend it on a minion, a spell, your hero power, or at worst roll it away."),
    "roll_short": ("Rolled without gold to buy", "jeef_every",
                   "If you can afford a useful buy, don't roll into something you'll only be able to freeze. "
                   "(Rolling your last 1–2 gold is fine: it would be lost anyway.)"),
    "early_order": ("Weak minion leading early", "jeef_pos",
                    "Turns 1–7: highest attack first, lowest last, to win value trades (except shields, summoners "
                    "and Rally minions, which have to attack to work)."),
    "taunt_cleave": ("Taunt in reach of a cleave", "jeef_pos",
                     "With one taunt, put it last (position 7): a cleave then hits one minion, not two."),
    "venom_biggest": ("Biggest minion into venom", "jeef_pos",
                      "Against venomous boards (often Murlocs), put your biggest minion last and spend venoms on small ones."),
    "dark_gifts_unused": ("Dark Gifts left unused", "dark_gifts",
                          "3 gold for a minion from a higher tier with a gift, up to 3 times a game (once per turn). "
                          "Unused ones are value you never got."),
}


def _rule(rule_id: str, rnd: int, what: str, **extra) -> dict:
    title, src, why = RULES[rule_id]
    name, url = SOURCES[src]
    return {"kind": "rule", "rule": rule_id, "round": rnd, "title": title, "what": what, "why": why,
            "source": name, "url": url, "diff": extra.pop("weight", 0.2), **extra}


def frozen_at_end(t: dict, nxt: dict | None) -> bool:
    """Was the shop frozen when the turn ended? The freeze button toggles (a second press unfreezes),
    so count the presses; when the next round's starting shop is known, it must still hold the cards."""
    if sum(1 for a in t.get("actions") or [] if a["type"] == "FREEZE") % 2 == 0:
        return False
    end = [s.get("card_id") for s in t.get("end_shop") or []]
    start = [s.get("card_id") for s in (nxt or {}).get("shop") or []]
    if end and start:
        return all(start.count(c) >= end.count(c) for c in set(end))
    return True


def _paid_refreshes(t: dict) -> int:
    """Refreshes that cost gold (free ones, e.g. from a hero power, don't count)."""
    acts = t.get("actions") or []
    n = 0
    for i, a in enumerate(acts):
        if a["type"] != "REFRESH" or a.get("gold") is None:
            continue
        after = next((x.get("gold") for x in acts[i + 1:] if x.get("gold") is not None), t.get("gold_end"))
        if after is None or after < a["gold"]:
            n += 1
    return n


def _atk(m: dict) -> int:
    return m.get("atk") or 0


def _size(m: dict) -> int:
    return (m.get("atk") or 0) + max(0, m.get("hp") or 0)


def _fine_up_front(m: dict, db) -> bool:
    """Minions that belong up front even with low attack: divine shields, deathrattle/avenge summoners
    (they free space), and minions that work when they attack (Rally: leading makes sure it fires,
    and it fires again on every attack)."""
    if "DIVINE_SHIELD" in (m.get("kw") or []):
        return True
    c = db.get(m.get("card_id")) if db else {}
    mech = set(c.get("mechanics") or [])
    text = (c.get("text") or "").lower()
    return bool({"DEATHRATTLE", "AVENGE", "BACON_RALLY"} & mech) or "summon" in text or "rally" in text \
        or "whenever this attacks" in text or "after this attacks" in text


def _positioning(g: dict, combats: dict, db) -> list[dict]:
    """Positioning rules, checked on fights you lost (where it could have mattered)."""
    out = []
    for r, c in sorted(combats.items()):
        mine, theirs = c.get("my_board") or [], c.get("opp_board") or []
        if c.get("result") != "LOSS" or len(mine) < 2:
            continue
        # early: a low-attack minion leads while a much bigger hitter waits
        if r <= 7 and not _fine_up_front(mine[0], db):
            best = max(mine[1:], key=_atk)
            if _atk(best) >= 2 * max(1, _atk(mine[0])) and _atk(best) - _atk(mine[0]) >= 3:
                out.append(_rule("early_order", r, f"Led with a {_atk(mine[0])}-attack minion while a "
                                                   f"{_atk(best)}-attack one waited in position "
                                                   f"{mine.index(best) + 1}.", weight=0.1, card=mine[0].get("card_id")))
        cleave = any("CLEAVE" in (m.get("kw") or []) for m in theirs)
        taunts = [i for i, m in enumerate(mine) if "TAUNT" in (m.get("kw") or [])]
        if cleave and len(taunts) == 1 and 0 < taunts[0] < len(mine) - 1:
            out.append(_rule("taunt_cleave", r, f"Their board had cleave; your only taunt stood in position "
                                                f"{taunts[0] + 1} of {len(mine)}, with minions on both sides.",
                             weight=0.15))
        venoms = sum(1 for m in theirs if {"VENOMOUS", "POISONOUS"} & set(m.get("kw") or []))
        if venoms >= 2 and len(mine) >= 4:
            big = max(range(len(mine)), key=lambda i: _size(mine[i]))
            if big <= 1 and "DIVINE_SHIELD" not in (mine[big].get("kw") or []):
                out.append(_rule("venom_biggest", r, f"They had {venoms} venomous/poisonous minions; your biggest "
                                                     f"minion ({_size(mine[big])} stats) stood in position {big + 1}.",
                                 weight=0.2, card=mine[big].get("card_id")))
    return out


def _short_rolls(turns: dict) -> list[dict]:
    """A paid roll that left less than a minion's price, then nothing bought and the shop frozen:
    you rolled into something you couldn't afford (rolling for a cheap spell is fine: you'd buy it)."""
    out = []
    for r, t in sorted(turns.items()):
        acts = t.get("actions") or []
        for i, a in enumerate(acts):
            if a["type"] != "REFRESH" or a.get("gold") is None or r <= 2:
                continue
            after = next((x.get("gold") for x in acts[i + 1:] if x.get("gold") is not None), t.get("gold_end"))
            if after is None or after >= a["gold"] or after >= 3 or a["gold"] < 3:
                continue  # free roll, still able to buy, or spare gold that would be lost anyway
            rest = acts[i + 1:]
            if not any(x["type"] in ("BUY", "REFRESH") for x in rest) and frozen_at_end(t, turns.get(r + 1)):
                out.append(_rule("roll_short", r, f"Rolled with {a['gold']} gold (enough to buy), leaving {after}, then "
                                                  f"froze what came up instead of buying.", weight=0.05))
                break
    return out


def check(g: dict, db=None) -> list[dict]:
    """Every playbook rule this game broke, with the round and what happened.
    `db` (card database) refines positioning checks; without it they still run on keywords."""
    turns = {t["round"]: t for t in g.get("turns") or []}
    combats = {c["round"]: c for c in g.get("combats") or []}
    out = []

    early = {r: _paid_refreshes(turns[r]) for r in range(1, 6) if r in turns}
    if sum(early.values()) > 1:
        rounds = ", ".join(f"R{r}×{n}" for r, n in early.items() if n)
        out.append(_rule("early_rolls", max(r for r, n in early.items() if n),
                         f"{sum(early.values())} paid rolls in the first five turns ({rounds}).",
                         weight=0.05 * sum(early.values())))

    t2 = turns.get(2)
    if t2 and t2.get("tier") == 1 and (turns.get(3) or {}).get("tier") == 1:
        used_power = any(a["type"] == "HERO_POWER" for a in t2.get("actions") or [])
        if not used_power:  # the standard exception is a 1-gold hero power you use every turn
            out.append(_rule("tier2_turn2", 2, "You stayed on tier 1 on turn 2 without using your hero power."))

    t6 = turns.get(6)
    if t6 and (t6.get("tier") or 1) < 3 and len(turns) >= 6:
        out.append(_rule("tier3_turn5", 5, f"Still on tier {t6.get('tier')} when turn 6 started.", weight=0.3))

    for r, t in turns.items():
        acts = t.get("actions") or []
        c = combats.get(r) or {}
        hp_start = (t.get("hp") or 0) + (t.get("armor") or 0)
        hp_after = (c.get("hp_after") or 0) + (c.get("armor_after") or 0) if c else None
        levels = [i for i, a in enumerate(acts) if a["type"] == "LEVEL"]
        if levels and r >= 4 and hp_after is not None and hp_start >= DAMAGE_CAP_HP > hp_after > 0 \
                and c.get("result") == "LOSS":
            out.append(_rule("level_below_cap", r,
                             f"Levelled to tier {acts[levels[-1]].get('to_tier') or '?'} at {hp_start} HP, lost "
                             f"{c.get('damage_taken')} and dropped to {hp_after}.", weight=0.3))
        triples = [i for i, a in enumerate(acts) if a["type"] == "CAST" and a.get("card_id") == TRIPLE_REWARD]
        if triples and levels and min(triples) < max(levels):
            tier = acts[min(triples)].get("tier") or t.get("tier")
            if isinstance(tier, int):
                out.append(_rule("triple_before_level", r,
                                 f"Played the triple reward on tier {tier}, then levelled the same turn: it discovered "
                                 f"from tier {tier + 1} instead of tier {tier + 2}.", weight=0.25))
        if r + 1 in turns and frozen_at_end(t, turns[r + 1]):
            frozen = {s.get("card_id") for s in t.get("end_shop") or []}
            nxt = turns[r + 1].get("actions") or []
            bought = set()
            for a in nxt:
                if a["type"] == "REFRESH":
                    break
                if a["type"] == "BUY":
                    bought.add(a.get("target"))
            if frozen and not (frozen & bought):
                out.append(_rule("freeze_unused", r, f"Froze {len(frozen)} cards on round {r}, then bought none of "
                                                     f"them on round {r + 1}.", weight=0.05))

    short = _short_rolls(turns)
    rolled = {x["round"] for x in short}  # that gold is already told as a short roll: one cause, one lesson
    last_round = max(turns) if turns else 0
    left = [(r, t["gold_end"]) for r, t in sorted(turns.items())
            if 3 <= r < last_round and r not in rolled and isinstance(t.get("gold_end"), int) and t["gold_end"] >= 2]
    if left:
        out.append(_rule("gold_unspent", left[0][0], "Ended " + ", ".join(f"round {r} with {gold} gold" for r, gold in left)
                         + " left over.", weight=0.05 * sum(gold for _, gold in left)))
    out += _positioning(g, combats, db)
    out += short

    gifts = [r for r, t in turns.items() for a in t.get("actions") or [] if a["type"] == "DARK_GIFT"]
    last = max(turns) if turns else 0
    season14 = str(g.get("start") or "") >= DARK_GIFTS_FROM or bool(gifts)
    if season14 and last >= 9 and len(gifts) < 3 and (g.get("placement") or 8) >= 3:
        when = f" (used on rounds {', '.join(map(str, gifts))})" if gifts else ""
        out.append(_rule("dark_gifts_unused", last, f"Game ended on round {last} with {3 - len(gifts)} of 3 Dark Gifts "
                                                    f"unused{when}.", weight=0.1 * (3 - len(gifts))))
    return out
