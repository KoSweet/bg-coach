"""When is another option *really* better than what you did? One rule set for every suggestion:
post-game buys, Discover/triple/Dark Gift picks, hero picks, and the live pick advice.

An alternative is suggested only when all three hold:

1. **Fit**: it fits your build at least as well as your choice, and is never off-build
   (synergy.py; a Beast player isn't told to take a Pirate).
2. **Evidence**: players at your MMR place better with it by at least MIN_DIFF places, *and* by more
   than the statistics' own noise. Every average rests on a number of games; two numbers from a
   few hundred games each can differ by 0.3 places by chance alone. Noise = Z standard errors of
   the difference, with the spread of final placements (1–8) as the standard deviation.
3. **Survival**: at LOW_HP or less, it must also add at least as much to your board *right now*
   (printed attack + health). A card that pays off in three turns doesn't help if the next fight
   can knock you out, and the statistics can't see that: players who take economy cards late are
   mostly the ones who are healthy enough to afford them.
"""
from __future__ import annotations

import math
from typing import NamedTuple

PLACEMENT_SD = 2.29  # standard deviation of a final placement spread evenly over 1..8
Z = 2.0              # ~95%: a difference smaller than this many standard errors is "too close to call"
MIN_DIFF = 0.25      # places; smaller differences aren't worth a habit even when certain
LOW_HP = 15          # health + armor at or below which surviving the next fight comes first


class Stat(NamedTuple):
    avg: float  # average final placement (lower is better)
    n: int      # games behind that average


def noise(a: Stat, b: Stat) -> float:
    """How far apart two averages can be by chance (Z standard errors of their difference)."""
    return Z * PLACEMENT_SD * math.sqrt(1 / max(a.n, 1) + 1 / max(b.n, 1))


def clearly_better(mine: Stat, alt: Stat) -> bool:
    """`alt` places better than `mine` by a margin that is both big enough and beyond chance."""
    diff = mine.avg - alt.avg
    return diff >= MIN_DIFF and diff > noise(mine, alt)


def printed_stats(card_id: str | None, db) -> int | None:
    """Attack + health a minion adds to the board when played (None for spells and unknown cards)."""
    c = db.get(card_id) if card_id else {}
    if c.get("type") != "MINION":
        return None
    return (c.get("attack") or 0) + (c.get("health") or 0)


def low_hp(hp: int | None) -> bool:
    return hp is not None and hp <= LOW_HP


def survives(mine: str, alt: str, hp: int | None, db) -> bool:
    """Rule 3: at low HP only an alternative that adds at least as much to the board now."""
    if not low_hp(hp):
        return True
    a, b = printed_stats(alt, db), printed_stats(mine, db)
    return a is not None and (b is None or a >= b)


def explain(mine: Stat, alt: Stat) -> str:
    """'0.31 places better (chance alone: up to 0.12; 4,120 and 9,870 games)'."""
    return (f"{mine.avg - alt.avg:.2f} places better (chance alone could explain up to {noise(mine, alt):.2f}; "
            f"{mine.n:,} and {alt.n:,} games)")
