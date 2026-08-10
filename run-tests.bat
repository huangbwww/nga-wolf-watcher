@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Missing virtual environment. Run setup-local.bat first.
  exit /b 1
)

"%~dp0.venv\Scripts\python.exe" -m pytest %*
endlocal
