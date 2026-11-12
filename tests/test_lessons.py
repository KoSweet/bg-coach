"""The one thing: ranking by kind, then size; one impact language; sentences that read right."""
from bgcoach import lessons


def name(cid):
    return {"A": "Alpha", "B": "Bravo", "X": "Xavius"}.get(cid, cid or "?")


def test_rank_by_kind_then_size():
    ms = [{"kind": "fight", "round": 9, "damage": 15},
          {"kind": "rule", "round": 5, "rule": "early_rolls", "title": "Rolling in the early game", "what": "3 rolls", "diff": 0.15},
          {"kind": "hero", "round": 0, "better": "X", "diff": 0.5, "why": ["Xavius finishes top 4 more often."]},
          {"kind": "position", "round": 6, "gain": 23, "base_win": 6, "best_win": 29, "saved_hp": 6, "seen_round": 3},
          {"kind": "turning", "round": 7, "damage": 10, "what": "Round 7: you dropped from 23 to 13 HP, below 15.",
           "habit": "Stabilize before levelling."},
          {"kind": "counter", "round": 4, "gain": 30, "saved_hp": 4, "hp_after": 12, "line_kind": "skip_level", "what": "Skip the level-up, buy A",
           "base": {"win": 0, "tie": 0, "loss": 100}, "new": {"win": 20, "tie": 20, "loss": 60}},
          {"kind": "counter", "round": 8, "gain": 67, "saved_hp": 10, "hp_after": 2, "line_kind": "instead", "what": "Instead of B, buy A",
           "base": {"win": 7, "tie": 11, "loss": 82}, "new": {"win": 71, "tie": 16, "loss": 13}}]
    ranked = lessons.annotate(ms, name)
    assert [d["kind"] for d in ranked] == ["counter", "counter", "turning", "position", "hero", "rule", "fight"]
    assert ranked[0]["round"] == 8 and ranked[0]["rank"] == 0          # more HP saved first
    assert [d["impact"] for d in ranked] == ["~10 HP saved", "~4 HP saved", "10 HP", "~6 HP saved", "0.50 places",
                                             "habit", "15 HP"]
    assert all(d["habit"] for d in ranked)
    assert "buy for the next fight first" in ranked[0]["habit"]         # 'instead' line → buying habit
    assert "Before levelling" in ranked[1]["habit"]                      # 'skip_level' line → levelling habit
    assert ranked[2]["habit"] == "Stabilize before levelling."          # the turning point brings its own
    assert "you dropped to 2" in ranked[0]["headline"] and "10 HP saved" in ranked[0]["headline"]


def test_a_loss_turned_into_a_tie_reads_right():
    d = {"kind": "counter", "round": 2, "gain": 50, "line_kind": "skip_level", "what": "Skip the level-up, buy A",
         "base": {"win": 0, "tie": 0, "loss": 100}, "new": {"win": 0, "tie": 100, "loss": 0}}
    h = lessons.annotate([d], name)[0]["headline"]
    assert "from 0% win, 100% loss to 0% win, 0% loss" in h


def test_highroll_fight_sentence_and_habit():
    d = {"kind": "fight", "round": 9, "damage": 15, "opp": "X", "highroll": True, "opp_ratio": 3.2, "no_counter": {"tried": 9}}
    r = lessons.annotate([d], name)[0]
    assert r["headline"] == ("Round 9: lost 15 HP to Xavius, a highroll (3.2× the average for their hero). "
                             "Nothing in your shop that turn would have won it.")
    assert "next-opponent" in r["habit"]


def test_hero_moment_only_when_clearly_better():
    a = {"hero_pick": {"clear": False, "loss": 0.1}}
    assert lessons.hero_moment(a, "A") is None
    a = {"hero_pick": {"clear": True, "picked_avg": 4.3, "best": "X", "best_avg": 3.9, "loss": 0.4, "noise": 0.1, "why": []}}
    m = lessons.hero_moment(a, "A")
    assert m["kind"] == "hero" and m["better"] == "X" and m["round"] == 0


def test_turning_point_causes():
    from bgcoach.decisions import turning_point

    def game(level_round, ratios, rolls=0, buys=2):
        turns = []
        for r in range(1, 8):
            acts = [{"type": "LEVEL", "to_tier": 4}] if r == level_round else []
            acts += [{"type": "REFRESH"}] * (rolls if r >= 5 else 0) + [{"type": "BUY"}] * (buys if r >= 5 else 0)
            turns.append({"round": r, "actions": acts})
        combats = [{"round": r, "result": "LOSS" if r == 7 else "WIN", "hp_before": 30 if r < 7 else 22,
                    "hp_after": 30 if r < 7 else 10, "armor_before": 0, "armor_after": 0} for r in range(1, 8)]
        strength = [{"round": r, "ratio": ratios.get(r, 1.0)} for r in range(1, 8)]
        return {"turns": turns, "combats": combats}, strength

    g, s = game(6, {5: 0.7, 6: 0.65, 7: 0.6})
    assert turning_point(g, s)["cause"] == "levelled"           # levelled with the board already behind
    g, s = game(5, {4: 1.0, 5: 0.7, 6: 0.65, 7: 0.6}, rolls=2, buys=2)
    assert turning_point(g, s)["cause"] == "spent"              # level was fine; the buys didn't keep up
    g, s = game(6, {5: 0.8, 6: 1.1, 7: 1.3})
    assert turning_point(g, s) is None                          # good board in that fight: close fight, no lesson
