"""Regression tests on real archived logs (skipped when the archive isn't present).

Expected values were verified against HDT's BgsLastGames.xml and the MMR change.
"""
import datetime as dt
import gzip
from pathlib import Path

import pytest

from bgcoach.replay import Replay

RAW = Path(r"D:\bg-coach\data\raw\hs")


def _parse(session: str, name: str):
    p = RAW / session / name
    if not p.exists():
        pytest.skip(f"archive missing: {p}")
    date = dt.date(*map(int, session.split("_")[1:4]))
    with gzip.open(p, "rt", encoding="utf-8", errors="replace") as fh:
        return Replay(base_date=date).feed_all(fh)


def test_guff_game_full_record():
    games = _parse("Hearthstone_2026_11_10_00_25_38", "Power_old.log.gz")
    g = games[0]
    assert g.build == 255790 and g.game_type == "GT_BATTLEGROUNDS"
    assert g.hero == "BG20_HERO_242"                       # Guff Runetotem
    assert len(g.hero_offers) == 4
    assert g.placement == 3                                 # HDT: 3, MMR 6648 -> 6689
    assert len(g.turns) == 14
    assert sorted(c["card_id"] for c in g.final_board) == [   # matches HDT FinalBoard
        "BG25_001_G", "BG25_010_G", "BG32_324_G", "BG34_692", "BG36_515"]
    r1 = g.turns[0]
    assert r1["gold"] == 3 and r1["tier"] == 1
    assert [a["type"] for a in r1["actions"]][:2] == ["BUY", "PLAY"]
    # combat results: round 1 win, round 5 loss of 10 (armor), lethal at the end
    assert g.combats[0]["result"] == "WIN"
    assert g.combats[4]["result"] == "LOSS" and g.combats[4]["damage_taken"] == 10
    assert g.combats[-1]["hp_after"] <= 0


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


def test_shop_click_is_not_a_buy():
    # Clicking a shop card only selects it; buys are DragBuy options. BUY count must equal the
    # number of DragBuy / DragBuy_Spell SendOptions in the game.
    games = _parse("Hearthstone_2026_11_10_00_25_38", "Power_old.log.gz")
    g = games[0]
    buys = [a for t in g.turns for a in t["actions"] if a["type"] == "BUY"]
    assert len(buys) == 26
    assert all(a.get("target") for a in buys)


def test_self_checks_pass_and_late_click_not_applied():
    # Every recorded buy/sell/level/play/refresh must have its effect in the log. The one action in
    # the archive that didn't (Ichoron played 0.75 s before the timer ended the turn) is marked.
    games = _parse("Hearthstone_2026_11_09_00_19_19", "Power.log.gz")
    g = next(g for g in games if g.start.strftime("%H:%M") == "00:48")
    assert g.check_failures == []
    assert g.checks_ok > 300
    late = [a for t in g.turns for a in t["actions"] if a.get("applied") is False]
    assert len(late) == 1 and late[0]["type"] == "PLAY" and late[0]["round"] == 9
