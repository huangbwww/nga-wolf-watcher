from __future__ import annotations

from pathlib import Path

import ngawolf_cli


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


def test_run_once_flag_is_set() -> None:
    args = ngawolf_cli.parse_args(["run", "--once"])

    assert args.command == "run"
    assert args.once is True
