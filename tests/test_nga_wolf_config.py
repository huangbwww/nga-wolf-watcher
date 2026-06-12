from __future__ import annotations

import importlib
import json
import sys
import types
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


def test_load_config_accepts_jsonc_comments_and_urls(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(
        """
{
  // 行注释可以写中文说明
  "nga_cookie": "cookie",
  "wechat_bot_base_url": "https://ilinkai.weixin.qq.com",
  /*
    块注释也可以保留在配置文件里。
  */
  "interval": "45"
}
""",
        encoding="utf-8",
    )

    loaded = nga_wolf_config.load_config(path)

    assert loaded["nga_cookie"] == "cookie"
    assert loaded["wechat_bot_base_url"] == "https://ilinkai.weixin.qq.com"
    assert loaded["interval"] == "45"


def test_save_config_writes_chinese_comments_and_examples(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = {
        "nga_cookie": "cookie",
        "watch_author_ids": "150058=狼大",
        "push_targets": "[]",
        "listen_rules": "[]",
    }

    nga_wolf_config.save_config(config, path)

    text = path.read_text(encoding="utf-8")
    loaded = nga_wolf_config.load_config(path)

    assert "// NGA Wolf 配置文件" in text
    assert "push_targets 格式样例" in text
    assert "listen_rules 格式样例" in text
    assert loaded["nga_cookie"] == "cookie"
    assert loaded["watch_author_ids"] == "150058=狼大"


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


def test_gui_and_shared_default_config_are_same_object() -> None:
    sys.modules.setdefault("customtkinter", types.SimpleNamespace())
    nga_wolf_gui = importlib.import_module("nga_wolf_gui")

    assert nga_wolf_gui.DEFAULT_CONFIG is nga_wolf_config.DEFAULT_CONFIG
    assert nga_wolf_config.DEFAULT_CONFIG["watch_author_ids"] == "150058=狼大"
    assert nga_wolf_config.DEFAULT_CONFIG["preset_thread_ids"] == "45974302=自立自强，科学技术打头阵"
    assert (
        nga_wolf_config.DEFAULT_CONFIG["ai_auto_analysis_prompt"]
        == "根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。"
    )
    assert nga_wolf_config.DEFAULT_CONFIG["ai_schedule_prompt"] == nga_wolf_config.DEFAULT_CONFIG["ai_auto_analysis_prompt"]


def test_gui_and_shared_validate_config_match_original_messages() -> None:
    sys.modules.setdefault("customtkinter", types.SimpleNamespace())
    nga_wolf_gui = importlib.import_module("nga_wolf_gui")
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update({"bot_channel": "email", "nga_cookie": "", "email_to": "", "email_username": "", "email_password": ""})

    gui_errors = nga_wolf_gui.validate_config(config)
    shared_errors = nga_wolf_config.validate_config(config)

    assert gui_errors == shared_errors
    assert "NGA Cookie" in shared_errors
    assert "邮箱登录账号" in shared_errors
    assert "邮箱密码或授权码" in shared_errors
    assert "收件邮箱" in shared_errors


def test_load_listen_rules_splits_semicolon_separated_target_ids() -> None:
    config = {
        "listen_rules": json.dumps(
            [
                {
                    "id": "rule-1",
                    "mode": "thread_author",
                    "tid": "45974302",
                    "author_id": "150058",
                    "target_ids": "a;b；c",
                }
            ]
        )
    }

    rules = nga_wolf_config.load_listen_rules(config)

    assert rules[0]["target_ids"] == ["a", "b", "c"]


def test_gui_validate_config_delegates_to_shared_module(monkeypatch) -> None:
    sys.modules.setdefault("customtkinter", types.SimpleNamespace())
    nga_wolf_gui = importlib.import_module("nga_wolf_gui")

    config = {"bot_channel": "email"}
    expected = ["delegated"]

    def fake_validate_config(payload, *, require_receive_id=True, require_cookie=True):
        assert payload is config
        assert require_receive_id is False
        assert require_cookie is True
        return expected

    monkeypatch.setattr(nga_wolf_config, "validate_config", fake_validate_config)

    assert nga_wolf_gui.validate_config(config, require_receive_id=False) == expected
