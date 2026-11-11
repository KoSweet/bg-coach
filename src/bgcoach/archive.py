"""Raw-data archiver: never lose a game log again.

Hearthstone keeps only the last few session folders under <HS>/Logs and deletes
older ones. This copies every session's logs (gzip-compressed) plus HDT's
Battlegrounds history + logs into the archive. Idempotent: a file is re-copied
only when its size or mtime changed (so an in-progress session is refreshed on
the next run).

Usage:
    python -m bgcoach.archive                 # archive HS + HDT
    python -m bgcoach.archive --import-legacy # also one-time import of old-repo logs
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

from .paths import DATA, HDT_DIR, HS_LOGS

ARCHIVE = DATA / "raw"
# optional one-time import of logs collected by an older project (set BGCOACH_LEGACY_REPO)
LEGACY_REPO = Path(os.environ["BGCOACH_LEGACY_REPO"]) if os.environ.get("BGCOACH_LEGACY_REPO") else None
MANIFEST = ARCHIVE / "manifest.json"


def _load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _save_manifest(m: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST.with_suffix(".tmp")
    tmp.write_text(json.dumps(m, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(MANIFEST)


def _sig(p: Path) -> list:
    st = p.stat()
    return [st.st_size, int(st.st_mtime)]


def _copy(src: Path, dst: Path, compress: bool) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    # HS keeps the log open; open with shared read via plain open() (works on Windows).
    with open(src, "rb") as fi:
        if compress:
            with gzip.open(tmp, "wb", compresslevel=6) as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
        else:
            with open(tmp, "wb") as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
    tmp.replace(dst)


def _archive_file(src: Path, dst: Path, manifest: dict, stats: dict) -> None:
    compress = src.suffix.lower() in (".log", ".txt", ".xml")
    if compress:
        dst = dst.with_name(dst.name + ".gz")
    key = str(src)
    sig = _sig(src)
    if manifest.get(key, {}).get("sig") == sig and dst.exists():
        stats["skipped"] += 1
        return
    # NEVER replace an archived copy with a smaller file. Hearthstone empties Power.log when it
    # exits (seen 2026-11-10: 430 MB -> 0 bytes), which once overwrote a whole session's archive.
    old = manifest.get(key, {}).get("sig")
    if old and dst.exists() and sig[0] < old[0]:
        if sig[0] == 0:
            stats["skipped"] += 1
            return
        dst = dst.with_name(f"{dst.name.removesuffix('.gz')}.v{sig[1]}" + (".gz" if compress else ""))
        key = f"{key}#v{sig[1]}"
        if key in manifest:
            stats["skipped"] += 1
            return
    try:
        _copy(src, dst, compress)
    except OSError as e:  # locked / vanished mid-copy: retry next run
        stats["errors"].append(f"{src}: {e}")
        return
    manifest[key] = {"sig": sig, "dst": str(dst), "archived_at": int(time.time())}
    stats["copied"] += 1
    stats["bytes"] += sig[0]


def archive_hs(manifest: dict, stats: dict) -> None:
    if not HS_LOGS.exists():
        stats["errors"].append(f"missing {HS_LOGS}")
        return
    for session in sorted(HS_LOGS.glob("Hearthstone_*")):
        if not session.is_dir():
            continue
        for f in session.iterdir():
            if f.is_file():
                _archive_file(f, ARCHIVE / "hs" / session.name / f.name, manifest, stats)


def archive_hdt(manifest: dict, stats: dict) -> None:
    if HDT_DIR is None or not HDT_DIR.exists():
        return
    # BgsLastGames.xml is a rolling window: keep one snapshot per distinct content.
    xml = HDT_DIR / "BgsLastGames.xml"
    if xml.exists():
        h = hashlib.sha256(xml.read_bytes()).hexdigest()[:12]
        dst = ARCHIVE / "hdt" / "BgsLastGames" / f"{time.strftime('%Y%m%d')}_{h}.xml"
        if not any((ARCHIVE / "hdt" / "BgsLastGames").glob(f"*_{h}.xml.gz")):
            _archive_file(xml, dst, manifest, stats)
    for f in sorted((HDT_DIR / "Logs").glob("*.txt")):
        _archive_file(f, ARCHIVE / "hdt" / "logs" / f.name, manifest, stats)


def import_legacy(manifest: dict, stats: dict) -> None:
    if LEGACY_REPO is None:
        stats["errors"].append("set BGCOACH_LEGACY_REPO to the old project folder")
        return
    for f in sorted((LEGACY_REPO / "data" / "real_players_logs").glob("*.log")):
        _archive_file(f, ARCHIVE / "legacy" / "real_players_logs" / f.name, manifest, stats)
    z = HS_LOGS.parent / "Logs.zip"
    if z.exists():
        _archive_file(z, ARCHIVE / "legacy" / "Logs_2026-04.zip", manifest, stats)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--import-legacy", action="store_true")
    args = ap.parse_args(argv)
    t0 = time.time()
    manifest = _load_manifest()
    stats = {"copied": 0, "skipped": 0, "bytes": 0, "errors": []}
    archive_hs(manifest, stats)
    archive_hdt(manifest, stats)
    if args.import_legacy:
        import_legacy(manifest, stats)
    _save_manifest(manifest)
    msg = (f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] copied={stats['copied']} "
           f"({stats['bytes'] / 1e6:.0f} MB raw) skipped={stats['skipped']} "
           f"errors={len(stats['errors'])} in {time.time() - t0:.0f}s")
    print(msg)
    for e in stats["errors"]:
        print("  ERR", e)
    log = ARCHIVE / "archive.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(msg + "\n" + "".join(f"  ERR {e}\n" for e in stats["errors"]))
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
