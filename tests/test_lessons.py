"""The one thing: ranking by kind, then size; one impact language; sentences that read right."""
from bgcoach import lessons


def name(cid):
    return {"A": "Alpha", "B": "Bravo", "X": "Xavius"}.get(cid, cid or "?")


def test_rank_by_kind_then_size():
    ms = [{"kind": "fight", "round": 9, "damage": 15},
          {"kind": "rule", "round": 5, "rule": "early_rolls", "title": "Rolling in the early game", "what": "3 rolls", "diff": 0.15},
          {"kind": "hero", "round": 0, "better": "X", "diff": 0.5, "why": ["Xavius finishes top 4 more often."]},
          {"kind": "position", "round": 6, "gain": 23, "base_win": 6, "best_win": 29},
          {"kind": "counter", "round": 4, "gain": 30, "line_kind": "skip_level", "what": "Skip the level-up, buy A",
           "base": {"win": 0, "tie": 0, "loss": 100}, "new": {"win": 20, "tie": 20, "loss": 60}},
          {"kind": "counter", "round": 8, "gain": 67, "line_kind": "instead", "what": "Instead of B, buy A",
           "base": {"win": 7, "tie": 11, "loss": 82}, "new": {"win": 71, "tie": 16, "loss": 13}}]
    ranked = lessons.annotate(ms, name)
    assert [d["kind"] for d in ranked] == ["counter", "counter", "position", "hero", "rule", "fight"]
    assert ranked[0]["round"] == 8 and ranked[0]["rank"] == 0          # the bigger counter first
    assert [d["impact"] for d in ranked] == ["67 pts", "30 pts", "23 pts", "0.50 places", "habit", "15 HP"]
    assert all(d["habit"] for d in ranked)
    assert "Before each buy" in ranked[0]["habit"]                      # 'instead' line → buying habit
    assert "Before you level" in ranked[1]["habit"]                     # 'skip_level' line → levelling habit


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
