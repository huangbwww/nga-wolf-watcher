"""Cross-platform discovery and selection for local AI Agent CLIs.

Discovery is intentionally separate from probing. Scanning only inspects paths;
probing executes a small, built-in set of version/help commands and never sends
a model request. The module has no dependency on the watcher UI or runners.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


BUILTIN_PROVIDERS = ("codex", "claude", "codewhale")
SELECTION_MODES = {"auto", "selected", "manual"}
DEFAULT_COMMANDS = {
    "codex": "codex",
    "claude": "claude",
    "codewhale": "codewhale",
}

SOURCE_PATH = 0
SOURCE_NATIVE = 10
SOURCE_PACKAGE = 20
SOURCE_SYSTEM = 25
SOURCE_LEGACY = 30

_VERSION_RE = re.compile(r"(?<!\d)v?(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)")


@dataclass(frozen=True)
class CapabilityCheck:
    name: str
    markers: tuple[str, ...]


@dataclass(frozen=True)
class HelpProbeSpec:
    args: tuple[str, ...]
    checks: tuple[CapabilityCheck, ...]


@dataclass(frozen=True)
class AgentCliSpec:
    provider: str
    display_name: str
    aliases: tuple[str, ...]
    legacy_aliases: tuple[str, ...]
    version_args: tuple[str, ...]
    help_probes: tuple[HelpProbeSpec, ...]
    required_capabilities: frozenset[str]
    optional_capabilities: frozenset[str]
    probe_env: tuple[tuple[str, str], ...] = ()


@dataclass
class AgentCliCandidate:
    provider: str
    invocation_path: Path
    canonical_path: Path
    source: str
    source_rank: int
    path_order: int | None = None
    probe_status: str = "unverified"
    version: str = ""
    prerelease: bool = False
    capabilities: set[str] = field(default_factory=set)
    missing_optional: set[str] = field(default_factory=set)
    diagnostic: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "path": str(self.invocation_path),
            "canonicalPath": str(self.canonical_path),
            "source": self.source,
            "sourceRank": self.source_rank,
            "pathOrder": self.path_order,
            "status": self.probe_status,
            "version": self.version,
            "prerelease": self.prerelease,
            "capabilities": sorted(self.capabilities),
            "missingOptional": sorted(self.missing_optional),
            "diagnostic": self.diagnostic,
        }


@dataclass(frozen=True)
class AgentCliSelection:
    mode: str = "auto"
    selected_path: str = ""
    manual_path: str = ""
    manual_args: tuple[str, ...] = ()

    @classmethod
    def from_value(cls, value: object) -> "AgentCliSelection":
        raw = value if isinstance(value, dict) else {}
        mode = str(raw.get("mode") or "auto").strip().lower()
        if mode not in SELECTION_MODES:
            mode = "auto"
        args_value = raw.get("manual_args")
        if isinstance(args_value, list):
            manual_args = tuple(str(item) for item in args_value if str(item))
        elif isinstance(args_value, tuple):
            manual_args = tuple(str(item) for item in args_value if str(item))
        elif str(args_value or "").strip():
            manual_args = tuple(_split_command_text(str(args_value)))
        else:
            manual_args = ()
        return cls(
            mode=mode,
            selected_path=str(raw.get("selected_path") or "").strip(),
            manual_path=str(raw.get("manual_path") or "").strip(),
            manual_args=manual_args,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "selected_path": self.selected_path,
            "manual_path": self.manual_path,
            "manual_args": list(self.manual_args),
        }

    def cache_key(self) -> tuple[Any, ...]:
        return (self.mode, self.selected_path, self.manual_path, self.manual_args)


@dataclass(frozen=True)
class ResolvedAgentCli:
    provider: str
    argv_prefix: tuple[str, ...]
    invocation_path: Path
    source: str
    version: str
    capabilities: frozenset[str]
    capability_status: str
    missing_optional: frozenset[str]
    selection_mode: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "argvPrefix": list(self.argv_prefix),
            "path": str(self.invocation_path),
            "source": self.source,
            "version": self.version,
            "capabilities": sorted(self.capabilities),
            "status": self.capability_status,
            "missingOptional": sorted(self.missing_optional),
            "selectionMode": self.selection_mode,
        }


class AgentCliResolutionError(RuntimeError):
    def __init__(self, message: str, candidates: Sequence[AgentCliCandidate] = ()) -> None:
        super().__init__(message)
        self.candidates = list(candidates)


def _specs() -> dict[str, AgentCliSpec]:
    return {
        "codex": AgentCliSpec(
            provider="codex",
            display_name="Codex",
            aliases=("codex",),
            legacy_aliases=(),
            version_args=("--version",),
            help_probes=(
                HelpProbeSpec(
                    args=("exec", "--help"),
                    checks=(
                        CapabilityCheck("exec", ("--output-last-message", "--skip-git-repo-check")),
                        CapabilityCheck("ignore-user-config", ("--ignore-user-config",)),
                        CapabilityCheck("image", ("--image",)),
                    ),
                ),
                HelpProbeSpec(
                    args=("exec", "resume", "--help"),
                    checks=(CapabilityCheck("resume", ("--last",)),),
                ),
            ),
            required_capabilities=frozenset({"version", "exec", "resume"}),
            optional_capabilities=frozenset({"ignore-user-config", "image"}),
        ),
        "claude": AgentCliSpec(
            provider="claude",
            display_name="Claude Code",
            aliases=("claude",),
            legacy_aliases=(),
            version_args=("--version",),
            help_probes=(
                HelpProbeSpec(
                    args=("--help",),
                    checks=(
                        CapabilityCheck("stream-json", ("--output-format", "--input-format")),
                        CapabilityCheck("replay-user-messages", ("--replay-user-messages",)),
                        CapabilityCheck("verbose", ("--verbose",)),
                        CapabilityCheck("model", ("--model",)),
                        CapabilityCheck("effort", ("--effort",)),
                        CapabilityCheck("permission-mode", ("--permission-mode",)),
                    ),
                ),
                HelpProbeSpec(
                    args=("--permission-prompt-tool", "stdio", "--version"),
                    checks=(CapabilityCheck("permission-stdio", ()),),
                ),
            ),
            required_capabilities=frozenset(
                {"version", "stream-json", "permission-stdio", "replay-user-messages", "verbose"}
            ),
            optional_capabilities=frozenset({"model", "effort", "permission-mode"}),
            probe_env=(("DISABLE_AUTOUPDATER", "1"),),
        ),
        "codewhale": AgentCliSpec(
            provider="codewhale",
            display_name="CodeWhale",
            aliases=("codewhale", "codew"),
            legacy_aliases=("deepseek",),
            version_args=("--version",),
            help_probes=(
                HelpProbeSpec(
                    args=("exec", "--help"),
                    checks=(
                        CapabilityCheck("exec-stream-json", ("--output-format", "stream-json")),
                        CapabilityCheck("auto", ("--auto",)),
                        CapabilityCheck("resume", ("--resume",)),
                    ),
                ),
                HelpProbeSpec(
                    args=("--help",),
                    checks=(
                        CapabilityCheck("model", ("--model",)),
                        CapabilityCheck("runtime-config", ("--config",)),
                    ),
                ),
            ),
            required_capabilities=frozenset(
                {"version", "exec-stream-json", "auto", "resume", "model", "runtime-config"}
            ),
            optional_capabilities=frozenset(),
        ),
    }


AGENT_CLI_SPECS = _specs()


def provider_spec(provider: str) -> AgentCliSpec:
    key = str(provider or "").strip().lower()
    try:
        return AGENT_CLI_SPECS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported local Agent provider: {provider}") from exc


def default_agent_cli_config() -> dict[str, dict[str, Any]]:
    return {provider: AgentCliSelection().to_dict() for provider in BUILTIN_PROVIDERS}


def normalize_agent_cli_config(
    value: object,
    *,
    legacy_commands: Mapping[str, object] | None = None,
) -> dict[str, dict[str, Any]]:
    raw = value if isinstance(value, dict) else {}
    legacy_commands = legacy_commands or {}
    result: dict[str, dict[str, Any]] = {}
    for provider in BUILTIN_PROVIDERS:
        provider_value = raw.get(provider)
        if isinstance(provider_value, dict):
            selection = AgentCliSelection.from_value(provider_value)
        else:
            selection = _selection_from_legacy_command(provider, legacy_commands.get(provider))
        result[provider] = selection.to_dict()
    return result


def selection_for_provider(config: Mapping[str, object], provider: str) -> AgentCliSelection:
    normalized = normalize_agent_cli_config(
        config.get("ai_cli"),
        legacy_commands={
            "codex": config.get("ai_codex_command"),
            "claude": config.get("ai_claude_command"),
            "codewhale": config.get("ai_codewhale_command"),
        },
    )
    return AgentCliSelection.from_value(normalized.get(provider))


def _selection_from_legacy_command(provider: str, raw: object) -> AgentCliSelection:
    default = DEFAULT_COMMANDS[provider]
    text = str(raw or default).strip() or default
    parts = _split_command_text(text)
    if not parts or (len(parts) == 1 and parts[0].lower() == default.lower()):
        return AgentCliSelection()
    executable = parts[0]
    path = Path(executable).expanduser()
    if not path.is_absolute() and path.parent == Path("."):
        found = shutil.which(executable)
        if found:
            executable = found
    return AgentCliSelection(mode="manual", manual_path=executable, manual_args=tuple(parts[1:]))


def _split_command_text(value: str) -> list[str]:
    try:
        parts = shlex.split(value, posix=os.name != "nt")
        if os.name == "nt":
            parts = [
                item[1:-1]
                if len(item) >= 2 and item[0] == item[-1] and item[0] in {'"', "'"}
                else item
                for item in parts
            ]
        return parts
    except ValueError:
        return [value.strip()] if value.strip() else []


def _platform_key(value: str | None = None) -> str:
    text = str(value or sys.platform).lower()
    if text.startswith("win") or text == "nt":
        return "windows"
    if text.startswith("darwin") or text.startswith("mac"):
        return "darwin"
    return "linux"


def _candidate_key(path: Path, platform: str) -> str:
    text = str(path)
    return text.replace("/", "\\").casefold() if platform == "windows" else text


class AgentCliScanner:
    def __init__(
        self,
        *,
        platform: str | None = None,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
        prefix_runner: Callable[[Sequence[str], float, Mapping[str, str]], str] | None = None,
        prefix_timeout: float = 2.0,
    ) -> None:
        self.platform = _platform_key(platform)
        self.env = dict(os.environ if env is None else env)
        self.home = Path.home() if home is None else Path(home)
        self.prefix_runner = prefix_runner or self._default_prefix_runner
        self.prefix_timeout = prefix_timeout

    def scan_all(self) -> dict[str, list[AgentCliCandidate]]:
        package_dirs = self._package_manager_dirs()
        return {provider: self.scan_provider(provider, package_dirs=package_dirs) for provider in BUILTIN_PROVIDERS}

    def scan_provider(
        self,
        provider: str,
        *,
        package_dirs: Sequence[tuple[Path, str, int]] | None = None,
    ) -> list[AgentCliCandidate]:
        spec = provider_spec(provider)
        found: dict[str, AgentCliCandidate] = {}

        for candidate in self._path_candidates(spec):
            self._remember(found, candidate)

        for path, source, rank, aliases in self._known_locations(spec):
            for candidate in self._candidates_from_location(spec, path, source, rank, aliases):
                self._remember(found, candidate)

        package_locations = self._package_manager_dirs() if package_dirs is None else package_dirs
        for directory, source, rank in package_locations:
            for candidate in self._candidates_from_directory(spec, directory, source, rank, spec.aliases):
                self._remember(found, candidate)

        return sorted(found.values(), key=self._discovery_sort_key)

    def _path_candidates(self, spec: AgentCliSpec) -> Iterable[AgentCliCandidate]:
        separator = ";" if self.platform == "windows" else ":"
        raw_path = str(self.env.get("PATH") or "")
        for directory_index, raw_directory in enumerate(raw_path.split(separator)):
            if not raw_directory.strip():
                continue
            directory = Path(os.path.expandvars(raw_directory.strip().strip('"'))).expanduser()
            for alias_index, alias in enumerate(spec.aliases):
                for extension_index, name in enumerate(self._executable_names(alias)):
                    path = directory / name
                    if self._is_candidate_file(path) and not self._is_protected_app_internal(path):
                        order = directory_index * 1000 + alias_index * 100 + extension_index
                        yield self._candidate(spec.provider, path, "PATH", SOURCE_PATH, order)

    def _known_locations(
        self,
        spec: AgentCliSpec,
    ) -> list[tuple[Path, str, int, tuple[str, ...]]]:
        env = self.env
        home = self.home
        locations: list[tuple[Path, str, int, tuple[str, ...]]] = []
        if self.platform == "windows":
            appdata = Path(env["APPDATA"]) if env.get("APPDATA") else None
            localappdata = Path(env["LOCALAPPDATA"]) if env.get("LOCALAPPDATA") else None
            locations.append((home / ".local" / "bin", "native", SOURCE_NATIVE, spec.aliases))
            if localappdata:
                locations.append((localappdata / "Microsoft" / "WinGet" / "Links", "winget", SOURCE_PACKAGE, spec.aliases))
            if appdata:
                locations.append((appdata / "npm", "npm", SOURCE_PACKAGE, spec.aliases))
            if spec.provider == "codex" and localappdata:
                locations.extend(
                    [
                        (
                            localappdata / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
                            "official-native",
                            SOURCE_NATIVE,
                            (),
                        ),
                        (
                            localappdata / "OpenAI" / "Codex" / "bin" / "codex.exe",
                            "legacy",
                            SOURCE_LEGACY,
                            (),
                        ),
                    ]
                )
            if spec.provider == "codewhale" and appdata:
                locations.append((appdata / "npm", "legacy", SOURCE_LEGACY, spec.legacy_aliases))
        else:
            locations.append((home / ".local" / "bin", "native", SOURCE_NATIVE, spec.aliases))
            if self.platform == "darwin":
                locations.append((Path("/opt/homebrew/bin"), "homebrew", SOURCE_PACKAGE, spec.aliases))
            locations.extend(
                [
                    (Path("/usr/local/bin"), "system", SOURCE_SYSTEM, spec.aliases),
                    (Path("/usr/bin"), "system", SOURCE_SYSTEM, spec.aliases),
                ]
            )
            if spec.provider == "codewhale":
                cargo_home = Path(env.get("CARGO_HOME") or (home / ".cargo"))
                locations.append((cargo_home / "bin", "cargo", SOURCE_PACKAGE, spec.aliases))
                locations.append((Path("/usr/local/bin"), "legacy", SOURCE_LEGACY, spec.legacy_aliases))
        return locations

    def _package_manager_dirs(self) -> list[tuple[Path, str, int]]:
        result: list[tuple[Path, str, int]] = []
        prefix = str(self.env.get("NPM_CONFIG_PREFIX") or "").strip()
        if prefix:
            root = Path(prefix).expanduser()
            result.append((root if self.platform == "windows" else root / "bin", "npm", SOURCE_PACKAGE))
        npm = shutil.which("npm", path=self.env.get("PATH"))
        if npm:
            value = self._safe_prefix_query([npm, "prefix", "-g"])
            if value:
                root = Path(value).expanduser()
                result.append((root if self.platform == "windows" else root / "bin", "npm", SOURCE_PACKAGE))
        if self.platform == "darwin" or shutil.which("brew", path=self.env.get("PATH")):
            brew = shutil.which("brew", path=self.env.get("PATH"))
            if brew:
                value = self._safe_prefix_query([brew, "--prefix"])
                if value:
                    result.append((Path(value).expanduser() / "bin", "homebrew", SOURCE_PACKAGE))
        unique: dict[str, tuple[Path, str, int]] = {}
        for path, source, rank in result:
            unique[_candidate_key(path, self.platform)] = (path, source, rank)
        return list(unique.values())

    def _safe_prefix_query(self, argv: Sequence[str]) -> str:
        try:
            return str(self.prefix_runner(argv, self.prefix_timeout, self.env) or "").splitlines()[0].strip()
        except (OSError, subprocess.SubprocessError, IndexError):
            return ""

    @staticmethod
    def _default_prefix_runner(argv: Sequence[str], timeout: float, env: Mapping[str, str]) -> str:
        completed = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            env=dict(env),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.stdout if completed.returncode == 0 else ""

    def _candidates_from_location(
        self,
        spec: AgentCliSpec,
        path: Path,
        source: str,
        rank: int,
        aliases: tuple[str, ...],
    ) -> Iterable[AgentCliCandidate]:
        if aliases:
            yield from self._candidates_from_directory(spec, path, source, rank, aliases)
        elif self._is_candidate_file(path) and not self._is_protected_app_internal(path):
            yield self._candidate(spec.provider, path, source, rank)

    def _candidates_from_directory(
        self,
        spec: AgentCliSpec,
        directory: Path,
        source: str,
        rank: int,
        aliases: Sequence[str],
    ) -> Iterable[AgentCliCandidate]:
        for alias in aliases:
            for name in self._executable_names(alias):
                path = directory / name
                if self._is_candidate_file(path) and not self._is_protected_app_internal(path):
                    yield self._candidate(spec.provider, path, source, rank)

    def _executable_names(self, alias: str) -> tuple[str, ...]:
        if self.platform != "windows" or Path(alias).suffix:
            return (alias,)
        raw = str(self.env.get("PATHEXT") or ".EXE;.CMD;.BAT;.COM")
        extensions = [item.lower() for item in raw.split(";") if item.lower() in {".exe", ".cmd", ".bat", ".com"}]
        if not extensions:
            extensions = [".exe", ".cmd", ".bat", ".com"]
        return tuple(f"{alias}{extension}" for extension in extensions)

    def _is_candidate_file(self, path: Path) -> bool:
        try:
            if not path.is_file():
                return False
            return self.platform == "windows" or os.access(path, os.X_OK)
        except OSError:
            return False

    def _is_protected_app_internal(self, path: Path) -> bool:
        parts = [part.lower() for part in path.parts]
        if self.platform == "windows" and "windowsapps" in parts:
            return True
        return self.platform == "darwin" and any(part.endswith(".app") for part in parts)

    def _candidate(
        self,
        provider: str,
        path: Path,
        source: str,
        rank: int,
        path_order: int | None = None,
    ) -> AgentCliCandidate:
        absolute = path.expanduser().absolute()
        try:
            canonical = absolute.resolve(strict=False)
        except OSError:
            canonical = absolute
        return AgentCliCandidate(provider, absolute, canonical, source, rank, path_order)

    def _remember(self, found: dict[str, AgentCliCandidate], candidate: AgentCliCandidate) -> None:
        key = _candidate_key(candidate.canonical_path, self.platform)
        current = found.get(key)
        if current is None or self._discovery_sort_key(candidate) < self._discovery_sort_key(current):
            found[key] = candidate

    @staticmethod
    def _discovery_sort_key(candidate: AgentCliCandidate) -> tuple[Any, ...]:
        order = candidate.path_order if candidate.path_order is not None else 1_000_000
        return (candidate.source_rank, order, str(candidate.invocation_path).lower())


ProbeRunner = Callable[[Sequence[str], float, Mapping[str, str]], tuple[int, str, str]]


class AgentCliProbe:
    def __init__(
        self,
        *,
        runner: ProbeRunner | None = None,
        timeout: float = 3.0,
        output_limit: int = 65536,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.runner = runner or self._default_runner
        self.timeout = timeout
        self.output_limit = output_limit
        self.env = dict(os.environ if env is None else env)

    def probe(self, candidate: AgentCliCandidate, spec: AgentCliSpec | None = None) -> AgentCliCandidate:
        spec = spec or provider_spec(candidate.provider)
        candidate.capabilities.clear()
        candidate.missing_optional.clear()
        candidate.diagnostic = ""
        probe_env = dict(self.env)
        probe_env.update(dict(spec.probe_env))
        probe_env.setdefault("NO_COLOR", "1")
        try:
            code, stdout, stderr = self.runner(
                [str(candidate.invocation_path), *spec.version_args], self.timeout, probe_env
            )
        except subprocess.TimeoutExpired:
            candidate.probe_status = "timeout"
            candidate.diagnostic = f"version probe timed out after {self.timeout:g}s"
            return candidate
        except OSError as exc:
            candidate.probe_status = "failed"
            candidate.diagnostic = str(exc)
            return candidate
        version_output = self._bounded(f"{stdout}\n{stderr}")
        if code != 0:
            candidate.probe_status = "failed"
            candidate.diagnostic = self._diagnostic("version probe failed", version_output)
            return candidate
        match = _VERSION_RE.search(version_output)
        if not match:
            candidate.probe_status = "failed"
            candidate.diagnostic = self._diagnostic("could not parse CLI version", version_output)
            return candidate
        candidate.version = match.group(1)
        candidate.prerelease = "-" in candidate.version
        candidate.capabilities.add("version")

        for help_probe in spec.help_probes:
            try:
                code, stdout, stderr = self.runner(
                    [str(candidate.invocation_path), *help_probe.args], self.timeout, probe_env
                )
            except subprocess.TimeoutExpired:
                candidate.probe_status = "timeout"
                candidate.diagnostic = f"help probe timed out after {self.timeout:g}s: {' '.join(help_probe.args)}"
                return candidate
            except OSError as exc:
                candidate.probe_status = "failed"
                candidate.diagnostic = str(exc)
                return candidate
            output = self._bounded(f"{stdout}\n{stderr}")
            if code != 0:
                candidate.probe_status = "failed"
                candidate.diagnostic = self._diagnostic(
                    f"help probe failed: {' '.join(help_probe.args)}", output
                )
                return candidate
            lowered = output.lower()
            for check in help_probe.checks:
                if all(marker.lower() in lowered for marker in check.markers):
                    candidate.capabilities.add(check.name)

        missing_required = spec.required_capabilities - candidate.capabilities
        candidate.missing_optional = set(spec.optional_capabilities - candidate.capabilities)
        if missing_required:
            candidate.probe_status = "incompatible"
            candidate.diagnostic = "missing required capabilities: " + ", ".join(sorted(missing_required))
        elif candidate.missing_optional:
            candidate.probe_status = "limited"
            candidate.diagnostic = "missing optional capabilities: " + ", ".join(sorted(candidate.missing_optional))
        else:
            candidate.probe_status = "compatible"
        return candidate

    def _bounded(self, text: str) -> str:
        return text[-self.output_limit :]

    @staticmethod
    def _diagnostic(prefix: str, output: str) -> str:
        compact = " ".join(output.strip().split())
        return f"{prefix}: {compact[:500]}" if compact else prefix

    @staticmethod
    def _default_runner(
        argv: Sequence[str], timeout: float, env: Mapping[str, str]
    ) -> tuple[int, str, str]:
        completed = subprocess.run(
            list(argv),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
            env=dict(env),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return completed.returncode, completed.stdout, completed.stderr


class AgentCliResolver:
    def __init__(self, probe: AgentCliProbe | None = None) -> None:
        self.probe = probe or AgentCliProbe()

    def resolve(
        self,
        provider: str,
        selection: AgentCliSelection,
        candidates: Sequence[AgentCliCandidate],
        *,
        additional_required: Iterable[str] = (),
    ) -> ResolvedAgentCli:
        spec = provider_spec(provider)
        required = set(spec.required_capabilities) | {str(item) for item in additional_required}
        if selection.mode == "manual":
            path = self._strict_path(selection.manual_path, "manual")
            candidate = self._find_or_create(provider, path, candidates, "manual")
            self._ensure_probed(candidate, spec)
            self._require(candidate, required, "manual")
            return self._resolved(candidate, selection, (str(candidate.invocation_path), *selection.manual_args))
        if selection.mode == "selected":
            path = self._strict_path(selection.selected_path, "selected")
            candidate = self._find_or_create(provider, path, candidates, "selected")
            self._ensure_probed(candidate, spec)
            self._require(candidate, required, "selected")
            return self._resolved(candidate, selection, (str(candidate.invocation_path),))
        return self._resolve_auto(spec, selection, list(candidates), required)

    def _resolve_auto(
        self,
        spec: AgentCliSpec,
        selection: AgentCliSelection,
        candidates: list[AgentCliCandidate],
        required: set[str],
    ) -> ResolvedAgentCli:
        path_candidates = sorted(
            (item for item in candidates if item.source_rank == SOURCE_PATH),
            key=lambda item: (item.path_order if item.path_order is not None else 1_000_000, str(item.invocation_path)),
        )
        for candidate in path_candidates:
            self._ensure_probed(candidate, spec)
            if self._is_usable(candidate, required):
                return self._resolved(candidate, selection, (str(candidate.invocation_path),))

        ranks = sorted({item.source_rank for item in candidates if item.source_rank != SOURCE_PATH})
        for rank in ranks:
            tier = [item for item in candidates if item.source_rank == rank]
            for candidate in tier:
                self._ensure_probed(candidate, spec)
            usable = [item for item in tier if self._is_usable(item, required)]
            if usable:
                usable.sort(key=lambda item: str(item.invocation_path).lower())
                usable.sort(key=lambda item: (not item.prerelease, _version_key(item.version)), reverse=True)
                return self._resolved(usable[0], selection, (str(usable[0].invocation_path),))

        summary = _candidate_summary(candidates, required)
        message = f"No compatible {spec.display_name} CLI was found."
        if summary:
            message += f" {summary}"
        raise AgentCliResolutionError(message, candidates)

    def _ensure_probed(self, candidate: AgentCliCandidate, spec: AgentCliSpec) -> None:
        if not candidate.invocation_path.is_file():
            candidate.probe_status = "stale"
            candidate.diagnostic = "executable no longer exists; rescan or choose another installation"
            return
        if candidate.probe_status in {"unverified", "stale"}:
            self.probe.probe(candidate, spec)

    @staticmethod
    def _is_usable(candidate: AgentCliCandidate, required: set[str]) -> bool:
        return candidate.probe_status in {"compatible", "limited"} and required <= candidate.capabilities

    def _require(self, candidate: AgentCliCandidate, required: set[str], mode: str) -> None:
        if self._is_usable(candidate, required):
            return
        missing = sorted(required - candidate.capabilities)
        detail = candidate.diagnostic or candidate.probe_status
        if missing:
            detail = f"missing capabilities: {', '.join(missing)}"
        raise AgentCliResolutionError(
            f"The {mode} {candidate.provider} CLI is not compatible: {candidate.invocation_path} ({detail}).",
            [candidate],
        )

    @staticmethod
    def _strict_path(raw: str, mode: str) -> Path:
        text = str(raw or "").strip()
        if not text:
            raise AgentCliResolutionError(f"{mode.capitalize()} CLI path is empty.")
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise AgentCliResolutionError(
                f"{mode.capitalize()} CLI path must be absolute; use automatic mode for PATH lookup: {text}"
            )
        if not path.is_file():
            raise AgentCliResolutionError(f"{mode.capitalize()} CLI path does not exist: {path}")
        return path.absolute()

    @staticmethod
    def _find_or_create(
        provider: str,
        path: Path,
        candidates: Sequence[AgentCliCandidate],
        source: str,
    ) -> AgentCliCandidate:
        target = os.path.normcase(str(path.resolve(strict=False)))
        for candidate in candidates:
            current = os.path.normcase(str(candidate.invocation_path.resolve(strict=False)))
            if current == target:
                return candidate
        canonical = path.resolve(strict=False)
        return AgentCliCandidate(provider, path, canonical, source, SOURCE_PATH)

    @staticmethod
    def _resolved(
        candidate: AgentCliCandidate,
        selection: AgentCliSelection,
        argv_prefix: Sequence[str],
    ) -> ResolvedAgentCli:
        return ResolvedAgentCli(
            provider=candidate.provider,
            argv_prefix=tuple(argv_prefix),
            invocation_path=candidate.invocation_path,
            source=candidate.source,
            version=candidate.version,
            capabilities=frozenset(candidate.capabilities),
            capability_status=candidate.probe_status,
            missing_optional=frozenset(candidate.missing_optional),
            selection_mode=selection.mode,
        )


def _version_key(value: str) -> tuple[int, ...]:
    core = value.split("-", 1)[0].split("+", 1)[0]
    return tuple(int(item) for item in core.split(".") if item.isdigit())


def _candidate_summary(candidates: Sequence[AgentCliCandidate], required: set[str]) -> str:
    parts: list[str] = []
    for candidate in candidates[:8]:
        missing = sorted(required - candidate.capabilities)
        detail = candidate.diagnostic or candidate.probe_status
        if missing and candidate.probe_status in {"compatible", "limited"}:
            detail = "missing " + ", ".join(missing)
        parts.append(f"{candidate.invocation_path} [{candidate.source}: {detail}]")
    return "Candidates: " + "; ".join(parts) if parts else ""


class AgentCliDiscoveryService:
    def __init__(
        self,
        *,
        scanner: AgentCliScanner | None = None,
        probe: AgentCliProbe | None = None,
    ) -> None:
        self.scanner = scanner or AgentCliScanner()
        self.probe = probe or AgentCliProbe()
        self.resolver = AgentCliResolver(self.probe)
        self._condition = threading.Condition()
        self._status = "idle"
        self._error = ""
        self._candidates: dict[str, list[AgentCliCandidate]] = {provider: [] for provider in BUILTIN_PROVIDERS}
        self._resolved_cache: dict[tuple[Any, ...], ResolvedAgentCli] = {}
        self._latest_resolved: dict[str, ResolvedAgentCli] = {}
        self._scan_thread: threading.Thread | None = None
        self._updated_at = 0.0

    def start(self) -> None:
        with self._condition:
            if self._status in {"scanning", "ready"}:
                return
            self._status = "scanning"
            self._error = ""
            self._scan_thread = threading.Thread(target=self._scan_worker, name="agent-cli-scan", daemon=True)
            self._scan_thread.start()

    def rescan(self) -> dict[str, Any]:
        with self._condition:
            if self._status == "scanning":
                thread = self._scan_thread
            else:
                self._status = "scanning"
                self._error = ""
                thread = None
        if thread is not None:
            thread.join(timeout=10)
            return self.snapshot()
        self._scan_worker()
        return self.snapshot()

    def wait_ready(self, timeout: float = 10.0) -> None:
        self.start()
        deadline = time.monotonic() + max(timeout, 0.0)
        with self._condition:
            while self._status == "scanning":
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise AgentCliResolutionError("Local Agent CLI discovery is still running.")
                self._condition.wait(timeout=remaining)
            if self._status != "ready":
                raise AgentCliResolutionError(self._error or "Local Agent CLI discovery failed.")

    def resolve(
        self,
        provider: str,
        selection: AgentCliSelection,
        *,
        additional_required: Iterable[str] = (),
        timeout: float = 10.0,
    ) -> ResolvedAgentCli:
        self.wait_ready(timeout)
        required = tuple(sorted({str(item) for item in additional_required}))
        key = (provider, *selection.cache_key(), required)
        with self._condition:
            cached = self._resolved_cache.get(key)
            candidates = self._candidates.get(provider, [])
        if cached and cached.invocation_path.is_file():
            return cached
        resolved = self.resolver.resolve(
            provider,
            selection,
            candidates,
            additional_required=required,
        )
        with self._condition:
            self._resolved_cache[key] = resolved
            self._latest_resolved[provider] = resolved
        return resolved

    def test_selection(
        self,
        provider: str,
        selection: AgentCliSelection,
        *,
        additional_required: Iterable[str] = (),
    ) -> dict[str, Any]:
        try:
            self.wait_ready()
        except AgentCliResolutionError as exc:
            return {"ok": False, "resolved": None, "error": str(exc), "candidates": []}
        with self._condition:
            self._resolved_cache = {
                key: value for key, value in self._resolved_cache.items() if key[0] != provider
            }
            self._latest_resolved.pop(provider, None)
            candidates = self._candidates.get(provider, [])
            if selection.mode == "auto":
                refresh_candidates = list(candidates)
            else:
                raw_path = selection.selected_path if selection.mode == "selected" else selection.manual_path
                target = os.path.normcase(str(Path(raw_path).expanduser().resolve(strict=False))) if raw_path else ""
                refresh_candidates = [
                    candidate
                    for candidate in candidates
                    if os.path.normcase(str(candidate.invocation_path.resolve(strict=False))) == target
                ]
            for candidate in refresh_candidates:
                candidate.probe_status = "unverified"
                candidate.version = ""
                candidate.prerelease = False
                candidate.capabilities.clear()
                candidate.missing_optional.clear()
                candidate.diagnostic = ""
        try:
            resolved = self.resolve(provider, selection, additional_required=additional_required)
            return {"ok": True, "resolved": resolved.to_dict(), "error": ""}
        except AgentCliResolutionError as exc:
            return {
                "ok": False,
                "resolved": None,
                "error": str(exc),
                "candidates": [candidate.to_dict() for candidate in exc.candidates],
            }

    def probe_all(self, provider: str | None = None) -> dict[str, Any]:
        self.wait_ready()
        providers = [provider] if provider else list(BUILTIN_PROVIDERS)
        with self._condition:
            groups = [(name, list(self._candidates.get(name, []))) for name in providers]
        for name, candidates in groups:
            spec = provider_spec(name)
            for candidate in candidates:
                if candidate.probe_status == "unverified":
                    self.probe.probe(candidate, spec)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "status": self._status,
                "error": self._error,
                "updatedAt": self._updated_at,
                "providers": {
                    provider: {
                        "candidates": [item.to_dict() for item in self._candidates.get(provider, [])],
                        "resolved": self._latest_resolved.get(provider).to_dict()
                        if provider in self._latest_resolved
                        else None,
                    }
                    for provider in BUILTIN_PROVIDERS
                },
            }

    def _scan_worker(self) -> None:
        try:
            candidates = self.scanner.scan_all()
        except Exception as exc:
            with self._condition:
                self._status = "error"
                self._error = str(exc)
                self._condition.notify_all()
            return
        with self._condition:
            self._candidates = candidates
            self._resolved_cache.clear()
            self._latest_resolved.clear()
            self._status = "ready"
            self._error = ""
            self._updated_at = time.time()
            self._condition.notify_all()


GLOBAL_AGENT_CLI_SERVICE = AgentCliDiscoveryService()
