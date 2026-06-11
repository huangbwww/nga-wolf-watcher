from __future__ import annotations

import json
from pathlib import Path

import nga_wolf_config


def test_linux_config_path_defaults_without_xdg(monkeypatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/tester")))

    assert nga_wolf_config.linux_config_path() == Path("/home/tester/.config/ngawolf/config.json")


def test_linux_data_dir_defaults_without_xdg(monkeypatch) -> None:
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: Path("/home/tester")))

    assert nga_wolf_config.linux_data_dir() == Path("/home/tester/.local/state/ngawolf")


def test_linux_paths_honor_xdg_overrides(monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "/tmp/xdg-config")
    monkeypatch.setenv("XDG_STATE_HOME", "/tmp/xdg-state")

    assert nga_wolf_config.linux_config_path() == Path("/tmp/xdg-config/ngawolf/config.json")
    assert nga_wolf_config.linux_data_dir() == Path("/tmp/xdg-state/ngawolf")


def test_resolved_state_path_uses_supplied_data_dir_for_relative_paths(tmp_path: Path) -> None:
    config = {"state_path": "seen/state.json"}

    assert nga_wolf_config.resolved_state_path(config, data_dir=tmp_path) == tmp_path / "seen" / "state.json"


def test_load_and_save_config_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = {
        "nga_cookie": "cookie",
        "interval": "15",
        "email_smtp_profiles": json.dumps(
            [
                {
                    "id": "mail",
                    "username": "sender@example.com",
                    "password": "secret",
                    "from_email": "sender@example.com",
                }
            ]
        ),
    }

    nga_wolf_config.save_config(config, path)

    loaded = nga_wolf_config.load_config(path)

    assert loaded["nga_cookie"] == "cookie"
    assert loaded["interval"] == "15"
    assert loaded["email_smtp_profiles"] == config["email_smtp_profiles"]


def test_build_args_resolves_state_and_ai_work_dir_under_data_dir(tmp_path: Path) -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update(
        {
            "nga_cookie": "cookie",
            "state_path": "state/seen.json",
            "ai_work_dir": "agent/work",
            "email_to": "receiver@example.com",
            "email_smtp_profiles": json.dumps(
                [
                    {
                        "id": "gmail",
                        "smtp_host": "smtp.example.com",
                        "smtp_port": "2525",
                        "smtp_security": "ssl",
                        "username": "sender@example.com",
                        "password": "secret",
                        "from_email": "sender@example.com",
                        "from_name": "Watcher Sender",
                        "reply_to": "reply@example.com",
                    }
                ]
            ),
        }
    )

    args = nga_wolf_config.build_args(config, data_dir=tmp_path)

    assert Path(args.state_path) == tmp_path / "state" / "seen.json"
    assert Path(args.ai_work_dir) == tmp_path / "agent" / "work"
    assert args.email_smtp_profiles == config["email_smtp_profiles"]
    assert args.email_to == "receiver@example.com"
    assert args.email_username == ""
    assert args.email_from_name == "NGA Wolf Watcher"


def test_validate_config_reports_missing_cookie_and_invalid_email_requirements() -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update(
        {
            "bot_channel": "email",
            "nga_cookie": "",
            "email_to": "",
            "email_smtp_profiles": json.dumps(
                [
                    {
                        "id": "mail",
                        "username": "",
                        "password": "",
                        "from_email": "sender@example.com",
                    }
                ]
            ),
        }
    )

    errors = nga_wolf_config.validate_config(config)

    assert "NGA Cookie" in errors
    assert len(errors) >= 4
