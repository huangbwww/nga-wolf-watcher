# Linux CLI Service Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a headless Linux-friendly `ngawolf` CLI that can initialize, edit, validate, and run NGA Wolf Watcher from `config.json`.

**Architecture:** Extract shared config behavior from the desktop GUI into `nga_wolf_config.py`, then build `ngawolf_cli.py` as a thin command-line wrapper over that shared config module and the existing `nga_feishu_watch.py` watcher functions. The desktop GUI keeps its current behavior by importing the same helpers with desktop data paths.

**Tech Stack:** Python standard library (`argparse`, `json`, `getpass`, `pathlib`, `unittest.mock`), existing project modules (`nga_feishu_watch`, `ai_analysis`, channel modules), pytest for tests.

---

## File Structure

- Create `nga_wolf_config.py`: shared defaults, profile parsing helpers, JSON read/write, path resolution, config validation, config-to-`Namespace` conversion, and watcher dispatch helpers that do not import desktop UI libraries.
- Create `ngawolf_cli.py`: user-facing CLI command dispatcher, line-based prompt helpers, and command implementations for `init`, `config`, `run`, `check`, `mark-seen`, and `test-send`.
- Modify `nga_wolf_gui.py`: replace duplicated config helpers with imports from `nga_wolf_config.py` while preserving Windows desktop data paths and public function names used by `nga_wolf_webgui.py`.
- Modify `nga_wolf_webgui.py`: keep using `nga_wolf_gui.py` facade functions; only adjust imports if the extraction changes names.
- Create `tests/test_nga_wolf_config.py`: shared config tests.
- Create `tests/test_ngawolf_cli.py`: CLI prompt and command dispatch tests.
- Modify `README.zh-CN.md`: add Linux CLI usage section.

---

### Task 1: Extract Shared Config Module

**Files:**
- Create: `nga_wolf_config.py`
- Modify: `nga_wolf_gui.py`
- Test: `tests/test_nga_wolf_config.py`

- [ ] **Step 1: Write failing tests for shared config paths and arg conversion**

Create `tests/test_nga_wolf_config.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import nga_wolf_config


def test_linux_default_paths_use_xdg_home(monkeypatch, tmp_path: Path) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    assert nga_wolf_config.linux_config_path() == home / ".config" / "ngawolf" / "config.json"
    assert nga_wolf_config.linux_data_dir() == home / ".local" / "state" / "ngawolf"


def test_explicit_xdg_paths_are_used(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))

    assert nga_wolf_config.linux_config_path() == tmp_path / "config" / "ngawolf" / "config.json"
    assert nga_wolf_config.linux_data_dir() == tmp_path / "state" / "ngawolf"


def test_resolved_state_path_uses_supplied_data_dir(tmp_path: Path) -> None:
    config = {"state_path": ".nga_seen.json"}

    assert nga_wolf_config.resolved_state_path(config, data_dir=tmp_path) == tmp_path / ".nga_seen.json"


def test_load_and_save_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config["bot_channel"] = "email"
    config["email_to"] = "receiver@example.com"

    nga_wolf_config.save_config(config, path)
    loaded = nga_wolf_config.load_config(path)

    assert loaded["bot_channel"] == "email"
    assert loaded["email_to"] == "receiver@example.com"


def test_build_args_resolves_relative_service_paths(tmp_path: Path) -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update(
        {
            "bot_channel": "email",
            "nga_cookie": "ngaPassportUid=1; ngaPassportCid=2",
            "watch_author_ids": "150058=wolf",
            "preset_thread_ids": "45974302=main",
            "email_username": "sender@example.com",
            "email_password": "secret",
            "email_to": "receiver@example.com",
            "state_path": ".seen.json",
            "ai_work_dir": ".ai",
        }
    )

    args = nga_wolf_config.build_args(config, data_dir=tmp_path)

    assert args.bot_channel == "email"
    assert args.state_path == str(tmp_path / ".seen.json")
    assert args.ai_work_dir == str(tmp_path / ".ai")
    assert args.default_author_id == "150058"
    assert args.default_tid == "45974302"


def test_validate_config_reuses_desktop_rules() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config["bot_channel"] = "email"

    errors = nga_wolf_config.validate_config(config)

    assert "NGA Cookie" in errors
    assert any("邮箱" in item or "閭" in item for item in errors)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_nga_wolf_config.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'nga_wolf_config'`.

- [ ] **Step 3: Create `nga_wolf_config.py` with extracted helpers**

Create `nga_wolf_config.py` by moving these UI-independent definitions out of `nga_wolf_gui.py`:

```python
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from argparse import Namespace
from pathlib import Path
from typing import Any

import ai_analysis
import nga_feishu_watch
import wechat_bot

APP_DIR_NAME = "NGA Wolf Watcher"
CONFIG_FILE = "config.json"
RUNTIME_CONFIG_FILE = "runtime_config.json"
LOG_FILE = "watcher.log"
WATCHER_PID_FILE = "watcher.pid"

DEFAULT_CONFIG = {
    # Copy the full existing DEFAULT_CONFIG value from nga_wolf_gui.py unchanged.
}
```

Move the full bodies of these existing functions from `nga_wolf_gui.py` into `nga_wolf_config.py`:

```python
json_list_config
ensure_profile_id
load_feishu_profiles
load_wechat_profiles
load_dingtalk_profiles
load_email_profiles
load_push_targets
load_listen_rules
describe_target
describe_rule
write_json
int_value
float_value
resolved_state_path
build_args
validate_config
run_watcher_from_config
```

Add these Linux path helpers:

```python
def linux_config_path() -> Path:
    root = os.getenv("XDG_CONFIG_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".config"
    return base / "ngawolf" / CONFIG_FILE


def linux_data_dir() -> Path:
    root = os.getenv("XDG_STATE_HOME")
    base = Path(root).expanduser() if root else Path.home() / ".local" / "state"
    return base / "ngawolf"


def load_config(path: Path, defaults: dict[str, object] | None = None) -> dict[str, object]:
    base = dict(defaults or DEFAULT_CONFIG)
    if not path.exists():
        return base
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            loaded = json.load(f)
    except json.JSONDecodeError as exc:
        raise ValueError(f"配置文件 JSON 格式错误: {path}: {exc}") from exc
    if isinstance(loaded, dict):
        base.update(loaded)
    return base


def save_config(config: dict[str, object], path: Path) -> None:
    write_json(path, config)
```

Update `resolved_state_path` signature so desktop and CLI can pass different data roots:

```python
def resolved_state_path(config: dict[str, object], data_dir: Path | None = None) -> Path:
    raw = str(config.get("state_path") or ".nga_seen.json").strip()
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (data_dir or Path.cwd()) / path
    return path
```

Update `build_args` signature and AI work dir handling:

```python
def build_args(
    config: dict[str, object],
    *,
    data_dir: Path | None = None,
    mark_seen: bool = False,
    ws: bool = False,
    ws_no_watch: bool = False,
) -> Namespace:
    # Keep the existing body, but call resolved_state_path(config, data_dir=data_dir).
    # When building ai_work_dir:
    raw_ai_work_dir = str(config.get("ai_work_dir") or ".ai_agent_workspace").strip()
    ai_work_dir = Path(raw_ai_work_dir).expanduser()
    if data_dir is not None and not ai_work_dir.is_absolute():
        raw_ai_work_dir = str(data_dir / ai_work_dir)
```

- [ ] **Step 4: Keep desktop facade functions in `nga_wolf_gui.py`**

Modify imports near the top of `nga_wolf_gui.py`:

```python
import nga_wolf_config
from nga_wolf_config import DEFAULT_CONFIG
```

Replace the moved function bodies in `nga_wolf_gui.py` with wrappers that preserve desktop behavior:

```python
def config_path() -> Path:
    return data_dir() / CONFIG_FILE


def watcher_config_path() -> Path:
    return data_dir() / RUNTIME_CONFIG_FILE


def log_path() -> Path:
    return data_dir() / LOG_FILE


def watcher_pid_path() -> Path:
    return data_dir() / WATCHER_PID_FILE


def load_config() -> dict[str, object]:
    migrate_old_config()
    return nga_wolf_config.load_config(config_path())


def save_config(config: dict[str, object]) -> None:
    nga_wolf_config.save_config(config, config_path())


def save_runtime_config(config: dict[str, object]) -> None:
    nga_wolf_config.write_json(watcher_config_path(), config)


def resolved_state_path(config: dict[str, object]) -> Path:
    return nga_wolf_config.resolved_state_path(config, data_dir=data_dir())


def build_args(config: dict[str, object], *, mark_seen: bool = False, ws: bool = False, ws_no_watch: bool = False) -> Namespace:
    return nga_wolf_config.build_args(config, data_dir=data_dir(), mark_seen=mark_seen, ws=ws, ws_no_watch=ws_no_watch)


validate_config = nga_wolf_config.validate_config
json_list_config = nga_wolf_config.json_list_config
ensure_profile_id = nga_wolf_config.ensure_profile_id
load_feishu_profiles = nga_wolf_config.load_feishu_profiles
load_wechat_profiles = nga_wolf_config.load_wechat_profiles
load_dingtalk_profiles = nga_wolf_config.load_dingtalk_profiles
load_email_profiles = nga_wolf_config.load_email_profiles
load_push_targets = nga_wolf_config.load_push_targets
load_listen_rules = nga_wolf_config.load_listen_rules
describe_target = nga_wolf_config.describe_target
describe_rule = nga_wolf_config.describe_rule
int_value = nga_wolf_config.int_value
float_value = nga_wolf_config.float_value
write_json = nga_wolf_config.write_json
```

Keep `run_watcher_from_config` as a wrapper so existing `nga_wolf_webgui.py` calls keep working:

```python
def run_watcher_from_config(path: Path, *, ws_no_watch: bool = False) -> None:
    nga_wolf_config.run_watcher_from_config(path, data_dir=data_dir(), ws_no_watch=ws_no_watch)
```

- [ ] **Step 5: Run focused config tests**

Run:

```bash
python -m pytest tests/test_nga_wolf_config.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Run existing tests**

Run:

```bash
python -m pytest tests/test_email_channel.py tests/test_dingtalk_channel.py tests/test_issue18_thread_watch.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit extraction**

```bash
git add nga_wolf_config.py nga_wolf_gui.py tests/test_nga_wolf_config.py
git commit -m "refactor: extract shared watcher config"
```

---

### Task 2: Add CLI Parser and Path Resolution

**Files:**
- Create: `ngawolf_cli.py`
- Modify: `tests/test_ngawolf_cli.py`

- [ ] **Step 1: Write failing tests for CLI defaults and parser**

Create `tests/test_ngawolf_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

import ngawolf_cli


def test_parser_accepts_primary_commands() -> None:
    for command in ["init", "config", "run", "check", "mark-seen", "test-send"]:
        args = ngawolf_cli.parse_args([command])
        assert args.command == command


def test_common_paths_default_to_linux_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    args = ngawolf_cli.parse_args(["check"])

    paths = ngawolf_cli.resolve_cli_paths(args)

    assert paths.config_path == tmp_path / "home" / ".config" / "ngawolf" / "config.json"
    assert paths.data_dir == tmp_path / "home" / ".local" / "state" / "ngawolf"
    assert paths.log_file == tmp_path / "home" / ".local" / "state" / "ngawolf" / "watcher.log"


def test_common_paths_accept_overrides(tmp_path: Path) -> None:
    args = ngawolf_cli.parse_args(
        [
            "--config",
            str(tmp_path / "custom.json"),
            "--data-dir",
            str(tmp_path / "state"),
            "--log-file",
            str(tmp_path / "watcher.log"),
            "run",
            "--once",
        ]
    )

    paths = ngawolf_cli.resolve_cli_paths(args)

    assert paths.config_path == tmp_path / "custom.json"
    assert paths.data_dir == tmp_path / "state"
    assert paths.log_file == tmp_path / "watcher.log"
    assert args.once is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_ngawolf_cli.py -q
```

Expected: fails with `ModuleNotFoundError: No module named 'ngawolf_cli'`.

- [ ] **Step 3: Implement CLI parser and path dataclass**

Create `ngawolf_cli.py`:

```python
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import nga_wolf_config


@dataclass(frozen=True)
class CliPaths:
    config_path: Path
    data_dir: Path
    log_file: Path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="ngawolf", description="Headless CLI for NGA Wolf Watcher.")
    parser.add_argument("--config", default="", help="Path to config.json.")
    parser.add_argument("--data-dir", default="", help="Directory for state, logs, and relative runtime files.")
    parser.add_argument("--log-file", default="", help="Path to watcher log file.")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("init", help="Create a new interactive config.")
    subparsers.add_parser("config", help="Edit an existing config interactively.")

    run_parser = subparsers.add_parser("run", help="Run watcher in the foreground.")
    run_parser.add_argument("--once", action="store_true", help="Run one polling pass and exit.")

    subparsers.add_parser("check", help="Validate config and print detected issues.")
    subparsers.add_parser("mark-seen", help="Mark current matching posts as already seen.")
    subparsers.add_parser("test-send", help="Send a test message through configured channel.")
    return parser.parse_args(argv)


def resolve_cli_paths(args: argparse.Namespace) -> CliPaths:
    config_path = Path(args.config).expanduser() if args.config else nga_wolf_config.linux_config_path()
    data_dir = Path(args.data_dir).expanduser() if args.data_dir else nga_wolf_config.linux_data_dir()
    log_file = Path(args.log_file).expanduser() if args.log_file else data_dir / nga_wolf_config.LOG_FILE
    return CliPaths(config_path=config_path, data_dir=data_dir, log_file=log_file)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_cli_paths(args)
    print(f"config: {paths.config_path}")
    print(f"data: {paths.data_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run parser tests**

Run:

```bash
python -m pytest tests/test_ngawolf_cli.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit parser**

```bash
git add ngawolf_cli.py tests/test_ngawolf_cli.py
git commit -m "feat: add ngawolf cli parser"
```

---

### Task 3: Implement Interactive `init` and `config`

**Files:**
- Modify: `ngawolf_cli.py`
- Modify: `tests/test_ngawolf_cli.py`

- [ ] **Step 1: Add failing tests for prompt editing**

Append to `tests/test_ngawolf_cli.py`:

```python
from unittest.mock import patch

import nga_wolf_config


def test_config_prompt_keeps_existing_values_on_enter() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config["bot_channel"] = "email"
    config["nga_cookie"] = "old-cookie"
    config["email_to"] = "old@example.com"

    with patch("builtins.input", side_effect=["", "", ""]):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated["bot_channel"] == "email"
    assert updated["nga_cookie"] == "old-cookie"
    assert updated["email_to"] == "old@example.com"


def test_config_prompt_updates_entered_values() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config["bot_channel"] = "feishu"

    with patch("builtins.input", side_effect=["email", "new-cookie", "receiver@example.com"]):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated["bot_channel"] == "email"
    assert updated["nga_cookie"] == "new-cookie"
    assert updated["email_to"] == "receiver@example.com"


def test_init_refuses_existing_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{}", encoding="utf-8")
    paths = ngawolf_cli.CliPaths(path, tmp_path / "state", tmp_path / "watcher.log")

    result = ngawolf_cli.command_init(paths)

    assert result == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_ngawolf_cli.py -q
```

Expected: fails because `prompt_basic_config` and `command_init` are not defined.

- [ ] **Step 3: Implement line-based prompts and config write**

Add to `ngawolf_cli.py`:

```python
def prompt_text(label: str, current: object = "", *, secret: bool = False) -> str:
    shown = "<已设置>" if secret and str(current or "") else str(current or "")
    prompt = f"{label}"
    if shown:
        prompt += f" [{shown}]"
    prompt += ": "
    value = input(prompt).strip()
    return str(current or "") if value == "" else value


def prompt_basic_config(config: dict[str, object]) -> dict[str, object]:
    updated = dict(config)
    updated["bot_channel"] = prompt_text("推送通道 feishu/wechat/dingtalk/email", updated.get("bot_channel", "feishu"))
    updated["nga_cookie"] = prompt_text("NGA Cookie", updated.get("nga_cookie", ""), secret=True)
    channel = str(updated.get("bot_channel") or "feishu").strip().lower()
    if channel == "email":
        updated["email_to"] = prompt_text("收件邮箱", updated.get("email_to", ""))
    elif channel == "feishu":
        updated["feishu_app_id"] = prompt_text("飞书 App ID", updated.get("feishu_app_id", ""))
        updated["feishu_app_secret"] = prompt_text("飞书 App Secret", updated.get("feishu_app_secret", ""), secret=True)
        updated["feishu_receive_id"] = prompt_text("飞书 Receive ID", updated.get("feishu_receive_id", ""))
    elif channel == "wechat":
        updated["wechat_bot_token"] = prompt_text("微信 Bot Token", updated.get("wechat_bot_token", ""), secret=True)
        updated["wechat_bot_target_user_id"] = prompt_text("微信目标用户 ID", updated.get("wechat_bot_target_user_id", ""))
    elif channel == "dingtalk":
        updated["dingtalk_client_id"] = prompt_text("钉钉 Client ID/App Key", updated.get("dingtalk_client_id", ""))
        updated["dingtalk_client_secret"] = prompt_text("钉钉 Client Secret/App Secret", updated.get("dingtalk_client_secret", ""), secret=True)
        updated["dingtalk_target_user_ids"] = prompt_text("钉钉目标用户 ID，多个用逗号分隔", updated.get("dingtalk_target_user_ids", ""))
    updated["watch_mode"] = prompt_text("监听模式 author/thread_author/both", updated.get("watch_mode", "author"))
    updated["watch_author_ids"] = prompt_text("监听用户 ID 列表，例如 150058=狼大", updated.get("watch_author_ids", ""))
    updated["preset_thread_ids"] = prompt_text("帖子 ID 列表，例如 45974302=主贴", updated.get("preset_thread_ids", ""))
    updated["interval"] = prompt_text("轮询间隔秒", updated.get("interval", "30"))
    updated["jitter"] = prompt_text("轮询随机抖动秒", updated.get("jitter", "20"))
    updated["state_path"] = prompt_text("状态文件路径", updated.get("state_path", ".nga_seen.json"))
    return updated


def command_init(paths: CliPaths) -> int:
    if paths.config_path.exists():
        print(f"配置已存在: {paths.config_path}")
        print("如需修改，请运行 ngawolf config")
        return 2
    config = prompt_basic_config(dict(nga_wolf_config.DEFAULT_CONFIG))
    nga_wolf_config.save_config(config, paths.config_path)
    print(f"配置已写入: {paths.config_path}")
    return 0


def command_config(paths: CliPaths) -> int:
    config = nga_wolf_config.load_config(paths.config_path)
    updated = prompt_basic_config(config)
    nga_wolf_config.save_config(updated, paths.config_path)
    print(f"配置已更新: {paths.config_path}")
    return 0
```

Update `main` dispatch:

```python
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_cli_paths(args)
    if args.command == "init":
        return command_init(paths)
    if args.command == "config":
        return command_config(paths)
    print(f"command not implemented: {args.command}")
    return 2
```

- [ ] **Step 4: Run prompt tests**

Run:

```bash
python -m pytest tests/test_ngawolf_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 5: Commit init/config**

```bash
git add ngawolf_cli.py tests/test_ngawolf_cli.py
git commit -m "feat: add interactive linux config commands"
```

---

### Task 4: Implement Runtime Commands

**Files:**
- Modify: `ngawolf_cli.py`
- Modify: `tests/test_ngawolf_cli.py`

- [ ] **Step 1: Add failing tests for command dispatch**

Append to `tests/test_ngawolf_cli.py`:

```python
def valid_email_config() -> dict[str, object]:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update(
        {
            "bot_channel": "email",
            "nga_cookie": "ngaPassportUid=1; ngaPassportCid=2",
            "watch_author_ids": "150058=wolf",
            "preset_thread_ids": "45974302=main",
            "email_username": "sender@example.com",
            "email_password": "secret",
            "email_to": "receiver@example.com",
        }
    )
    return config


def write_config(path: Path, config: dict[str, object]) -> None:
    nga_wolf_config.save_config(config, path)


def test_check_returns_nonzero_for_invalid_config(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    write_config(path, dict(nga_wolf_config.DEFAULT_CONFIG))
    paths = ngawolf_cli.CliPaths(path, tmp_path / "state", tmp_path / "watcher.log")

    assert ngawolf_cli.command_check(paths) == 1


def test_mark_seen_dispatches_run_once(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    write_config(path, valid_email_config())
    paths = ngawolf_cli.CliPaths(path, tmp_path / "state", tmp_path / "watcher.log")

    with patch("nga_feishu_watch.run_once", return_value=3) as run_once:
        result = ngawolf_cli.command_mark_seen(paths)

    assert result == 0
    assert run_once.call_count == 1
    assert run_once.call_args.args[0].mark_seen is True


def test_test_send_dispatches_send_test_message(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    write_config(path, valid_email_config())
    paths = ngawolf_cli.CliPaths(path, tmp_path / "state", tmp_path / "watcher.log")

    with patch("nga_feishu_watch.send_test_message") as send_test:
        result = ngawolf_cli.command_test_send(paths)

    assert result == 0
    assert send_test.call_count == 1


def test_run_once_dispatches_run_once(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    write_config(path, valid_email_config())
    paths = ngawolf_cli.CliPaths(path, tmp_path / "state", tmp_path / "watcher.log")

    with patch("nga_feishu_watch.run_once", return_value=1) as run_once:
        result = ngawolf_cli.command_run(paths, once=True)

    assert result == 0
    assert run_once.call_count == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_ngawolf_cli.py -q
```

Expected: fails because runtime command functions are not defined.

- [ ] **Step 3: Implement shared config loading and validation helpers**

Add to `ngawolf_cli.py`:

```python
import contextlib
import nga_feishu_watch


def load_service_config(paths: CliPaths) -> dict[str, object]:
    return nga_wolf_config.load_config(paths.config_path)


def build_service_args(paths: CliPaths, config: dict[str, object], *, mark_seen: bool = False) -> argparse.Namespace:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    return nga_wolf_config.build_args(config, data_dir=paths.data_dir, mark_seen=mark_seen)


def print_validation_errors(errors: list[str]) -> None:
    print("配置检查失败:")
    for error in errors:
        print(f"- {error}")


def command_check(paths: CliPaths) -> int:
    config = load_service_config(paths)
    errors = nga_wolf_config.validate_config(config)
    if errors:
        print_validation_errors(errors)
        return 1
    print("配置检查通过")
    return 0
```

- [ ] **Step 4: Implement mark-seen and test-send**

Add to `ngawolf_cli.py`:

```python
def command_mark_seen(paths: CliPaths) -> int:
    config = load_service_config(paths)
    errors = nga_wolf_config.validate_config(config)
    if errors:
        print_validation_errors(errors)
        return 1
    args = build_service_args(paths, config, mark_seen=True)
    count = nga_feishu_watch.run_once(args)
    print(f"已标记 {count} 条为已读")
    return 0


def command_test_send(paths: CliPaths) -> int:
    config = load_service_config(paths)
    errors = nga_wolf_config.validate_config(config, require_cookie=False)
    if errors:
        print_validation_errors(errors)
        return 1
    args = build_service_args(paths, config)
    nga_feishu_watch.send_test_message(args)
    print("测试消息已发送")
    return 0
```

- [ ] **Step 5: Implement run command with foreground behavior**

Add to `ngawolf_cli.py`:

```python
def command_run(paths: CliPaths, *, once: bool = False) -> int:
    config = load_service_config(paths)
    errors = nga_wolf_config.validate_config(config)
    if errors:
        print_validation_errors(errors)
        return 1
    if once:
        args = build_service_args(paths, config)
        args.once = True
        nga_feishu_watch.run_once(args)
        return 0
    try:
        nga_wolf_config.run_watcher_from_config(paths.config_path, data_dir=paths.data_dir)
    except KeyboardInterrupt:
        print("已停止")
        return 130
    return 0
```

Update `main` dispatch:

```python
    if args.command == "check":
        return command_check(paths)
    if args.command == "mark-seen":
        return command_mark_seen(paths)
    if args.command == "test-send":
        return command_test_send(paths)
    if args.command == "run":
        return command_run(paths, once=bool(args.once))
```

- [ ] **Step 6: Run runtime CLI tests**

Run:

```bash
python -m pytest tests/test_ngawolf_cli.py -q
```

Expected: all CLI tests pass.

- [ ] **Step 7: Run all tests**

Run:

```bash
python -m pytest
```

Expected: all tests pass.

- [ ] **Step 8: Commit runtime commands**

```bash
git add ngawolf_cli.py tests/test_ngawolf_cli.py
git commit -m "feat: add linux service runtime commands"
```

---

### Task 5: Documentation and Smoke Verification

**Files:**
- Modify: `README.zh-CN.md`
- Optional Modify: `README.md`

- [ ] **Step 1: Add README section**

Add a Chinese section to `README.zh-CN.md` after the source CLI usage area:

```markdown
## Linux 服务器模式

Linux 服务器可以不启动桌面 GUI，直接使用 `ngawolf_cli.py` 生成配置并运行监听。

首次配置：

```bash
python ngawolf_cli.py init
```

修改配置：

```bash
python ngawolf_cli.py config
```

检查配置：

```bash
python ngawolf_cli.py check
```

初始化已读，避免第一次启动推送历史回复：

```bash
python ngawolf_cli.py mark-seen
```

前台运行服务：

```bash
python ngawolf_cli.py run
```

指定配置和数据目录：

```bash
python ngawolf_cli.py --config /etc/ngawolf/config.json --data-dir /var/lib/ngawolf run
```

默认配置路径是 `~/.config/ngawolf/config.json`，默认状态和日志目录是 `~/.local/state/ngawolf/`。相对状态路径会解析到数据目录下。
```

- [ ] **Step 2: Run markdown and Python smoke checks**

Run:

```bash
python ngawolf_cli.py --help
python ngawolf_cli.py run --help
python -m pytest
git diff --check
```

Expected:

- `python ngawolf_cli.py --help` prints command help and exits 0.
- `python ngawolf_cli.py run --help` prints run command help and exits 0.
- pytest passes.
- `git diff --check` exits 0.

- [ ] **Step 3: Commit docs**

```bash
git add README.zh-CN.md
git commit -m "docs: document linux cli service mode"
```

---

## Final Verification

Run:

```bash
python -m pytest
python ngawolf_cli.py --help
python ngawolf_cli.py check --config .does-not-exist.json
git status --short --branch
```

Expected:

- All tests pass.
- CLI help renders.
- Missing/empty default config produces validation errors and exits non-zero for `check`.
- Working tree contains only intentional changes or is clean after commits.

## Spec Coverage Review

- Headless Linux without GUI dependencies: covered by Task 1 extraction and Task 4 runtime commands.
- Shared watcher logic: covered by `nga_wolf_config.build_args` and `nga_wolf_config.run_watcher_from_config` reuse.
- Interactive `config.json` setup and editing: covered by Task 3.
- Foreground service execution: covered by Task 4 `command_run`.
- `check`, `mark-seen`, and `test-send`: covered by Task 4.
- Documentation: covered by Task 5.
- Web and full-screen TUI exclusion: preserved by using only line-based `input()`.
