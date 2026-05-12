# NGA Wolf Watcher

English | [中文说明](README.zh-CN.md)

Watch a specified NGA user's replies, push new replies to Feishu, and use Feishu cards to fetch history or pack results into `.txt` files.

## Features

- Continuous monitoring: after you click `启动监听` / `Start Watcher`, the app keeps checking the configured `Default User ID` for new NGA replies and pushes newly found replies to the target Feishu group.
- Manual Feishu actions: in the Feishu group, you can use commands or card buttons to fetch recent user replies, fetch thread replies, or pack results into `.txt` files.
- Do-not-disturb hours: automatic monitoring can be muted for a continuous weekly range, such as Friday 18:00 to Monday 08:00. Muted replies can either be ignored or summarized after the quiet period ends.

## Feedback

If you run into bugs or usage problems, please open an [Issue](https://github.com/huangbwww/nga-wolf-watcher/issues).

Feature ideas are also welcome. They can be related to NGA, stock-related workflows, or other adjacent personal tools. I check issues periodically and update when I have time.

## Use The EXE

This path does not require editing code or running Python commands.

1. Download `NGA-Wolf-Watcher.exe` from [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest).
2. Open [Feishu Open Platform](https://open.feishu.cn/page/openclaw), create a bot app, and copy the app's `App ID` and `App Secret`.
3. Add the bot to the target Feishu group.
4. If you want to use `/start` and other commands without mentioning the bot, grant `im:message.group_msg`.
5. Open `NGA-Wolf-Watcher.exe`, fill `Feishu App ID` and `Feishu App Secret`, then click `查询群组` / `List chats`.
6. Copy the target group's `chat_id` into `Receive ID`.
7. Log in to `https://bbs.nga.cn/`, copy the browser request `Cookie`, and paste it into `NGA Cookie`.
8. Click `保存配置`, then click `启动监听`.

Keep the first-start mark-seen option enabled before the first launch. It marks currently fetched NGA replies as already seen, so old replies are not pushed to Feishu in bulk.

The GUI saves local secrets under `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`. Runtime state is stored next to it as `.nga_seen.json` by default. Do not share these files.

### Do-Not-Disturb Hours

In `运行设置` / `Settings`, enable `免打扰时段` if you do not want automatic monitoring pushes during a weekly time range. Set a start weekday/time and an end weekday/time, for example `周五 18:00 -> 周一 08:00`. The time uses hour/minute dropdowns to avoid manual `HH:MM` input. Manual Feishu commands, packing, chat lookup, and test messages are not affected.

Do-not-disturb handling has two modes:

- `忽略新回复`: new replies found during the muted period are marked as seen and will not be sent later.
- `暂存并在免打扰结束后汇总推送`: new replies found during the muted period are stored and sent as one summary card after the muted period ends.

### How To Copy NGA Cookie

You can also refer to [Issue #1](https://github.com/huangbwww/nga-wolf-watcher/issues/1) for a concrete example.

1. Open `https://bbs.nga.cn/` in your browser and log in to the NGA account that can view the target content.
2. Open the NGA page you want to watch, or any NGA page under `bbs.nga.cn` after logging in.
3. Press `F12` to open Developer Tools, then switch to the `Network` tab.
4. Refresh the page with Developer Tools open.
5. Click a request sent to `bbs.nga.cn`, for example `thread.php`, `read.php`, or another request with status `200`.
6. In `Headers` / `Request Headers`, find `Cookie`.
7. Copy the full `Cookie` value, paste it into the GUI's `NGA Cookie` field, then click `保存配置`.

The cookie is equivalent to a temporary login credential. Do not post it in issues, chats, screenshots, logs, or release files. If NGA fetching returns empty data or JSON parsing errors, copy the cookie again from a logged-in `bbs.nga.cn` request.

## Commands

In the target Feishu group, mention the bot or use the card:

```text
/start
/history_r 150058 5
/pack_r 150058 5
/history_t 45974302 10
/pack_t 45974302 10
```

Defaults:

- `150058` = wolf uid
- `45974302` = wolf thread id
- When `<count>` is omitted, user-reply commands default to `5`, and thread-reply commands default to `10`.

Command meanings:

- `/history_r <uid|0> <count>` fetch recent replies by uid and send cards.
- `/pack_r <uid|0> <count>` fetch recent replies by uid and send a `.txt` file.
- `/history_t <tid> <count>` fetch latest posts from a thread and send cards.
- `/pack_t <tid> <count>` fetch latest posts from a thread and send a `.txt` file.

`/pack_r 45974302 10` is accepted as a compatibility alias for packing the default wolf thread.

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

The script stores pushed reply ids, handled command ids, and deferred quiet-hour replies in `.nga_seen.json`. In the EXE GUI, the default file lives under `%LOCALAPPDATA%\NGA Wolf Watcher\`, next to `config.json`. It is separate from config because it is runtime state and is written frequently; deleting it resets the watcher’s seen/handled history.

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
