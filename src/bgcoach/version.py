"""Game version + card database.

- Build number comes from the game's own log (`DebugPrintGame BuildNumber=`).
- Build -> patch name via Firestone's public patches.json.
- Card data per exact build from HearthstoneJSON (cached under data/cards/).
"""
from __future__ import annotations

import gzip
import json
import re
import time
import urllib.request
from functools import lru_cache

from . import __version__
from .paths import DATA, HS_LOGS  # shared, cross-platform

CACHE = DATA / "cache"
UA = {"User-Agent": f"bgcoach/{__version__} (+https://github.com/KoSweet/bg-coach)"}
PATCHES_URL = "https://static.zerotoheroes.com/hearthstone/data/patches.json"
HSJSON_URL = "https://api.hearthstonejson.com/v1/{build}/enUS/cards.json"
BLIZZ_BG_URL = "https://hearthstone.blizzard.com/en-us/api/cards?bgCardType={kind}&pageSize=500&page={page}"


def _get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw


def _cached_json(name: str, url: str, max_age_h: float | None) -> object:
    path = CACHE / name
    if path.exists() and (max_age_h is None or time.time() - path.stat().st_mtime < max_age_h * 3600):
        return json.loads(path.read_text(encoding="utf-8"))
    try:
        data = json.loads(_get(url))
    except Exception:
        if path.exists():  # offline: fall back to stale cache
            return json.loads(path.read_text(encoding="utf-8"))
        raise
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


# ---------------------------------------------------------------- patches
@lru_cache(maxsize=1)
def patches() -> dict:
    return _cached_json("patches.json", PATCHES_URL, max_age_h=12)


def patch_for_build(build: int) -> dict:
    """Patch entry for a build (exact match, else the latest patch at or before it)."""
    ps = sorted(patches()["patches"], key=lambda p: p["number"])
    best = None
    for p in ps:
        if p["number"] <= build:
            best = p
    return {**(best or {}), "exact": bool(best and best["number"] == build)}


def current_bg_meta_build() -> int:
    return int(patches()["currentBattlegroundsMetaPatch"])


# ---------------------------------------------------------------- cards
class CardDB:
    def __init__(self, build: int):
        self.build = build
        try:
            cards = _cached_json(f"cards_{build}.json", HSJSON_URL.format(build=build), max_age_h=None)
        except Exception:
            cards = _cached_json("cards_latest.json", HSJSON_URL.format(build="latest"), max_age_h=24)
            self.build = -1
        self.by_id = {c["id"]: c for c in cards}
        self.by_dbf = {c["dbfId"]: c for c in cards if c.get("dbfId")}

    def hero_power(self, hero_id: str | None) -> dict:
        """The hero power card of a Battlegrounds hero ({} if unknown)."""
        return self.by_dbf.get(self.get(hero_id).get("heroPowerDbfId"), {})

    def get(self, card_id: str | None) -> dict:
        if not card_id:
            return {}
        c = self.by_id.get(card_id)
        if c is None:
            c = self.by_id.get(re.sub(r"_SKIN_\w+$", "", card_id), {})
        return c

    def name(self, card_id: str | None) -> str:
        if not card_id:
            return "?"
        return self.get(card_id).get("name") or card_id

    def tier(self, card_id: str | None) -> int | None:
        return self.get(card_id).get("techLevel")


@lru_cache(maxsize=8)
def card_db(build: int) -> CardDB:
    return CardDB(build)


def blizzard_bg_pool() -> dict[str, list[dict]]:
    """Current live BG pool from Blizzard's public card API (cached 12h)."""
    out = {}
    for kind in ("hero", "minion", "spell", "trinket", "anomaly"):
        def fetch(kind=kind):
            cards, page = [], 1
            while True:
                d = json.loads(_get(BLIZZ_BG_URL.format(kind=kind, page=page)))
                cards += d.get("cards", [])
                if page >= d.get("pageCount", 1):
                    return cards
                page += 1
        path = CACHE / f"blizzard_bg_{kind}.json"
        if path.exists() and time.time() - path.stat().st_mtime < 12 * 3600:
            out[kind] = json.loads(path.read_text(encoding="utf-8"))
            continue
        try:
            out[kind] = fetch()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(out[kind]), encoding="utf-8")
        except Exception:
            out[kind] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    return out


# ---------------------------------------------------------------- client
def latest_client_build() -> tuple[int | None, str | None]:
    """Build number from the most recent Hearthstone session log."""
    if not HS_LOGS.exists():
        return None, None
    for session in sorted(HS_LOGS.glob("Hearthstone_*"), reverse=True):
        for name in ("Power.log", "Power_old.log", "Hearthstone.log"):
            f = session / name
            if not f.exists():
                continue
            with open(f, encoding="utf-8", errors="replace") as fh:
                for i, line in enumerate(fh):
                    m = re.search(r"BuildNumber=(\d+)", line)
                    if m:
                        return int(m.group(1)), session.name
                    if i > 200_000:
                        break
    return None, None
