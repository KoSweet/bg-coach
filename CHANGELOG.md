# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org/).

## [0.2.0] - 2026-11-12

### Improved suggestions
- One rule set for every suggestion (buys, picks, hero, live advice; `advice.py`): an alternative
  must fit your build at least as well, be better by more than chance (from how many games each
  number rests on), and, at 15 HP or less, add at least as much to your board right now.
  On the author's 56 games this removed 37 of 59 pick suggestions that were within chance and 5 of
  34 buy suggestions made at 1–7 HP (e.g. Patient Scout or a tavern spell instead of a minion).
- Live pick advice says when two options are **too close to call**, and at low HP which option adds
  the most to your board now.
- Each suggestion's details show the games behind each number and how much chance could explain.

### Added
- `bgcoach anonymise`: makes a `Power.log` safe to attach to a bug report (keeps only the lines
  the parser reads; replaces BattleTags, player names and account ids).
- Problem reports (**Copy report**, ⚑ Report this) remove BattleTags, player names and your folder
  names, so they can be posted publicly.
- Tests that run anywhere: an anonymised real game (`tests/fixtures`) covers the parser, import,
  terminal timeline, web API and coaching; 57 tests in total.
- CI on Windows, macOS and Linux (ruff + pytest), issue templates, contributing guide, MIT licence,
  `docs/ARCHITECTURE.md`, screenshots in the README.
- `bgcoach --version`; `bgcoach check --limit N`; `BGCOACH_HDT_DIR` override.

### Fixed
- When a game exists in several archived copies (a log archived mid-game before Hearthstone emptied
  it, plus the live copy), `bgcoach check` could compare the partial copy, and the saved game depended
  on import order. The fullest copy now always wins.
- Golden synergy never rose with triples you had made (the triple count was always 0), so cards
  that reward goldens were rated as a side synergy at best.
- An overlay left over from an app that crashed or was closed attached itself to the next app
  (two overlays on screen). Overlays now close when the app that opened them is gone.

### Changed
- The command line is a thin layer over the shared modules (no duplicated parser/live code).
- Lint clean under ruff (pyflakes, pycodestyle, isort, pyupgrade, bugbear, simplify).

## [0.1.0] - 2026-11-12

First public release.

- Parser for Battlegrounds `Power.log`: every buy, sell, play, cast, refresh, freeze, level and
  pick, shops, fights and placement, with self-checks against the game; 100% agreement with HDT
  on hero, placement and final board.
- App (Live, Improve, Games, Health) and an always-on-top overlay with live pick advice.
- Decision-level coaching with synergy-aware alternatives, Bob's Buddy odds, and an optional
  combat simulator for minion order and buy what-ifs (rounds 1–10).
- Windows (no console window, Desktop shortcut) and macOS (`bg-coach.app`) launchers.

[0.2.0]: https://github.com/KoSweet/bg-coach/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/KoSweet/bg-coach/releases/tag/v0.1.0
