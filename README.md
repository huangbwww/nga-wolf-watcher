# NGA Wolf Watcher

English | [中文说明](README.zh-CN.md)

Watch specified NGA replies, push new replies to Feishu, WeChat, DingTalk, or email, and use chat commands / Feishu cards to fetch history or pack results into `.txt` files.

## Features

- Continuous monitoring: after you click `启动监听` / `Start Watcher`, the app checks author reply pages or filters target authors inside fixed threads, then pushes newly found replies to selected Feishu chats, WeChat accounts, DingTalk users, or email recipients.
- Manual actions: in Feishu, WeChat, or DingTalk you can use commands; Feishu also supports card buttons to fetch recent user replies, fetch thread replies, or pack results into `.txt` files.
- Do-not-disturb hours: automatic monitoring can be muted for a continuous weekly range, such as Friday 18:00 to Monday 08:00. Muted replies can either be ignored or summarized after the quiet period ends.
- Optional local AI Agent enhancement: disabled by default. When enabled, it can save wolf posts, call local Codex / Claude Code / CodeWhale / custom commands, reply to `/ai` commands in Feishu, and run scheduled intraday reviews.

### AI Analysis Notes

AI is disabled by default. With the default config, the app does not require Codex, Claude, Node.js, API keys, or any extra AI dependency. When AI is disabled, NGA monitoring, Feishu pushes, WebSocket commands, card actions, do-not-disturb, GUI startup, and packaging keep their existing behavior.

This feature has a higher setup bar than the normal watcher. It is not a built-in hosted model; it forwards Feishu messages, newly captured NGA replies, and local context to an AI agent command running on your own machine. Install and sign in to Codex CLI, Claude Code CLI, CodeWhale, or provide a custom command before enabling it. Simple installation examples:

```powershell
# Codex CLI, requires Node/npm
npm install -g @openai/codex
codex

# Claude Code CLI; Windows users can also check Anthropic's winget/install-script options
npm install -g @anthropic-ai/claude-code
claude

# CodeWhale / DeepSeek TUI, requires Node/npm
npm install -g codewhale
codewhale auth set --provider deepseek
```

AI-assisted market analysis is personal and workflow-dependent. This project only provides a local experiment surface: newly fetched wolf posts are saved under `events/wolf_history.jsonl` and `events/latest_event.json`; `context/positions.json`, `context/watchlist.md`, and `context/notes.md` are reserved for your positions, watchlist, and notes. One practical workflow is to send position screenshots or position notes to the AI, let it organize them locally, then keep discussing later actions, trading habits, current market conditions, and possible directions in the Feishu group. The AI can then combine wolf-post history, the market, your positions, and your own latest thoughts into analysis or suggestions.

AI analysis is only a tool, not an out-of-the-box source of fixed answers. Its usefulness depends on the context, positions, watchlist, and feedback you provide over time. You can gradually correct its answer style, analysis depth, risk preference, and vocabulary in normal conversation so it better matches your own workflow. AI output is only for information organization, risk review, and discussion. It is not investment advice and the watcher does not place trades.

## Feedback

If you run into bugs or usage problems, please open an [Issue](https://github.com/huangbwww/nga-wolf-watcher/issues).

Feature ideas are also welcome. They can be related to NGA, stock-related workflows, or other adjacent personal tools. I check issues periodically and update when I have time.

## 1.3.0 Linux Release

Starting with `v1.3.0`, releases include a Linux server install path. On a server you can install the `ngawolf` command with one shell command, then use the terminal TUI to configure the NGA Cookie, push channels, NGA users/threads, and listen rules. The installed version creates a systemd service by default, and you can also manage background runtime and logs with `ngawolf start/stop/status/logs`.

## Release Assets

Release assets use the same lowercase project prefix and include version, platform, architecture, and package type:

```text
nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe
nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip
nga-wolf-watcher-vX.Y.Z-linux-x86_64.tar.gz
nga-wolf-watcher-vX.Y.Z-linux-aarch64.tar.gz
install-linux.sh
SHA256SUMS
```

The Windows `setup.exe` and `portable.zip` replace the old single large onefile exe. The Linux archives contain the headless `ngawolf` CLI; `install-linux.sh` installs those archives first and falls back to source installation only when needed.

The Windows setup installer supports Simplified Chinese and English. Current Windows release assets are not code-signed, so Windows SmartScreen may show an unknown-publisher warning. Verify downloaded files with `SHA256SUMS` from the same release when needed.

## Windows Setup Or Portable

This path does not require editing code or running Python commands.

1. Download `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe` from [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest). If you do not want to install, download `nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip`, extract it, and run `NGA-Wolf-Watcher.exe` inside the extracted folder.
2. Open [Feishu Open Platform](https://open.feishu.cn/page/openclaw), create a bot app, and copy the app's `App ID` and `App Secret`.
3. Add the bot to the target Feishu group.
4. If you want to use `/start` and other commands without mentioning the bot, grant `im:message.group_msg`.
5. Open the client, add a Feishu profile under `消息通道`, fill `App ID` and `App Secret`, then click `查询群组并保存` in that profile dialog.
6. Add common user IDs and thread IDs under `目标`, then add listen rules under `规则` / `监听规则`: choose author-page monitoring or fixed-thread author filtering, and directly select the Feishu chats or WeChat accounts to receive pushes.
7. Log in to `https://bbs.nga.cn/`, copy the browser request `Cookie`, and paste it into `NGA Cookie`.
8. Click `保存配置`, then click `启动监听`.

Keep the first-start mark-seen option enabled before the first launch. It marks currently fetched NGA replies as already seen, so old replies are not pushed to Feishu in bulk.

The setup and portable builds use the same data directory as the older exe. The GUI saves local secrets under `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`. Runtime state is stored next to it as `.nga_seen.json` by default. Do not share these files.

### Message Channels, Targets, And Listen Rules

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

## Advanced Usage

If you only want to use the EXE, you can stop reading here.

### Run With BAT

This mode requires a local Python environment.

Copy `start_local.example.bat` to `start_local.bat`, fill the empty `NGA_COOKIE` and Feishu values, then run it.

The BAT installs `lark-oapi` automatically. On the first run, if `.nga_seen.json` does not exist, it runs `--mark-seen` before starting the watcher to avoid pushing old replies.

### One-Command Linux Install

On a Linux server, install the `ngawolf` command without cloning the repository:

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo bash
```

The installer first tries the standard Linux release package for the current CPU architecture, such as `nga-wolf-watcher-vX.Y.Z-linux-x86_64.tar.gz` or `nga-wolf-watcher-vX.Y.Z-linux-aarch64.tar.gz`. These binary packages are built on Ubuntu 22.04 and target glibc-based Linux distributions; very old glibc systems and Alpine/musl systems may need the source-install fallback. If no suitable package is available, it falls back to source installation. It puts the app under `/opt/ngawolf`, stores config at `/etc/ngawolf/config.json`, stores runtime state under `/var/lib/ngawolf`, and creates `/usr/local/bin/ngawolf`. First-time setup opens a terminal wizard with arrow-key selection. In Feishu mode, after you enter the App ID / Secret, it lists visible groups so you can move with Up/Down, toggle with Space, then press Enter to confirm. WeChat binding prints both a terminal QR code and the original link. If the terminal TUI dependency is unavailable, the CLI falls back to the older numeric prompts:

```bash
sudo ngawolf init
sudo ngawolf check
sudo ngawolf mark-seen
sudo ngawolf test-send
```

Run in foreground:

```bash
sudo ngawolf run
```

If the server uses systemd, the installer writes `ngawolf.service`. After config and `mark-seen` look correct, start the service:

```bash
sudo systemctl enable --now ngawolf
sudo systemctl status ngawolf
```

You can also use the CLI wrapper to manage the background watcher and logs:

```bash
sudo ngawolf start
sudo ngawolf status
sudo ngawolf logs -f
sudo ngawolf restart
sudo ngawolf stop
```

The installed log file defaults to `/var/log/ngawolf/watcher.log`. If systemd is unavailable, `ngawolf start` falls back to a local background process and writes its PID to `/var/lib/ngawolf/watcher.pid`.

To edit config later:

```bash
sudo ngawolf config
sudo systemctl restart ngawolf
```

For a pinned release or local installer test, set environment variables:

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo NGAWOLF_VERSION=v1.3.0 bash
sudo NGAWOLF_SOURCE_DIR=/path/to/nga-wolf bash tools/install-linux.sh
```

If the server cannot reach GitHub reliably, you can use a third-party GitHub mirror. Mirrors are not official project services and may stop working; pin the version to avoid `latest` redirects failing on the mirror:

```bash
curl -fsSL https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/releases/download/vX.Y.Z/install-linux.sh \
  | sudo NGAWOLF_VERSION=vX.Y.Z NGAWOLF_GITHUB_PROXY=https://ghfast.top bash
```

You can also provide the mirrored source archive URL directly:

```bash
curl -fsSL https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/releases/download/vX.Y.Z/install-linux.sh \
  | sudo NGAWOLF_VERSION=vX.Y.Z NGAWOLF_ARCHIVE_URL=https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/archive/refs/tags/vX.Y.Z.tar.gz bash
```

For the most reliable mirrored install, download the source archive once and then install from that local directory:

```bash
MIRROR=https://ghfast.top VERSION=vX.Y.Z bash -c '
set -e
tmp=$(mktemp -d)
curl -fL "$MIRROR/https://github.com/huangbwww/nga-wolf-watcher/archive/refs/tags/$VERSION.tar.gz" -o "$tmp/src.tar.gz"
tar -xzf "$tmp/src.tar.gz" -C "$tmp" --strip-components=1
sudo NGAWOLF_SOURCE_DIR="$tmp" bash "$tmp/tools/install-linux.sh"
'
```

If the Linux server cannot reach GitHub at all, download or clone the source on another machine, copy it to the server, then run:

```bash
sudo NGAWOLF_SOURCE_DIR=/path/to/nga-wolf bash /path/to/nga-wolf/tools/install-linux.sh
```

The installer still uses pip for Python dependencies. If PyPI is also slow, pass a pip mirror:

```bash
sudo PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple NGAWOLF_SOURCE_DIR=/path/to/nga-wolf bash /path/to/nga-wolf/tools/install-linux.sh
```

### Run From Source

Install dependencies:

```powershell
cd D:\nga-wolf
python -m pip install lark-oapi customtkinter questionary Pillow qrcode
```

On a Linux server, use the interactive CLI instead of starting the desktop GUI or web manager. Feishu mode can list visible groups and generate push targets plus listen rules automatically; use Up/Down to move, Space to select groups, and Enter to confirm. WeChat binding tries to print the QR code directly in the terminal and always keeps the copyable original link. WxPusher setup defaults to the SPT simple-push mode, so the wizard only needs the SPT unless you choose the App Token + UID/Topic modes:

```bash
python ngawolf_cli.py init
```

To update an existing config later:

```bash
python ngawolf_cli.py config
```

Common checks and runtime commands:

```bash
python ngawolf_cli.py check
python ngawolf_cli.py mark-seen
python ngawolf_cli.py test-send
python ngawolf_cli.py run
python ngawolf_cli.py run --once
```

The default config file is `~/.config/ngawolf/config.json`; default runtime state and logs live under `~/.local/state/ngawolf/`. For systemd, Docker, or another process manager, keep the watcher in foreground mode:

```bash
python ngawolf_cli.py --config /etc/ngawolf/config.json --data-dir /var/lib/ngawolf run
```

Relative state paths are resolved under `--data-dir`. Use `init` for the first config, then `config` for guided edits; pressing Enter keeps the current value, which makes Cookie, listen rule, and target updates easier later.

#### Config File And Manual Edits

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

### Optional Local AI Agent Enhancement

This section is mainly for source/BAT users who need CLI flags, environment variables, and work-directory details. EXE-only users can start with the earlier “AI Analysis Notes” section and the GUI's `AI 分析` settings area.

Enable Codex:

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'codex'
$env:AI_CODEX_COMMAND = 'codex'
python .\nga_feishu_watch.py --ws
```

Enable Claude Code:

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'claude'
$env:AI_CLAUDE_COMMAND = 'claude'
python .\nga_feishu_watch.py --ws
```

Enable CodeWhale:

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'codewhale'
$env:AI_CODEWHALE_COMMAND = 'codewhale'
python .\nga_feishu_watch.py --ws
```

Use a custom command:

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'custom'
$env:AI_CUSTOM_COMMAND = 'python D:\agents\run_agent.py --work-dir {work_dir} --prompt {prompt_file} --output {output_file}'
python .\nga_feishu_watch.py --ws
```

Supported custom placeholders: `{work_dir}`, `{prompt_file}`, `{output_file}`, `{task_type}`, `{latest_event}`, `{history_file}`, `{session_id}`, `{image_files}`, `{file_files}`, `{permission_mode}`, `{model}`, `{reasoning_effort}`.

Model and reasoning effort:

- The GUI's default model and default reasoning effort are startup defaults. Leave them empty or `default` to use the agent's own default.
- The Feishu `/setting` card can override model/reasoning at runtime. Click `恢复默认模型/强度` to return to the GUI/startup defaults.
- Codex model dropdown: `gpt-5.5`, `gpt-5.4`, `gpt-5.4-mini`, `gpt-5.3-codex`, `gpt-5.3-codex-spark`, `gpt-5.2`; reasoning effort: `low`, `medium`, `high`, `xhigh`.
- Claude model dropdown: `default`, `sonnet[1m]`, `opus[1m]`, `haiku`; effort: `low`, `medium`, `high`, `xhigh`, `max`.
- CodeWhale model dropdown: `deepseek-v4-flash`, `deepseek-v4-pro`, or `auto` for CodeWhale's router; reasoning effort: `auto`, `off`, `low`, `medium`, `high`, `max`.
- Codex receives the model through `codex exec --model <model>` and receives reasoning effort through a Codex config override.
- Claude Code receives the model through `claude --model <model>` and reasoning effort through `--effort <level>`.
- CodeWhale runs in the background through `codewhale exec --output-format stream-json --auto`. The first turn captures CodeWhale's real saved session id from stream-json events, and later turns resume it with `--resume <id>`. The model is passed through `--model <model>`, and reasoning effort is passed through a temporary runtime config file.
- Custom commands only receive `{model}` and `{reasoning_effort}` placeholders; they take effect only if your command template uses them.

Auto-analyze new wolf posts:

```powershell
$env:AI_ENABLED = 'true'
$env:AI_AUTO_ANALYZE_NEW_POST = 'true'
```

Scheduled intraday review, defaulting to A-share trading windows:

```powershell
$env:AI_ENABLED = 'true'
$env:AI_SCHEDULE_ENABLED = 'true'
$env:AI_SCHEDULE_INTERVAL_MINUTES = '5'
$env:AI_SCHEDULE_WINDOWS = 'weekday:09:30-11:30,13:00-15:00'
```

Custom schedule window format:

- `weekday:09:30-11:30,13:00-15:00`: Monday to Friday, two intraday windows.
- `mon-fri:09:30-11:30`: Monday to Friday, one window.
- `1-5:09:30-11:30,13:00-15:00`: numeric weekdays, where `1` is Monday and `7` is Sunday.
- Use `;` to join multiple day groups, for example `1-5:09:30-11:30;6:10:00-11:00`.

AI Feishu commands:

```text
/start                     # open the fetch/pack menu card
/setting                   # open settings for AI, scheduled analysis, prompts, and permission mode
/ai help
/ai status
/ai on
/ai off
/mode
/mode yolo
/ai mode full-auto
/model
/model auto
/model gpt-5.4
/reasoning
/reasoning default
/reasoning high
/ai auto on
/ai auto off
/ai latest
<plain non-command message>   # sent to AI when AI is on
/ai ask <question>            # optional compatibility form
/ai schedule on
/ai schedule off
/ai schedule every <minutes>
/ai schedule windows weekday:09:30-11:30,13:00-15:00
/ai schedule prompt <prompt>
/ai auto prompt <prompt>
/ai prompt
/ai workdir
/ai history <N>
/ai last
```

AI configuration keys:

```text
NGA_BOT_CHANNEL=feishu
WECHAT_BOT_TOKEN=
WECHAT_BOT_BASE_URL=https://ilinkai.weixin.qq.com
WECHAT_BOT_CDN_BASE_URL=https://novac2c.cdn.weixin.qq.com/c2c
WECHAT_BOT_TARGET_USER_ID=
WECHAT_BOT_ALLOWED_USER_IDS=
WECHAT_BOT_POLL_TIMEOUT_MS=35000
WECHAT_BOT_ROUTE_TAG=
WECHAT_BOT_ACCOUNT_ID=default
DINGTALK_CLIENT_ID=
DINGTALK_CLIENT_SECRET=
DINGTALK_ROBOT_CODE=
DINGTALK_TARGET_USER_IDS=
DINGTALK_ALLOWED_USER_IDS=
DINGTALK_ACCOUNT_ID=default
AI_ENABLED=false
AI_PROVIDER=codex
AI_WORK_DIR=.ai_agent_workspace
AI_AUTO_ANALYZE_NEW_POST=false
AI_AUTO_ANALYSIS_PROMPT=According to the latest NGA reply history, my current positions and watchlist, query public A-share market information in real time, then analyze market changes, opportunities, and risks, and give key observations and operation ideas.
AI_PROMPT_FILE=
AI_TIMEOUT=300
AI_CODEX_COMMAND=codex
AI_CLAUDE_COMMAND=claude
AI_CODEWHALE_COMMAND=codewhale
AI_CUSTOM_COMMAND=
AI_MODEL=
AI_CODEX_MODEL=
AI_CLAUDE_MODEL=
AI_CODEWHALE_MODEL=
AI_CUSTOM_MODEL=
AI_REASONING_EFFORT=
AI_CODEX_REASONING_EFFORT=
AI_CLAUDE_EFFORT=
AI_CODEWHALE_REASONING_EFFORT=
AI_CUSTOM_REASONING_EFFORT=
AI_IGNORE_CODEX_USER_CONFIG=false
AI_SCHEDULE_ENABLED=false
AI_SCHEDULE_INTERVAL_MINUTES=5
AI_SCHEDULE_PROMPT=
AI_SCHEDULE_WINDOWS=weekday:09:30-11:30,13:00-15:00
AI_ALLOWED_USER_IDS=
AI_SEND_ERRORS_TO_FEISHU=false
AI_MAX_FEISHU_CHARS=3500
AI_UPLOAD_LONG_RESULT=false
AI_REPLY_STATUS_EMOJI=WITTY
AI_PERMISSION_MODE=default
```

When `AI_WORK_DIR` is relative, the watcher resolves it next to the runtime state file. In the GUI/EXE flow that means `%LOCALAPPDATA%\NGA Wolf Watcher\.ai_agent_workspace`; in plain CLI flow with the default `.nga_seen.json`, it stays under the current working directory. Use an absolute path if you want a fixed location.

AI work directory layout:

```text
.ai_agent_workspace/
  events/latest_event.json
  events/wolf_history.jsonl
  events/YYYYMMDD_HHMMSS_<key>.json
  analysis/latest_analysis.md
  analysis/YYYYMMDD_HHMMSS_<task_type>_<key>.md
  attachments/YYYYMMDD_HHMMSS/*
  attachments/nga/<post-key>/image_*.jpg
  prompts/default_stock_analysis.md
  prompts/scheduled_analysis.md
  context/memory.md
  context/watchlist.md
  AGENTS.md
  context/README.md
  state.json
  logs/ai_agent.log
```

Prompt behavior:

- New-post auto analysis and `/ai latest` send only the configured auto-analysis prompt. The default prompt asks the agent to combine reply history, positions/watchlist, and real-time public A-share market information.
- NGA reply images from `[img]`, HTML image tags, and common attachment links are saved into `image_urls` in `events/latest_event.json` / `wolf_history.jsonl`. The watcher also tries to download them under `attachments/nga/<post-key>/` and writes successful local files into `image_paths`. The Codex provider passes those images with `--image <path>` for auto analysis and `/ai latest`; if download fails, the original image URLs remain available in the event JSON.
- Plain Feishu messages are forwarded as-is to the local agent. General role and preferences live in `context/memory.md` / `AGENTS.md`, so the agent can read them when useful without injecting the same chat prompt every time.
- Feishu image messages, rich-text images, and file attachments are downloaded into `attachments/`, then local absolute paths are passed to the agent. The Codex provider also sends each image with `--image <path>`. If you reply to a file message and ask the agent to read it, the watcher also tries to resolve the replied message's attachment.
- AI messages from Feishu and WeChat that use the same AI work directory are processed through one local serial queue, so multiple messages do not concurrently resume the same local agent session.
- `/mode` follows cc-connect-style permission modes. Sending `/mode` returns a clickable selection card. Codex supports `default`, `auto-edit`, `full-auto`, and `yolo`; Claude supports `default`, `acceptEdits`, `plan`, `auto`, `bypassPermissions`, and `dontAsk`; CodeWhale supports `default`, `auto`, and `yolo`. `/mode yolo` or a card button click is persisted in AI state and only affects later AI tasks; it does not rewrite startup arguments.
- While AI is processing a Feishu message, the bot temporarily adds a reaction to the source message as a "replying" status and removes it after completion or failure. Override the default with `AI_REPLY_STATUS_EMOJI`; if the Feishu app lacks reaction permission, this only logs a warning and does not block AI replies.
- Scheduled analysis sends only the configured scheduled prompt; when empty, it uses the same concise default prompt as auto analysis.
- Codex first tries `codex exec resume --last` to reuse the latest session under the AI work directory, then creates a new session only when none exists. CodeWhale captures and stores the real session id from stream-json, then resumes with `--resume <id>`. Claude Code uses a stable `--session-id`, and custom commands can use `{session_id}`.

Security notes:

- AI output is for information organization, risk review, and observation only. It is not investment advice.
- The watcher does not place trades and the default prompts explicitly forbid buy/sell instructions.
- Do not put Cookies, Feishu secrets, account credentials, or full private position details into prompts, logs, or Feishu messages.
- `AI_ALLOWED_USER_IDS` can restrict `/ai on/off/ask/latest/schedule` to specific Feishu sender IDs.

Troubleshooting:

- `codex`, `claude`, or `codewhale` not found: install the tool locally or set `AI_CODEX_COMMAND` / `AI_CLAUDE_COMMAND` / `AI_CODEWHALE_COMMAND` to the full command.
- Timeout: increase `AI_TIMEOUT` or reduce the prompt/context size.
- Empty output: check `logs/ai_agent.log`; stdout is used as a fallback if the output file is missing.
- Feishu message too long: the default is truncated text. Set `AI_UPLOAD_LONG_RESULT=true` if you want long results uploaded as files.
- Permission denied: check `AI_ALLOWED_USER_IDS` and the sender ID reported by Feishu.
- Replying status is not shown: check whether the Feishu app has message reaction permissions, or set `AI_REPLY_STATUS_EMOJI` to an emoji type supported by your tenant.
- Images are not readable: for Feishu images, check whether the Feishu app has message resource read permission; for NGA images, check whether `events/latest_event.json` has `image_urls` and whether `attachments/nga/` contains downloaded files. Codex receives downloaded images through `--image`; if download fails, ask the agent to open the original URL from the event JSON.
- NGA images do not show inside Feishu cards: this only works in Feishu app mode, not webhook mode. Check whether the app can upload images, whether the original NGA image URL is reachable from the watcher machine, and whether `FEISHU_CARD_IMAGES` is still enabled. If upload fails, the card intentionally keeps the clickable image link.
- WeChat proactive pushes fail: send one message from the target WeChat account first, then make sure `WECHAT_BOT_TARGET_USER_ID` matches the cached user id.
- WeChat images/files are unreadable: check `WECHAT_BOT_CDN_BASE_URL`. Encrypted media download and outgoing file upload need `pycryptodome`; if upload is unavailable, packed txt content falls back to text chunks.
- Feishu txt/file attachments are not readable: check the same message resource read permission. The watcher downloads files into `attachments/` and passes local paths to the agent. For reply-to-file workflows, the bot must also be allowed to read the replied message.

The script stores pushed reply ids, handled command ids, and deferred quiet-hour replies in `.nga_seen.json`. In the EXE GUI, the default file lives under `%LOCALAPPDATA%\NGA Wolf Watcher\`, next to `config.json`. It is separate from config because it is runtime state and is written frequently; deleting it resets the watcher’s seen/handled history.

### Build Windows Release Assets

Build the frontend first, then package the pywebview client as an onedir app. The release workflow then zips that folder for portable use and builds an installer with Inno Setup:

```powershell
cd .\webui
npm.cmd ci
npm.cmd run build
cd ..
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean .\NGA-Wolf-Watcher-Web-Onedir.spec
```

The portable app folder is `dist\NGA-Wolf-Watcher\`. Release assets are named `nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip` and `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe`.

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
