# CLAUDE.md

Read `PLAN.md` first — it holds the goal, architecture, verified data sources, and phase exit criteria.

- Python 3.11 + uv. Run: `uv run python -m bgcoach.<module>`; tests: `uv run pytest -q`.
- Data lives in `data/` (gitignored; override with `BGCOACH_DATA`). Raw archive: `data/raw/` (gzip logs + `manifest.json`).
- Never modify files under `data/raw/` — it's the irreplaceable source of truth; everything else is regenerable.
- Old project (github.com/KoSweet/heartstone-coach) is read-only reference.

## App
- `bg-coach.bat` (double-click) → `bgcoach ui` → http://127.0.0.1:8765 (stdlib server `web.py`, page `static/index.html`).
  While open it archives + imports new logs every 30 min and streams the live game (`live.py`).
- Modules: `archive` (raw copy) → `replay` (parser) → `pipeline` (import, HDT match, games on disk)
  → `health` (errors.jsonl, per-game checks, report text) → `web`/`cli`.

## When the user pastes a "bg-coach error report" or "game report"
It contains the repo commit, the error + traceback, the archived log path and line number, and the
log lines around the failure. Reproduce by replaying that log (`uv run bgcoach log <path>`), fix the
cause in `replay.py`/`pipeline.py`, add a regression test in `tests/` using that log, re-run
`uv run bgcoach check` (HDT agreement must stay 100%), then `uv run bgcoach import --force`.
Never "fix" by silencing the error or the health check.

## When the user pastes a "bg-coach problem report (from the user)"
The user flagged a round where the game did something the app shows wrong or not at all. The report
has their description, what the app recorded (with log line numbers), key raw lines with the clicked
option marked ⇒, and a path to the full raw slice of that round under `data/reports/`. Read the
slice, decide whether the parser is wrong or the user misremembered (say which, with the log line as
evidence), and if it's the parser: fix + regression test + `bgcoach check` + `bgcoach import --force`.

Self-checks: every recorded BUY/SELL/LEVEL/PLAY/CAST/REFRESH registers the effect it must have
(`Replay._add_check`), verified when the next options arrive. A failure = the parser recorded
something the game didn't do → error `self_check` with log line. Clicks that land as the turn timer
ends are `applied: false` (real, not a bug). The overlay (`overlay.py`, starts with `bgcoach ui`)
shows the green/red state to the user while playing.

Testing without playing: `bg-coach-test.bat` (= `bgcoach ui --test`) replays the newest archived log
into the Live tab. Use another `--port` if the user's app is already running on 8765.

## Coaching
- `meta.py` (Firestone stats per MMR bracket, daily snapshots in data/meta), `analysis.py`
  (per-game Coach + improve_report), `facts.py` (`bgcoach facts` → used by `/review-session`).
- Live advice: parser emits `offers` before a pick; `web.Hub.coach` adds meta values and board
  strength; overlay/Live tab show them. Test mode (`ui --test`) never saves games.
- Every coaching number must say its evidence (meta = correlation at the user's MMR; yours = own
  games, small n). Don't present card stats as rules.

## Combat simulator (phase 4)
- `sim/run.js` wraps Firestone's simulator (npm, installed with --ignore-scripts, licence "All rights
  reserved": personal local use only, never commit node_modules). Card data cached in sim/cards_cache.json.
- `combat_sim.build_battle` → `simulate`; `whatif.py` caches per-game results in data/sim/<game>.json
  (fight odds, buy what-ifs, positioning). Only rounds ≤10, only fights passing the trust check
  (within 15 pts of Bob's Buddy, or the real result ≥25% in the simulation).
- Re-validate after simulator updates: `uv run bgcoach sim-check --logs 2`.

## Synergy (never suggest off-build cards)
`synergy.py` scores each option against the build at that moment: 3 = main tribe / strongly played
theme, 2 = no tribe / flexible (spell & gold engines), 1 = side tribe, 0 = tribe you don't play.
Buys, picks and live pick advice only suggest an alternative that fits at least as well as what was
taken. User feedback 2026-11-11: Balinda (spell engine) over Hooktusk (Pirate) in a Beast build was
right; the old stats-only advice was wrong. Keep it that way (tests/test_synergy.py).

## Running as an app / other machines
- Windows: `bg-coach.vbs` (or the Desktop/Start-menu shortcut from `bgcoach setup --shortcut`) starts
  `pythonw -m bgcoach.cli ui` with no console; output → data/app.log; Quit via the header button or the
  overlay ✕ menu (POST /api/quit). `bg-coach-debug.bat` = with console.
- macOS: `mac/setup.command` (uv sync, `bgcoach setup`, optional npm for sim/, builds bg-coach.app via
  osacompile). NOT yet run on a real Mac — paths tested by simulation only (tests/test_paths.py).
- All locations come from `paths.py` (BGCOACH_DATA, BGCOACH_HS_DIR overrides). HDT/Bob's Buddy are
  Windows-only and optional; everything must work without them.
- `bgcoach share` builds dist/bg-coach-<date>.zip: code + launchers + README only (no data, no notes).
