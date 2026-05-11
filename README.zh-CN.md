# NGA Wolf Watcher

[English](README.md) | 中文说明

监听指定 NGA 用户的回复，推送新回复到飞书，并支持通过飞书卡片查询历史或打包成 `.txt` 文件。

## 功能提示

- 持续监听：点击 `启动监听` 后，程序会持续查询配置里的 `默认用户 ID` 的 NGA 新回复，并把新发现的回复推送到目标飞书群。
- 手动查询：在飞书群里可以使用命令或卡片按钮，查询用户回复、查询帖子回复，或把结果打包成 `.txt` 文件。

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

GUI 会把本地密钥保存到 `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`。不要外发这个文件。

### 如何复制 NGA Cookie

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

脚本会把已推送回复 id 和已处理命令 id 存在 `.nga_seen.json`。

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
