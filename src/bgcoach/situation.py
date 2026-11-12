"""The game as it stood at one decision: the facts a pro weighs before levelling, rolling or holding gold.

Everything here was on your screen that turn: your health, the leaderboard (everyone's health and
tier), your board against the average for your hero, and what the next tavern tier holds for your
tribe in this lobby. `reasons()` turns them into the plain sentences a coach would say, so a lesson
explains *this* game ("your board was far behind, nobody was on tier 6 yet") instead of a rule.
"""
from __future__ import annotations

from collections import Counter

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


def tier_cards(db, tier: int, tribe: str, lobby_tribes: list[str] | None = None) -> list[str]:
    """Names of the minions of `tribe` that tavern tier `tier` adds (the pool, not tokens)."""
    if not db or not tribe or not hasattr(db, "by_id"):
        return []
    return sorted(c["name"] for c in db.by_id.values()
                  if c.get("isBattlegroundsPoolMinion") and c.get("techLevel") == tier
                  and (tribe in (c.get("races") or []) or "ALL" in (c.get("races") or [])))


def at(g: dict, rnd: int, strength: list[dict] | None = None, db=None, next_tier: int | None = None) -> dict | None:
    """The situation at the start of round `rnd` (None if that turn wasn't recorded). `next_tier` is the
    tier you went to (default: one up)."""
    turns = {t["round"]: t for t in g.get("turns") or []}
    t = turns.get(rnd)
    if not t:
        return None
    duos = "DUO" in (g.get("game_type") or "")
    me = t.get("me_lobby")
    lobby = t.get("lobby") or {}
    skip = {str(me)} | ({str(_partner(me))} if duos and me else set())
    others = {k: v for k, v in lobby.items() if k not in skip and (v.get("hp") or 0) > 0}
    if duos:  # one entry per team: teammates share health and show the same number
        others = {k: v for k, v in others.items() if int(k) % 2 == 1 or str(_partner(int(k))) not in others}
    st = {s["round"]: s.get("ratio") for s in strength or []}
    tier = t.get("tier") or 1
    board = t.get("board") or t.get("end_board") or []
    tribe, n_tribe = main_tribe(board, db)
    hp = _hp(t)
    nxt = next_tier or tier + 1
    return {
        "round": rnd, "duos": duos, "hp": hp, "tier": tier,
        "alive": len(others) + 1,
        "others_hp": sorted(v.get("hp") or 0 for v in others.values()),
        "more_hp": sum(1 for v in others.values() if (v.get("hp") or 0) > hp),
        "others_low": sum(1 for v in others.values() if (v.get("hp") or 0) < LINE_HP),
        "above_tier": sum(1 for v in others.values() if (v.get("tier") or 1) > tier),
        "at_next": sum(1 for v in others.values() if (v.get("tier") or 1) >= nxt), "next_tier": nxt,
        "ratio": st.get(rnd - 1),   # the board you came into this turn with (its last fight)
        "ratio_now": st.get(rnd),   # the board you fought with this round
        "tribe": tribe, "n_tribe": n_tribe,
        "next_tier_cards": tier_cards(db, nxt, tribe) if tribe and nxt <= 7 else [],
    }


def _pct(r: float) -> str:
    return f"{r * 100:.0f}%"


def board_words(ratio: float | None) -> str | None:
    if ratio is None:
        return None
    if ratio < 0.6:
        return f"far too weak ({_pct(ratio)} of the average board for your hero)"
    if ratio < 0.85:
        return f"behind ({_pct(ratio)} of the average board for your hero)"
    if ratio >= 1.15:
        return f"ahead ({_pct(ratio)} of the average board for your hero)"
    return f"about even ({_pct(ratio)} of the average board for your hero)"


def level_risks(s: dict) -> list[str]:
    """Why levelling was the wrong turn here, in this game's terms (empty when nothing argued against it)."""
    out = []
    if s.get("ratio") is not None and s["ratio"] < 0.85:
        out.append(f"your board was {board_words(s['ratio'])}")
    if s["more_hp"] >= max(2, (s["alive"] - 1) // 2):
        out.append(f"{s['more_hp']} of the {s['alive'] - 1} {'teams' if s['duos'] else 'players'} left had more "
                   f"health than your {s['hp']}, so you were the one who could least afford a loss")
    if s["at_next"] == 0:
        out.append(f"nobody else was on tier {s['next_tier']} yet: there was no race to keep up with")
    tribe, cards = s.get("tribe"), s.get("next_tier_cards") or []
    if tribe and s["n_tribe"] >= 3 and len(cards) <= 1:
        what = f"only {cards[0]}" if cards else "nothing"
        out.append(f"tier {s['next_tier']} adds {what} for your {tribe.title()}s: your build didn't need it yet")
    return out


def level_support(s: dict) -> list[str]:
    """What spoke for levelling (to say a level was fair, or weigh it)."""
    out = []
    if s.get("ratio") is not None and s["ratio"] >= 1.0:
        out.append(f"your board was {board_words(s['ratio'])}")
    if s["at_next"] >= 2:
        out.append(f"{s['at_next']} {'teams' if s['duos'] else 'players'} were already on tier {s['next_tier']}")
    tribe, cards = s.get("tribe"), s.get("next_tier_cards") or []
    if tribe and s["n_tribe"] >= 3 and len(cards) >= 3:
        out.append(f"tier {s['next_tier']} adds {len(cards)} {tribe.title()}s for your build ({', '.join(cards[:3])})")
    return out


def summary(s: dict) -> str:
    """One line: where you stood when that turn started."""
    parts = [f"{s['hp']} HP ({s['more_hp']} of {s['alive'] - 1} {'teams' if s['duos'] else 'players'} above you)",
             f"tier {s['tier']}" + (f", {s['above_tier']} ahead of you" if s["above_tier"] else ", nobody ahead")]
    if s.get("ratio") is not None:
        parts.append(f"board {_pct(s['ratio'])} of your hero's average")
    if s.get("tribe") and s["n_tribe"] >= 3:
        parts.append(f"{s['n_tribe']} {s['tribe'].title()}s")
    return "Round " + str(s["round"]) + ": " + " · ".join(parts)


def join(reasons: list[str]) -> str:
    if not reasons:
        return ""
    if len(reasons) == 1:
        return reasons[0]
    return "; ".join(reasons[:-1]) + "; and " + reasons[-1]
