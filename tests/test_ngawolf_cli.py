from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import ngawolf_cli
import nga_wolf_config


def test_parse_args_accepts_supported_commands() -> None:
    for command in ["init", "config", "run", "check", "mark-seen", "test-send"]:
        args = ngawolf_cli.parse_args([command])

        assert args.command == command


def test_resolve_cli_paths_defaults_without_xdg(monkeypatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/tester")))

    paths = ngawolf_cli.resolve_cli_paths(ngawolf_cli.parse_args(["check"]))

    assert paths.config_path == Path("/home/tester/.config/ngawolf/config.json")
    assert paths.data_dir == Path("/home/tester/.local/state/ngawolf")
    assert paths.log_file == Path("/home/tester/.local/state/ngawolf/watcher.log")


def test_resolve_cli_paths_honors_explicit_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "cfg.json"
    data_dir = tmp_path / "state"
    log_file = tmp_path / "watcher.log"

    args = ngawolf_cli.parse_args(
        [
            "--config",
            str(config_path),
            "--data-dir",
            str(data_dir),
            "--log-file",
            str(log_file),
            "run",
        ]
    )

    paths = ngawolf_cli.resolve_cli_paths(args)

    assert paths.config_path == config_path
    assert paths.data_dir == data_dir
    assert paths.log_file == log_file


def test_resolve_cli_paths_expands_user_home_overrides(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    args = ngawolf_cli.parse_args(
        [
            "--config",
            "~/cfg.json",
            "--data-dir",
            "~/state",
            "--log-file",
            "~/watcher.log",
            "check",
        ]
    )

    paths = ngawolf_cli.resolve_cli_paths(args)

    assert paths.config_path == tmp_path / "cfg.json"
    assert paths.data_dir == tmp_path / "state"
    assert paths.log_file == tmp_path / "watcher.log"


def test_run_once_flag_is_set() -> None:
    args = ngawolf_cli.parse_args(["run", "--once"])

    assert args.command == "run"
    assert args.once is True


def test_prompt_basic_config_keeps_existing_values_when_user_presses_enter() -> None:
    config = {
        "bot_channel": "feishu",
        "nga_cookie": "cookie",
        "email_to": "receiver@example.com",
        "email_username": "sender@example.com",
        "email_password": "secret",
        "feishu_app_id": "app",
        "feishu_app_secret": "secret",
        "feishu_receive_id": "chat",
        "wechat_bot_token": "token",
        "wechat_bot_target_user_id": "user",
        "dingtalk_client_id": "client",
        "dingtalk_client_secret": "secret",
        "dingtalk_target_user_ids": "a;b",
        "watch_mode": "both",
        "watch_author_ids": "1=alpha",
        "preset_thread_ids": "2=beta",
        "interval": "15",
        "jitter": "3",
        "state_path": "state.json",
    }

    with patch("builtins.input", side_effect=[""] * 11):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated == config
    assert updated is not config


def test_prompt_basic_config_updates_values_when_user_enters_replacements() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    inputs = [
        "wechat",
        "new-cookie",
        "new-token",
        "new-user-id",
        "thread_author",
        "10=alpha",
        "20=beta",
        "45",
        "9",
        "runtime/state.json",
    ]

    with patch("builtins.input", side_effect=inputs):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated["bot_channel"] == "wechat"
    assert updated["nga_cookie"] == "new-cookie"
    assert updated["wechat_bot_token"] == "new-token"
    assert updated["wechat_bot_target_user_id"] == "new-user-id"
    assert updated["watch_mode"] == "thread_author"
    assert updated["watch_author_ids"] == "10=alpha"
    assert updated["preset_thread_ids"] == "20=beta"
    assert updated["interval"] == "45"
    assert updated["jitter"] == "9"
    assert updated["state_path"] == "runtime/state.json"


def test_prompt_basic_config_prompts_only_email_fields_for_email_channel() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update(
        {
            "bot_channel": "email",
            "nga_cookie": "cookie",
            "email_to": "receiver@example.com",
            "email_username": "sender@example.com",
            "email_password": "secret",
        }
    )
    prompts: list[str] = []

    def record_prompt(prompt: str = "") -> str:
        prompts.append(prompt)
        return ""

    with patch("builtins.input", side_effect=record_prompt):
        updated = ngawolf_cli.prompt_basic_config(config)

    watch_author_default = str(nga_wolf_config.DEFAULT_CONFIG["watch_author_ids"])
    preset_thread_default = str(nga_wolf_config.DEFAULT_CONFIG["preset_thread_ids"])
    assert prompts == [
        "Bot channel [email]: ",
        "NGA cookie [hidden]: ",
        "Email to [receiver@example.com]: ",
        "Email username [sender@example.com]: ",
        "Email password [hidden]: ",
        "Watch mode [author]: ",
        f"Watch author IDs [{watch_author_default}]: ",
        f"Preset thread IDs [{preset_thread_default}]: ",
        "Interval [30]: ",
        "Jitter [20]: ",
        "State path [.nga_seen.json]: ",
    ]
    assert updated["email_to"] == "receiver@example.com"
    assert updated["email_username"] == "sender@example.com"
    assert updated["email_password"] == "secret"
    assert len(prompts) == 11


def test_prompt_text_masks_existing_secret_value_in_prompt() -> None:
    prompts: list[str] = []

    def record_prompt(prompt: str = "") -> str:
        prompts.append(prompt)
        return ""

    with patch("builtins.input", side_effect=record_prompt):
        assert ngawolf_cli.prompt_text("Token", "secret-value", secret=True) == "secret-value"

    assert prompts == ["Token [hidden]: "]


def test_prompt_text_trims_whitespace_and_preserves_current_on_blank_spaces() -> None:
    with patch("builtins.input", side_effect=["   "]):
        assert ngawolf_cli.prompt_text("Label", "old") == "old"

    with patch("builtins.input", side_effect=["  new value  "]):
        assert ngawolf_cli.prompt_text("Label", "old") == "new value"


def test_command_init_refuses_to_overwrite_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    paths = ngawolf_cli.CliPaths(
        config_path=config_path,
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )

    with patch.object(ngawolf_cli, "prompt_basic_config") as prompt_basic_config:
        assert ngawolf_cli.command_init(paths) == 2

    prompt_basic_config.assert_not_called()
    assert json.loads(config_path.read_text(encoding="utf-8")) == {}


def test_command_init_creates_config_file_when_missing(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    paths = ngawolf_cli.CliPaths(
        config_path=config_path,
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    expected_config = {"bot_channel": "email", "nga_cookie": "cookie"}

    with patch.object(ngawolf_cli, "prompt_basic_config", return_value=expected_config):
        assert ngawolf_cli.command_init(paths) == 0

    assert json.loads(config_path.read_text(encoding="utf-8")) == expected_config


def test_command_config_updates_existing_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    base_config = dict(nga_wolf_config.DEFAULT_CONFIG)
    base_config["bot_channel"] = "feishu"
    nga_wolf_config.save_config(base_config, config_path)
    paths = ngawolf_cli.CliPaths(
        config_path=config_path,
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    updated_config = dict(base_config)
    updated_config["bot_channel"] = "wechat"
    updated_config["wechat_bot_target_user_id"] = "new-user"

    with patch.object(ngawolf_cli, "prompt_basic_config", return_value=updated_config):
        assert ngawolf_cli.command_config(paths) == 0

    assert json.loads(config_path.read_text(encoding="utf-8")) == updated_config


def test_command_config_rejects_malformed_json_without_overwriting(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    original_text = "{not valid json"
    config_path.write_text(original_text, encoding="utf-8")
    paths = ngawolf_cli.CliPaths(
        config_path=config_path,
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )

    with patch.object(ngawolf_cli, "prompt_basic_config") as prompt_basic_config:
        assert ngawolf_cli.command_config(paths) == 2

    prompt_basic_config.assert_not_called()
    assert config_path.read_text(encoding="utf-8") == original_text
