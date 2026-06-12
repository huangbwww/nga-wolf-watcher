# Configuration, Channels, And Commands

Message channels, listen rules, commands, Cookie, config files, and troubleshooting commands.

> Detailed reference. Start with the repository README for the quick path.

## Message Channels, Targets, And Listen Rules

The recommended client separates configuration into clearer sections while keeping old configs compatible:

- `Message channel profiles`: bot accounts only. A Feishu profile stores App ID / App Secret and caches the chat list inside that profile; a WeChat profile stores the ilink token, target user, and account id; a DingTalk profile stores the Stream robot credentials and proactive target users; an email profile stores SMTP settings for outbound mail; a WxPusher profile stores the SPT used by simple push.
- `Targets` / `NGA resources`: reusable user IDs and thread IDs for monitoring and manual fetches.
- `Listen rules`: choose the watch source, either an author reply page or a fixed thread filtered by author, then directly select send destinations. A Feishu destination is a Feishu profile plus one chat; a WeChat destination is a WeChat profile; a DingTalk destination is a DingTalk profile; an email destination is an email sender profile plus recipient address; a WxPusher destination is a WxPusher SPT profile. One rule can push to multiple destinations at the same time.

Manual fetches are not limited by listen rules. Feishu, WeChat, and DingTalk commands such as `/history_r`, `/pack_r`, `/history_t`, and `/pack_t` can fetch any configured user or thread. Short commands use the current entry's default user/thread when available.

AI settings remain global. Feishu, WeChat, DingTalk, email, and WxPusher targets share the same AI work directory and local agent queue. New-post auto analysis follows the triggering listen rule's send destinations. Scheduled analysis runs once per interval, then copies the result to the selected scheduled-analysis targets.

The WeChat channel uses the same kind of personal-WeChat ilink gateway as cc-connect. It is not a normal official WeChat bot and it does not automate the desktop WeChat client. On first use, the target WeChat account must send one message to the bot so the watcher can cache its `context_token`; proactive NGA pushes can only be sent after that. WeChat has no Feishu cards, so `/setting` returns a plain-text menu and copyable commands.

WeChat channel variables:

```text
NGA_BOT_CHANNEL=wechat
WECHAT_BOT_TOKEN=<ilink Bearer token>
WECHAT_BOT_BASE_URL=https://ilinkai.weixin.qq.com
WECHAT_BOT_CDN_BASE_URL=https://novac2c.cdn.weixin.qq.com/c2c
WECHAT_BOT_TARGET_USER_ID=<xxx@im.wechat>
WECHAT_BOT_ALLOWED_USER_IDS=<empty means all, or comma-separated user IDs>
WECHAT_BOT_POLL_TIMEOUT_MS=35000
WECHAT_BOT_ACCOUNT_ID=default
```

Personal-WeChat bot access can be affected by the ilink gateway, login expiry, API changes, and account-risk controls. Check platform rules and account risk before using it.

DingTalk uses the official DingTalk Stream chatbot connection. It is not desktop DingTalk automation. Source/BAT users need the optional dependency before receiving DingTalk messages:

```powershell
python -m pip install dingtalk-stream
```

DingTalk channel variables:

```text
NGA_BOT_CHANNEL=dingtalk
DINGTALK_CLIENT_ID=<DingTalk chatbot Client ID / App Key>
DINGTALK_CLIENT_SECRET=<DingTalk chatbot Client Secret / App Secret>
DINGTALK_ROBOT_CODE=<robotCode for proactive sends; empty falls back to Client ID>
DINGTALK_TARGET_USER_IDS=<target user IDs for proactive pushes, comma-separated>
DINGTALK_ALLOWED_USER_IDS=<empty means all, or comma-separated user IDs>
DINGTALK_ACCOUNT_ID=default
```

Messages sent to the DingTalk bot, such as `/start`, `/setting`, `/history_r`, `/pack_r`, and normal AI chat messages, are replied to through the Stream session. Proactive pushes, including new NGA replies, do-not-disturb summaries, and scheduled AI analysis, use `DINGTALK_TARGET_USER_IDS` and require the DingTalk app's robot proactive-send permission.

Recommended EXE setup:

1. Create a DingTalk app in the DingTalk developer console, enable the robot / Stream connection, then fill the app's `Client ID` / `App Key` and `Client Secret` / `App Secret` in the DingTalk profile.
2. `Robot Code` can be left empty at first; proactive sends fall back to `Client ID`. If your DingTalk app page shows a separate robotCode, fill that value.
3. Save the config, start the watcher once, then send `/start` or any message to the DingTalk bot.
4. Return to the EXE's DingTalk profile dialog and click `获取最近用户 ID` / `Get recent user ID`. The app reads the last received DingTalk message and fills the sender's user ID into `Target user ID`.
5. Save again, then choose that DingTalk profile in `Send targets` / `Listen rules`. Automatic new replies, quiet-hour summaries, and scheduled AI analysis can then be pushed proactively to that user. Multiple user IDs can be comma-separated.

DingTalk currently uses Markdown cards and text menus. `/start` and `/setting` return card-styled menus; reply with `1` through `8`, `hr10`, `u1`, `t1`, `a1/a0`, and similar short commands to operate them. DingTalk temporary Markdown cards cannot be overwritten in place like Feishu cards. During AI generation the bot sends an `AI 正在生成` card; when the result is ready it tries to update that card, and if DingTalk rejects the update because `cardTemplateId` is required, the watcher sends a new `AI 回复` result card instead. True clickable and in-place-updatable DingTalk interactive cards require a template created in DingTalk Card Builder and a configured `cardTemplateId`.

In the GUI, click `扫码绑定` in the WeChat config card. The watcher requests a QR code from the ilink gateway, opens the QR link, and waits for confirmation from your phone. After confirmation, it fills `WECHAT_BOT_TOKEN`, `WECHAT_BOT_TARGET_USER_ID`, `WECHAT_BOT_ALLOWED_USER_IDS`, and `WECHAT_BOT_ACCOUNT_ID`. Save the config before starting the watcher.

WeChat does not support Feishu-style interactive cards, so the watcher provides text shortcuts:

- After `/start`, reply with `1`, `2`, `3`, `4`, or `5` for common fetch, pack, and settings actions.
- After `/setting`, reply with `1` through `8` to control AI, auto analysis, scheduled analysis, and return to the main menu.
- Direct short aliases also work: `hr10`/`hr 10`, `pr20`/`pr 20`, `ht10`/`ht 10`, `pt50`/`pt 50`, `s`, `st`, `a1/a0`, `n1/n0`, `q1/q0`, `b`.

Email SMTP channel variables:

```powershell
NGA_BOT_CHANNEL=email
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_SECURITY=starttls
EMAIL_USERNAME=<sender@example.com>
EMAIL_PASSWORD=<SMTP password or app password>
EMAIL_FROM=<sender@example.com>
EMAIL_FROM_NAME=NGA Wolf Watcher
EMAIL_TO=<receiver@example.com>
```

In the GUI, prefer the mailbox type templates. 163, 126, QQ Mail, Gmail, and Outlook / Microsoft 365 fill the SMTP server, port, and encryption mode automatically. Only choose `Custom mailbox` when your provider is not listed and you need to enter those low-level SMTP settings manually. Templates configure the sender only; the recipient address is still selected in each listen rule's send destination.

The sender can be any mailbox that supports standard SMTP authentication, such as Gmail, Outlook, QQ Mail, 163 Mail, or an enterprise mailbox. Using a separate small mailbox as the sending bot is recommended so your personal mailbox authorization token is not stored in the watcher config. Most personal mailboxes cannot use the normal login password for SMTP. Open the mailbox provider's web settings, enable `POP3/SMTP/IMAP` or the equivalent SMTP service, then generate an authorization code, client authorization code, or app password. 163/126/QQ Mail usually use authorization codes. Gmail usually needs a Google App Password, and App Passwords require 2-Step Verification on the Google Account.

The recipient can be any email address. The email channel is outbound-only: it can receive new-reply pushes, quiet-hours summaries, packed `.txt` results, and AI analysis output, but it does not receive chat commands or log in to the recipient mailbox to read replies.

WxPusher channel variables:

```text
NGA_BOT_CHANNEL=wxpusher
WXPUSHER_SPTS=<SPT_xxx>
WXPUSHER_CONTENT_TYPE=markdown
```

Recommended EXE setup:

1. Install or open a WxPusher client and copy its `SPT` from the client.
2. In the EXE, switch the message channel to `WxPusher`, add a WxPusher profile, and fill `SPT`.
3. In `Listen rules`, add a send target and choose that WxPusher profile.
4. Click `Send test` on that target before starting long-running monitoring.

WxPusher is outbound-only in this app. It can receive new NGA replies, quiet-hours summaries, packed text content, and AI analysis output, but it does not support `/start`, `/setting`, manual fetch commands, or AI chat input from WxPusher.

## Do-Not-Disturb Hours

In `运行设置` / `Settings`, enable `免打扰时段` if you do not want automatic monitoring pushes during a weekly time range. Set a start weekday/time and an end weekday/time, for example `周五 18:00 -> 周一 08:00`. The time uses hour/minute dropdowns to avoid manual `HH:MM` input. Manual Feishu commands, packing, chat lookup, and test messages are not affected.

Do-not-disturb handling has two modes:

- `忽略新回复`: new replies found during the muted period are marked as seen and will not be sent later.
- `暂存并在免打扰结束后汇总推送`: new replies found during the muted period are stored and sent as one summary card after the muted period ends.

## How To Copy NGA Cookie

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

In the target Feishu group, mention the bot or use the card. In WeChat mode, send the same commands directly to the bot:

```text
/start
/setting
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

- `/history_r <uid|0> <count>` fetch recent replies by uid and send them through the selected channel.
- `/pack_r <uid|0> <count|Nd>` fetch recent replies by uid and pack the content. Use `1d` for today's natural day, or `3d` for today plus the previous two natural days. Feishu app mode sends a `.txt` file; WeChat mode also tries to send a real `.txt` file through iLink media upload, then falls back to text chunks if upload is unavailable.
- `/history_t <tid> <count>` fetch latest posts from a thread and send them through the selected channel.
- `/pack_t <tid> <count|Nd>` fetch latest posts from a thread and pack the content. `Nd` uses natural days and only applies to pack commands.

`/pack_r 45974302 10` is accepted as a compatibility alias for packing the default wolf thread.

### Watch Modes

The default watch mode is `author`, which keeps the old behavior: fetch replies from the target user's reply page. The new `thread_author` mode fetches recent posts from a fixed thread, then filters them by author id. This is useful when the NGA user-reply endpoint often returns 503, permission errors, or missing flushed posts, but the target thread is still readable.

```powershell
$env:NGA_WATCH_MODE = 'thread_author'   # author | thread_author | both
$env:NGA_THREAD_AUTHOR_WATCHES = '45974302:150058=wolf|receive_id=oc_xxx'
$env:NGA_THREAD_WATCH_TAIL_COUNT = '20'
$env:NGA_THREAD_WATCH_INTERVAL = '10'
```

`NGA_THREAD_AUTHOR_WATCHES` accepts one rule per line:

```text
tid:uid=label
tid:uid=label|receive_id=oc_xxx
tid:uid=label|app_id=cli_xxx|app_secret=xxx|receive_id=oc_xxx|id_type=chat_id
tid:uid1,uid2=label
```

- `tid:uid=label` uses the main Feishu bot and main Receive ID.
- Adding `receive_id=oc_xxx` reuses the main Feishu bot but pushes that thread-author combo to another group.
- Adding `app_id/app_secret/receive_id` gives that combo its own Feishu bot.
- `both` enables both the old user-reply watcher and the new thread-author watcher; if the same original reply is seen through both paths, it is deduplicated before pushing.
- If you use the recommended client, a new listen rule can select multiple users and multiple thread presets at once, and can also select multiple Feishu chats, WeChat users, DingTalk users, or email recipients. When both users and threads are multi-selected, the client expands them as "watch each selected user in each selected thread" and saves multiple compatible low-level listen rules.

Thread-author watch defaults to scanning the selected author's latest replies in the thread every 10 seconds. It prefers `read.php?tid=...&authorid=...`, while author-page watch still uses `NGA_INTERVAL`. AI history is merged by author uid: for example, `45974302:150058` and `150058=wolf` both write to `events/by_source/author_150058.jsonl`, with the thread title and listen-rule source kept in each event.

To confirm the actual NGA URL during debugging, set `NGA_LOG_REQUEST_URLS=true` before starting the watcher. The log then prints thread-author `read.php?tid=...&authorid=...` requests. Keep it off for normal long-running use to avoid noisy logs.

### Mention Alerts

If you want the bot to @ you in the card when a new wolf reply or a quiet-hour summary arrives:

1. Send `/setting` in the Feishu group to open the settings card.
2. Click `开启并@我`.
3. The watcher saves the sender id from that button click, so you do not need to look up a user id manually.
4. Future automatic new-reply cards and quiet-hour summary cards will include that @ at the top.
5. To disable it, open `/setting` again and click `关闭@提醒`.

This is one global on/off switch. The mention is embedded in the original card, so the bot does not send an extra message. The setting is persisted in the runtime state file and remains active after restarting the watcher.

## Config File And Manual Edits

The actual config path depends on how you run the app:

- One-command Linux install: `/etc/ngawolf/config.json`; runtime state defaults to `/var/lib/ngawolf`; logs default to `/var/log/ngawolf/watcher.log`.
- Source or regular CLI: config defaults to `~/.config/ngawolf/config.json`; state and logs default to `~/.local/state/ngawolf/`.
- Windows GUI: config defaults to `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`; the older `nga_wolf_config.json` is migrated automatically.

The config file uses JSONC-style JSON, so `//` and `/* ... */` comments are allowed. `ngawolf init`, `ngawolf config`, and the Windows GUI write Chinese comments plus common format examples into the file; saving again regenerates the built-in comments, so extra hand-written comments are not guaranteed to be preserved. After manual edits, run `sudo ngawolf check`; when running from source, use `python ngawolf_cli.py check`.

Common field rules:

- `nga_cookie`: required NGA login Cookie, usually including `ngaPassportUid` and `ngaPassportCid`.
- `watch_author_ids`: author resources, one `author_id=label` per line, for example `150058=wolf`.
- `preset_thread_ids`: thread resources, one `tid=label` per line, for example `45974302=main thread`.
- `push_targets`: push target list stored as a JSON string; each target needs an `id`, and `channel` can be `feishu`, `wechat`, `dingtalk`, `email`, or `wxpusher`.
- `listen_rules`: listen rule list stored as a JSON string; `mode=author` watches an author page, `mode=thread_author` watches an author inside a specific thread, and `target_ids` references one or more `push_targets` ids.

For compatibility with older config loading, structured route fields are still saved as JSON strings. When editing by hand, keep the outer quotes and escape inner quotes. If unsure, add one item with the TUI first, then follow the comments and examples written into the config file:

```json
{
  "push_targets": "[{\"id\":\"feishu_main\",\"label\":\"main Feishu group\",\"channel\":\"feishu\",\"profile_id\":\"default\",\"receive_id\":\"oc_xxx\",\"id_type\":\"chat_id\"}]",
  "listen_rules": "[{\"id\":\"thread_author:45974302:150058\",\"label\":\"wolf in thread\",\"mode\":\"thread_author\",\"tid\":\"45974302\",\"author_id\":\"150058\",\"target_ids\":[\"feishu_main\"]}]"
}
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
$env:NGA_WATCH_MODE = 'author'
$env:NGA_AUTHOR_IDS = '150058=wolf,123456=other'
$env:NGA_PRESET_TIDS = '45974302=wolf thread,888888=other thread'
$env:NGA_THREAD_AUTHOR_WATCHES = '45974302:150058=wolf|receive_id=oc_xxx'
$env:NGA_THREAD_WATCH_TAIL_COUNT = '20'
$env:NGA_THREAD_WATCH_INTERVAL = '10'
$env:NGA_INTERVAL = '30'
$env:NGA_JITTER = '20'
$env:NGA_RETRIES = '10'
$env:NGA_RETRY_INITIAL_DELAY = '1'
$env:NGA_RETRY_DELAY = '1'
$env:NGA_PAGE_DELAY = '2.0'
$env:NGA_REQUEST_MIN_INTERVAL = '1.0'
$env:NGA_CACHE_TTL = '15'
$env:NGA_UNAVAILABLE_RETRIES = '3'
```

Source users can also configure the new routing model directly with JSON:

```powershell
$env:NGA_PUSH_TARGETS = '[{"id":"feishu_main","channel":"feishu","profile_id":"default","receive_id":"oc_xxx","default_author_id":"150058","default_tid":"45974302"}]'
$env:NGA_LISTEN_RULES = '[{"id":"wolf_thread","mode":"thread_author","tid":"45974302","author_id":"150058","target_ids":["feishu_main"]}]'
$env:AI_SCHEDULE_TARGET_IDS = 'feishu_main'
```

Optional AI Agent defaults, all disabled unless you opt in:

```powershell
$env:AI_ENABLED = 'false'
$env:AI_PROVIDER = 'codex'
$env:AI_WORK_DIR = '.ai_agent_workspace'
$env:AI_AUTO_ANALYZE_NEW_POST = 'false'
$env:AI_SCHEDULE_ENABLED = 'false'
$env:AI_PERMISSION_MODE = 'default'
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

Run the pywebview + React UI:

```powershell
python -m pip install pywebview pystray pillow
cd .\webui
npm.cmd ci
npm.cmd run build
cd ..
python .\nga_wolf_webgui.py
```

The recommended client reuses the same `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`, runtime state, and watcher startup path, but presents NGA resources, message channel profiles, listen rules, AI settings, do-not-disturb, runtime options, and an advanced JSON editor in clearer collapsible panels. With the new model, Feishu, WeChat, DingTalk, and email can be configured at the same time; listen rules decide where automatic pushes go.

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
python .\nga_feishu_watch.py --interval 30 --jitter 20 --retries 10 --retry-initial-delay 3 --retry-delay 1
```

`--retry-initial-delay` is the wait before the first retry, and `--retry-delay` is the extra step added after each failure. The example above retries after 3 seconds, then 4 seconds, then 5 seconds. The matching environment variables are `NGA_RETRY_INITIAL_DELAY` and `NGA_RETRY_DELAY`. NGA 503 responses are treated as ordinary failures and use the full `NGA_RETRIES` count. Other temporary-unavailable responses such as 429/500/502/504 use the same delay schedule, while `NGA_UNAVAILABLE_RETRIES` limits how many of those temporary failures are retried.

Watcher polling and manual commands share the same NGA request coordinator. `NGA_REQUEST_MIN_INTERVAL` enforces a minimum gap between NGA HTTP requests in the same process, and `NGA_CACHE_TTL` briefly reuses successful JSON responses for the same URL. This lets a manual “latest reply” command reuse the page that the watcher just fetched instead of immediately hitting NGA again.

Disable command polling in non-WebSocket mode:

```powershell
python .\nga_feishu_watch.py --disable-commands
```

Mention alerts can also be initialized with environment variables or CLI flags, but the Feishu `/setting` card is preferred because it captures your sender id automatically.

```powershell
$env:FEISHU_MENTION_ENABLED="true"
$env:FEISHU_MENTION_USER_ID="ou_xxx"
python .\nga_feishu_watch.py --feishu-mention-enabled --feishu-mention-user-id ou_xxx
```

NGA images in Feishu cards are embedded by default when you use Feishu app credentials. The watcher downloads the image URL, uploads it to Feishu, renders the returned `image_key` in the card, and falls back to the old clickable link if any step fails. Webhook mode cannot upload card images and keeps links. Some NGA image URLs reject HTTPS direct downloads; the watcher automatically retries the same image over HTTP before falling back to a link.

```powershell
$env:FEISHU_CARD_IMAGES="true"
$env:FEISHU_CARD_IMAGE_LIMIT="6"
python .\nga_feishu_watch.py --feishu-card-images --feishu-card-image-limit 6
```

Uploaded `image_key` values are cached in `feishu_image_cache.json` next to `.nga_seen.json`, so repeated history queries do not upload the same NGA image again.

## Legacy Custom Bot Webhook

Webhook mode is still supported:

```powershell
$env:FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/...'
$env:FEISHU_SECRET = 'optional signing secret'
python .\nga_feishu_watch.py
```
