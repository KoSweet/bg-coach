"""The game as it stood at one decision, judged the way a pro judges it.

A pro deciding whether to level (or roll, or hold gold) looks, in this order, at:
1. the next opponent: their tier against yours, whether they've been losing or winning, and the board
   you last saw from them;
2. the lobby: how your board did against the boards you've actually been fighting;
3. health against the damage cap: what one loss can cost this round (5 / 10 / 15 early in the game,
   then the winner's tier plus the tiers of their surviving minions) and where it leaves you;
4. the race: who's already on the next tier;
5. the build: what the next tier holds for your tribe in the pool.

Everything here was on your screen that turn (the leaderboard, the boards you fought, the cap), except
what the next opponent actually had, which is only ever shown as hindsight. No average over other
players' games is used: this lobby is the yardstick.
"""
from __future__ import annotations

import itertools
from collections import Counter

from . import lobby

LINE_HP = 15  # below this, one more loss can end the game


def _hp(t: dict) -> int:
    return (t.get("hp") or 0) + (t.get("armor") or 0)


def _partner(lobby_id: int) -> int:
    """Duos teammates sit in pairs on the leaderboard (1-2, 3-4, ...)."""
    return lobby_id + 1 if lobby_id % 2 else lobby_id - 1


def main_tribe(board: list[dict] | None, db) -> tuple[str | None, int]:
    """Your board's most common tribe and how many minions have it (dual types count for both)."""
    c: Counter = Counter()
    for m in board or []:
        card = db.get(m.get("card_id")) if db else {}
        for r in card.get("races") or ([card["race"]] if card.get("race") else []):
            if r not in ("ALL", "INVALID"):
                c[r] += 1
    if not c:
        return None, 0
    tribe, n = c.most_common(1)[0]
    return tribe, n


def tier_cards(db, tier: int, tribe: str) -> list[str]:
    """Names of the minions of `tribe` that tavern tier `tier` adds (the pool, not tokens)."""
    if not db or not tribe or not hasattr(db, "by_id"):
        return []
    return sorted(c["name"] for c in db.by_id.values()
                  if c.get("isBattlegroundsPoolMinion") and c.get("techLevel") == tier
                  and (tribe in (c.get("races") or []) or "ALL" in (c.get("races") or [])))


def _losses(turns: dict, lobby_id: int, rnd: int, n: int = 3) -> list[int]:
    """What each of a player's last `n` fights before round `rnd` cost them (0 = no loss), oldest first."""
    hps = [((turns.get(r) or {}).get("lobby") or {}).get(str(lobby_id), {}).get("hp") for r in range(rnd - n, rnd + 1)]
    return [max(0, a - b) for a, b in itertools.pairwise(hps) if isinstance(a, int) and isinstance(b, int)]


def _next_opponent(g: dict, rnd: int, turns: dict, combats: dict, db) -> dict | None:
    c = combats.get(rnd) or {}
    lid = c.get("opp_lobby_id")
    t = turns.get(rnd) or {}
    lb = (t.get("lobby") or {}).get(str(lid)) if lid else None
    if not lb:
        return None
    seen = [x for r, x in sorted(combats.items()) if r < rnd and x.get("opp_lobby_id") == lid and x.get("opp_board")]
    last = seen[-1] if seen else None
    lost = _losses(turns, lid, rnd)
    unhurt = 0
    for x in reversed(lost):
        if x:
            break
        unhurt += 1
    name = db.name if db and hasattr(db, "name") else (lambda cid: cid)
    return {"name": name(lb.get("hero") or c.get("opp_hero")), "tier": lb.get("tier") or 1, "hp": lb.get("hp"),
            "lost": lost, "unhurt": unhurt,
            "seen_round": last["round"] if last else None,
            "seen_stats": lobby.stats(last["opp_board"]) if last else None,
            "actual": lobby.stats(c.get("opp_board")) if c.get("opp_board") else None,  # hindsight
            "actual_mine": lobby.stats(c.get("my_board")) if c.get("my_board") else None}


def at(g: dict, rnd: int, strength: list[dict] | None = None, db=None, next_tier: int | None = None) -> dict | None:
    """The situation at the start of round `rnd` (None if that turn wasn't recorded). `next_tier` is the
    tier you went to (default: one up). `strength` is accepted for compatibility; the lobby is read
    from the fights themselves."""
    turns = {t["round"]: t for t in g.get("turns") or []}
    combats = {c["round"]: c for c in g.get("combats") or []}
    t = turns.get(rnd)
    if not t:
        return None
    duos = "DUO" in (g.get("game_type") or "")
    me = t.get("me_lobby")
    lb = t.get("lobby") or {}
    skip = {str(me)} | ({str(_partner(me))} if duos and me else set())
    others = {k: v for k, v in lb.items() if k not in skip and (v.get("hp") or 0) > 0}
    if duos:  # one entry per team: teammates share health and show the same number
        others = {k: v for k, v in others.items() if int(k) % 2 == 1 or str(_partner(int(k))) not in others}
    tier = t.get("tier") or 1
    nxt = next_tier or tier + 1
    board = t.get("board") or t.get("end_board") or []
    tribe, n_tribe = main_tribe(board, db)
    hp = _hp(t)
    fight = combats.get(rnd) or {}
    cap = fight.get("damage_cap")
    cap_known = "damage_cap" in fight  # games parsed before the cap was recorded: unknown, never "no cap"
    return {
        "round": rnd, "duos": duos, "hp": hp, "tier": tier, "next_tier": nxt,
        "board": lobby.stats(board),
        "opp": _next_opponent(g, rnd, turns, combats, db),
        # your board against the boards you fought on the three rounds before this one (what you knew)
        "vs_lobby": lobby.head_to_head(list(combats.values()), rnd - 3, rnd - 1), "lobby_from": max(1, rnd - 3),
        "cap": cap, "cap_known": cap_known,
        "alive": len(others) + 1,
        "more_hp": sum(1 for v in others.values() if (v.get("hp") or 0) > hp),
        "above_tier": sum(1 for v in others.values() if (v.get("tier") or 1) > tier),
        "at_next": sum(1 for v in others.values() if (v.get("tier") or 1) >= nxt),
        "tribe": tribe, "n_tribe": n_tribe,
        "next_tier_cards": tier_cards(db, nxt, tribe) if tribe and nxt <= 7 else [],
    }


def _pct(r: float) -> str:
    return f"{r * 100:.0f}%"


def _who(s: dict) -> str:
    return "teams" if s["duos"] else "players"


def _opp_threat(s: dict) -> str | None:
    """The next opponent, if they were a reason to be careful (what you could see before the fight)."""
    o = s.get("opp")
    if not o:
        return None
    bits = []
    if o["tier"] > s["tier"]:
        bits.append(f"was already on tier {o['tier']} (you on {s['tier']})")
    if o["unhurt"] >= 2:
        bits.append(f"hadn't lost in {o['unhurt']} rounds")
    if o["seen_stats"] and s["round"] - o["seen_round"] <= 4 and o["seen_stats"] > s["board"]:
        bits.append(f"had {o['seen_stats']} stats when you met on round {o['seen_round']}, against your "
                    f"{s['board']} now")
    if not bits:
        return None
    return f"your next opponent, {o['name']}, " + ", ".join(bits)


def _opp_soft(s: dict) -> str | None:
    """The next opponent, if they looked beatable (a reason a level could be afforded)."""
    o = s.get("opp")
    if not o:
        return None
    bits = []
    if o["tier"] < s["tier"]:
        bits.append(f"was on tier {o['tier']}, below you")
    if len(o["lost"]) >= 2 and all(o["lost"][-2:]):
        bits.append(f"had lost their last two fights (−{o['lost'][-2]}, −{o['lost'][-1]})")
    if o["seen_stats"] and s["round"] - o["seen_round"] <= 3 and o["seen_stats"] * 1.2 < s["board"]:
        bits.append(f"had {o['seen_stats']} stats on round {o['seen_round']}, well under your {s['board']}")
    return f"your next opponent, {o['name']}, " + ", ".join(bits) if bits else None


def _hindsight(s: dict) -> str | None:
    o = s.get("opp") or {}
    if o.get("actual") is None or o.get("actual_mine") is None:
        return None
    return f"(They had {o['actual']} stats in that fight, you {o['actual_mine']}.)"


def _weigh(s: dict) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    """Every reason against and for a level, each with a weight: the board and the cost of a loss count
    most, the next opponent, the race and the build count once."""
    against: list[tuple[str, float]] = []
    for_: list[tuple[str, float]] = []
    for text in level_risks(s):
        w = 1.5 if ("of the stats of the boards" in text or "one loss could cost" in text) else 1.0
        if "one loss could cost" in text and s["hp"] - (s.get("cap") or 0) < 10:
            w = 2.0
        against.append((text, w))
    for text in level_support(s):
        for_.append((text, 1.5 if ("of the stats of the boards" in text or "capped at" in text) else 1.0))
    return against, for_


def level_was_fair(s: dict) -> bool:
    """A pro's call: the reasons for the level outweighed the reasons against (a lost fight after a
    fair level is variance, not a mistake)."""
    against, for_ = _weigh(s)
    return sum(w for _, w in for_) > sum(w for _, w in against)


def level_risks(s: dict) -> list[str]:
    """Why levelling was the wrong turn here, in the order a pro checks (empty when nothing argued against it)."""
    out = []
    threat = _opp_threat(s)
    if threat:
        out.append(threat)
    if s.get("vs_lobby") is not None and s["vs_lobby"] < 0.85:
        out.append(f"on rounds {s['lobby_from']}–{s['round'] - 1} your board had only {_pct(s['vs_lobby'])} of the "
                   f"stats of the boards you fought")
    cap = s.get("cap")
    if cap:  # while the cap is on, the only question is where a capped loss leaves you
        if s["hp"] - cap < LINE_HP:
            out.append(f"one loss could cost up to {cap} (this round's damage cap) and leave you at {s['hp'] - cap}")
    elif not s.get("cap_known", True):
        if s["more_hp"] >= max(2, (s["alive"] - 1) // 2):
            out.append(f"{s['more_hp']} of the {s['alive'] - 1} {_who(s)} left had more health than your {s['hp']}")
    elif s["hp"] <= 25 or s["more_hp"] >= max(2, (s["alive"] - 1) // 2):
        out.append(f"there was no damage cap any more (a loss costs their tier plus their surviving minions' "
                   f"tiers), and at {s['hp']} HP {s['more_hp']} of the {s['alive'] - 1} {_who(s)} left had more "
                   f"health than you")
    if s["at_next"] == 0:
        out.append(f"nobody else was on tier {s['next_tier']} yet: there was no race to keep up with")
    tribe, cards = s.get("tribe"), s.get("next_tier_cards") or []
    if tribe and s["n_tribe"] >= 3 and len(cards) <= 1:
        what = f"only {cards[0]}" if cards else "nothing"
        out.append(f"tier {s['next_tier']} adds {what} for your {tribe.title()}s: your build didn't need it yet")
    return out


def level_support(s: dict) -> list[str]:
    """What spoke for levelling, in the same order."""
    out = []
    soft = _opp_soft(s)
    if soft:
        out.append(soft)
    if s.get("vs_lobby") is not None and s["vs_lobby"] >= 1.1:
        out.append(f"your board had {_pct(s['vs_lobby'])} of the stats of the boards you'd been fighting")
    cap = s.get("cap")
    if cap and s["hp"] - cap >= LINE_HP:
        out.append(f"even a loss was capped at {cap}, leaving you at {s['hp'] - cap}")
    if s["at_next"] >= 2:
        out.append(f"{s['at_next']} {_who(s)} were already on tier {s['next_tier']}")
    tribe, cards = s.get("tribe"), s.get("next_tier_cards") or []
    if tribe and s["n_tribe"] >= 3 and len(cards) >= 3:
        out.append(f"tier {s['next_tier']} adds {len(cards)} {tribe.title()}s for your build ({', '.join(cards[:3])})")
    return out


def summary(s: dict) -> str:
    """One line: where you stood when that turn started, next opponent first."""
    parts = []
    o = s.get("opp")
    if o:
        form = (f"no loss in {o['unhurt']}" if o["unhurt"] >= 2 else
                "lost last fight" if o["lost"] and o["lost"][-1] else "")
        parts.append(f"next: {o['name']} (tier {o['tier']}, {o['hp']} HP{', ' + form if form else ''})")
    if s.get("vs_lobby") is not None:
        parts.append(f"your board {_pct(s['vs_lobby'])} of the boards you fought on rounds "
                     f"{s['lobby_from']}–{s['round'] - 1}")
    parts.append(f"{s['hp']} HP" + (f", a loss capped at {s['cap']}" if s.get("cap") else
                                    ", no damage cap" if s.get("cap_known", True) else ""))
    who = _who(s)[:-1] if s["above_tier"] == 1 else _who(s)
    parts.append(f"tier {s['tier']}" + (f", {s['above_tier']} {who} ahead" if s["above_tier"] else ", nobody ahead"))
    if s.get("tribe") and s["n_tribe"] >= 3:
        parts.append(f"{s['n_tribe']} {s['tribe'].title()}s")
    line = f"Round {s['round']}: " + " · ".join(parts)
    hind = _hindsight(s)
    return line + (" " + hind if hind else "")


def join(reasons: list[str]) -> str:
    if not reasons:
        return ""
    if len(reasons) == 1:
        return reasons[0]
    return "; ".join(reasons[:-1]) + "; and " + reasons[-1]
