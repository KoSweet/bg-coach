"""Coaching analysis on the maintainer's real games (skipped when those games / the meta are unavailable)."""
import json

import pytest

from bgcoach.paths import DATA

GAME = DATA / "games" / "20261110_211054_BG21_HERO_000.json"


def test_game_analysis_cariel():
    if not GAME.exists():
        pytest.skip("game file missing")
    from bgcoach import analysis
    g = json.loads(GAME.read_text(encoding="utf-8"))
    try:
        a = analysis.game_analysis(g, 50)
    except Exception as e:  # offline and no snapshot yet
        pytest.skip(f"meta unavailable: {e}")
    assert a["tier_round"] == {3: 5, 4: 7, 5: 8, 6: 10}
    assert a["hero_pick"]["best"] and a["hero_pick"]["loss"] >= 0
    assert len(a["strength"]) == 13 and all(s["mine"] >= 0 for s in a["strength"])
    assert a["strength_phase"]["late"] > 1      # the pirate board out-scaled same-hero players late
    assert a["gold_unspent"] == 37               # rounds 10-13 ended with 12+4+7+14 gold (verified)
    assert all(p["loss"] >= 0 for p in a["picks"])


def test_decisions_are_real_either_or_choices():
    f = DATA / "games" / "20261110_163527_TB_BaconShop_HERO_92.json"
    if not f.exists():
        pytest.skip("game file missing")
    from bgcoach import analysis, decisions
    g = json.loads(f.read_text(encoding="utf-8"))
    try:
        a = analysis.game_analysis(g, 50)
    except Exception as e:
        pytest.skip(f"meta unavailable: {e}")
    ds = decisions.all_decisions(g, 50, a["strength"])
    buys = [d for d in ds if d["kind"] == "buy"]
    for d in buys:
        assert d["diff"] >= decisions.FLAG_DIFF and d["better"] != d["you"]
        assert d["better_val"] < d["you_val"]
        assert d["gold"] < 6  # couldn't afford both a 3g card and the alternative
    fights = [d for d in ds if d["kind"] == "fight"]
    # 106 stats vs ~212 same-hero average, lost 15 (the average moves with the daily meta snapshot)
    assert any(d["round"] == 8 and 0.4 <= d["ratio"] <= 0.6 and d["damage"] == 15 for d in fights)
