@echo off
setlocal

cd /d "%~dp0"

rem Fill these values in your local start_local.bat.
set "NGA_COOKIE="
set "FEISHU_APP_ID="
set "FEISHU_APP_SECRET="
set "FEISHU_RECEIVE_ID="
set "FEISHU_ID_TYPE=chat_id"

rem Message channel. Default is feishu. Set to wechat to ignore Feishu settings.
set "NGA_BOT_CHANNEL=feishu"
rem set "WECHAT_BOT_TOKEN="
rem set "WECHAT_BOT_BASE_URL=https://ilinkai.weixin.qq.com"
rem set "WECHAT_BOT_CDN_BASE_URL=https://novac2c.cdn.weixin.qq.com/c2c"
rem set "WECHAT_BOT_TARGET_USER_ID="
rem set "WECHAT_BOT_ALLOWED_USER_IDS="
rem set "WECHAT_BOT_POLL_TIMEOUT_MS=35000"
rem set "WECHAT_BOT_ACCOUNT_ID=default"

rem Optional defaults.
set "NGA_DEFAULT_AUTHOR_ID=150058"
set "NGA_DEFAULT_TID=45974302"
set "NGA_INTERVAL=60"
set "NGA_JITTER=20"
set "NGA_RETRIES=10"
set "NGA_PAGE_DELAY=2.0"
set "NGA_UNAVAILABLE_RETRIES=3"

rem Optional local AI Agent enhancement. Disabled by default.
rem set "AI_ENABLED=false"
rem set "AI_PROVIDER=codex"
rem set "AI_WORK_DIR=.ai_agent_workspace"
rem set "AI_AUTO_ANALYZE_NEW_POST=false"
rem set "AI_AUTO_ANALYSIS_PROMPT=根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。"
rem set "AI_CODEX_COMMAND=codex"
rem set "AI_CLAUDE_COMMAND=claude"
rem set "AI_CUSTOM_COMMAND="
rem set "AI_PERMISSION_MODE=default"
rem set "AI_SCHEDULE_ENABLED=false"
rem set "AI_SCHEDULE_INTERVAL_MINUTES=5"
rem set "AI_SCHEDULE_WINDOWS=weekday:09:30-11:30,13:00-15:00"

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
