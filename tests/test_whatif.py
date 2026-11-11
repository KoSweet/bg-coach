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
    cache = {"version": whatif.VERSION, "fights": {"5": {"win": 20, "tie": 10, "loss": 70}},
             "buys": [{"round": 5, "you": "A", "better": "B", "you_win": 40, "you_loss": 50, "alt_win": 40,
                       "alt_loss": 50, "gain": 0.0},
                      {"round": 6, "you": "C", "better": "D", "you_win": 30, "you_loss": 60, "alt_win": 55,
                       "alt_loss": 35, "gain": 25.0}],
             "positions": [{"round": 4, "actual": ["X", "Y"], "order": ["Y", "X"], "base_win": 10,
                            "best_win": 40, "base_loss": 80, "best_loss": 50, "gain": 30.0}]}
    monkeypatch.setattr(whatif, "load", lambda f: cache)
    ds = [{"kind": "buy", "round": 5, "you": "A", "better": "B"}, {"kind": "buy", "round": 6, "you": "C", "better": "D"},
          {"kind": "fight", "round": 5}]
    out = with_simulation({"file": "x.json"}, ds)
    assert "no difference" in out[0]["sim_note"]
    assert "+25 points" in out[1]["sim_note"]
    assert out[2]["sim"]["loss"] == 70
    pos = [d for d in out if d["kind"] == "position"]
    assert pos and pos[0]["gain"] == 30.0 and pos[0]["order"] == ["Y", "X"]
