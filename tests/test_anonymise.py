"""`bgcoach anonymise`: logs shared in bug reports / used as fixtures must carry no personal data."""
import gzip
import re
from pathlib import Path

from bgcoach.anonymise import anonymise_file, anonymise_lines, select_games

from .conftest import FIXTURE_LOG, FIXTURES, parse


def test_problem_report_is_safe_to_post_publicly():
    from bgcoach import health
    from bgcoach.paths import DATA
    text = health.private(f"log: {DATA / 'raw' / 'Power.log.gz'}\ntraceback: {Path.home() / 'x.py'}\n"
                          ">> 5: GameState.DebugPrintPower() - TAG_CHANGE Entity=Somebody#1234 tag=X value=1\n"
                          "   6: GameState.DebugPrintPower() - TAG_CHANGE Entity=Bartender Bob tag=Y value=1\n")
    assert str(DATA) not in text and str(Path.home()) not in text and "Somebody" not in text
    assert "<data>" in text and "Entity=You#0001" in text and "Entity=Bartender Bob" in text

LINES = [
    "D 20:00:00.0000000 GameState.DebugPrintPower() - CREATE_GAME\n",
    "D 20:00:00.0000000 GameState.DebugPrintPower() -     Player EntityID=20 PlayerID=7 GameAccountId=[hi=144115 lo=8166]\n",
    "D 20:00:00.0000000 GameState.DebugPrintPower() -     Player EntityID=21 PlayerID=15 GameAccountId=[hi=0 lo=0]\n",
    "D 20:00:00.0000000 GameState.DebugPrintGame() - PlayerID=7, PlayerName=Somebody#12345\n",
    "D 20:00:00.0000000 GameState.DebugPrintGame() - PlayerID=15, PlayerName=SomeoneElse\n",
    "D 20:00:01.0000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=Somebody#12345 tag=RESOURCES value=3 \n",
    "D 20:00:01.0000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=고양이 tag=PLAYER_LEADERBOARD_PLACE value=2 \n",
    "D 20:00:01.0000000 GameState.DebugPrintPower() - TAG_CHANGE Entity=Bartender Bob tag=ZONE value=PLAY \n",
    "D 20:00:01.0000000 GameState.DebugPrintPower() -     FULL_ENTITY - Updating [entityName=Bartender Bob id=21 "
    "zone=PLAY zonePos=0 cardId=TB_BaconShopBob player=15] CardID=TB_BaconShopBob\n",
    "D 20:00:02.0000000 GameState.DebugPrintEntityChoices() - id=3 Player=Somebody#12345 TaskList= ChoiceType=GENERAL\n",
    "D 20:00:02.0000000 PowerTaskList.DebugPrintPower() - TAG_CHANGE Entity=Somebody#12345 tag=X value=1 \n",
]


def test_names_and_accounts_replaced():
    out, info = anonymise_lines(select_games(LINES))
    text = "".join(out)
    assert "Somebody" not in text and "12345" not in text and "고양이" not in text and "SomeoneElse" not in text
    assert "lo=8166" not in text and "hi=144115" not in text
    assert "PlayerName=You#0001" in text and "Entity=You#0001 tag=RESOURCES" in text
    assert "Player=You#0001 TaskList" in text
    assert "GameAccountId=[hi=1 lo=1]" in text and "GameAccountId=[hi=0 lo=0]" in text
    assert "Entity=Bartender Bob tag=ZONE" in text  # card names are game data, kept
    assert re.search(r"Entity=Opponent\d+ tag=PLAYER_LEADERBOARD_PLACE", text)
    assert info["leftover_tags"] == []


def test_only_gamestate_lines_kept():
    out, _ = anonymise_lines(select_games(LINES))
    assert all("GameState." in ln for ln in out) and len(out) == len(LINES) - 1


def test_select_one_game():
    two = LINES + LINES
    assert len(select_games(two, game=2)) == len(select_games(LINES))
    assert select_games(two, game=3) == []


def test_fixture_is_anonymous():
    """Guard: never commit a personal log. Every fixture must already be anonymised."""
    for f in FIXTURES.glob("*.log.gz"):
        text = gzip.decompress(f.read_bytes()).decode("utf-8")
        tags = set(re.findall(r"[^\s=\[\]]+#\d{3,6}\b", text))
        assert tags <= {"You#0001"}, f"{f.name}: BattleTag-like strings {tags}"
        accounts = set(re.findall(r"GameAccountId=\[hi=\d+ lo=\d+\]", text))
        assert accounts <= {"GameAccountId=[hi=1 lo=1]", "GameAccountId=[hi=0 lo=0]"}, f"{f.name}: {accounts}"
        names = {m.group(1) for m in re.finditer(r"PlayerName=(\S+)", text)}
        assert all(n == "You#0001" or n.startswith("Opponent") for n in names), names


def test_anonymising_twice_changes_nothing(tmp_path):
    out = tmp_path / "again.log.gz"
    anonymise_file(FIXTURE_LOG, out)
    assert gzip.decompress(out.read_bytes()) == gzip.decompress(FIXTURE_LOG.read_bytes())


def test_anonymised_log_parses_the_same(tmp_path):
    # the fixture's parse must not depend on names: re-anonymise as plain text and parse again
    out = tmp_path / "Power_2026_11_10.log"
    anonymise_file(FIXTURE_LOG, out)
    a, b = parse(FIXTURE_LOG)[0].to_dict(), parse(out)[0].to_dict()
    a.pop("source", None)
    b.pop("source", None)
    assert a == b
