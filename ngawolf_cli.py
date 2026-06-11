from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

import nga_wolf_config


@dataclass(frozen=True)
class CliPaths:
    config_path: Path
    data_dir: Path
    log_file: Path


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="Path to config.json.")
    parser.add_argument("--data-dir", type=Path, help="Path to the watcher data directory.")
    parser.add_argument("--log-file", type=Path, help="Path to the watcher log file.")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    common = argparse.ArgumentParser(add_help=False)
    _add_common_arguments(common)

    parser = argparse.ArgumentParser(
        prog="ngawolf",
        description="Headless CLI for NGA Wolf Watcher.",
        parents=[common],
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Create a new config file.")
    subparsers.add_parser("config", help="Edit an existing config file.")

    run_parser = subparsers.add_parser("run", help="Run the watcher.")
    run_parser.add_argument("--once", action="store_true", help="Run one pass and exit.")

    subparsers.add_parser("check", help="Validate config without starting the watcher.")
    subparsers.add_parser("mark-seen", help="Mark existing posts as seen.")
    subparsers.add_parser("test-send", help="Send a test message.")

    return parser.parse_args(argv)


def resolve_cli_paths(args: argparse.Namespace) -> CliPaths:
    config_override = getattr(args, "config", None)
    data_dir_override = getattr(args, "data_dir", None)
    log_file_override = getattr(args, "log_file", None)

    config_path = config_override.expanduser() if config_override is not None else nga_wolf_config.linux_config_path()
    data_dir = data_dir_override.expanduser() if data_dir_override is not None else nga_wolf_config.linux_data_dir()
    log_file = log_file_override.expanduser() if log_file_override is not None else (data_dir / nga_wolf_config.LOG_FILE)
    return CliPaths(config_path=config_path, data_dir=data_dir, log_file=log_file)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = resolve_cli_paths(args)
    print(f"config_path: {paths.config_path}")
    print(f"data_dir: {paths.data_dir}")
    print(f"log_file: {paths.log_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
