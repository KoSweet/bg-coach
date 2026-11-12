"""Reasons from the game itself: the situation at a decision, and the live best order."""
from typing import ClassVar

from bgcoach import playbook, situation, whatif


class DB:
    """A tiny card pool: Undead on tiers 5 and 6, one Beast on tier 6."""
    cards: ClassVar[dict] = {"U1": {"races": ["UNDEAD"]}, "U2": {"races": ["UNDEAD"]}, "U3": {"races": ["UNDEAD"]},
             "T6U": {"name": "Big Undead", "isBattlegroundsPoolMinion": True, "techLevel": 6, "races": ["UNDEAD"]},
             "T6B": {"name": "Big Beast", "isBattlegroundsPoolMinion": True, "techLevel": 6, "races": ["BEAST"]}}
    by_id = cards

    def get(self, cid):
        return self.cards.get(cid, {})

    def name(self, cid):
        return self.cards.get(cid, {}).get("name", cid)


class DB3(DB):
    """The same, with three tier-6 Undead: tier 6 is where this build's payoffs are."""
    cards: ClassVar[dict] = {**DB.cards, **{f"T6U{i}": {"name": f"Undead {i}", "isBattlegroundsPoolMinion": True, "techLevel": 6,
                                        "races": ["UNDEAD"]} for i in range(2)}}
    by_id = cards


def game(my_hp=27, others=(40, 38, 35, 30, 12, 10, 8), tiers=(5, 5, 5, 5, 4, 4, 4), my_tier=5):
    lobby = {str(i + 2): {"hp": hp, "tier": t} for i, (hp, t) in enumerate(zip(others, tiers, strict=True))}
    lobby["1"] = {"hp": my_hp, "tier": my_tier}
    board = [{"card_id": c, "atk": 5, "hp": 5} for c in ("U1", "U2", "U3")]
    t8 = {"round": 8, "hp": my_hp, "armor": 0, "tier": my_tier, "me_lobby": 1, "lobby": lobby, "board": board,
          "actions": [{"type": "LEVEL", "to_tier": 6}]}
    c8 = {"round": 8, "result": "LOSS", "hp_after": my_hp - 15, "armor_after": 0, "damage_taken": 15,
          "my_board": board, "opp_board": []}
    return {"start": "2026-11-12T20:00:00", "placement": 6, "turns": [t8], "combats": [c8]}


def test_situation_reads_the_leaderboard_and_the_pool():
    s = situation.at(game(), 8, [{"round": 7, "ratio": 0.55}], DB(), next_tier=6)
    assert s["hp"] == 27 and s["more_hp"] == 4 and s["at_next"] == 0 and s["tribe"] == "UNDEAD"
    assert s["next_tier_cards"] == ["Big Undead"]
    risks = situation.level_risks(s)
    assert any("far too weak" in r for r in risks)                       # 55% of the hero's average
    assert any("nobody else was on tier 6" in r for r in risks)           # no race to keep up with
    assert any("only Big Undead for your Undeads" in r for r in risks)    # the build didn't need tier 6


def test_level_warning_speaks_about_this_game_and_stays_quiet_when_fair():
    weak = playbook.check(game(), DB(), [{"round": 7, "ratio": 0.55}])
    lvl = next(r for r in weak if r["rule"] == "level_below_cap")
    assert "In this game: your board was far too weak" in lvl["what"] and lvl["context"]
    # board ahead, everyone already on tier 6, a healthy lobby position: a fair level that lost a fight
    fair = game(my_hp=27, others=(20, 18, 16, 30, 12, 10, 8), tiers=(6, 6, 6, 5, 5, 5, 5))
    rules = [r["rule"] for r in playbook.check(fair, DB3(), [{"round": 7, "ratio": 1.3}])]
    assert "level_below_cap" not in rules


def test_order_change_names_the_move():
    a, b, c = {"card_id": "A"}, {"card_id": "B"}, {"card_id": "C"}
    assert whatif.order_change([a, b, c], [c, a, b]) == {"card_id": "C", "to": 1, "of": 3}
    assert whatif.order_change([a, b, c], [c, b, a]) == {"reverse": True, "of": 3}


def test_live_best_order_only_when_clearly_better(monkeypatch):
    from bgcoach import combat_sim, web
    mine = [{"card_id": "SMALL", "atk": 1, "hp": 1}, {"card_id": "BIG", "atk": 9, "hp": 9}]

    def fake_sim(battles):  # BIG first wins 70%, anything else 40%
        out = {}
        for k, bt in battles.items():
            first = bt["playerBoard"]["board"][0]["cardId"]
            w = 70.0 if first == "BIG" else 40.0
            out[k] = {"win": w, "tie": 0.0, "loss": 100 - w}
        return out
    monkeypatch.setattr(combat_sim, "simulate", fake_sim)
    opp = {"round": 6, "my_hero": "H", "my_tier": 3, "last_seen": {"round": 5, "board": [], "hero": "X"}}
    best = web.Hub()._best_order(opp, mine, {"win": 40.0, "tie": 0.0, "loss": 60.0})
    assert best["card_id"] == "BIG" and best["to"] == 1 and best["win"] == 70.0 and best["base_win"] == 40.0
    assert web.Hub()._best_order(opp, mine, {"win": 68.0, "tie": 0.0, "loss": 32.0}) is None  # within 8 points


def test_live_odds_only_against_a_recent_board():
    # growing an older board to the hero average was tested on real rematches and rejected (always "100% win")
    from bgcoach import web
    seen = {"round": 3, "board": [{"card_id": "A", "atk": 2, "hp": 3}], "stats": 5, "projected": 15}
    assert web.Hub._their_board({"round": 6, "last_seen": seen}) == (seen["board"], False)
    assert web.Hub._their_board({"round": 7, "last_seen": seen}) is None
