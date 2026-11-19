"""The fights that decided a game, and the reasons a pro gives for them (from real games, 13 Nov 2026)."""
from typing import ClassVar

from bgcoach import decisions, playbook, situation


class DB:
    names: ClassVar[dict] = {"BRANN": "Dinotamer Brann", "FELBOAR": "Felboar", "UNDERDOG": "Heroic Underdog", "BG28_603": "Boon of Beetles",
             "PRIV": "Proud Privateer", "BANDIT": "Bigwig Bandit"}
    cards: ClassVar[dict] = {"PRIV": {"name": "Proud Privateer", "techLevel": 5, "races": ["PIRATE"]},
             "BANDIT": {"name": "Bigwig Bandit", "techLevel": 4, "races": ["PIRATE"]}}

    def name(self, cid):
        return self.names.get(cid, cid)

    def get(self, cid):
        return self.cards.get(cid, {})


def b(*stats, cid="X"):
    return [{"card_id": cid, "atk": a, "hp": h} for a, h in stats]


def final_vs_deity():
    """Varden's final: 56,289 stats lost to Brann's visible 7,506, a Deity and Heroic Underdog."""
    mine = b((23905, 16166), (7093, 4938), (1152, 955), (396, 574), (358, 229), (301, 212), (4, 6))
    mine[0]["card_id"] = "FELBOAR"
    c = {"round": 15, "result": "LOSS", "damage_taken": 17, "opp_hero": "BRANN", "opp_lobby_id": 5,
         "my_board": mine, "opp_board": b((3669, 2729), (216, 453), (41, 118), (32, 104), (7, 59), (4, 54), (2, 18)),
         "opp_secrets": [{"card_id": "BG_OldGod", "deity": True, "atk": 3631, "hp": 2585, "after": 4,
                          "atk_peak": 4455, "hp_peak": 2997}, {"card_id": "BG28_603"}],
         "my_big": {"card_id": "FELBOAR", "atk": 23905, "hp": 16166, "died": True, "killed_by": "UNDERDOG"}}
    early = {"round": 12, "result": "WIN", "opp_lobby_id": 5, "my_board": b((5, 5)), "opp_board": b((5, 5))}
    return {"placement": 2, "combats": [early, c]}, [{"round": 12, "lobby_id": 5}, {"round": 15, "lobby_id": 5}]


def test_final_explains_what_the_board_did_not_show():
    g, opps = final_vs_deity()
    d = decisions.deciding_fights(g, opps, DB())
    assert len(d) == 1 and d[0]["kind"] == "decider" and d[0]["sim_blind"]
    w = d[0]["what"]
    assert w.startswith("Round 15: you lost to Dinotamer Brann with 56,289 stats against their 7,506 (7.5× theirs).")
    assert "their Deity, a hidden 3,631/2,585, 4,455/2,997 by the end of the fight, which joins the fight after 4" in w
    assert "a secret (Boon of Beetles)" in w
    assert "Felboar (23,905/16,166, 71% of your stats), was killed by Heroic Underdog: it gains the Attack" in w
    assert "You'd fought this player on round 12." in w
    assert "Taunt on a small minion" in d[0]["habit"]


def test_a_1_1_deity_and_close_losses_are_not_deciders():
    g, opps = final_vs_deity()
    c = g["combats"][1]
    c["opp_secrets"] = [{"card_id": "BG_OldGod", "deity": True, "atk": 1, "hp": 1, "after": 4}]  # everyone has one
    assert decisions.hidden_strength(c, DB()) == []
    g["placement"] = 6                                    # not a top-4 final; mine 1.4× theirs: no upset
    c["my_board"] = b((7000, 3500))
    c.pop("my_big")
    assert decisions.deciding_fights(g, opps, DB()) == []


def test_losses_left_counts_health_in_capped_losses():
    combats = [{"round": 8, "hp_before": 30, "armor_before": 0, "damage_cap": 15}]
    assert decisions._losses_left(combats, [8, 9, 10]) == ("From round 8 you were on 30 HP with losses capped at "
                                                            "15: two losses from out.")
    assert decisions._losses_left([{**combats[0], "hp_before": 31}], [8]) is None


def test_a_level_that_bought_the_engine_counts_for_it():
    t = {"round": 8, "actions": [{"type": "LEVEL", "to_tier": 5}, {"type": "PLAY", "card_id": "BANDIT"},
                                 {"type": "PLAY", "card_id": "PRIV"}, {"type": "BUY", "card_id": "PRIV"},
                                 {"type": "PLAY", "card_id": "PRIV"}]}
    assert situation.got_from_tier(t, 5, DB()) == ["Proud Privateer", "Proud Privateer"]
    s = {"got": ["Proud Privateer"] * 2, "next_tier": 5, "hp": 19, "cap": 15, "at_next": 0, "vs_lobby": None}
    assert situation.level_support(s)[0] == "the level paid off at once: you played 2× Proud Privateer from tier 5+ that turn"


def test_gold_left_when_the_timer_ran_out_is_said_as_such():
    t = {"round": 9, "tier": 5, "hp": 26, "gold_end": 9, "end_board": [], "end_shop": [],
         "actions": [{"type": "BUY", "t": "2026-11-13T15:50:10"}]}
    c = {"round": 9, "t": "2026-11-13T15:50:12", "result": "WIN"}
    g = {"turns": [t, {"round": 10, "actions": []}], "combats": [c]}
    gold = next(r for r in playbook.check(g) if r["rule"] == "gold_unspent")
    assert gold["what"].startswith("The turn timer ran out with 9 gold left on round 9")


def test_thin_board_early_only_when_the_early_game_leaked():
    # Faelin, 13 Nov: 2 minions on round 4, and rounds 3-8 cost 31 HP
    t = [{"round": r, "tier": 2, "hp": 30, "actions": []} for r in range(1, 9)]
    c = [{"round": 4, "result": "LOSS", "damage_taken": 6, "my_board": b((3, 4), (1, 3)), "opp_board": b((4, 4))}]
    c += [{"round": r, "result": "LOSS", "damage_taken": d, "my_board": b(*[(5, 5)] * 6), "opp_board": b((9, 9))}
          for r, d in ((6, 10), (7, 7), (8, 8))]
    rule = next(r for r in playbook.check({"turns": t, "combats": c}) if r["rule"] == "thin_board")
    assert rule["what"] == "2 minions on the board on round 4, lost 6. Rounds 3–8 cost you 31 HP in all."
    # the same board in a game where the early rounds were cheap: nothing to say
    assert "thin_board" not in [r["rule"] for r in playbook.check({"turns": t, "combats": c[:1]})]


class DeityDB(DB):
    cards: ClassVar[dict] = {**DB.cards,
                             "CTHUN": {"name": "C'Thun", "text": "<b>Deity.</b> After this awakens, give this minion's "
                                                                 "stats split amongst your other minions."},
                             "CONV": {"name": "Faceless Converter", "text": "[x]<b>Deathrattle:</b> Give your "
                                                                          "<b>Deity</b> +2/+1."},
                             "SPIDER": {"name": "Venom Spider"}}

    def name(self, cid):
        return self.cards.get(cid, {}).get("name") or super().name(cid)


def mutanus_r8():
    """Mutanus, 16 Nov R8 (8th): 268 against 149 on the board, lost 14 to Zerek's C'Thun (37/37, 45/44 at its peak)."""
    mine = b((54, 54), (21, 24), (22, 20), (14, 8), (13, 13), (6, 10), (6, 3))
    mine[0]["card_id"] = "HELLCALLER"
    c = {"round": 8, "result": "LOSS", "damage_taken": 14, "opp_hero": "ZEREK", "opp_lobby_id": 3, "my_board": mine,
         "opp_board": b((12, 8), (12, 12), (11, 13), (11, 8), (5, 5), (17, 17), (6, 12)),
         "opp_secrets": [{"card_id": "BG_OldGod", "deity": True, "atk": 37, "hp": 37, "after": 4,
                          "atk_peak": 45, "hp_peak": 44}],
         "my_big": {"card_id": "HELLCALLER", "atk": 54, "hp": 54, "died": True, "killed_by": "CTHUN"}}
    later = {"round": 10, "result": "LOSS", "damage_taken": 15, "my_board": b((50, 50)), "opp_board": b((60, 60))}
    return {"placement": 8, "combats": [c, later]}


def test_a_deity_a_quarter_of_your_board_explains_a_loss_you_led():
    d = decisions.deciding_fights(mutanus_r8(), [], DeityDB())
    assert [x["round"] for x in d] == [8] and d[0]["upset"] and d[0]["sim_blind"]
    assert d[0]["what"].startswith("Round 8: you lost to ZEREK with 268 stats against their 149 (1.8× theirs).")
    assert "a hidden 37/37, 45/44 by the end of the fight" in d[0]["what"]
    assert "was killed by their Deity, C'Thun." in d[0]["what"]
    # a Deity at a tenth of your board doesn't explain a fight you led by 1.8×
    g = mutanus_r8()
    g["combats"][0]["opp_secrets"][0].update(atk=12, hp=12, atk_peak=None, hp_peak=None)
    assert decisions.deciding_fights(g, [], DeityDB()) == []


def test_a_minion_that_feeds_a_deity_is_not_called_the_deity():
    killer, answer = decisions._killer({"my_board": b((10, 10))}, {"killed_by": "CONV", "atk": 10, "hp": 10}, DeityDB())
    assert killer == "Faceless Converter" and answer is None


def test_a_venomous_killer_of_a_stat_holder_names_the_fix():
    mine = b((500, 500), (20, 20), (20, 20))
    mine[0].update(card_id="BIG", kw=["DIVINE_SHIELD"])
    c = {"my_board": mine, "opp_board": [{"card_id": "SPIDER", "atk": 3, "hp": 3, "kw": ["VENOMOUS"]}]}
    killer, answer = decisions._killer(c, {"card_id": "BIG", "atk": 500, "hp": 500, "killed_by": "SPIDER"}, DeityDB())
    assert killer == "Venom Spider (venomous)"
    assert "one minion holding 93% of your stats" in answer and "a Taunt in front of it is what keeps it alive" in answer
    assert "Divine Shield on it" not in answer  # its shield was already gone: the fix is the taunt


def test_last_fight_lost_while_behind_with_nothing_hidden_says_nothing():
    g, opps = final_vs_deity()
    c = g["combats"][1]
    c["opp_secrets"], c["my_board"] = [], b((1000, 500))  # 1,500 against their 7,506: the board was simply behind
    c["my_big"]["killed_by"] = "PRIV"
    assert decisions.deciding_fights(g, opps, DB()) == []


def test_duos_last_fight_counts_only_in_the_top_half():
    g, opps = final_vs_deity()
    g["game_type"] = "GT_BATTLEGROUNDS_DUO"
    g["combats"][1]["opp_secrets"] = []
    g["combats"][1]["my_big"].pop("killed_by")
    g["combats"][1]["my_board"] = b((5000, 5000))    # 10,000 against 7,506: ahead, not an upset
    g["placement"] = 3                                # 3rd of 4 teams: not a top finish
    assert decisions.deciding_fights(g, opps, DB()) == []
    g["placement"] = 2
    d = decisions.deciding_fights(g, opps, DB())
    assert d and d[0]["final"] and "The stat count leaves out" not in d[0]["what"]  # their test board has no keywords


def test_far_behind_the_venom_that_killed_your_best_minion_is_not_why_you_lost():
    # 12 Nov: 5,705 against 39,097 in the last fight; Hackerfin (venomous) killed Snazzy Phantom
    mine = b((1767, 1357), (900, 900), (400, 381))
    mine[0]["card_id"] = "PHANTOM"
    c = {"round": 15, "result": "LOSS", "damage_taken": 20, "opp_hero": "MECHANO", "my_board": mine,
         "opp_board": [{"card_id": "SPIDER", "atk": 5000, "hp": 5000, "kw": ["VENOMOUS"]}, *b((14000, 15097))],
         "my_big": {"card_id": "PHANTOM", "atk": 1767, "hp": 1357, "died": True, "killed_by": "SPIDER"}}
    g = {"placement": 2, "combats": [c]}
    assert decisions.deciding_fights(g, [], DeityDB()) == []
    c["opp_board"] = [{"card_id": "SPIDER", "atk": 3000, "hp": 3000, "kw": ["VENOMOUS"]}]  # 5,705 against 6,000
    d = decisions.deciding_fights(g, [], DeityDB())
    assert d and "was killed by Venom Spider (venomous): a venomous minion kills any size" in d[0]["what"]


def test_duos_health_is_the_teams():
    t = ("Round 8: you dropped from 19 to 4 HP, below 15. From round 7 you were on 20 HP with losses capped at 15: "
         "two losses from out.")
    assert decisions.team_words(t) == ("Round 8: your team dropped from 19 to 4 HP, below 15. From round 7 your team "
                                       "was on 20 HP with losses capped at 15: two losses from out.")
