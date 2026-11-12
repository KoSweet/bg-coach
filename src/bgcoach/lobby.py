"""The lobby as you could see it: each opponent's boards when you fought them, and the leaderboard
(tier, health, triples) every round.

Only information the game showed you is used: boards from your own fights, and the leaderboard.
"Highrolling" compares an opponent's board with the average board of players on the *same hero* on
that round (public statistics), so a hero that is always big early doesn't count as a highroll.
"""
from __future__ import annotations

from collections import Counter

HIGHROLL = 1.5  # board ≥ 1.5× the average for that hero on that round
TECH = ("DIVINE_SHIELD", "VENOMOUS", "POISONOUS", "REBORN", "TAUNT", "WINDFURY", "MEGA_WINDFURY", "CLEAVE")
KW_WORD = {"DIVINE_SHIELD": "divine shield", "VENOMOUS": "venomous", "POISONOUS": "poisonous", "REBORN": "reborn",
           "TAUNT": "taunt", "WINDFURY": "windfury", "MEGA_WINDFURY": "mega-windfury", "CLEAVE": "cleave"}


def stats(board: list[dict] | None) -> int:
    return sum((m.get("atk") or 0) + max(0, m.get("hp") or 0) for m in board or [])


def keywords(board: list[dict] | None) -> dict[str, int]:
    c = Counter(k for m in board or [] for k in m.get("kw") or [] if k in TECH)
    return dict(c)


def describe_kw(kw: dict[str, int]) -> str:
    return ", ".join(f"{n} {KW_WORD.get(k, k.lower())}" for k, n in sorted(kw.items(), key=lambda x: -x[1])) or "no keywords"


def hero_average(hm, hero: str | None, rnd: int) -> float | None:
    """Average board stats of players on this hero on this round (None if unknown)."""
    h = hm.get(hero) if hm and hero else None
    return h["warband"].get(rnd) if h else None


def fights(g: dict, hm=None) -> list[dict]:
    """Every fight with the opponent's side summarised: stats, keywords, vs their hero's average,
    and when you had last seen that player's board."""
    last_seen: dict = {}
    out = []
    for c in g.get("combats") or []:
        lid = c.get("opp_lobby_id")
        opp = stats(c.get("opp_board"))
        ref = hero_average(hm, c.get("opp_hero"), c["round"])
        prev = last_seen.get(lid) if lid else None
        f = {"round": c["round"], "lobby_id": lid, "hero": c.get("opp_hero"), "stats": opp,
             "mine": stats(c.get("my_board")), "kw": keywords(c.get("opp_board")),
             "ratio": round(opp / ref, 2) if ref else None, "result": c.get("result"),
             "damage_taken": c.get("damage_taken"),
             "seen_before": {"round": prev["round"], "stats": prev["stats"]} if prev else None}
        f["highroll"] = bool(f["ratio"] and f["ratio"] >= HIGHROLL)
        out.append(f)
        if lid and c.get("opp_board"):
            last_seen[lid] = f
    return out


def opponent_before(g: dict, lobby_id: int | None, rnd: int, hm=None) -> dict | None:
    """What you knew about a player before fighting them on round `rnd`: their last board you saw
    and their leaderboard entry at the start of that round."""
    if not lobby_id:
        return None
    seen = [f for f in fights(g, hm) if f["lobby_id"] == lobby_id and f["round"] < rnd]
    turn = next((t for t in g.get("turns") or [] if t["round"] == rnd), None)
    lb = ((turn or {}).get("lobby") or {}).get(str(lobby_id))
    if not seen and not lb:
        return None
    return {"last_seen": seen[-1] if seen else None, "leaderboard": lb}
