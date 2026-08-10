@echo off
setlocal
cd /d "%~dp0" || exit /b 1

if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv || exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade pip || exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt pytest || exit /b 1

pushd webui || exit /b 1
call npm.cmd ci || goto :web_failed
call npm.cmd run build || goto :web_failed
popd

echo Setup complete.
exit /b 0

:web_failed
set "setup_exit_code=%errorlevel%"
popd
if "%setup_exit_code%"=="0" set "setup_exit_code=1"
exit /b %setup_exit_code%
