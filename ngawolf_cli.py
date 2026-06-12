from __future__ import annotations

import argparse
import json
import getpass
import re
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

import nga_feishu_watch
import nga_wolf_config
import wechat_bot

try:
    import questionary
except Exception:  # pragma: no cover - optional terminal enhancement
    questionary = None


@dataclass(frozen=True)
class CliPaths:
    config_path: Path
    data_dir: Path
    log_file: Path


def is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _questionary_client():
    if questionary is None or not is_interactive_terminal():
        return None
    return questionary


def _questionary_choice(client, title: str, value: str, *, checked: bool | None = None):
    choice_cls = getattr(client, "Choice", None)
    if choice_cls is not None:
        kwargs = {"title": title, "value": value}
        if checked is not None:
            kwargs["checked"] = checked
        return choice_cls(**kwargs)
    item = {"name": title, "value": value}
    if checked is not None:
        item["checked"] = checked
    return item


def _questionary_style(client):
    style_cls = getattr(client, "Style", None)
    if style_cls is None:
        return None
    try:
        return style_cls(
            [
                ("qmark", "fg:#888888"),
                ("question", "bold"),
                ("answer", "fg:#00afff bg:#000000 bold noreverse"),
                ("pointer", "fg:#00afff bg:#000000 bold noreverse"),
                ("highlighted", "fg:#00afff bg:#000000 bold noreverse"),
                ("selected", "fg:#00afff bg:#000000 noreverse"),
                ("separator", "fg:#888888"),
                ("instruction", "fg:#888888"),
                ("text", "noreverse"),
                ("disabled", "fg:#888888 italic"),
            ]
        )
    except Exception:
        return None


def _questionary_prompt(factory, *args, style=None, **kwargs):
    if style is not None:
        kwargs["style"] = style
    try:
        return factory(*args, **kwargs)
    except TypeError:
        kwargs.pop("instruction", None)
        kwargs.pop("style", None)
        return factory(*args, **kwargs)


def prompt_text(label: str, current: object = "", *, secret: bool = False) -> str:
    current_text = "" if current is None else str(current)
    client = _questionary_client()
    if client is not None:
        try:
            style = _questionary_style(client)
            prompt = (
                _questionary_prompt(client.password, label, instruction="（输入后回车确认）", style=style)
                if secret
                else _questionary_prompt(client.text, label, default=current_text, instruction="（输入后回车确认）", style=style)
            )
            value = prompt.ask()
        except Exception:
            value = None
        if value is None:
            return current_text
        value_text = str(value).strip()
        return current_text if value_text == "" else value_text

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
    default = current_text if current_text in values else choices[0][0]
    client = _questionary_client()
    if client is not None:
        answer = _questionary_prompt(
            client.select,
            label,
            choices=[_questionary_choice(client, title, value) for value, title in choices],
            default=default,
            instruction="（使用方向键选择，回车确认）",
            style=_questionary_style(client),
        ).ask()
        if answer is None:
            return default
        normalized_answer = str(answer).strip().lower()
        return normalized_answer if normalized_answer in values else default

    for index, (value, title) in enumerate(choices, start=1):
        marker = "*" if value == current_text else " "
        print(f"  {marker} {index}. {title} ({value})")
    while True:
        raw = input(f"{label} [{current_text}]: ").strip()
        if raw == "":
            return default
        if raw.isdigit():
            index = int(raw)
            if 1 <= index <= len(choices):
                return choices[index - 1][0]
        normalized = raw.lower()
        if normalized in values:
            return normalized
        print(f"请选择 1-{len(choices)} 或输入其中一个值：{', '.join(value for value, _ in choices)}", file=sys.stderr)


def prompt_multi_select(
    label: str,
    options: list[dict[str, str]],
    selected_values: list[str] | None = None,
) -> list[dict[str, str]]:
    selected = set(selected_values or [])
    value_to_option = {str(option.get("value") or ""): option for option in options}
    selected = {value for value in selected if value in value_to_option}
    client = _questionary_client()
    if client is not None:
        answers = _questionary_prompt(
            client.checkbox,
            label,
            choices=[
                _questionary_choice(
                    client,
                    str(option.get("label") or option.get("value") or ""),
                    str(option.get("value") or ""),
                    checked=str(option.get("value") or "") in selected,
                )
                for option in options
            ],
            instruction="（使用方向键移动，空格选择/取消，回车确认）",
            style=_questionary_style(client),
        ).ask()
        if answers is None:
            answers = selected
        answer_values = {str(value) for value in answers}
        return [option for option in options if str(option.get("value") or "") in answer_values]

    while True:
        print(label)
        for index, option in enumerate(options, start=1):
            value = str(option.get("value") or "")
            checked = "x" if value in selected else " "
            title = str(option.get("label") or value)
            print(f"  [{checked}] {index}. {title} ({value})")

        raw = input("输入编号切换选择，a 全选，n 清空，回车确认：").strip().lower()
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
                print(f"已忽略无效选择：{token}", file=sys.stderr)
                continue
            index = int(token)
            if not 1 <= index <= len(options):
                print(f"已忽略超出范围的选择：{token}", file=sys.stderr)
                continue
            value = str(options[index - 1].get("value") or "")
            if value in selected:
                selected.remove(value)
            else:
                selected.add(value)
            changed = True
        if not changed:
            print("没有有效选择发生变化。", file=sys.stderr)


def _prompt_fields(config: dict[str, object], fields: list[tuple[str, str, bool]]) -> None:
    for key, label, secret in fields:
        config[key] = prompt_text(label, config.get(key, ""), secret=secret)


def _normalize_bot_channel(value: object) -> str:
    channel = str(value or "feishu").strip().lower()
    if channel not in {"feishu", "wechat", "dingtalk", "email", "wxpusher"}:
        raise ValueError("bot_channel must be one of: feishu, wechat, dingtalk, email, wxpusher")
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
    config["feishu_app_id"] = prompt_text("飞书 App ID", config.get("feishu_app_id", ""))
    config["feishu_app_secret"] = prompt_text("飞书 App Secret", config.get("feishu_app_secret", ""), secret=True)

    app_id = str(config.get("feishu_app_id") or "").strip()
    app_secret = str(config.get("feishu_app_secret") or "").strip()
    existing_profiles = _json_list(config.get("feishu_bot_profiles"))
    existing_profile = existing_profiles[0] if existing_profiles else {}
    profile = {
        "id": "default",
        "label": str(existing_profile.get("label") or "默认飞书机器人"),
        "app_id": app_id,
        "app_secret": app_secret,
        "id_type": "chat_id",
        "chats": existing_profile.get("chats") if isinstance(existing_profile.get("chats"), list) else [],
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
            source_choices = [(f"chat:{option['value']}", f"群组：{option['label']}") for option in options]
            if len(options) > 1:
                source_choices.append(("multi", "选择多个群组"))
            source_choices.append(("manual", "手动填写 receive ID"))
            target_source = prompt_choice(
                "飞书发送目标",
                source_choices,
                f"chat:{options[0]['value']}",
            )
            if target_source.startswith("chat:"):
                chat_id = target_source.split(":", 1)[1]
                selected_chats = [option for option in options if option["value"] == chat_id]
            elif target_source == "multi":
                selected_chats = prompt_multi_select("选择飞书群组", options, selected_values=[options[0]["value"]])
            if selected_chats:
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
        config["feishu_receive_id"] = prompt_text("飞书 receive ID", config.get("feishu_receive_id", ""))

    config["feishu_id_type"] = "chat_id"
    config["feishu_bot_profiles"] = _json_dumps([profile])


def _current_wxpusher_delivery_mode(config: dict[str, object]) -> str:
    profiles = _json_list(config.get("wxpusher_profiles"))
    profile = profiles[0] if profiles else {}
    if str(config.get("wxpusher_spts") or profile.get("spts") or "").strip():
        return "spt"
    if str(config.get("wxpusher_topic_ids") or profile.get("topic_ids") or "").strip():
        return "topic_id"
    if str(config.get("wxpusher_uids") or profile.get("uids") or "").strip():
        return "uid"
    return "spt"


def _configure_wxpusher_channel(config: dict[str, object]) -> None:
    delivery_mode = prompt_choice(
        "WxPusher 推送方式",
        [
            ("spt", "SPT 极简推送"),
            ("uid", "App Token + UID"),
            ("topic_id", "App Token + Topic ID"),
        ],
        _current_wxpusher_delivery_mode(config),
    )
    config["wxpusher_content_type"] = prompt_choice(
        "WxPusher 内容格式",
        [
            ("markdown", "Markdown"),
            ("text", "纯文本"),
            ("html", "HTML"),
        ],
        config.get("wxpusher_content_type", "markdown"),
    )
    if delivery_mode == "spt":
        config["wxpusher_spts"] = prompt_text("WxPusher SPT", config.get("wxpusher_spts", ""), secret=True)
        config["wxpusher_app_token"] = ""
        config["wxpusher_uids"] = ""
        config["wxpusher_topic_ids"] = ""
        receive_id = ""
        id_type = "spt"
    elif delivery_mode == "uid":
        config["wxpusher_spts"] = ""
        config["wxpusher_app_token"] = prompt_text("WxPusher App Token", config.get("wxpusher_app_token", ""), secret=True)
        config["wxpusher_uids"] = prompt_text("WxPusher UID", config.get("wxpusher_uids", ""))
        config["wxpusher_topic_ids"] = ""
        receive_id = str(config.get("wxpusher_uids") or "").strip()
        id_type = "uid"
    else:
        config["wxpusher_spts"] = ""
        config["wxpusher_app_token"] = prompt_text("WxPusher App Token", config.get("wxpusher_app_token", ""), secret=True)
        config["wxpusher_uids"] = ""
        config["wxpusher_topic_ids"] = prompt_text("WxPusher Topic ID", config.get("wxpusher_topic_ids", ""))
        receive_id = str(config.get("wxpusher_topic_ids") or "").strip()
        id_type = "topic_id"

    profile = {
        "id": "default",
        "label": "Default WxPusher",
        "spts": str(config.get("wxpusher_spts") or "").strip(),
        "app_token": str(config.get("wxpusher_app_token") or "").strip(),
        "uids": str(config.get("wxpusher_uids") or "").strip(),
        "topic_ids": str(config.get("wxpusher_topic_ids") or "").strip(),
        "content_type": str(config.get("wxpusher_content_type") or "markdown").strip() or "markdown",
    }
    config["wxpusher_profiles"] = _json_dumps([profile])
    config["push_targets"] = _json_dumps(
        [
            {
                "id": "wxpusher_1",
                "label": "Default WxPusher",
                "channel": "wxpusher",
                "profile_id": "default",
                "receive_id": receive_id,
                "id_type": id_type,
                "default_author_id": str(config.get("default_author_id") or "150058").strip(),
                "default_tid": str(config.get("default_tid") or "45974302").strip(),
            }
        ]
    )


def _merge_targets(existing: list[dict[str, object]], added: list[dict[str, object]]) -> list[dict[str, object]]:
    merged = [dict(target) for target in existing]
    indexes = {str(target.get("id") or ""): index for index, target in enumerate(merged) if str(target.get("id") or "")}
    for target in added:
        target_id = str(target.get("id") or "")
        if target_id and target_id in indexes:
            merged[indexes[target_id]] = dict(target)
        else:
            merged.append(dict(target))
    return merged


def _next_target_id(config: dict[str, object], prefix: str) -> str:
    existing = {str(target.get("id") or "") for target in _json_list(config.get("push_targets"))}
    index = 1
    while f"{prefix}_{index}" in existing:
        index += 1
    return f"{prefix}_{index}"


def _int_config(config: dict[str, object], key: str, default: int) -> int:
    try:
        return int(str(config.get(key) or default).strip())
    except (TypeError, ValueError):
        return default


def _configure_wechat_channel(config: dict[str, object]) -> None:
    base_url = str(config.get("wechat_bot_base_url") or wechat_bot.DEFAULT_WECHAT_BASE_URL).strip()
    route_tag = str(config.get("wechat_bot_route_tag") or "").strip()
    timeout = max(_int_config(config, "timeout", 20), 40)
    qr = wechat_bot.begin_qr_login(base_url, route_tag=route_tag, timeout=timeout)
    qr_url = str(qr["qr_url"])
    print(f"微信扫码链接：{qr_url}")
    try:
        webbrowser.open(qr_url)
    except Exception:
        pass
    print("请用微信扫码并确认，确认后 CLI 会自动继续。")
    result = wechat_bot.poll_qr_login(
        str(qr["qr_key"]),
        base_url,
        route_tag=route_tag,
        timeout_seconds=wechat_bot.DEFAULT_WECHAT_QR_TIMEOUT_SECONDS,
    )

    token = str(result.get("token") or "").strip()
    target_user_id = str(result.get("user_id") or "").strip()
    account_id = str(result.get("account_id") or config.get("wechat_bot_account_id") or "default").strip() or "default"
    bound_base_url = str(result.get("base_url") or base_url).strip() or base_url
    profiles = nga_wolf_config.load_wechat_profiles(config)
    config["wechat_bot_token"] = token
    config["wechat_bot_base_url"] = bound_base_url
    if target_user_id:
        config["wechat_bot_target_user_id"] = target_user_id
        config["wechat_bot_allowed_user_ids"] = target_user_id
    if account_id:
        config["wechat_bot_account_id"] = account_id

    profile = {
        "label": target_user_id or "WeChat",
        "token": token,
        "base_url": bound_base_url,
        "cdn_base_url": str(config.get("wechat_bot_cdn_base_url") or wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL).strip(),
        "target_user_id": target_user_id,
        "allowed_user_ids": target_user_id,
        "poll_timeout_ms": str(config.get("wechat_bot_poll_timeout_ms") or "35000").strip(),
        "route_tag": route_tag,
        "account_id": account_id,
    }
    profile["id"] = nga_wolf_config.ensure_profile_id("wechat", profile)
    replaced = False
    for index, item in enumerate(profiles):
        if str(item.get("id") or "") == str(profile["id"]):
            profiles[index] = profile
            replaced = True
            break
    if not replaced:
        profiles.append(profile)
    config["wechat_bot_profiles"] = _json_dumps(profiles)

    if target_user_id:
        target = {
            "id": _next_target_id(config, "wechat"),
            "label": target_user_id,
            "channel": "wechat",
            "profile_id": str(profile["id"]),
            "receive_id": target_user_id,
            "id_type": "user_id",
            "default_author_id": str(config.get("default_author_id") or "150058").strip(),
            "default_tid": str(config.get("default_tid") or "45974302").strip(),
        }
        before = _json_list(config.get("push_targets"))
        config["push_targets"] = _json_dumps(_merge_targets(before, [target]))
    print("微信绑定已保存。首次主动推送前，请先用目标微信给机器人发一条消息。")


def _run_channel_config(config: dict[str, object], channel: str) -> None:
    before = _json_list(config.get("push_targets"))
    if channel == "feishu":
        _configure_feishu_channel(config)
        after = _json_list(config.get("push_targets"))
        config["push_targets"] = _json_dumps(_merge_targets(before, after))
    elif channel == "wxpusher":
        _configure_wxpusher_channel(config)
        after = _json_list(config.get("push_targets"))
        config["push_targets"] = _json_dumps(_merge_targets(before, after))
    elif channel == "email":
        _prompt_fields(
            config,
            [
                ("email_to", "收件邮箱", False),
                ("email_username", "邮箱账号", False),
                ("email_password", "邮箱密码或授权码", True),
            ],
        )
        receive_id = str(config.get("email_to") or "").strip()
        if receive_id:
            target = {
                "id": _next_target_id(config, "email"),
                "label": receive_id,
                "channel": "email",
                "profile_id": "default",
                "receive_id": receive_id,
                "id_type": "email",
                "default_author_id": str(config.get("default_author_id") or "150058").strip(),
                "default_tid": str(config.get("default_tid") or "45974302").strip(),
            }
            config["push_targets"] = _json_dumps(_merge_targets(before, [target]))
    elif channel == "wechat":
        _configure_wechat_channel(config)
    elif channel == "dingtalk":
        _prompt_fields(
            config,
            [
                ("dingtalk_client_id", "DingTalk Client ID", False),
                ("dingtalk_client_secret", "DingTalk Client Secret", True),
                ("dingtalk_target_user_ids", "DingTalk 目标用户 ID", False),
            ],
        )
        receive_id = str(config.get("dingtalk_target_user_ids") or "").strip()
        if receive_id:
            target = {
                "id": _next_target_id(config, "dingtalk"),
                "label": "DingTalk",
                "channel": "dingtalk",
                "profile_id": "default",
                "receive_id": receive_id,
                "id_type": "user_id",
                "default_author_id": str(config.get("default_author_id") or "150058").strip(),
                "default_tid": str(config.get("default_tid") or "45974302").strip(),
            }
            config["push_targets"] = _json_dumps(_merge_targets(before, [target]))

    targets = _json_list(config.get("push_targets"))
    if targets:
        config["bot_channel"] = str(targets[0].get("channel") or channel)


def _delete_push_target(config: dict[str, object]) -> None:
    targets = _json_list(config.get("push_targets"))
    choices = [(str(target.get("id") or ""), _target_title(target)) for target in targets if str(target.get("id") or "")]
    if not choices:
        print("暂无可删除的推送通道。", file=sys.stderr)
        return
    target_id = prompt_choice("选择要删除的推送通道", choices, choices[0][0])
    if not target_id:
        return
    removed_target = next((target for target in targets if str(target.get("id") or "") == target_id), {})
    remaining_targets = [target for target in targets if str(target.get("id") or "") != target_id]
    config["push_targets"] = _json_dumps(remaining_targets)
    _clear_legacy_target_fields(config, removed_target)

    cleaned_rules: list[dict[str, object]] = []
    for rule in _json_list(config.get("listen_rules")):
        remaining_target_ids = [item for item in _target_ids_for_rule(rule) if item != target_id]
        if not remaining_target_ids:
            continue
        updated_rule = dict(rule)
        updated_rule["target_ids"] = remaining_target_ids
        cleaned_rules.append(updated_rule)
    _save_listen_rules(config, cleaned_rules)
    if remaining_targets:
        config["bot_channel"] = str(remaining_targets[0].get("channel") or config.get("bot_channel") or "feishu")
    else:
        config["bot_channel"] = "feishu"


def _test_push_target(config: dict[str, object]) -> None:
    targets = _json_list(config.get("push_targets"))
    choices = [(str(target.get("id") or ""), _target_title(target)) for target in targets if str(target.get("id") or "")]
    if not choices:
        print("暂无可测试的推送通道。", file=sys.stderr)
        return
    errors = nga_wolf_config.validate_config(config, require_cookie=False)
    if errors:
        print_validation_errors(errors)
        return
    target_id = prompt_choice("选择要测试的推送通道", choices, choices[0][0])
    args = nga_wolf_config.build_args(config)
    target = nga_feishu_watch.find_push_target(args, target_id)
    if target is None:
        print("请选择有效推送通道。", file=sys.stderr)
        return
    title = target.label or target.id or target.receive_id or target.channel
    print(f"正在测试推送通道：{title}")
    _send_test_message_safely(nga_feishu_watch.args_for_push_target(args, target))


def _test_send_error_message(exc: Exception) -> str:
    message = str(exc).strip()
    if "尚未建立 context_token" in message:
        return "微信主动推送还没有建立 context_token。请先用目标微信给机器人发一条消息，再回来测试。"
    return f"测试发送失败：{message or exc.__class__.__name__}"


def _send_test_message_safely(args: argparse.Namespace) -> bool:
    try:
        nga_feishu_watch.send_test_message(args)
    except Exception as exc:
        print(_test_send_error_message(exc), file=sys.stderr)
        return False
    return True


def _clear_legacy_target_fields(config: dict[str, object], target: dict[str, object]) -> None:
    channel = str(target.get("channel") or "feishu").strip().lower()
    receive_id = str(target.get("receive_id") or "").strip()
    id_type = str(target.get("id_type") or "").strip().lower()
    if channel == "feishu" and str(config.get("feishu_receive_id") or "").strip() == receive_id:
        config["feishu_receive_id"] = ""
    elif channel == "wechat":
        if not receive_id or str(config.get("wechat_bot_target_user_id") or "").strip() == receive_id:
            config["wechat_bot_target_user_id"] = ""
        if not receive_id or str(config.get("wechat_bot_allowed_user_ids") or "").strip() == receive_id:
            config["wechat_bot_allowed_user_ids"] = ""
    elif channel == "dingtalk" and str(config.get("dingtalk_target_user_ids") or "").strip() == receive_id:
        config["dingtalk_target_user_ids"] = ""
    elif channel == "email" and str(config.get("email_to") or "").strip() == receive_id:
        config["email_to"] = ""
    elif channel == "wxpusher":
        if id_type == "spt":
            config["wxpusher_spts"] = ""
            profiles = _json_list(config.get("wxpusher_profiles"))
            for profile in profiles:
                if not target.get("profile_id") or str(profile.get("id") or "") == str(target.get("profile_id") or ""):
                    profile["spts"] = ""
            config["wxpusher_profiles"] = _json_dumps(profiles)
        elif id_type == "topic_id" and str(config.get("wxpusher_topic_ids") or "").strip() == receive_id:
            config["wxpusher_topic_ids"] = ""
        elif id_type == "uid" and str(config.get("wxpusher_uids") or "").strip() == receive_id:
            config["wxpusher_uids"] = ""


def _manage_push_targets(config: dict[str, object]) -> None:
    if not _json_list(config.get("push_targets")):
        feishu_profiles = nga_wolf_config.load_feishu_profiles(config)
        wechat_profiles = nga_wolf_config.load_wechat_profiles(config)
        dingtalk_profiles = nga_wolf_config.load_dingtalk_profiles(config)
        email_profiles = nga_wolf_config.load_email_profiles(config)
        wxpusher_profiles = nga_wolf_config.load_wxpusher_profiles(config)
        legacy_targets = nga_wolf_config.load_push_targets(
            config,
            feishu_profiles,
            wechat_profiles,
            dingtalk_profiles,
            email_profiles,
            wxpusher_profiles,
        )
        if legacy_targets:
            config["push_targets"] = _json_dumps(legacy_targets)
            config["bot_channel"] = str(legacy_targets[0].get("channel") or config.get("bot_channel") or "feishu")

    while True:
        targets = _json_list(config.get("push_targets"))
        action = prompt_choice(
            "推送通道管理",
            [
                ("view", f"查看已配置推送通道（已配置 {len(targets)} 个）"),
                ("add_feishu", "添加 Feishu"),
                ("add_wxpusher", "添加 WxPusher"),
                ("add_email", "添加 Email"),
                ("add_wechat", "微信扫码绑定"),
                ("add_dingtalk", "添加 DingTalk"),
                ("test", f"测试推送通道（已配置 {len(targets)} 个）"),
                ("delete", f"删除推送通道（已配置 {len(targets)} 个）"),
                ("done", "完成推送通道管理"),
            ],
            "done" if targets else "add_feishu",
        )
        if action == "done":
            break
        if action == "view":
            _print_existing("已配置推送通道", [_target_title(target) for target in targets])
            continue
        if action == "delete":
            _delete_push_target(config)
            continue
        if action == "test":
            _test_push_target(config)
            continue
        _run_channel_config(config, action.removeprefix("add_"))


def _split_config_entries(value: object) -> list[str]:
    if not value:
        return []
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _entry_with_label(value: str, label: str) -> str:
    value = value.strip()
    label = label.strip()
    return f"{value}={label}" if label else value


def _clear_default_entries(entries: list[str], key: str) -> None:
    default_entries = _split_config_entries(nga_wolf_config.DEFAULT_CONFIG.get(key, ""))
    if entries == default_entries:
        entries.clear()


def _entry_parts(entry: str) -> tuple[str, str]:
    main = entry.split("|", 1)[0].strip()
    if "=" in main:
        item_id, label = main.split("=", 1)
        return item_id.strip(), label.strip()
    if ":" in main and not main.count(":") == 1:
        item_id, label = main.split(":", 1)
        return item_id.strip(), label.strip()
    return main.strip(), ""


def _entry_title(entry: str) -> str:
    item_id, label = _entry_parts(entry)
    return f"{label} ({item_id})" if label else item_id


def _channel_title(channel: object) -> str:
    normalized = str(channel or "").strip().lower()
    return {
        "feishu": "Feishu",
        "wechat": "WeChat",
        "dingtalk": "DingTalk",
        "email": "Email",
        "wxpusher": "WxPusher",
    }.get(normalized, normalized or "未知通道")


def _id_type_title(id_type: object) -> str:
    normalized = str(id_type or "").strip().lower()
    return {
        "chat_id": "chat_id",
        "user_id": "user_id",
        "email": "Email",
        "spt": "SPT",
        "uid": "UID",
        "topic_id": "Topic ID",
    }.get(normalized, str(id_type or "").strip())


def _target_title(target: dict[str, object]) -> str:
    label = str(target.get("label") or target.get("id") or "").strip()
    channel = _channel_title(target.get("channel"))
    receive_id = str(target.get("receive_id") or "").strip()
    id_type = _id_type_title(target.get("id_type"))
    suffix = channel
    if receive_id:
        suffix = f"{suffix} / {receive_id}"
    elif id_type:
        suffix = f"{suffix} / {id_type}"
    return f"{label} ({suffix})" if label else suffix


def _entry_lookup(entries: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for entry in entries:
        item_id, _label = _entry_parts(entry)
        if item_id:
            result[item_id] = _entry_title(entry)
    return result


def _target_lookup(config: dict[str, object]) -> dict[str, str]:
    return {
        str(target.get("id") or ""): _target_title(target)
        for target in _json_list(config.get("push_targets"))
        if str(target.get("id") or "")
    }


def _target_ids_for_rule(rule: dict[str, object]) -> list[str]:
    raw_target_ids = rule.get("target_ids")
    if isinstance(raw_target_ids, list):
        return [str(target_id).strip() for target_id in raw_target_ids if str(target_id).strip()]
    if isinstance(raw_target_ids, str):
        return [part.strip() for part in re.split(r"[,，;；、\s]+", raw_target_ids) if part.strip()]
    return []


def _rule_title(
    rule: dict[str, object],
    author_entries: list[str],
    thread_entries: list[str],
    targets: dict[str, str],
) -> str:
    mode = str(rule.get("mode") or "").strip()
    author_id = str(rule.get("author_id") or "").strip()
    tid = str(rule.get("tid") or "").strip()
    label = str(rule.get("label") or "").strip()
    author_lookup = _entry_lookup(author_entries)
    thread_lookup = _entry_lookup(thread_entries)
    target_names = [targets.get(target_id, f"未知通道({target_id})") for target_id in _target_ids_for_rule(rule)]
    target_text = "、".join(target_names) if target_names else "未选择推送通道"
    if mode == "author":
        author_title = author_lookup.get(author_id) or (f"{label} ({author_id})" if label and author_id else author_id)
        return f"用户主页监听：{author_title} -> {target_text}"
    if mode == "thread_author":
        thread_title = thread_lookup.get(tid) or tid
        author_title = author_lookup.get(author_id) or author_id
        return f"帖子内监听：{thread_title} / {author_title} -> {target_text}"
    return f"{label or rule.get('id') or '未知规则'} -> {target_text}"


def _print_existing(title: str, rows: list[str]) -> None:
    print(title)
    if not rows:
        print("  暂无")
        return
    for index, row in enumerate(rows, start=1):
        print(f"  {index}. {row}")


def _selected_option_value(options: list[dict[str, str]]) -> list[str]:
    return [str(option.get("value") or "") for option in options if str(option.get("value") or "")]


def _select_existing_entry(label: str, entries: list[str]) -> str:
    if not entries:
        return ""
    choices = [(entry, _entry_title(entry)) for entry in entries]
    return prompt_choice(label, choices, entries[0])


def _set_watch_mode_from_rules(config: dict[str, object], rules: list[dict[str, object]]) -> None:
    has_author = any(str(rule.get("mode") or "") == "author" for rule in rules)
    has_thread_author = any(str(rule.get("mode") or "") == "thread_author" for rule in rules)
    if has_author and has_thread_author:
        config["watch_mode"] = "both"
    elif has_thread_author:
        config["watch_mode"] = "thread_author"
    else:
        config["watch_mode"] = "author"


def _save_listen_rules(config: dict[str, object], rules: list[dict[str, object]]) -> None:
    config["listen_rules"] = _json_dumps(rules)
    if rules:
        _set_watch_mode_from_rules(config, rules)


def _delete_entry_by_id(entries: list[str], selected_entry: str) -> tuple[list[str], str]:
    selected_id, _label = _entry_parts(selected_entry)
    if not selected_id:
        return entries, ""
    return [entry for entry in entries if _entry_parts(entry)[0] != selected_id], selected_id


def _delete_author_rules(config: dict[str, object], author_id: str) -> None:
    if not author_id:
        return
    rules = [
        rule
        for rule in _json_list(config.get("listen_rules"))
        if str(rule.get("author_id") or "").strip() != author_id
    ]
    _save_listen_rules(config, rules)


def _delete_thread_rules(config: dict[str, object], tid: str) -> None:
    if not tid:
        return
    rules = [
        rule
        for rule in _json_list(config.get("listen_rules"))
        if not (str(rule.get("mode") or "").strip() == "thread_author" and str(rule.get("tid") or "").strip() == tid)
    ]
    _save_listen_rules(config, rules)


def _configure_watch_resources(config: dict[str, object]) -> None:
    author_entries = _split_config_entries(config.get("watch_author_ids"))
    thread_entries = _split_config_entries(config.get("preset_thread_ids"))

    while True:
        action = prompt_choice(
            "用户和帖子管理",
            [
                ("view_authors", f"查看已配置用户 ID（已配置 {len(author_entries)} 个）"),
                ("add_author", "添加用户 ID"),
                ("delete_author", f"删除用户 ID（已配置 {len(author_entries)} 个）"),
                ("view_threads", f"查看已配置帖子 ID（已配置 {len(thread_entries)} 个）"),
                ("add_thread", "添加帖子 ID"),
                ("delete_thread", f"删除帖子 ID（已配置 {len(thread_entries)} 个）"),
                ("done", "完成用户和帖子管理"),
            ],
            "done" if (author_entries or thread_entries) else "add_author",
        )
        if action == "done":
            break
        if action == "view_authors":
            _print_existing("已配置用户 ID", [_entry_title(entry) for entry in author_entries])
        elif action == "add_author":
            _clear_default_entries(author_entries, "watch_author_ids")
            author_id = prompt_text("监听用户 ID", "")
            if author_id:
                author_entries.append(_entry_with_label(author_id, prompt_text("备注名称（可空）", "")))
        elif action == "delete_author":
            if not author_entries:
                print("暂无可删除的用户 ID。", file=sys.stderr)
                continue
            selected = _select_existing_entry("选择要删除的用户 ID", author_entries)
            author_entries, author_id = _delete_entry_by_id(author_entries, selected)
            _delete_author_rules(config, author_id)
        elif action == "view_threads":
            _print_existing("已配置帖子 ID", [_entry_title(entry) for entry in thread_entries])
        elif action == "add_thread":
            _clear_default_entries(thread_entries, "preset_thread_ids")
            tid = prompt_text("固定帖子 ID", "")
            if tid:
                thread_entries.append(_entry_with_label(tid, prompt_text("备注名称（可空）", "")))
        elif action == "delete_thread":
            if not thread_entries:
                print("暂无可删除的帖子 ID。", file=sys.stderr)
                continue
            selected = _select_existing_entry("选择要删除的帖子 ID", thread_entries)
            thread_entries, tid = _delete_entry_by_id(thread_entries, selected)
            _delete_thread_rules(config, tid)

    config["watch_author_ids"] = "\n".join(author_entries)
    config["preset_thread_ids"] = "\n".join(thread_entries)


def _configure_listen_rules(config: dict[str, object]) -> None:
    rules = _json_list(config.get("listen_rules"))
    author_entries = _split_config_entries(config.get("watch_author_ids"))
    thread_entries = _split_config_entries(config.get("preset_thread_ids"))
    targets = _json_list(config.get("push_targets"))

    while True:
        action = prompt_choice(
            "监听规则管理",
            [
                ("view", f"查看已有监听规则（已配置 {len(rules)} 条）"),
                ("add_author", "添加用户主页监听"),
                ("add_thread_author", "添加帖子内指定用户监听"),
                ("delete", f"删除监听规则（已配置 {len(rules)} 条）"),
                ("done", "完成监听规则管理"),
            ],
            "done" if (rules or author_entries or thread_entries) else "add_author",
        )
        if action == "done":
            break
        if action == "view":
            target_titles = _target_lookup(config)
            rows = [_rule_title(rule, author_entries, thread_entries, target_titles) for rule in rules]
            _print_existing("已有监听规则", rows)
            continue
        if action == "delete":
            if not rules:
                print("暂无可删除的监听规则。", file=sys.stderr)
                continue
            target_titles = _target_lookup(config)
            choices = [
                (str(rule.get("id") or index), _rule_title(rule, author_entries, thread_entries, target_titles))
                for index, rule in enumerate(rules, start=1)
            ]
            selected_rule_id = prompt_choice("选择要删除的监听规则", choices, choices[0][0])
            rules = [
                rule
                for index, rule in enumerate(rules, start=1)
                if str(rule.get("id") or index) != selected_rule_id
            ]
            continue

        if not targets:
            print("请先添加至少一个推送通道。", file=sys.stderr)
            continue
        target_options = [{"value": str(target.get("id") or ""), "label": _target_title(target)} for target in targets if str(target.get("id") or "")]
        selected_targets = _selected_option_value(prompt_multi_select("选择监听通道", target_options, selected_values=[option["value"] for option in target_options]))
        if not selected_targets:
            print("未选择监听通道，已跳过。", file=sys.stderr)
            continue

        if action == "add_author":
            if not author_entries:
                print("请先在用户和帖子管理里添加用户 ID。", file=sys.stderr)
                continue
            author_entry = _select_existing_entry("选择用户 ID", author_entries)
            author_id, label = _entry_parts(author_entry)
            if not author_id:
                continue
            rules.append(
                {
                    "id": f"author:{author_id}",
                    "label": label,
                    "mode": "author",
                    "author_id": author_id,
                    "tid": "",
                    "target_ids": selected_targets,
                }
            )
        elif action == "add_thread_author":
            if not author_entries or not thread_entries:
                print("请先添加用户 ID 和帖子 ID。", file=sys.stderr)
                continue
            thread_entry = _select_existing_entry("选择帖子 ID", thread_entries)
            author_entry = _select_existing_entry("选择用户 ID", author_entries)
            tid, thread_label = _entry_parts(thread_entry)
            author_id, author_label = _entry_parts(author_entry)
            if not tid or not author_id:
                continue
            label = f"{thread_label or tid} / {author_label or author_id}"
            rules.append(
                {
                    "id": f"thread_author:{tid}:{author_id}",
                    "label": label,
                    "mode": "thread_author",
                    "author_id": author_id,
                    "tid": tid,
                    "target_ids": selected_targets,
                }
            )

    _save_listen_rules(config, rules)


def _sync_listen_rules(config: dict[str, object]) -> None:
    if _json_list(config.get("listen_rules")):
        return
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
    updated["nga_cookie"] = prompt_text("NGA cookie", updated.get("nga_cookie", ""), secret=True)
    _manage_push_targets(updated)
    _configure_watch_resources(updated)
    _configure_listen_rules(updated)
    updated["interval"] = str(updated.get("interval") or "30").strip() or "30"
    current_jitter = str(updated.get("jitter") or "").strip()
    default_jitter = str(nga_wolf_config.DEFAULT_CONFIG.get("jitter") or "20").strip()
    updated["jitter"] = current_jitter if current_jitter and current_jitter != default_jitter else "5"
    updated["state_path"] = str(updated.get("state_path") or ".nga_seen.json").strip() or ".nga_seen.json"
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
    if nga_feishu_watch.parse_push_targets(getattr(args, "push_targets", "")):
        targets = nga_feishu_watch.configured_push_targets(args)
        if not targets:
            print("未找到可测试的推送通道。", file=sys.stderr)
            return 2
        has_failure = False
        for target in targets:
            title = target.label or target.id or target.receive_id or target.channel
            print(f"正在测试推送通道：{title}")
            if not _send_test_message_safely(nga_feishu_watch.args_for_push_target(args, target)):
                has_failure = True
        return 2 if has_failure else 0
    return 0 if _send_test_message_safely(args) else 2


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
