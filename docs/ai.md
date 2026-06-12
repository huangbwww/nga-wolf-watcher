# Local AI Agent Enhancement

Local AI Agent setup, commands, workspace layout, prompts, and troubleshooting.

> Detailed reference. Start with the repository README for the quick path.

## AI Analysis Notes

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

## Optional Local AI Agent Enhancement

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
