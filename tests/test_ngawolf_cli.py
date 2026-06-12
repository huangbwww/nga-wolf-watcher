from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import ngawolf_cli
import nga_feishu_watch
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


def test_command_test_send_sends_each_structured_push_target(tmp_path: Path) -> None:
    paths = ngawolf_cli.CliPaths(
        config_path=tmp_path / "config.json",
        data_dir=tmp_path / "state",
        log_file=tmp_path / "watcher.log",
    )
    config = _valid_email_config()
    config["push_targets"] = json.dumps(
        [
            {"id": "feishu_1", "label": "Alpha", "channel": "feishu", "receive_id": "oc_1"},
            {"id": "email_1", "label": "ops@example.com", "channel": "email", "receive_id": "ops@example.com"},
            {"id": "wxpusher_1", "label": "WxPusher", "channel": "wxpusher", "id_type": "spt"},
        ],
        ensure_ascii=False,
    )
    base_args = argparse.Namespace(push_targets=config["push_targets"])
    scoped_args = [argparse.Namespace(target_id="feishu_1"), argparse.Namespace(target_id="email_1"), argparse.Namespace(target_id="wxpusher_1")]
    targets = [
        nga_feishu_watch.PushTarget(id="feishu_1", label="Alpha", channel="feishu", receive_id="oc_1"),
        nga_feishu_watch.PushTarget(id="email_1", label="ops@example.com", channel="email", receive_id="ops@example.com"),
        nga_feishu_watch.PushTarget(id="wxpusher_1", label="WxPusher", channel="wxpusher", id_type="spt"),
    ]

    with patch.object(ngawolf_cli, "load_service_config", return_value=config), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ), patch.object(ngawolf_cli, "build_service_args", return_value=base_args), patch.object(
        ngawolf_cli.nga_feishu_watch, "configured_push_targets", return_value=targets
    ) as configured_push_targets, patch.object(
        ngawolf_cli.nga_feishu_watch, "args_for_push_target", side_effect=scoped_args
    ) as args_for_push_target, patch.object(
        ngawolf_cli.nga_feishu_watch, "send_test_message", return_value=None
    ) as send_test_message:
        assert ngawolf_cli.command_test_send(paths) == 0

    configured_push_targets.assert_called_once_with(base_args)
    assert [call.args for call in args_for_push_target.call_args_list] == [(base_args, targets[0]), (base_args, targets[1]), (base_args, targets[2])]
    assert [call.args[0] for call in send_test_message.call_args_list] == scoped_args


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

    for key, value in config.items():
        if key in {"push_targets", "listen_rules"}:
            continue
        assert updated[key] == value
    assert updated is not config


def test_prompt_basic_config_updates_values_when_user_enters_replacements() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    inputs = [
        "add_email",
        "receiver@example.com",
        "sender@example.com",
        "done",
        "add_author",
        "10",
        "alpha",
        "add_thread",
        "20",
        "beta",
        "done",
        "add_thread_author",
        "",
        "",
        "",
        "done",
    ]

    with patch("builtins.input", side_effect=inputs), patch("getpass.getpass", side_effect=["new-cookie", "new-password"]):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated["bot_channel"] == "email"
    assert updated["nga_cookie"] == "new-cookie"
    assert updated["email_to"] == "receiver@example.com"
    assert updated["email_username"] == "sender@example.com"
    assert updated["email_password"] == "new-password"
    assert updated["watch_mode"] == "thread_author"
    assert updated["watch_author_ids"] == "10=alpha"
    assert updated["preset_thread_ids"] == "20=beta"
    assert updated["thread_author_watches"] == ""
    assert json.loads(str(updated["listen_rules"])) == [
        {
            "id": "thread_author:20:10",
            "label": "beta / alpha",
            "mode": "thread_author",
            "author_id": "10",
            "tid": "20",
            "target_ids": ["email_1"],
        }
    ]
    assert updated["interval"] == "30"
    assert updated["jitter"] == "5"
    assert updated["state_path"] == ".nga_seen.json"


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

    assert prompts == [
        "推送通道管理 [done]: ",
        "用户和帖子管理 [done]: ",
        "监听规则管理 [done]: ",
    ]
    assert updated["email_to"] == "receiver@example.com"
    assert updated["email_username"] == "sender@example.com"
    assert updated["email_password"] == "secret"
    assert getpass_mock.call_count == 1


def test_prompt_basic_config_uses_runtime_defaults_without_prompting_runtime_fields() -> None:
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
        return "done" if prompt.startswith("监听配置") else ""

    with patch("builtins.input", side_effect=record_prompt), patch("getpass.getpass", side_effect=["", ""]):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert not any("轮询间隔" in prompt or "随机抖动" in prompt or "状态文件路径" in prompt for prompt in prompts)
    assert updated["interval"] == "30"
    assert updated["jitter"] == "5"
    assert updated["state_path"] == ".nga_seen.json"


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


def test_run_channel_config_wechat_uses_qr_binding_instead_of_token_prompts(monkeypatch, capsys) -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    fake_wechat = SimpleNamespace(
        DEFAULT_WECHAT_BASE_URL="https://ilink.example",
        DEFAULT_WECHAT_CDN_BASE_URL="https://cdn.example",
        DEFAULT_WECHAT_QR_TIMEOUT_SECONDS=60,
        begin_qr_login=Mock(return_value={"qr_key": "qr-key", "qr_url": "https://qr.example/code"}),
        poll_qr_login=Mock(return_value={"token": "bot-token", "user_id": "wx-user", "account_id": "bot-account", "base_url": "https://bound.example"}),
    )
    monkeypatch.setattr(ngawolf_cli, "wechat_bot", fake_wechat, raising=False)
    monkeypatch.setattr(ngawolf_cli, "webbrowser", SimpleNamespace(open=Mock(return_value=True)), raising=False)

    with patch.object(ngawolf_cli, "prompt_text") as prompt_text:
        ngawolf_cli._run_channel_config(config, "wechat")

    prompt_text.assert_not_called()
    fake_wechat.begin_qr_login.assert_called_once_with("https://ilinkai.weixin.qq.com", route_tag="", timeout=40)
    fake_wechat.poll_qr_login.assert_called_once_with("qr-key", "https://ilinkai.weixin.qq.com", route_tag="", timeout_seconds=60)
    captured = capsys.readouterr()
    assert "微信扫码链接：https://qr.example/code" in captured.out
    assert config["bot_channel"] == "wechat"
    assert config["wechat_bot_token"] == "bot-token"
    assert config["wechat_bot_target_user_id"] == "wx-user"
    assert config["wechat_bot_allowed_user_ids"] == "wx-user"
    assert config["wechat_bot_account_id"] == "bot-account"
    expected_profile_id = nga_wolf_config.ensure_profile_id(
        "wechat",
        {
            "token": "bot-token",
            "account_id": "bot-account",
        },
    )
    assert json.loads(str(config["wechat_bot_profiles"])) == [
        {
            "id": expected_profile_id,
            "label": "wx-user",
            "token": "bot-token",
            "base_url": "https://bound.example",
            "cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",
            "target_user_id": "wx-user",
            "allowed_user_ids": "wx-user",
            "poll_timeout_ms": "35000",
            "route_tag": "",
            "account_id": "bot-account",
        }
    ]
    assert json.loads(str(config["push_targets"])) == [
        {
            "id": "wechat_1",
            "label": "wx-user",
            "channel": "wechat",
            "profile_id": expected_profile_id,
            "receive_id": "wx-user",
            "id_type": "user_id",
            "default_author_id": "150058",
            "default_tid": "45974302",
        }
    ]


def test_prompt_multi_select_supports_all_and_confirm() -> None:
    options = [
        {"value": "oc_1", "label": "Alpha"},
        {"value": "oc_2", "label": "Beta"},
    ]

    with patch("builtins.input", side_effect=["a", ""]):
        selected = ngawolf_cli.prompt_multi_select("Feishu groups", options)

    assert selected == options


class FakeQuestionaryPrompt:
    def __init__(self, answer):
        self.answer = answer

    def ask(self):
        return self.answer


class FakeQuestionary:
    def __init__(self, *, select_answer=None, checkbox_answer=None):
        self.select_answer = select_answer
        self.checkbox_answer = checkbox_answer
        self.select_calls = []
        self.checkbox_calls = []
        self.styles = []

    def Style(self, rules):
        self.styles.append(rules)
        return {"rules": rules}

    def select(self, message, choices, default=None, **kwargs):
        self.select_calls.append({"message": message, "choices": choices, "default": default, **kwargs})
        return FakeQuestionaryPrompt(self.select_answer)

    def checkbox(self, message, choices, **kwargs):
        self.checkbox_calls.append({"message": message, "choices": choices, **kwargs})
        return FakeQuestionaryPrompt(self.checkbox_answer)


def test_prompt_choice_uses_questionary_in_interactive_terminal(monkeypatch) -> None:
    fake = FakeQuestionary(select_answer="email")
    monkeypatch.setattr(ngawolf_cli, "questionary", fake)
    monkeypatch.setattr(ngawolf_cli, "is_interactive_terminal", lambda: True)

    with patch("builtins.input") as input_mock:
        selected = ngawolf_cli.prompt_choice("Bot channel", [("feishu", "Feishu"), ("email", "Email")], "feishu")

    assert selected == "email"
    assert fake.select_calls == [
        {
            "message": "Bot channel",
            "choices": [{"name": "Feishu", "value": "feishu"}, {"name": "Email", "value": "email"}],
            "default": "feishu",
            "instruction": "（使用方向键选择，回车确认）",
            "style": {"rules": fake.styles[0]},
        }
    ]
    assert ("highlighted", "fg:#00afff bg:#000000 bold noreverse") in fake.styles[0]
    input_mock.assert_not_called()


def test_configure_feishu_channel_can_select_a_listed_group_directly() -> None:
    config: dict[str, object] = {}
    chats = [
        {"chat_id": "oc_1", "name": "Alpha"},
        {"chat_id": "oc_2", "name": "Beta"},
    ]

    with patch.object(ngawolf_cli, "prompt_text", side_effect=["cli_xxx", "secret"]) as prompt_text, patch.object(
        ngawolf_cli, "prompt_choice", return_value="chat:oc_2"
    ) as prompt_choice, patch.object(ngawolf_cli, "prompt_multi_select") as prompt_multi_select, patch.object(
        ngawolf_cli.nga_feishu_watch, "list_feishu_chats", return_value=chats
    ):
        ngawolf_cli._configure_feishu_channel(config)

    prompt_choice.assert_called_once_with(
        "飞书发送目标",
        [("chat:oc_1", "群组：Alpha"), ("chat:oc_2", "群组：Beta"), ("multi", "选择多个群组"), ("manual", "手动填写 receive ID")],
        "chat:oc_1",
    )
    prompt_multi_select.assert_not_called()
    assert prompt_text.call_count == 2
    assert config["feishu_receive_id"] == "oc_2"


def test_configure_feishu_channel_can_select_multiple_listed_groups() -> None:
    config: dict[str, object] = {}
    chats = [
        {"chat_id": "oc_1", "name": "Alpha"},
        {"chat_id": "oc_2", "name": "Beta"},
    ]

    with patch.object(ngawolf_cli, "prompt_text", side_effect=["cli_xxx", "secret"]), patch.object(
        ngawolf_cli, "prompt_choice", return_value="multi"
    ), patch.object(ngawolf_cli, "prompt_multi_select", return_value=[{"value": "oc_1", "label": "Alpha"}, {"value": "oc_2", "label": "Beta"}]) as prompt_multi_select, patch.object(
        ngawolf_cli.nga_feishu_watch, "list_feishu_chats", return_value=chats
    ):
        ngawolf_cli._configure_feishu_channel(config)

    prompt_multi_select.assert_called_once_with(
        "选择飞书群组",
        [{"value": "oc_1", "label": "Alpha"}, {"value": "oc_2", "label": "Beta"}],
        selected_values=["oc_1"],
    )
    assert config["feishu_receive_id"] == "oc_1"


def test_configure_feishu_channel_can_choose_manual_receive_id_after_listing_groups() -> None:
    config: dict[str, object] = {}

    with patch.object(ngawolf_cli, "prompt_text", side_effect=["cli_xxx", "secret", "oc_manual"]) as prompt_text, patch.object(
        ngawolf_cli, "prompt_choice", return_value="manual"
    ) as prompt_choice, patch.object(ngawolf_cli, "prompt_multi_select") as prompt_multi_select, patch.object(
        ngawolf_cli.nga_feishu_watch, "list_feishu_chats", return_value=[{"chat_id": "oc_1", "name": "Alpha"}]
    ):
        ngawolf_cli._configure_feishu_channel(config)

    prompt_choice.assert_called_once()
    prompt_multi_select.assert_not_called()
    assert prompt_text.call_args_list[-1].args == ("飞书 receive ID", "")
    assert config["feishu_receive_id"] == "oc_manual"


def test_configure_watch_resources_adds_entries() -> None:
    config: dict[str, object] = {}

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["add_author", "add_thread", "done"]), patch.object(
        ngawolf_cli,
        "prompt_text",
        side_effect=["123", "Alice", "456", "Thread"],
    ):
        ngawolf_cli._configure_watch_resources(config)

    assert config["watch_author_ids"] == "123=Alice"
    assert config["preset_thread_ids"] == "456=Thread"


def test_configure_watch_resources_deletes_author_and_dependent_rules() -> None:
    config: dict[str, object] = {
        "watch_author_ids": "123=Alice\n789=Bob",
        "preset_thread_ids": "456=Thread",
        "listen_rules": json.dumps(
            [
                {"id": "author:123", "mode": "author", "author_id": "123", "tid": "", "target_ids": ["feishu_1"]},
                {"id": "thread_author:456:123", "mode": "thread_author", "author_id": "123", "tid": "456", "target_ids": ["feishu_1"]},
                {"id": "author:789", "mode": "author", "author_id": "789", "tid": "", "target_ids": ["feishu_1"]},
            ],
            ensure_ascii=False,
        ),
    }

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["delete_author", "123=Alice", "done"]):
        ngawolf_cli._configure_watch_resources(config)

    assert config["watch_author_ids"] == "789=Bob"
    assert config["preset_thread_ids"] == "456=Thread"
    assert json.loads(str(config["listen_rules"])) == [
        {"id": "author:789", "mode": "author", "author_id": "789", "tid": "", "target_ids": ["feishu_1"]}
    ]


def test_configure_watch_resources_deletes_thread_and_dependent_rules() -> None:
    config: dict[str, object] = {
        "watch_author_ids": "123=Alice",
        "preset_thread_ids": "456=Thread\n999=Other",
        "listen_rules": json.dumps(
            [
                {"id": "thread_author:456:123", "mode": "thread_author", "author_id": "123", "tid": "456", "target_ids": ["feishu_1"]},
                {"id": "thread_author:999:123", "mode": "thread_author", "author_id": "123", "tid": "999", "target_ids": ["feishu_1"]},
            ],
            ensure_ascii=False,
        ),
    }

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["delete_thread", "456=Thread", "done"]):
        ngawolf_cli._configure_watch_resources(config)

    assert config["watch_author_ids"] == "123=Alice"
    assert config["preset_thread_ids"] == "999=Other"
    assert json.loads(str(config["listen_rules"])) == [
        {"id": "thread_author:999:123", "mode": "thread_author", "author_id": "123", "tid": "999", "target_ids": ["feishu_1"]}
    ]


def test_configure_listen_rules_adds_thread_author_rule_with_selected_targets() -> None:
    config: dict[str, object] = {
        "watch_author_ids": "123=Alice",
        "preset_thread_ids": "456=Thread",
        "push_targets": json.dumps(
            [
                {"id": "feishu_1", "label": "Alpha", "channel": "feishu", "receive_id": "oc_1"},
                {"id": "wxpusher_1", "label": "WxPusher", "channel": "wxpusher", "receive_id": ""},
            ],
            ensure_ascii=False,
        ),
    }

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["add_thread_author", "456=Thread", "123=Alice", "done"]), patch.object(
        ngawolf_cli,
        "prompt_multi_select",
        return_value=[
            {"value": "feishu_1", "label": "Alpha"},
            {"value": "wxpusher_1", "label": "WxPusher"},
        ],
    ):
        ngawolf_cli._configure_listen_rules(config)

    assert config["watch_mode"] == "thread_author"
    assert json.loads(str(config["listen_rules"])) == [
        {
            "id": "thread_author:456:123",
            "label": "Thread / Alice",
            "mode": "thread_author",
            "author_id": "123",
            "tid": "456",
            "target_ids": ["feishu_1", "wxpusher_1"],
        }
    ]


def test_manage_push_targets_deletes_target_and_cleans_listen_rules() -> None:
    config: dict[str, object] = {
        "bot_channel": "feishu",
        "push_targets": json.dumps(
            [
                {"id": "feishu_1", "label": "Alpha", "channel": "feishu", "receive_id": "oc_1"},
                {"id": "email_1", "label": "ops@example.com", "channel": "email", "receive_id": "ops@example.com"},
            ],
            ensure_ascii=False,
        ),
        "listen_rules": json.dumps(
            [
                {"id": "author:123", "mode": "author", "author_id": "123", "tid": "", "target_ids": ["feishu_1", "email_1"]},
                {"id": "author:456", "mode": "author", "author_id": "456", "tid": "", "target_ids": ["feishu_1"]},
            ],
            ensure_ascii=False,
        ),
    }

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["delete", "feishu_1", "done"]):
        ngawolf_cli._manage_push_targets(config)

    assert json.loads(str(config["push_targets"])) == [
        {"id": "email_1", "label": "ops@example.com", "channel": "email", "receive_id": "ops@example.com"}
    ]
    assert json.loads(str(config["listen_rules"])) == [
        {"id": "author:123", "mode": "author", "author_id": "123", "tid": "", "target_ids": ["email_1"]}
    ]
    assert config["bot_channel"] == "email"


def test_manage_push_targets_tests_selected_target(capsys) -> None:
    config = _valid_email_config()
    config["push_targets"] = json.dumps(
        [
            {
                "id": "email_1",
                "label": "Ops Mail",
                "channel": "email",
                "profile_id": "default",
                "receive_id": "receiver@example.com",
                "id_type": "email",
            }
        ],
        ensure_ascii=False,
    )

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["test", "email_1", "done"]), patch.object(
        ngawolf_cli.nga_wolf_config, "validate_config", return_value=[]
    ) as validate_config, patch.object(ngawolf_cli.nga_feishu_watch, "send_test_message", return_value=None) as send_test_message:
        ngawolf_cli._manage_push_targets(config)

    validate_config.assert_called_once_with(config, require_cookie=False)
    send_test_message.assert_called_once()
    scoped_args = send_test_message.call_args.args[0]
    assert scoped_args.bot_channel == "email"
    assert scoped_args.email_to == "receiver@example.com"
    captured = capsys.readouterr()
    assert "正在测试推送通道：Ops Mail" in captured.out


def test_manage_push_targets_delete_last_target_clears_legacy_receive_field() -> None:
    config: dict[str, object] = {
        "bot_channel": "email",
        "email_to": "ops@example.com",
        "email_username": "sender@example.com",
        "email_password": "secret",
        "push_targets": json.dumps(
            [{"id": "email_1", "label": "ops@example.com", "channel": "email", "receive_id": "ops@example.com"}],
            ensure_ascii=False,
        ),
    }

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["delete", "email_1", "done"]):
        ngawolf_cli._manage_push_targets(config)

    assert json.loads(str(config["push_targets"])) == []
    assert config["email_to"] == ""
    assert config["email_username"] == "sender@example.com"
    assert config["bot_channel"] == "feishu"


def test_configure_listen_rules_views_readable_routes_and_deletes_rule(capsys) -> None:
    config: dict[str, object] = {
        "watch_author_ids": "123=Alice",
        "preset_thread_ids": "456=Thread",
        "push_targets": json.dumps(
            [
                {"id": "feishu_1", "label": "Alpha", "channel": "feishu", "receive_id": "oc_1"},
                {"id": "wxpusher_1", "label": "WxPusher", "channel": "wxpusher", "receive_id": "", "id_type": "spt"},
            ],
            ensure_ascii=False,
        ),
        "listen_rules": json.dumps(
            [
                {
                    "id": "thread_author:456:123",
                    "label": "Thread / Alice",
                    "mode": "thread_author",
                    "author_id": "123",
                    "tid": "456",
                    "target_ids": ["feishu_1", "wxpusher_1"],
                }
            ],
            ensure_ascii=False,
        ),
    }

    with patch.object(ngawolf_cli, "prompt_choice", side_effect=["view", "delete", "thread_author:456:123", "done"]), patch.object(
        ngawolf_cli, "prompt_multi_select", return_value=[]
    ):
        ngawolf_cli._configure_listen_rules(config)

    captured = capsys.readouterr()
    assert "帖子内监听：Thread (456) / Alice (123) -> Alpha (Feishu / oc_1)、WxPusher (WxPusher / SPT)" in captured.out
    assert json.loads(str(config["listen_rules"])) == []


def test_prompt_multi_select_uses_questionary_checkbox_in_interactive_terminal(monkeypatch) -> None:
    fake = FakeQuestionary(checkbox_answer=["oc_2"])
    monkeypatch.setattr(ngawolf_cli, "questionary", fake)
    monkeypatch.setattr(ngawolf_cli, "is_interactive_terminal", lambda: True)
    options = [
        {"value": "oc_1", "label": "Alpha"},
        {"value": "oc_2", "label": "Beta"},
    ]

    with patch("builtins.input") as input_mock:
        selected = ngawolf_cli.prompt_multi_select("Feishu groups", options, selected_values=["oc_1"])

    assert selected == [{"value": "oc_2", "label": "Beta"}]
    assert fake.checkbox_calls == [
        {
            "message": "Feishu groups",
            "choices": [
                {"name": "Alpha", "value": "oc_1", "checked": True},
                {"name": "Beta", "value": "oc_2", "checked": False},
            ],
            "instruction": "（使用方向键移动，空格选择/取消，回车确认）",
            "style": {"rules": fake.styles[0]},
        }
    ]
    assert ("highlighted", "fg:#00afff bg:#000000 bold noreverse") in fake.styles[0]
    input_mock.assert_not_called()


def test_prompt_choice_reprompts_after_invalid_selection() -> None:
    with patch("builtins.input", side_effect=["invalid", "2"]):
        selected = ngawolf_cli.prompt_choice("Bot channel", [("feishu", "Feishu"), ("email", "Email")], "feishu")

    assert selected == "email"


def test_prompt_basic_config_lists_feishu_chats_and_builds_routes() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    inputs = [
        "",
        "cli_xxx",
        "multi",
        "a",
        "",
        "",
        "add_author",
        "150058",
        "wolf",
        "done",
        "add_author",
        "",
        "",
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
            "label": "默认飞书机器人",
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


def test_prompt_basic_config_builds_wxpusher_spt_profile_and_routes(monkeypatch) -> None:
    monkeypatch.setattr(ngawolf_cli, "questionary", None)
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    inputs = [
        "add_wxpusher",
        "",
        "",
        "",
        "add_author",
        "150058",
        "wolf",
        "done",
        "add_author",
        "",
        "",
        "",
        "",
        "",
    ]

    with patch("builtins.input", side_effect=inputs), patch("getpass.getpass", side_effect=["cookie", "SPT_secret"]):
        updated = ngawolf_cli.prompt_basic_config(config)

    assert updated["bot_channel"] == "wxpusher"
    assert updated["nga_cookie"] == "cookie"
    assert updated["wxpusher_spts"] == "SPT_secret"
    assert updated["wxpusher_app_token"] == ""
    assert updated["wxpusher_uids"] == ""
    assert updated["wxpusher_topic_ids"] == ""
    assert updated["wxpusher_content_type"] == "markdown"

    assert json.loads(str(updated["wxpusher_profiles"])) == [
        {
            "id": "default",
            "label": "Default WxPusher",
            "spts": "SPT_secret",
            "app_token": "",
            "uids": "",
            "topic_ids": "",
            "content_type": "markdown",
        }
    ]
    assert json.loads(str(updated["push_targets"])) == [
        {
            "id": "wxpusher_1",
            "label": "Default WxPusher",
            "channel": "wxpusher",
            "profile_id": "default",
            "receive_id": "",
            "id_type": "spt",
            "default_author_id": "150058",
            "default_tid": "45974302",
        }
    ]
    assert json.loads(str(updated["listen_rules"])) == [
        {
            "id": "author:150058",
            "label": "wolf",
            "mode": "author",
            "author_id": "150058",
            "tid": "",
            "target_ids": ["wxpusher_1"],
        }
    ]
    assert nga_wolf_config.validate_config(updated, require_cookie=True) == []


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
