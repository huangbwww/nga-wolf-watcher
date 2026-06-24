# NGA Wolf Watcher

<p align="center">
  <img src="assets/app_icon.png" alt="NGA Wolf Watcher" width="96">
</p>

<p align="center">
  <strong>NGA 回复监听和多通道推送工具</strong><br>
  监听指定 NGA 用户或帖子内作者的新回复，并推送到飞书、微信、钉钉、邮箱或 WxPusher。
</p>

<p align="center">
  <a href="README.md">English</a> ·
  <a href="https://github.com/huangbwww/nga-wolf-watcher/releases/latest">下载最新版</a> ·
  <a href="docs/installation.zh-CN.md">安装文档</a> ·
  <a href="docs/configuration.zh-CN.md">配置参考</a>
</p>

<p align="center">
  <img alt="Release" src="https://img.shields.io/github/v/release/huangbwww/nga-wolf-watcher?style=flat-square">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-setup%20%2F%20portable-2563eb?style=flat-square">
  <img alt="Linux" src="https://img.shields.io/badge/Linux-x86__64%20%2F%20aarch64-16a34a?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square">
</p>

---

## 快速开始

| 你想做什么 | 推荐入口 | 说明 |
| --- | --- | --- |
| Windows 日常使用 | 下载 `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe` | 安装后从开始菜单启动；也可以下载 `portable.zip` 免安装运行。 |
| Linux 服务器后台运行 | `curl \| sudo bash` 一行安装 | 安装为 `ngawolf` 命令，支持 TUI 配置、systemd、日志和后台管理。 |
| 配置飞书/微信/钉钉/邮箱/WxPusher | 先打开 GUI 或运行 `ngawolf config` | 推荐先用交互界面添加通道、用户、帖子和监听规则。 |
| 查参数或手动改配置 | 看 [配置参考](docs/configuration.zh-CN.md) | 包含通道字段、监听模式、群内命令、配置路径和排查命令。 |

### Windows

1. 打开 [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest)。
2. 下载 `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe` 并安装。
3. 如果不想安装，下载 `nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip`，解压后运行 `NGA-Wolf-Watcher.exe`。
4. 在界面里填写 `NGA Cookie`，再新增消息通道、NGA 用户/帖子和监听规则。
5. 第一次启动前建议先执行“初始化已读”，避免历史回复一次性推送。

Windows 安装版支持简体中文和英文安装界面。安装版、便携版和旧版 exe 复用同一个数据目录：`%LOCALAPPDATA%\NGA Wolf Watcher\`。

### Linux

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo bash
```

安装后常用命令：

```bash
sudo ngawolf config
sudo ngawolf check
sudo ngawolf mark-seen
sudo ngawolf test-send
sudo ngawolf start
sudo ngawolf logs -f
```

如果国内服务器执行一行安装时访问 GitHub 超时，可以固定版本并使用镜像：

```bash
curl -fsSL https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/releases/download/vX.Y.Z/install-linux.sh \
  | sudo NGAWOLF_VERSION=vX.Y.Z NGAWOLF_GITHUB_PROXY=https://ghfast.top bash
```

`ghfast.top` 不是项目官方服务，失效时换成可用的 GitHub 加速域名即可。更多 Linux 安装、源码安装、pip 镜像和无 systemd 场景见 [安装和运行](docs/installation.zh-CN.md)。

## NGA Cookie 怎么找

Cookie 是 NGA 登录凭据，程序用它读取你能看到的帖子和回复。

1. 用浏览器登录 `https://bbs.nga.cn/`。
2. 打开任意一个 `bbs.nga.cn` 页面。
3. 按 `F12` 打开开发者工具，切到 `网络` / `Network`。
4. 保持开发者工具打开，刷新页面。
5. 点开一个发往 `bbs.nga.cn` 的请求，例如 `thread.php` 或 `read.php`。
6. 在 `标头` / `Headers` 里找到 `请求标头` / `Request Headers`。
7. 复制完整的 `Cookie` 值，填到程序里的 `NGA Cookie`。

不要把 Cookie 发到 Issue、聊天、截图、日志或 Release 文件里。Cookie 失效、复制不完整或域名不对时，常见表现是拉取空数据、JSON 解析失败或监听不到新回复。

## 推送通道

| 通道 | 适合场景 | 交互能力 |
| --- | --- | --- |
| 飞书 | 群内查询、卡片按钮、多人使用 | 支持 `/start`、`/setting`、历史查询、打包、卡片交互和 AI 对话。 |
| 微信 | 个人微信提醒 | 需要扫码绑定；支持文本菜单和短命令。 |
| 钉钉 | 企业钉钉机器人 | 支持 Stream 会话、Markdown 菜单和主动推送。 |
| 邮箱 | 只想收通知或归档 | 纯出站推送，不接收命令。 |
| WxPusher | 手机轻量通知 | 纯出站推送，使用 SPT 配置最简单。 |

通道、目标和监听规则是分开的：通道保存机器人账号，NGA 资源库保存用户 ID 和帖子 ID，监听规则决定“监听谁、从哪里监听、推送到哪里”。详细字段见 [配置、通道和命令参考](docs/configuration.zh-CN.md)。

## 常用群内命令

```text
/start
/setting
/history_r 150058 5
/pack_r 150058 5
/history_t 45974302 10
/pack_t 45974302 10
```

默认 `150058` 是 wolf uid，`45974302` 是 wolf thread id。`history` 直接发送最近回复，`pack` 会打包成文本内容或 `.txt` 文件。飞书、微信、钉钉的菜单和短命令差异见 [配置参考](docs/configuration.zh-CN.md#群内命令)。

## 本地 AI Agent

AI 功能默认关闭，不影响普通 NGA 监听和推送。开启后，程序可以把飞书/微信/钉钉消息、NGA 新回复和本地上下文交给你电脑上的 Codex、Claude Code、CodeWhale 或自定义命令处理。

适合的用法：

- 保存狼大发言和图片到本地 AI 工作目录。
- 用 `/ai` 在群里向本地 agent 提问。
- 对新回复做自动分析，或按 A 股交易时间做定时分析。
- 结合 `context/watchlist.md`、`context/positions.json`、`context/notes.md` 做个人化整理。

AI 输出只适合作为信息整理、风险提示和讨论参考，不构成投资建议，也不会自动下单。完整配置见 [本地 AI Agent 增强](docs/ai.zh-CN.md)。

## 股票看板与牛股策略

v1.5.0 开始，Windows 桌面端融合了 NGA 社区分享的牛股计算器思路，做成独立股票看板和单股工作台。这个功能来自 [Atanvardo_1](https://bbs.nga.cn/nuke.php?func=ucp&uid=8096803)、娜美、Xhox 等大佬分享的牛股计算器经验，并在本项目中结合本地 AI Agent 和持仓/重点关注列表做了适配。

看板支持自选股、重点关注、持仓看板和自定义分组，支持代码/名称搜索、模糊搜索、CSV 导入导出、清空列表、拖拽排序，以及 3 秒行情刷新。大盘条包含上证、深证、创业板和科创 50，点击指数可以查看黄白线分时图。

单股工作台支持快速切换股票，查看分时/K 线、成交量、MA/BOLL、阶段高低点、斐波回撤、日内压力/支撑、持仓盈亏和牛股策略信号。阶段高点/低点会优先按日 K 和 MACD 波段自动计算，仍可手动修正；策略输出只用于观察和复盘，不构成投资建议。

## 常用路径

| 运行方式 | 配置 | 状态和日志 |
| --- | --- | --- |
| Windows GUI | `%LOCALAPPDATA%\NGA Wolf Watcher\config.json` | 同目录下的 `.nga_seen.json` 和日志文件 |
| Linux 一行安装 | `/etc/ngawolf/config.json` | `/var/lib/ngawolf`、`/var/log/ngawolf/watcher.log` |
| 源码/普通 CLI | `~/.config/ngawolf/config.json` | `~/.local/state/ngawolf/` |

配置文件会写入中文注释和样例。手动编辑后建议运行 `ngawolf check` 或 `python ngawolf_cli.py check`。

## 文档导航

| 文档 | 内容 |
| --- | --- |
| [安装和运行](docs/installation.zh-CN.md) | Windows、Linux、源码、镜像安装、后台服务、发布包构建 |
| [配置、通道和命令参考](docs/configuration.zh-CN.md) | 通道字段、监听规则、Cookie、群内命令、免打扰、排查命令 |
| [本地 AI Agent 增强](docs/ai.zh-CN.md) | Codex、Claude Code、CodeWhale、自定义 agent、Prompt 和故障排查 |
| [Issue #1 Cookie 示例](https://github.com/huangbwww/nga-wolf-watcher/issues/1) | NGA Cookie 复制截图和补充说明 |

## 源码运行

```powershell
python -m pip install -r requirements.txt
python .\nga_wolf_webgui.py
```

Linux CLI：

```bash
python -m pip install -r requirements-linux.txt
python ngawolf_cli.py init
python ngawolf_cli.py run
```

更完整的源码运行、pywebview 前端构建、BAT 方式和发布打包见 [安装和运行](docs/installation.zh-CN.md)。

## 反馈

遇到 bug 或使用问题，欢迎提 [Issue](https://github.com/huangbwww/nga-wolf-watcher/issues)。功能建议也可以提，NGA 相关、股票相关，或者类似的个人工具需求都可以。

## 免责声明

本项目仅供个人技术研究和学习使用，使用者需自行承担使用风险。

使用者应自行确认并遵守 NGA、飞书、微信、钉钉、邮箱服务商、所在组织以及当地法律法规和平台规则。自动化访问、消息转发、Cookie 使用、频繁轮询或机器人交互可能带来账号限制、封号、数据泄露、服务中断或其他不确定后果。项目作者不作任何保证，也不对因使用、修改、分发或部署本项目造成的损失、纠纷、账号处罚、法律后果或第三方索赔承担责任。
