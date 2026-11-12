"""Population stats ("the meta") from Firestone's public data, snapshotted daily.

- hero-stats: per hero average placement, per-turn average warband stats (atk+hp of the board) and
  combat win rate, split by MMR bracket (top 100/50/25/10/1 %).
- card-stats: per card and per turn, average placement of players who played it vs who didn't.

Snapshots are kept per day under data/meta/<date>/ so history accumulates (patches change things).
These are correlations from many games, not causal truths: used to compare, never to command.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
from functools import lru_cache

from .advice import Stat
from .paths import DATA
from .replay import norm_hero
from .version import _get

META_DIR = DATA / "meta"
URL = "https://static.zerotoheroes.com/api/bgs/{kind}/mmr-{bracket}/last-patch/overview-from-hourly.gz.json"
BRACKETS = (100, 50, 25, 10, 1)


def _fetch(kind: str, bracket: int) -> dict:
    today = dt.date.today().isoformat()
    path = META_DIR / today / f"{kind}-mmr-{bracket}.json.gz"
    if path.exists():
        return json.loads(gzip.decompress(path.read_bytes()))
    try:
        data = json.loads(_get(URL.format(kind=kind, bracket=bracket)))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(gzip.compress(json.dumps(data).encode()))
        return data
    except Exception:
        # offline: newest snapshot we have
        for old in sorted(META_DIR.glob(f"*/{kind}-mmr-{bracket}.json.gz"), reverse=True):
            return json.loads(gzip.decompress(old.read_bytes()))
        raise


def bracket_for(mmr: int | None) -> int:
    """Tightest Firestone bracket the player belongs to (e.g. 6600 MMR -> top 50%)."""
    if not mmr:
        return 100
    pcts = _fetch("hero-stats", 100).get("mmrPercentiles") or []
    best = 100
    for p in pcts:
        if p["percentile"] < best and mmr >= p["mmr"]:
            best = p["percentile"]
    return best


TRIBE_NAME = {11: "UNDEAD", 14: "MURLOC", 15: "DEMON", 17: "MECHANICAL", 18: "ELEMENTAL", 20: "BEAST",
              23: "PIRATE", 24: "DRAGON", 43: "QUILBOAR", 92: "NAGA", 126: "NAGA"}  # Firestone's tribe codes


class HeroMeta:
    def __init__(self, bracket: int):
        d = _fetch("hero-stats", bracket)
        self.bracket, self.updated, self.games = bracket, d.get("lastUpdateDate"), d.get("dataPoints")
        self.mmr_floor = next((p["mmr"] for p in d.get("mmrPercentiles", []) if p["percentile"] == bracket), None)
        self.heroes = {}
        for h in d["heroStats"]:
            dist = {p["rank"]: p["percentage"] for p in h.get("placementDistribution") or []}
            self.heroes[norm_hero(h["heroCardId"])] = {
                "avg": h["averagePosition"], "n": h["dataPoints"],
                "warband": {w["turn"]: w["averageStats"] for w in h.get("warbandStats") or []},
                "combat": {c["turn"]: c["winrate"] for c in h.get("combatWinrate") or [] if c["winrate"] is not None},
                "top4": round(sum(dist.get(r, 0) for r in (1, 2, 3, 4)), 1) if dist else None,
                "first": round(dist.get(1, 0), 1) if dist else None,
                # how the hero's average placement moves when a tribe is in the lobby (negative = better)
                "tribes": {TRIBE_NAME.get(t["tribe"], str(t["tribe"])): t.get("impactAveragePosition")
                           for t in h.get("tribeStats") or [] if t.get("dataPoints", 0) >= 100},
            }

    def get(self, hero: str | None) -> dict | None:
        return self.heroes.get(norm_hero(hero)) if hero else None


class CardMeta:
    def __init__(self, bracket: int):
        d = _fetch("card-stats", bracket)
        self.updated = d.get("lastUpdateDate")
        self.cards = {}
        for c in d["cardStats"]:
            self.cards[c["cardId"]] = {
                "avg": c["averagePlacement"], "n": c["totalPlayed"],
                "turn": {t["turn"]: (t["averagePlacement"], t["totalPlayed"]) for t in c.get("turnStats") or []},
            }

    def stat(self, card_id: str | None, turn: int, min_n: int = 50) -> Stat | None:
        """Average placement of players who played this card on this turn, and how many games that
        rests on (None if too few games)."""
        if not card_id:
            return None
        c = self.cards.get(card_id) or self.cards.get(card_id.removesuffix("_G"))
        if not c:
            return None
        for t in (turn, turn - 1, turn + 1):  # neighbouring turns if this one is thin
            v = c["turn"].get(t)
            if v and v[1] >= min_n:
                return Stat(v[0], v[1])
        return Stat(c["avg"], c["n"]) if c["n"] >= min_n * 5 else None

    def at_turn(self, card_id: str | None, turn: int, min_n: int = 50) -> float | None:
        s = self.stat(card_id, turn, min_n)
        return s.avg if s else None


@lru_cache(maxsize=8)
def heroes(bracket: int) -> HeroMeta:
    return HeroMeta(bracket)


@lru_cache(maxsize=8)
def cards(bracket: int) -> CardMeta:
    return CardMeta(bracket)
