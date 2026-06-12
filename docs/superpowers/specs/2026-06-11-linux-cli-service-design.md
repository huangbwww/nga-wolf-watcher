# Linux CLI Service Mode Design

## Context

Issue #20 asks whether NGA Wolf Watcher can run on a headless Linux server without a display, either through a web interface or as a pure service driven by `config.json`.

The chosen first phase is a simple interactive CLI configuration flow, not a web admin UI and not a full-screen TUI. This keeps the Linux path easy to deploy over SSH, friendly to systemd and Docker, and aligned with the existing watcher logic.

## Goals

- Run on headless Linux without `customtkinter`, `pywebview`, a display server, or a browser shell.
- Share the same watcher, channel, rule, AI, retry, quiet-hours, and state logic used by the current desktop app.
- Provide a low-friction command-line setup flow that can create and update `config.json`.
- Support foreground service execution for systemd, Docker, tmux, and manual debugging.
- Keep the first phase small enough to deliver without building a remote web management system.

## Non-Goals

- No web management console in this phase.
- No full-screen TUI in this phase.
- No multi-user remote permission model.
- No separate Linux-only watcher implementation.
- No automatic privileged installation into `/etc` or systemd unless explicitly requested by the user during a later phase.

## Command Shape

The Linux-friendly command should be named `ngawolf`.

Primary commands:

```bash
ngawolf init
ngawolf config
ngawolf run
ngawolf check
ngawolf mark-seen
ngawolf test-send
```

Common options:

```bash
--config /path/to/config.json
--data-dir /path/to/state-dir
--log-file /path/to/watcher.log
```

Default paths on Linux:

```text
~/.config/ngawolf/config.json
~/.local/state/ngawolf/
~/.local/state/ngawolf/watcher.log
```

`--config` and `--data-dir` always override defaults. Relative paths inside the config, such as `state_path` and `AI_WORK_DIR`, resolve under the selected data directory for CLI service mode.

## Interactive Configuration

`ngawolf init` creates a new config file. If the file already exists, it should refuse to overwrite unless the user passes a future explicit option such as `--force`, or it should suggest `ngawolf config`.

`ngawolf config` edits an existing config. For each prompt, the current value is shown and pressing Enter keeps it unchanged. This makes small changes fast over SSH.

The first phase should cover the configuration needed for a normal working deployment:

- NGA Cookie.
- Watch mode: user homepage, fixed thread author filter, or both.
- Watched user IDs and labels.
- Preset thread IDs and labels.
- Listen rules and push target selection.
- Message channel setup for Feishu, WeChat, DingTalk, and email, using the same config fields as the desktop app.
- Polling and retry basics: interval, jitter, timeout, retry count.
- State file location.
- First-start behavior: whether to mark existing results as seen before running.

The prompt flow should be plain line-based input, not a curses UI. Secrets should be accepted from stdin without echo when practical, but the implementation may fall back to normal input if the terminal does not support hidden entry.

## Runtime Commands

`ngawolf run` loads config, validates it, builds watcher args from the shared config adapter, and runs in the foreground until interrupted.

Expected behavior:

- Logs go to stdout/stderr by default.
- If `--log-file` is passed, output is mirrored or redirected to that file.
- Ctrl+C should stop cleanly.
- The command should return non-zero for invalid config or startup failures.

`ngawolf check` validates config without starting the long-running watcher. It should report:

- Missing required fields.
- Invalid IDs or listen rules.
- Channel credential problems detectable without sending messages.
- Optional live checks, such as NGA Cookie validation, if the implementation already has a safe reusable helper.

`ngawolf mark-seen` runs one mark-seen pass using the selected config and state path.

`ngawolf test-send` sends a test message through the configured target or selected target id. It should not require starting the watcher loop.

## Architecture

The implementation should avoid importing desktop GUI modules from the Linux CLI. Existing shared behavior currently lives partly in `nga_wolf_gui.py`, so the implementation should extract reusable configuration helpers before adding the CLI entrypoint.

Proposed module boundaries:

- `nga_wolf_config.py`: default config, config file read/write, path resolution, validation, config-to-arg conversion.
- `ngawolf_cli.py`: argparse command dispatcher and interactive prompts.
- `nga_feishu_watch.py`: existing watcher, channel, command, AI, and polling behavior.
- `nga_wolf_gui.py` and `nga_wolf_webgui.py`: desktop wrappers that consume the shared config module instead of owning service config logic.

The CLI should call the same watcher functions as the desktop app after config is converted to an `argparse.Namespace`. No watcher behavior should be duplicated for Linux.

## Data Flow

```text
ngawolf init/config
  -> config prompts
  -> config.json

ngawolf run/check/mark-seen/test-send
  -> read config.json
  -> resolve paths under data-dir
  -> validate config
  -> build watcher args
  -> call shared watcher functions
```

## Packaging

The first implementation can work as:

```bash
python ngawolf_cli.py run
```

The user-facing command name remains `ngawolf`. Packaging can later expose it through a console script, standalone binary, or Docker image without changing the command contract.

## Error Handling

- Config parse errors should include the path and a short JSON error message.
- Validation errors should be grouped and printed before exit.
- Missing optional channel dependencies should explain which feature needs the dependency.
- Runtime exceptions should be logged and should preserve existing watcher retry/backoff behavior where applicable.
- `init` and `config` should write config atomically to avoid corrupting an existing file.

## Testing

Unit tests should cover:

- Default Linux path resolution.
- `--config` and `--data-dir` override behavior.
- Config load/save round trip.
- Pressing Enter in `ngawolf config` keeps existing values.
- Config-to-args conversion matches existing desktop behavior for representative Feishu, WeChat, DingTalk, and email configs.
- `run`, `mark-seen`, and `test-send` dispatch to the expected watcher functions with a mocked watcher layer.

Manual verification should cover:

- Fresh `ngawolf init` creates a valid config.
- `ngawolf config` edits one field without changing unrelated fields.
- `ngawolf check` catches missing Cookie and missing push target.
- `ngawolf run --once` or equivalent smoke path can execute without importing GUI dependencies.

## Open Decisions

- Whether the first command script is installed as `ngawolf` immediately or documented as `python ngawolf_cli.py` until packaging is added.
- Whether `install-systemd` belongs in the first implementation or should wait until the base CLI proves stable.

The recommended first implementation is to defer systemd generation and packaging polish, but keep the command names stable.
