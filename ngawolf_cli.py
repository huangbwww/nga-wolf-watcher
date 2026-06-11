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


def prompt_text(label: str, current: object = "", *, secret: bool = False) -> str:
    current_text = "" if current is None else str(current)
    if secret and current_text:
        prompt = f"{label} [hidden]: "
    elif current_text:
        prompt = f"{label} [{current_text}]: "
    else:
        prompt = f"{label}: "
    value = input(prompt)
    return current_text if value == "" else value


def prompt_basic_config(config: dict[str, object]) -> dict[str, object]:
    updated = dict(config)
    updated["bot_channel"] = prompt_text("Bot channel", updated.get("bot_channel", "feishu"))
    updated["nga_cookie"] = prompt_text("NGA cookie", updated.get("nga_cookie", ""), secret=True)
    updated["email_to"] = prompt_text("Email to", updated.get("email_to", ""))
    updated["email_username"] = prompt_text("Email username", updated.get("email_username", ""))
    updated["email_password"] = prompt_text("Email password", updated.get("email_password", ""), secret=True)
    updated["feishu_app_id"] = prompt_text("Feishu app ID", updated.get("feishu_app_id", ""))
    updated["feishu_app_secret"] = prompt_text("Feishu app secret", updated.get("feishu_app_secret", ""), secret=True)
    updated["feishu_receive_id"] = prompt_text("Feishu receive ID", updated.get("feishu_receive_id", ""))
    updated["wechat_bot_token"] = prompt_text("WeChat bot token", updated.get("wechat_bot_token", ""), secret=True)
    updated["wechat_bot_target_user_id"] = prompt_text("WeChat target user ID", updated.get("wechat_bot_target_user_id", ""))
    updated["dingtalk_client_id"] = prompt_text("DingTalk client ID", updated.get("dingtalk_client_id", ""))
    updated["dingtalk_client_secret"] = prompt_text("DingTalk client secret", updated.get("dingtalk_client_secret", ""), secret=True)
    updated["dingtalk_target_user_ids"] = prompt_text("DingTalk target user IDs", updated.get("dingtalk_target_user_ids", ""))
    updated["watch_mode"] = prompt_text("Watch mode", updated.get("watch_mode", "author"))
    updated["watch_author_ids"] = prompt_text("Watch author IDs", updated.get("watch_author_ids", ""))
    updated["preset_thread_ids"] = prompt_text("Preset thread IDs", updated.get("preset_thread_ids", ""))
    updated["interval"] = prompt_text("Interval", updated.get("interval", "30"))
    updated["jitter"] = prompt_text("Jitter", updated.get("jitter", "20"))
    updated["state_path"] = prompt_text("State path", updated.get("state_path", ".nga_seen.json"))
    return updated


def command_init(paths: CliPaths) -> int:
    if paths.config_path.exists():
        print(f"Config already exists: {paths.config_path}", file=sys.stderr)
        return 2
    config = prompt_basic_config(dict(nga_wolf_config.DEFAULT_CONFIG))
    nga_wolf_config.save_config(config, paths.config_path)
    print(paths.config_path)
    return 0


def command_config(paths: CliPaths) -> int:
    if not paths.config_path.exists():
        print(f"Config not found: {paths.config_path}", file=sys.stderr)
        return 2
    config = nga_wolf_config.load_config(paths.config_path)
    updated = prompt_basic_config(config)
    nga_wolf_config.save_config(updated, paths.config_path)
    print(paths.config_path)
    return 0


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
    if args.command == "init":
        return command_init(paths)
    if args.command == "config":
        return command_config(paths)
    print(f"{args.command} is not implemented yet.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
