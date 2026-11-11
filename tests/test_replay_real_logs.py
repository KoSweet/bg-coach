"""Regression tests on the maintainer's archived logs (skipped when that archive isn't present).

Edge cases that the anonymised fixture game doesn't contain. Expected values were verified against
HDT's BgsLastGames.xml and the MMR change. The fixture-based tests are in test_fixture_game.py.
"""
import datetime as dt
import gzip

import pytest

from bgcoach.paths import DATA
from bgcoach.replay import Replay

RAW = DATA / "raw" / "hs"


def _parse(session: str, name: str):
    p = RAW / session / name
    if not p.exists():
        pytest.skip(f"archive missing: {p}")
    date = dt.date(*map(int, session.split("_")[1:4]))
    with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
        return Replay(base_date=date).feed_all(fh)


def test_placement_ignores_post_complete_resort():
    # Loh game: true finish 5th; after STATE=COMPLETE the client re-sorts my hero to 4.
    # (The original case, 11-10 16:35 Y'Shaarj, lived in the log Hearthstone wiped on exit.)
    games = _parse("Hearthstone_2026_11_09_21_42_23", "Power_old.log.gz")
    g = next(g for g in games if g.start.strftime("%H:%M") == "21:43")
    assert g.placement == 5  # HDT: 5, MMR 6619 -> 6605


def test_placement_set_after_lost_event():
    # Eudora game: PLAYSTATE LOST fires before the hero's final leaderboard value (2).
    games = _parse("Hearthstone_2026_11_09_21_42_23", "Power_old.log.gz")
    g = next(g for g in games if g.start.strftime("%H:%M") == "22:27")
    assert g.placement == 2  # HDT: 2, MMR 6634 -> 6700


def test_self_checks_pass_and_late_click_not_applied():
    # Every recorded buy/sell/level/play/refresh must have its effect in the log. The one action in
    # the archive that didn't (Ichoron played 0.75 s before the timer ended the turn) is marked.
    games = _parse("Hearthstone_2026_11_09_00_19_19", "Power.log.gz")
    g = next(g for g in games if g.start.strftime("%H:%M") == "00:48")
    assert g.check_failures == []
    assert g.checks_ok > 300
    late = [a for t in g.turns for a in t["actions"] if a.get("applied") is False]
    assert len(late) == 1 and late[0]["type"] == "PLAY" and late[0]["round"] == 9
