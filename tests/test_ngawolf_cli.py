from __future__ import annotations

import argparse
import json
from pathlib import Path
from unittest.mock import patch

import ngawolf_cli
import nga_wolf_config


def _valid_email_config() -> dict[str, object]:
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
    return config


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


def test_load_service_config_uses_shared_loader(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    paths = ngawolf_cli.CliPaths(
        config_path=config_path,
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )

    with patch.object(nga_wolf_config, "load_config", return_value={"bot_channel": "email"}) as load_config:
        assert ngawolf_cli.load_service_config(paths) == {"bot_channel": "email"}

    load_config.assert_called_once_with(config_path, nga_wolf_config.DEFAULT_CONFIG)


def test_build_service_args_creates_data_dir_and_uses_shared_builder(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()

    with patch.object(nga_wolf_config, "build_args", return_value={"args": True}) as build_args:
        result = ngawolf_cli.build_service_args(paths, config, mark_seen=True)

    assert paths.data_dir.exists()
    assert result == {"args": True}
    build_args.assert_called_once_with(config, data_dir=paths.data_dir, mark_seen=True)


def test_print_validation_errors_prints_each_error(capsys) -> None:
    ngawolf_cli.print_validation_errors(["first", "second"])

    captured = capsys.readouterr()
    assert captured.err == "first\nsecond\n"
    assert captured.out == ""


def test_command_check_returns_non_zero_for_invalid_config(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )

    with patch.object(ngawolf_cli, "load_service_config", return_value=dict(nga_wolf_config.DEFAULT_CONFIG)), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=["missing target"]
    ) as validate_config, patch.object(ngawolf_cli, "print_validation_errors") as print_validation_errors:
        assert ngawolf_cli.command_check(paths) == 2

    validate_config.assert_called_once_with(dict(nga_wolf_config.DEFAULT_CONFIG), require_cookie=True)
    print_validation_errors.assert_called_once_with(["missing target"])


def test_command_check_returns_zero_for_valid_config(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ) as validate_config, patch.object(ngawolf_cli, "print_validation_errors") as print_validation_errors:
        assert ngawolf_cli.command_check(paths) == 0

    validate_config.assert_called_once_with(config, require_cookie=True)
    print_validation_errors.assert_not_called()


def test_command_mark_seen_validates_and_runs_once(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update(
        {
            "bot_channel": "feishu",
            "nga_cookie": "cookie",
            "feishu_app_id": "app-id",
            "feishu_app_secret": "app-secret",
            "watch_author_ids": "150058=author",
            "preset_thread_ids": "45974302=thread",
        }
    )
    args = argparse.Namespace()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli, "validate_mark_seen_config", return_value=[]
    ) as validate_mark_seen_config, patch.object(ngawolf_cli, "build_service_args", return_value=args) as build_service_args, patch.object(
        ngawolf_cli.nga_feishu_watch, "run_once", return_value=1
    ) as run_once:
        assert ngawolf_cli.command_mark_seen(paths) == 0

    validate_mark_seen_config.assert_called_once_with(config)
    build_service_args.assert_called_once_with(paths, config, mark_seen=True)
    run_once.assert_called_once_with(args)


def test_command_mark_seen_accepts_minimal_config_without_delivery_credentials(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = {
        "bot_channel": "email",
        "nga_cookie": "cookie",
        "watch_mode": "author",
        "watch_author_ids": "150058=author",
        "preset_thread_ids": "45974302=thread",
    }
    args = argparse.Namespace()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli, "build_service_args", return_value=args
    ) as build_service_args, patch.object(ngawolf_cli.nga_feishu_watch, "run_once", return_value=1) as run_once:
        assert ngawolf_cli.command_mark_seen(paths) == 0

    build_service_args.assert_called_once_with(paths, config, mark_seen=True)
    run_once.assert_called_once_with(args)


def test_command_mark_seen_rejects_malformed_author_selector(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = {
        "bot_channel": "email",
        "nga_cookie": "cookie",
        "watch_mode": "author",
        "watch_author_ids": "=",
    }

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_feishu_watch, "run_once"
    ) as run_once:
        assert ngawolf_cli.command_mark_seen(paths) != 0

    run_once.assert_not_called()


def test_command_mark_seen_rejects_thread_author_mode_without_selectors(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = {
        "bot_channel": "email",
        "nga_cookie": "cookie",
        "watch_mode": "thread_author",
        "thread_author_watches": "",
    }

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_feishu_watch, "run_once"
    ) as run_once:
        assert ngawolf_cli.command_mark_seen(paths) != 0

    run_once.assert_not_called()


def test_command_mark_seen_rejects_both_mode_without_thread_author_selectors(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = {
        "bot_channel": "email",
        "nga_cookie": "cookie",
        "watch_mode": "both",
        "watch_author_ids": "150058",
        "thread_author_watches": "",
        "listen_rules": "",
    }

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_feishu_watch, "run_once"
    ) as run_once:
        assert ngawolf_cli.command_mark_seen(paths) != 0

    run_once.assert_not_called()


def test_command_mark_seen_accepts_thread_author_watch_without_delivery_credentials(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = {
        "bot_channel": "email",
        "nga_cookie": "cookie",
        "watch_mode": "thread_author",
        "thread_author_watches": "45974302:150058",
    }
    args = argparse.Namespace()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli, "build_service_args", return_value=args
    ) as build_service_args, patch.object(ngawolf_cli.nga_feishu_watch, "run_once", return_value=1) as run_once:
        assert ngawolf_cli.command_mark_seen(paths) == 0

    build_service_args.assert_called_once_with(paths, config, mark_seen=True)
    run_once.assert_called_once_with(args)


def test_command_test_send_validates_without_cookie_and_sends_test_message(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()
    config["nga_cookie"] = ""
    args = argparse.Namespace()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ) as validate_config, patch.object(ngawolf_cli, "build_service_args", return_value=args) as build_service_args, patch.object(
        ngawolf_cli.nga_feishu_watch, "send_test_message", return_value=None
    ) as send_test_message:
        assert ngawolf_cli.command_test_send(paths) == 0

    validate_config.assert_called_once_with(config, require_cookie=False)
    build_service_args.assert_called_once_with(paths, config, mark_seen=False)
    send_test_message.assert_called_once_with(args)


def test_command_run_once_validates_and_runs_once(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()
    args = argparse.Namespace()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ) as validate_config, patch.object(ngawolf_cli, "build_service_args", return_value=args) as build_service_args, patch.object(
        ngawolf_cli.nga_feishu_watch, "run_once", return_value=1
    ) as run_once:
        assert ngawolf_cli.command_run(paths, once=True) == 0

    validate_config.assert_called_once_with(config, require_cookie=True)
    build_service_args.assert_called_once_with(paths, config, mark_seen=False)
    run_once.assert_called_once_with(args)


def test_command_run_once_returns_130_on_keyboard_interrupt(tmp_path: Path, capsys) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()
    args = argparse.Namespace()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ), patch.object(ngawolf_cli, "build_service_args", return_value=args), patch.object(
        ngawolf_cli.nga_feishu_watch, "run_once", side_effect=KeyboardInterrupt
    ):
        assert ngawolf_cli.command_run(paths, once=True) == 130

    captured = capsys.readouterr()
    assert "stopped" in captured.err.lower()


def test_command_run_long_running_delegates_to_shared_watcher(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ) as validate_config, patch.object(ngawolf_cli.nga_wolf_config, "run_watcher_from_config", return_value=None) as run_watcher_from_config:
        assert ngawolf_cli.command_run(paths, once=False) == 0

    validate_config.assert_called_once_with(config, require_cookie=True)
    run_watcher_from_config.assert_called_once_with(paths.config_path, data_dir=paths.data_dir)


def test_command_run_long_running_handles_keyboard_interrupt(tmp_path: Path, capsys) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ), patch.object(ngawolf_cli.nga_wolf_config, "run_watcher_from_config", side_effect=KeyboardInterrupt):
        assert ngawolf_cli.command_run(paths, once=False) == 130

    captured = capsys.readouterr()
    assert "stopped" in captured.err.lower()


def test_main_dispatches_runtime_commands(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    data_dir = tmp_path / "state"
    log_file = tmp_path / "watcher.log"

    cases = [
        ("check", "command_check"),
        ("mark-seen", "command_mark_seen"),
        ("test-send", "command_test_send"),
        ("run", "command_run"),
    ]
    for command, handler_name in cases:
        with patch.object(ngawolf_cli, "parse_args", return_value=argparse.Namespace(command=command, config=config_path, data_dir=data_dir, log_file=log_file)) as parse_args, patch.object(
            ngawolf_cli, "resolve_cli_paths", return_value=ngawolf_cli.CliPaths(config_path=config_path, data_dir=data_dir, log_file=log_file)
        ) as resolve_cli_paths, patch.object(ngawolf_cli, handler_name, return_value=0) as handler:
            assert ngawolf_cli.main([command]) == 0

        parse_args.assert_called_once_with([command])
        resolve_cli_paths.assert_called_once()
        handler.assert_called_once()


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
        "feishu_id_type": "chat_id",
        "feishu_bot_profiles": json.dumps(
            [
                {
                    "id": "default",
                    "label": "Default Feishu bot",
                    "app_id": "app",
                    "app_secret": "secret",
                    "id_type": "chat_id",
                    "chats": [],
                }
            ],
            ensure_ascii=False,
        ),
        "wechat_bot_token": "token",
        "wechat_bot_target_user_id": "user",
        "dingtalk_client_id": "client",
        "dingtalk_client_secret": "secret",
        "dingtalk_target_user_ids": "a;b",
        "watch_mode": "both",
        "watch_author_ids": "1=alpha",
        "preset_thread_ids": "2=beta",
        "thread_author_watches": "2:1=beta",
        "interval": "15",
        "jitter": "3",
        "state_path": "state.json",
    }

    with patch("builtins.input", side_effect=[""] * 10), patch("getpass.getpass", side_effect=["", ""]):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated == config
    assert updated is not config


def test_prompt_basic_config_updates_values_when_user_enters_replacements() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    inputs = [
        "wechat",
        "new-user-id",
        "thread_author",
        "10=alpha",
        "20=beta",
        "20:10=alpha in thread",
        "45",
        "9",
        "runtime/state.json",
    ]

    with patch("builtins.input", side_effect=inputs), patch("getpass.getpass", side_effect=["new-cookie", "new-token"]):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated["bot_channel"] == "wechat"
    assert updated["nga_cookie"] == "new-cookie"
    assert updated["wechat_bot_token"] == "new-token"
    assert updated["wechat_bot_target_user_id"] == "new-user-id"
    assert updated["watch_mode"] == "thread_author"
    assert updated["watch_author_ids"] == "10=alpha"
    assert updated["preset_thread_ids"] == "20=beta"
    assert updated["thread_author_watches"] == "20:10=alpha in thread"
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

    with patch("builtins.input", side_effect=record_prompt), patch("getpass.getpass", side_effect=["cookie", "secret"]) as getpass_mock:
        updated = ngawolf_cli.prompt_basic_config(config)

    watch_author_default = str(nga_wolf_config.DEFAULT_CONFIG["watch_author_ids"])
    preset_thread_default = str(nga_wolf_config.DEFAULT_CONFIG["preset_thread_ids"])
    assert prompts == [
        "Bot channel [email]: ",
        "Email to [receiver@example.com]: ",
        "Email username [sender@example.com]: ",
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
    assert getpass_mock.call_count == 2


def test_prompt_text_uses_getpass_for_secret_input_and_trims_value() -> None:
    with patch("getpass.getpass", return_value="  secret-value  ") as getpass_mock, patch("builtins.input") as input_mock:
        assert ngawolf_cli.prompt_text("Token", "current", secret=True) == "secret-value"

    getpass_mock.assert_called_once_with("Token [hidden]: ")
    input_mock.assert_not_called()


def test_prompt_text_trims_whitespace_and_preserves_current_on_blank_spaces() -> None:
    with patch("getpass.getpass", return_value="   "), patch("builtins.input") as input_mock:
        assert ngawolf_cli.prompt_text("Label", "old", secret=True) == "old"
    input_mock.assert_not_called()

    with patch("getpass.getpass", return_value="  new value  "):
        assert ngawolf_cli.prompt_text("Label", "old", secret=True) == "new value"


def test_prompt_basic_config_normalizes_bot_channel_and_prompts_wechat_fields() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config["nga_cookie"] = "cookie"
    config["wechat_bot_token"] = "token"
    prompts: list[str] = []
    inputs = iter(["WeChat", "", "", "", "", "", "", ""])

    def record_input(prompt: str = "") -> str:
        prompts.append(prompt)
        return next(inputs)

    with patch("builtins.input", side_effect=record_input), patch("getpass.getpass", side_effect=["cookie", "token"]) as getpass_mock:
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated["bot_channel"] == "wechat"
    assert prompts == [
        "Bot channel [feishu]: ",
        "WeChat target user ID: ",
        "Watch mode [author]: ",
        "Watch author IDs [150058=狼大]: ",
        "Preset thread IDs [45974302=自立自强，科学技术打头阵]: ",
        "Interval [30]: ",
        "Jitter [20]: ",
        "State path [.nga_seen.json]: ",
    ]
    assert getpass_mock.call_args_list[0].args == ("NGA cookie [hidden]: ",)
    assert getpass_mock.call_args_list[1].args == ("WeChat bot token [hidden]: ",)


def test_prompt_multi_select_supports_all_and_confirm() -> None:
    options = [
        {"value": "oc_1", "label": "Alpha"},
        {"value": "oc_2", "label": "Beta"},
    ]

    with patch("builtins.input", side_effect=["a", ""]):
        selected = ngawolf_cli.prompt_multi_select("Feishu groups", options)

    assert selected == options


def test_prompt_choice_reprompts_after_invalid_selection() -> None:
    with patch("builtins.input", side_effect=["invalid", "2"]):
        selected = ngawolf_cli.prompt_choice("Bot channel", [("feishu", "Feishu"), ("email", "Email")], "feishu")

    assert selected == "email"


def test_prompt_basic_config_lists_feishu_chats_and_builds_routes() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    inputs = [
        "",
        "cli_xxx",
        "a",
        "",
        "",
        "150058=wolf",
        "45974302=wolf",
        "",
        "",
        "",
    ]
    chats = [
        {"chat_id": "oc_1", "name": "Alpha"},
        {"chat_id": "oc_2", "name": "Beta"},
    ]
    normalized_chats = [
        {"chat_id": "oc_1", "name": "Alpha", "chat_type": "", "description": ""},
        {"chat_id": "oc_2", "name": "Beta", "chat_type": "", "description": ""},
    ]

    with patch("builtins.input", side_effect=inputs), patch("getpass.getpass", side_effect=["cookie", "secret"]), patch.object(
        ngawolf_cli.nga_feishu_watch, "list_feishu_chats", return_value=chats
    ) as list_feishu_chats:
        updated = ngawolf_cli.prompt_basic_config(config)

    list_feishu_chats.assert_called_once_with("cli_xxx", "secret", 10)
    assert updated["bot_channel"] == "feishu"
    assert updated["nga_cookie"] == "cookie"
    assert updated["feishu_app_id"] == "cli_xxx"
    assert updated["feishu_app_secret"] == "secret"
    assert updated["feishu_receive_id"] == "oc_1"

    profiles = json.loads(str(updated["feishu_bot_profiles"]))
    assert profiles == [
        {
            "id": "default",
            "label": "Default Feishu bot",
            "app_id": "cli_xxx",
            "app_secret": "secret",
            "id_type": "chat_id",
            "chats": normalized_chats,
        }
    ]

    targets = json.loads(str(updated["push_targets"]))
    assert targets == [
        {
            "id": "feishu_1",
            "label": "Alpha",
            "channel": "feishu",
            "profile_id": "default",
            "receive_id": "oc_1",
            "id_type": "chat_id",
            "default_author_id": "150058",
            "default_tid": "45974302",
        },
        {
            "id": "feishu_2",
            "label": "Beta",
            "channel": "feishu",
            "profile_id": "default",
            "receive_id": "oc_2",
            "id_type": "chat_id",
            "default_author_id": "150058",
            "default_tid": "45974302",
        },
    ]

    rules = json.loads(str(updated["listen_rules"]))
    assert rules == [
        {
            "id": "author:150058",
            "label": "wolf",
            "mode": "author",
            "author_id": "150058",
            "tid": "",
            "target_ids": ["feishu_1", "feishu_2"],
        }
    ]


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


def test_command_init_rejects_invalid_bot_channel_without_saving(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    paths = ngawolf_cli.CliPaths(
        config_path=config_path,
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )

    with patch.object(ngawolf_cli, "prompt_basic_config", side_effect=ValueError("bad config")):
        assert ngawolf_cli.command_init(paths) == 2

    assert not config_path.exists()


def test_command_config_rejects_invalid_bot_channel_without_overwriting(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    base_config = dict(nga_wolf_config.DEFAULT_CONFIG)
    nga_wolf_config.save_config(base_config, config_path)
    original_text = config_path.read_text(encoding="utf-8")
    paths = ngawolf_cli.CliPaths(
        config_path=config_path,
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )

    with patch.object(ngawolf_cli, "prompt_basic_config", side_effect=ValueError("bad config")):
        assert ngawolf_cli.command_config(paths) == 2

    assert config_path.read_text(encoding="utf-8") == original_text
