"""The raw archive is irreplaceable: it must survive Hearthstone emptying Power.log on exit."""
import collections
import gzip
import os
import time
from pathlib import Path

from bgcoach import archive
from bgcoach.live import LogTee


def _stats():
    return {"copied": 0, "skipped": 0, "bytes": 0, "errors": []}


def gz_text(path) -> str:
    return gzip.decompress(Path(path).read_bytes()).decode("utf-8")


def test_archiver_never_overwrites_with_smaller_file(tmp_path):
    src = tmp_path / "Power.log"
    dst = tmp_path / "arch" / "Power.log"
    src.write_text("line\n" * 1000, encoding="utf-8")
    manifest, stats = {}, _stats()
    archive._archive_file(src, dst, manifest, stats)
    big = gz_text(str(dst) + ".gz")
    assert big.count("line") == 1000

    # Hearthstone exits and empties the log (seen 2026-11-10)
    src.write_text("", encoding="utf-8")
    os.utime(src, (time.time() + 5, time.time() + 5))
    archive._archive_file(src, dst, manifest, stats)
    assert gz_text(str(dst) + ".gz") == big  # untouched

    # a new, shorter log at the same path is kept as a separate version, not over the old one
    src.write_text("new\n" * 10, encoding="utf-8")
    os.utime(src, (time.time() + 10, time.time() + 10))
    archive._archive_file(src, dst, manifest, stats)
    assert gz_text(str(dst) + ".gz") == big
    versions = list((tmp_path / "arch").glob("Power.log.v*.gz"))
    assert len(versions) == 1
    assert gz_text(versions[0]).count("new") == 10


def test_live_tee_is_readable_after_many_flushes(tmp_path, monkeypatch):
    import bgcoach.pipeline as pipeline
    monkeypatch.setattr(pipeline, "RAW", tmp_path)
    src = tmp_path / "Hearthstone_2026_11_10_21_09_24" / "Power.log"
    tee = LogTee(src)
    for i in range(5):
        for j in range(100):
            tee.add(f"chunk {i} line {j}\n")
        tee.flush()
    text = gz_text(tee.path)
    assert collections.Counter(ln.split()[1] for ln in text.splitlines()) == {str(i): 100 for i in range(5)}
