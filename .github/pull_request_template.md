## What and why

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `uv run ruff check src tests` and `uv run pytest -q` pass
- [ ] Parser change: a regression test (anonymise the log with `bgcoach anonymise`), and `bgcoach check` still agrees with HDT
- [ ] Coaching change: every number shown says where it comes from (your games, public stats, simulator)
- [ ] No personal data added (logs, BattleTags, screenshots with names, files from `data/`)
