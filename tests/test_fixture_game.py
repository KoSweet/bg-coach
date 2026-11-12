"""Parser on the anonymised fixture game (runs everywhere, no network).

Expected values were checked against Hearthstone Deck Tracker's record of the same game
(placement 3, same final board) and against the timeline in the log itself.
"""
import collections
import datetime as dt

from .conftest import FIXTURE_LOG, parse


def test_game_header(fixture_game):
    g = fixture_game
    assert g.build == 255790 and g.game_type == "GT_BATTLEGROUNDS"
    assert g.start.replace(microsecond=0) == dt.datetime(2026, 11, 10, 0, 26, 26)
    assert g.account == 1  # the anonymised log owner
    assert g.hero == "BG20_HERO_242"  # Guff Runetotem
    assert g.hero_offers == ["TB_BaconShop_HERO_67_SKIN_F", "TB_BaconShop_HERO_45", "BG20_HERO_242", "BG22_HERO_001"]
    assert g.anomaly is None


def test_result_and_final_board(fixture_game):
    g = fixture_game
    assert g.complete and g.placement == 3
    assert len(g.turns) == 14
    assert sorted(c["card_id"] for c in g.final_board) == [  # matches HDT's FinalBoard
        "BG25_001_G", "BG25_010_G", "BG32_324_G", "BG34_692", "BG36_515"]
    golden = {c["card_id"]: c.get("golden") for c in g.final_board}
    assert golden["BG25_010_G"] and not golden["BG36_515"]


def test_rounds_tiers_and_gold(fixture_game):
    g = fixture_game
    r1 = g.turns[0]
    assert r1["gold"] == 3 and r1["tier"] == 1
    assert [(a["type"], a.get("target") or a.get("card_id")) for a in r1["actions"]] == [
        ("BUY", "BG28_300"), ("PLAY", "BG28_300")]  # Harmless Bonehead
    tiers = {t["round"]: t["tier"] for t in g.turns}
    assert tiers[2] == 1 and tiers[3] == 2 and tiers[5] == 3 and tiers[7] == 4 and tiers[13] == 5
    levels = [a for t in g.turns for a in t["actions"] if a["type"] == "LEVEL"]
    assert [a["to_tier"] for a in levels] == [2, 3, 4, 5]


def test_combats(fixture_game):
    c = fixture_game.combats
    assert [x["result"] for x in c] == ["WIN", "TIE", "WIN", "WIN", "LOSS", "LOSS", "LOSS", "LOSS",
                                        "WIN", "WIN", "WIN", "WIN", "WIN", "LOSS"]
    assert c[0]["damage_dealt"] == 2
    assert c[4]["damage_taken"] == 10 and c[4]["hp_after"] == 30  # absorbed by armor
    assert c[7]["hp_before"] == 17 and c[7]["hp_after"] == 2
    assert c[-1]["hp_after"] <= 0  # lethal: out in 3rd


def test_shop_click_is_not_a_buy(fixture_game):
    # Clicking a shop card only selects it; a buy is a DragBuy option. Every buy has a target.
    buys = [a for t in fixture_game.turns for a in t["actions"] if a["type"] == "BUY"]
    assert len(buys) == 26 and all(a.get("target") for a in buys)


def test_choices(fixture_game):
    ch = fixture_game.choices
    assert ch[0]["kind"] == "HERO_PICK" and ch[0]["picked"] == "BG20_HERO_242"
    kinds = collections.Counter(c["kind"] for c in ch)
    assert kinds["TRIPLE_DISCOVER"] >= 4 and kinds["TRINKET_PICK"] >= 1


def test_self_checks_and_no_errors(fixture_game):
    g = fixture_game
    assert g.checks_ok == 154 and g.check_failures == [] and g.not_applied == 0
    assert g.errors == []


def test_events_stream():
    events = collections.Counter()
    parse(FIXTURE_LOG, on_event=lambda kind, data: events.update([kind]))
    assert events["round"] == 14 and events["combat"] == 14 and events["game_end"] == 1
    assert events["turn_start"] == 14 and events["tier"] == 4
    assert events["parse_error"] == 0 and events["check_failed"] == 0


def test_game_start_hook_fires_once_with_build():
    seen = []
    from bgcoach.pipeline import base_date_for, open_log
    from bgcoach.replay import Replay
    with open_log(FIXTURE_LOG) as fh:
        Replay(base_date=base_date_for(FIXTURE_LOG), on_game_start=lambda g: seen.append(g.build)).feed_all(fh)
    assert seen == [255790]


def test_round_trip_to_dict(fixture_game):
    import json
    d = json.loads(json.dumps(fixture_game.to_dict(), default=str))
    assert d["placement"] == 3 and len(d["turns"]) == 14 and d["hero"] == "BG20_HERO_242"


def test_partial_copy_never_replaces_the_full_game(tmp_path, monkeypatch, fixture_game):
    # A Power.log archived mid-game (Hearthstone emptied the rest on exit) sits next to the live
    # copy of the full game. Whatever order they are imported in, the full game must win.
    import json

    from bgcoach import pipeline
    from bgcoach.pipeline import base_date_for, open_log
    from bgcoach.replay import Replay
    monkeypatch.setattr(pipeline, "GAMES_DIR", tmp_path)
    with open_log(FIXTURE_LOG) as fh:
        lines = fh.readlines()
    partial = Replay(base_date=base_date_for(FIXTURE_LOG)).feed_all(lines[: len(lines) // 2])[0]
    assert not partial.complete and len(partial.turns) < 14
    assert pipeline.completeness(fixture_game) > pipeline.completeness(partial)

    for order in ((fixture_game, partial), (partial, fixture_game)):
        for f in tmp_path.glob("*.json"):
            f.unlink()
        for g in order:
            p = pipeline.save_game(g)
        saved = json.loads(p.read_text(encoding="utf-8"))
        assert saved["complete"] and saved["placement"] == 3 and len(saved["turns"]) == 14


def test_lobby_every_round(fixture_game):
    # the leaderboard as the game shows it: 8 players, your own slot, tier/health/triples
    g = fixture_game
    r1, r14 = g.turns[0], g.turns[-1]
    assert len(r1["lobby"]) == 8 and r1["me_lobby"] == 7
    assert r1["lobby"]["7"]["hero"] == "BG20_HERO_242" and r1["lobby"]["7"]["tier"] == 1
    assert r14["lobby"]["7"]["triples"] == 7 and r14["lobby"]["2"]["place"] == 1
    assert {c["opp_lobby_id"] for c in g.combats} <= {int(k) for k in r1["lobby"]} - {7}


def test_next_opponent_is_announced_before_each_fight():
    seen = []
    parse(FIXTURE_LOG, on_event=lambda k, d: seen.append(d) if k == "next_opponent" else None)
    games = parse(FIXTURE_LOG)
    fought = [(c["round"], c["opp_lobby_id"]) for c in games[0].combats]
    assert [(d["round"], d["lobby_id"]) for d in seen] == fought


def test_end_of_turn_shop_and_lobby_view(fixture_game):
    from bgcoach import lobby
    g = fixture_game
    assert all(t.get("end_shop") is not None for t in g.turns)
    assert g.turns[5]["end_shop"] and all("atk" in s for s in g.turns[5]["end_shop"])
    import json
    fights = lobby.fights(json.loads(json.dumps(g.to_dict(), default=str)))  # no hero averages offline
    assert len(fights) == 14 and fights[7]["seen_before"] == {"round": 1, "stats": fights[0]["stats"]}


def test_locked_hero_offers(fixture_game):
    # the log marks the heroes only the Tavern Pass unlocks: here the outer two of four
    assert fixture_game.hero_locked == ["TB_BaconShop_HERO_67_SKIN_F", "BG22_HERO_001"]


def test_duos_win_is_read_from_the_enemy_teams_health(monkeypatch):
    # in Duos the hit lands on whichever enemy hero fought last; the leaderboard shows the team's health
    from bgcoach.replay import Game, Replay
    r = Replay()
    r.g = Game(game_type="GT_BATTLEGROUNDS_DUO")
    r.cur_combat = {"round": 3, "hp_before": 30, "armor_before": 10, "opp_lobby_id": 7,
                    "_lobby": {"7": {"hp": 50}, "8": {"hp": 50}}}
    monkeypatch.setattr(r, "lobby", lambda: {"7": {"hp": 41}, "8": {"hp": 41}})
    r._close_combat()
    c = r.g.combats[-1]
    assert c["result"] == "WIN" and c["damage_dealt"] == 9 and "_lobby" not in c
