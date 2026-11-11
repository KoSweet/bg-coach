"""Shared test fixtures.

`tests/fixtures/Power_2026_11_10_bg.log.gz` is one real Battlegrounds game (Guff Runetotem, 3rd place,
14 rounds) made shareable with `bgcoach anonymise`: only the GameState lines the parser reads,
player names replaced (You#0001, Opponent1…), account ids replaced. It lets every parser, import,
coaching and app test run anywhere, including CI, without anyone's personal log archive.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from bgcoach import paths
from bgcoach.pipeline import base_date_for, open_log
from bgcoach.replay import Game, Replay

FIXTURES = Path(__file__).parent / "fixtures"
FIXTURE_LOG = FIXTURES / "Power_2026_11_10_bg.log.gz"
FIXTURE_BUILD = 255790
# where the archiver would have put it: the session folder name carries the date
SESSION = "Hearthstone_2026_11_10_00_25_38"


def parse(path: Path, on_event=None) -> list[Game]:
    with open_log(path) as fh:
        return Replay(base_date=base_date_for(path), on_event=on_event).feed_all(fh)


@pytest.fixture(scope="session")
def fixture_game() -> Game:
    games = parse(FIXTURE_LOG)
    assert len(games) == 1
    return games[0]


@pytest.fixture(scope="session")
def card_db():
    """The card database for the fixture's build (downloaded once, then cached)."""
    from bgcoach import version as V
    try:
        db = V.card_db(FIXTURE_BUILD)
    except Exception as e:  # offline and not cached
        pytest.skip(f"card database unavailable (offline?): {e}")
    if len(db.by_id) < 1000:
        pytest.skip("card database unavailable (offline?)")
    return db


def app_env(data: Path) -> dict[str, str]:
    """Environment for a bg-coach subprocess that only sees `data` (no real Hearthstone / HDT)."""
    env = dict(os.environ)
    env.update({"BGCOACH_DATA": str(data), "BGCOACH_HS_DIR": str(data / "no-hearthstone"),
                "BGCOACH_HDT_DIR": "", "PYTHONIOENCODING": "utf-8"})
    return env


def run_cli(data: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "bgcoach.cli", *args], env=app_env(data), capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, check=False)


@pytest.fixture(scope="session")
def online() -> int:
    """Card data + patch list reachable (or cached). Returns the current Battlegrounds build."""
    from bgcoach import version as V
    try:
        build = V.current_bg_meta_build()
        V.card_db(FIXTURE_BUILD)
        V.card_db(build)
    except Exception as e:
        pytest.skip(f"needs network the first time: {e}")
    return build


def _seed_cache(data: Path) -> None:
    """Copy already-downloaded card data into a fresh data folder (saves re-downloading 30 MB files)."""
    from bgcoach import version as V
    names = {"patches.json", f"cards_{FIXTURE_BUILD}.json"}
    try:
        names.add(f"cards_{V.current_bg_meta_build()}.json")
    except Exception:
        pass
    for name in names:
        src = paths.DATA / "cache" / name
        if src.exists():
            (data / "cache").mkdir(exist_ok=True)
            shutil.copy(src, data / "cache" / name)


@pytest.fixture(scope="session")
def app_data(tmp_path_factory) -> Path:
    """A fresh data folder holding the fixture log as if the archiver had copied it, then imported."""
    data = tmp_path_factory.mktemp("bgcoach-data")
    session = data / "raw" / "hs" / SESSION
    session.mkdir(parents=True)
    shutil.copy(FIXTURE_LOG, session / "Power.log.gz")
    _seed_cache(data)
    r = run_cli(data, "import")
    assert r.returncode == 0, r.stderr
    return data
