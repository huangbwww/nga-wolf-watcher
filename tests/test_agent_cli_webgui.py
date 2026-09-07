from __future__ import annotations

from pathlib import Path

import agent_cli
import nga_wolf_config
import nga_wolf_webgui


class FakeAgentCliService:
    def __init__(self) -> None:
        self.rescan_calls = 0
        self.probe_calls: list[str | None] = []
        self.test_calls: list[tuple[str, agent_cli.AgentCliSelection, set[str]]] = []

    def snapshot(self):
        return {
            "status": "ready",
            "error": "",
            "providers": {provider: {"candidates": [], "resolved": None} for provider in agent_cli.BUILTIN_PROVIDERS},
        }

    def rescan(self):
        self.rescan_calls += 1
        return self.snapshot()

    def probe_all(self, provider=None):
        self.probe_calls.append(provider)
        return self.snapshot()

    def test_selection(self, provider, selection, *, additional_required=()):
        self.test_calls.append((provider, selection, set(additional_required)))
        return {
            "ok": True,
            "resolved": {
                "provider": provider,
                "path": selection.selected_path or selection.manual_path,
                "version": "1.0.0",
            },
            "error": "",
        }


def _api(service: FakeAgentCliService) -> nga_wolf_webgui.PreviewApi:
    api = nga_wolf_webgui.PreviewApi.__new__(nga_wolf_webgui.PreviewApi)
    api.process = None
    api.closing = False
    api.agent_cli_service = service
    api._merged_config = lambda value=None: {**dict(nga_wolf_config.DEFAULT_CONFIG), **(value or {})}
    return api


def test_webgui_test_uses_structured_selected_path(tmp_path: Path) -> None:
    service = FakeAgentCliService()
    api = _api(service)
    selected = str((tmp_path / "codex").absolute())
    config = {
        "ai_provider": "codex",
        "ai_ignore_codex_user_config": True,
        "ai_cli": {
            **agent_cli.default_agent_cli_config(),
            "codex": {
                "mode": "selected",
                "selected_path": selected,
                "manual_path": "",
                "manual_args": [],
            },
        },
    }

    result = api.agent_cli_test("codex", config)

    assert result["ok"] is True
    assert result["agentCli"]["status"] == "ready"
    provider, selection, required = service.test_calls[0]
    assert provider == "codex"
    assert selection.mode == "selected"
    assert selection.selected_path == selected
    assert required == {"ignore-user-config"}


def test_webgui_rescan_scans_all_then_probes_requested_provider() -> None:
    service = FakeAgentCliService()
    api = _api(service)

    result = api.agent_cli_rescan("claude")

    assert result["ok"] is True
    assert service.rescan_calls == 1
    assert service.probe_calls == ["claude"]


def test_webgui_bootstrap_exposes_astra_without_changing_default() -> None:
    api = _api(FakeAgentCliService())
    api._status = lambda: {}
    api.read_logs = lambda offset: {}

    result = api.bootstrap()

    models = result["options"]["aiModels"]["codex"]
    assert models[0] == "gpt-5.6-sol"
    assert "gpt-6-astra" in models
    assert result["options"]["aiReasoningByModel"]["codex"]["gpt-6-astra"] == [
        "low", "medium", "high", "xhigh", "max", "ultra",
    ]
