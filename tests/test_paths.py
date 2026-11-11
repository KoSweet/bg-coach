"""Cross-platform locations + Hearthstone logging setup (macOS logic tested by simulation)."""
from pathlib import Path

from bgcoach import paths


def test_ensure_logging_creates_and_is_idempotent(tmp_path):
    cfg = tmp_path / "Blizzard" / "Hearthstone" / "log.config"
    assert paths.ensure_logging(cfg) is True           # created
    text = cfg.read_text(encoding="utf-8")
    assert "[Power]" in text and "Verbose=True" in text and "FilePrinting=True" in text
    assert paths.ensure_logging(cfg) is False          # nothing to change the second time
    assert cfg.read_text(encoding="utf-8") == text


def test_ensure_logging_keeps_other_sections_and_fixes_power(tmp_path):
    cfg = tmp_path / "log.config"
    cfg.write_text("[Achievements]\nLogLevel=1\nFilePrinting=True\n[Power]\nLogLevel=1\nVerbose=False\n", encoding="utf-8")
    assert paths.ensure_logging(cfg) is True
    text = cfg.read_text(encoding="utf-8")
    assert "[Achievements]" in text                      # untouched section kept
    power = text.split("[Power]")[1].split("[")[0]
    assert "Verbose=True" in power and "Verbose=False" not in power


def test_mac_locations(monkeypatch):
    monkeypatch.setattr(paths, "IS_MAC", True)
    monkeypatch.setattr(paths, "IS_WIN", False)
    monkeypatch.delenv("BGCOACH_HS_DIR", raising=False)
    cands = paths.hs_dir_candidates()
    assert cands[0] == Path("/Applications/Hearthstone")
    assert paths.log_config_path().parts[-4:] == ("Preferences", "Blizzard", "Hearthstone", "log.config")


def test_hs_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BGCOACH_HS_DIR", str(tmp_path))
    assert paths.hs_dir_candidates() == [tmp_path]


def test_data_dir_is_inside_project_by_default():
    import os
    if not os.environ.get("BGCOACH_DATA"):
        assert paths.DATA == paths.REPO / "data"
