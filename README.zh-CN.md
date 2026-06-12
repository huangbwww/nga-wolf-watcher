# NGA Wolf Watcher

[English](README.md) | 中文说明

监听指定 NGA 用户的回复，推送新回复到飞书、微信、钉钉或邮箱，并支持通过群内命令/飞书卡片查询历史或打包成 `.txt` 文件。

## 功能提示

- 持续监听：点击 `启动监听` 后，程序会按监听规则检查用户主页回复，或在指定帖子里筛选目标作者的新回复，并推送到选定的飞书群、微信账号、钉钉用户或邮箱。
- 手动查询：在飞书群、微信或钉钉里可以使用命令；飞书还支持卡片按钮，查询用户回复、查询帖子回复，或把结果打包成 `.txt` 文件。
- 免打扰时段：可以设置一个连续的每周免打扰区间，例如周五 18:00 到周一 08:00，期间的新回复可以选择忽略，或在免打扰结束后汇总推送。
- 可选本地 AI Agent 增强：默认关闭。开启后可保存狼大发言、调用本机 Codex / Claude Code / CodeWhale / custom 命令、在飞书群响应 `/ai` 命令，并支持盘中定时分析。

### AI 分析功能说明

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

## 反馈和建议

如果遇到 bug 或使用问题，欢迎提 [Issue](https://github.com/huangbwww/nga-wolf-watcher/issues)。

其他功能建议也可以提，NGA 相关、股票相关，或者类似的个人工具需求都可以。我会定期看 Issue，有空就更新。

## 直接使用 EXE

这条路径不需要改代码，也不需要运行 Python 命令。

1. 从 [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest) 下载 `NGA-Wolf-Watcher.exe`。从 1.2.x 开始，Release 只发布新版配置客户端。
2. 打开 [飞书开放平台](https://open.feishu.cn/page/openclaw)，创建一个机器人应用，复制应用的 `App ID` 和 `App Secret`。
3. 把机器人加入目标飞书群。
4. 如果希望不 @ 机器人也能直接使用 `/start` 等命令，需要添加 `im:message.group_msg` 权限。
5. 打开客户端，在 `消息通道` 里新增一个飞书配置组，填写 `App ID` 和 `App Secret`，在弹窗里点击 `查询群组并保存`。
6. 在 `目标` 里添加常用用户 ID 和帖子 ID，再到 `规则` / `监听规则` 里新增监听规则：选择用户主页监听或固定帖子筛选用户，并直接勾选要推送到的飞书群或微信账号。
7. 登录 `https://bbs.nga.cn/`，从浏览器请求里复制 `Cookie`，填入 `NGA Cookie`。
8. 点击 `保存配置`，再点击 `启动监听`。

第一次启动前建议保持“首次启动前自动初始化已读”开启。它会先把当前抓到的 NGA 回复标记为已读，避免历史回复一次性刷到飞书。

GUI 会把本地密钥保存到 `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`。运行状态默认保存在同目录的 `.nga_seen.json`。不要外发这些文件。

### 消息通道、目标和监听规则

新版推荐客户端把配置拆成几个更清晰的区域，旧配置仍会自动兼容：

- `消息通道配置组`：只保存机器人账号。飞书配置组保存 App ID / App Secret，并且群组查询结果只缓存到这一组里；微信配置组保存 ilink Token、目标用户和账号标识；钉钉配置组保存 Stream 机器人凭证和主动推送目标用户；邮箱配置组保存用于发信的 SMTP 配置；WxPusher 配置组保存极简推送使用的 SPT。
- `目标` / `NGA 资源库`：保存可被监听和手动查询的用户 ID、帖子 ID，飞书卡片和微信短命令会从这里取默认可选项。
- `监听规则`：选择监听方式（用户主页监听，或固定帖子内筛选用户），再直接选择发送位置。飞书发送位置由“飞书配置组 + 群组”组成，微信发送位置选择对应微信配置组，钉钉发送位置选择对应钉钉配置组，邮箱发送位置由“邮箱发信配置组 + 收件邮箱地址”组成，WxPusher 发送位置选择对应 SPT 配置组。同一条规则可以同时推送到多个目标。

这样一个飞书群、一个微信账号、一个钉钉机器人、多个机器人、多个 NGA 用户/帖子不再混在同一个表单里。手动查询不受监听规则限制：飞书、微信和钉钉里的 `/history_r`、`/pack_r`、`/history_t`、`/pack_t` 都可以查询资源库里的所有用户和帖子；短命令默认使用当前入口对应的默认用户和默认帖子。

AI 配置仍然是全局一份，飞书/微信/钉钉/邮箱/WxPusher 目标会使用同一个 AI 工作目录和同一个本地 agent 队列。自动新帖分析会跟随触发的监听规则发到对应发送位置；定时分析只跑一次，然后复制发送到勾选的定时分析目标。

微信通道使用 cc-connect 同类的个人微信 ilink 网关，不是普通微信官方机器人，也不会控制桌面微信。首次使用时，需要先让目标微信账号给机器人发一条消息，程序收到消息后会缓存 `context_token`，之后才能主动推送 NGA 新回复。微信没有飞书卡片，`/setting` 会返回文本菜单和可复制命令。

微信通道需要这些配置：

```text
NGA_BOT_CHANNEL=wechat
WECHAT_BOT_TOKEN=<ilink Bearer token>
WECHAT_BOT_BASE_URL=https://ilinkai.weixin.qq.com
WECHAT_BOT_CDN_BASE_URL=https://novac2c.cdn.weixin.qq.com/c2c
WECHAT_BOT_TARGET_USER_ID=<xxx@im.wechat>
WECHAT_BOT_ALLOWED_USER_IDS=<留空表示不限制，或逗号分隔用户 ID>
WECHAT_BOT_POLL_TIMEOUT_MS=35000
WECHAT_BOT_ACCOUNT_ID=default
```

微信个人号通道可能受 ilink 网关、登录状态、接口变化和账号风控影响；请自行评估平台规则和账号风险。

钉钉通道使用官方 DingTalk Stream 机器人连接，不是桌面钉钉自动化。源码运行时如需接收钉钉消息，需要先安装可选依赖：

```powershell
python -m pip install dingtalk-stream
```

钉钉通道需要这些配置：

```text
NGA_BOT_CHANNEL=dingtalk
DINGTALK_CLIENT_ID=<钉钉机器人 Client ID / App Key>
DINGTALK_CLIENT_SECRET=<钉钉机器人 Client Secret / App Secret>
DINGTALK_ROBOT_CODE=<主动推送用 robotCode，可为空则使用 Client ID>
DINGTALK_TARGET_USER_IDS=<主动推送目标用户 ID，多个用逗号分隔>
DINGTALK_ALLOWED_USER_IDS=<留空表示不限制，或逗号分隔用户 ID>
DINGTALK_ACCOUNT_ID=default
```

钉钉里给机器人发 `/start`、`/setting`、`/history_r`、`/pack_r`、普通 AI 对话消息等，会通过 Stream 会话直接回复；NGA 新回复、免打扰汇总和定时 AI 分析属于主动推送，需要填写 `DINGTALK_TARGET_USER_IDS`，并确保钉钉应用有对应机器人主动发送权限。

EXE 推荐配置步骤：

1. 在钉钉开放平台创建应用并启用机器人/Stream 模式，把应用的 `Client ID` / `App Key` 和 `Client Secret` / `App Secret` 填到钉钉配置组。
2. `Robot Code` 可以先留空；主动推送接口会默认使用 `Client ID`。如果你的应用后台单独显示了 robotCode，再填入该值。
3. 先保存配置并启动监听一次，在钉钉里给机器人发送 `/start` 或任意一条消息。
4. 回到 EXE 的钉钉配置组，点击 `获取最近用户 ID`。程序会读取刚才收到的钉钉消息，并把发送人的用户 ID 填到 `目标用户 ID`。
5. 再次保存配置，在 `发送目标` / `监听规则` 里选择这个钉钉配置组；之后自动新回复、免打扰汇总和定时 AI 分析就能主动推送到该用户。多个用户 ID 可以用逗号分隔。

钉钉目前使用 Markdown 卡片和文本菜单：`/start`、`/setting` 会返回卡片样式菜单，直接回复 `1` 到 `8`、`hr10`、`u1`、`t1`、`a1/a0` 等短命令即可操作。钉钉的临时 Markdown 卡片不能像飞书卡片那样原地覆盖更新；AI 生成中会先发一张“AI 正在生成”，结果出来后会尝试更新，若钉钉接口要求 `cardTemplateId` 导致更新失败，则自动补发一张新的 `AI 回复` 卡片。要做真正可点击、可覆盖更新的钉钉互动卡片，需要先在钉钉卡片搭建器创建模板并提供 `cardTemplateId`。

GUI 里可以直接点击微信配置卡片的 `扫码绑定`。程序会向 ilink 网关申请二维码，打开二维码链接并后台等待手机确认；确认成功后会自动回填 `WECHAT_BOT_TOKEN`、`WECHAT_BOT_TARGET_USER_ID`、`WECHAT_BOT_ALLOWED_USER_IDS` 和 `WECHAT_BOT_ACCOUNT_ID`。回填后点击 `保存配置` 再启动监听。

微信没有飞书卡片按钮，但提供文本快捷菜单：

- 发送 `/start` 后，可以直接回 `1`、`2`、`3`、`4`、`5` 执行常用查询、打包和设置。
- 发送 `/setting` 后，可以直接回 `1` 到 `8` 控制 AI、自动分析、定时分析和返回主菜单。
- 短命令也可直接使用：`hr10`/`hr 10`、`pr20`/`pr 20`、`ht10`/`ht 10`、`pt50`/`pt 50`、`s`、`st`、`a1/a0`、`n1/n0`、`q1/q0`、`b`。

Email SMTP 通道需要这些配置：

```text
NGA_BOT_CHANNEL=email
EMAIL_SMTP_HOST=smtp.gmail.com
EMAIL_SMTP_PORT=587
EMAIL_SMTP_SECURITY=starttls
EMAIL_USERNAME=<发件邮箱>
EMAIL_PASSWORD=<SMTP 密码、App Password 或授权码>
EMAIL_FROM=<发件邮箱>
EMAIL_FROM_NAME=NGA Wolf Watcher
EMAIL_TO=<收件邮箱>
```

GUI 里推荐优先使用邮箱类型模板。163、126、QQ、Gmail、Outlook / Microsoft 365 会自动带出 SMTP 服务器、端口和加密方式；只有选择“自定义邮箱”时才需要手动填写这些底层参数。模板只是发信配置，收信地址仍然要在监听规则的发送目标里填写。

发件邮箱可以是任何支持标准 SMTP 认证的邮箱，例如 Gmail、Outlook、QQ 邮箱、163 邮箱或企业邮箱。建议注册一个小号作为发信机器人，避免把私人主邮箱授权码放进本地配置。大多数个人邮箱不能直接使用登录密码发 SMTP，需要先在邮箱网页设置里开启 `POP3/SMTP/IMAP` 或类似的 SMTP 服务，并生成“授权码”“客户端授权码”或“应用专用密码”：163/126/QQ 邮箱通常填授权码，Gmail 通常填 Google App Password 且账号需要先开启两步验证。

收件邮箱没有特殊限制，填任意可收信地址即可。Email 通道只负责出站推送：可以接收新回复、免打扰汇总、打包 `.txt` 和 AI 分析结果，但不能接收聊天命令，也不会登录收件邮箱读取回复。

WxPusher 通道需要这些配置：

```text
NGA_BOT_CHANNEL=wxpusher
WXPUSHER_SPTS=<SPT_xxx>
WXPUSHER_CONTENT_TYPE=markdown
```

EXE 推荐配置步骤：

1. 安装或打开 WxPusher 客户端，在客户端里复制 `SPT`。
2. 在 EXE 里把消息通道切换到 `WxPusher`，新增 WxPusher 配置组，填写 `SPT`。
3. 在 `监听规则` 里新增发送目标，选择这个 WxPusher 配置组即可。
4. 长时间启动监听前，先对这个发送目标点一次 `发送测试`。

WxPusher 在本项目里是纯出站推送通道：可以接收 NGA 新回复、免打扰汇总、打包文本内容和 AI 分析结果，但不支持从 WxPusher 里发送 `/start`、`/setting`、手动查询命令或 AI 聊天输入。

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

## 群内命令

在目标飞书群里提及机器人，或在微信通道里直接给机器人发消息：

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

- `/history_r <uid|0> <count>` 按 uid 拉取最近回复并发送到当前通道。
- `/pack_r <uid|0> <count|Nd>` 按 uid 拉取最近回复并发送打包内容；`1d` 表示今天自然日，`3d` 表示今天加前两个自然日。飞书应用模式会发 `.txt` 文件，微信通道也会优先通过 iLink 媒体上传发送真正的 `.txt` 文件，上传不可用时回退为文本分段发送。
- `/history_t <tid> <count>` 拉取帖子最新回复并发送到当前通道。
- `/pack_t <tid> <count|Nd>` 拉取帖子最新回复并发送打包内容；`Nd` 按自然日计算，且只对打包命令生效。

`NGA_AUTHOR_IDS` 用于自动监听多个用户回复，`NGA_PRESET_TIDS` 只作为手动查询/打包的帖子预设，不会自动监听帖子。两者都支持逗号或换行分隔，格式可以是 `id` 或 `id=备注`。微信命令也可以用预设编号，例如 `/history_r u1 20`、`/pack_t t1 50`；飞书卡片里可以从预设下拉选择，也可以手动输入 ID。

### 监听模式

默认监听模式是 `author`，也就是旧版行为：直接拉取目标用户主页回复。新版本额外支持 `thread_author`：拉取指定帖子的最新回复，再按作者 ID 过滤。这适合遇到 NGA 用户主页经常 503、权限不足或冲水导致不可用时，改从固定帖子里筛选目标用户的新回复。

```powershell
$env:NGA_WATCH_MODE = 'thread_author'   # author | thread_author | both
$env:NGA_THREAD_AUTHOR_WATCHES = '45974302:150058=wolf|receive_id=oc_xxx'
$env:NGA_THREAD_WATCH_TAIL_COUNT = '20'
$env:NGA_THREAD_WATCH_INTERVAL = '10'
```

`NGA_THREAD_AUTHOR_WATCHES` 每行一条，格式如下：

```text
tid:uid=备注
tid:uid=备注|receive_id=oc_xxx
tid:uid=备注|app_id=cli_xxx|app_secret=xxx|receive_id=oc_xxx|id_type=chat_id
tid:uid1,uid2=备注
```

- 只写 `tid:uid=备注` 时，使用主飞书机器人和主 Receive ID。
- 追加 `receive_id=oc_xxx` 时，复用主飞书机器人，但把这个“帖子 + 作者”组合推送到另一个群。
- 追加 `app_id/app_secret/receive_id` 时，这个组合使用单独的飞书机器人。
- `both` 会同时启用旧的用户主页监听和新的帖内作者监听；同一条回复如果两边都命中，会按原始回复去重，避免重复推送。
- 如果使用新版推荐客户端的 `监听规则`，可以在新增规则时一次勾选多个用户和多个帖子，也可以直接选择多个飞书群、微信用户、钉钉用户或邮箱收件人；用户和帖子同时多选时，客户端会按“每个帖子监听每个用户”的方式展开，保存成多条兼容的底层监听规则。

帖内作者监听默认每 10 秒扫描指定作者在帖子里的最新回复，优先请求 `read.php?tid=...&authorid=...`，适合更短间隔、小窗口地盯固定帖子；用户主页监听仍按普通 `NGA_INTERVAL` 执行。AI 历史会按作者 UID 合并，例如 `45974302:150058` 和 `150058=wolf` 都写入同一个 `events/by_source/author_150058.jsonl`，同时事件里保留帖子标题和监听规则来源。

如果要确认实际访问的 NGA URL，可以临时设置 `NGA_LOG_REQUEST_URLS=true` 后启动监听；日志里会打印帖内作者请求的 `read.php?tid=...&authorid=...` URL。该开关只用于排查问题，避免长期运行时刷屏。

`/pack_r 45974302 10` 会作为兼容别名处理，相当于打包默认 wolf 帖。

### 新回复 @ 提醒

如果希望收到新大佬回复或免打扰汇总时机器人在卡片里 @ 自己：

1. 在飞书群里发送 `/setting` 打开设置卡片。
2. 点击设置卡片里的 `开启并@我`。
3. 程序会自动保存点击人的飞书 sender id，不需要手动查 user id。
4. 之后自动新回复卡片和免打扰汇总卡片顶部都会带上这个 @。
5. 需要关闭时，再进 `/setting` 点击 `关闭@提醒`。

这是一个全局开关，不区分新回复和汇总。@ 信息直接放在原卡片里，不会额外发送一条消息。开启或关闭后会持久化到运行状态文件，重启监听后仍然生效。

## 高级用法

如果你只是使用 EXE，后面的内容可以不用看。

### 使用 BAT

这种方式需要本机有 Python 环境。

复制 `start_local.example.bat` 为 `start_local.bat`，填入空着的 `NGA_COOKIE` 和飞书配置，然后运行。

BAT 会自动安装 `lark-oapi`。第一次运行时，如果没有 `.nga_seen.json`，它会先执行 `--mark-seen`，避免历史回复刷屏。

### Linux 一行安装

Linux 服务器可以直接安装为 `ngawolf` 命令，不需要克隆源码：

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo bash
```

安装脚本会把程序放到 `/opt/ngawolf`，把配置放到 `/etc/ngawolf/config.json`，把运行状态放到 `/var/lib/ngawolf`，并生成 `/usr/local/bin/ngawolf`。首次配置会进入终端 TUI 向导；飞书模式下输入 App ID / Secret 后会自动查询机器人可见群组，可以用上下键移动、空格勾选、回车确认；微信扫码绑定会同时打印终端二维码和原始链接。如果终端 TUI 依赖不可用，CLI 会自动退回旧的数字提示：

```bash
sudo ngawolf init
sudo ngawolf check
sudo ngawolf mark-seen
sudo ngawolf test-send
```

前台运行：

```bash
sudo ngawolf run
```

如果服务器使用 systemd，安装脚本会写入 `ngawolf.service`。配置和初始化已读确认无误后启动服务：

```bash
sudo systemctl enable --now ngawolf
sudo systemctl status ngawolf
```

也可以直接使用 CLI 包装命令管理后台服务和日志：

```bash
sudo ngawolf start
sudo ngawolf status
sudo ngawolf logs -f
sudo ngawolf restart
sudo ngawolf stop
```

安装版日志默认写到 `/var/log/ngawolf/watcher.log`。如果系统没有 systemd，`ngawolf start` 会退回到本地后台进程，并把 PID 写到 `/var/lib/ngawolf/watcher.pid`。

之后需要修改配置：

```bash
sudo ngawolf config
sudo systemctl restart ngawolf
```

如需安装指定版本或从本地目录调试安装，可以设置环境变量：

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo NGAWOLF_VERSION=v1.2.3 bash
sudo NGAWOLF_SOURCE_DIR=/path/to/nga-wolf bash tools/install-linux.sh
```

### 直接运行源码

安装依赖：

```powershell
cd D:\nga-wolf
python -m pip install lark-oapi customtkinter questionary Pillow qrcode
```

Linux 服务器推荐使用交互式 CLI 配置，不需要启动桌面 GUI 或 Web 管理台。飞书模式会自动查询可见群组并生成发送目标和监听规则；可以用上下键移动、空格勾选群组、回车确认。微信扫码绑定会尝试直接在终端打印二维码，并始终保留可复制的原始链接。WxPusher 默认走 SPT 极简推送模式，除非你主动选择 App Token + UID/Topic 模式，否则向导只需要填写 SPT：

```bash
python ngawolf_cli.py init
```

之后需要修改配置时运行：

```bash
python ngawolf_cli.py config
```

常用检查和运行命令：

```bash
python ngawolf_cli.py check
python ngawolf_cli.py mark-seen
python ngawolf_cli.py test-send
python ngawolf_cli.py run
python ngawolf_cli.py run --once
```

默认配置文件是 `~/.config/ngawolf/config.json`，默认运行状态和日志目录是 `~/.local/state/ngawolf/`。部署到 systemd、Docker 或其他进程管理器时，建议使用前台运行：

```bash
python ngawolf_cli.py --config /etc/ngawolf/config.json --data-dir /var/lib/ngawolf run
```

相对状态路径会解析到 `--data-dir` 下。`init` 用于首次创建配置，`config` 会读取已有配置并逐项提示修改；留空会保留当前值，方便后续改 Cookie、监听规则或推送目标。

#### 配置文件和手动编辑

实际配置文件路径取决于运行方式：

- Linux 一行安装版：`/etc/ngawolf/config.json`；状态目录默认是 `/var/lib/ngawolf`；日志默认是 `/var/log/ngawolf/watcher.log`。
- 源码/普通 CLI：默认配置文件是 `~/.config/ngawolf/config.json`；状态和日志默认在 `~/.local/state/ngawolf/`。
- Windows GUI：默认配置文件是 `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`；旧版 `nga_wolf_config.json` 会自动迁移。

配置文件是 JSONC 风格，支持 `//` 和 `/* ... */` 注释。`ngawolf init` / `ngawolf config` 或 Windows GUI 保存时会自动写入中文说明和常用格式样例；再次保存会重新生成内置注释，手写的额外注释不保证保留。手动编辑后建议执行 `sudo ngawolf check`，源码运行则执行 `python ngawolf_cli.py check`。

常用字段规则：

- `nga_cookie`：NGA 登录 Cookie，必填，通常包含 `ngaPassportUid`、`ngaPassportCid` 等字段。
- `watch_author_ids`：用户主页监听资源，每行一个 `用户ID=备注`，例如 `150058=狼大`。
- `preset_thread_ids`：帖子资源，每行一个 `帖子ID=备注`，例如 `45974302=自立自强，科学技术打头阵`。
- `push_targets`：推送目标列表，当前为 JSON 字符串；每个目标需要有 `id`，`channel` 可选 `feishu`、`wechat`、`dingtalk`、`email`、`wxpusher`。
- `listen_rules`：监听规则列表，当前为 JSON 字符串；`mode=author` 表示监听用户主页，`mode=thread_author` 表示监听指定帖子里的指定用户，`target_ids` 引用 `push_targets` 里的 `id`，可同时推送到多个通道。

结构化字段为了兼容旧配置，当前仍保存为“JSON 字符串”，手写时要保留外层引号并转义内部双引号；不确定时先用 TUI 添加一条，再照着配置文件里的中文注释和样例改：

```json
{
  "push_targets": "[{\"id\":\"feishu_main\",\"label\":\"主飞书群\",\"channel\":\"feishu\",\"profile_id\":\"default\",\"receive_id\":\"oc_xxx\",\"id_type\":\"chat_id\"}]",
  "listen_rules": "[{\"id\":\"thread_author:45974302:150058\",\"label\":\"帖子内狼大\",\"mode\":\"thread_author\",\"tid\":\"45974302\",\"author_id\":\"150058\",\"target_ids\":[\"feishu_main\"]}]"
}
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

源码用户也可以直接用 JSON 配置新版路由模型：

```powershell
$env:NGA_PUSH_TARGETS = '[{"id":"feishu_main","channel":"feishu","profile_id":"default","receive_id":"oc_xxx","default_author_id":"150058","default_tid":"45974302"}]'
$env:NGA_LISTEN_RULES = '[{"id":"wolf_thread","mode":"thread_author","tid":"45974302","author_id":"150058","target_ids":["feishu_main"]}]'
$env:AI_SCHEDULE_TARGET_IDS = 'feishu_main'
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

启动 pywebview + React 界面：

```powershell
python -m pip install pywebview
cd .\webui
npm.cmd install
npm.cmd run build
cd ..
python .\nga_wolf_webgui.py
```

推荐客户端复用同一个 `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`、运行状态和启动逻辑，但把 NGA 资源库、消息通道配置组、监听规则、AI、免打扰、运行参数和高级 JSON 分成更清晰的折叠面板。新版模型下飞书、微信、钉钉和邮箱可以同时配置；监听规则决定自动推送到哪些目标。

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
python .\nga_feishu_watch.py --interval 30 --jitter 20 --retries 10 --retry-initial-delay 3 --retry-delay 1
```

`--retry-initial-delay` 是第一次失败后的等待秒数，`--retry-delay` 是每次重试递增的秒数。上面的例子会按 3 秒、4 秒、5 秒递增重试。环境变量对应 `NGA_RETRY_INITIAL_DELAY` 和 `NGA_RETRY_DELAY`。NGA 返回 503 时按普通失败处理，使用 `NGA_RETRIES` 的总重试次数；429/500/502/504 等临时不可用错误使用同一套等待节奏，但最多重试次数由 `NGA_UNAVAILABLE_RETRIES` 控制。

监听和手动命令共用同一个 NGA 请求协调层：`NGA_REQUEST_MIN_INTERVAL` 控制同一进程内两次 NGA HTTP 请求至少间隔多久，`NGA_CACHE_TTL` 控制成功拉取的同 URL JSON 短暂缓存多久。这样手动拉取刚好撞上监听时，可以复用最近一次第一页结果，减少 503。

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

使用飞书应用凭证发送卡片时，NGA 图片默认会尝试直接显示在卡片里。程序会先下载图片 URL，再上传到飞书换取 `image_key`，然后在卡片中渲染图片；任一步失败都会自动回退成原来的可点击图片链接，不影响新回复推送。Webhook 模式不能上传卡片图片，仍然只显示链接。部分 NGA 图片 URL 会拒绝 HTTPS 直连下载，程序会自动用同一地址的 HTTP 版本重试，再失败才回退成链接。

```powershell
$env:FEISHU_CARD_IMAGES="true"
$env:FEISHU_CARD_IMAGE_LIMIT="6"
python .\nga_feishu_watch.py --feishu-card-images --feishu-card-image-limit 6
```

上传后的 `image_key` 会缓存在 `.nga_seen.json` 同目录的 `feishu_image_cache.json`，重复查询历史时不会反复上传同一张 NGA 图片。

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

### 打包 EXE

先构建前端，再打包 pywebview 客户端：

```powershell
cd .\webui
npm.cmd install
npm.cmd run build
cd ..
python -m pip install pywebview pyinstaller
python -m PyInstaller --noconfirm --clean .\NGA-Wolf-Watcher-Web.spec
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
