@echo off
setlocal

cd /d "%~dp0"

rem Fill these values in your local start_local.bat.
set "NGA_COOKIE="
set "FEISHU_APP_ID="
set "FEISHU_APP_SECRET="
set "FEISHU_RECEIVE_ID="
set "FEISHU_ID_TYPE=chat_id"

rem Optional defaults.
set "NGA_DEFAULT_AUTHOR_ID=150058"
set "NGA_DEFAULT_TID=45974302"
set "NGA_INTERVAL=60"
set "NGA_JITTER=20"
set "NGA_RETRIES=10"

echo Installing/updating Python dependency: lark-oapi
python -m pip install lark-oapi
if errorlevel 1 (
    echo.
    echo Failed to install lark-oapi. Check Python and pip, then run this script again.
    pause
    exit /b 1
)

echo Starting NGA watcher...
if not exist ".nga_seen.json" (
    echo First run detected. Marking current fetched posts as seen before starting.
    python .\nga_feishu_watch.py --mark-seen
    if errorlevel 1 (
        echo.
        echo Failed to initialize seen state. Fix the error above, then run this script again.
        pause
        exit /b 1
    )
)

python .\nga_feishu_watch.py --ws
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
    echo.
    echo NGA watcher exited with code %EXIT_CODE%.
    pause
)
exit /b %EXIT_CODE%
