"""What-if logic that doesn't need the simulator itself."""
from bgcoach import whatif
from bgcoach.decisions import with_simulation


def test_orders_are_single_moves_plus_reverse():
    board = [{"card_id": c} for c in "ABCD"]
    orders = whatif._orders(board)
    names = {"".join(m["card_id"] for m in o) for o in orders}
    assert "ABCD" not in names and "DCBA" in names and "BACD" in names and "BCDA" in names
    assert all(sorted(n) == list("ABCD") for n in names)


def test_simulation_notes(monkeypatch, tmp_path):
    cache = {"version": whatif.VERSION,
             "fights": {"5": {"win": 20, "tie": 10, "loss": 70, "trusted": True},
                        # Bob's Buddy said 100% loss, the simulator 47% win: it didn't reproduce the fight
                        "6": {"win": 47, "tie": 45, "loss": 8, "trusted": False, "trust_why": "70 points from Bob's Buddy"}},
             "buys": [{"round": 5, "you": "A", "better": "B", "you_win": 40, "you_loss": 50, "alt_win": 40,
                       "alt_loss": 50, "gain": 0.0},
                      {"round": 6, "you": "C", "better": "D", "you_win": 30, "you_loss": 60, "alt_win": 55,
                       "alt_loss": 35, "gain": 25.0}],
             "positions": [{"round": 4, "actual": ["X", "Y"], "order": ["Y", "X"], "base_win": 10,
                            "best_win": 40, "base_loss": 80, "best_loss": 50, "gain": 30.0}]}
    monkeypatch.setattr(whatif, "load", lambda f: cache)
    ds = [{"kind": "buy", "round": 5, "you": "A", "better": "B"}, {"kind": "buy", "round": 6, "you": "C", "better": "D"},
          {"kind": "fight", "round": 5}, {"kind": "fight", "round": 6}]
    g = {"file": "x.json", "combats": [{"round": 4, "result": "LOSS", "damage_taken": 20, "hp_after": 10}]}
    seen = [{"round": 4, "seen_before": {"round": 2, "stats": 30}}]
    out = with_simulation(g, ds, seen)
    unseen = with_simulation(g, [dict(x) for x in ds[:0]], [])  # never seen that board: hindsight, not a lesson
    assert not [d for d in unseen if d["kind"] == "position"]
    assert "no difference" in out[0]["sim_note"]
    assert "+25 points" in out[1]["sim_note"]
    assert out[2]["sim"]["loss"] == 70
    assert "sim" not in out[3] and "70 points" in out[3]["sim_untrusted"]  # never show an unreproduced fight
    pos = [d for d in out if d["kind"] == "position"]
    assert pos and pos[0]["gain"] == 30.0 and pos[0]["order"] == ["Y", "X"]


def test_counter_lines_use_gold_you_had():
    class DB:
        def get(self, cid):
            return {"type": "MINION"} if cid != "SPELL" else {"type": "BATTLEGROUND_SPELL"}

    board = [{"card_id": "A", "atk": 5, "hp": 5}, {"card_id": "B", "atk": 1, "hp": 1}]
    turn = {"gold_end": 0, "end_shop": [{"card_id": "V", "atk": 1, "hp": 1, "kw": ["VENOMOUS"]}, {"card_id": "SPELL"}],
            "actions": [{"type": "BUY", "target": "A", "gold": 8}, {"type": "LEVEL", "gold": 5}, {"type": "PLAY", "gold": 0}]}
    vs = whatif._counter_variants({"my_board": board}, turn, DB())
    kinds = {v["kind"] for v in vs}
    assert kinds == {"instead", "skip_level"}             # no spare gold: only lines that free gold you spent
    assert all(v["buy"]["card_id"] == "V" for v in vs)    # spells aren't simulated as board minions
    inst = next(v for v in vs if v["kind"] == "instead")
    assert inst["undone"] == "A" and [m["card_id"] for m in inst["board"]].count("A") == 0
    assert whatif._level_cost(turn) == 5
    turn["gold_end"] = 2                                   # 2 spare gold + selling the weakest (B) = 3
    spare = [v for v in whatif._counter_variants({"my_board": board}, turn, DB()) if v["kind"] == "spare"]
    assert spare and all([m["card_id"] for m in v["sold"]] == ["B"] for v in spare)


def test_keep_line_puts_a_sold_minion_back():
    # a full board: the sold stat holder comes back in place of the weakest minion, with the stats it was sold at
    board = [{"card_id": f"M{i}", "atk": 5, "hp": 5} for i in range(6)] + [{"card_id": "TAD", "atk": 1, "hp": 1}]
    t = {"board": [{"card_id": "CHORAL", "atk": 30, "hp": 30, "pos": 3, "kw": ["DIVINE_SHIELD"]}],
         "actions": [{"type": "SELL", "target": "CHORAL", "target_atk_hp": [32, 40]},
                     {"type": "SELL", "target": "TINY", "target_atk_hp": [1, 1]},    # no bigger than the weakest
                     {"type": "SELL", "target": "M0", "target_atk_hp": [5, 5]}]}     # a copy is still on the board
    vs = whatif._keep_variants(board, t, weakest=6)
    assert {v["undone"] for v in vs} == {"CHORAL"} and all(v["kind"] == "keep" for v in vs)
    assert {v["pos"] for v in vs} == {0, 2, 6}  # in front, where it stood (slot 3), at the back
    v = vs[0]
    assert len(v["board"]) == 7 and [m["card_id"] for m in v["sold"]] == ["TAD"]
    kept = next(m for m in v["board"] if m["card_id"] == "CHORAL")
    assert (kept["atk"], kept["hp"], kept["kw"]) == (32, 40, ["DIVINE_SHIELD"])
    # with room on the board nothing has to go
    assert all(not v["sold"] and len(v["board"]) == 3 for v in whatif._keep_variants(board[:2], t, weakest=0))


def test_keep_line_in_a_coachs_words():
    from bgcoach.decisions import _counter_moment
    from bgcoach.lessons import habit

    class DB:
        def name(self, c):
            return {"CHORAL": "Choral Mrrrglr", "TAD": "Tad"}.get(c, c)

    c = {"round": 14, "kind": "keep", "undone": "CHORAL", "buy": "CHORAL", "buy_stats": [32, 40], "buy_kw": [],
         "sold": ["TAD"], "pos": 3, "board": ["x"] * 7, "base": {"win": 4, "tie": 2, "loss": 94},
         "new": {"win": 60, "tie": 5, "loss": 35}, "gain": 55, "stats_change": 70, "trust": "2 points from Bob's Buddy"}
    m = _counter_moment(c, DB(), None)
    assert m["what"] == "Keep Choral Mrrrglr (32/40) instead of selling it, in place of Tad"
    assert "placed in slot 3" in m["calc"] and "You sold it that turn." in m["calc"] and not m["risky"]
    assert "don't sell a stat holder" in habit(m)


def test_keep_line_only_when_the_fight_cost_the_hp_line(monkeypatch):
    from bgcoach import decisions
    from bgcoach.lessons import headline

    class DB:
        def name(self, c):
            return c

    monkeypatch.setattr(decisions.V, "card_db", lambda build: DB())

    def line(r):
        return {"round": r, "kind": "keep", "undone": "K", "buy": "K", "buy_stats": [9, 9], "buy_kw": [], "sold": [],
                "pos": 1, "board": ["K"], "base": {"win": 0, "tie": 0, "loss": 100},
                "new": {"win": 100, "tie": 0, "loss": 0}, "gain": 100, "stats_change": 18, "trust": "ok"}

    monkeypatch.setattr(whatif, "load", lambda f: {"version": whatif.VERSION, "fights": {}, "counters": [line(3), line(9)]})
    g = {"file": "x.json", "build": 1, "combats": [
        {"round": 3, "result": "LOSS", "damage_taken": 6, "hp_after": 34},  # sold early to upgrade: tempo, not a lesson
        {"round": 9, "result": "LOSS", "damage_taken": 9, "hp_after": 0}]}  # that one cost the game
    out = [d for d in with_simulation(g, [], []) if d["kind"] == "counter"]
    assert [d["round"] for d in out] == [9]
    assert "that fight knocked you out" in headline(out[0], str)
