from __future__ import annotations

import logging
from argparse import Namespace
import json
from pathlib import Path

import agent_cli
import ai_analysis


def test_ai_config_uses_state_dir_for_stock_watchlist_path(tmp_path: Path) -> None:
    state_path = tmp_path / ".nga_seen.json"
    args = Namespace(ai_work_dir="agent", state_path=str(state_path))

    config = ai_analysis.AIConfig.from_namespace(args)

    assert config.work_dir == tmp_path / "agent"
    assert config.stock_watchlist_path == tmp_path / "stock_watchlist.json"


def test_ai_config_prefers_explicit_stock_watchlist_path(tmp_path: Path) -> None:
    explicit_path = tmp_path / "software" / "stock_watchlist.json"
    args = Namespace(ai_work_dir=str(tmp_path / "agent"), state_path="", stock_watchlist_path=str(explicit_path))

    config = ai_analysis.AIConfig.from_namespace(args)

    assert config.stock_watchlist_path == explicit_path


def test_local_history_context_syncs_positions_snapshot(tmp_path: Path) -> None:
    stock_path = tmp_path / "stock_watchlist.json"
    stock_path.write_text(
        json.dumps(
            {
                "groups": ["重点关注"],
                "items": [
                    {
                        "fullCode": "hk00700",
                        "name": "腾讯控股",
                        "group": "重点关注",
                        "now": 388,
                        "cost": 350,
                        "shares": 100,
                        "buyDate": "2026-06-01",
                    },
                    {"fullCode": "sh600000", "name": "浦发银行", "group": ""},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = ai_analysis.AIConfig(
        work_dir=tmp_path / ".ai_agent_workspace",
        stock_watchlist_path=stock_path,
    )

    context = ai_analysis.AIManager(config).local_history_context()

    assert f"- stock dashboard source: {stock_path.resolve()}" in context
    snapshot_path = tmp_path / ".ai_agent_workspace" / "context" / "positions.json"
    assert f"- synced positions snapshot: {snapshot_path.resolve()}" in context
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["holdings"][0]["fullCode"] == "hk00700"
    assert payload["focusWatch"][0]["fullCode"] == "hk00700"
    assert [item["fullCode"] for item in payload["items"]] == ["hk00700", "sh600000"]


def test_stock_position_item_requires_positive_cost_or_shares_or_buy_date() -> None:
    for item in (
        {},
        {"cost": "0"},
        {"shares": 0},
        {"cost": "-1"},
        {"shares": "not-a-number"},
        {"shares": "inf"},
        {"buyDate": "   "},
    ):
        assert ai_analysis.is_stock_position_item(item) is False

    for item in (
        {"cost": "10.5"},
        {"shares": 100},
        {"buyDate": "2026-08-10"},
    ):
        assert ai_analysis.is_stock_position_item(item) is True


def _task(tmp_path: Path) -> ai_analysis.AITask:
    return ai_analysis.AITask(
        task_type="chat",
        user_prompt="hello",
        latest_event=tmp_path / "latest.json",
        history_file=tmp_path / "history.jsonl",
        output_file=tmp_path / "answer.md",
        work_dir=tmp_path,
        timeout=30,
    )


def test_codex_commands_ignore_user_config_when_enabled(tmp_path: Path) -> None:
    runner = ai_analysis.CodexRunner(ai_analysis.AIConfig(ignore_codex_user_config=True))

    commands = runner.build_commands(_task(tmp_path), tmp_path / "prompt.md", "prompt")

    assert commands
    assert all("--ignore-user-config" in command for command in commands)


def test_codex_56_models_and_alias_are_available() -> None:
    assert ai_analysis.provider_default_model("codex") == "gpt-5.6-sol"
    assert ai_analysis.provider_default_reasoning_effort("codex") == "high"
    assert ai_analysis.model_options("codex")[:3] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert ai_analysis.normalize_provider_model("codex", "gpt-5.6") == "gpt-5.6-sol"
    assert ai_analysis.is_valid_model("gpt-5.6", "codex") is True


def test_codex_reasoning_options_follow_selected_model() -> None:
    assert ai_analysis.reasoning_effort_options("codex", "gpt-5.6-sol") == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    ]
    assert ai_analysis.reasoning_effort_options("codex", "gpt-5.6-terra")[-2:] == ["max", "ultra"]
    assert ai_analysis.reasoning_effort_options("codex", "gpt-5.6-luna")[-1] == "max"
    assert "ultra" not in ai_analysis.reasoning_effort_options("codex", "gpt-5.6-luna")
    assert ai_analysis.reasoning_effort_options("codex", "gpt-5.5")[-1] == "xhigh"


def test_codex_ultra_is_only_emitted_for_supported_model(tmp_path: Path) -> None:
    task = _task(tmp_path)
    sol = ai_analysis.CodexRunner(
        ai_analysis.AIConfig(model="gpt-5.6-sol", reasoning_effort="ultra")
    ).build_command(task, tmp_path / "prompt.md", "prompt")
    luna = ai_analysis.CodexRunner(
        ai_analysis.AIConfig(model="gpt-5.6-luna", reasoning_effort="ultra")
    ).build_command(task, tmp_path / "prompt.md", "prompt")

    assert 'model_reasoning_effort="ultra"' in sol
    assert 'model_reasoning_effort="ultra"' not in luna


def test_codex_commands_keep_user_config_when_disabled(tmp_path: Path) -> None:
    runner = ai_analysis.CodexRunner(ai_analysis.AIConfig(ignore_codex_user_config=False))

    commands = runner.build_commands(_task(tmp_path), tmp_path / "prompt.md", "prompt")

    assert commands
    assert all("--ignore-user-config" not in command for command in commands)


def test_codex_commands_use_resolved_cli_prefix(tmp_path: Path) -> None:
    resolved = tmp_path / "chosen-codex"
    runner = ai_analysis.CodexRunner(
        ai_analysis.AIConfig(
            resolved_cli_command=(str(resolved), "--profile", "bot"),
            resolved_cli_capabilities={"ignore-user-config", "image"},
            ignore_codex_user_config=True,
        )
    )

    command = runner.build_command(_task(tmp_path), tmp_path / "prompt.md", "prompt")

    assert command[:3] == [str(resolved), "--profile", "bot"]
    assert "--ignore-user-config" in command


def test_codex_omits_images_when_resolved_cli_lacks_capability(tmp_path: Path) -> None:
    task = _task(tmp_path)
    task.image_paths = [tmp_path / "image.png"]
    runner = ai_analysis.CodexRunner(
        ai_analysis.AIConfig(
            resolved_cli_command=(str(tmp_path / "codex"),),
            resolved_cli_capabilities={"exec", "resume"},
        )
    )

    command = runner.build_command(task, tmp_path / "prompt.md", "prompt")

    assert "--image" not in command


def test_ai_manager_resolves_builtin_cli_once_during_startup(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "codex"

    class FakeService:
        def __init__(self) -> None:
            self.start_calls = 0
            self.resolve_calls = 0

        def start(self) -> None:
            self.start_calls += 1

        def resolve(self, provider, selection, *, additional_required=(), timeout=10):
            self.resolve_calls += 1
            assert provider == "codex"
            assert selection.mode == "auto"
            return agent_cli.ResolvedAgentCli(
                provider="codex",
                argv_prefix=(str(executable),),
                invocation_path=executable,
                source="PATH",
                version="1.2.3",
                capabilities=frozenset({"version", "exec", "resume"}),
                capability_status="compatible",
                missing_optional=frozenset(),
                selection_mode="auto",
            )

        def snapshot(self):
            return {"providers": {"codex": {"candidates": []}}}

    service = FakeService()
    monkeypatch.setattr(agent_cli, "GLOBAL_AGENT_CLI_SERVICE", service)
    monkeypatch.setattr(ai_analysis, "configure_logger", lambda _path: logging.getLogger("test-ai-manager"))

    manager = ai_analysis.AIManager(ai_analysis.AIConfig(provider="codex", work_dir=tmp_path))

    assert manager._cli_ready.wait(timeout=2)
    effective = manager.effective_config()
    assert service.start_calls == 1
    assert service.resolve_calls == 1
    assert effective.resolved_cli_command == (str(executable),)
    assert effective.resolved_cli_capabilities == {"version", "exec", "resume"}
