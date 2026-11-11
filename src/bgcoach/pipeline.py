"""Shared pipeline used by the CLI and the UI: parse logs -> games on disk, matched with HDT."""
from __future__ import annotations

import collections
import datetime as dt
import gzip
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from . import version as V
from .health import game_issues, record_error
from .replay import Game, Replay, norm_hero

DATA = V.DATA
RAW = DATA / "raw"
GAMES_DIR = DATA / "games"
IMPORTED = DATA / "imported.json"
from .paths import HDT_DIR  # noqa: E402

HDT_XML = HDT_DIR / "BgsLastGames.xml" if HDT_DIR else None  # Windows + HDT only


def open_log(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, encoding="utf-8", errors="replace")


def base_date_for(path: Path) -> dt.date:
    m = re.search(r"(20\d\d)[_-]?(\d\d)[_-]?(\d\d)", str(path))
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return dt.date.fromtimestamp(path.stat().st_mtime)


def archived_logs() -> list[Path]:
    return (sorted(RAW.glob("hs/*/Power*.log.gz")) + sorted(RAW.glob("hs/*/Power*.log.v*.gz"))
            + sorted(RAW.glob("hs/*/Power*.live-*.gz"))  # copies written by the live watcher
            + sorted(RAW.glob("legacy/real_players_logs/*.log.gz")))


# ------------------------------------------------------------------ HDT
def hdt_games() -> list[dict]:
    """All games HDT recorded (live XML + archived snapshots)."""
    sources = ([HDT_XML] if HDT_XML else []) + sorted((RAW / "hdt" / "BgsLastGames").glob("*.xml.gz"))
    out = {}
    for src in sources:
        if not src.exists():
            continue
        try:
            data = gzip.open(src).read() if src.suffix == ".gz" else src.read_bytes()
            root = ET.fromstring(data)
        except Exception as e:  # noqa: BLE001
            record_error("hdt_read", e, source=str(src))
            continue
        for el in root.iter("Game"):
            start = dt.datetime.fromisoformat(el.get("StartTime")[:26]).replace(tzinfo=None)
            out[start] = {
                "start": start.isoformat(), "hero": norm_hero(el.get("Hero")),
                "placement": int(el.get("Placemenent") or 0),
                "rating": int(el.get("Rating") or 0) or None, "rating_after": int(el.get("RatingAfter") or 0) or None,
                "duos": el.get("Duos") == "true",
                "board": sorted(m.findtext("CardId") for m in el.iter("Minion")),
            }
    return sorted(out.values(), key=lambda x: x["start"])


def match_hdt(g: dict, hdt: list[dict]) -> dict | None:
    """HDT stamps StartTime when *it* notices the game, so match same hero within -5..+20 min."""
    if not g.get("start"):
        return None
    start = dt.datetime.fromisoformat(g["start"])
    cands = [h for h in hdt if h["hero"] == norm_hero(g.get("hero"))
             and -300 < (dt.datetime.fromisoformat(h["start"]) - start).total_seconds() < 1200]
    return min(cands, key=lambda h: abs((dt.datetime.fromisoformat(h["start"]) - start).total_seconds()),
               default=None)


# ------------------------------------------------------------------ games on disk
def game_file(g: Game | dict) -> Path:
    start = g.start if isinstance(g, Game) else dt.datetime.fromisoformat(g["start"])
    hero = g.hero if isinstance(g, Game) else g.get("hero")
    return GAMES_DIR / f"{start:%Y%m%d_%H%M%S}_{norm_hero(hero)}.json"


def save_game(g: Game, hdt: list[dict] | None = None) -> Path:
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    d = g.to_dict()
    if hdt is not None:
        d["hdt"] = match_hdt(d, hdt)
    p = game_file(g)
    if p.exists():  # a re-save must never lose what the previous save knew
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            if not d.get("source"):
                d["source"] = old.get("source")
            if not d.get("hdt") and old.get("hdt"):  # e.g. HDT was mid-write when we read its file
                d["hdt"] = old["hdt"]
        except Exception:  # noqa: BLE001
            pass
    p.write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
    return p


def my_account(games: list[dict]) -> int | None:
    """The account HDT recorded the most games for (falls back to the most common account)."""
    with_hdt = collections.Counter(g.get("account") for g in games if g.get("hdt"))
    if with_hdt:
        return with_hdt.most_common(1)[0][0]
    c = collections.Counter(g.get("account") for g in games)
    return c.most_common(1)[0][0] if c else None


def load_games() -> list[dict]:
    games = []
    for p in sorted(GAMES_DIR.glob("*.json")):
        try:
            g = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            record_error("game_file_unreadable", e, file=str(p))
            continue
        g["file"] = p.name
        games.append(g)
    acct = my_account(games)
    for g in games:
        g["mine"] = g.get("account") == acct
        g["issues"] = game_issues(g)
    return games


def summary(g: dict) -> dict:
    hdt = g.get("hdt") or {}
    return {
        "file": g["file"], "start": g.get("start"), "hero": g.get("hero"), "placement": g.get("placement"),
        "rounds": len(g.get("turns") or []), "build": g.get("build"), "mine": g.get("mine"),
        "duos": "DUO" in (g.get("game_type") or ""),
        "mmr_before": hdt.get("rating"), "mmr_after": hdt.get("rating_after"),
        "errors": sum(i["severity"] == "error" for i in g["issues"]),
        "warnings": sum(i["severity"] == "warn" for i in g["issues"]),
    }


# ------------------------------------------------------------------ import
def _load_imported() -> dict:
    return json.loads(IMPORTED.read_text(encoding="utf-8")) if IMPORTED.exists() else {}


def replay_path(path: Path, on_event: Callable | None = None) -> tuple[list[Game], list[dict]]:
    rp = Replay(base_date=base_date_for(path), on_event=on_event)
    with open_log(path) as fh:
        games = rp.feed_all(fh)
    for g in games:
        g.source = str(path)
    for e in rp.errors:  # persist parse errors with the exact location
        record_error("parse_error", None, error=e["error"], traceback=e["traceback"], source=str(path),
                     line_no=e["line_no"], round=e["round"], line=e["line"])
    return games, rp.errors


def import_all(force: bool = False, progress: Callable[[str], None] = print) -> dict:
    """Parse every archived log not yet imported (or changed). Returns counts."""
    done = {} if force else _load_imported()
    hdt = hdt_games()
    logs = archived_logs()
    stats = collections.Counter()
    for i, p in enumerate(logs, 1):
        sig = [p.stat().st_size, int(p.stat().st_mtime)]
        if done.get(str(p)) == sig:
            stats["skipped"] += 1
            continue
        progress(f"[{i}/{len(logs)}] parsing {p.parent.name}/{p.name}")
        try:
            games, errors = replay_path(p)
        except Exception as e:  # noqa: BLE001
            record_error("import_failed", e, source=str(p))
            stats["failed_logs"] += 1
            continue
        for g in games:
            save_game(g, hdt)
            stats["games"] += 1
        stats["parse_errors"] += len(errors)
        done[str(p)] = sig
        IMPORTED.parent.mkdir(parents=True, exist_ok=True)
        IMPORTED.write_text(json.dumps(done, indent=1), encoding="utf-8")
    # refresh HDT matches on all saved games (HDT may know about games imported earlier)
    for p in GAMES_DIR.glob("*.json"):
        d = json.loads(p.read_text(encoding="utf-8"))
        m = match_hdt(d, hdt)
        if m != d.get("hdt"):
            d["hdt"] = m
            p.write_text(json.dumps(d, indent=1, default=str), encoding="utf-8")
    progress(f"done: {dict(stats)}")
    return dict(stats)


def card_names(obj, db: V.CardDB) -> dict[str, str]:
    """Map of every card id appearing anywhere in obj -> display name."""
    names = {}

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str) and o and o not in names and len(o) < 60:
            c = db.get(o)
            if c:
                names[o] = c.get("name") or o
    walk(obj)
    return names
