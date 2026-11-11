"""Where things are, on Windows and macOS.

Every location can be overridden with an environment variable:
  BGCOACH_DATA    app data (default: <project>/data)
  BGCOACH_HS_DIR  Hearthstone install folder (the one containing "Logs")
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

REPO = Path(__file__).resolve().parents[2]
DATA = Path(os.environ.get("BGCOACH_DATA") or (REPO / "data"))

HOME = Path.home()


def _hdt_dir() -> Path | None:
    """Hearthstone Deck Tracker (Windows only): game history + Bob's Buddy odds."""
    if not IS_WIN or not os.environ.get("APPDATA"):
        return None
    p = Path(os.environ["APPDATA"]) / "HearthstoneDeckTracker"
    return p if p.exists() else None


HDT_DIR = _hdt_dir()


def _hdt_hs_dir() -> Path | None:
    """HDT remembers where Hearthstone is installed."""
    if HDT_DIR is None:
        return None
    try:
        m = re.search(r"<HearthstoneDirectory>([^<]+)</HearthstoneDirectory>",
                      (HDT_DIR / "config.xml").read_text(encoding="utf-8", errors="replace"))
        return Path(m.group(1)) if m else None
    except OSError:
        return None


def hs_dir_candidates() -> list[Path]:
    if os.environ.get("BGCOACH_HS_DIR"):
        return [Path(os.environ["BGCOACH_HS_DIR"])]
    if IS_MAC:
        return [Path("/Applications/Hearthstone"), HOME / "Applications" / "Hearthstone"]
    cands = [_hdt_hs_dir()]
    for drive in ("C", "D", "E", "F"):
        cands += [Path(f"{drive}:/Program Files (x86)/Hearthstone"), Path(f"{drive}:/Program Files/Hearthstone"),
                  Path(f"{drive}:/Hearthstone"), Path(f"{drive}:/Games/Hearthstone")]
    return [c for c in cands if c]


def hs_dir() -> Path:
    """The Hearthstone install folder (first candidate that exists; default otherwise)."""
    cands = hs_dir_candidates()
    for c in cands:
        if (c / "Logs").exists() or (c / "Hearthstone.exe").exists() or (c / "Hearthstone.app").exists():
            return c
    return cands[0] if cands else Path("Hearthstone")


HS_DIR = hs_dir()
HS_LOGS = HS_DIR / "Logs"


def log_config_path() -> Path:
    """Hearthstone's logging settings file."""
    if IS_MAC:
        return HOME / "Library" / "Preferences" / "Blizzard" / "Hearthstone" / "log.config"
    base = os.environ.get("LOCALAPPDATA") or str(HOME / "AppData" / "Local")
    return Path(base) / "Blizzard" / "Hearthstone" / "log.config"


REQUIRED_LOGS = {  # the parser reads Power; LoadingScreen helps detect modes
    "Power": {"LogLevel": "1", "FilePrinting": "True", "ConsolePrinting": "False",
              "ScreenPrinting": "False", "Verbose": "True"},
    "LoadingScreen": {"LogLevel": "1", "FilePrinting": "True", "ConsolePrinting": "False",
                      "ScreenPrinting": "False", "Verbose": "False"},
}


def ensure_logging(path: Path | None = None) -> bool:
    """Make sure Hearthstone writes the logs we need. Adds/fixes only our sections; keeps the rest.
    Returns True if the file changed (Hearthstone must be restarted to pick it up)."""
    path = path or log_config_path()
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    sections: dict[str, dict[str, str]] = {}
    order: list[str] = []
    cur = None
    for line in text.splitlines():
        m = re.match(r"^\s*\[(.+?)\]\s*$", line)
        if m:
            cur = m.group(1)
            sections.setdefault(cur, {})
            order.append(cur)
        elif cur and "=" in line:
            k, v = line.split("=", 1)
            sections[cur][k.strip()] = v.strip()
    changed = False
    for name, want in REQUIRED_LOGS.items():
        have = sections.setdefault(name, {})
        if name not in order:
            order.append(name)
        for k, v in want.items():
            if have.get(k) != v:
                have[k] = v
                changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        out = []
        for name in order:
            out.append(f"[{name}]")
            out += [f"{k}={v}" for k, v in sections[name].items()]
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def screenshot_dirs() -> list[Path]:
    """Where Hearthstone saves screenshots (the Desktop, possibly redirected)."""
    cands = [HOME / "Desktop", HOME / "OneDrive" / "Desktop", HOME / "Pictures" / "Screenshots"]
    if IS_WIN:
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf)  # CSIDL_DESKTOPDIRECTORY
            if buf.value:
                cands.insert(0, Path(buf.value))
        except Exception:  # noqa: BLE001
            pass
    out: list[Path] = []
    for c in cands:
        if c.exists() and c.resolve() not in [o.resolve() for o in out]:
            out.append(c)
    return out


# fonts for the overlay
FONT = "Segoe UI" if IS_WIN else "Helvetica Neue" if IS_MAC else "DejaVu Sans"
MONO = "Consolas" if IS_WIN else "Menlo" if IS_MAC else "DejaVu Sans Mono"
