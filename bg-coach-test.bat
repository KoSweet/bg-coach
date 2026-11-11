@echo off
rem TEST MODE: replays your newest archived game into the Live tab, as if you were playing now.
rem No Hearthstone needed. Close this window to stop.
cd /d "%~dp0"
if not exist ".venv\Scripts\bgcoach.exe" uv sync
".venv\Scripts\bgcoach.exe" ui --test
if errorlevel 1 pause
