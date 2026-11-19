"""Pro playbook checks fire only when the log shows the situation."""
from bgcoach import playbook


def game(turns, combats=(), start="2026-11-10T20:00:00", placement=5):
    return {"start": start, "placement": placement, "turns": list(turns), "combats": list(combats)}


def turn(rnd, actions=(), tier=1, hp=30, armor=0, **kw):
    return {"round": rnd, "tier": tier, "hp": hp, "armor": armor, "actions": list(actions), **kw}


def rules(g):
    return [r["rule"] for r in playbook.check(g)]


def test_early_rolls_count_only_paid_rolls_and_only_when_the_early_game_leaked():
    t3 = turn(3, [{"type": "REFRESH", "gold": 5}, {"type": "REFRESH", "gold": 4}, {"type": "BUY", "gold": 3}], tier=2)
    free = turn(4, [{"type": "REFRESH", "gold": 6}, {"type": "BUY", "gold": 6}], tier=2)  # free roll (hero power)
    leak = [{"round": r, "result": "LOSS", "damage_taken": 5} for r in (4, 5)]
    assert "early_rolls" in rules(game([turn(1), turn(2, tier=2), t3], leak))
    assert "early_rolls" not in rules(game([turn(1), turn(2, tier=2), free], leak))
    # the same rolls in a game whose early fights cost little: they found what they were for
    assert "early_rolls" not in rules(game([turn(1), turn(2, tier=2), t3], leak[:1]))
    # the standard curve rolls its spare gold: level on 4 (6 gold, 5 for the level, roll the 1), buy two on 5
    # (7 gold, roll the 1): two paid rolls, no minion given up
    t4 = turn(4, [{"type": "LEVEL", "gold": 6, "to_tier": 3}, {"type": "REFRESH", "gold": 1}], tier=2, gold=6, gold_end=0)
    t5 = turn(5, [{"type": "BUY", "gold": 7}, {"type": "BUY", "gold": 4}, {"type": "REFRESH", "gold": 1}], tier=3,
              gold=7, gold_end=0)
    assert "early_rolls" not in rules(game([turn(1), turn(2, tier=2), turn(3, tier=2), t4, t5], leak))


def test_tier2_on_turn2_unless_hero_power():
    stay = [turn(1), turn(2, [{"type": "BUY", "gold": 4}]), turn(3)]
    power = [turn(1), turn(2, [{"type": "HERO_POWER", "gold": 4}]), turn(3)]
    assert "tier2_turn2" in rules(game(stay))
    assert "tier2_turn2" not in rules(game(power))


def test_tier3_by_turn5():
    ts = [turn(r, tier=2 if r > 1 else 1) for r in range(1, 7)]
    assert "tier3_turn5" in rules(game(ts))
    ts[5]["tier"] = 3
    assert "tier3_turn5" not in rules(game(ts))


def test_level_below_damage_cap():
    t = turn(7, [{"type": "LEVEL", "gold": 9, "to_tier": 5}], tier=4, hp=21)
    lost = {"round": 7, "result": "LOSS", "damage_taken": 10, "hp_after": 11, "armor_after": 0}
    safe = {**lost, "damage_taken": 4, "hp_after": 17}
    assert "level_below_cap" in rules(game([t], [lost]))
    assert "level_below_cap" not in rules(game([t], [safe]))


def test_triple_reward_before_level():
    bad = turn(6, [{"type": "CAST", "card_id": playbook.TRIPLE_REWARD, "tier": 3, "gold": 8},
                   {"type": "LEVEL", "gold": 8}], tier=3)
    good = turn(6, [{"type": "LEVEL", "gold": 8}, {"type": "CAST", "card_id": playbook.TRIPLE_REWARD, "tier": 4}], tier=3)
    r = playbook.check(game([bad]))
    assert [x["rule"] for x in r] == ["triple_before_level"] and "tier 4 instead of tier 5" in r[0]["what"]
    assert "triple_before_level" not in rules(game([good]))


def test_freeze_then_paid_to_roll_it_away():
    t4 = turn(4, [{"type": "FREEZE", "gold": 0}], end_shop=[{"card_id": "A"}, {"card_id": "B"}])
    skip = turn(5, [{"type": "BUY", "target": "C", "gold": 7}])
    took = turn(5, [{"type": "BUY", "target": "A", "gold": 7}])
    rolled_first = turn(5, [{"type": "REFRESH", "gold": 7}, {"type": "BUY", "target": "A", "gold": 6}])
    levelled = turn(5, [{"type": "LEVEL", "gold": 7, "to_tier": 3}])  # freeze on 1, level on 2: cost nothing
    assert "freeze_unused" in rules(game([t4, rolled_first]))  # paid a gold for the shop the turn gave free
    assert "freeze_unused" not in rules(game([t4, took]))
    assert "freeze_unused" not in rules(game([t4, skip]))      # never rolled: the freeze cost nothing sure
    assert "freeze_unused" not in rules(game([t4, levelled]))


def test_dark_gifts_only_from_season_14():
    ts = [turn(r) for r in range(1, 11)]
    ts[3]["actions"] = [{"type": "DARK_GIFT", "gold": 3}]
    assert "dark_gifts_unused" not in rules(game(ts))  # every gold went into the board: traded, not forgotten
    ts[6]["gold_end"] = 3
    assert "dark_gifts_unused" in rules(game(ts, start="2026-11-10T20:00:00"))
    assert "dark_gifts_unused" not in rules(game([turn(r) for r in range(1, 11)], start="2026-07-15T20:00:00"))
    assert "dark_gifts_unused" not in rules(game(ts, placement=1))  # won: nothing to fix


def test_every_rule_names_its_source():
    for rid, (title, src, why) in playbook.RULES.items():
        assert src in playbook.SOURCES and title and why, rid


def m(atk, hp, *kw, cid="X"):
    return {"card_id": cid, "atk": atk, "hp": hp, "kw": list(kw)}


def fight(rnd, mine, theirs, result="LOSS"):
    return {"round": rnd, "result": result, "my_board": mine, "opp_board": theirs, "damage_taken": 5}


def test_early_order_weak_minion_leading():
    lost = fight(4, [m(1, 1), m(8, 8), m(2, 2)], [m(10, 10)])
    assert "early_order" in rules(game([turn(4)], [lost]))
    hopeless = fight(4, [m(1, 1), m(8, 8), m(2, 2)], [m(30, 30)])     # their board was 3× yours: order didn't decide it
    assert "early_order" not in rules(game([turn(4)], [hopeless]))
    shield = fight(4, [m(1, 1, "DIVINE_SHIELD"), m(8, 8)], [m(5, 5)])  # a shield up front is fine
    won = fight(4, [m(1, 1), m(8, 8)], [m(5, 5)], result="WIN")
    late = fight(9, [m(1, 1), m(8, 8)], [m(5, 5)])                    # late game: bumpers lead on purpose
    assert "early_order" not in rules(game([turn(4)], [shield]))
    assert "early_order" not in rules(game([turn(4)], [won]))
    assert "early_order" not in rules(game([turn(9)], [late]))


def test_taunt_next_to_cleave():
    middle = fight(10, [m(5, 5), m(9, 9, "TAUNT"), m(5, 5)], [m(9, 9, "CLEAVE")])
    edge = fight(10, [m(5, 5), m(5, 5), m(9, 9, "TAUNT")], [m(9, 9, "CLEAVE")])
    no_cleave = fight(10, [m(5, 5), m(9, 9, "TAUNT"), m(5, 5)], [m(9, 9)])
    assert "taunt_cleave" in rules(game([turn(10)], [middle]))
    assert "taunt_cleave" not in rules(game([turn(10)], [edge]))
    assert "taunt_cleave" not in rules(game([turn(10)], [no_cleave]))


def test_biggest_minion_into_venom():
    mine = [m(50, 50), m(5, 5), m(5, 5), m(5, 5)]
    venom = [m(1, 1, "VENOMOUS"), m(1, 1, "POISONOUS"), m(3, 3)]
    assert "venom_biggest" in rules(game([turn(10)], [fight(10, mine, venom)]))
    assert "venom_biggest" not in rules(game([turn(10)], [fight(10, mine[1:] + mine[:1], venom)]))


def test_roll_into_a_freeze_only_when_you_could_buy():
    could_buy = turn(6, [{"type": "REFRESH", "gold": 3}, {"type": "FREEZE", "gold": 2}], gold_end=2)
    spare_gold = turn(6, [{"type": "REFRESH", "gold": 1}, {"type": "FREEZE", "gold": 0}], gold_end=0)
    bought = turn(6, [{"type": "REFRESH", "gold": 3}, {"type": "BUY", "gold": 2}], gold_end=0)
    assert "roll_short" in rules(game([could_buy]))
    assert "roll_short" not in rules(game([spare_gold]))   # last gold would be lost anyway
    assert "roll_short" not in rules(game([bought]))


def test_gold_left_unspent():
    ts = [turn(r, gold_end=0) for r in range(1, 9)]
    assert "gold_unspent" not in rules(game(ts))
    ts[4]["gold_end"] = 3
    ts[7]["gold_end"] = 9          # the last turn of the game doesn't count (you may have run out of time)
    r = [x for x in playbook.check(game(ts)) if x["rule"] == "gold_unspent"]
    assert len(r) == 1 and "round 5 with 3 gold" in r[0]["what"] and "round 8" not in r[0]["what"]
    ts[4]["gold_end"] = 2          # 2 gold buys nothing (no 2-gold card left in the shop): not worth a lesson
    assert "gold_unspent" not in rules(game(ts))


def test_gold_left_on_an_engine_turn_is_the_clock_not_a_leak():
    # Omu, 17 Nov R12: Bounties and sells kept paying out; 19 gold left when the timer ran out, fight won
    # (gold before each action: a Bounty pays 8, a sell 1, a Bounty 6 = 15 in, 10 left at the end)
    engine = turn(5, [{"type": t, "gold": g} for t, g in (("BUY", 10), ("CAST", 7), ("BUY", 15), ("SELL", 12),
                                                         ("CAST", 13), ("BUY", 19), ("BUY", 16), ("BUY", 13))],
                  gold_end=10)
    ts = [turn(r, gold_end=0) for r in range(1, 9)]
    ts[4] = engine
    assert "gold_unspent" not in rules(game(ts))
    # a plain turn: one sell paid 1, 5 left over: that's gold you had and didn't use
    ts[4] = turn(5, [{"type": "BUY", "gold": 10}, {"type": "BUY", "gold": 7}, {"type": "SELL", "gold": 4}], gold_end=5)
    assert "gold_unspent" in rules(game(ts))


def test_a_short_roll_is_not_also_told_as_unspent_gold():
    # rolled with 3, froze what came up, ended with 2: one cause (the roll), so one lesson, not two that disagree
    short = turn(6, [{"type": "REFRESH", "gold": 3}, {"type": "FREEZE", "gold": 2}], gold_end=2)
    found = rules(game([short, turn(7, gold_end=0)]))
    assert "roll_short" in found and "gold_unspent" not in found


def test_freeze_pressed_twice_is_an_unfreeze():
    # the button toggles: two presses leave the shop unfrozen, and the next shop is new
    t4 = turn(4, [{"type": "FREEZE", "gold": 0}, {"type": "FREEZE", "gold": 0}],
              end_shop=[{"card_id": "A"}, {"card_id": "B"}])
    t5 = turn(5, [{"type": "REFRESH", "gold": 7}, {"type": "BUY", "target": "C", "gold": 6}],
              shop=[{"card_id": "C"}, {"card_id": "D"}])
    assert "freeze_unused" not in rules(game([t4, t5]))
    # one press, and the next shop really holds the frozen cards: a real freeze
    t4["actions"] = [{"type": "FREEZE", "gold": 0}]
    t5["shop"] = [{"card_id": "A"}, {"card_id": "B"}, {"card_id": "E"}]
    assert "freeze_unused" in rules(game([t4, t5]))


def test_early_order_lets_a_rally_minion_lead():
    # Rally fires when the minion attacks: leading with it is the point, whatever its attack
    class DB:
        def get(self, cid):
            return {"WHELP": {"mechanics": ["BACON_RALLY"],
                              "text": "<b>Rally:</b> Your Tavern spells give an extra +1 Health this game."}}.get(cid, {})
    rally = fight(7, [m(3, 7, cid="WHELP"), m(12, 12), m(4, 3)], [m(20, 20)])
    plain = fight(7, [m(3, 7), m(12, 12), m(4, 3)], [m(20, 20)])
    assert "early_order" not in [r["rule"] for r in playbook.check(game([turn(7)], [rally]), DB())]
    assert "early_order" in [r["rule"] for r in playbook.check(game([turn(7)], [plain]), DB())]


def test_opponent_tribes_from_the_board_you_saw():
    # the hover in game sums up their tribes; the log has no tag for it, so count their minions
    from bgcoach import lobby

    class DB:
        def get(self, cid):
            return {"M1": {"races": ["MURLOC"]}, "M2": {"races": ["MURLOC"]}, "B": {"races": ["BEAST"]},
                    "MIX": {"races": ["MURLOC", "BEAST"]}}.get(cid, {})
    board = [{"card_id": c} for c in ("M1", "M2", "MIX", "B", "NONE")]
    assert lobby.tribes(board, DB()) == [["MURLOC", 3], ["BEAST", 2]]
    assert lobby.describe_tribes(lobby.tribes(board, DB())) == "3 Murloc, 2 Beast"


def test_stayed_rolling_when_the_game_says_a_level_fit(monkeypatch):
    # Drest'agath, 16 Nov (3rd): 25 HP, 125% of the lobby, two players on tier 6; 12 then 8 rolls on tier 5
    from bgcoach import situation
    sit = {"round": 10, "tier": 5, "next_tier": 6, "hp": 25, "alive": 5, "at_next": 3, "duos": False}
    monkeypatch.setattr(situation, "at", lambda g, r, st, db, next_tier=None: {**sit, "round": r})
    monkeypatch.setattr(situation, "level_was_fair", lambda s: True)
    monkeypatch.setattr(situation, "level_support", lambda s: ["your board had 125% of the stats of the boards "
                                                               "you'd been fighting"])
    monkeypatch.setattr(situation, "summary", lambda s: "")

    def rolls(n, gold=16):
        return [{"type": "REFRESH", "gold": gold - i} for i in range(n)] + [{"type": "BUY", "gold": gold - n}]
    ts = [turn(r, tier=5, gold=16) for r in range(1, 14)]
    ts[9]["actions"], ts[10]["actions"] = rolls(12), rolls(8)
    lost = [{"round": 11, "result": "LOSS", "damage_taken": 15}]
    r = [x for x in playbook.check(game(ts, lost, placement=3)) if x["rule"] == "stayed_rolling"]
    assert len(r) == 1 and r[0]["round"] == 10
    assert r[0]["what"].startswith("Rounds 10–11: you stayed on tier 5 and rolled 12 and 8 times.")
    assert r[0]["what"].endswith("Round 11 cost you 15.")
    assert "stayed_rolling" not in rules(game(ts, lost, placement=1))  # it won: the rolls found what they were for
    ts[10]["actions"] = [*rolls(8), {"type": "LEVEL", "gold": 5, "to_tier": 6}]  # one turn of rolling, then the level
    assert "stayed_rolling" not in rules(game(ts, lost, placement=3))
