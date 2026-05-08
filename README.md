# NGA Wolf Watcher

English | [中文说明](README.zh-CN.md)

Watch NGA replies, push new replies to Feishu, and use Feishu cards to fetch history or pack results into `.txt` files.

## Use The EXE

This path does not require editing code or running Python commands.

1. Download `NGA-Wolf-Watcher.exe` from [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest).
2. Open [Feishu Open Platform](https://open.feishu.cn/page/openclaw), create a bot app, and copy the app's `App ID` and `App Secret`.
3. Add the bot to the target Feishu group.
4. If you want to use `/start` and other commands without mentioning the bot, grant `im:message.group_msg`.
5. Open `NGA-Wolf-Watcher.exe`, fill `Feishu App ID` and `Feishu App Secret`, then click `查询群组` / `List chats`.
6. Copy the target group's `chat_id` into `Receive ID`.
7. Log in to `https://bbs.nga.cn/`, open the watched page, copy the browser request `Cookie`, and paste it into `NGA Cookie`.
8. Click `保存配置`, then click `启动监听`.

Keep the first-start mark-seen option enabled before the first launch. It marks currently fetched NGA replies as already seen, so old replies are not pushed to Feishu in bulk.

The GUI saves local secrets under `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`. Do not share that file.

## Commands

In the target Feishu group, mention the bot or use the card:

```text
/start
/history_r 150058 10
/pack_r 150058 10
/history_t 45974302 100
/pack_t 45974302 100
```

Defaults:

- `150058` = wolf uid
- `45974302` = wolf thread id

Command meanings:

- `/history_r <uid|0> <count>` fetch recent replies by uid and send cards.
- `/pack_r <uid|0> <count>` fetch recent replies by uid and send a `.txt` file.
- `/history_t <tid> <count>` fetch latest posts from a thread and send cards.
- `/pack_t <tid> <count>` fetch latest posts from a thread and send a `.txt` file.

`/pack_r 45974302 100` is accepted as a compatibility alias for packing the default wolf thread.

## Advanced Usage

If you only want to use the EXE, you can stop reading here.

### Run With BAT

This mode requires a local Python environment.

Copy `start_local.example.bat` to `start_local.bat`, fill the empty `NGA_COOKIE` and Feishu values, then run it.

The BAT installs `lark-oapi` automatically. On the first run, if `.nga_seen.json` does not exist, it runs `--mark-seen` before starting the watcher to avoid pushing old replies.

### Run From Source

Install dependencies:

```powershell
cd D:\nga-wolf
python -m pip install lark-oapi customtkinter
```

Set required environment variables:

```powershell
$env:NGA_COOKIE = 'ngaPassportUid=...; ngaPassportCid=...; ...'
$env:FEISHU_APP_ID = 'cli_xxx'
$env:FEISHU_APP_SECRET = 'xxx'
$env:FEISHU_RECEIVE_ID = 'oc_xxx'
$env:FEISHU_ID_TYPE = 'chat_id'
```

Optional defaults:

```powershell
$env:NGA_DEFAULT_AUTHOR_ID = '150058'
$env:NGA_DEFAULT_TID = '45974302'
$env:NGA_INTERVAL = '60'
$env:NGA_JITTER = '20'
$env:NGA_RETRIES = '10'
```

Initialize state if you do not want old replies pushed on first run:

```powershell
python .\nga_feishu_watch.py --mark-seen
```

Run with WebSocket card callbacks and periodic NGA watch:

```powershell
python .\nga_feishu_watch.py --ws
```

Run the local GUI manager from source:

```powershell
python .\nga_wolf_gui.py
```

Only test message/card callbacks, without periodic NGA watch:

```powershell
python .\nga_feishu_watch.py --ws --ws-no-watch
```

List chats visible to the Feishu bot:

```powershell
python .\nga_feishu_watch.py --list-feishu-chats
```

Send one Feishu test message:

```powershell
python .\nga_feishu_watch.py --send-test
```

### Useful Checks

Test NGA parsing:

```powershell
python .\nga_feishu_watch.py --once --dry-run
```

Run one polling cycle:

```powershell
python .\nga_feishu_watch.py --once
```

Tune polling and retries:

```powershell
python .\nga_feishu_watch.py --interval 60 --jitter 20 --retries 10 --retry-delay 2
```

Disable command polling in non-WebSocket mode:

```powershell
python .\nga_feishu_watch.py --disable-commands
```

The script stores pushed reply ids and handled command ids in `.nga_seen.json`.

### Build The EXE

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name NGA-Wolf-Watcher --icon .\assets\app_icon.ico --add-data ".\assets\app_icon.ico;assets" --add-data ".\assets\app_icon.png;assets" --collect-all lark_oapi --collect-all customtkinter .\nga_wolf_gui.py
```

The output is `dist\NGA-Wolf-Watcher.exe`.

## Legacy Custom Bot Webhook

Webhook mode is still supported:

```powershell
$env:FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/...'
$env:FEISHU_SECRET = 'optional signing secret'
python .\nga_feishu_watch.py
```

## Disclaimer

This project is provided only for personal technical research and learning. Use it at your own risk.

You are responsible for complying with NGA, Feishu, your organization, and local laws or platform rules. Automated access, message forwarding, cookie use, frequent polling, or bot interaction may cause account restrictions, account bans, data leakage, service interruption, or other uncertain consequences. The project author does not provide any guarantee and is not responsible for losses, disputes, account penalties, legal consequences, or third-party claims caused by using, modifying, distributing, or deploying this project.
