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


def game(my_hp=27, mine=5, theirs=10, opp_tier=6, opp_hp=(40, 40, 40, 40), tiers=(5, 5, 5, 4, 4, 4), cap=10):
    """Rounds 5-8. Lobby slot 1 is you, slot 2 the opponent you meet on rounds 6 and 8 (Big Opp)."""
    board = [{"card_id": c, "atk": mine, "hp": mine} for c in ("U1", "U2", "U3")]
    opp_board = [{"card_id": "X", "atk": theirs, "hp": theirs}] * 3
    turns, combats = [], []
    for i, r in enumerate(range(5, 9)):
        lobby = {"1": {"hp": my_hp, "tier": 5}, "2": {"hero": "OPP", "hp": opp_hp[i], "tier": opp_tier}}
        lobby.update({str(k + 3): {"hp": 30, "tier": t} for k, t in enumerate(tiers)})
        turns.append({"round": r, "hp": my_hp, "armor": 0, "tier": 5, "me_lobby": 1, "lobby": lobby, "board": board,
                      "actions": [{"type": "LEVEL", "to_tier": 6}] if r == 8 else []})
        combats.append({"round": r, "result": "LOSS" if r == 8 else "TIE", "opp_lobby_id": 2 if r in (6, 8) else 3,
                        "hp_after": my_hp - 15 if r == 8 else my_hp, "armor_after": 0,
                        "damage_taken": 15 if r == 8 else 0, "damage_cap": cap, "my_board": board,
                        "opp_board": opp_board})
    return {"start": "2026-11-12T20:00:00", "placement": 6, "turns": turns, "combats": combats}


def test_situation_reads_the_next_opponent_first_then_the_lobby():
    s = situation.at(game(), 8, None, DB(), next_tier=6)
    assert s["opp"]["name"] == "OPP" and s["opp"]["unhurt"] == 3 and s["vs_lobby"] == 0.5
    risks = situation.level_risks(s)
    assert risks[0].startswith("your next opponent, OPP, was already on tier 6 (you on 5), hadn't lost in 3 rounds")
    assert "had 60 stats when you met on round 6, against your 30 now" in risks[0]
    assert any("your board had only 50% of the stats of the boards you fought" in r for r in risks)
    assert not any("nobody else was on tier 6" in r for r in risks)       # OPP is there: there is a race
    assert any("only Big Undead for your Undeads" in r for r in risks)    # the build didn't need tier 6
    assert "even a loss was capped at 10, leaving you at 17" in situation.level_support(s)
    assert "(They had 60 stats in that fight, you 30.)" in situation.summary(s)


def test_level_warning_speaks_about_this_game_and_stays_quiet_when_fair():
    weak = playbook.check(game(), DB())
    lvl = next(r for r in weak if r["rule"] == "level_below_cap")
    assert "In this game: your next opponent, OPP" in lvl["what"] and "For it: even a loss" in lvl["what"]
    assert lvl["context"][0].startswith("Round 8: next: OPP (tier 6, 40 HP, no loss in 3)")
    # a weak next opponent (tier 4, lost twice), your board ahead, the lobby already on tier 6
    fair = game(mine=10, theirs=5, opp_tier=4, opp_hp=(40, 32, 25, 20), tiers=(6, 6, 6, 5, 5, 5))
    assert "level_below_cap" not in [r["rule"] for r in playbook.check(fair, DB3())]


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


def test_the_lobby_is_scaled_by_round_and_one_neighbour_or_a_ghost_cant_fake_a_highroll():
    from bgcoach import lobby

    def b(n):
        return [{"card_id": "X", "atk": n, "hp": 0}]
    # round 10 from a real game: Patches 977 against your 704; the round-9 opponent was a ghost (47 stats)
    combats = [{"round": 8, "my_board": b(212), "opp_board": b(226), "opp_hp_before": 28, "result": "LOSS"},
               {"round": 9, "my_board": b(226), "opp_board": b(47), "opp_hp_before": 0, "result": "WIN"},
               {"round": 10, "my_board": b(704), "opp_board": b(977), "opp_hp_before": 24, "result": "LOSS"}]
    assert lobby.lobby_level(combats, 10, skip_round=10) is None          # one live neighbour isn't a lobby
    assert not lobby.fights({"combats": combats})[2]["highroll"]
    # boards from other rounds are grown to this round (late boards double every round), yours left out
    combats = [{"round": r, "my_board": b(10), "opp_board": b(s), "opp_hp_before": 20, "result": "LOSS"}
               for r, s in ((5, 46), (6, 77), (7, 300), (8, 245))]
    assert lobby.lobby_level(combats, 7, skip_round=7) == 132             # 46, 77, 245 all scale to 132
    f = lobby.fights({"combats": combats})[2]
    assert f["ratio"] == 2.27 and f["highroll"]
    # a board well above the lobby but smaller than yours is not a highroll against you
    combats[2]["my_board"] = b(400)
    assert not lobby.fights({"combats": combats})[2]["highroll"]
