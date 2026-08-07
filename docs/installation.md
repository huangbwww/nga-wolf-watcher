# Installation And Runtime

Windows, macOS, Linux, source runtime, and release build notes.

> Detailed reference. Start with the repository README for the quick path.

## Release Assets

Release assets use the same lowercase project prefix and include version, platform, architecture, and package type:

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

The Windows `setup.exe` and `portable.zip` replace the old single large onefile exe. The macOS assets contain an unsigned experimental `.dmg` with an Applications shortcut plus a fallback `.zip` for Apple Silicon Macs. The Linux archives contain the headless `ngawolf` CLI; `install-linux.sh` installs those archives first and falls back to source installation only when needed.

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

## macOS Experimental App

Download `nga-wolf-watcher-vX.Y.Z-macos-arm64-experimental.dmg` from [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest), open it, then drag `NGA-Wolf-Watcher.app` to `Applications`. If the DMG flow does not work on your machine, use the fallback `.zip` package, unzip it, and open `NGA-Wolf-Watcher.app`.

This package is currently built for Apple Silicon Macs and is not signed or notarized. On first launch, macOS may block it as an unidentified app. Right-click the app and choose Open, or allow it in System Settings, if you trust the downloaded release asset. Verify downloaded files with `SHA256SUMS` when needed.

The macOS app stores local secrets under `~/.nga_wolf_watcher/config.json`. Runtime state and logs are stored in the same directory. Do not share these files.

## Run With BAT

This mode requires a local Python environment.

Copy `start_local.example.bat` to `start_local.bat`, fill the empty `NGA_COOKIE` and Feishu values, then run it.

The BAT installs `lark-oapi` automatically. On the first run, if `.nga_seen.json` does not exist, it runs `--mark-seen` before starting the watcher to avoid pushing old replies.

## One-Command Linux Install

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

## Run From Source

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

## Build Windows Release Assets

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

## Build macOS Experimental App

Build the frontend first, then package the pywebview client as an unsigned `.app` bundle:

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

The macOS package is experimental until code signing and notarization are configured.
