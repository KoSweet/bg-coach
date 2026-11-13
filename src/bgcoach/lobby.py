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

HIGHROLL = 1.5  # an opponent's board ≥ 1.5× the other boards you fought around that round (scaled)
TECH = ("DIVINE_SHIELD", "VENOMOUS", "POISONOUS", "REBORN", "TAUNT", "WINDFURY", "MEGA_WINDFURY", "CLEAVE")
KW_WORD = {"DIVINE_SHIELD": "divine shield", "VENOMOUS": "venomous", "POISONOUS": "poisonous", "REBORN": "reborn",
           "TAUNT": "taunt", "WINDFURY": "windfury", "MEGA_WINDFURY": "mega-windfury", "CLEAVE": "cleave"}


def stats(board: list[dict] | None) -> int:
    return sum((m.get("atk") or 0) + max(0, m.get("hp") or 0) for m in board or [])


DEITY_SHOWN = 0.1  # a Deity counts once it's 20+ stats and at least this share of their board


def deity(c: dict, side: str = "opp") -> dict | None:
    """Their Old God "Deity" in a fight, when it mattered: a hidden secret that joins the fight as a minion
    after `after` of their minions die, grown by Aberrations (Faceless Converter, Dark Puppeteer...).
    Everyone has one (a 1/1 until it's fed), so only a fed one is returned. Its stats are its largest
    during the fight."""
    board = stats(c.get(f"{side}_board"))
    for d in c.get(f"{side}_secrets") or []:
        if d.get("deity"):
            atk, hp = d.get("atk_peak") or d.get("atk") or 0, d.get("hp_peak") or d.get("hp") or 0
            if atk + hp >= max(20, DEITY_SHOWN * board):
                return {"atk": atk, "hp": hp, "after": d.get("after") or 4,
                        "start": [d.get("atk") or 0, d.get("hp") or 0]}
    return None


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


# How a typical board grows, round by round: median warband stats at high MMR (Firestone, Nov 2026).
# Late-game boards double every round, so a board from round 9 is scaled before it's compared with
# one from round 10.
GROWTH = {1: 4, 2: 5, 3: 16, 4: 28, 5: 46, 6: 77, 7: 132, 8: 245, 9: 523, 10: 1101, 11: 2259, 12: 3887,
          13: 5732, 14: 7591, 15: 8758}


FLOOR = 0.5  # the lobby level is never below half the typical board (GROWTH) on that round


def _growth(rnd: int) -> int:
    return GROWTH[min(max(rnd, 1), max(GROWTH))]


def lobby_level(combats: list[dict], rnd: int, skip_round: int | None = None) -> float | None:
    """The typical board in your lobby on round `rnd`: the median of the other boards you fought on rounds
    rnd-1..rnd+1 (widening to ±2, then ±3, until there are three), each scaled to round `rnd` by how boards grow. Left out: the opponent
    being judged (`skip_round`), ghosts and knocked-out players (they can't stand for the lobby), and
    your own board (a weak board of yours would make a normal one look like a highroll). None with fewer
    than three boards: one neighbour isn't a lobby. Never below half the typical board at high MMR on
    that round: a lobby of dying players can't turn a normal board into a "6× highroll"."""
    vals: list[float] = []
    for w in (1, 2, 3):
        vals = [stats(c["opp_board"]) * _growth(rnd) / _growth(c["round"]) for c in combats or []
                if rnd - w <= c["round"] <= rnd + w and c["round"] != skip_round and c.get("opp_board")
                and not (isinstance(c.get("opp_hp_before"), int) and c["opp_hp_before"] <= 0)]
        if len(vals) >= 3:
            break
    if len(vals) < 3:
        return None
    return round(max(statistics.median(vals), FLOOR * _growth(rnd)))


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
