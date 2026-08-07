# 安装和运行

Windows、macOS、Linux、源码运行和发布包构建说明。

> 详细参考文档。第一次使用建议先看仓库首页的快速开始。

## Release 资产命名

Release 资产统一使用小写项目前缀，并在文件名里写明版本、平台、架构和包类型：

```text
nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe
nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip
nga-wolf-watcher-vX.Y.Z-macos-arm64-experimental.dmg
nga-wolf-watcher-vX.Y.Z-macos-arm64-experimental.zip
nga-wolf-watcher-vX.Y.Z-linux-x86_64.tar.gz
nga-wolf-watcher-vX.Y.Z-linux-aarch64.tar.gz
install-linux.sh
SHA256SUMS
```

Windows 的 `setup.exe` 和 `portable.zip` 会替代旧的单文件大 exe。macOS 资产包含面向 Apple Silicon Mac 的未签名实验版 `.dmg`，里面带 Applications 快捷方式，同时也保留 `.zip` 备用包。Linux 压缩包内是无界面的 `ngawolf` CLI；`install-linux.sh` 会优先安装这些二进制包，必要时才回退到源码安装。

Windows 安装版支持简体中文和英文安装界面。当前 Windows Release 资产还没有做代码签名，所以 Windows SmartScreen 可能提示未知发布者。需要校验文件时，用同一个 Release 里的 `SHA256SUMS`。

## Windows 安装版或便携版

这条路径不需要改代码，也不需要运行 Python 命令。

1. 从 [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest) 下载 `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe`。如果不想安装，下载 `nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip`，解压后运行里面的 `NGA-Wolf-Watcher.exe`。
2. 打开 [飞书开放平台](https://open.feishu.cn/page/openclaw)，创建一个机器人应用，复制应用的 `App ID` 和 `App Secret`。
3. 把机器人加入目标飞书群。
4. 如果希望不 @ 机器人也能直接使用 `/start` 等命令，需要添加 `im:message.group_msg` 权限。
5. 打开客户端，在 `消息通道` 里新增一个飞书配置组，填写 `App ID` 和 `App Secret`，在弹窗里点击 `查询群组并保存`。
6. 在 `目标` 里添加常用用户 ID 和帖子 ID，再到 `规则` / `监听规则` 里新增监听规则：选择用户主页监听或固定帖子筛选用户，并直接勾选要推送到的飞书群或微信账号。
7. 登录 `https://bbs.nga.cn/`，从浏览器请求里复制 `Cookie`，填入 `NGA Cookie`。
8. 点击 `保存配置`，再点击 `启动监听`。

第一次启动前建议保持“首次启动前自动初始化已读”开启。它会先把当前抓到的 NGA 回复标记为已读，避免历史回复一次性刷到飞书。

安装版和便携版会复用旧 EXE 的同一个数据目录。GUI 会把本地密钥保存到 `%LOCALAPPDATA%\NGA Wolf Watcher\config.json`。运行状态默认保存在同目录的 `.nga_seen.json`。不要外发这些文件。

## macOS 实验版

从 [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest) 下载 `nga-wolf-watcher-vX.Y.Z-macos-arm64-experimental.dmg`，打开后把 `NGA-Wolf-Watcher.app` 拖到 `Applications`。如果 DMG 方式在你的机器上不可用，可以下载备用 `.zip` 包，解压后打开 `NGA-Wolf-Watcher.app`。

这个包目前面向 Apple Silicon Mac，没有签名，也没有做 Apple 公证。首次打开时，macOS 可能会提示无法验证开发者。确认信任该 Release 文件后，可以右键应用选择“打开”，或到系统设置里允许打开。需要校验下载文件时，用同一个 Release 里的 `SHA256SUMS`。

macOS 应用会把本地密钥保存到 `~/.nga_wolf_watcher/config.json`。运行状态和日志也在同一目录。不要外发这些文件。

## 使用 BAT

这种方式需要本机有 Python 环境。

复制 `start_local.example.bat` 为 `start_local.bat`，填入空着的 `NGA_COOKIE` 和飞书配置，然后运行。

BAT 会自动安装 `lark-oapi`。第一次运行时，如果没有 `.nga_seen.json`，它会先执行 `--mark-seen`，避免历史回复刷屏。

## Linux 一行安装

Linux 服务器可以直接安装为 `ngawolf` 命令，不需要克隆源码：

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo bash
```

安装脚本会优先下载当前 CPU 架构对应的标准 Linux release 包，例如 `nga-wolf-watcher-vX.Y.Z-linux-x86_64.tar.gz` 或 `nga-wolf-watcher-vX.Y.Z-linux-aarch64.tar.gz`。这些二进制包在 Ubuntu 22.04 上构建，面向基于 glibc 的 Linux 发行版；特别旧的 glibc 系统和 Alpine/musl 系统可能需要走源码安装回退。如果没有可用包，再回退到源码安装。安装后程序放到 `/opt/ngawolf`，配置放到 `/etc/ngawolf/config.json`，运行状态放到 `/var/lib/ngawolf`，并生成 `/usr/local/bin/ngawolf`。首次配置会进入终端 TUI 向导；飞书模式下输入 App ID / Secret 后会自动查询机器人可见群组，可以用上下键移动、空格勾选、回车确认；微信扫码绑定会同时打印终端二维码和原始链接。如果终端 TUI 依赖不可用，CLI 会自动退回旧的数字提示：

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
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo NGAWOLF_VERSION=v1.3.0 bash
sudo NGAWOLF_SOURCE_DIR=/path/to/nga-wolf bash tools/install-linux.sh
```

如果服务器直连 GitHub 超时，可以用第三方 GitHub 镜像。镜像不是项目官方服务，可能随时失效；优先固定版本号，避免 `latest` 跳转在镜像站上失败：

```bash
curl -fsSL https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/releases/download/vX.Y.Z/install-linux.sh \
  | sudo NGAWOLF_VERSION=vX.Y.Z NGAWOLF_GITHUB_PROXY=https://ghfast.top bash
```

也可以直接指定源码包镜像地址：

```bash
curl -fsSL https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/releases/download/vX.Y.Z/install-linux.sh \
  | sudo NGAWOLF_VERSION=vX.Y.Z NGAWOLF_ARCHIVE_URL=https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/archive/refs/tags/vX.Y.Z.tar.gz bash
```

如果只想依赖一次镜像下载，可以先下载源码包，再走本地目录安装；这种方式最适合 GitHub 不稳定的服务器：

```bash
MIRROR=https://ghfast.top VERSION=vX.Y.Z bash -c '
set -e
tmp=$(mktemp -d)
curl -fL "$MIRROR/https://github.com/huangbwww/nga-wolf-watcher/archive/refs/tags/$VERSION.tar.gz" -o "$tmp/src.tar.gz"
tar -xzf "$tmp/src.tar.gz" -C "$tmp" --strip-components=1
sudo NGAWOLF_SOURCE_DIR="$tmp" bash "$tmp/tools/install-linux.sh"
'
```

如果 Linux 服务器完全不能访问 GitHub，可以在其他机器下载源码包或克隆仓库后传到服务器，再执行：

```bash
sudo NGAWOLF_SOURCE_DIR=/path/to/nga-wolf bash /path/to/nga-wolf/tools/install-linux.sh
```

安装过程还需要通过 pip 安装 Python 依赖；如果 PyPI 也慢，可以把 pip 镜像一并传给安装脚本：

```bash
sudo PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple NGAWOLF_SOURCE_DIR=/path/to/nga-wolf bash /path/to/nga-wolf/tools/install-linux.sh
```

## 直接运行源码

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

## 打包 Windows Release 资产

先构建前端，再把 pywebview 客户端打包成 onedir 目录。Release workflow 会把这个目录压缩成 portable zip，并用 Inno Setup 生成安装包：

```powershell
cd .\webui
npm.cmd ci
npm.cmd run build
cd ..
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean .\NGA-Wolf-Watcher-Web-Onedir.spec
```

便携版程序目录是 `dist\NGA-Wolf-Watcher\`。Release 资产命名为 `nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip` 和 `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe`。

## 打包 macOS 实验版

先构建前端，再把 pywebview 客户端打包成未签名 `.app`：

```bash
cd webui
npm ci
npm run build
cd ..
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean NGA-Wolf-Watcher-macOS.spec
bash tools/build-macos-dmg.sh dist/NGA-Wolf-Watcher.app "release/nga-wolf-watcher-vX.Y.Z-macos-arm64-experimental.dmg" "NGA Wolf Watcher"
ditto -c -k --keepParent dist/NGA-Wolf-Watcher.app "release/nga-wolf-watcher-vX.Y.Z-macos-arm64-experimental.zip"
```

在配置代码签名和 Apple 公证前，macOS 包都先按 experimental 处理。
