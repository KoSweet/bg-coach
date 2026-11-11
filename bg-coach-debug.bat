@echo off
rem DEBUG: runs bg-coach WITH a console window so you can see errors. Close the window to stop it.
cd /d "%~dp0"
if not exist ".venv\Scripts\bgcoach.exe" uv sync
".venv\Scripts\bgcoach.exe" ui
pause
