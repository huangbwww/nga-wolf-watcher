@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Missing virtual environment. Run setup-local.bat first.
  pause
  exit /b 1
)

start "NGA Wolf Watcher" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0nga_wolf_webgui.py"
endlocal
