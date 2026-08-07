from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import agent_cli
import nga_wolf_config


def _touch_executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("stub", encoding="utf-8")
    path.chmod(0o755)
    return path


def _candidate(
    provider: str,
    path: Path,
    *,
    source: str,
    rank: int,
    order: int | None = None,
    status: str = "compatible",
    version: str = "1.0.0",
    capabilities: set[str] | None = None,
) -> agent_cli.AgentCliCandidate:
    spec = agent_cli.provider_spec(provider)
    return agent_cli.AgentCliCandidate(
        provider=provider,
        invocation_path=path,
        canonical_path=path,
        source=source,
        source_rank=rank,
        path_order=order,
        probe_status=status,
        version=version,
        prerelease="-" in version,
        capabilities=set(capabilities if capabilities is not None else spec.required_capabilities),
    )


class FakeProbe:
    def __init__(self, outcomes: dict[str, tuple[str, str, set[str]]] | None = None) -> None:
        self.outcomes = outcomes or {}
        self.calls: list[str] = []

    def probe(
        self,
        candidate: agent_cli.AgentCliCandidate,
        spec: agent_cli.AgentCliSpec | None = None,
    ) -> agent_cli.AgentCliCandidate:
        self.calls.append(str(candidate.invocation_path))
        status, version, capabilities = self.outcomes.get(
            str(candidate.invocation_path),
            ("compatible", "1.0.0", set((spec or agent_cli.provider_spec(candidate.provider)).required_capabilities)),
        )
        candidate.probe_status = status
        candidate.version = version
        candidate.prerelease = "-" in version
        candidate.capabilities = set(capabilities)
        candidate.diagnostic = "fake outcome"
        return candidate


def test_windows_scanner_preserves_path_order(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = _touch_executable(first_dir / "codex.exe")
    second = _touch_executable(second_dir / "codex.cmd")
    scanner = agent_cli.AgentCliScanner(
        platform="windows",
        env={
            "PATH": f"{first_dir};{second_dir}",
            "PATHEXT": ".EXE;.CMD",
            "APPDATA": str(tmp_path / "appdata"),
            "LOCALAPPDATA": str(tmp_path / "local"),
        },
        home=tmp_path / "home",
        prefix_runner=lambda *_args: "",
    )

    candidates = scanner.scan_provider("codex", package_dirs=[])

    assert [item.invocation_path for item in candidates] == [first.absolute(), second.absolute()]
    assert [item.source for item in candidates] == ["PATH", "PATH"]
    assert candidates[0].path_order < candidates[1].path_order


def test_scanner_deduplicates_path_and_known_location(tmp_path: Path) -> None:
    bin_dir = tmp_path / ".local" / "bin"
    executable = _touch_executable(bin_dir / "claude.exe")
    scanner = agent_cli.AgentCliScanner(
        platform="windows",
        env={"PATH": str(bin_dir), "PATHEXT": ".EXE"},
        home=tmp_path,
        prefix_runner=lambda *_args: "",
    )

    candidates = scanner.scan_provider("claude", package_dirs=[])

    assert len(candidates) == 1
    assert candidates[0].invocation_path == executable.absolute()
    assert candidates[0].source == "PATH"


def test_scanner_excludes_desktop_application_internals(tmp_path: Path) -> None:
    internal = _touch_executable(tmp_path / "WindowsApps" / "OpenAI.Codex" / "codex.exe")
    scanner = agent_cli.AgentCliScanner(
        platform="windows",
        env={"PATH": str(internal.parent), "PATHEXT": ".EXE"},
        home=tmp_path / "home",
        prefix_runner=lambda *_args: "",
    )

    assert scanner.scan_provider("codex", package_dirs=[]) == []


def test_codewhale_scanner_includes_cargo_install(tmp_path: Path) -> None:
    cargo_home = tmp_path / "cargo"
    executable = _touch_executable(cargo_home / "bin" / "codewhale")
    scanner = agent_cli.AgentCliScanner(
        platform="linux",
        env={"PATH": "", "CARGO_HOME": str(cargo_home)},
        home=tmp_path / "home",
        prefix_runner=lambda *_args: "",
    )

    candidates = scanner.scan_provider("codewhale", package_dirs=[])

    assert [item.invocation_path for item in candidates] == [executable.absolute()]
    assert candidates[0].source == "cargo"


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_posix_scanner_uses_path_order_for_linux_and_macos(
    tmp_path: Path, platform: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first = _touch_executable(first_dir / "claude")
    second = _touch_executable(second_dir / "claude")
    scanner = agent_cli.AgentCliScanner(
        platform=platform,
        env={"PATH": "first:second"},
        home=tmp_path / "home",
        prefix_runner=lambda *_args: "",
    )

    candidates = scanner.scan_provider("claude", package_dirs=[])

    assert [item.invocation_path for item in candidates] == [first.absolute(), second.absolute()]
    assert [item.path_order for item in candidates] == [0, 1000]


def test_macos_scanner_excludes_application_bundle_internals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    executable = _touch_executable(tmp_path / "Codex.app" / "Contents" / "MacOS" / "codex")
    scanner = agent_cli.AgentCliScanner(
        platform="darwin",
        env={"PATH": "Codex.app/Contents/MacOS"},
        home=tmp_path / "home",
        prefix_runner=lambda *_args: "",
    )

    assert scanner.scan_provider("codex", package_dirs=[]) == []


def test_wsl_style_linux_scan_does_not_cross_discover_windows_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    linux_dir = tmp_path / "linux-bin"
    linux_cli = _touch_executable(linux_dir / "codex")
    windows_dir = tmp_path / "mnt" / "c" / "tools"
    _touch_executable(windows_dir / "codex.exe")
    scanner = agent_cli.AgentCliScanner(
        platform="linux",
        env={"PATH": "mnt/c/tools:linux-bin", "PATHEXT": ".EXE"},
        home=tmp_path / "home",
        prefix_runner=lambda *_args: "",
    )

    candidates = scanner.scan_provider("codex", package_dirs=[])

    assert [item.invocation_path for item in candidates] == [linux_cli.absolute()]


def test_package_prefix_timeout_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    npm = _touch_executable(tmp_path / "bin" / "npm")
    calls: list[tuple[str, ...]] = []

    def timeout_runner(argv, _timeout, _env):
        calls.append(tuple(argv))
        raise subprocess.TimeoutExpired(argv, 0.01)

    monkeypatch.setattr(agent_cli.shutil, "which", lambda name, path=None: str(npm) if name == "npm" else None)
    scanner = agent_cli.AgentCliScanner(
        platform="linux",
        env={"PATH": str(npm.parent)},
        home=tmp_path / "home",
        prefix_runner=timeout_runner,
        prefix_timeout=0.01,
    )

    assert scanner._package_manager_dirs() == []
    assert calls == [(str(npm), "prefix", "-g")]


def test_probe_extracts_codex_version_and_capabilities(tmp_path: Path) -> None:
    executable = _touch_executable(tmp_path / "codex")
    calls: list[tuple[str, ...]] = []

    def runner(argv, _timeout, _env):
        calls.append(tuple(argv[1:]))
        if argv[1:] == ["--version"]:
            return 0, "codex-cli 0.130.0-alpha.5", ""
        if argv[1:] == ["exec", "--help"]:
            return 0, "--output-last-message --skip-git-repo-check --ignore-user-config --image", ""
        return 0, "--last", ""

    candidate = agent_cli.AgentCliCandidate(
        "codex", executable, executable, "PATH", agent_cli.SOURCE_PATH
    )

    result = agent_cli.AgentCliProbe(runner=runner).probe(candidate)

    assert result.probe_status == "compatible"
    assert result.version == "0.130.0-alpha.5"
    assert result.prerelease is True
    assert {"version", "exec", "resume", "ignore-user-config", "image"} <= result.capabilities
    assert calls == [("--version",), ("exec", "--help"), ("exec", "resume", "--help")]


def test_probe_marks_missing_required_capabilities_incompatible(tmp_path: Path) -> None:
    executable = _touch_executable(tmp_path / "claude")

    def runner(argv, _timeout, _env):
        if argv[1:] == ["--version"]:
            return 0, "2.1.187 (Claude Code)", ""
        return 0, "--output-format --input-format", ""

    candidate = agent_cli.AgentCliCandidate(
        "claude", executable, executable, "PATH", agent_cli.SOURCE_PATH
    )

    result = agent_cli.AgentCliProbe(runner=runner).probe(candidate)

    assert result.probe_status == "incompatible"
    assert "replay-user-messages" in result.diagnostic


def test_auto_resolution_prefers_compatible_path_over_newer_native(tmp_path: Path) -> None:
    path_cli = _candidate(
        "codex",
        _touch_executable(tmp_path / "path" / "codex"),
        source="PATH",
        rank=agent_cli.SOURCE_PATH,
        order=0,
        version="1.0.0",
    )
    native_cli = _candidate(
        "codex",
        _touch_executable(tmp_path / "native" / "codex"),
        source="native",
        rank=agent_cli.SOURCE_NATIVE,
        version="9.0.0",
    )

    resolved = agent_cli.AgentCliResolver(FakeProbe()).resolve(
        "codex", agent_cli.AgentCliSelection(), [native_cli, path_cli]
    )

    assert resolved.invocation_path == path_cli.invocation_path
    assert resolved.source == "PATH"


def test_auto_resolution_skips_incompatible_path_candidate(tmp_path: Path) -> None:
    bad = _candidate(
        "codex",
        _touch_executable(tmp_path / "first" / "codex"),
        source="PATH",
        rank=agent_cli.SOURCE_PATH,
        order=0,
        status="incompatible",
        capabilities={"version"},
    )
    good = _candidate(
        "codex",
        _touch_executable(tmp_path / "second" / "codex"),
        source="PATH",
        rank=agent_cli.SOURCE_PATH,
        order=1,
    )

    resolved = agent_cli.AgentCliResolver(FakeProbe()).resolve(
        "codex", agent_cli.AgentCliSelection(), [bad, good]
    )

    assert resolved.invocation_path == good.invocation_path


def test_auto_resolution_uses_stable_then_highest_version_within_fallback_tier(tmp_path: Path) -> None:
    prerelease = _candidate(
        "codex",
        _touch_executable(tmp_path / "preview" / "codex"),
        source="native",
        rank=agent_cli.SOURCE_NATIVE,
        version="3.0.0-alpha.1",
    )
    stable_old = _candidate(
        "codex",
        _touch_executable(tmp_path / "stable-old" / "codex"),
        source="native",
        rank=agent_cli.SOURCE_NATIVE,
        version="1.0.0",
    )
    stable_new = _candidate(
        "codex",
        _touch_executable(tmp_path / "stable-new" / "codex"),
        source="native",
        rank=agent_cli.SOURCE_NATIVE,
        version="2.0.0",
    )

    resolved = agent_cli.AgentCliResolver(FakeProbe()).resolve(
        "codex", agent_cli.AgentCliSelection(), [prerelease, stable_old, stable_new]
    )

    assert resolved.invocation_path == stable_new.invocation_path


def test_selected_mode_is_strict_and_does_not_fallback(tmp_path: Path) -> None:
    fallback = _candidate(
        "codex",
        _touch_executable(tmp_path / "fallback" / "codex"),
        source="PATH",
        rank=agent_cli.SOURCE_PATH,
    )
    missing = tmp_path / "missing" / "codex"
    selection = agent_cli.AgentCliSelection(mode="selected", selected_path=str(missing.absolute()))

    with pytest.raises(agent_cli.AgentCliResolutionError, match="does not exist"):
        agent_cli.AgentCliResolver(FakeProbe()).resolve("codex", selection, [fallback])


def test_manual_mode_keeps_separate_arguments(tmp_path: Path) -> None:
    executable = _touch_executable(tmp_path / "manual" / "claude")
    candidate = _candidate(
        "claude", executable, source="manual", rank=agent_cli.SOURCE_PATH
    )
    selection = agent_cli.AgentCliSelection(
        mode="manual",
        manual_path=str(executable.absolute()),
        manual_args=("--settings", "safe profile.json"),
    )

    resolved = agent_cli.AgentCliResolver(FakeProbe()).resolve("claude", selection, [candidate])

    assert resolved.argv_prefix == (
        str(executable.absolute()),
        "--settings",
        "safe profile.json",
    )


def test_manual_mode_rejects_bare_command_name() -> None:
    selection = agent_cli.AgentCliSelection(mode="manual", manual_path="codex")

    with pytest.raises(agent_cli.AgentCliResolutionError, match="must be absolute"):
        agent_cli.AgentCliResolver(FakeProbe()).resolve("codex", selection, [])


def test_normalize_config_migrates_default_and_explicit_legacy_commands(tmp_path: Path) -> None:
    explicit = _touch_executable(tmp_path / "tools" / "claude")

    normalized = agent_cli.normalize_agent_cli_config(
        None,
        legacy_commands={
            "codex": "codex",
            "claude": f'"{explicit}" --settings profile.json',
            "codewhale": "codewhale",
        },
    )

    assert normalized["codex"]["mode"] == "auto"
    assert normalized["codewhale"]["mode"] == "auto"
    assert normalized["claude"] == {
        "mode": "manual",
        "selected_path": "",
        "manual_path": str(explicit),
        "manual_args": ["--settings", "profile.json"],
    }


def test_additional_required_capability_rejects_limited_cli(tmp_path: Path) -> None:
    candidate = _candidate(
        "codex",
        _touch_executable(tmp_path / "codex"),
        source="PATH",
        rank=agent_cli.SOURCE_PATH,
        status="limited",
    )

    with pytest.raises(agent_cli.AgentCliResolutionError, match="No compatible"):
        agent_cli.AgentCliResolver(FakeProbe()).resolve(
            "codex",
            agent_cli.AgentCliSelection(),
            [candidate],
            additional_required={"ignore-user-config"},
        )


def test_discovery_service_scans_once_and_caches_resolution(tmp_path: Path) -> None:
    executable = _touch_executable(tmp_path / "codex")
    candidate = agent_cli.AgentCliCandidate(
        "codex", executable, executable, "PATH", agent_cli.SOURCE_PATH, 0
    )

    class FakeScanner:
        def __init__(self) -> None:
            self.calls = 0

        def scan_all(self):
            self.calls += 1
            return {"codex": [candidate], "claude": [], "codewhale": []}

    scanner = FakeScanner()
    probe = FakeProbe()
    service = agent_cli.AgentCliDiscoveryService(scanner=scanner, probe=probe)
    service.start()

    first = service.resolve("codex", agent_cli.AgentCliSelection())
    second = service.resolve("codex", agent_cli.AgentCliSelection())

    assert first == second
    assert scanner.calls == 1
    assert probe.calls == [str(executable)]


def test_explicit_test_reprobes_cached_selection(tmp_path: Path) -> None:
    executable = _touch_executable(tmp_path / "codex")
    candidate = agent_cli.AgentCliCandidate(
        "codex", executable, executable, "PATH", agent_cli.SOURCE_PATH, 0
    )

    class FakeScanner:
        def scan_all(self):
            return {"codex": [candidate], "claude": [], "codewhale": []}

    probe = FakeProbe()
    service = agent_cli.AgentCliDiscoveryService(scanner=FakeScanner(), probe=probe)

    assert service.test_selection("codex", agent_cli.AgentCliSelection())["ok"] is True
    assert service.test_selection("codex", agent_cli.AgentCliSelection())["ok"] is True

    assert probe.calls == [str(executable), str(executable)]


def test_cached_auto_selection_marks_missing_executable_stale_and_uses_fallback(tmp_path: Path) -> None:
    first_path = _touch_executable(tmp_path / "first" / "codex")
    second_path = _touch_executable(tmp_path / "second" / "codex")
    first = agent_cli.AgentCliCandidate(
        "codex", first_path, first_path, "PATH", agent_cli.SOURCE_PATH, 0
    )
    second = agent_cli.AgentCliCandidate(
        "codex", second_path, second_path, "PATH", agent_cli.SOURCE_PATH, 1
    )

    class FakeScanner:
        def scan_all(self):
            return {"codex": [first, second], "claude": [], "codewhale": []}

    service = agent_cli.AgentCliDiscoveryService(scanner=FakeScanner(), probe=FakeProbe())
    initial = service.resolve("codex", agent_cli.AgentCliSelection())
    first_path.unlink()

    replacement = service.resolve("codex", agent_cli.AgentCliSelection())

    assert initial.invocation_path == first_path
    assert replacement.invocation_path == second_path
    assert first.probe_status == "stale"


def test_load_config_migrates_legacy_command_to_manual_selection(tmp_path: Path) -> None:
    executable = _touch_executable(tmp_path / "tools" / "claude")
    path = tmp_path / "config.json"
    path.write_text(
        json.dumps(
            {
                "ai_provider": "claude",
                "ai_claude_command": f'"{executable}" --settings profile.json',
            }
        ),
        encoding="utf-8",
    )

    loaded = nga_wolf_config.load_config(path)
    selection = agent_cli.selection_for_provider(loaded, "claude")

    assert selection.mode == "manual"
    assert selection.manual_path == str(executable)
    assert selection.manual_args == ("--settings", "profile.json")


def test_build_args_carries_active_provider_cli_selection(tmp_path: Path) -> None:
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config["ai_provider"] = "codex"
    config["ai_cli"] = agent_cli.default_agent_cli_config()
    config["ai_cli"]["codex"] = {
        "mode": "selected",
        "selected_path": str((tmp_path / "codex").absolute()),
        "manual_path": "",
        "manual_args": [],
    }

    args = nga_wolf_config.build_args(config, data_dir=tmp_path)

    assert args.ai_cli_mode == "selected"
    assert args.ai_cli_selected_path == str((tmp_path / "codex").absolute())
    assert args.ai_cli_manual_path == ""
    assert args.ai_cli_manual_args == []
