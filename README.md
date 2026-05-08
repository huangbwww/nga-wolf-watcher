# NGA reply watcher -> Feishu

Watch NGA replies, push new messages to Feishu, and use Feishu cards to fetch history or pack results into `.txt` files.

## Getting Started

### 1. Install dependencies

```powershell
cd D:\nga-wolf
python -m pip install lark-oapi
```

### 2. Create a Feishu bot app

Fastest path: open [Feishu OpenClaw](https://open.feishu.cn/page/openclaw) and create an intelligent agent app.

Then in the Feishu developer console:

1. Enable the bot capability.
2. Install/publish the app to your tenant.
3. Add the app bot to the target group.
4. For WebSocket interactive cards, enable event subscription by long connection.
5. Subscribe to `im.message.receive_v1` and `card.action.trigger`.
6. Make sure message/file permissions are enabled if Feishu asks for them, then re-publish/re-install.

Copy the app credentials:

```powershell
$env:FEISHU_APP_ID = 'cli_xxx'
$env:FEISHU_APP_SECRET = 'xxx'
```

### 3. Get the target Feishu group id

After the bot is in the target group:

```powershell
python .\nga_feishu_watch.py --list-feishu-chats
```

The first column that starts with `oc_` is the group `chat_id`:

```powershell
$env:FEISHU_RECEIVE_ID = 'oc_xxx'
```

`FEISHU_ID_TYPE` defaults to `chat_id`, so this is optional:

```powershell
$env:FEISHU_ID_TYPE = 'chat_id'
```

Test Feishu sending:

```powershell
python .\nga_feishu_watch.py --send-test
```

### 4. Get the NGA Cookie

1. Log in to `https://bbs.nga.cn/` in a browser.
2. Open the target page, for example `https://bbs.nga.cn/thread.php?searchpost=1&authorid=150058`.
3. Press `F12` -> `Network`.
4. Refresh the page.
5. Click the `thread.php?...` or `read.php?...` request.
6. In `Request Headers`, copy the full `Cookie` header value.

Set it:

```powershell
$env:NGA_COOKIE = 'ngaPassportUid=...; ngaPassportCid=...; ...'
```

NGA cookies expire. If the script reports login errors, copy a fresh cookie.

### 5. Optional defaults

```powershell
$env:NGA_DEFAULT_AUTHOR_ID = '150058'
$env:NGA_DEFAULT_TID = '45974302'
$env:NGA_INTERVAL = '60'
$env:NGA_JITTER = '20'
$env:NGA_RETRIES = '10'
```

### 6. Run

Initialize state if you do not want old replies pushed on first run:

```powershell
python .\nga_feishu_watch.py --mark-seen
```

Run with WebSocket card callbacks and periodic NGA watch:

```powershell
python .\nga_feishu_watch.py --ws
```

Only test card/message callbacks, without periodic watch:

```powershell
python .\nga_feishu_watch.py --ws --ws-no-watch
```

## Local Config File

For a second machine or another account, create a local `.env.ps1`:

```powershell
$env:NGA_COOKIE = '...'
$env:FEISHU_APP_ID = 'cli_xxx'
$env:FEISHU_APP_SECRET = 'xxx'
$env:FEISHU_RECEIVE_ID = 'oc_xxx'
$env:NGA_DEFAULT_AUTHOR_ID = '150058'
$env:NGA_DEFAULT_TID = '45974302'
```

Load and run:

```powershell
. .\.env.ps1
python .\nga_feishu_watch.py --ws
```

Do not commit `.env.ps1`; it contains secrets.

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

## Useful Checks

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

## Legacy Custom Bot Webhook

Webhook mode is still supported:

```powershell
$env:FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/...'
$env:FEISHU_SECRET = 'optional signing secret'
python .\nga_feishu_watch.py
```
