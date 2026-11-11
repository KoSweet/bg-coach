#!/bin/bash
# bg-coach setup for macOS. Double-click this file once (or run: bash mac/setup.command).
# It installs what's needed, turns on Hearthstone's logging and creates "bg-coach.app".
set -e
cd "$(dirname "$0")/.."
REPO="$(pwd)"
echo "== bg-coach setup in $REPO"

# 1) uv (Python manager from Astral) — installs Python for this project only
if ! command -v uv >/dev/null 2>&1; then
  if [ -x "$HOME/.local/bin/uv" ]; then
    export PATH="$HOME/.local/bin:$PATH"
  else
    echo "== installing uv (https://docs.astral.sh/uv/)"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi
fi

# 2) Python + dependencies
uv sync

# 3) Hearthstone logging + paths check
./.venv/bin/python -m bgcoach.cli setup

# 4) optional combat simulator (needs Node.js: https://nodejs.org)
if command -v npm >/dev/null 2>&1; then
  echo "== installing the combat simulator (optional)"
  (cd sim && npm install --ignore-scripts --no-audit --no-fund) || echo "   (skipped: npm failed)"
else
  echo "== Node.js not found: combat-simulator what-ifs will be off (everything else works)"
fi

# 5) the clickable app (no Terminal window when you start it)
APP="$REPO/bg-coach.app"
rm -rf "$APP"
osacompile -o "$APP" -e "do shell script \"cd \" & quoted form of \"$REPO\" & \" && mkdir -p data && nohup ./.venv/bin/python -m bgcoach.cli ui >> data/app.log 2>&1 &\""
cp "$REPO/src/bgcoach/static/icon.icns" "$APP/Contents/Resources/applet.icns" 2>/dev/null || true
touch "$APP"

echo
echo "== done. Start bg-coach by double-clicking: $APP"
echo "   (drag it to your Dock if you like). If Hearthstone was running, restart it once so logging is on."
open "$APP"
