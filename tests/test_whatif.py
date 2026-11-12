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
    out = with_simulation({"file": "x.json"}, ds)
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
