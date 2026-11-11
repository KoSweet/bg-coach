"""Simulator input building (pure Python; the simulator itself isn't run here)."""
from bgcoach.combat_sim import build_battle


def test_build_battle_from_recorded_fight():
    combat = {"round": 8, "hp_before": 21, "armor_before": 4, "opp_hero": "BG27_HERO_801",
              "my_board": [{"card_id": "BG25_008_G", "atk": 72, "hp": 41, "kw": ["TAUNT"]},
                           {"card_id": "BG32_880", "atk": 18, "hp": 6, "kw": ["REBORN"]}],
              "opp_board": [{"card_id": "BG36_848", "atk": 14, "hp": 9, "kw": ["DIVINE_SHIELD", "WINDFURY"]}]}
    b = build_battle(combat, "BG20_HERO_242", 4)
    me, opp = b["playerBoard"], b["opponentBoard"]
    assert me["player"]["hpLeft"] == 25 and me["player"]["cardId"] == "BG20_HERO_242"
    assert [e["cardId"] for e in me["board"]] == ["BG25_008_G", "BG32_880"]  # order preserved
    assert me["board"][0]["taunt"] and me["board"][1]["reborn"] and not me["board"][0].get("reborn")
    assert opp["board"][0]["divineShield"] and opp["board"][0]["windfury"]
    assert b["gameState"]["currentTurn"] == 8
    # what-if: a different board for the same fight
    alt = build_battle(combat, "BG20_HERO_242", 4, my_board=list(reversed(combat["my_board"])))
    assert [e["cardId"] for e in alt["playerBoard"]["board"]] == ["BG32_880", "BG25_008_G"]
