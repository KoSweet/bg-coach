"""First-run setup: check locations, turn on Hearthstone logging, Windows shortcuts, windowless output."""
from __future__ import annotations

import subprocess
import sys

from . import paths


def windowless_logging() -> None:
    """Started without a console (pythonw / macOS app): send output to data/app.log."""
    if sys.stdout is None or sys.stderr is None:
        paths.DATA.mkdir(parents=True, exist_ok=True)
        f = open(paths.DATA / "app.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115 (lives for the process)
        sys.stdout = sys.stderr = f


def run_setup(shortcut: bool = False) -> None:
    from .combat_sim import available
    system = "Windows" if paths.IS_WIN else "macOS" if paths.IS_MAC else sys.platform
    print("bg-coach setup")
    print(f"  system           : {system}")
    print(f"  data folder      : {paths.DATA}")
    found = paths.HS_LOGS.exists()
    print(f"  Hearthstone      : {paths.HS_DIR} {'(found)' if found else '(NOT FOUND: set BGCOACH_HS_DIR)'}")
    changed = paths.ensure_logging()
    note = "(updated: restart Hearthstone once)" if changed else "(already OK)"
    print(f"  logging settings : {paths.log_config_path()} {note}")
    hdt = paths.HDT_DIR or "not installed: no HDT history / Bob's Buddy odds"
    print(f"  HDT (optional)   : {hdt}")
    sim = "ready" if available() else "not installed (optional: needs Node.js, see README)"
    print(f"  combat simulator : {sim}")
    if shortcut and paths.IS_WIN:
        make_windows_shortcut()


def make_windows_shortcut() -> None:
    """Desktop + Start-menu shortcut that starts bg-coach without a console window."""
    vbs = paths.REPO / "bg-coach.vbs"
    ico = paths.REPO / "src" / "bgcoach" / "static" / "icon.ico"
    ps = (
        "$s=(New-Object -ComObject WScript.Shell);"
        "foreach($d in @([Environment]::GetFolderPath('Desktop'),[Environment]::GetFolderPath('Programs'))){"
        "$l=$s.CreateShortcut((Join-Path $d 'bg-coach.lnk'));"
        f"$l.TargetPath='wscript.exe';$l.Arguments='\"{vbs}\"';$l.WorkingDirectory='{paths.REPO}';"
        f"$l.IconLocation='{ico}';$l.Description='bg-coach: Battlegrounds coach';$l.Save()}}"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, check=False)
    print("  shortcut         :", "created on Desktop + Start menu" if r.returncode == 0 else r.stderr.strip()[:200])
