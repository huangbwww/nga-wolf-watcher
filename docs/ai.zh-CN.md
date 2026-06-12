# 本地 AI Agent 增强

本地 AI Agent 的启用方式、命令、工作目录、Prompt 和故障排查。

> 详细参考文档。第一次使用建议先看仓库首页的快速开始。

## AI 分析功能说明

AI 功能默认关闭。默认配置下，程序不要求安装 Codex、Claude、Node、API key 或任何额外 AI 依赖。AI 关闭时，NGA 监听、飞书推送、WebSocket 命令、卡片交互、免打扰、GUI 启动和打包行为保持原有兼容行为；如果不想用 AI，直接保持关闭即可。

这部分功能有一定使用门槛：它不是内置大模型服务，而是把飞书群里的消息、NGA 新回复和本地保存的上下文转交给你电脑上的本地 AI Agent 命令执行。你需要先在本机安装并登录 Codex CLI、Claude Code CLI、CodeWhale，或自己提供 custom command。简单安装方式：

```powershell
# Codex CLI，需要本机有 Node/npm
npm install -g @openai/codex
codex

# Claude Code CLI，Windows 也可参考官方 winget/安装脚本方式
npm install -g @anthropic-ai/claude-code
claude

# CodeWhale / DeepSeek TUI，需要本机有 Node/npm
npm install -g codewhale
codewhale auth set --provider deepseek
```

不同人用 AI 分析股票会有完全不同的流程。这里提供的只是一个本地试验入口：程序拉取到狼大发言后，会把回复写入 AI 工作目录里的 `events/wolf_history.jsonl` 和 `events/latest_event.json`；同时预留 `context/positions.json`、`context/watchlist.md`、`context/notes.md` 等位置记录你的持仓、重点关注和补充笔记。我的用法是把自己的持仓截图或持仓信息直接发给 AI，让它自己整理记录；后续操作、交易习惯、接下来想看的方向，也直接在飞书群里和它聊。AI 可以结合狼大的历史发言、当前盘面、你的持仓和你的即时想法给出分析或讨论建议。

AI 分析只是工具，不是开箱即用的固定答案。实际效果取决于你给它的上下文、持仓信息、观察重点和持续反馈；回答风格、分析深度、风险偏好、常用术语等也可以在日常对话中慢慢校正，让它更贴近你自己的使用习惯。AI 输出只适合作为信息整理、风险提示和讨论参考，不构成投资建议，也不会自动下单。具体买卖仍需要你自己判断。

## 可选本地 AI Agent 增强系统

本节主要是源码/BAT 用户需要的 CLI、环境变量和工作目录细节。只使用 EXE 的用户，可以先看前面的“AI 分析功能说明”和 GUI 里的 `AI 分析` 配置区域。

启用 Codex：

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'codex'
$env:AI_CODEX_COMMAND = 'codex'
python .\nga_feishu_watch.py --ws
```

启用 Claude Code：

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'claude'
$env:AI_CLAUDE_COMMAND = 'claude'
python .\nga_feishu_watch.py --ws
```

启用 CodeWhale：

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'codewhale'
$env:AI_CODEWHALE_COMMAND = 'codewhale'
python .\nga_feishu_watch.py --ws
```

使用 custom command：

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'custom'
$env:AI_CUSTOM_COMMAND = 'python D:\agents\run_agent.py --work-dir {work_dir} --prompt {prompt_file} --output {output_file}'
python .\nga_feishu_watch.py --ws
```

custom command 支持占位符：`{work_dir}`、`{prompt_file}`、`{output_file}`、`{task_type}`、`{latest_event}`、`{history_file}`、`{session_id}`、`{image_files}`、`{file_files}`、`{permission_mode}`、`{model}`、`{reasoning_effort}`。

模型和思考强度：

- GUI 里的“默认模型”和“默认思考强度”是启动默认值，留空或 `default` 表示不指定，使用 agent 自己的默认。
- 飞书 `/setting` 卡片里的模型/思考强度是运行时覆盖，点“恢复默认模型/强度”会回到 GUI/启动默认值。
- Codex 下拉模型：`gpt-5.5`、`gpt-5.4`、`gpt-5.4-mini`、`gpt-5.3-codex`、`gpt-5.3-codex-spark`、`gpt-5.2`；思考强度：`low`、`medium`、`high`、`xhigh`。
- Claude 下拉模型：`default`、`sonnet[1m]`、`opus[1m]`、`haiku`；思考强度：`low`、`medium`、`high`、`xhigh`、`max`。
- CodeWhale 下拉模型：`deepseek-v4-flash`、`deepseek-v4-pro`，也可选 `auto` 让 CodeWhale 自动路由；思考强度：`auto`、`off`、`low`、`medium`、`high`、`max`。
- Codex 会把模型传给 `codex exec --model <model>`，把思考强度通过 Codex 配置覆盖传入。
- Claude Code 会把模型传给 `claude --model <model>`，把思考强度传给 `--effort <level>`。
- CodeWhale 会通过 `codewhale exec --output-format stream-json --auto` 后台执行。第一轮会从 stream-json 事件捕获 CodeWhale 真实保存的 session id，后续轮次用 `--resume <id>` 续同一条会话；模型传给 `--model <model>`，思考强度通过临时运行配置文件传入 `reasoning_effort`。
- custom command 只保存并暴露 `{model}`、`{reasoning_effort}`，是否生效取决于你的命令模板是否使用这些占位符。

新帖自动分析：

```powershell
$env:AI_ENABLED = 'true'
$env:AI_AUTO_ANALYZE_NEW_POST = 'true'
```

盘中定时分析，默认 A 股时间窗口：

```powershell
$env:AI_ENABLED = 'true'
$env:AI_SCHEDULE_ENABLED = 'true'
$env:AI_SCHEDULE_INTERVAL_MINUTES = '5'
$env:AI_SCHEDULE_WINDOWS = 'weekday:09:30-11:30,13:00-15:00'
```

自定义时间窗口格式：

- `weekday:09:30-11:30,13:00-15:00`：周一到周五，两个盘中窗口。
- `mon-fri:09:30-11:30`：周一到周五，一个窗口。
- `1-5:09:30-11:30,13:00-15:00`：数字星期，`1` 是周一，`7` 是周日。
- 多组日期用 `;` 拼接，例如 `1-5:09:30-11:30;6:10:00-11:00`。

飞书 `/ai` 命令：

```text
/start                  # 打开查询/打包菜单
/setting                # 打开设置卡片，控制 AI、定时分析、prompt 和权限模式
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
<非命令普通消息>   # AI 开启后会直接交给 agent
/ai ask <问题>      # 兼容写法，可不用
/ai schedule on
/ai schedule off
/ai schedule every <分钟>
/ai schedule windows weekday:09:30-11:30,13:00-15:00
/ai schedule prompt <提示词>
/ai auto prompt <提示词>
/ai prompt
/ai workdir
/ai history <N>
/ai last
```

AI 配置项：

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
AI_AUTO_ANALYSIS_PROMPT=根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。
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

`AI_WORK_DIR` 如果是相对路径，会解析到运行状态文件旁边。GUI/EXE 默认就是 `%LOCALAPPDATA%\NGA Wolf Watcher\.ai_agent_workspace`；普通 CLI 默认 `.nga_seen.json` 在当前目录，所以工作目录也在当前目录。想固定位置可以直接填绝对路径。

AI 工作目录结构：

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

Prompt 使用方式：

- 新帖自动分析和 `/ai latest` 只发送配置里的自动分析 Prompt。默认 Prompt 很短，只要求结合回复历史、持仓/观察列表和实时 A 股情况做分析。
- NGA 回复里的 `[img]`、HTML 图片和常见附件图片链接会写入 `events/latest_event.json` / `wolf_history.jsonl` 的 `image_urls` 字段；程序会尽量下载到 `attachments/nga/<post-key>/`，并把成功下载的本地图片路径写入 `image_paths`。Codex provider 会在自动分析和 `/ai latest` 时把这些图片通过 `--image <path>` 传给 agent；下载失败时，agent 仍可从事件 JSON 里看到原始图片 URL。
- 飞书普通消息会原样转发给本地 agent。通用定位和偏好放在 `context/memory.md` / `AGENTS.md`，agent 需要时自己读，不会每次都把同一段 chat prompt 注入进去。
- 飞书图片消息、富文本图片和文件附件会先下载到 `attachments/`，再把本地绝对路径交给 agent；Codex provider 会额外使用 `--image <path>` 传图。回复一条文件消息并让 agent 读取时，程序也会尝试读取被回复消息里的附件。
- 同一个 AI 工作目录下，飞书和微信发来的 AI 消息会进入同一个本地队列串行执行，避免多条消息并发抢同一条本地 agent 会话。
- `/mode` 参考 cc-connect 的权限模式。直接发送 `/mode` 会返回可点击选择卡片；Codex 支持 `default`、`auto-edit`、`full-auto`、`yolo`；Claude 支持 `default`、`acceptEdits`、`plan`、`auto`、`bypassPermissions`、`dontAsk`；CodeWhale 支持 `default`、`auto`、`yolo`。`/mode yolo` 或点击卡片按钮会持久化到 AI state，只影响后续 AI 任务，不改启动参数。
- AI 处理飞书消息时，会临时给原消息加一个表情作为“正在回复”状态，完成或报错后移除。默认表情可用 `AI_REPLY_STATUS_EMOJI` 调整；如果飞书应用没有消息表情权限，只会记录日志，不影响 AI 回复。
- 定时分析只发送配置里的定时 Prompt；为空时使用和自动分析一致的简短默认 Prompt。
- Codex 会优先使用 `codex exec resume --last` 复用 AI 工作目录下最近一条会话；如果还没有历史会话，则自动新建。CodeWhale 使用 stream-json 捕获并保存真实 session id，后续用 `--resume <id>` 续聊。Claude Code 使用稳定的 `--session-id`，custom command 可用 `{session_id}` 自行接入常驻会话。

安全说明：

- AI 输出仅用于信息整理、风险提示和观察点，不构成投资建议。
- 程序不自动下单；默认 prompt 明确禁止替用户做买卖决定。
- 不要把 Cookie、飞书密钥、账户凭证或完整私有持仓写入 prompt、日志或飞书消息。
- 可用 `AI_ALLOWED_USER_IDS` 限制 `/ai on/off/ask/latest/schedule` 的飞书发送人。

故障排查：

- 找不到 `codex`、`claude` 或 `codewhale`：先在本机安装对应工具，或把 `AI_CODEX_COMMAND` / `AI_CLAUDE_COMMAND` / `AI_CODEWHALE_COMMAND` 设置为完整命令。
- 任务超时：调大 `AI_TIMEOUT`，或减少 prompt / context 内容。
- 输出为空：查看 `logs/ai_agent.log`；如果 output file 缺失，程序会用 stdout 兜底。
- 飞书消息过长：默认直接截断成文本。需要长结果文件时再设置 `AI_UPLOAD_LONG_RESULT=true`。
- 权限不足：检查 `AI_ALLOWED_USER_IDS` 和飞书 sender id。
- 正在回复状态不显示：检查飞书应用是否开启消息表情 Reaction 相关权限，或把 `AI_REPLY_STATUS_EMOJI` 改成当前租户支持的表情类型。
- 图片读不了：如果是飞书图片，检查飞书应用是否开启消息资源读取权限；如果是 NGA 图片，检查 `events/latest_event.json` 是否有 `image_urls`，以及 `attachments/nga/` 下是否下载成功。Codex 会通过 `--image` 接收已下载图片，失败时可让 agent 打开事件里的原图 URL。
- NGA 图片没有直接显示在飞书卡片里：这个能力只支持飞书应用模式，不支持 webhook 模式。检查应用是否有上传图片权限、运行机器是否能访问原始 NGA 图片 URL，以及 `FEISHU_CARD_IMAGES` 是否仍然开启。上传失败时卡片会保留可点击图片链接。
- 微信不能主动推送：先用目标微信给机器人发一条消息，确认 `WECHAT_BOT_TARGET_USER_ID` 与缓存到的用户 ID 一致。
- 微信图片/文件读不了：确认 `WECHAT_BOT_CDN_BASE_URL` 正确；加密附件下载和微信文件发送需要本机可用 `pycryptodome`。如果文件上传不可用，打包 txt 会自动回退为文本分段发送。
- 飞书 txt/file 附件读不了：同样检查消息资源读取权限；程序会把附件下载到 `attachments/` 并把本地路径给 agent。若是“回复某个文件消息”，还需要机器人能读取被回复的那条消息。

脚本会把已推送回复 id、已处理命令 id 和免打扰暂存回复存在 `.nga_seen.json`。EXE GUI 默认会把它放在 `%LOCALAPPDATA%\NGA Wolf Watcher\`，和 `config.json` 同目录。它和 config 分开是因为它属于运行状态，会频繁写入；删除它相当于重置已读/已处理历史。
