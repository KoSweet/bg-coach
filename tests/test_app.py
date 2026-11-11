"""End to end: the command line and the app's web API, each in its own process and data folder."""
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from bgcoach import __version__

from .conftest import FIXTURE_LOG, app_env, run_cli


def test_version_flag(tmp_path):
    r = run_cli(tmp_path, "--version")
    assert r.returncode == 0 and r.stdout.strip() == f"bg-coach {__version__}"


def test_help_lists_every_command(tmp_path):
    r = run_cli(tmp_path, "--help")
    for cmd in ("ui", "setup", "log", "import", "archive", "check", "facts", "whatif", "sim-check",
                "version", "share", "overlay", "anonymise"):
        assert cmd in r.stdout, cmd


def test_import_saves_the_game(app_data):
    files = list((app_data / "games").glob("*.json"))
    assert [f.name for f in files] == ["20261110_002626_BG20_HERO_242.json"]
    g = json.loads(files[0].read_text(encoding="utf-8"))
    assert g["placement"] == 3 and g["hero"] == "BG20_HERO_242" and g["account"] == 1
    assert g["source"].endswith("Power.log.gz") and g["hdt"] is None
    imported = json.loads((app_data / "imported.json").read_text(encoding="utf-8"))
    assert len(imported) == 1


def test_import_twice_skips(app_data):
    r = run_cli(app_data, "import")
    assert r.returncode == 0 and "'skipped': 1" in r.stdout


def test_log_timeline(tmp_path, online):
    r = run_cli(tmp_path, "log", str(FIXTURE_LOG))
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert "build 255790" in out and "── Round 14" in out
    assert "BUY      Harmless Bonehead" in out
    assert "PLACEMENT: 3" in out and "Self-checks: 154 passed, 0 failed, 0 not applied" in out
    assert (tmp_path / "games" / "20261110_002626_BG20_HERO_242.json").exists()


# ------------------------------------------------------------------ web API
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _get(base: str, path: str, timeout: float = 120):
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        body = r.read()
        return r.status, (json.loads(body) if r.headers.get_content_type() == "application/json" else body)


@pytest.fixture(scope="module")
def server(app_data, online):
    port = _free_port()
    follow = app_data / "follow.log"  # watch an empty file, never the real Hearthstone log
    follow.write_text("", encoding="utf-8")
    proc = subprocess.Popen([sys.executable, "-m", "bgcoach.cli", "ui", "--port", str(port), "--no-browser",
                             "--no-overlay", "--no-auto-archive", "--follow", str(follow)],
                            env=app_env(app_data), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{port}"
    for _ in range(150):
        try:
            _get(base, "/", timeout=2)
            break
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            if proc.poll() is not None:
                pytest.fail(f"app exited: {proc.stdout.read().decode(errors='replace')}")
            time.sleep(0.2)
    yield base
    try:
        urllib.request.urlopen(urllib.request.Request(base + "/api/quit", data=b"{}", method="POST"), timeout=5)
        proc.wait(timeout=20)
    except Exception:
        proc.kill()


def test_page_and_icon(server):
    status, body = _get(server, "/")
    assert status == 200 and b"bg-coach" in body
    status, body = _get(server, "/icon.png")
    assert status == 200 and body[:4] == b"\x89PNG"


def test_games_list(server):
    status, d = _get(server, "/api/games")
    assert status == 200 and len(d["games"]) == 1
    row = d["games"][0]
    assert row["placement"] == 3 and d["names"][row["hero"]] == "Guff Runetotem"


def test_game_page_has_coaching_or_reason(server):
    status, g = _get(server, "/api/games/20261110_002626_BG20_HERO_242.json")
    assert status == 200 and g["placement"] == 3 and len(g["turns"]) == 14
    assert g["names"]["BG28_300"] == "Harmless Bonehead"
    # coaching needs community stats (Firestone); if they can't be fetched the page says why
    assert "coach" in g or "coach_error" in g
    if "coach" in g:
        assert g["coach"]["strength"] and isinstance(g["coach"]["decisions"], list)


def test_health_and_report(server):
    status, h = _get(server, "/api/health")
    assert status == 200 and h["total_games"] == 1 and h["games"] == []  # no issues in this game
    status, r = _get(server, "/api/report?game=20261110_002626_BG20_HERO_242.json")
    assert status == 200 and "BG20_HERO_242" in r["text"]


def test_unknown_game_is_404(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        _get(server, "/api/games/nope.json")
    assert e.value.code == 404
