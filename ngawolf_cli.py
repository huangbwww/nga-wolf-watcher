from __future__ import annotations

import argparse
import json
import getpass
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import nga_feishu_watch
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
    if secret:
        try:
            value = getpass.getpass(prompt).strip()
        except (EOFError, OSError, ValueError):
            value = input(prompt).strip()
    else:
        value = input(prompt).strip()
    return current_text if value == "" else value


def prompt_choice(label: str, choices: list[tuple[str, str]], current: object = "") -> str:
    current_text = "" if current is None else str(current).strip()
    values = {value for value, _ in choices}
    for index, (value, title) in enumerate(choices, start=1):
        marker = "*" if value == current_text else " "
        print(f"  {marker} {index}. {title} ({value})")
    while True:
        raw = input(f"{label} [{current_text}]: ").strip()
        if raw == "":
            return current_text or choices[0][0]
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(choices):
                return choices[index - 1][0]
        normalized = raw.lower()
        if normalized in values:
            return normalized
        print(f"Please choose 1-{len(choices)} or one of: {', '.join(value for value, _ in choices)}", file=sys.stderr)


def prompt_multi_select(
    label: str,
    options: list[dict[str, str]],
    selected_values: list[str] | None = None,
) -> list[dict[str, str]]:
    selected = set(selected_values or [])
    value_to_option = {str(option.get("value") or ""): option for option in options}
    selected = {value for value in selected if value in value_to_option}

    while True:
        print(label)
        for index, option in enumerate(options, start=1):
            value = str(option.get("value") or "")
            checked = "x" if value in selected else " "
            title = str(option.get("label") or value)
            print(f"  [{checked}] {index}. {title} ({value})")

        raw = input("Select numbers, 'a' all, 'n' none, Enter confirm: ").strip().lower()
        if raw == "":
            return [option for option in options if str(option.get("value") or "") in selected]
        if raw == "a":
            selected = set(value_to_option)
            continue
        if raw == "n":
            selected.clear()
            continue

        changed = False
        for token in re.split(r"[,，;；\s]+", raw):
            if not token:
                continue
            if not token.isdigit():
                print(f"Ignored invalid selection: {token}", file=sys.stderr)
                continue
            index = int(token)
            if not 1 <= index <= len(options):
                print(f"Ignored out-of-range selection: {token}", file=sys.stderr)
                continue
            value = str(options[index - 1].get("value") or "")
            if value in selected:
                selected.remove(value)
            else:
                selected.add(value)
            changed = True
        if not changed:
            print("No valid selection changed.", file=sys.stderr)


def _prompt_fields(config: dict[str, object], fields: list[tuple[str, str, bool]]) -> None:
    for key, label, secret in fields:
        config[key] = prompt_text(label, config.get(key, ""), secret=secret)


def _normalize_bot_channel(value: object) -> str:
    channel = str(value or "feishu").strip().lower()
    if channel not in {"feishu", "wechat", "dingtalk", "email"}:
        raise ValueError("bot_channel must be one of: feishu, wechat, dingtalk, email")
    return channel


def _json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if not value:
        return []
    try:
        loaded = json.loads(str(value))
    except Exception:
        return []
    if not isinstance(loaded, list):
        return []
    return [item for item in loaded if isinstance(item, dict)]


def _chat_options(chats: list[dict[str, object]]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for chat in nga_feishu_watch.merge_feishu_chats(chats):
        chat_id = str(chat.get("chat_id") or "").strip()
        if not chat_id:
            continue
        label = str(chat.get("name") or chat_id).strip() or chat_id
        options.append({"value": chat_id, "label": label})
    return options


def _current_feishu_target_ids(config: dict[str, object]) -> list[str]:
    ids = [
        str(target.get("receive_id") or "").strip()
        for target in _json_list(config.get("push_targets"))
        if str(target.get("channel") or "feishu").strip() == "feishu"
    ]
    if ids:
        return [item for item in ids if item]
    receive_id = str(config.get("feishu_receive_id") or "").strip()
    return [receive_id] if receive_id else []


def _target_ids_from_config(config: dict[str, object]) -> list[str]:
    return [
        str(target.get("id") or "").strip()
        for target in _json_list(config.get("push_targets"))
        if str(target.get("id") or "").strip()
    ]


def _configure_feishu_channel(config: dict[str, object]) -> None:
    config["feishu_app_id"] = prompt_text("Feishu app ID", config.get("feishu_app_id", ""))
    config["feishu_app_secret"] = prompt_text("Feishu app secret", config.get("feishu_app_secret", ""), secret=True)

    app_id = str(config.get("feishu_app_id") or "").strip()
    app_secret = str(config.get("feishu_app_secret") or "").strip()
    profile = {
        "id": "default",
        "label": "Default Feishu bot",
        "app_id": app_id,
        "app_secret": app_secret,
        "id_type": "chat_id",
        "chats": [],
    }
    selected_chats: list[dict[str, str]] = []
    should_list_chats = bool(app_id and app_secret) and not _current_feishu_target_ids(config)
    if should_list_chats:
        try:
            chats = nga_feishu_watch.list_feishu_chats(app_id, app_secret, 10)
        except Exception as exc:
            print(f"Could not list Feishu groups: {exc}", file=sys.stderr)
            chats = []
        options = _chat_options(chats)
        if options:
            selected_chats = prompt_multi_select("Feishu groups visible to this bot", options)
            profile["chats"] = [
                {
                    "chat_id": chat["value"],
                    "name": chat["label"],
                    "chat_type": "",
                    "description": "",
                }
                for chat in selected_chats
            ]

    if selected_chats:
        targets = []
        for index, chat in enumerate(selected_chats, start=1):
            targets.append(
                {
                    "id": f"feishu_{index}",
                    "label": chat["label"],
                    "channel": "feishu",
                    "profile_id": "default",
                    "receive_id": chat["value"],
                    "id_type": "chat_id",
                    "default_author_id": str(config.get("default_author_id") or "150058").strip(),
                    "default_tid": str(config.get("default_tid") or "45974302").strip(),
                }
            )
        config["feishu_receive_id"] = selected_chats[0]["value"]
        config["push_targets"] = _json_dumps(targets)
    else:
        config["feishu_receive_id"] = prompt_text("Feishu receive ID", config.get("feishu_receive_id", ""))

    config["feishu_id_type"] = "chat_id"
    config["feishu_bot_profiles"] = _json_dumps([profile])


def _sync_listen_rules(config: dict[str, object]) -> None:
    target_ids = _target_ids_from_config(config)
    if not target_ids:
        return
    rules: list[dict[str, object]] = []
    watch_mode = str(config.get("watch_mode") or "author").strip()
    if watch_mode in {"author", "both"}:
        for target in nga_feishu_watch.parse_target_list(config.get("watch_author_ids"), str(config.get("default_author_id") or "150058")):
            rules.append(
                {
                    "id": f"author:{target.id}",
                    "label": target.label,
                    "mode": "author",
                    "author_id": target.id,
                    "tid": "",
                    "target_ids": list(target_ids),
                }
            )
    if watch_mode in {"thread_author", "both"}:
        for watch in nga_feishu_watch.parse_thread_author_watches(config.get("thread_author_watches")):
            rules.append(
                {
                    "id": f"thread_author:{watch.tid}:{watch.author_id}",
                    "label": watch.label,
                    "mode": "thread_author",
                    "author_id": watch.author_id,
                    "tid": watch.tid,
                    "target_ids": list(target_ids),
                }
            )
    if rules:
        config["listen_rules"] = _json_dumps(rules)


def prompt_basic_config(config: dict[str, object]) -> dict[str, object]:
    updated = dict(config)
    updated["bot_channel"] = _normalize_bot_channel(
        prompt_choice(
            "Bot channel",
            [
                ("feishu", "Feishu"),
                ("email", "Email"),
                ("wechat", "WeChat"),
                ("dingtalk", "DingTalk"),
            ],
            updated.get("bot_channel", "feishu"),
        )
    )
    updated["nga_cookie"] = prompt_text("NGA cookie", updated.get("nga_cookie", ""), secret=True)
    channel = str(updated.get("bot_channel") or "feishu").strip()
    channel_fields = {
        "email": [
            ("email_to", "Email to", False),
            ("email_username", "Email username", False),
            ("email_password", "Email password", True),
        ],
        "wechat": [
            ("wechat_bot_token", "WeChat bot token", True),
            ("wechat_bot_target_user_id", "WeChat target user ID", False),
        ],
        "dingtalk": [
            ("dingtalk_client_id", "DingTalk client ID", False),
            ("dingtalk_client_secret", "DingTalk client secret", True),
            ("dingtalk_target_user_ids", "DingTalk target user IDs", False),
        ],
    }
    if channel == "feishu":
        _configure_feishu_channel(updated)
    else:
        _prompt_fields(updated, channel_fields.get(channel, []))
    updated["watch_mode"] = prompt_choice(
        "Watch mode",
        [
            ("author", "Watch user profile replies"),
            ("thread_author", "Watch author inside fixed thread"),
            ("both", "Watch both"),
        ],
        updated.get("watch_mode", "author"),
    )
    updated["watch_author_ids"] = prompt_text("Watch author IDs", updated.get("watch_author_ids", ""))
    updated["preset_thread_ids"] = prompt_text("Preset thread IDs", updated.get("preset_thread_ids", ""))
    if str(updated.get("watch_mode") or "author") in {"thread_author", "both"}:
        updated["thread_author_watches"] = prompt_text("Thread author watches", updated.get("thread_author_watches", ""))
    updated["interval"] = prompt_text("Interval", updated.get("interval", "30"))
    updated["jitter"] = prompt_text("Jitter", updated.get("jitter", "20"))
    updated["state_path"] = prompt_text("State path", updated.get("state_path", ".nga_seen.json"))
    _sync_listen_rules(updated)
    return updated


def load_existing_config_for_edit(path: Path) -> dict[str, object] | None:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
    except Exception:
        return None
    if not isinstance(loaded, dict):
        return None
    config = dict(nga_wolf_config.DEFAULT_CONFIG)
    config.update(loaded)
    return config


def load_service_config(paths: CliPaths) -> dict[str, object]:
    return nga_wolf_config.load_config(paths.config_path, nga_wolf_config.DEFAULT_CONFIG)


def build_service_args(paths: CliPaths, config: dict[str, object], mark_seen: bool = False):
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    return nga_wolf_config.build_args(config, data_dir=paths.data_dir, mark_seen=mark_seen)


def print_validation_errors(errors: list[str]) -> None:
    for error in errors:
        print(error, file=sys.stderr)


def validate_mark_seen_config(config: dict[str, object]) -> list[str]:
    errors: list[str] = []
    if not str(config.get("nga_cookie") or "").strip():
        errors.append("NGA Cookie")

    watch_mode = str(config.get("watch_mode") or "author").strip()
    if watch_mode not in {"author", "thread_author", "both"}:
        errors.append("Watch mode must be author, thread_author, or both")

    def validate_author_selectors() -> None:
        raw = str(config.get("watch_author_ids") or "").strip()
        default_author_id = str(config.get("default_author_id") or "150058").strip()
        if not raw:
            if not default_author_id.isdigit():
                errors.append("Default author ID must be numeric")
            return
        parsed_any = False
        for item in re.split(r"[\r\n]+", raw):
            for token in [part.strip() for part in re.split(r"[,，;；\s]+", item) if part.strip()]:
                main = token.split("|", 1)[0].strip()
                if "=" in main:
                    raw_id = main.split("=", 1)[0].strip()
                elif ":" in main:
                    raw_id = main.split(":", 1)[0].strip()
                else:
                    raw_id = main
                if raw_id.isdigit():
                    parsed_any = True
                    continue
                errors.append(f"Watch author IDs contains non-numeric ID: {raw_id or token}")
        if not parsed_any:
            errors.append("Watch author IDs must contain at least one numeric ID")

    def validate_thread_author_selectors() -> None:
        raw_thread_watches = str(config.get("thread_author_watches") or "").strip()
        raw_listen_rules = str(config.get("listen_rules") or "").strip()
        parsed_watches = nga_feishu_watch.parse_thread_author_watches(raw_thread_watches)
        parsed_rules = [rule for rule in nga_feishu_watch.parse_listen_rules(raw_listen_rules) if rule.mode == "thread_author"]
        if not raw_thread_watches and not parsed_rules:
            errors.append("Thread author watches must contain at least one valid tid:author_id rule")
            return
        if raw_thread_watches and not parsed_watches:
            errors.append("Thread author watches must contain at least one valid tid:author_id rule")
        for watch in parsed_watches:
            if not watch.tid.isdigit() or not watch.author_id.isdigit():
                errors.append(f"Thread author watches contains non-numeric tid:author_id pair: {watch.tid}:{watch.author_id}")
        for rule in parsed_rules:
            if not rule.tid.isdigit() or not rule.author_id.isdigit():
                errors.append(f"Listen rules contains non-numeric tid:author_id pair: {rule.tid}:{rule.author_id}")

    if watch_mode in {"author", "both"}:
        validate_author_selectors()
    if watch_mode in {"thread_author", "both"}:
        validate_thread_author_selectors()

    return errors


def command_init(paths: CliPaths) -> int:
    if paths.config_path.exists():
        print(f"Config already exists: {paths.config_path}", file=sys.stderr)
        return 2
    try:
        config = prompt_basic_config(dict(nga_wolf_config.DEFAULT_CONFIG))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    nga_wolf_config.save_config(config, paths.config_path)
    print(paths.config_path)
    return 0


def command_config(paths: CliPaths) -> int:
    if not paths.config_path.exists():
        print(f"Config not found: {paths.config_path}", file=sys.stderr)
        return 2
    config = load_existing_config_for_edit(paths.config_path)
    if config is None:
        print(f"Config is not valid JSON: {paths.config_path}", file=sys.stderr)
        return 2
    try:
        updated = prompt_basic_config(config)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    nga_wolf_config.save_config(updated, paths.config_path)
    print(paths.config_path)
    return 0


def command_check(paths: CliPaths) -> int:
    config = load_service_config(paths)
    errors = nga_wolf_config.validate_config(config, require_cookie=True)
    if errors:
        print_validation_errors(errors)
        return 2
    return 0


def command_mark_seen(paths: CliPaths) -> int:
    config = load_service_config(paths)
    errors = validate_mark_seen_config(config)
    if errors:
        print_validation_errors(errors)
        return 2
    args = build_service_args(paths, config, mark_seen=True)
    nga_feishu_watch.run_once(args)
    return 0


def command_test_send(paths: CliPaths) -> int:
    config = load_service_config(paths)
    errors = nga_wolf_config.validate_config(config, require_cookie=False)
    if errors:
        print_validation_errors(errors)
        return 2
    args = build_service_args(paths, config, mark_seen=False)
    nga_feishu_watch.send_test_message(args)
    return 0


def command_run(paths: CliPaths, once: bool = False) -> int:
    config = load_service_config(paths)
    errors = nga_wolf_config.validate_config(config, require_cookie=True)
    if errors:
        print_validation_errors(errors)
        return 2
    if once:
        try:
            args = build_service_args(paths, config, mark_seen=False)
            setattr(args, "once", True)
            nga_feishu_watch.run_once(args)
            return 0
        except KeyboardInterrupt:
            print("Watcher stopped.", file=sys.stderr)
            return 130
    try:
        nga_wolf_config.run_watcher_from_config(paths.config_path, data_dir=paths.data_dir)
    except KeyboardInterrupt:
        print("Watcher stopped.", file=sys.stderr)
        return 130
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
    if args.command == "check":
        return command_check(paths)
    if args.command == "mark-seen":
        return command_mark_seen(paths)
    if args.command == "test-send":
        return command_test_send(paths)
    if args.command == "run":
        return command_run(paths, once=getattr(args, "once", False))
    print(f"{args.command} is not implemented yet.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
