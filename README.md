# NGA Wolf Watcher

<p align="center">
  <img src="assets/app_icon.png" alt="NGA Wolf Watcher" width="96">
</p>

<p align="center">
  <strong>NGA reply watcher with multi-channel notifications</strong><br>
  Watch selected NGA authors or thread authors, then push new replies to Feishu, WeChat, DingTalk, email, or WxPusher.
</p>

<p align="center">
  <a href="README.zh-CN.md">中文说明</a> ·
  <a href="https://github.com/huangbwww/nga-wolf-watcher/releases/latest">Latest Release</a> ·
  <a href="docs/installation.md">Installation</a> ·
  <a href="docs/configuration.md">Configuration</a>
</p>

<p align="center">
  <img alt="Release" src="https://img.shields.io/github/v/release/huangbwww/nga-wolf-watcher?style=flat-square">
  <img alt="Windows" src="https://img.shields.io/badge/Windows-setup%20%2F%20portable-2563eb?style=flat-square">
  <img alt="Linux" src="https://img.shields.io/badge/Linux-x86__64%20%2F%20aarch64-16a34a?style=flat-square">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12+-3776ab?style=flat-square">
</p>

---

## Quick Start

| Goal | Recommended Entry | Notes |
| --- | --- | --- |
| Use it on Windows | Download `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe` | Use `portable.zip` if you do not want to install. |
| Run it on a Linux server | Install with one shell command | Creates the `ngawolf` command, TUI setup, logs, and background service helpers. |
| Configure channels and listen rules | Use the GUI or `ngawolf config` | Add push channels, NGA users, thread IDs, and listen rules interactively. |
| Check advanced settings | Read [Configuration](docs/configuration.md) | Channel fields, commands, config paths, watch modes, and troubleshooting commands. |

### Windows

1. Open [Releases](https://github.com/huangbwww/nga-wolf-watcher/releases/latest).
2. Download and run `nga-wolf-watcher-vX.Y.Z-windows-x86_64-setup.exe`.
3. Or download `nga-wolf-watcher-vX.Y.Z-windows-x86_64-portable.zip`, extract it, and run `NGA-Wolf-Watcher.exe`.
4. Fill `NGA Cookie`, then add message channels, NGA users/threads, and listen rules.
5. Before the first long-running watch, mark existing replies as seen to avoid pushing old history in bulk.

The Windows setup installer supports Simplified Chinese and English. Setup, portable, and older onefile builds use the same data directory: `%LOCALAPPDATA%\NGA Wolf Watcher\`.

### Linux

```bash
curl -fsSL https://github.com/huangbwww/nga-wolf-watcher/releases/latest/download/install-linux.sh | sudo bash
```

Common commands after installation:

```bash
sudo ngawolf config
sudo ngawolf check
sudo ngawolf mark-seen
sudo ngawolf test-send
sudo ngawolf start
sudo ngawolf logs -f
```

If GitHub downloads time out, pin a version and pass a mirror to the installer:

```bash
curl -fsSL https://ghfast.top/https://github.com/huangbwww/nga-wolf-watcher/releases/download/vX.Y.Z/install-linux.sh \
  | sudo NGAWOLF_VERSION=vX.Y.Z NGAWOLF_GITHUB_PROXY=https://ghfast.top bash
```

`ghfast.top` is not an official project service. Replace it with another working GitHub mirror if needed. More Linux, source, pip mirror, and non-systemd notes are in [Installation And Runtime](docs/installation.md).

## How To Copy NGA Cookie

The Cookie is your NGA login credential. The watcher uses it to read pages your account can access.

1. Log in to `https://bbs.nga.cn/` in a browser.
2. Open any `bbs.nga.cn` page.
3. Press `F12`, then open `Network`.
4. Keep DevTools open and refresh the page.
5. Select a request to `bbs.nga.cn`, such as `thread.php` or `read.php`.
6. In `Headers`, find `Request Headers`.
7. Copy the full `Cookie` value and paste it into `NGA Cookie`.

Do not post your Cookie in issues, chats, screenshots, logs, or release files. Empty fetch results or JSON parse errors usually mean the Cookie expired, was copied incompletely, or came from the wrong domain.

## Push Channels

| Channel | Best For | Interaction |
| --- | --- | --- |
| Feishu | Group queries, cards, team use | `/start`, `/setting`, history, pack, cards, and AI chat. |
| WeChat | Personal WeChat reminders | QR binding, text menus, and short commands. |
| DingTalk | Enterprise bot usage | Stream sessions, Markdown menus, and active push. |
| Email | Notifications and archive | Outbound push only. |
| WxPusher | Lightweight phone notifications | Outbound push through SPT. |

Channels, NGA resources, and listen rules are separate: channels store bot accounts, the resource library stores users and thread IDs, and listen rules decide what to watch and where to send. See [Configuration, Channels, And Commands](docs/configuration.md).

## Common Commands

```text
/start
/setting
/history_r 150058 5
/pack_r 150058 5
/history_t 45974302 10
/pack_t 45974302 10
```

By default, `150058` is the wolf uid and `45974302` is the wolf thread id. `history` sends recent replies directly; `pack` sends packed text or a `.txt` file. See [Commands](docs/configuration.md#commands) for channel-specific behavior.

## Local AI Agent

AI is disabled by default and is not required for normal NGA watching or pushing. When enabled, the app can pass Feishu/WeChat/DingTalk messages, new NGA replies, and local context to a local Codex, Claude Code, CodeWhale, or custom command.

Typical uses:

- Save watched replies and images into a local AI workspace.
- Ask your local agent from a group with `/ai`.
- Automatically analyze new replies or run scheduled market-session analysis.
- Keep personal context in `context/watchlist.md`, `context/positions.json`, and `context/notes.md`.

AI output is for information organization, risk notes, and discussion only. It is not investment advice and the app never trades automatically. See [Local AI Agent Enhancement](docs/ai.md).

## Stock Dashboard And Bull Strategy

Since v1.5.0, the Windows desktop app includes a stock dashboard and single-stock workbench inspired by bull stock calculator ideas shared in the NGA community. The feature integrates calculator experience shared by [Atanvardo_1](https://bbs.nga.cn/nuke.php?func=ucp&uid=8096803), Nami, Xhox, and other contributors, then adapts it to this app's local AI Agent context, position list, and focus-watch list.

The dashboard supports watchlists, focus-watch stocks, positions, custom groups, code/name search, fuzzy search, CSV import/export, clearing the list, drag ordering, and 3-second quote refreshes. The market strip includes Shanghai, Shenzhen, ChiNext, and STAR 50 indexes; clicking an index opens the yellow/white intraday line view.

The single-stock workbench supports fast stock switching, intraday/K-line charts, volume, MA/BOLL overlays, swing high/low, Fibonacci retracement, intraday pressure/support, position profit and loss, and bull strategy signals. Swing high/low values are auto-filled from daily K-line and MACD swing logic when possible, but can still be edited manually. Strategy output is for observation and review only. It is not investment advice.

## Default Paths

| Runtime | Config | State And Logs |
| --- | --- | --- |
| Windows GUI | `%LOCALAPPDATA%\NGA Wolf Watcher\config.json` | `.nga_seen.json` and logs in the same directory |
| Linux one-command install | `/etc/ngawolf/config.json` | `/var/lib/ngawolf`, `/var/log/ngawolf/watcher.log` |
| Source / plain CLI | `~/.config/ngawolf/config.json` | `~/.local/state/ngawolf/` |

The generated config file includes comments and examples. After manual edits, run `ngawolf check` or `python ngawolf_cli.py check`.

## Documentation

| Page | Contents |
| --- | --- |
| [Installation And Runtime](docs/installation.md) | Windows, Linux, source, mirrors, background service, release builds |
| [Configuration, Channels, And Commands](docs/configuration.md) | Channel fields, listen rules, Cookie, commands, quiet hours, troubleshooting commands |
| [Local AI Agent Enhancement](docs/ai.md) | Codex, Claude Code, CodeWhale, custom agents, prompts, and troubleshooting |
| [Issue #1 Cookie Example](https://github.com/huangbwww/nga-wolf-watcher/issues/1) | Extra Cookie copying notes and screenshots |

## Run From Source

```powershell
python -m pip install -r requirements.txt
python .\nga_wolf_webgui.py
```

Linux CLI:

```bash
python -m pip install -r requirements-linux.txt
python ngawolf_cli.py init
python ngawolf_cli.py run
```

More source runtime, pywebview build, BAT usage, and release packaging notes are in [Installation And Runtime](docs/installation.md).

## Feedback

Please open an [Issue](https://github.com/huangbwww/nga-wolf-watcher/issues) for bugs, usage problems, or feature ideas.

## Disclaimer

This project is for personal technical research and learning. You are responsible for your own use.

You must confirm and follow the rules of NGA, Feishu, WeChat, DingTalk, email providers, your organization, and applicable laws. Automated access, message forwarding, Cookie usage, frequent polling, and bot interaction may cause account restrictions, bans, data exposure, service interruption, or other unpredictable consequences. The author provides no warranty and is not liable for losses, disputes, account penalties, legal consequences, or third-party claims caused by using, modifying, distributing, or deploying this project.
