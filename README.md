# bg-coach

A personal coach for **Hearthstone Battlegrounds**. It records every decision you make from the
game's own log, checks itself against the game, and shows you concrete moments to learn from:
buys and picks compared with what else you could have taken (respecting your build), fights where
your board was behind, better minion orders (simulated), hero picks — with live advice while you play.

Everything runs on your computer. Nothing about your games is uploaded. It only downloads public
card data/art (HearthstoneJSON) and public Battlegrounds statistics (Firestone).

## Install

### macOS
1. Unzip the folder somewhere permanent (e.g. `~/bg-coach`).
2. Double-click **`mac/setup.command`** (if macOS blocks it: right-click → Open, or in Terminal
   `bash mac/setup.command`). It installs what's needed (uv + Python, ~1 minute), turns on
   Hearthstone's logging, and creates **`bg-coach.app`**.
3. **Restart Hearthstone once** so logging is on.
4. From then on, start **bg-coach.app** (drag it to your Dock). No Terminal window.

Optional: install [Node.js](https://nodejs.org) *before* setup to enable the combat simulator
(minion-order and "what if" fight checks). Everything else works without it.

### Windows
1. Install [uv](https://docs.astral.sh/uv/) (one line in PowerShell:
   `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`).
2. Unzip the folder somewhere permanent and double-click **`bg-coach.vbs`**. The first start
   installs everything and creates a **bg-coach** shortcut on your Desktop and Start menu.
3. Restart Hearthstone once. From then on use the shortcut (no console window).

## Use
- Start bg-coach, then play. A small round icon sits on top of the game (ring colour = status,
  number = round). Click it for the live feed and pick advice; `–` shrinks it; `✕` → menu (quit).
- Run Hearthstone in **windowed / "fullscreen windowed"** mode so the overlay can show on top.
- Something looks wrong mid-game? Press **Print Screen** in Hearthstone. The screenshot is attached
  to that round; report it after the game from the game's page (📷 → ⚑ Report this).
- **Improve** tab: moments to learn from across games + your stats compared with your good/bad games.
- **Games** tab: every game; open one for its round-by-round timeline and coach section.
- **Health** tab: errors and data checks, each with **Copy report** (paste it to whoever maintains it).
- **Quit** button (top right) stops recording.

## Limits
- Bob's Buddy odds and HDT game history are read from Hearthstone Deck Tracker (Windows only).
  On a Mac those parts are simply empty.
- Card/hero numbers are statistics from players at your MMR (correlations, not rules).
  The simulator is used only for rounds 1–10, where it matches Bob's Buddy well.
- The combat simulator is Firestone's (npm `@firestone-hs/simulate-bgs-battle`, licence "All rights
  reserved"): installed locally for personal use, not redistributed in this folder.

## Troubleshooting
- Log file: `data/app.log`. Windows: `bg-coach-debug.bat` runs with a visible console.
- No games appearing? Check `uv run bgcoach setup` (shows where it looks for Hearthstone; set
  `BGCOACH_HS_DIR` if Hearthstone is installed somewhere unusual), then restart Hearthstone.
- Test without playing: `bg-coach-test.bat` / `uv run bgcoach ui --test` replays an old game.

## Commands
`uv run bgcoach <command>`: `ui`, `setup`, `import`, `check` (vs HDT), `facts` (for `/review-session`
in Claude Code), `whatif`, `sim-check`, `version`, `share`.
