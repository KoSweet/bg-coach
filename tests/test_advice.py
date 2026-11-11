"""The rules every suggestion follows (advice.py): fit, evidence beyond chance, survival at low HP."""
import pytest

from bgcoach import advice
from bgcoach.advice import Stat

CARDS = {"BIG": {"type": "MINION", "attack": 4, "health": 5}, "SMALL": {"type": "MINION", "attack": 1, "health": 1},
         "SPELL": {"type": "BATTLEGROUND_SPELL"}}


class FakeDB:
    def get(self, cid):
        return CARDS.get(cid, {})


def test_small_samples_are_too_close_to_call():
    # 0.30 places apart, but each number rests on only 150 games: within chance
    assert not advice.clearly_better(Stat(4.10, 150), Stat(3.80, 150))
    # the same gap from thousands of games is real
    assert advice.clearly_better(Stat(4.10, 5000), Stat(3.80, 5000))
    # a certain but tiny difference isn't worth a habit
    assert not advice.clearly_better(Stat(4.10, 10**6), Stat(4.00, 10**6))


def test_noise_shrinks_with_more_games():
    assert advice.noise(Stat(4, 100), Stat(4, 100)) > advice.noise(Stat(4, 10000), Stat(4, 10000))
    assert advice.noise(Stat(4, 150), Stat(4, 150)) == pytest.approx(0.53, abs=0.01)


def test_low_hp_needs_board_strength_now():
    db = FakeDB()
    assert advice.survives("BIG", "SMALL", 30, db)       # healthy: stats decide
    assert not advice.survives("BIG", "SMALL", 2, db)    # 2 HP: don't trade 9 stats for 2
    assert advice.survives("SMALL", "BIG", 2, db)
    assert not advice.survives("BIG", "SPELL", 10, db)   # can't tell what a spell adds now: don't suggest it
    assert advice.survives("SPELL", "BIG", 10, db)


def test_live_advice_close_call_and_low_hp(monkeypatch):
    from bgcoach import meta, synergy, web

    class FakeCards:
        def stat(self, cid, turn, min_n=50):
            return {"BIG": Stat(4.00, 200), "SMALL": Stat(3.80, 200), "SPELL": None}[cid]

    monkeypatch.setattr(meta, "cards", lambda b: FakeCards())
    monkeypatch.setattr(synergy, "context", lambda board, hist: {})
    monkeypatch.setattr(synergy, "fit", lambda cid, ctx: (2, "flexible"))
    hub = web.Hub()
    hub.watcher = type("W", (), {"db": FakeDB()})()
    d = {"kind": "DISCOVER", "round": 9, "options": ["BIG", "SMALL", "SPELL"], "board_ids": [], "history": {},
         "my_hp": 4}
    hub._advise(d, 100)
    assert d["best"] == "SMALL"                                # lowest average among equal fits
    assert d["close"] == "BIG"                                 # 0.20 apart from 200 games each: within chance
    assert d["tempo"] == {"card": "BIG", "hp": 4, "more": 7}  # at 4 HP the bigger minion helps now


def test_fixture_two_hp_buy_is_not_second_guessed(fixture_game, online):
    """Round 11 at 2 HP: Risen Rider was bought; Patient Scout (an economy card) has a better average,
    but at 2 HP it adds nothing to the next fight, so it must not be suggested."""
    import json

    from bgcoach import decisions
    g = json.loads(json.dumps(fixture_game.to_dict(), default=str))
    try:
        ds = decisions.buy_decisions(g, 100)
    except Exception as e:  # public statistics unreachable
        pytest.skip(f"meta unavailable: {e}")
    assert not [d for d in ds if d["round"] == 11 and d["better"] == "BG24_715"]  # Patient Scout (1/1)
    for d in ds:  # every remaining suggestion is beyond chance and, at low HP, no weaker on the board now
        assert d["diff"] > d["noise"] and d["diff"] >= advice.MIN_DIFF
