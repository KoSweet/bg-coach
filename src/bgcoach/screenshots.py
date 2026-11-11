"""Hearthstone screenshots as in-game "flags".

Pressing Print Screen in Hearthstone saves `Hearthstone Screenshot MM-DD-YY HH.MM.SS.png` to the
Desktop. The file name carries the exact local time, so each screenshot can be matched to the game
and round it was taken in, with no app interaction needed while playing.
"""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

NAME_RE = re.compile(r"^Hearthstone Screenshot (\d\d)-(\d\d)-(\d\d) (\d\d)\.(\d\d)\.(\d\d)\.png$", re.I)


def screenshot_dirs() -> list[Path]:
    from .paths import screenshot_dirs as _dirs
    return _dirs()


def list_screenshots() -> list[dict]:
    shots = []
    for d in screenshot_dirs():
        for p in d.iterdir():
            m = NAME_RE.match(p.name)
            if m:
                mo, da, yy, h, mi, s = map(int, m.groups())
                shots.append({"path": str(p), "name": p.name,
                              "time": dt.datetime(2000 + yy, mo, da, h, mi, s)})
    return sorted(shots, key=lambda x: x["time"])


def is_screenshot(path: str) -> bool:
    """Only real Hearthstone screenshots in the known folders may be served/attached."""
    p = Path(path)
    return bool(NAME_RE.match(p.name)) and p.exists() and any(
        p.resolve().parent == d.resolve() for d in screenshot_dirs())


def _round_at(game: dict, t: dt.datetime) -> int | None:
    rnd = None
    for turn in game.get("turns") or []:
        if turn.get("start") and dt.datetime.fromisoformat(turn["start"]) <= t:
            rnd = turn["round"]
    return rnd


def for_game(game: dict, shots: list[dict] | None = None) -> list[dict]:
    """Screenshots taken during this game, each tagged with the round it was taken in."""
    if not game.get("start"):
        return []
    start = dt.datetime.fromisoformat(game["start"])
    end = dt.datetime.fromisoformat(game["end"]) if game.get("end") else start + dt.timedelta(hours=1)
    out = []
    for s in shots if shots is not None else list_screenshots():
        if start <= s["time"] <= end + dt.timedelta(seconds=30):
            out.append({"path": s["path"], "name": s["name"], "time": s["time"].isoformat(),
                        "round": _round_at(game, s["time"])})
    return out
