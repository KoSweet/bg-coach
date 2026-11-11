# Contributing

Bug reports from real games are the most valuable contribution: a parser that is right in every
game is what everything else stands on. Ideas, fixes and new coaching checks are welcome too.

## Reporting a problem

Use the app's **Copy report** (Health tab, or ⚑ on a round) and paste it into a
[bug report](https://github.com/KoSweet/bg-coach/issues/new?template=bug_report.yml). The report already
has BattleTags, player names and your folder names removed. If a log is needed, attach an
anonymised one:

```sh
uv run bgcoach anonymise "path/to/Power.log" --game 2   # → Power.anon.log.gz
```

Never attach a raw `Power.log` or anything from `data/`.

## Development setup

You need [uv](https://docs.astral.sh/uv/). Python is installed by uv if needed.

```sh
git clone https://github.com/KoSweet/bg-coach.git
cd bg-coach
uv sync                       # Python 3.11+, Pillow, pytest, ruff
uv run pytest -q              # ~1 minute; downloads public card data the first time
uv run ruff check src tests
uv run bgcoach ui --test      # the app, replaying a recorded game (needs an archived log)
```

Run the test copy of the app on another port (`--port 8799`) if your own copy is open on 8765.
`BGCOACH_DATA=/some/folder` gives it a separate data folder.

The combat simulator is optional: with [Node.js](https://nodejs.org) installed,
`cd sim && npm install --ignore-scripts` enables it (it is third-party code under its own licence;
never commit `sim/node_modules`).

## How the code is organised

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the pipeline, how the log is read, the
self-checks, and the coaching rules. In short: `replay.py` parses, `pipeline.py` stores,
`analysis.py`/`decisions.py`/`synergy.py` coach, `web.py` + `static/index.html` + `overlay.py`
show it.

## Rules of thumb

- **Parser changes need a regression test from a real log.** Anonymise it with
  `bgcoach anonymise --game N -o tests/fixtures/<name>.log.gz`, keep only the game you need, and
  assert the facts you verified (ideally against HDT or the in-game screen). `test_fixture_is_anonymous`
  refuses fixtures that still contain BattleTags or account ids.
- **Never silence a failing self-check or health check** to make an error go away; find out which
  side is wrong.
- **Coaching numbers must say where they come from**: your own games (small samples), public
  statistics at your MMR (correlation, not cause), or the simulator (rounds 1–10 only). Don't
  present a statistic as a rule, and don't suggest cards that don't fit the build.
- **No personal data in the repository**: no logs except anonymised fixtures, no files from
  `data/`, no screenshots showing BattleTags. README screenshots are taken from the fixture game.
- Standard library first. The only runtime dependency is Pillow (card thumbnails).
- Keep it working on Windows and macOS: all locations go through `paths.py`.

## Pull requests

Small and focused is best. CI runs ruff and the tests on Windows, macOS and Linux. Add a line to
`CHANGELOG.md` under "Unreleased" for anything a user would notice.
