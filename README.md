# NGA Wolf Watcher

English | [中文说明](README.zh-CN.md)

Watch a specified NGA user's replies, push new replies to Feishu, and use Feishu cards to fetch history or pack results into `.txt` files.

## Features

- Continuous monitoring: after you click `启动监听` / `Start Watcher`, the app keeps checking the configured `Default User ID` for new NGA replies and pushes newly found replies to the target Feishu group.
- Manual Feishu actions: in the Feishu group, you can use commands or card buttons to fetch recent user replies, fetch thread replies, or pack results into `.txt` files.
- Do-not-disturb hours: automatic monitoring can be muted for a continuous weekly range, such as Friday 18:00 to Monday 08:00. Muted replies can either be ignored or summarized after the quiet period ends.
- Optional local AI Agent enhancement: disabled by default. When enabled, it can save wolf posts, call local Codex / Claude Code / custom commands, reply to `/ai` commands in Feishu, and run scheduled intraday reviews.

### AI Analysis Notes

AI is disabled by default. With the default config, the app does not require Codex, Claude, Node.js, API keys, or any extra AI dependency. When AI is disabled, NGA monitoring, Feishu pushes, WebSocket commands, card actions, do-not-disturb, GUI startup, and packaging keep their existing behavior.

This feature has a higher setup bar than the normal watcher. It is not a built-in hosted model; it forwards Feishu messages, newly captured NGA replies, and local context to an AI agent command running on your own machine. Install and sign in to Codex CLI, Claude Code CLI, or provide a custom command before enabling it. Simple installation examples:

```powershell
# Codex CLI, requires Node/npm
npm install -g @openai/codex
codex

# Claude Code CLI; Windows users can also check Anthropic's winget/install-script options
npm install -g @anthropic-ai/claude-code
claude
```

AI-assisted market analysis is personal and workflow-dependent. This project only provides a local experiment surface: newly fetched wolf posts are saved under `events/wolf_history.jsonl` and `events/latest_event.json`; `context/positions.json`, `context/watchlist.md`, and `context/notes.md` are reserved for your positions, watchlist, and notes. One practical workflow is to send position screenshots or position notes to the AI, let it organize them locally, then keep discussing later actions, trading habits, current market conditions, and possible directions in the Feishu group. The AI can then combine wolf-post history, the market, your positions, and your own latest thoughts into analysis or suggestions.

AI analysis is only a tool, not an out-of-the-box source of fixed answers. Its usefulness depends on the context, positions, watchlist, and feedback you provide over time. You can gradually correct its answer style, analysis depth, risk preference, and vocabulary in normal conversation so it better matches your own workflow. AI output is only for information organization, risk review, and discussion. It is not investment advice and the watcher does not place trades.

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

- `/history_r <uid|0> <count>` fetch recent replies by uid and send cards.
- `/pack_r <uid|0> <count>` fetch recent replies by uid and send a `.txt` file.
- `/history_t <tid> <count>` fetch latest posts from a thread and send cards.
- `/pack_t <tid> <count>` fetch latest posts from a thread and send a `.txt` file.

`/pack_r 45974302 10` is accepted as a compatibility alias for packing the default wolf thread.

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
$env:NGA_PAGE_DELAY = '2.0'
$env:NGA_UNAVAILABLE_RETRIES = '3'
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
- Codex receives the model through `codex exec --model <model>` and receives reasoning effort through a Codex config override.
- Claude Code receives the model through `claude --model <model>` and reasoning effort through `--effort <level>`.
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
AI_ENABLED=false
AI_PROVIDER=codex
AI_WORK_DIR=.ai_agent_workspace
AI_AUTO_ANALYZE_NEW_POST=false
AI_AUTO_ANALYSIS_PROMPT=According to the latest NGA reply history, my current positions and watchlist, query public A-share market information in real time, then analyze market changes, opportunities, and risks, and give key observations and operation ideas.
AI_PROMPT_FILE=
AI_TIMEOUT=300
AI_CODEX_COMMAND=codex
AI_CLAUDE_COMMAND=claude
AI_CUSTOM_COMMAND=
AI_MODEL=
AI_CODEX_MODEL=
AI_CLAUDE_MODEL=
AI_CUSTOM_MODEL=
AI_REASONING_EFFORT=
AI_CODEX_REASONING_EFFORT=
AI_CLAUDE_EFFORT=
AI_CUSTOM_REASONING_EFFORT=
AI_IGNORE_CODEX_USER_CONFIG=true
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
- AI messages for the same AI work directory and Feishu chat are processed serially, so multiple Feishu messages do not concurrently resume the same local agent session.
- `/mode` follows cc-connect-style permission modes. Sending `/mode` returns a clickable selection card. Codex supports `default`, `auto-edit`, `full-auto`, and `yolo`; Claude supports `default`, `acceptEdits`, `plan`, `auto`, `bypassPermissions`, and `dontAsk`. `/mode yolo` or a card button click is persisted in AI state and only affects later AI tasks; it does not rewrite startup arguments.
- While AI is processing a Feishu message, the bot temporarily adds a reaction to the source message as a "replying" status and removes it after completion or failure. Override the default with `AI_REPLY_STATUS_EMOJI`; if the Feishu app lacks reaction permission, this only logs a warning and does not block AI replies.
- Scheduled analysis sends only the configured scheduled prompt; when empty, it uses the same concise default prompt as auto analysis.
- Codex first tries `codex exec resume --last` to reuse the latest session under the AI work directory, then creates a new session only when none exists. Claude Code uses a stable `--session-id`, and custom commands can use `{session_id}`.

Security notes:

- AI output is for information organization, risk review, and observation only. It is not investment advice.
- The watcher does not place trades and the default prompts explicitly forbid buy/sell instructions.
- Do not put Cookies, Feishu secrets, account credentials, or full private position details into prompts, logs, or Feishu messages.
- `AI_ALLOWED_USER_IDS` can restrict `/ai on/off/ask/latest/schedule` to specific Feishu sender IDs.

Troubleshooting:

- `codex` or `claude` not found: install the tool locally or set `AI_CODEX_COMMAND` / `AI_CLAUDE_COMMAND` to the full command.
- Timeout: increase `AI_TIMEOUT` or reduce the prompt/context size.
- Empty output: check `logs/ai_agent.log`; stdout is used as a fallback if the output file is missing.
- Feishu message too long: the default is truncated text. Set `AI_UPLOAD_LONG_RESULT=true` if you want long results uploaded as files.
- Permission denied: check `AI_ALLOWED_USER_IDS` and the sender ID reported by Feishu.
- Replying status is not shown: check whether the Feishu app has message reaction permissions, or set `AI_REPLY_STATUS_EMOJI` to an emoji type supported by your tenant.
- Images are not readable: for Feishu images, check whether the Feishu app has message resource read permission; for NGA images, check whether `events/latest_event.json` has `image_urls` and whether `attachments/nga/` contains downloaded files. Codex receives downloaded images through `--image`; if download fails, ask the agent to open the original URL from the event JSON.
- NGA images do not show inside Feishu cards: this only works in Feishu app mode, not webhook mode. Check whether the app can upload images, whether the original NGA image URL is reachable from the watcher machine, and whether `FEISHU_CARD_IMAGES` is still enabled. If upload fails, the card intentionally keeps the clickable image link.
- Feishu txt/file attachments are not readable: check the same message resource read permission. The watcher downloads files into `attachments/` and passes local paths to the agent. For reply-to-file workflows, the bot must also be allowed to read the replied message.

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
