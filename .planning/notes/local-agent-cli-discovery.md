---
title: Cross-platform local Agent CLI discovery and selection
date: 2026-07-10
context: Redesign local Agent executable resolution for Codex, Claude Code, and CodeWhale
---

# Cross-platform local Agent CLI discovery and selection

## Context

NGA Wolf Watcher currently resolves local Agent executables inside `ai_analysis.py` with provider-specific, Windows-first path checks. The first existing path wins, without comparing capabilities or recording why it was chosen. This allowed a stale Codex executable under a legacy directory to shadow other installations and then fail while parsing configuration written by a newer desktop app.

The replacement must work consistently on Windows, macOS, Linux, and WSL; support automatic discovery, selection from detected installations, and an explicit manual path; and apply the same lifecycle to Codex, Claude Code, and CodeWhale. The existing `custom` provider remains manual-only in the first version.

## Confirmed decisions

1. Automatic mode respects `PATH` order first. It does not globally choose the highest version.
2. A detected installation selected by the user is pinned to that invocation path. If it becomes invalid, the task fails with an actionable error instead of silently falling back.
3. A manually entered executable is also strict and never silently replaced.
4. Automatic discovery covers the built-in Codex, Claude Code, and CodeWhale providers. Arbitrary user-defined probe commands are out of scope for v1.
5. Discovery runs once during service startup and is cached. Settings can trigger an explicit rescan. AI requests never initiate a scan.
6. Provider-specific model invocation remains in each Runner; executable discovery and validation move into a shared subsystem.

## Goals

- Make the selected executable deterministic and visible.
- Respect explicit user intent before compatibility fallbacks.
- Support common native, package-manager, and legacy installations across all supported operating systems.
- Validate the exact capabilities NGA Wolf Watcher needs without sending prompts or invoking a model.
- Preserve backward compatibility with the existing `ai_*_command` fields.
- Produce diagnostics that explain every rejected candidate.

## Non-goals

- Installing or updating Agent CLIs.
- Querying the internet for the latest available version.
- Selecting a CLI only because its semantic version is highest.
- Scanning inside desktop application bundles or protected app-package directories.
- Letting users define arbitrary discovery or probe commands in v1.
- Replacing the existing `custom` command-template mechanism.

## Architecture

### `AgentCliRegistry`

A static registry owns the safe, built-in definition for each provider:

```python
@dataclass(frozen=True)
class AgentCliSpec:
    provider: str
    display_name: str
    aliases: tuple[str, ...]
    detectors: tuple[CliDetector, ...]
    version_probe: ProbeSpec
    capability_probes: tuple[ProbeSpec, ...]
    required_capabilities: frozenset[str]
    optional_capabilities: frozenset[str]
```

The registry contains data and probe definitions only. It must not know about GUI widgets or task execution.

### `AgentCliScanner`

The scanner discovers candidate invocation paths from `PATH`, known install roots, and safe package-manager prefix queries. Discovery is filesystem-only and does not invoke the candidate executable.

```python
@dataclass
class AgentCliCandidate:
    provider: str
    invocation_path: Path
    canonical_path: Path
    source: str
    source_rank: int
    path_order: int | None
    aliases: tuple[str, ...]
    probe_status: str = "unverified"
    version: str = ""
    prerelease: bool = False
    capabilities: set[str] = field(default_factory=set)
    diagnostic: str = ""
```

Candidates are deduplicated by canonical file identity where possible, while retaining the invocation path that the user or package manager controls. A symlink may continue to point at a newer binary after an update; this is allowed, but the target is revalidated on startup.

### `AgentCliProbe`

The probe executes only registry-defined version and help commands:

- `stdin` is closed.
- `shell=False` is mandatory.
- Each command has a short timeout and bounded output.
- The probe runs from a neutral working directory.
- Provider-specific environment flags disable automatic updates where officially supported.
- It never runs `doctor`, login, authentication, or a model request.

Discovery and probing are separate. Startup discovers all providers but probes only candidates needed to resolve the active provider. Selecting or manually entering a CLI probes that choice before saving. The settings UI may explicitly request validation of additional candidates.

This separation avoids triggering package launchers or background updaters merely to populate a list. A launcher that cannot guarantee a side-effect-free `--version` call remains `unverified` until it is needed or the user requests a test.

### `AgentCliResolver`

The resolver consumes configuration and cached candidates and produces one immutable result for the Runner:

```python
@dataclass(frozen=True)
class ResolvedAgentCli:
    provider: str
    argv_prefix: tuple[str, ...]
    invocation_path: Path
    source: str
    version: str
    capabilities: frozenset[str]
    selection_mode: str
```

Runners receive `argv_prefix` and do not perform path discovery themselves.

### `AgentCliDiscoveryService`

The service owns the in-memory cache and lifecycle:

- Start one background discovery pass during service startup.
- Expose `initializing`, `ready`, and `error` states.
- Resolve and probe the active provider before marking AI ready.
- Return cached results to GUI, WebUI, CLI status, and logs.
- Replace the cache atomically after an explicit rescan.
- Never scan from an AI request.

If an executable disappears after startup, the current task fails, the cached candidate is marked stale, and the user is told to rescan or change the selection. It does not silently switch providers or executables.

## Selection modes

### Automatic

Automatic selection uses this order:

1. Compatible candidates found by walking `PATH` in its declared order.
2. Compatible candidates from current official native-install locations.
3. Compatible candidates from current package-manager locations.
4. Compatible candidates from explicitly supported legacy locations.

An incompatible candidate does not block candidates later in the same tier. Within a non-`PATH` tier, the deterministic tiebreakers are:

1. all required capabilities present;
2. stable release before prerelease;
3. higher parsed version;
4. normalized invocation path for a stable final ordering.

The resolver records why every earlier candidate was rejected. It never checks a remote registry to decide what is newest.

### Selected installation

The user chooses a discovered invocation path. That path is persisted and re-probed on startup and when saved. Updating the executable behind the same path is allowed. If the path disappears or loses a required capability, AI tasks fail with no automatic fallback. The UI offers an explicit “switch to automatic” action.

### Manual

Manual configuration stores a path and a separate argument array. A bare command name is not accepted in strict manual mode; users who want `PATH` semantics should use automatic mode. Manual configuration is probed before saving and is never replaced automatically.

## Cross-platform discovery

`PATH` is always scanned first and all entries are preserved in order. Known roots supplement `PATH` for GUI/services that may inherit an incomplete environment.

| Platform | Common supplemental sources |
| --- | --- |
| Windows | official standalone roots, `%USERPROFILE%\.local\bin`, WinGet Links, npm global prefix, provider legacy roots |
| macOS | `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, npm global prefix, `~/.cargo/bin` |
| Linux | `~/.local/bin`, `/usr/local/bin`, `/usr/bin`, npm global prefix, `~/.cargo/bin` |
| WSL | Linux rules only; never cross-discover Windows executables |

Safe package-manager detectors may query `npm prefix -g` and `brew --prefix` when those commands are already available. They use short timeouts and cannot install or update packages. System packages under `/usr/bin` are found through `PATH` or known roots; the scanner does not invoke `apt`, `dnf`, or `apk`.

Provider aliases:

- Codex: `codex`
- Claude Code: `claude`
- CodeWhale: `codewhale`, `codew`, plus explicitly ranked legacy aliases where supported

Desktop app internals such as Microsoft Store/WindowsApps resources or macOS application-bundle helpers are excluded. These are implementation details of another product surface and may be protected, moved, or versioned independently.

Official installation references:

- [Codex environment and standalone installer locations](https://learn.chatgpt.com/docs/config-file/environment-variables)
- [Claude Code installation methods](https://code.claude.com/docs/en/installation)
- [CodeWhale installation methods](https://codewhale.net/en/install)

## Provider capability profiles

The registry validates capabilities rather than relying on a minimum version alone.

### Codex

Required probes cover:

- `codex --version`
- `codex exec --help`
- `codex exec resume --help`
- non-interactive execution and last-message output
- session resume arguments used by the current Runner
- `--ignore-user-config` when user-config isolation is enabled

Optional capabilities include image input and other features that the Runner can omit safely.

### Claude Code

Required probes cover:

- `claude --version`
- stream JSON input and output
- the stdio permission-prompt protocol
- replayed user messages and verbose stream mode
- model, effort, and permission flags used by the current persistent session

Probe subprocesses set the documented update-disable environment for the duration of validation so detection does not initiate an update.

### CodeWhale

Required probes cover:

- `codewhale --version`
- `exec` with stream JSON output
- automatic execution mode
- model and runtime config arguments
- session resume support used by the current Runner

CodeWhale npm entries may be launchers around a downloaded native binary. Discovery records the launcher without executing it; validation occurs only when it is needed for resolution or explicitly requested.

## Candidate states

- `unverified`: discovered but not executed
- `compatible`: all required capabilities are present
- `limited`: required core capabilities are present but optional features are missing
- `incompatible`: a required capability is absent
- `failed`: the executable could not start or returned unparseable output
- `timeout`: a probe exceeded its deadline
- `stale`: a previously selected path no longer exists

Only `compatible` and explicitly permitted `limited` candidates may be auto-selected. The UI must name the missing optional features before allowing a limited candidate.

## Configuration model

Selections are stored for every built-in provider so switching providers restores the previous choice:

```json
{
  "ai_cli": {
    "codex": {
      "mode": "auto",
      "selected_path": "",
      "manual_path": "",
      "manual_args": []
    },
    "claude": {
      "mode": "selected",
      "selected_path": "/Users/me/.local/bin/claude",
      "manual_path": "",
      "manual_args": []
    },
    "codewhale": {
      "mode": "manual",
      "selected_path": "",
      "manual_path": "/opt/agents/codewhale",
      "manual_args": []
    }
  }
}
```

Valid modes are `auto`, `selected`, and `manual`. `selected_path` and `manual_path` are mutually exclusive by mode. `manual_args` is an array so quoting is never reinterpreted by a shell.

Headless environment overrides follow the same model, for example:

- `AI_CODEX_CLI_MODE`
- `AI_CODEX_CLI_PATH`
- `AI_CODEX_CLI_ARGS`

Equivalent variables exist for Claude and CodeWhale. JSON configuration remains the durable source; environment variables are process-scoped overrides.

### Backward migration

- A legacy command equal to the provider’s default command name becomes `auto`.
- A non-default legacy command or path becomes `manual` after parsing into path and arguments.
- Ambiguous legacy command strings are preserved and reported for user confirmation rather than silently rewritten.
- `ai_custom_command` remains unchanged.
- Old fields are read for at least one compatibility release but new saves write the structured configuration.

## User experience

Each provider section in GUI and WebUI shows:

- mode: Automatic, Detected installation, or Manual;
- current resolved path, version, source, and compatibility state;
- discovered candidates with source, version, and rejection reason;
- actions: Use this installation, Test, Rescan, Switch to automatic;
- an explanation of why automatic mode chose the current candidate.

The desktop GUI may provide a native file picker for manual mode. WebUI accepts a server-side path and makes clear that scanning occurs on the server host, not the browser machine.

Headless management adds commands such as:

```text
ngawolf agent-cli list
ngawolf agent-cli list --provider codex
ngawolf agent-cli test codex
ngawolf agent-cli rescan
```

`ngawolf check` includes the resolved provider, selection mode, path, version, and compatibility result.

## Error handling and observability

Startup and task logs include:

```text
provider=codex
selection_mode=auto
source=PATH
executable=C:\...\codex.exe
version=0.x.y
capability_status=compatible
```

They also include bounded rejection summaries for skipped candidates. Commands and environment values continue to use existing secret redaction. Errors shown to users include the selected path, failure category, and exact recovery actions without including credentials or full environment dumps.

## Security requirements

- Never invoke discovery or probes with a shell.
- Keep executable path and arguments structurally separate.
- Only built-in registry probes may run automatically.
- Close stdin and cap time, stdout, and stderr for every probe.
- Do not run model, authentication, update, installer, or doctor commands during automatic detection.
- Do not traverse protected desktop application internals.
- Resolve and validate paths without deleting, modifying, or repairing installations.
- Manual selections receive no automatic fallback.

## Test strategy

### Unit tests

- Candidate generation for Windows, macOS, Linux, and WSL.
- `PATH` ordering, PATHEXT handling, aliases, symlinks, and deduplication.
- Package-manager prefix parsing and timeout behavior.
- Version parsing, prerelease classification, and capability extraction.
- Automatic ranking and rejection diagnostics.
- Strict selected/manual behavior with no fallback.
- Legacy configuration migration.
- Cache replacement and stale-path handling.

### Integration tests

- Fake executables emitting representative version/help output for all providers.
- Probe timeouts, nonzero exits, malformed output, and missing flags.
- GUI/WebUI API payloads and configuration round trips.
- Service startup readiness and explicit rescan behavior.
- Existing Runner commands receiving the resolved `argv_prefix` unchanged.

### Platform verification

Run the discovery and selection suite on Windows, macOS, and Linux CI workers. Platform-specific tests should use temporary fake install roots and must not depend on a real Agent account or network access.

## Implementation sequence

1. Introduce registry, candidate, probe, resolver, and cache types behind tests.
2. Implement cross-platform detectors and deterministic automatic selection.
3. Add structured configuration and backward migration.
4. Integrate the resolved CLI into Codex, Claude, and CodeWhale Runners.
5. Add service lifecycle, status APIs, and logging.
6. Add GUI, WebUI, and headless management surfaces.
7. Update documentation and complete the cross-platform test matrix.

## Acceptance criteria

- With multiple installations, automatic mode selects the first compatible `PATH` candidate and explains the choice.
- An incompatible `PATH` candidate is skipped with a diagnostic and a compatible fallback may be selected.
- Selected and manual modes never fall back silently.
- Windows, macOS, Linux, and WSL candidate discovery behaves deterministically.
- Codex, Claude Code, and CodeWhale use the same discovery lifecycle and provider-specific capability profiles.
- Startup performs one cached discovery pass; AI requests perform none.
- No automatic probe sends a model request, authenticates, installs, updates, or runs `doctor`.
- Existing command configuration migrates without losing an explicit user path or arguments.
- GUI, WebUI, headless CLI, logs, and `ngawolf check` display the same resolved result.
