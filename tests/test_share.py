"""`bgcoach share` must never pack personal data."""
import zipfile

from bgcoach import share
from bgcoach.paths import REPO


def test_share_contains_code_not_data():
    rel = {p.relative_to(REPO).as_posix() for p in share.files()}
    assert {"README.md", "pyproject.toml", "mac/setup.command", "bg-coach.vbs", "src/bgcoach/cli.py"} <= rel
    for r in rel:
        assert not r.startswith(("data/", ".venv/", "dist/", "sim/node_modules/")), r
        assert "__pycache__" not in r and not r.endswith(".pyc"), r
    assert "sim/cards_cache.json" not in rel  # downloaded by the simulator, not ours to share


def test_share_zip_layout(tmp_path):
    z = share.build(tmp_path)
    with zipfile.ZipFile(z) as zz:
        names = zz.namelist()
        mode = zz.getinfo("bg-coach/mac/setup.command").external_attr >> 16
    assert all(n.startswith("bg-coach/") for n in names)
    assert mode & 0o111, "setup.command must stay executable for macOS"
