# Changelog

All notable changes. Versions follow [semantic versioning](https://semver.org/).

## [Unreleased]

The point first, details on demand.

### Changed
- **The one thing:** every game is reduced to its most important lesson plus a habit for the next
  game, ranked by kind (a concrete line you could have played, then minion order, a risky level-up,
  the hero pick, a playbook habit, and lost fights last) and by size within the kind
  (`lessons.py`). The game page, the after-game card, the overlay and Improve all use it.
- **Game page:** a one-line header, the one thing with "also" lines, the game's story (click a bar
  to open that round), then every round in one line with its lessons underneath; the shop, board
  and fight open on click. The lobby, card numbers, final board and screenshots are drawers at the
  bottom. A 14-round game fits in about 1,500 px instead of 6,000+.
- **Between games:** the after-game card sits at the top of the Live tab and shows only the lesson,
  the habit and two "also" lines; it updates once the simulator has checked the game's fights. The
  overlay shows the same lesson until the next game starts.
- **Improve:** starts with your focus (the costliest habit you can practise, never a lost fight),
  whether it's getting better game by game, and its biggest example; then other habits, decisions
  and, in a drawer, your stats.
- Impact is stated one way: what it cost, in its own unit (pts of win chance, places, HP), no +/-
  signs; "habit" for playbook rules.

### Coaching judged like a pro: by HP at stake, not one fight's odds
- **Turning point** replaces generic lost-fight lessons: the fight that took you below 15 HP, your
  board strength on the turns before, and what you spent them on, with the matching habit:
  levelled while already behind → stabilize first; spent but still fell behind → go for big
  upgrades; or a highroller with a fine board → little to fix. Close fights with a good board aren't
  lessons. Top-2 games without a turning point open with "Good game" and the small things.
- **Counter lines** only when they save real HP (expected HP saved = damage × how much less likely the
  loss; 5+ HP, or 3+ when the fight took you below 15). "Skip the level-up" only when levelling cost
  you the 15-HP line (Jeef's rule): no more "skip your turn-2 level to save 2 HP". Shown as HP saved.
- **Minion order** only against a board you had already seen (positioning with information), and only
  when it saves real HP; otherwise it was hindsight.
- Lost fights get their own line only against a real highroller (2× the average for their hero).
- **Scam and other keyword boards are judged by their fights, not their stat total.** A venomous /
  divine-shield board at 30% of the stat average that keeps winning is not "behind"; when it does
  lose, the lesson says so from its fight record. A turning point needs two lost fights in its
  window (one loss is not a pattern), and a 1st place always opens with "You won".
- **Transition turns:** selling your stat holders on the turn you cross below 15 HP (for triples, a
  buy-play-sell engine, a new build) is its own turning point, with what they had fought with the
  round before and whether it paid off afterwards.
- **Keep lines (simulated):** "keep the minion you sold instead of selling it", back on the board with
  the stats it was sold at, only when that fight cost you the 15-HP line.
- **Every round is simulated**, not just 1–10/12: from round 11 a fight's what-ifs are used only when
  Bob's Buddy agrees with the simulator on that fight (late fights are where most games are decided).
- A short roll and unspent gold on the same turn are one lesson, not two that disagree.

### Added
- **Reasons from this game** (`situation.py`): a lesson about levelling now says why it mattered
  in *this* game, from what was on screen that turn: your board against your hero's average ("far
  too weak"), how many players had more health than you, whether anyone else was on the next tier
  yet, and what the next tier holds for your tribe in the pool ("tier 6 adds only Snazzy Phantom for
  your Undeads: your build didn't need it yet"). What spoke for the level is said too ("For it: 2
  players were already on tier 5"), and a fair level that just lost a fight (board ahead, the lobby
  already there) isn't flagged at all. Turning points blamed on a level get the same reasons, and
  every lesson shows where you stood that turn (📍).
- **Unspent gold** names what the shop still had that you could afford; **Dark Gifts** names the
  turns you ended with 3+ gold.
- **Live best order:** against your next opponent's last board (if you met them in the last 3
  rounds), the coach tries every single move of one minion plus the reversed board and says "Move X
  first: 42% → 61% win" when a new order is confirmed 8+ points better. Growing older boards to their
  hero's average was tested on 14 real rematches and rejected: it called every one a sure win, and 6
  were losses.
- **Next opponent's last fights:** what each of their last two fights cost them, and "no loss in N
  rounds" (from the leaderboard's health; the log doesn't record who they fought). Their *current*
  tribe and win streak from the in-game hover aren't in any log the game writes.
- **Next opponent:** the live panel and the overlay show the minions you saw when you last met that
  player, and their tribes the way the in-game hover sums them up ("6 Beast"), worked out from those
  minions (the log has no tribe tag).

### Fixed
- The freeze button toggles: a second press unfreezes. "Froze the shop, bought none" counted
  toggled-off freezes (13 false alarms in 11 games, 2 real); the timeline now shows UNFREEZE.
- Counter lines that turn a sure loss into a tie read "0% to 0% win"; they now show win and loss.
- **Locked heroes:** without the Tavern Pass the game shows four heroes but only the middle two can
  be picked. The log marks the other two (`BACON_LOCKED_MULLIGAN_HERO`); they're now recorded
  (`hero_locked`), shown with a 🔒, and never the advice, live or after the game. Before, the hero
  verdict named a hero you couldn't pick in 31 of 61 games.
- **Rally minions lead on purpose:** "Weak minion leading early" no longer fires when the leader has
  Rally (or another attack trigger): it has to attack to work.
- **Duos fights you won** were recorded as ties when the hit landed on the enemy's teammate (15 of
  77 Duos fights). Wins are now read from the enemy team's health on the leaderboard as well. Solo
  results are unchanged (713 fights re-checked). Logs are parsed again once (parser version 3).
- **Duos:** no hero verdict after the game (the hero numbers are solo numbers: top 4 of 8 players);
  the live hero pick says "solo numbers".

## [0.3.0] - 2026-11-12

Coaching that reads the lobby, like a coach watching over your shoulder.

### Added
- **Counter lines (simulated):** for a fight you lost, the coach tries what you could actually have
  done that turn with minions still in your shop when the turn ended: buy one *instead of* a minion
  you bought, *skip the level-up* and buy one, or use spare gold (selling your weakest minion if 1–2
  gold short). It shows a line when it clearly changes the fight (e.g. "skip the 5-gold level-up, buy
  Tarecgosa: 0% → 42% win"), marked **risky** when it costs a tier or total stats. If nothing in the
  shop wins the fight, it says so: the fight was decided earlier.
- **Highrollers:** every opponent board you fought is compared with the average for their hero on that
  round; boards at 1.5× or more are flagged. Fights show their board, keywords, and whether you had
  seen that player before. A **Lobby** panel lists every opponent's fights, final place, tier and triples.
- **Next opponent, live:** during the shop phase the overlay and Live tab show who you fight next
  (tier, health, triples), the last board you saw from them vs their hero's average, and, with the
  simulator installed, your current board's odds against it, updated as you change your board.
- **Pro playbook:** principles from top players' guides (JeefHS's leveling guide and tips, a high-MMR
  written guide, Blizzard's Dark Gift rules), checked against every game: early rolls, tier 2 on
  turn 2, tier 3 by turn 5, levelling below the 15-HP damage cap, triple reward before levelling,
  unused freezes, unused Dark Gifts, and positioning (weak minion leading early, a taunt in reach of
  a cleave, your biggest minion into venom), and gold left unspent. The hero pick explanation also
  compares starting health. Each moment links its source. See `docs/PLAYBOOK.md`.
- **Hero pick, explained:** the start-of-game moment says why the other hero was better: top-4 rate,
  early vs late fight win rate, how this lobby's tribes suit each hero, and the hero power.
- Parser records the leaderboard every round, the shop left at the end of each turn, and the next
  opponent. Saved games are re-parsed once automatically after an update (parser version).

### Changed
- Card averages are no longer "moments to review": they can't see your situation (an economy card
  while losing, a plan). They're listed under **Card numbers** as context, with a note when the card
  you took has a situational payoff (e.g. Tortollan Blue Shell sells for 5 after a lost fight).
- "What to work on" ranks counter lines, highroller/weak-board fights, minion order, risky level-ups
  and clear hero picks.

### Fixed
- A fight could show the simulator's odds even when the simulator failed to reproduce that fight
  (e.g. "Bob's Buddy 100% loss" next to "simulated 47% win"). Unreproduced fights now say so instead.

### Docs
- README: fair-play section (log reading only, no automation or game-file changes) and asset notice;
  `NOTICE` file; credit line in the app. Card art stays © Blizzard and isn't in the repository.

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

[0.3.0]: https://github.com/KoSweet/bg-coach/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/KoSweet/bg-coach/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/KoSweet/bg-coach/releases/tag/v0.1.0
