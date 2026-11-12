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
        combats = [{"round": r, "result": "LOSS" if r >= 6 else "WIN", "hp_before": {6: 30, 7: 22}.get(r, 30),
                    "hp_after": {6: 22, 7: 10}.get(r, 30), "armor_before": 0, "armor_after": 0} for r in range(1, 8)]
        strength = [{"round": r, "ratio": ratios.get(r, 1.0)} for r in range(1, 8)]
        return {"turns": turns, "combats": combats}, strength

    g, s = game(6, {5: 0.7, 6: 0.65, 7: 0.6})
    assert turning_point(g, s)["cause"] == "levelled"           # levelled with the board already behind
    g, s = game(5, {4: 1.0, 5: 0.7, 6: 0.65, 7: 0.6}, rolls=2, buys=2)
    assert turning_point(g, s)["cause"] == "spent"              # level was fine; the buys didn't keep up
    g, s = game(6, {5: 0.8, 6: 1.1, 7: 1.3})
    assert turning_point(g, s) is None                          # good board in that fight: close fight, no lesson


def test_keyword_board_is_judged_by_its_fights_not_its_stats():
    # a winning venom/divine-shield ("scam") board at a fraction of the stat average is not "behind"
    from bgcoach.decisions import keyword_board, turning_point
    venom = [{"kw": ["VENOMOUS", "DIVINE_SHIELD"]}, {"kw": ["VENOMOUS"]}, {"kw": []}]
    assert keyword_board(venom) and not keyword_board([{"kw": ["TAUNT"]}, {"kw": ["DIVINE_SHIELD"]}])

    def game(results):
        rounds = range(10, 10 + len(results))
        hp = 30
        combats = []
        for r, res in zip(rounds, results, strict=True):
            after = hp - (8 if res == "LOSS" else 0)
            combats.append({"round": r, "result": res, "hp_before": hp, "hp_after": after, "armor_before": 0,
                            "armor_after": 0, "my_board": venom})
            hp = after
        turns = [{"round": r, "actions": [{"type": "REFRESH"}] * 5 + [{"type": "BUY"}] * 5} for r in rounds]
        strength = [{"round": r, "ratio": 0.3} for r in rounds]
        return {"turns": turns, "combats": combats}, strength

    g, s = game(["WIN", "WIN", "LOSS", "WIN", "WIN"])     # 30% of the stat average, one loss: not "behind"
    assert turning_point(g, s) is None
    g, s = game(["LOSS", "WIN", "LOSS"])                   # a keyword board that lost 2 of 3: told by its record
    assert turning_point(g, s)["cause"] == "keyword_lost"
    g, s = game(["LOSS", "LOSS"])
    tp = turning_point(g, s)
    assert tp["cause"] == "keyword_lost" and "lost 2 of 2 fights" in tp["what"] and "%" not in tp["what"]


def test_selling_the_board_down_at_the_line_is_the_turning_point():
    # one decision on one turn: sold the stat holders at 15 HP, lost the fight, then won with the new board
    from bgcoach.decisions import turning_point
    big = [{"card_id": "choral", "atk": 400, "hp": 400}, {"card_id": "escapee", "atk": 100, "hp": 100},
           {"card_id": "a", "atk": 50, "hp": 50}]
    small = [{"card_id": "a", "atk": 50, "hp": 50}, {"card_id": "tad", "atk": 10, "hp": 10}]
    combats = [{"round": 13, "result": "WIN", "hp_before": 15, "hp_after": 15, "my_board": big},
               {"round": 14, "result": "LOSS", "hp_before": 15, "hp_after": 8, "my_board": small},
               {"round": 15, "result": "WIN", "hp_before": 8, "hp_after": 8, "my_board": big},
               {"round": 16, "result": "WIN", "hp_before": 8, "hp_after": 8, "my_board": big}]
    sells = [{"type": "SELL", "target": x} for x in ("escapee", "tad", "choral")]  # tad is still on the board
    g = {"turns": [{"round": 13, "actions": []}, {"round": 14, "actions": sells}], "combats": combats}
    tp = turning_point(g, [], name=str.title)
    assert tp["cause"] == "transition" and tp["damage"] == 7 and tp["sold"] == ["escapee", "choral"]
    assert "sold Choral and Escapee, which had fought with 1000 of your 1100 stats on round 13" in tp["what"]
    assert "you won rounds 15 and 16 after it" in tp["what"] and "%" not in tp["what"]
    g["turns"][1]["actions"] = [{"type": "SELL", "target": "tad"}]  # nothing big sold: one loss, no lesson
    assert turning_point(g, []) is None


def test_one_lost_fight_is_not_a_turning_point():
    from bgcoach.decisions import turning_point
    combats = [{"round": 7, "result": "WIN", "hp_before": 20, "hp_after": 20},
               {"round": 8, "result": "LOSS", "hp_before": 20, "hp_after": 10}]
    turns = [{"round": r, "actions": [{"type": "LEVEL", "to_tier": 5}]} for r in (7, 8)]
    assert turning_point({"turns": turns, "combats": combats}, [{"round": 8, "ratio": 0.5}]) is None
