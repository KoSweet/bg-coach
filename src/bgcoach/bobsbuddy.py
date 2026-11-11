"""Bob's Buddy odds per fight, read from HDT's own log.

HDT runs Bob's Buddy at the start of every combat and logs:
  3:48:32 PM|Info|BobsBuddyInvoker.RunSimulation >> WinRate=0% (Lethal=0%), TieRate=0%, LossRate=100% (Lethal=0%)
Lines carry only a 12-hour clock time, and HDT names files after when they were *rotated*, so each
file is dated backwards from its last-modified time (the original mtime for archived copies).
We match each of our combats to the simulation that ran within a few seconds of its start.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from .version import DATA

from .paths import HDT_DIR  # noqa: E402

HDT_LOGS = HDT_DIR / "Logs" if HDT_DIR else None  # Windows + HDT only (no odds elsewhere)
ARCHIVE = DATA / "raw" / "hdt" / "logs"
MANIFEST = DATA / "raw" / "manifest.json"
LINE_RE = re.compile(r"^(\d{1,2}):(\d\d):(\d\d) (AM|PM)\|Info\|BobsBuddyInvoker\.RunSimulation >> "
                     r"WinRate=([\d.]+)% \(Lethal=([\d.]+)%\), TieRate=([\d.]+)%, LossRate=([\d.]+)% \(Lethal=([\d.]+)%\)")
TIME_RE = re.compile(r"^(\d{1,2}):(\d\d):(\d\d) (AM|PM)\|")


def _secs(h, m, s, ampm) -> int:
    h = int(h) % 12 + (12 if ampm == "PM" else 0)
    return h * 3600 + int(m) * 60 + int(s)


def _parse(lines: list[str], end: dt.datetime) -> list[dict]:
    """Date every simulation result by walking backwards from the file's end time."""
    out, day, last = [], end.date(), None
    for line in reversed(lines):
        m = TIME_RE.match(line)
        if not m:
            continue
        secs = _secs(*m.groups())
        if last is not None and secs > last + 3600:  # going backwards past midnight
            day -= dt.timedelta(days=1)
        last = secs
        b = LINE_RE.match(line)
        if b:
            t = dt.datetime.combine(day, dt.time()) + dt.timedelta(seconds=secs)
            win, wl, tie, loss, ll = (float(x) for x in b.groups()[4:])
            out.append({"t": t, "win": win, "win_lethal": wl, "tie": tie, "loss": loss, "loss_lethal": ll})
    return out[::-1]


def _sources() -> list[tuple[str, list[str], dt.datetime]]:
    srcs: dict[str, tuple[list[str], dt.datetime]] = {}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    for f in sorted(ARCHIVE.glob("*.txt.gz")):
        name = f.name[:-3]
        orig = next((v for k, v in manifest.items() if k.endswith("\\" + name) or k.endswith("/" + name)), None)
        mtime = dt.datetime.fromtimestamp(orig["sig"][1]) if orig else dt.datetime.fromtimestamp(f.stat().st_mtime)
        srcs[name] = (gzip.open(f, "rt", encoding="utf-8", errors="replace").read().splitlines(), mtime)
    if HDT_LOGS is not None and HDT_LOGS.exists():
        for f in HDT_LOGS.glob("*.txt"):  # live files win (newest content)
            try:
                srcs[f.name] = (f.read_text(encoding="utf-8", errors="replace").splitlines(),
                                dt.datetime.fromtimestamp(f.stat().st_mtime))
            except OSError:
                pass
    return [(k, v[0], v[1]) for k, v in srcs.items()]


@lru_cache(maxsize=1)
def _all(stamp: int) -> list[dict]:
    sims = []
    for _name, lines, end in _sources():
        sims += _parse(lines, end)
    sims.sort(key=lambda x: x["t"])
    return sims


def simulations() -> list[dict]:
    """All Bob's Buddy results (cached; refreshed every 5 minutes)."""
    import time
    return _all(int(time.time() // 300))


def for_combat(t_iso: str | None, sims: list[dict] | None = None) -> dict | None:
    """The simulation that ran at the start of this combat (within -3..+25 s), if any."""
    if not t_iso:
        return None
    t = dt.datetime.fromisoformat(t_iso)
    best, gap = None, None
    for s in sims if sims is not None else simulations():
        d = (s["t"] - t).total_seconds()
        if -3 <= d <= 25 and (gap is None or d < gap):
            best, gap = s, d
    if best is None:
        return None
    return {k: v for k, v in best.items() if k != "t"}


def for_game_combat(g: dict, c: dict, sims: list[dict] | None = None) -> dict | None:
    """Match one combat of a saved game. Uses the exact combat start time when the game has it;
    otherwise the window between your last action of that round and the start of the next round."""
    if c.get("t"):
        return for_combat(c["t"], sims)
    turns = {t["round"]: t for t in g.get("turns") or []}
    t = turns.get(c["round"])
    if not t:
        return None
    times = [a["t"] for a in t.get("actions") or [] if a.get("t")] or [t.get("start")]
    lo = dt.datetime.fromisoformat(max(x for x in times if x))
    nxt = turns.get(c["round"] + 1)
    hi = dt.datetime.fromisoformat(nxt["start"]) if nxt and nxt.get("start") else lo + dt.timedelta(seconds=120)
    for s in sims if sims is not None else simulations():
        if lo - dt.timedelta(seconds=2) <= s["t"] <= hi:
            return {k: v for k, v in s.items() if k != "t"}
    return None
