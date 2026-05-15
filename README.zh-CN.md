# NGA Wolf Watcher

[English](README.md) | 中文说明

监听指定 NGA 用户的回复，推送新回复到飞书，并支持通过飞书卡片查询历史或打包成 `.txt` 文件。

## 功能提示

- 持续监听：点击 `启动监听` 后，程序会持续查询配置里的 `默认用户 ID` 的 NGA 新回复，并把新发现的回复推送到目标飞书群。
- 手动查询：在飞书群里可以使用命令或卡片按钮，查询用户回复、查询帖子回复，或把结果打包成 `.txt` 文件。
- 免打扰时段：可以设置一个连续的每周免打扰区间，例如周五 18:00 到周一 08:00，期间的新回复可以选择忽略，或在免打扰结束后汇总推送。
- 可选本地 AI Agent 增强：默认关闭。开启后可保存狼大发言、调用本机 Codex / Claude Code / custom 命令、在飞书群响应 `/ai` 命令，并支持盘中定时分析。

### AI 分析功能说明

AI 功能默认关闭。默认配置下，程序不要求安装 Codex、Claude、Node、API key 或任何额外 AI 依赖。AI 关闭时，NGA 监听、飞书推送、WebSocket 命令、卡片交互、免打扰、GUI 启动和打包行为保持原有兼容行为；如果不想用 AI，直接保持关闭即可。

这部分功能有一定使用门槛：它不是内置大模型服务，而是把飞书群里的消息、NGA 新回复和本地保存的上下文转交给你电脑上的本地 AI Agent 命令执行。你需要先在本机安装并登录 Codex CLI、Claude Code CLI，或自己提供 custom command。简单安装方式：

```powershell
# Codex CLI，需要本机有 Node/npm
npm install -g @openai/codex
codex

# Claude Code CLI，Windows 也可参考官方 winget/安装脚本方式
npm install -g @anthropic-ai/claude-code
claude
```

不同人用 AI 分析股票会有完全不同的流程。这里提供的只是一个本地试验入口：程序拉取到狼大发言后，会把回复写入 AI 工作目录里的 `events/wolf_history.jsonl` 和 `events/latest_event.json`；同时预留 `context/positions.json`、`context/watchlist.md`、`context/notes.md` 等位置记录你的持仓、重点关注和补充笔记。我的用法是把自己的持仓截图或持仓信息直接发给 AI，让它自己整理记录；后续操作、交易习惯、接下来想看的方向，也直接在飞书群里和它聊。AI 可以结合狼大的历史发言、当前盘面、你的持仓和你的即时想法给出分析或讨论建议。

AI 分析只是工具，不是开箱即用的固定答案。实际效果取决于你给它的上下文、持仓信息、观察重点和持续反馈；回答风格、分析深度、风险偏好、常用术语等也可以在日常对话中慢慢校正，让它更贴近你自己的使用习惯。AI 输出只适合作为信息整理、风险提示和讨论参考，不构成投资建议，也不会自动下单。具体买卖仍需要你自己判断。

## 反馈和建议

如果遇到 bug 或使用问题，欢迎提 [Issue](https://github.com/huangbwww/nga-wolf-watcher/issues)。

其他功能建议也可以提，NGA 相关、股票相关，或者类似的个人工具需求都可以。我会定期看 Issue，有空就更新。

## 直接使用 EXE

这条路径不需要改代码，也不需要运行 Python 命令。

1. 从 [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest) 下载 `NGA-Wolf-Watcher.exe`。
2. 打开 [飞书开放平台](https://open.feishu.cn/page/openclaw)，创建一个机器人应用，复制应用的 `App ID` 和 `App Secret`。
3. 把机器人加入目标飞书群。
4. 如果希望不 @ 机器人也能直接使用 `/start` 等命令，需要添加 `im:message.group_msg` 权限。
5. 打开 `NGA-Wolf-Watcher.exe`，填写 `Feishu App ID` 和 `Feishu App Secret`，点击 `查询群组`。
6. 把目标群的 `chat_id` 复制到 `Receive ID`。
7. 登录 `https://bbs.nga.cn/`，从浏览器请求里复制 `Cookie`，填入 `NGA Cookie`。
8. 点击 `保存配置`，再点击 `启动监听`。

第一次启动前建议保持“首次启动前自动初始化已读”开启。它会先把当前抓到的 NGA 回复标记为已读，避免历史回复一次性刷到飞书。

GUI 会把本地密钥保存到 `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`。运行状态默认保存在同目录的 `.nga_seen.json`。不要外发这些文件。

### 免打扰时段

在 `运行设置` 里开启 `免打扰时段` 后，可以设置开始星期/时间和结束星期/时间，例如 `周五 18:00 -> 周一 08:00`。时间使用小时/分钟下拉选择，不需要手动输入 `HH:MM`。免打扰时段只影响自动持续监听的新回复推送，不影响飞书手动查询、打包、查询群组和发送测试。

免打扰期间的新回复有两种处理方式：

- `忽略新回复`：免打扰期间仍会监听并标记已读，免打扰结束后不会补发。
- `暂存并在免打扰结束后汇总推送`：免打扰期间的新回复会先暂存，免打扰结束后发送一张汇总卡片。

### 如何复制 NGA Cookie

也可以参考 [Issue #1](https://github.com/huangbwww/nga-wolf-watcher/issues/1) 里的具体示例。

1. 用浏览器打开 `https://bbs.nga.cn/`，登录能看到目标内容的 NGA 账号。
2. 打开要监听的 NGA 页面，或者登录后任意一个 `bbs.nga.cn` 下的页面。
3. 按 `F12` 打开开发者工具，切到 `网络` / `Network` 面板。
4. 保持开发者工具打开，刷新当前页面。
5. 在请求列表里点开一个发往 `bbs.nga.cn` 的请求，例如 `thread.php`、`read.php`，或其他状态码为 `200` 的请求。
6. 在 `标头` / `Headers` 里找到 `请求标头` / `Request Headers`，复制其中完整的 `Cookie` 值。
7. 把复制出来的整段 `Cookie` 填到界面的 `NGA Cookie`，再点击 `保存配置`。

Cookie 相当于临时登录凭据，不要发到 issue、聊天、截图、日志或 release 文件里。如果 NGA 拉取返回空数据或 JSON 解析错误，通常是 Cookie 失效、复制不完整、域名不对，重新从已登录的 `bbs.nga.cn` 请求里复制一次。

## 飞书群命令

在目标飞书群里提及机器人，或使用卡片按钮：

```text
/start
/setting
/history_r 150058 5
/pack_r 150058 5
/history_t 45974302 10
/pack_t 45974302 10
```

默认值：

- `150058` = wolf uid
- `45974302` = wolf thread id
- 省略 `<count>` 时，用户回复类命令默认 `5` 条，帖子回复类命令默认 `10` 条。

命令含义：

- `/history_r <uid|0> <count>` 按 uid 拉取最近回复并发送卡片。
- `/pack_r <uid|0> <count>` 按 uid 拉取最近回复并发送 `.txt` 文件。
- `/history_t <tid> <count>` 拉取帖子最新回复并发送卡片。
- `/pack_t <tid> <count>` 拉取帖子最新回复并发送 `.txt` 文件。

`/pack_r 45974302 10` 会作为兼容别名处理，相当于打包默认 wolf 帖。

### 新回复 @ 提醒

如果希望收到新大佬回复或免打扰汇总时机器人在卡片里 @ 自己，在飞书群发送 `/setting`，点击设置卡片里的 `开启并@我`。程序会保存点击人的飞书 sender id，之后自动新回复卡片和免打扰汇总卡片都会带上这个 @；点击 `关闭@提醒` 后两类卡片都不再 @。

这是全局开关，不区分新回复和汇总。@ 信息直接放在原卡片里，不会额外发送一条消息。

## 高级用法

如果你只是使用 EXE，后面的内容可以不用看。

### 使用 BAT

这种方式需要本机有 Python 环境。

复制 `start_local.example.bat` 为 `start_local.bat`，填入空着的 `NGA_COOKIE` 和飞书配置，然后运行。

BAT 会自动安装 `lark-oapi`。第一次运行时，如果没有 `.nga_seen.json`，它会先执行 `--mark-seen`，避免历史回复刷屏。

### 直接运行源码

安装依赖：

```powershell
cd D:\nga-wolf
python -m pip install lark-oapi customtkinter
```

设置必填环境变量：

```powershell
$env:NGA_COOKIE = 'ngaPassportUid=...; ngaPassportCid=...; ...'
$env:FEISHU_APP_ID = 'cli_xxx'
$env:FEISHU_APP_SECRET = 'xxx'
$env:FEISHU_RECEIVE_ID = 'oc_xxx'
$env:FEISHU_ID_TYPE = 'chat_id'
```

可选默认值：

```powershell
$env:NGA_DEFAULT_AUTHOR_ID = '150058'
$env:NGA_DEFAULT_TID = '45974302'
$env:NGA_INTERVAL = '60'
$env:NGA_JITTER = '20'
$env:NGA_RETRIES = '10'
$env:NGA_PAGE_DELAY = '2.0'
$env:NGA_UNAVAILABLE_RETRIES = '3'
```

可选 AI Agent 默认值；除非主动开启，否则不会启用：

```powershell
$env:AI_ENABLED = 'false'
$env:AI_PROVIDER = 'codex'
$env:AI_WORK_DIR = '.ai_agent_workspace'
$env:AI_AUTO_ANALYZE_NEW_POST = 'false'
$env:AI_SCHEDULE_ENABLED = 'false'
$env:AI_PERMISSION_MODE = 'default'
```

第一次运行前初始化已读，避免推送旧回复：

```powershell
python .\nga_feishu_watch.py --mark-seen
```

使用 WebSocket 卡片回调和周期性 NGA 监听：

```powershell
python .\nga_feishu_watch.py --ws
```

从源码启动 GUI：

```powershell
python .\nga_wolf_gui.py
```

只测试消息/卡片回调，不启动周期性 NGA 监听：

```powershell
python .\nga_feishu_watch.py --ws --ws-no-watch
```

查询机器人可见群组：

```powershell
python .\nga_feishu_watch.py --list-feishu-chats
```

发送一条飞书测试消息：

```powershell
python .\nga_feishu_watch.py --send-test
```

### 常用检查

测试 NGA 解析：

```powershell
python .\nga_feishu_watch.py --once --dry-run
```

只跑一轮轮询：

```powershell
python .\nga_feishu_watch.py --once
```

调整轮询和重试：

```powershell
python .\nga_feishu_watch.py --interval 60 --jitter 20 --retries 10 --retry-delay 2
```

非 WebSocket 模式下禁用命令轮询：

```powershell
python .\nga_feishu_watch.py --disable-commands
```

新回复卡片 @ 提醒也可以用环境变量或 CLI 设置初始默认值；更推荐在飞书 `/setting` 卡片里点击 `开启并@我`，这样不需要手动查 user id。

```powershell
$env:FEISHU_MENTION_ENABLED="true"
$env:FEISHU_MENTION_USER_ID="ou_xxx"
python .\nga_feishu_watch.py --feishu-mention-enabled --feishu-mention-user-id ou_xxx
```

### 可选本地 AI Agent 增强系统

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

使用 custom command：

```powershell
$env:AI_ENABLED = 'true'
$env:AI_PROVIDER = 'custom'
$env:AI_CUSTOM_COMMAND = 'python D:\agents\run_agent.py --work-dir {work_dir} --prompt {prompt_file} --output {output_file}'
python .\nga_feishu_watch.py --ws
```

custom command 支持占位符：`{work_dir}`、`{prompt_file}`、`{output_file}`、`{task_type}`、`{latest_event}`、`{history_file}`、`{session_id}`、`{image_files}`、`{file_files}`、`{permission_mode}`。

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
AI_ENABLED=false
AI_PROVIDER=codex
AI_WORK_DIR=.ai_agent_workspace
AI_AUTO_ANALYZE_NEW_POST=false
AI_AUTO_ANALYSIS_PROMPT=根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。
AI_PROMPT_FILE=
AI_TIMEOUT=300
AI_CODEX_COMMAND=codex
AI_CLAUDE_COMMAND=claude
AI_CUSTOM_COMMAND=
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
- 同一个 AI 工作目录和同一个飞书群的 AI 消息会串行排队执行，避免多条消息并发抢同一条本地 agent 会话。
- `/mode` 参考 cc-connect 的权限模式。直接发送 `/mode` 会返回可点击选择卡片；Codex 支持 `default`、`auto-edit`、`full-auto`、`yolo`；Claude 支持 `default`、`acceptEdits`、`plan`、`auto`、`bypassPermissions`、`dontAsk`。`/mode yolo` 或点击卡片按钮会持久化到 AI state，只影响后续 AI 任务，不改启动参数。
- AI 处理飞书消息时，会临时给原消息加一个表情作为“正在回复”状态，完成或报错后移除。默认表情可用 `AI_REPLY_STATUS_EMOJI` 调整；如果飞书应用没有消息表情权限，只会记录日志，不影响 AI 回复。
- 定时分析只发送配置里的定时 Prompt；为空时使用和自动分析一致的简短默认 Prompt。
- Codex 会优先使用 `codex exec resume --last` 复用 AI 工作目录下最近一条会话；如果还没有历史会话，则自动新建。Claude Code 使用稳定的 `--session-id`，custom command 可用 `{session_id}` 自行接入常驻会话。

安全说明：

- AI 输出仅用于信息整理、风险提示和观察点，不构成投资建议。
- 程序不自动下单；默认 prompt 明确禁止替用户做买卖决定。
- 不要把 Cookie、飞书密钥、账户凭证或完整私有持仓写入 prompt、日志或飞书消息。
- 可用 `AI_ALLOWED_USER_IDS` 限制 `/ai on/off/ask/latest/schedule` 的飞书发送人。

故障排查：

- 找不到 `codex` 或 `claude`：先在本机安装对应工具，或把 `AI_CODEX_COMMAND` / `AI_CLAUDE_COMMAND` 设置为完整命令。
- 任务超时：调大 `AI_TIMEOUT`，或减少 prompt / context 内容。
- 输出为空：查看 `logs/ai_agent.log`；如果 output file 缺失，程序会用 stdout 兜底。
- 飞书消息过长：默认直接截断成文本。需要长结果文件时再设置 `AI_UPLOAD_LONG_RESULT=true`。
- 权限不足：检查 `AI_ALLOWED_USER_IDS` 和飞书 sender id。
- 正在回复状态不显示：检查飞书应用是否开启消息表情 Reaction 相关权限，或把 `AI_REPLY_STATUS_EMOJI` 改成当前租户支持的表情类型。
- 图片读不了：如果是飞书图片，检查飞书应用是否开启消息资源读取权限；如果是 NGA 图片，检查 `events/latest_event.json` 是否有 `image_urls`，以及 `attachments/nga/` 下是否下载成功。Codex 会通过 `--image` 接收已下载图片，失败时可让 agent 打开事件里的原图 URL。
- 飞书 txt/file 附件读不了：同样检查消息资源读取权限；程序会把附件下载到 `attachments/` 并把本地路径给 agent。若是“回复某个文件消息”，还需要机器人能读取被回复的那条消息。

脚本会把已推送回复 id、已处理命令 id 和免打扰暂存回复存在 `.nga_seen.json`。EXE GUI 默认会把它放在 `%LOCALAPPDATA%\NGA Wolf Watcher\`，和 `config.json` 同目录。它和 config 分开是因为它属于运行状态，会频繁写入；删除它相当于重置已读/已处理历史。

### 打包 EXE

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name NGA-Wolf-Watcher --icon .\assets\app_icon.ico --add-data ".\assets\app_icon.ico;assets" --add-data ".\assets\app_icon.png;assets" --collect-all lark_oapi --collect-all customtkinter .\nga_wolf_gui.py
```

输出文件是 `dist\NGA-Wolf-Watcher.exe`。

## 旧版自定义机器人 Webhook

Webhook 模式仍然保留：

```powershell
$env:FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/...'
$env:FEISHU_SECRET = 'optional signing secret'
python .\nga_feishu_watch.py
```

## 免责声明

本项目仅供个人技术研究和学习使用，使用者需自行承担使用风险。

使用者应自行确认并遵守 NGA、飞书、所在组织以及当地法律法规和平台规则。自动化访问、消息转发、Cookie 使用、频繁轮询或机器人交互可能带来账号限制、封号、数据泄露、服务中断或其他不确定后果。项目作者不作任何保证，也不对因使用、修改、分发或部署本项目造成的损失、纠纷、账号处罚、法律后果或第三方索赔承担责任。
