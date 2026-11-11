# bg-coach — plan

**Goal:** improve *my own* Battlegrounds play (placement / MMR ~6.6k). Not an AI that plays.
Successor to `OneDrive\Documents\heartstone-coach` (archived reference: its sim/RL/AlphaZero
plateaued at teacher parity; its parser had P0 data bugs — see that repo's `BUGS.md`,
`ANALYSIS_why_cant_improve_2026-06-06.md`). Salvage ideas, not code.

## The loop (what "getting better" means here)
1. **Measure** every game → per-decision facts.
2. **Rank leaks** across *all* games by estimated placement cost.
3. **Focus** on one habit next session.
4. **Verify** the next report shows the habit + placement moving. Then next leak.

## Architecture
```
archive  → copies HS Logs (rotates! only ~6 sessions kept) + HDT files → data/raw   [DONE]
parse    → Power.log → entity replay + exact decisions (Options → SendOption, Choices → ChosenEntities)
store    → DuckDB data/bgcoach.duckdb: games, turns, decisions, shops, boards, combats, opponents
knowledge→ card DB (HearthstoneJSON per build + Blizzard BG API) + Firestone meta snapshots per patch
analyze  → metrics + comparison vs my MMR bracket + combat counterfactuals
report   → HTML per game/session; facts JSON → Claude Code `/review-session` writes coaching (no API key)
live     → optional overlay, last
```

## Ground-truth sources (verified 2026-11-10)
- Power.log (Verbose): `GameState.DebugPrintOptions` lists every legal option; `GameState.SendOption
  selectedOption=N selectedTarget=E selectedPosition=P` = what I chose. Option mainEntity cardIds identify
  the action: `TB_BaconShop_DragBuy` (buy, target=shop minion), `TB_BaconShop_DragSell`, `TB_BaconShop_8p_Reroll_Button`,
  `TB_BaconShopLockAll_Button` (freeze), tavern-up button, `BG36_Button_DarkGift`, hero power, minion = play/activate.
  Use these, NOT zone-change heuristics (old repo's P0 bug).
- `DebugPrintGame` gives BuildNumber + GameType (filter GT_BATTLEGROUNDS; exclude duos).
- Each line is emitted twice (GameState + PowerTaskList). Pick one stream for state; GameState for options.
- Bob is a separate player (shop minions owned by Bob's controller) — never treat as an opponent.
- HDT `BgsLastGames.xml`: hero, placement, Rating/RatingAfter, final board per game → parser validation oracle.
- HDT `hdt_log*.txt`: Bob's Buddy full combat input + `WinRate=..% TieRate LossRate` per combat → combat oracle.
- hslog 1.20 parses packets fast but crashes on BG player-id swap (`InconsistentPlayerIdError`) — reference only.
- Meta (Firestone static, public): `static.zerotoheroes.com/api/bgs/hero-stats/mmr-{100,50,25,10,1}/last-patch/overview-from-hourly.gz.json`
  (avg position, placement distribution, by MMR percentile), `.../card-stats/mmr-100/last-patch/...` (per-card turnStats).
  comp-stats is stale (2025) — skip. Snapshot daily; tag by patch.
- Cards: `api.hearthstonejson.com/v1/<build>/enUS/cards.json`; BG pool `hearthstone.blizzard.com/en-us/api/cards?bgCardType=...`
  (tier at `card.battlegrounds.tier`).
- Combat sim: `@firestone-hs/simulate-bgs-battle` (npm, updated weekly, license "All rights reserved" → personal local use only, never redistribute).

## Parser facts learned the hard way (verified on real logs 2026-11-10)
- Round = (GameEntity TURN + 1) // 2; odd TURN = recruit, even = combat.
- "Me" = CREATE_GAME player with GameAccountId lo != 0; record `account` — archived logs include
  games from OTHER accounts (old repo's `real_players_logs` June set, a spectated game). Filter by account.
- Gold = player RESOURCES + TEMP_RESOURCES - RESOURCES_USED.
- Combat result: my hero's BACON_WON_LAST_COMBAT flag + effective HP (health + ARMOR) change.
  Damage dealt = max PREDAMAGE on the opponent's combat hero (its HEALTH/ARMOR reset after combat).
- Placement = last PLAYER_LEADERBOARD_PLACE on my hero OR the hero copy created at my death
  (CARDTYPE HERO, my controller, my hero card) — BEFORE GameEntity STATE=COMPLETE. Values after
  COMPLETE are a cosmetic re-sort (wrong). PLAYSTATE LOST can fire before the final value.
- Buying can be drag (TB_BaconShop_DragBuy target) OR clicking the shop card itself (option entity = shop card).
- **Hearthstone can EMPTY Power.log when it exits** (2026-11-10 21:08: 430 MB → 0 bytes, no Power_old.log).
  The archiver must never shrink an archived file, and the live watcher keeps its own copy
  (`Power.log.live-*.gz`). Lost because of this: raw log of 11-10 15:47–20:51 (games already parsed).
- Clicking a shop card is NOT a buy (0/147 in archive); buys are only DragBuy/DragBuy_Spell options.
- HDT StartTime = when HDT noticed the game (late if HDT opened mid-game) → match by hero within 20 min.

## Commands
- `uv run bgcoach version` — client build, patch, live BG pool
- `uv run bgcoach log [FILE|latest]` — full timeline of every decision; saves `data/games/*.json`
- `uv run bgcoach log --live` — follow the running game
- `uv run bgcoach check` — parse whole archive, verify against HDT (currently 20/20 hero, placement, board)

## Phases (exit criteria)
| # | Deliverable | Done when |
|---|---|---|
| 0 | repo + archiver | logs survive sessions ✅ (scheduled task: run by user) |
| 1a | parser + version + live | ✅ 20/20 HDT agreement (hero, placement, board); 0 unclassified actions |
| 1c | app: live tab, overlay icon + feed, self-checks, screenshots-as-flags, reports | ✅ 2026-11-10 |
| 1b | Bob's Buddy odds join (HDT log) | ✅ 1,945 results; clear favourite matched the result in 270/275 fights; bad luck vs weak board split |
| 2 | knowledge + meta snapshots | ✅ card DB per build; Firestone hero/card stats per MMR bracket, daily snapshots |
| 3 | coaching | ✅ decision-first: buys vs exact affordable shop, picks, hero, costly fights (with BB odds), risky levels; stats table as context; focus trend |
| 4 | combat sim + counterfactuals | ✅ Firestone simulator (sim/, personal use) validated vs Bob's Buddy: rounds 1–5 2.1 pts / 38 of 39 same favourite, rounds 6–10 9.7 pts / 39 of 44; used for rounds ≤10 only, and only for fights it reproduces (per-fight trust check). Buy what-ifs + positioning in decisions (`bgcoach whatif`, `sim-check`) |
| 5 | `/review-session` | ✅ `bgcoach facts` + `.claude/commands/review-session.md`; focus trend on Improve tab |
| 5b | live coaching | ✅ hero/Discover/triple/Dark Gift option values while choosing, live board strength, post-game summary |
| 6 | live overlay | ✅ small icon → live feed with round thumbnails, live pick advice, board strength, self-check status |

## Rules
- Test against real archived logs; HDT + Bob's Buddy are independent oracles. Green unit tests ≠ correct data.
- Never guess card facts — use the card DB for the game's build.
- Small samples lie: show n and uncertainty on every leak estimate.

## Known gaps (2026-11-12)
- Duos: parsed but self-checks/analysis assume solos.
- Archiving only runs while the app is open (scheduled task needs the user to run the schtasks command).
  Hearthstone can empty Power.log on exit; the app's live copy is what makes games safe → keep the app open.
- Raw log of 2026-11-10 15:47–20:51 was lost (Hearthstone wiped it before the archiver fix); games are saved.
- Overlay can't draw over exclusive fullscreen (use Fullscreen Windowed), same as HDT.
- Card/hero numbers are correlations at the user's MMR, not causal. Simulated what-ifs only cover the
  fight that turn (rounds ≤10), with the alternative card at printed stats; hero powers/trinkets/hidden
  scaling aren't passed to the simulator. Rounds 11+ use Bob's Buddy odds only.
- macOS support (paths, logging setup, bg-coach.app) is written and simulated but not yet run on a real Mac.
