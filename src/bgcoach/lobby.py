"""The lobby as you could see it: each opponent's boards when you fought them, and the leaderboard
(tier, health, triples) every round.

Only information the game showed you is used: boards from your own fights, and the leaderboard.
Strength is measured against *this lobby*: your board against the boards you actually fought around
that round, and an opponent's board against the other boards you fought then ("highroll" = well above
them). The average for a hero across all games (public statistics) is only a fallback.
"""
from __future__ import annotations

import statistics
from collections import Counter

HIGHROLL = 1.5  # an opponent's board ≥ 1.5× the other boards you fought around that round
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


def tribes(board: list[dict] | None, db) -> list[list]:
    """Their tribes, the way the game sums them up on hover: [["MURLOC", 4], ["BEAST", 2]], most first.
    Worked out from their minions (the log has no tribe tag); dual-type minions count for both."""
    c = Counter()
    for m in board or []:
        card = db.get(m.get("card_id")) if db else {}
        for r in card.get("races") or ([card["race"]] if card.get("race") else []):
            c[r] += 1
    return [[r, n] for r, n in c.most_common()]


def describe_tribes(tr: list[list]) -> str:
    return ", ".join(f"{n} {'all-type' if r == 'ALL' else r.title()}" for r, n in tr) or "no tribe"


def head_to_head(combats: list[dict], lo: int, hi: int) -> float | None:
    """Your board ÷ theirs, summed over your fights on rounds lo..hi: like for like, round by round
    (1.0 = even with the boards you were fighting)."""
    mine = opp = 0
    for c in combats or []:
        if lo <= c["round"] <= hi and c.get("my_board") and c.get("opp_board"):
            mine += stats(c["my_board"])
            opp += stats(c["opp_board"])
    return round(mine / opp, 2) if opp else None


def lobby_level(combats: list[dict], rnd: int, skip_round: int | None = None) -> float | None:
    """The typical board in your lobby around a round: the median of the boards on rounds rnd-1..rnd+1,
    yours included (you're part of the lobby), leaving out the opponent being judged (`skip_round`).
    Widens to rnd-2..rnd+2 when that gives fewer than three boards, so one weak neighbour (a ghost, a
    dying player) can't make a normal board look like a 30× highroll."""
    vals: list[int] = []
    for w in (1, 2):
        vals = [stats(c["opp_board"]) for c in combats or []
                if rnd - w <= c["round"] <= rnd + w and c["round"] != skip_round and c.get("opp_board")]
        vals += [stats(c["my_board"]) for c in combats or [] if rnd - w <= c["round"] <= rnd + w and c.get("my_board")]
        if len(vals) >= 3:
            break
    return statistics.median(vals) if vals else None


def hero_average(hm, hero: str | None, rnd: int) -> float | None:
    """Average board stats of players on this hero on this round (None if unknown)."""
    h = hm.get(hero) if hm and hero else None
    return h["warband"].get(rnd) if h else None


def fights(g: dict, hm=None) -> list[dict]:
    """Every fight with the opponent's side summarised: stats, keywords, vs their hero's average,
    and when you had last seen that player's board."""
    last_seen: dict = {}
    out = []
    combats = g.get("combats") or []
    for c in combats:
        lid = c.get("opp_lobby_id")
        opp = stats(c.get("opp_board"))
        ref = hero_average(hm, c.get("opp_hero"), c["round"])
        level = lobby_level(combats, c["round"], skip_round=c["round"])
        prev = last_seen.get(lid) if lid else None
        f = {"round": c["round"], "lobby_id": lid, "hero": c.get("opp_hero"), "stats": opp,
             "mine": stats(c.get("my_board")), "kw": keywords(c.get("opp_board")),
             # vs the other boards you fought around then; the hero average only when there are none
             "ratio": round(opp / level, 2) if level else (round(opp / ref, 2) if ref else None),
             "vs": "lobby" if level else "hero", "lobby_level": level,
             "hero_ratio": round(opp / ref, 2) if ref else None, "result": c.get("result"),
             "damage_taken": c.get("damage_taken"),
             "seen_before": {"round": prev["round"], "stats": prev["stats"]} if prev else None}
        # a highroll stands out from the lobby *and* beats your board: a board smaller than yours isn't one
        f["highroll"] = bool(f["ratio"] and f["ratio"] >= HIGHROLL and opp >= 1.25 * f["mine"])
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
