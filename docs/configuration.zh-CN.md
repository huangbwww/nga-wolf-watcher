# 配置、通道和命令参考

消息通道、监听规则、群内命令、Cookie、配置文件和排查命令说明。

> 详细参考文档。第一次使用建议先看仓库首页的快速开始。

## 消息通道、目标和监听规则

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

## 免打扰时段

在 `运行设置` 里开启 `免打扰时段` 后，可以设置开始星期/时间和结束星期/时间，例如 `周五 18:00 -> 周一 08:00`。时间使用小时/分钟下拉选择，不需要手动输入 `HH:MM`。免打扰时段只影响自动持续监听的新回复推送，不影响飞书手动查询、打包、查询群组和发送测试。

免打扰期间的新回复有两种处理方式：

- `忽略新回复`：免打扰期间仍会监听并标记已读，免打扰结束后不会补发。
- `暂存并在免打扰结束后汇总推送`：免打扰期间的新回复会先暂存，免打扰结束后发送一张汇总卡片。

## 如何复制 NGA Cookie

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

## 配置文件和手动编辑

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

## 常用检查

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

## 旧版自定义机器人 Webhook

Webhook 模式仍然保留：

```powershell
$env:FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/...'
$env:FEISHU_SECRET = 'optional signing secret'
python .\nga_feishu_watch.py
```
