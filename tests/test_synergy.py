"""Synergy rules: never suggest a card that fits the build worse than what was taken."""
import pytest

from bgcoach import synergy

BALINDA, HOOKTUSK, TEMPEST = "BG35_883", "BG36_344", "BG36_708"
# the real round-8 board: 3 Beasts, Treasure Parrot (Beast+Pirate), Fruit Vendor, 2 Bilgewater (Pirate)
BOARD = ["BG36_204", "BG36_210", "BG36_210", "BG36_763", "BG36_346", "BG36_520", "BG36_520"]  # Headhunter Gryphon, 2x Hoarding Hyena, Treasure Parrot, Fruit Vendor, 2x Bilgewater


def _ctx(board, **hist):
    try:
        return synergy.context(board, {"spells_on_minions": 0, "discovers": 0, "goldens": 0, **hist})
    except Exception as e:  # card DB not cached offline
        pytest.skip(f"card db unavailable: {e}")


def test_main_tribe_beats_side_tribe():
    ctx = _ctx(BOARD)  # 3 Beasts, 2 Pirates
    assert ctx["main"] == "BEAST" and ctx["tribes"]["BEAST"] > ctx["tribes"]["PIRATE"]
    lvl_pirate, why = synergy.fit(HOOKTUSK, ctx)
    assert lvl_pirate == 1 and "side tribe" in why


def test_spell_engine_is_flexible_and_rises_with_spells_cast():
    ctx = _ctx(["BG36_204", "BG36_210", "BG36_210"])
    assert synergy.fit(BALINDA, ctx)[0] == 2
    ctx_spells = _ctx(["BG36_204", "BG36_210", "BG36_210"], spells_on_minions=5)
    assert synergy.fit(BALINDA, ctx_spells)[0] == 3


def test_balinda_over_hooktusk_in_a_beast_build():
    # the user's real pick (R8 triple reward): Balinda taken, Hooktusk had the better raw number
    ctx = _ctx(BOARD)
    values = {BALINDA: 3.85, HOOKTUSK: 3.41}
    best, fits = synergy.best_option([BALINDA, HOOKTUSK], values, ctx)
    assert best == BALINDA, fits


def test_main_tribe_card_wins_when_numbers_close():
    ctx = _ctx(["BG36_204", "BG36_210", "BG36_210"])
    beast = "BGS_078"  # a Beast
    best, _ = synergy.best_option([beast, HOOKTUSK], {beast: 3.9, HOOKTUSK: 3.5}, ctx)
    assert best == beast
