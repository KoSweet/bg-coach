# CLAUDE.md

Notes for Claude Code working in this repository. Read `docs/ARCHITECTURE.md` first: the pipeline,
how the log is read, the self-checks, the coaching rules and the simulator's validated range.

- Python 3.11+ with uv. Run: `uv run bgcoach <command>`; tests: `uv run pytest -q`; lint: `uv run ruff check src tests`.
- Data lives in `data/` (gitignored; `BGCOACH_DATA` overrides; `BGCOACH_HS_DIR`, `BGCOACH_HDT_DIR` too).
  Raw archive: `data/raw/` (gzip logs + `manifest.json`).
- Never modify files under `data/raw/`: it's the irreplaceable source of truth; everything else is regenerable.
- Never commit personal data: no raw logs (only `bgcoach anonymise`d fixtures), nothing from `data/`.
- The previous project (github.com/KoSweet/heartstone-coach) is read-only reference.

## App
- `bgcoach ui` → http://127.0.0.1:8765 (stdlib server `web.py`, page `static/index.html`) + `overlay.py`.
  While open it archives + imports new logs every 30 min and streams the live game (`live.py`).
- Modules: `archive` (raw copy) → `replay` (parser) → `pipeline` (import, HDT match, games on disk)
  → `health` (errors.jsonl, per-game checks, report text) → `web`/`cli`.
- Testing without playing: `bgcoach ui --test [LOG]` replays a log into the Live tab and never saves.
  If the user's own app is running on 8765, use `--port 8799` and a separate `BGCOACH_DATA`.

## When a "bg-coach error report" or "game report" is pasted
It contains the version and commit, the error + traceback, the log file and line number, and the
log lines around the failure (`<data>` = the data folder; names are anonymised). Reproduce by
replaying that log (`uv run bgcoach log <path>`), fix the cause in `replay.py`/`pipeline.py`, add a
regression test (anonymise the game into `tests/fixtures/` if the fixture game doesn't cover it),
re-run `uv run bgcoach check` (HDT agreement must not drop), then `uv run bgcoach import --force`.
Never "fix" by silencing the error or the health check.

## When a "bg-coach problem report (from the user)" is pasted
The user flagged a round where the game did something the app shows wrong or not at all. The report
has their description, what the app recorded (with log line numbers), key raw lines with the clicked
option marked ⇒, and a path to the full raw slice of that round under `<data>/reports/`. Read the
slice, decide whether the parser is wrong or the user misremembered (say which, with the log line as
evidence), and if it's the parser: fix + regression test + `bgcoach check` + `bgcoach import --force`.

Self-checks: every recorded BUY/SELL/LEVEL/PLAY/CAST/REFRESH registers the effect it must have
(`Replay._add_check`), verified when the next options arrive. A failure = the parser recorded
something the game didn't do → error `self_check` with log line. Clicks that land as the turn timer
ends are `applied: false` (real, not a bug).

## Coaching
- `meta.py` (Firestone stats per MMR bracket, daily snapshots in data/meta), `analysis.py`
  (per-game coach + improve report), `decisions.py` (either/or moments), `facts.py`
  (`bgcoach facts` → used by `/review-session`).
- Live advice: the parser emits `offers` before a pick; `web.Hub.coach` adds meta values, synergy
  and board strength; overlay/Live tab show them.
- Every coaching number must say its evidence (meta = correlation at the user's MMR; yours = own
  games, small n; simulator = rounds ≤10). Don't present card stats as rules.

## Synergy (never suggest off-build cards)
`synergy.py` scores each option against the build at that moment: 3 = main tribe / strongly played
theme, 2 = no tribe / flexible (spell & gold engines), 1 = side tribe, 0 = tribe you don't play.
Buys, picks and live advice only suggest an alternative that fits at least as well as what was
taken. Balinda (spell engine) over Hooktusk (Pirate) in a Beast build is right; the old stats-only
advice was wrong. Keep it that way (tests/test_synergy.py).

## Combat simulator
- `sim/run.js` wraps Firestone's simulator (npm, installed with --ignore-scripts, licence "All rights
  reserved": personal local use only, never commit node_modules or sim/cards_cache.json).
- `combat_sim.build_battle` → `simulate`; `whatif.py` caches per-game results in data/sim/<game>.json.
  Only rounds ≤10, only fights passing the trust check (within 15 pts of Bob's Buddy, or the real
  result ≥25% in the simulation). Re-validate after simulator updates: `uv run bgcoach sim-check --logs 2`.

## Platforms
- Windows: `bg-coach.vbs` (or the shortcut from `bgcoach setup --shortcut`) starts
  `pythonw -m bgcoach.cli ui` with no console; output → data/app.log. `bg-coach-debug.bat` = with console.
- macOS: `mac/setup.command` (uv sync, `bgcoach setup`, optional npm for sim/, builds bg-coach.app).
- All locations come from `paths.py`. HDT/Bob's Buddy are Windows-only and optional; everything
  must work without them.
- `bgcoach share` builds dist/bg-coach-<date>.zip: code + launchers + docs only (no data).
