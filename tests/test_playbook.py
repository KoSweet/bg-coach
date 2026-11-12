"""Pro playbook checks fire only when the log shows the situation."""
from bgcoach import playbook


def game(turns, combats=(), start="2026-11-10T20:00:00", placement=5):
    return {"start": start, "placement": placement, "turns": list(turns), "combats": list(combats)}


def turn(rnd, actions=(), tier=1, hp=30, armor=0, **kw):
    return {"round": rnd, "tier": tier, "hp": hp, "armor": armor, "actions": list(actions), **kw}


def rules(g):
    return [r["rule"] for r in playbook.check(g)]


def test_early_rolls_count_only_paid_rolls():
    t3 = turn(3, [{"type": "REFRESH", "gold": 5}, {"type": "REFRESH", "gold": 4}, {"type": "BUY", "gold": 3}], tier=2)
    free = turn(4, [{"type": "REFRESH", "gold": 6}, {"type": "BUY", "gold": 6}], tier=2)  # free roll (hero power)
    assert "early_rolls" in rules(game([turn(1), turn(2, tier=2), t3]))
    assert "early_rolls" not in rules(game([turn(1), turn(2, tier=2), free]))


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


def test_freeze_then_buy_nothing():
    t4 = turn(4, [{"type": "FREEZE", "gold": 0}], end_shop=[{"card_id": "A"}, {"card_id": "B"}])
    skip = turn(5, [{"type": "BUY", "target": "C", "gold": 7}])
    took = turn(5, [{"type": "BUY", "target": "A", "gold": 7}])
    rolled_first = turn(5, [{"type": "REFRESH", "gold": 7}, {"type": "BUY", "target": "A", "gold": 6}])
    assert "freeze_unused" in rules(game([t4, skip]))
    assert "freeze_unused" not in rules(game([t4, took]))
    assert "freeze_unused" in rules(game([t4, rolled_first]))  # rolled the frozen shop away


def test_dark_gifts_only_from_season_14():
    ts = [turn(r) for r in range(1, 11)]
    ts[3]["actions"] = [{"type": "DARK_GIFT", "gold": 3}]
    assert "dark_gifts_unused" in rules(game(ts, start="2026-11-10T20:00:00"))
    assert "dark_gifts_unused" not in rules(game([turn(r) for r in range(1, 11)], start="2026-07-15T20:00:00"))
    assert "dark_gifts_unused" not in rules(game(ts, placement=1))  # won: nothing to fix


def test_every_rule_names_its_source():
    for rid, (title, src, why) in playbook.RULES.items():
        assert src in playbook.SOURCES and title and why, rid
