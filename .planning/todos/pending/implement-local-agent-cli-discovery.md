---
title: Implement cross-platform local Agent CLI discovery and selection
date: 2026-07-10
priority: high
---

# Implement cross-platform local Agent CLI discovery and selection

## Source design

Implement the approved design in [`../../notes/local-agent-cli-discovery.md`](../../notes/local-agent-cli-discovery.md).

## Outcome

Replace the current provider-specific executable lookup with a shared, observable, cross-platform discovery and selection subsystem for Codex, Claude Code, and CodeWhale. Preserve `custom` as manual-only.

## Work items

- [x] Add `AgentCliSpec`, `AgentCliCandidate`, `ResolvedAgentCli`, and structured selection configuration types.
- [x] Add the built-in provider registry and safe version/capability probes.
- [x] Implement ordered `PATH` scanning, supplemental platform detectors, package-manager prefix detectors, canonical deduplication, and bounded timeouts.
- [x] Implement automatic, selected, and manual resolution semantics.
- [x] Add startup discovery/cache lifecycle and explicit rescan support; prohibit request-time scanning.
- [x] Migrate `ai_codex_command`, `ai_claude_command`, and `ai_codewhale_command` without losing explicit commands or arguments.
- [x] Refactor Codex, Claude, and CodeWhale Runners to consume `ResolvedAgentCli.argv_prefix`.
- [x] Add shared status/diagnostic payloads to configuration APIs and `ngawolf check`.
- [x] Add GUI controls for mode, candidate selection, manual file selection, test, and rescan.
- [x] Add equivalent WebUI controls with server-host path semantics.
- [x] Add headless `ngawolf agent-cli list|test|rescan` commands.
- [x] Add startup and task logging for selection mode, source, path, version, capability state, and rejection summaries.
- [x] Update English and Chinese AI documentation.
- [x] Add unit and integration coverage for Windows, macOS, Linux, WSL, legacy migration, strict pinning, capability failures, and caching.

## Guardrails

- Automatic resolution must prefer compatible `PATH` entries in declared order.
- Selected/manual modes must never fall back silently.
- Candidate execution must use `shell=False`, closed stdin, bounded output, and short timeouts.
- Automatic discovery must not run installers, updates, login, authentication, doctor, or model commands.
- Do not scan protected desktop application bundle internals.
- Do not introduce user-defined automatic probe commands in v1.
- Preserve unrelated local changes and keep the migration backward compatible for at least one release.

## Verification

- [x] Targeted discovery/resolver/config migration tests pass.
- [x] Full Python test suite passes.
- [x] WebUI tests/build pass where configured.
- [ ] Cross-platform discovery tests pass on Windows, macOS, and Linux CI.
- [x] Manual smoke checks confirm automatic behavior for Codex, Claude Code, and CodeWhale installed on the test host; selected/manual strict behavior is covered by integration tests.
- [x] Logs and user-facing errors contain no credentials or complete environment dumps.

## Done when

All acceptance criteria in the source design are met, the old hard-coded resolution path is no longer used by built-in Runners, and users can see and control exactly which local Agent CLI will execute.
