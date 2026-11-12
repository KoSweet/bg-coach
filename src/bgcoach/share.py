"""Build a clean zip to give to someone else (e.g. a friend on a Mac).

  bgcoach share   ->  dist/bg-coach-<date>.zip

Contains the code, launchers and README only: never your data folder (games, logs, screenshots,
reports), your Python environment, the downloaded simulator or your personal notes.
"""
from __future__ import annotations

import datetime as dt
import stat
import zipfile
from pathlib import Path

from .paths import REPO

INCLUDE_FILES = ["README.md", "LICENSE", "NOTICE", "CHANGELOG.md", "pyproject.toml", "uv.lock", ".gitignore", "bg-coach.vbs", "bg-coach.bat",
                 "bg-coach-debug.bat", "bg-coach-test.bat", "mac/setup.command", "sim/run.js", "sim/package.json",
                 "sim/package-lock.json", "sim/test_battles.jsonl", ".claude/commands/review-session.md"]
INCLUDE_DIRS = ["src", "tests"]
EXECUTABLE = {"mac/setup.command"}
SKIP_PARTS = {"__pycache__", ".pytest_cache"}


def files() -> list[Path]:
    out = [REPO / f for f in INCLUDE_FILES if (REPO / f).exists()]
    for d in INCLUDE_DIRS:
        for p in sorted((REPO / d).rglob("*")):
            if p.is_file() and not (SKIP_PARTS & set(p.parts)) and p.suffix != ".pyc":
                out.append(p)
    return out


def build(dist: Path | None = None) -> Path:
    dist = dist or REPO / "dist"
    dist.mkdir(parents=True, exist_ok=True)
    zpath = dist / f"bg-coach-{dt.date.today():%Y%m%d}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files():
            rel = p.relative_to(REPO).as_posix()
            info = zipfile.ZipInfo(f"bg-coach/{rel}", date_time=dt.datetime.fromtimestamp(p.stat().st_mtime).timetuple()[:6])
            mode = 0o755 if rel in EXECUTABLE else 0o644
            info.external_attr = (stat.S_IFREG | mode) << 16  # keep setup.command executable on macOS
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, p.read_bytes())
    return zpath


def main(argv=None):
    z = build()
    with zipfile.ZipFile(z) as zz:
        names = zz.namelist()
    print(f"{z}  ({z.stat().st_size / 1e6:.1f} MB, {len(names)} files)")
    print("contains no data/, .venv/, simulator download or personal notes")


if __name__ == "__main__":
    main()
