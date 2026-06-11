from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from argparse import Namespace
from pathlib import Path
from typing import Any

import ai_analysis
import nga_feishu_watch


APP_DIR_NAME = "NGA Wolf Watcher"
CONFIG_FILE = "config.json"
RUNTIME_CONFIG_FILE = "runtime_config.json"
LOG_FILE = "watcher.log"
WATCHER_PID_FILE = "watcher.pid"

DEFAULT_CONFIG = {
    "bot_channel": "feishu",
    "nga_cookie": "",
    "feishu_app_id": "",
    "feishu_app_secret": "",
    "feishu_receive_id": "",
    "feishu_id_type": "chat_id",
    "feishu_bot_profiles": "[]",
    "wechat_bot_token": "",
    "wechat_bot_base_url": "https://ilinkai.weixin.qq.com",
    "wechat_bot_cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",
    "wechat_bot_target_user_id": "",
    "wechat_bot_allowed_user_ids": "",
    "wechat_bot_poll_timeout_ms": "35000",
    "wechat_bot_route_tag": "",
    "wechat_bot_account_id": "default",
    "wechat_bot_profiles": "[]",
    "dingtalk_client_id": "",
    "dingtalk_client_secret": "",
    "dingtalk_robot_code": "",
    "dingtalk_target_user_ids": "",
    "dingtalk_allowed_user_ids": "",
    "dingtalk_account_id": "default",
    "dingtalk_state_dir": "",
    "dingtalk_bot_profiles": "[]",
    "email_smtp_host": "smtp.gmail.com",
    "email_smtp_port": "587",
    "email_smtp_security": "starttls",
    "email_username": "",
    "email_password": "",
    "email_from": "",
    "email_from_name": "NGA Wolf Watcher",
    "email_reply_to": "",
    "email_to": "",
    "email_smtp_profiles": "[]",
    "default_author_id": "150058",
    "default_tid": "45974302",
    "watch_mode": "author",
    "watch_author_ids": "150058=鐙煎ぇ",
    "preset_thread_ids": "45974302=鑷珛鑷己锛岀瀛︽妧鏈墦澶撮樀",
    "thread_author_watches": "",
    "push_targets": "[]",
    "listen_rules": "[]",
    "thread_watch_tail_count": "20",
    "thread_watch_interval": "10",
    "interval": "30",
    "jitter": "20",
    "retries": "10",
    "retry_initial_delay": "1",
    "retry_delay": "1",
    "nga_request_min_interval": "1",
    "nga_cache_ttl": "15",
    "nga_target_min_delay": "2",
    "nga_target_max_delay": "6",
    "nga_unavailable_backoff_base": "60",
    "nga_unavailable_backoff_max": "600",
    "timeout": "20",
    "state_path": ".nga_seen.json",
    "auto_mark_seen_first_start": True,
    "mark_seen_initialized": False,
    "quiet_hours_enabled": False,
    "quiet_start_day": "5",
    "quiet_end_day": "0",
    "quiet_start_time": "00:00",
    "quiet_end_time": "00:00",
    "quiet_policy": "ignore",
    "ai_enabled": False,
    "ai_provider": "codex",
    "ai_work_dir": ".ai_agent_workspace",
    "ai_auto_analyze_new_post": False,
    "ai_auto_analysis_prompt": "鏍规嵁鏈€鏂扮殑 NGA 鍥炲鍘嗗彶銆佹垜鐩墠鐨勬寔浠撲俊鎭拰瑙傚療鍒楄〃锛屽苟瀹炴椂鏌ヨ鍏紑 A 鑲¤鎯呬俊鎭紝鍒嗘瀽鐩橀潰鍙樺寲銆佹満浼氫笌椋庨櫓锛岀粰鍑烘帴涓嬫潵闇€瑕侀噸鐐硅瀵熺殑鏂瑰悜鍜屾搷浣滃缓璁€?",
    "ai_prompt_file": "",
    "ai_timeout": "300",
    "ai_codex_command": "codex",
    "ai_claude_command": "claude",
    "ai_codewhale_command": "codewhale",
    "ai_custom_command": "",
    "ai_model": "",
    "ai_reasoning_effort": "",
    "ai_ignore_codex_user_config": False,
    "ai_schedule_enabled": False,
    "ai_schedule_interval_minutes": "5",
    "ai_schedule_prompt": "鏍规嵁鏈€鏂扮殑 NGA 鍥炲鍘嗗彶銆佹垜鐩墠鐨勬寔浠撲俊鎭拰瑙傚療鍒楄〃锛屽苟瀹炴椂鏌ヨ鍏紑 A 鑲¤鎯呬俊鎭紝鍒嗘瀽鐩橀潰鍙樺寲銆佹満浼氫笌椋庨櫓锛岀粰鍑烘帴涓嬫潵闇€瑕侀噸鐐硅瀵熺殑鏂瑰悜鍜屾搷浣滃缓璁€?",
    "ai_schedule_target_ids": "",
    "ai_schedule_window_mode": "a_share",
    "ai_schedule_windows": "weekday:09:30-11:30,13:00-15:00",
    "ai_allowed_user_ids": "",
    "ai_send_errors_to_feishu": False,
    "ai_max_feishu_chars": "3500",
    "ai_upload_long_result": False,
    "web_close_behavior": "ask",
}


def linux_config_path() -> Path:
    root = os.getenv("XDG_CONFIG_HOME")
    base = Path(root) if root else Path.home() / ".config"
    return base / "ngawolf" / CONFIG_FILE


def linux_data_dir() -> Path:
    root = os.getenv("XDG_STATE_HOME")
    base = Path(root) if root else Path.home() / ".local" / "state"
    return base / "ngawolf"


def load_config(path: Path, defaults: dict[str, object] | None = None) -> dict[str, object]:
    base = dict(DEFAULT_CONFIG if defaults is None else defaults)
    if not path.exists():
        return base
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            loaded = json.load(handle)
    except Exception:
        return base
    if isinstance(loaded, dict):
        base.update(loaded)
    return base


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    last_exc: PermissionError | None = None
    for attempt in range(1, 8):
        try:
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.08 * attempt)
    if last_exc is not None:
        raise last_exc


def save_config(config: dict[str, object], path: Path) -> None:
    write_json(path, config)


def json_list_config(config: dict[str, object], key: str) -> list[dict[str, Any]]:
    raw = config.get(key)
    if isinstance(raw, list):
        items = raw
    else:
        try:
            value = json.loads(str(raw or "[]"))
        except json.JSONDecodeError:
            value = []
        items = value if isinstance(value, list) else []
    return [dict(item) for item in items if isinstance(item, dict)]


def ensure_profile_id(prefix: str, profile: dict[str, Any]) -> str:
    current = str(profile.get("id") or "").strip()
    if current:
        return current
    if prefix == "feishu":
        return nga_feishu_watch.stable_profile_id("feishu", str(profile.get("app_id") or ""), str(profile.get("label") or ""))
    if prefix == "email":
        return nga_feishu_watch.stable_profile_id("email", str(profile.get("username") or ""), str(profile.get("from_email") or ""), str(profile.get("label") or ""))
    if prefix == "dingtalk":
        return nga_feishu_watch.stable_profile_id("dingtalk", str(profile.get("account_id") or "default"), str(profile.get("client_id") or ""), str(profile.get("label") or ""))
    return nga_feishu_watch.stable_profile_id("wechat", str(profile.get("account_id") or "default"), str(profile.get("token") or "")[:16])


def load_feishu_profiles(config: dict[str, object]) -> list[dict[str, Any]]:
    profiles = json_list_config(config, "feishu_bot_profiles")
    for profile in profiles:
        profile["id"] = ensure_profile_id("feishu", profile)
        profile.setdefault("label", "")
        profile.setdefault("app_id", "")
        profile.setdefault("app_secret", "")
        profile.setdefault("id_type", "chat_id")
        profile.setdefault("chats", [])
    if profiles:
        return profiles
    app_id = str(config.get("feishu_app_id") or "").strip()
    app_secret = str(config.get("feishu_app_secret") or "").strip()
    if not (app_id or app_secret):
        return []
    return [
        {
            "id": "default",
            "label": "榛樿椋炰功",
            "app_id": app_id,
            "app_secret": app_secret,
            "id_type": str(config.get("feishu_id_type") or "chat_id").strip() or "chat_id",
            "chats": [],
        }
    ]


def load_wechat_profiles(config: dict[str, object]) -> list[dict[str, Any]]:
    profiles = json_list_config(config, "wechat_bot_profiles")
    for profile in profiles:
        profile["id"] = ensure_profile_id("wechat", profile)
        profile.setdefault("label", "")
        profile.setdefault("token", "")
        profile.setdefault("base_url", "https://ilinkai.weixin.qq.com")
        profile.setdefault("cdn_base_url", "https://novac2c.cdn.weixin.qq.com/c2c")
        profile.setdefault("target_user_id", "")
        profile.setdefault("allowed_user_ids", "")
        profile.setdefault("poll_timeout_ms", "35000")
        profile.setdefault("route_tag", "")
        profile.setdefault("account_id", "default")
    if profiles:
        return profiles
    token = str(config.get("wechat_bot_token") or "").strip()
    if not token:
        return []
    return [
        {
            "id": "default",
            "label": "榛樿寰俊",
            "token": token,
            "base_url": str(config.get("wechat_bot_base_url") or "https://ilinkai.weixin.qq.com").strip(),
            "cdn_base_url": str(config.get("wechat_bot_cdn_base_url") or "https://novac2c.cdn.weixin.qq.com/c2c").strip(),
            "target_user_id": str(config.get("wechat_bot_target_user_id") or "").strip(),
            "allowed_user_ids": str(config.get("wechat_bot_allowed_user_ids") or "").strip(),
            "poll_timeout_ms": str(config.get("wechat_bot_poll_timeout_ms") or "35000").strip(),
            "route_tag": str(config.get("wechat_bot_route_tag") or "").strip(),
            "account_id": str(config.get("wechat_bot_account_id") or "default").strip() or "default",
        }
    ]


def load_dingtalk_profiles(config: dict[str, object]) -> list[dict[str, Any]]:
    profiles = json_list_config(config, "dingtalk_bot_profiles")
    for profile in profiles:
        profile["id"] = ensure_profile_id("dingtalk", profile)
        profile.setdefault("label", "")
        profile.setdefault("client_id", "")
        profile.setdefault("client_secret", "")
        profile.setdefault("robot_code", "")
        profile.setdefault("target_user_ids", "")
        profile.setdefault("allowed_user_ids", "")
        profile.setdefault("account_id", "default")
    if profiles:
        return profiles
    client_id = str(config.get("dingtalk_client_id") or "").strip()
    client_secret = str(config.get("dingtalk_client_secret") or "").strip()
    robot_code = str(config.get("dingtalk_robot_code") or "").strip()
    if not (client_id or client_secret or robot_code):
        return []
    return [
        {
            "id": "default",
            "label": "榛樿閽夐拤",
            "client_id": client_id,
            "client_secret": client_secret,
            "robot_code": robot_code,
            "target_user_ids": str(config.get("dingtalk_target_user_ids") or "").strip(),
            "allowed_user_ids": str(config.get("dingtalk_allowed_user_ids") or "").strip(),
            "account_id": str(config.get("dingtalk_account_id") or "default").strip() or "default",
        }
    ]


def load_email_profiles(config: dict[str, object]) -> list[dict[str, Any]]:
    profiles = json_list_config(config, "email_smtp_profiles")
    for profile in profiles:
        profile["id"] = ensure_profile_id("email", profile)
        profile.setdefault("label", "")
        profile.setdefault("smtp_host", "smtp.gmail.com")
        profile.setdefault("smtp_port", "587")
        profile.setdefault("smtp_security", "starttls")
        profile.setdefault("username", "")
        profile.setdefault("password", "")
        profile.setdefault("from_email", profile.get("username", ""))
        profile.setdefault("from_name", "NGA Wolf Watcher")
        profile.setdefault("reply_to", "")
    if profiles:
        return profiles
    username = str(config.get("email_username") or "").strip()
    password = str(config.get("email_password") or "").strip()
    from_email = str(config.get("email_from") or username).strip()
    if not (username or password or from_email):
        return []
    return [
        {
            "id": "default",
            "label": "榛樿閭",
            "smtp_host": str(config.get("email_smtp_host") or "smtp.gmail.com").strip(),
            "smtp_port": str(config.get("email_smtp_port") or "587").strip(),
            "smtp_security": str(config.get("email_smtp_security") or "starttls").strip(),
            "username": username,
            "password": password,
            "from_email": from_email,
            "from_name": str(config.get("email_from_name") or "NGA Wolf Watcher").strip(),
            "reply_to": str(config.get("email_reply_to") or "").strip(),
        }
    ]


def load_push_targets(
    config: dict[str, object],
    feishu_profiles: list[dict[str, Any]],
    wechat_profiles: list[dict[str, Any]],
    dingtalk_profiles: list[dict[str, Any]] | None = None,
    email_profiles: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    targets = json_list_config(config, "push_targets")
    for target in targets:
        target.setdefault("id", nga_feishu_watch.stable_profile_id("target", str(target.get("channel") or ""), str(target.get("profile_id") or ""), str(target.get("receive_id") or "")))
        target.setdefault("label", "")
        target.setdefault("channel", "feishu")
        target.setdefault("profile_id", "")
        target.setdefault("receive_id", "")
        target.setdefault("id_type", "chat_id")
        target.setdefault("default_author_id", "")
        target.setdefault("default_tid", "")
    if targets:
        return targets
    fallback: list[dict[str, Any]] = []
    receive_id = str(config.get("feishu_receive_id") or "").strip()
    if feishu_profiles and receive_id:
        fallback.append(
            {
                "id": "default_feishu",
                "label": "榛樿椋炰功缇?",
                "channel": "feishu",
                "profile_id": str(feishu_profiles[0].get("id") or "default"),
                "receive_id": receive_id,
                "id_type": str(config.get("feishu_id_type") or "chat_id"),
                "default_author_id": str(config.get("default_author_id") or ""),
                "default_tid": str(config.get("default_tid") or ""),
            }
        )
    target_user = str(config.get("wechat_bot_target_user_id") or "").strip()
    if wechat_profiles and target_user:
        fallback.append(
            {
                "id": "default_wechat",
                "label": "榛樿寰俊",
                "channel": "wechat",
                "profile_id": str(wechat_profiles[0].get("id") or "default"),
                "receive_id": target_user,
                "id_type": "user_id",
                "default_author_id": str(config.get("default_author_id") or ""),
                "default_tid": str(config.get("default_tid") or ""),
            }
        )
    dingtalk_targets = str(config.get("dingtalk_target_user_ids") or "").strip()
    if dingtalk_profiles and dingtalk_targets:
        fallback.append(
            {
                "id": "default_dingtalk",
                "label": "榛樿閽夐拤",
                "channel": "dingtalk",
                "profile_id": str(dingtalk_profiles[0].get("id") or "default"),
                "receive_id": dingtalk_targets,
                "id_type": "user_id",
                "default_author_id": str(config.get("default_author_id") or ""),
                "default_tid": str(config.get("default_tid") or ""),
            }
        )
    email_to = str(config.get("email_to") or "").strip()
    if email_profiles and email_to:
        fallback.append(
            {
                "id": "default_email",
                "label": "榛樿閭",
                "channel": "email",
                "profile_id": str(email_profiles[0].get("id") or "default"),
                "receive_id": email_to,
                "id_type": "email",
                "default_author_id": str(config.get("default_author_id") or ""),
                "default_tid": str(config.get("default_tid") or ""),
            }
        )
    return fallback


def load_listen_rules(config: dict[str, object]) -> list[dict[str, Any]]:
    rules = json_list_config(config, "listen_rules")
    for rule in rules:
        rule.setdefault("id", "")
        rule.setdefault("label", "")
        rule.setdefault("mode", "thread_author")
        rule.setdefault("author_id", "")
        rule.setdefault("tid", "")
        target_ids = rule.get("target_ids")
        if isinstance(target_ids, str):
            rule["target_ids"] = [part.strip() for part in re.split(r"[,，、\s]+", target_ids) if part.strip()]
        elif isinstance(target_ids, list):
            rule["target_ids"] = [str(part).strip() for part in target_ids if str(part).strip()]
        else:
            rule["target_ids"] = []
    if rules:
        return rules
    legacy: list[dict[str, Any]] = []
    mode = str(config.get("watch_mode") or "author")
    default_targets = []
    if str(config.get("feishu_receive_id") or "").strip():
        default_targets.append("default_feishu")
    if str(config.get("wechat_bot_target_user_id") or "").strip():
        default_targets.append("default_wechat")
    if str(config.get("email_to") or "").strip():
        default_targets.append("default_email")
    if mode in {"author", "both"}:
        for target in nga_feishu_watch.parse_target_list(config.get("watch_author_ids"), str(config.get("default_author_id") or "150058")):
            legacy.append({"id": f"author:{target.id}", "label": target.label, "mode": "author", "author_id": target.id, "tid": "", "target_ids": list(default_targets)})
    if mode in {"thread_author", "both"}:
        for watch in nga_feishu_watch.parse_thread_author_watches(config.get("thread_author_watches")):
            legacy.append({"id": f"thread_author:{watch.tid}:{watch.author_id}", "label": watch.label, "mode": "thread_author", "author_id": watch.author_id, "tid": watch.tid, "target_ids": list(default_targets)})
    return legacy


def int_value(config: dict[str, object], key: str, default: int) -> int:
    raw = str(config.get(key, default)).strip()
    return int(raw or default)


def float_value(config: dict[str, object], key: str, default: float) -> float:
    raw = str(config.get(key, default)).strip()
    return float(raw or default)


def resolved_state_path(config: dict[str, object], data_dir: Path | None = None) -> Path:
    raw = str(config.get("state_path") or ".nga_seen.json").strip()
    path = Path(raw)
    if path.is_absolute():
        return path
    if data_dir is not None:
        return data_dir / path
    return Path.cwd() / path


def build_args(
    config: dict[str, object],
    *,
    data_dir: Path | None = None,
    mark_seen: bool = False,
    ws: bool = False,
    ws_no_watch: bool = False,
) -> Namespace:
    watch_author_ids = str(config.get("watch_author_ids") or "").strip()
    preset_thread_ids = str(config.get("preset_thread_ids") or "").strip()
    author_targets = nga_feishu_watch.parse_target_list(watch_author_ids, str(config.get("default_author_id") or "150058").strip())
    thread_targets = nga_feishu_watch.parse_target_list(preset_thread_ids, str(config.get("default_tid") or "45974302").strip())
    author_id = author_targets[0].id if author_targets else str(config.get("default_author_id") or "150058").strip()
    default_tid = thread_targets[0].id if thread_targets else str(config.get("default_tid") or "45974302").strip()
    ai_work_dir = Path(str(config.get("ai_work_dir") or ".ai_agent_workspace").strip())
    if data_dir is not None and not ai_work_dir.is_absolute():
        ai_work_dir = data_dir / ai_work_dir
    return Namespace(
        bot_channel=str(config.get("bot_channel") or "feishu").strip(),
        author_id=author_id,
        author_ids=watch_author_ids,
        watch_mode=str(config.get("watch_mode") or "author").strip(),
        watch_author_ids=watch_author_ids,
        default_author_id=author_id,
        default_tid=default_tid,
        preset_thread_ids=preset_thread_ids,
        thread_author_watches=str(config.get("thread_author_watches") or "").strip(),
        push_targets=str(config.get("push_targets") or "").strip(),
        listen_rules=str(config.get("listen_rules") or "").strip(),
        thread_watch_tail_count=int_value(config, "thread_watch_tail_count", 20),
        thread_watch_interval=float_value(config, "thread_watch_interval", 10.0),
        max_pages=1,
        state_path=str(resolved_state_path(config, data_dir=data_dir)),
        cookie=str(config.get("nga_cookie") or "").strip(),
        webhook="",
        secret="",
        feishu_app_id=str(config.get("feishu_app_id") or "").strip(),
        feishu_app_secret=str(config.get("feishu_app_secret") or "").strip(),
        feishu_receive_id=str(config.get("feishu_receive_id") or "").strip(),
        feishu_id_type=str(config.get("feishu_id_type") or "chat_id").strip(),
        feishu_bot_profiles=str(config.get("feishu_bot_profiles") or "").strip(),
        wechat_bot_token=str(config.get("wechat_bot_token") or "").strip(),
        wechat_bot_base_url=str(config.get("wechat_bot_base_url") or "https://ilinkai.weixin.qq.com").strip(),
        wechat_bot_cdn_base_url=str(config.get("wechat_bot_cdn_base_url") or "https://novac2c.cdn.weixin.qq.com/c2c").strip(),
        wechat_bot_target_user_id=str(config.get("wechat_bot_target_user_id") or "").strip(),
        wechat_bot_allowed_user_ids=str(config.get("wechat_bot_allowed_user_ids") or "").strip(),
        wechat_bot_poll_timeout_ms=int_value(config, "wechat_bot_poll_timeout_ms", 35000),
        wechat_bot_route_tag=str(config.get("wechat_bot_route_tag") or "").strip(),
        wechat_bot_account_id=str(config.get("wechat_bot_account_id") or "default").strip(),
        wechat_bot_state_dir="",
        wechat_bot_profiles=str(config.get("wechat_bot_profiles") or "").strip(),
        dingtalk_client_id=str(config.get("dingtalk_client_id") or "").strip(),
        dingtalk_client_secret=str(config.get("dingtalk_client_secret") or "").strip(),
        dingtalk_robot_code=str(config.get("dingtalk_robot_code") or "").strip(),
        dingtalk_target_user_ids=str(config.get("dingtalk_target_user_ids") or "").strip(),
        dingtalk_allowed_user_ids=str(config.get("dingtalk_allowed_user_ids") or "").strip(),
        dingtalk_account_id=str(config.get("dingtalk_account_id") or "default").strip(),
        dingtalk_state_dir=str(config.get("dingtalk_state_dir") or "").strip(),
        dingtalk_session_webhook="",
        dingtalk_bot_profiles=str(config.get("dingtalk_bot_profiles") or "").strip(),
        email_smtp_profiles=str(config.get("email_smtp_profiles") or "").strip(),
        email_smtp_host=str(config.get("email_smtp_host") or "smtp.gmail.com").strip(),
        email_smtp_port=int_value(config, "email_smtp_port", 587),
        email_smtp_security=str(config.get("email_smtp_security") or "starttls").strip(),
        email_username=str(config.get("email_username") or "").strip(),
        email_password=str(config.get("email_password") or "").strip(),
        email_from=str(config.get("email_from") or "").strip(),
        email_from_name=str(config.get("email_from_name") or "NGA Wolf Watcher").strip(),
        email_reply_to=str(config.get("email_reply_to") or "").strip(),
        email_to=str(config.get("email_to") or "").strip(),
        wechat_poll=str(config.get("bot_channel") or "feishu").strip() == "wechat",
        timeout=int_value(config, "timeout", 20),
        dry_run=False,
        mark_seen=mark_seen,
        list_feishu_chats=False,
        send_test=False,
        message_format="card",
        disable_commands=False,
        command_lookback=600,
        retries=int_value(config, "retries", 10),
        retry_initial_delay=float_value(config, "retry_initial_delay", 1.0),
        retry_delay=float_value(config, "retry_delay", 1.0),
        nga_request_min_interval=float_value(config, "nga_request_min_interval", 1.0),
        nga_cache_ttl=float_value(config, "nga_cache_ttl", 15.0),
        nga_target_min_delay=float_value(config, "nga_target_min_delay", 2.0),
        nga_target_max_delay=float_value(config, "nga_target_max_delay", 6.0),
        nga_unavailable_backoff_base=float_value(config, "nga_unavailable_backoff_base", 60.0),
        nga_unavailable_backoff_max=float_value(config, "nga_unavailable_backoff_max", 600.0),
        interval=int_value(config, "interval", 30),
        jitter=int_value(config, "jitter", 20),
        quiet_hours_enabled=bool(config.get("quiet_hours_enabled", False)),
        quiet_start_day=int(str(config.get("quiet_start_day", "5") or "5")),
        quiet_end_day=int(str(config.get("quiet_end_day", "0") or "0")),
        quiet_days=list(config.get("quiet_days") or [5, 6]),
        quiet_start_time=str(config.get("quiet_start_time") or "00:00").strip(),
        quiet_end_time=str(config.get("quiet_end_time") or "00:00").strip(),
        quiet_policy=str(config.get("quiet_policy") or "ignore").strip(),
        once=False,
        ws=ws,
        ws_no_watch=ws_no_watch,
        ai_enabled=bool(config.get("ai_enabled", False)),
        ai_provider=str(config.get("ai_provider") or "codex").strip(),
        ai_work_dir=str(ai_work_dir),
        ai_auto_analyze_new_post=bool(config.get("ai_auto_analyze_new_post", False)),
        ai_auto_analysis_prompt=str(config.get("ai_auto_analysis_prompt") or "").strip(),
        ai_prompt_file=str(config.get("ai_prompt_file") or "").strip(),
        ai_history_limit=50,
        ai_timeout=int_value(config, "ai_timeout", 300),
        ai_codex_command=str(config.get("ai_codex_command") or "codex").strip(),
        ai_claude_command=str(config.get("ai_claude_command") or "claude").strip(),
        ai_codewhale_command=str(config.get("ai_codewhale_command") or "codewhale").strip(),
        ai_custom_command=str(config.get("ai_custom_command") or "").strip(),
        ai_model=str(config.get("ai_model") or "").strip(),
        ai_reasoning_effort=str(config.get("ai_reasoning_effort") or "").strip(),
        ai_ignore_codex_user_config=bool(config.get("ai_ignore_codex_user_config", False)),
        ai_schedule_enabled=bool(config.get("ai_schedule_enabled", False)),
        ai_schedule_interval_minutes=int_value(config, "ai_schedule_interval_minutes", 5),
        ai_schedule_prompt=str(config.get("ai_schedule_prompt") or "").strip(),
        ai_schedule_target_ids=str(config.get("ai_schedule_target_ids") or "").strip(),
        ai_schedule_windows=str(config.get("ai_schedule_windows") or "weekday:09:30-11:30,13:00-15:00").strip(),
        ai_allowed_user_ids=str(config.get("ai_allowed_user_ids") or "").strip(),
        ai_send_errors_to_feishu=bool(config.get("ai_send_errors_to_feishu", False)),
        ai_max_feishu_chars=int_value(config, "ai_max_feishu_chars", 3500),
        ai_upload_long_result=bool(config.get("ai_upload_long_result", False)),
    )


def validate_config(
    config: dict[str, object],
    *,
    require_receive_id: bool = True,
    require_cookie: bool = True,
) -> list[str]:
    channel = str(config.get("bot_channel") or "feishu").strip()
    if channel not in {"feishu", "wechat", "dingtalk", "email"}:
        channel = "feishu"

    required: list[tuple[str, str]] = []
    feishu_profiles = load_feishu_profiles(config)
    wechat_profiles = load_wechat_profiles(config)
    dingtalk_profiles = load_dingtalk_profiles(config)
    email_profiles = load_email_profiles(config)

    has_feishu_profile = any(str(p.get("app_id") or "").strip() and str(p.get("app_secret") or "").strip() for p in feishu_profiles)
    has_wechat_profile = any(str(p.get("token") or "").strip() for p in wechat_profiles)
    has_dingtalk_profile = any(str(p.get("client_id") or "").strip() and str(p.get("client_secret") or "").strip() for p in dingtalk_profiles)
    has_email_profile = any(str(p.get("username") or "").strip() and str(p.get("password") or "").strip() for p in email_profiles)

    push_targets = nga_feishu_watch.parse_push_targets(config.get("push_targets"))
    listen_rules = nga_feishu_watch.parse_listen_rules(config.get("listen_rules"))
    has_structured_routes = bool(push_targets or listen_rules)

    if not has_structured_routes and channel == "feishu":
        if not has_feishu_profile:
            required.extend([("feishu_app_id", "Feishu App ID"), ("feishu_app_secret", "Feishu App Secret")])
        if require_receive_id and not has_feishu_profile:
            required.append(("feishu_receive_id", "Receive ID"))
    elif not has_structured_routes and channel == "wechat":
        required.append(("wechat_bot_token", "WeChat Bot Token"))
        if require_receive_id:
            required.append(("wechat_bot_target_user_id", "WeChat target user ID"))
    elif not has_structured_routes and channel == "dingtalk":
        if not has_dingtalk_profile:
            required.extend([("dingtalk_client_id", "DingTalk Client ID"), ("dingtalk_client_secret", "DingTalk Client Secret")])
        if require_receive_id:
            required.append(("dingtalk_target_user_ids", "DingTalk target user IDs"))
    elif not has_structured_routes and channel == "email":
        if not has_email_profile:
            required.extend([("email_username", "email username"), ("email_password", "email password")])
        if require_receive_id:
            required.append(("email_to", "email recipient"))

    if has_wechat_profile:
        required = [(key, label) for key, label in required if key not in {"wechat_bot_token", "wechat_bot_target_user_id"}]
    if has_dingtalk_profile:
        required = [(key, label) for key, label in required if key not in {"dingtalk_client_id", "dingtalk_client_secret"}]
    if has_email_profile:
        required = [(key, label) for key, label in required if key not in {"email_username", "email_password"}]
    if require_cookie:
        required.append(("nga_cookie", "NGA Cookie"))

    errors = [label for key, label in required if not str(config.get(key) or "").strip()]

    watch_mode = str(config.get("watch_mode") or "author").strip()
    if watch_mode not in {"author", "thread_author", "both"}:
        errors.append("watch_mode must be author, thread_author, or both")

    for key, label, fallback in [
        ("watch_author_ids", "watch_author_ids", str(config.get("default_author_id") or "150058").strip()),
        ("preset_thread_ids", "preset_thread_ids", str(config.get("default_tid") or "45974302").strip()),
    ]:
        for target in nga_feishu_watch.parse_target_list(config.get(key), fallback):
            if not target.id.isdigit():
                errors.append(f"{label} contains non-numeric ID: {target.id}")

    push_target_ids = {target.id for target in push_targets}
    for target in push_targets:
        if target.channel == "feishu":
            profile = next((item for item in feishu_profiles if str(item.get("id") or "") == target.profile_id), None)
            if not profile:
                errors.append(f"push target {target.label or target.id} is missing a valid Feishu profile")
            elif not (str(profile.get("app_id") or "").strip() and str(profile.get("app_secret") or "").strip()):
                errors.append(f"push target {target.label or target.id} has incomplete Feishu credentials")
            if not target.receive_id:
                errors.append(f"push target {target.label or target.id} is missing Feishu receive_id")
        elif target.channel == "wechat":
            profile = next((item for item in wechat_profiles if str(item.get("id") or "") == target.profile_id), None)
            if not profile:
                errors.append(f"push target {target.label or target.id} is missing a valid WeChat profile")
            elif not str(profile.get("token") or "").strip():
                errors.append(f"push target {target.label or target.id} has incomplete WeChat token")
        elif target.channel == "dingtalk":
            profile = next((item for item in dingtalk_profiles if str(item.get("id") or "") == target.profile_id), None)
            if not profile:
                errors.append(f"push target {target.label or target.id} is missing a valid DingTalk profile")
            elif not (str(profile.get("client_id") or "").strip() and str(profile.get("client_secret") or "").strip()):
                errors.append(f"push target {target.label or target.id} has incomplete DingTalk credentials")
            if not target.receive_id:
                errors.append(f"push target {target.label or target.id} is missing DingTalk recipient")
        elif target.channel == "email":
            profile = next((item for item in email_profiles if str(item.get("id") or "") == target.profile_id), None)
            if not profile:
                errors.append(f"push target {target.label or target.id} is missing a valid email profile")
            elif not (str(profile.get("username") or "").strip() and str(profile.get("password") or "").strip()):
                errors.append(f"push target {target.label or target.id} has incomplete email credentials")
            if not target.receive_id:
                errors.append(f"push target {target.label or target.id} is missing email recipient")

    for rule in listen_rules:
        if not rule.author_id.isdigit() or (rule.mode == "thread_author" and not rule.tid.isdigit()):
            errors.append(f"listen rule {rule.label or rule.id} contains non-numeric NGA IDs")
        if not rule.target_ids:
            errors.append(f"listen rule {rule.label or rule.id} must reference at least one push target")
        for target_id in rule.target_ids:
            if target_id not in push_target_ids:
                errors.append(f"listen rule {rule.label or rule.id} references missing push target {target_id}")

    if not listen_rules and channel == "feishu" and require_receive_id and has_feishu_profile and not str(config.get("feishu_receive_id") or "").strip():
        routed_author_targets = nga_feishu_watch.parse_target_list(config.get("watch_author_ids"), str(config.get("default_author_id") or "150058").strip())
        routed_thread_watches = nga_feishu_watch.parse_thread_author_watches(config.get("thread_author_watches"))
        needs_default_route = False
        if watch_mode in {"author", "both"}:
            needs_default_route = any(not target.route_channel for target in routed_author_targets)
        if watch_mode in {"thread_author", "both"}:
            needs_default_route = needs_default_route or any(not watch.route_channel for watch in routed_thread_watches)
        if needs_default_route:
            errors.append("default Feishu receive_id is required for unrouted watches")

    if not listen_rules and watch_mode in {"thread_author", "both"}:
        watches = nga_feishu_watch.parse_thread_author_watches(config.get("thread_author_watches"))
        if not watches:
            errors.append("thread_author mode requires at least one tid:uid rule")
        for watch in watches:
            if not watch.tid.isdigit() or not watch.author_id.isdigit():
                errors.append(f"thread_author watch contains non-numeric IDs: {watch.tid}:{watch.author_id}")
            if (watch.feishu_app_id or watch.feishu_app_secret) and not (watch.feishu_app_id and watch.feishu_app_secret and watch.feishu_receive_id):
                errors.append(f"thread_author watch {watch.key} requires app_id, app_secret, and receive_id together")

    for key, label in [
        ("interval", "interval"),
        ("jitter", "jitter"),
        ("retries", "retries"),
        ("retry_initial_delay", "retry_initial_delay"),
        ("retry_delay", "retry_delay"),
        ("nga_request_min_interval", "nga_request_min_interval"),
        ("nga_cache_ttl", "nga_cache_ttl"),
        ("thread_watch_tail_count", "thread_watch_tail_count"),
        ("thread_watch_interval", "thread_watch_interval"),
        ("timeout", "timeout"),
        ("ai_timeout", "ai_timeout"),
        ("ai_schedule_interval_minutes", "ai_schedule_interval_minutes"),
        ("ai_max_feishu_chars", "ai_max_feishu_chars"),
        ("wechat_bot_poll_timeout_ms", "wechat_bot_poll_timeout_ms"),
    ]:
        try:
            float_value(config, key, 0)
        except ValueError:
            errors.append(f"{label} must be numeric")

    if bool(config.get("quiet_hours_enabled", False)):
        try:
            nga_feishu_watch.parse_weekday(config.get("quiet_start_day"), 5)
        except ValueError:
            errors.append("quiet_start_day is invalid")
        try:
            nga_feishu_watch.parse_weekday(config.get("quiet_end_day"), 0)
        except ValueError:
            errors.append("quiet_end_day is invalid")
        try:
            nga_feishu_watch.parse_hhmm(str(config.get("quiet_start_time") or ""))
        except ValueError:
            errors.append("quiet_start_time must be HH:MM")
        try:
            nga_feishu_watch.parse_hhmm(str(config.get("quiet_end_time") or ""))
        except ValueError:
            errors.append("quiet_end_time must be HH:MM")
        if str(config.get("quiet_policy") or "") not in {"ignore", "defer"}:
            errors.append("quiet_policy is invalid")

    provider = str(config.get("ai_provider") or "codex")
    if provider not in {"codex", "claude", "codewhale", "custom"}:
        errors.append("AI Provider must be codex, claude, codewhale, or custom")
    effort = str(config.get("ai_reasoning_effort") or "").strip().lower()
    if provider != "custom" and effort and not ai_analysis.is_valid_reasoning_effort(effort, provider):
        values = ", ".join(ai_analysis.reasoning_effort_options(provider))
        errors.append(f"AI reasoning effort must be one of: {values}")
    if bool(config.get("ai_enabled", False)) and provider == "custom" and not str(config.get("ai_custom_command") or "").strip():
        errors.append("custom AI provider requires ai_custom_command")

    return errors


def run_watcher_from_config(path: Path, *, data_dir: Path | None = None, ws_no_watch: bool = False) -> None:
    with path.open("r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    log_file = str(config.get("_log_path") or "")
    if log_file:
        log_handle = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_handle
        sys.stderr = log_handle
    try:
        channel = str(config.get("bot_channel") or "feishu").strip()
        args = build_args(config, data_dir=data_dir, ws=(channel == "feishu"), ws_no_watch=ws_no_watch)
        if nga_feishu_watch.uses_structured_routes(args) and not ws_no_watch:
            print("姝ｅ湪鍚姩缁撴瀯鍖栧閫氶亾鐩戝惉杩涚▼銆?")
            nga_feishu_watch.start_multi_channel(args)
            return
        if channel == "wechat":
            print("姝ｅ湪鍚姩寰俊 Bot 闀胯疆璇㈢洃鍚繘绋嬨€?")
            nga_feishu_watch.start_wechat_poll(args)
        elif channel == "dingtalk":
            print("姝ｅ湪鍚姩閽夐拤 Stream 鐩戝惉杩涚▼銆?")
            nga_feishu_watch.start_dingtalk_stream(args)
        elif channel == "email":
            print("姝ｅ湪鍚姩閭閫氶亾鐩戝惉杩涚▼銆?")
            service_unavailable_failures = 0
            while True:
                round_error: Exception | None = None
                try:
                    nga_feishu_watch.run_once(args)
                    nga_feishu_watch.maybe_run_ai_schedule(args)
                    service_unavailable_failures = 0
                except Exception as exc:
                    round_error = exc
                    if nga_feishu_watch.is_nga_service_unavailable(exc):
                        service_unavailable_failures += 1
                    else:
                        service_unavailable_failures = 0
                    print(f"閭閫氶亾鐩戝惉寰幆澶辫触: {exc}", file=sys.stderr)
                sleep_for = nga_feishu_watch.watch_sleep_seconds(args, round_error, service_unavailable_failures)
                time.sleep(sleep_for)
        else:
            print("姝ｅ湪鍚姩椋炰功 WebSocket 鐩戝惉杩涚▼銆?")
            nga_feishu_watch.start_ws(args)
    except BaseException:
        traceback.print_exc()
        raise
