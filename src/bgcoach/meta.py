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
from pathlib import Path

from .replay import norm_hero
from .version import DATA, _get

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


class HeroMeta:
    def __init__(self, bracket: int):
        d = _fetch("hero-stats", bracket)
        self.bracket, self.updated, self.games = bracket, d.get("lastUpdateDate"), d.get("dataPoints")
        self.mmr_floor = next((p["mmr"] for p in d.get("mmrPercentiles", []) if p["percentile"] == bracket), None)
        self.heroes = {}
        for h in d["heroStats"]:
            self.heroes[norm_hero(h["heroCardId"])] = {
                "avg": h["averagePosition"], "n": h["dataPoints"],
                "warband": {w["turn"]: w["averageStats"] for w in h.get("warbandStats") or []},
                "combat": {c["turn"]: c["winrate"] for c in h.get("combatWinrate") or [] if c["winrate"] is not None},
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

    def at_turn(self, card_id: str | None, turn: int, min_n: int = 50) -> float | None:
        """Average placement of players who played this card on this turn (None if too few games)."""
        if not card_id:
            return None
        c = self.cards.get(card_id) or self.cards.get(card_id.removesuffix("_G"))
        if not c:
            return None
        for t in (turn, turn - 1, turn + 1):  # neighbouring turns if this one is thin
            v = c["turn"].get(t)
            if v and v[1] >= min_n:
                return v[0]
        return c["avg"] if c["n"] >= min_n * 5 else None


@lru_cache(maxsize=8)
def heroes(bracket: int) -> HeroMeta:
    return HeroMeta(bracket)


@lru_cache(maxsize=8)
def cards(bracket: int) -> CardMeta:
    return CardMeta(bracket)
