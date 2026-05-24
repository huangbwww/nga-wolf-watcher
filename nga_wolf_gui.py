from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
import ctypes
from argparse import Namespace
from pathlib import Path
from tkinter import BooleanVar, END, Listbox, SINGLE, StringVar, messagebox
from typing import Any, Callable

import customtkinter as ctk

import ai_analysis
import nga_feishu_watch
import wechat_bot


APP_TITLE = "NGA Wolf Watcher"
APP_DIR_NAME = "NGA Wolf Watcher"
CONFIG_FILE = "config.json"
RUNTIME_CONFIG_FILE = "runtime_config.json"
LOG_FILE = "watcher.log"
ICON_FILE = "app_icon.ico"
WATCHER_PID_FILE = "watcher.pid"
LOG_POLL_MS = 1000
MAX_LOG_LINES_PER_POLL = 200

BG = "#f3f6fb"
CARD = "#ffffff"
CARD_ALT = "#f8fafc"
BORDER = "#e2e8f0"
TEXT = "#0f172a"
MUTED = "#64748b"
PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
SIDEBAR = "#0f2538"
SIDEBAR_ACTIVE = "#1d4ed8"

WATCH_MODE_LABELS = {
    "thread_author": "模式一：固定帖子筛选用户",
    "author": "模式二：用户主页监听",
    "both": "同时启用两种模式",
}
WATCH_MODE_VALUES = {label: value for value, label in WATCH_MODE_LABELS.items()}
ROUTE_CHANNEL_LABELS = {
    "inherit": "继承默认",
    "feishu": "飞书",
    "wechat": "微信",
}
ROUTE_CHANNEL_VALUES = {label: value for value, label in ROUTE_CHANNEL_LABELS.items()}

FEISHU_ID_TYPE_LABELS = {
    "chat_id": "群聊 chat_id（推荐）",
    "open_id": "单个用户 open_id",
    "user_id": "单个用户 user_id",
    "union_id": "单个用户 union_id",
}
FEISHU_ID_TYPE_VALUES = {label: value for value, label in FEISHU_ID_TYPE_LABELS.items()}


def feishu_id_type_label(value: str) -> str:
    return FEISHU_ID_TYPE_LABELS.get(str(value or "chat_id"), str(value or "chat_id"))


def feishu_id_type_value(label: str) -> str:
    text = str(label or "chat_id")
    return FEISHU_ID_TYPE_VALUES.get(text, text if text in FEISHU_ID_TYPE_LABELS else "chat_id")


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
    "default_author_id": "150058",
    "default_tid": "45974302",
    "watch_mode": "author",
    "watch_author_ids": "150058=狼大",
    "preset_thread_ids": "45974302=自立自强，科学技术打头阵",
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
    "ai_auto_analysis_prompt": "根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。",
    "ai_prompt_file": "",
    "ai_timeout": "300",
    "ai_codex_command": "codex",
    "ai_claude_command": "claude",
    "ai_codewhale_command": "codewhale",
    "ai_custom_command": "",
    "ai_model": "",
    "ai_reasoning_effort": "default",
    "ai_ignore_codex_user_config": False,
    "ai_schedule_enabled": False,
    "ai_schedule_interval_minutes": "5",
    "ai_schedule_prompt": "根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。",
    "ai_schedule_target_ids": "",
    "ai_schedule_window_mode": "a_share",
    "ai_schedule_windows": "weekday:09:30-11:30,13:00-15:00",
    "ai_allowed_user_ids": "",
    "ai_send_errors_to_feishu": False,
    "ai_max_feishu_chars": "3500",
    "ai_upload_long_result": False,
    "web_close_behavior": "ask",
}


WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
HOUR_OPTIONS = [f"{hour:02d}" for hour in range(24)]
MINUTE_OPTIONS = [f"{minute:02d}" for minute in range(60)]


def weekday_label(day: int) -> str:
    if day < 0 or day > 6:
        return WEEKDAY_LABELS[0]
    return WEEKDAY_LABELS[day]


def weekday_index(label: str) -> int:
    try:
        return WEEKDAY_LABELS.index(label)
    except ValueError:
        return 0


def split_hhmm(value: object, default: str) -> tuple[str, str]:
    text = str(value or default).strip()
    try:
        minutes = nga_feishu_watch.parse_hhmm(text)
    except ValueError:
        minutes = nga_feishu_watch.parse_hhmm(default)
    return f"{minutes // 60:02d}", f"{minutes % 60:02d}"


class HoverTooltip:
    def __init__(self, widget: ctk.CTkBaseClass, text: str) -> None:
        self.widget = widget
        self.text = text
        self.window: ctk.CTkToplevel | None = None
        widget.bind("<Enter>", self.show)
        widget.bind("<Leave>", self.hide)

    def show(self, _event: object | None = None) -> None:
        if self.window is not None:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + 24
        self.window = ctk.CTkToplevel(self.widget)
        self.window.overrideredirect(True)
        self.window.geometry(f"+{x}+{y}")
        ctk.CTkLabel(
            self.window,
            text=self.text,
            justify="left",
            wraplength=340,
            fg_color="#0f172a",
            text_color="#ffffff",
            corner_radius=8,
            width=360,
            height=72,
        ).grid(row=0, column=0)

    def hide(self, _event: object | None = None) -> None:
        if self.window is not None:
            self.window.destroy()
            self.window = None


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", app_dir()))
    return app_dir()


def icon_path() -> Path:
    return resource_dir() / "assets" / ICON_FILE


def data_dir() -> Path:
    root = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    if root:
        path = Path(root) / APP_DIR_NAME
    else:
        path = Path.home() / f".{APP_DIR_NAME.lower().replace(' ', '_')}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def old_config_path() -> Path:
    return app_dir() / "nga_wolf_config.json"


def config_path() -> Path:
    return data_dir() / CONFIG_FILE


def watcher_config_path() -> Path:
    return data_dir() / RUNTIME_CONFIG_FILE


def log_path() -> Path:
    return data_dir() / LOG_FILE


def watcher_pid_path() -> Path:
    return data_dir() / WATCHER_PID_FILE


def migrate_old_config() -> None:
    new_path = config_path()
    old_path = old_config_path()
    if new_path.exists() or not old_path.exists():
        return
    try:
        new_path.write_text(old_path.read_text(encoding="utf-8-sig"), encoding="utf-8")
    except OSError:
        pass


def load_config() -> dict[str, object]:
    migrate_old_config()
    path = config_path()
    if not path.exists():
        return dict(DEFAULT_CONFIG)
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            loaded = json.load(f)
    except Exception:
        return dict(DEFAULT_CONFIG)
    config = dict(DEFAULT_CONFIG)
    if isinstance(loaded, dict):
        config.update(loaded)
    return config


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write("\n")
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


def save_config(config: dict[str, object]) -> None:
    write_json(config_path(), config)


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
            "label": "默认飞书",
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
            "label": "默认微信",
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


def load_push_targets(config: dict[str, object], feishu_profiles: list[dict[str, Any]], wechat_profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
                "label": "默认飞书群",
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
                "label": "默认微信",
                "channel": "wechat",
                "profile_id": str(wechat_profiles[0].get("id") or "default"),
                "receive_id": target_user,
                "id_type": "user_id",
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
            rule["target_ids"] = [part.strip() for part in re.split(r"[,，;；\s]+", target_ids) if part.strip()]
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
    if mode in {"author", "both"}:
        for target in nga_feishu_watch.parse_target_list(config.get("watch_author_ids"), str(config.get("default_author_id") or "150058")):
            legacy.append({"id": f"author:{target.id}", "label": target.label, "mode": "author", "author_id": target.id, "tid": "", "target_ids": list(default_targets)})
    if mode in {"thread_author", "both"}:
        for watch in nga_feishu_watch.parse_thread_author_watches(config.get("thread_author_watches")):
            legacy.append({"id": f"thread_author:{watch.tid}:{watch.author_id}", "label": watch.label, "mode": "thread_author", "author_id": watch.author_id, "tid": watch.tid, "target_ids": list(default_targets)})
    return legacy


def profile_label(profile: dict[str, Any], fallback: str) -> str:
    label = str(profile.get("label") or "").strip()
    profile_id = str(profile.get("id") or "").strip()
    return f"{label} ({profile_id})" if label and profile_id else label or profile_id or fallback


def chat_label(chat: dict[str, Any]) -> str:
    chat_id = str(chat.get("chat_id") or chat.get("id") or "").strip()
    name = str(chat.get("name") or chat.get("title") or "").strip()
    return f"{name} ({chat_id})" if name and chat_id else chat_id or name


def push_target_label(target: dict[str, Any]) -> str:
    channel = "飞书" if str(target.get("channel") or "feishu") == "feishu" else "微信"
    label = str(target.get("label") or "").strip()
    target_id = str(target.get("id") or "").strip()
    receive_id = str(target.get("receive_id") or "").strip()
    name = label or target_id or receive_id
    suffix = f" -> {receive_id}" if receive_id else ""
    return f"{channel} / {name}{suffix}"


def listen_rule_label(rule: dict[str, Any]) -> str:
    mode = str(rule.get("mode") or "thread_author")
    label = str(rule.get("label") or "").strip()
    author_id = str(rule.get("author_id") or "").strip()
    tid = str(rule.get("tid") or "").strip()
    source = f"帖子 {tid} / 用户 {author_id}" if mode == "thread_author" else f"用户主页 {author_id}"
    targets = rule.get("target_ids") if isinstance(rule.get("target_ids"), list) else []
    prefix = label + "：" if label else ""
    return f"{prefix}{source} -> {len(targets)} 个发送目标"


def route_channel_label(value: str) -> str:
    return ROUTE_CHANNEL_LABELS.get(str(value or "").strip() or "inherit", ROUTE_CHANNEL_LABELS["inherit"])


def route_channel_value(label: str) -> str:
    value = ROUTE_CHANNEL_VALUES.get(str(label or "").strip(), str(label or "").strip())
    return "" if value == "inherit" else value


def save_runtime_config(config: dict[str, object]) -> None:
    write_json(watcher_config_path(), config)


def int_value(config: dict[str, object], key: str, default: int) -> int:
    raw = str(config.get(key, default)).strip()
    return int(raw or default)


def float_value(config: dict[str, object], key: str, default: float) -> float:
    raw = str(config.get(key, default)).strip()
    return float(raw or default)


def resolved_state_path(config: dict[str, object]) -> Path:
    raw = str(config.get("state_path") or ".nga_seen.json").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = data_dir() / path
    return path


def build_args(
    config: dict[str, object],
    *,
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
        state_path=str(resolved_state_path(config)),
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
        ai_work_dir=str(config.get("ai_work_dir") or ".ai_agent_workspace").strip(),
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
    if channel not in {"feishu", "wechat"}:
        channel = "feishu"
    required: list[tuple[str, str]] = []
    feishu_profiles = load_feishu_profiles(config)
    wechat_profiles = load_wechat_profiles(config)
    has_feishu_profile = any(str(profile.get("app_id") or "").strip() and str(profile.get("app_secret") or "").strip() for profile in feishu_profiles)
    has_wechat_profile = any(str(profile.get("token") or "").strip() for profile in wechat_profiles)
    push_targets = nga_feishu_watch.parse_push_targets(config.get("push_targets"))
    listen_rules = nga_feishu_watch.parse_listen_rules(config.get("listen_rules"))
    has_structured_routes = bool(push_targets or listen_rules)
    if not has_structured_routes and channel == "feishu":
        if not has_feishu_profile:
            required.extend(
                [
                    ("feishu_app_id", "Feishu App ID"),
                    ("feishu_app_secret", "Feishu App Secret"),
                ]
            )
        if require_receive_id and not has_feishu_profile:
            required.append(("feishu_receive_id", "Receive ID"))
    elif not has_structured_routes:
        required.append(("wechat_bot_token", "微信 Bot Token"))
        if require_receive_id:
            required.append(("wechat_bot_target_user_id", "微信目标用户 ID"))
    if has_wechat_profile:
        required = [(key, label) for key, label in required if key not in {"wechat_bot_token", "wechat_bot_target_user_id"}]
    if require_cookie:
        required.append(("nga_cookie", "NGA Cookie"))
    errors = [label for key, label in required if not str(config.get(key) or "").strip()]
    for key, label, fallback in [
        ("watch_author_ids", "监听用户 ID 列表", str(config.get("default_author_id") or "150058").strip()),
        ("preset_thread_ids", "帖子预设 ID 列表", str(config.get("default_tid") or "45974302").strip()),
    ]:
        for target in nga_feishu_watch.parse_target_list(config.get(key), fallback):
            if not target.id.isdigit():
                errors.append(f"{label} 包含非数字 ID：{target.id}")
    watch_mode = str(config.get("watch_mode") or "author").strip()
    if watch_mode not in {"author", "thread_author", "both"}:
        errors.append("监听模式必须是 author、thread_author 或 both")
    push_target_ids = {target.id for target in push_targets}
    for target in push_targets:
        if target.channel == "feishu":
            profile = next((item for item in feishu_profiles if str(item.get("id") or "") == target.profile_id), None)
            if not profile:
                errors.append(f"发送目标 {target.label or target.id} 未选择有效飞书机器人")
            elif not (str(profile.get("app_id") or "").strip() and str(profile.get("app_secret") or "").strip()):
                errors.append(f"发送目标 {target.label or target.id} 的飞书机器人缺少 App ID 或 App Secret")
            if not target.receive_id:
                errors.append(f"发送目标 {target.label or target.id} 缺少飞书群 chat_id")
        elif target.channel == "wechat":
            profile = next((item for item in wechat_profiles if str(item.get("id") or "") == target.profile_id), None)
            if not profile:
                errors.append(f"发送目标 {target.label or target.id} 未选择有效微信机器人")
            elif not str(profile.get("token") or "").strip():
                errors.append(f"发送目标 {target.label or target.id} 的微信机器人缺少 Token")
    for rule in listen_rules:
        if not rule.author_id.isdigit() or (rule.mode == "thread_author" and not rule.tid.isdigit()):
            errors.append(f"监听规则 {rule.label or rule.id} 包含非数字 NGA ID")
        if not rule.target_ids:
            errors.append(f"监听规则 {rule.label or rule.id} 至少需要选择一个发送目标")
        for target_id in rule.target_ids:
            if target_id not in push_target_ids:
                errors.append(f"监听规则 {rule.label or rule.id} 选择了不存在的发送目标：{target_id}")
    if not listen_rules and channel == "feishu" and require_receive_id and has_feishu_profile and not str(config.get("feishu_receive_id") or "").strip():
        routed_author_targets = nga_feishu_watch.parse_target_list(config.get("watch_author_ids"), str(config.get("default_author_id") or "150058").strip())
        routed_thread_watches = nga_feishu_watch.parse_thread_author_watches(config.get("thread_author_watches"))
        needs_default_route = False
        if watch_mode in {"author", "both"}:
            needs_default_route = any(not target.route_channel for target in routed_author_targets)
        if watch_mode in {"thread_author", "both"}:
            needs_default_route = needs_default_route or any(not watch.route_channel for watch in routed_thread_watches)
        if needs_default_route:
            errors.append("存在未单独选择通道的监听项，请填写默认飞书 Receive ID，或给这些监听项选择具体通道。")
    if not listen_rules and watch_mode in {"thread_author", "both"}:
        watches = nga_feishu_watch.parse_thread_author_watches(config.get("thread_author_watches"))
        if not watches:
            errors.append("帖内作者监听模式需要至少一条 tid:uid 规则")
        for watch in watches:
            if not watch.tid.isdigit() or not watch.author_id.isdigit():
                errors.append(f"帖内作者规则包含非数字 ID：{watch.tid}:{watch.author_id}")
            if (watch.feishu_app_id or watch.feishu_app_secret) and not (watch.feishu_app_id and watch.feishu_app_secret and watch.feishu_receive_id):
                errors.append(f"帖内作者规则 {watch.key} 使用单独飞书机器人时必须同时填写 app_id、app_secret 和 receive_id")
    for key, label in [
        ("interval", "轮询间隔"),
        ("jitter", "用户回复随机抖动"),
        ("retries", "重试次数"),
        ("retry_initial_delay", "重试初始等待"),
        ("retry_delay", "重试延迟"),
        ("nga_request_min_interval", "NGA 请求最小间隔"),
        ("nga_cache_ttl", "NGA 短缓存"),
        ("thread_watch_tail_count", "帖内扫描条数"),
        ("thread_watch_interval", "帖内扫描间隔"),
        ("timeout", "请求超时"),
        ("ai_timeout", "AI 超时"),
        ("ai_schedule_interval_minutes", "AI 定时间隔"),
        ("ai_max_feishu_chars", "AI 飞书最大字符"),
        ("wechat_bot_poll_timeout_ms", "微信长轮询超时"),
    ]:
        try:
            float_value(config, key, 0)
        except ValueError:
            errors.append(f"{label}必须是数字")
    if bool(config.get("quiet_hours_enabled", False)):
        try:
            nga_feishu_watch.parse_weekday(config.get("quiet_start_day"), 5)
        except ValueError:
            errors.append("免打扰开始星期无效")
        try:
            nga_feishu_watch.parse_weekday(config.get("quiet_end_day"), 0)
        except ValueError:
            errors.append("免打扰结束星期无效")
        try:
            nga_feishu_watch.parse_hhmm(str(config.get("quiet_start_time") or ""))
        except ValueError:
            errors.append("免打扰开始时间必须是 HH:MM")
        try:
            nga_feishu_watch.parse_hhmm(str(config.get("quiet_end_time") or ""))
        except ValueError:
            errors.append("免打扰结束时间必须是 HH:MM")
        if str(config.get("quiet_policy") or "") not in {"ignore", "defer"}:
            errors.append("免打扰处理方式无效")
    provider = str(config.get("ai_provider") or "codex")
    if provider not in {"codex", "claude", "codewhale", "custom"}:
        errors.append("AI Provider 必须是 codex、claude、codewhale 或 custom")
    effort = str(config.get("ai_reasoning_effort") or "").strip().lower()
    if provider != "custom" and effort and not ai_analysis.is_valid_reasoning_effort(effort, provider):
        values = "、".join(["default", *ai_analysis.reasoning_effort_options(provider)])
        errors.append(f"AI 思考强度必须是 {values}")
    if bool(config.get("ai_enabled", False)) and provider == "custom":
        if not str(config.get("ai_custom_command") or "").strip():
            errors.append("启用 custom AI provider 时必须填写 Custom 命令模板")
    return errors


def command_for_mode(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-u", str(Path(__file__).resolve()), *args]


def process_exists(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def find_watcher_process_ids() -> set[int]:
    if sys.platform != "win32":
        return set()
    script = """
$own = $PID
Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $own -and
    ($_.Name -ieq 'python.exe' -or $_.Name -ieq 'pythonw.exe' -or $_.Name -ieq 'NGA-Wolf-Watcher.exe' -or $_.Name -ieq 'NGA-Wolf-Watcher-Web.exe') -and
    $_.CommandLine -like '*--watcher-config*'
} | ForEach-Object { $_.ProcessId }
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return set()
    pids: set[int] = set()
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid and pid != os.getpid():
            pids.add(pid)
    return pids


def kill_process_tree(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform == "win32":
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.returncode == 0
    try:
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def run_watcher_from_config(path: Path, *, ws_no_watch: bool = False) -> None:
    with path.open("r", encoding="utf-8-sig") as f:
        config = json.load(f)
    log_file = str(config.get("_log_path") or "")
    if log_file:
        log_handle = open(log_file, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_handle
        sys.stderr = log_handle
    try:
        channel = str(config.get("bot_channel") or "feishu").strip()
        args = build_args(config, ws=(channel != "wechat"), ws_no_watch=ws_no_watch)
        if nga_feishu_watch.uses_structured_routes(args) and not ws_no_watch:
            print("正在启动结构化多通道监听进程。")
            nga_feishu_watch.start_multi_channel(args)
            return
        if channel == "wechat":
            print("正在启动微信 Bot 长轮询监听进程。")
            nga_feishu_watch.start_wechat_poll(args)
        else:
            print("正在启动飞书 WebSocket 监听进程。")
            nga_feishu_watch.start_ws(args)
    except BaseException:
        traceback.print_exc()
        raise


class App:
    def __init__(self, root: ctk.CTk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.apply_app_icon()
        self.root.geometry("820x760")
        self.root.minsize(760, 680)

        self.config = load_config()
        self.process: subprocess.Popen[str] | None = None
        self.log_offset = 0
        self.ui_thread = threading.get_ident()
        self.operation_lock = threading.Lock()
        self.starting = False
        self.stopping = False

        self.vars: dict[str, StringVar] = {
            key: StringVar(value=str(self.config.get(key) or ""))
            for key in [
                "bot_channel",
                "feishu_app_id",
                "feishu_app_secret",
                "feishu_receive_id",
                "feishu_id_type",
                "wechat_bot_token",
                "wechat_bot_base_url",
                "wechat_bot_cdn_base_url",
                "wechat_bot_target_user_id",
                "wechat_bot_allowed_user_ids",
                "wechat_bot_poll_timeout_ms",
                "wechat_bot_route_tag",
                "wechat_bot_account_id",
                "default_author_id",
                "default_tid",
                "watch_mode",
                "thread_watch_tail_count",
                "thread_watch_interval",
                "interval",
                "jitter",
                "retries",
                "retry_initial_delay",
                "retry_delay",
                "nga_request_min_interval",
                "nga_cache_ttl",
                "nga_target_min_delay",
                "nga_target_max_delay",
                "nga_unavailable_backoff_base",
                "nga_unavailable_backoff_max",
                "timeout",
                "state_path",
                "ai_provider",
                "ai_work_dir",
                "ai_auto_analysis_prompt",
                "ai_prompt_file",
                "ai_timeout",
                "ai_codex_command",
                "ai_claude_command",
                "ai_codewhale_command",
                "ai_custom_command",
                "ai_model",
                "ai_reasoning_effort",
                "ai_schedule_interval_minutes",
                "ai_schedule_prompt",
                "ai_schedule_windows",
                "ai_allowed_user_ids",
                "ai_max_feishu_chars",
            ]
        }
        if not self.vars["feishu_id_type"].get():
            self.vars["feishu_id_type"].set("chat_id")
        if self.vars["bot_channel"].get() not in {"feishu", "wechat"}:
            self.vars["bot_channel"].set("feishu")
        if not self.vars["wechat_bot_base_url"].get():
            self.vars["wechat_bot_base_url"].set("https://ilinkai.weixin.qq.com")
        if not self.vars["wechat_bot_cdn_base_url"].get():
            self.vars["wechat_bot_cdn_base_url"].set("https://novac2c.cdn.weixin.qq.com/c2c")
        if not self.vars["wechat_bot_poll_timeout_ms"].get():
            self.vars["wechat_bot_poll_timeout_ms"].set("35000")
        if not self.vars["wechat_bot_account_id"].get():
            self.vars["wechat_bot_account_id"].set("default")
        self.channel_label_var = StringVar(value=route_channel_label(self.vars["bot_channel"].get()))

        self.auto_init_var = BooleanVar(value=bool(self.config.get("auto_mark_seen_first_start", True)))
        self.quiet_enabled_var = BooleanVar(value=bool(self.config.get("quiet_hours_enabled", False)))
        quiet_start_day = nga_feishu_watch.parse_weekday(self.config.get("quiet_start_day", 5), 5)
        quiet_end_day = nga_feishu_watch.parse_weekday(self.config.get("quiet_end_day", 0), 0)
        self.quiet_start_day_var = StringVar(value=weekday_label(quiet_start_day))
        self.quiet_end_day_var = StringVar(value=weekday_label(quiet_end_day))
        start_hour, start_minute = split_hhmm(self.config.get("quiet_start_time"), "00:00")
        end_hour, end_minute = split_hhmm(self.config.get("quiet_end_time"), "00:00")
        self.quiet_start_hour_var = StringVar(value=start_hour)
        self.quiet_start_minute_var = StringVar(value=start_minute)
        self.quiet_end_hour_var = StringVar(value=end_hour)
        self.quiet_end_minute_var = StringVar(value=end_minute)
        self.quiet_policy_var = StringVar(value=str(self.config.get("quiet_policy") or "ignore"))
        self.ai_enabled_var = BooleanVar(value=bool(self.config.get("ai_enabled", False)))
        self.ai_auto_var = BooleanVar(value=bool(self.config.get("ai_auto_analyze_new_post", False)))
        self.ai_schedule_var = BooleanVar(value=bool(self.config.get("ai_schedule_enabled", False)))
        self.ai_send_errors_var = BooleanVar(value=bool(self.config.get("ai_send_errors_to_feishu", False)))
        self.ai_upload_long_result_var = BooleanVar(value=bool(self.config.get("ai_upload_long_result", False)))
        self.ai_ignore_codex_user_config_var = BooleanVar(value=bool(self.config.get("ai_ignore_codex_user_config", False)))
        raw_window_mode = str(self.config.get("ai_schedule_window_mode") or "a_share")
        self.ai_schedule_window_mode_var = StringVar(value="自定义" if raw_window_mode == "custom" else "A股开市时间")
        self.status_var = StringVar(value="未启动")
        self.status_detail_var = StringVar(value="监听服务尚未运行")
        self.action_feedback_var = StringVar(value="准备就绪")
        self.save_state_var = StringVar(value="配置已保存")
        self.path_var = StringVar(value=str(config_path()))
        self.dirty = False

        self.pages: dict[str, ctk.CTkBaseClass] = {}
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.current_page: str | None = None
        self.cookie_textboxes: list[ctk.CTkTextbox] = []
        self.target_lists: dict[str, list[nga_feishu_watch.WatchTarget]] = {}
        self.target_listboxes: dict[str, list[Listbox]] = {}
        self.selected_target_indices: dict[str, int] = {}
        self.feishu_profiles = load_feishu_profiles(self.config)
        self.wechat_profiles = load_wechat_profiles(self.config)
        self.push_targets = load_push_targets(self.config, self.feishu_profiles, self.wechat_profiles)
        self.listen_rules = load_listen_rules(self.config)
        self.feishu_profile_listboxes: list[Listbox] = []
        self.wechat_profile_listboxes: list[Listbox] = []
        self.push_target_listboxes: list[Listbox] = []
        self.listen_rule_listboxes: list[Listbox] = []
        self.ai_schedule_target_frames: list[ctk.CTkFrame] = []
        self.ai_schedule_target_listboxes: list[Listbox] = []
        self.ai_schedule_selected_target_ids = self.configured_ai_schedule_target_id_list()
        self.selected_feishu_profile_index = 0 if self.feishu_profiles else -1
        self.selected_wechat_profile_index = 0 if self.wechat_profiles else -1
        self.selected_push_target_index = 0 if self.push_targets else -1
        self.selected_listen_rule_index = 0 if self.listen_rules else -1
        self.watch_mode_label_var = StringVar(
            value=WATCH_MODE_LABELS.get(self.vars["watch_mode"].get(), WATCH_MODE_LABELS["author"])
        )
        self.thread_author_watches = list(nga_feishu_watch.parse_thread_author_watches(self.config.get("thread_author_watches")))
        self.thread_author_listboxes: list[Listbox] = []
        self.selected_thread_author_index = 0 if self.thread_author_watches else -1
        self.chat_result_frames: list[ctk.CTkFrame] = []
        self.feishu_frames: list[ctk.CTkFrame] = []
        self.wechat_frames: list[ctk.CTkFrame] = []
        self.syncing_cookie = False
        self.log_text: ctk.CTkTextbox
        self.status_dot: ctk.CTkLabel
        self.status_badge: ctk.CTkLabel
        self.start_button: ctk.CTkButton
        self.stop_button: ctk.CTkButton
        self.global_save_button: ctk.CTkButton
        self.save_state_label: ctk.CTkLabel
        self.minute_picker: ctk.CTkToplevel | None = None
        self.ai_model_menu: ctk.CTkOptionMenu | None = None
        self.ai_model_entry: ctk.CTkEntry | None = None
        self.ai_reasoning_menu: ctk.CTkOptionMenu | None = None
        self.ai_reasoning_entry: ctk.CTkEntry | None = None

        self.build_ui()
        self.poll_logs()
        self.poll_process()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def apply_app_icon(self) -> None:
        try:
            if sys.platform == "win32":
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("nga.wolf.watcher")
        except Exception:
            pass

        path = icon_path()
        if not path.exists():
            return
        try:
            self.root.iconbitmap(default=str(path))
        except Exception:
            pass

    def build_ui(self) -> None:
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")

        self.root.configure(fg_color=BG)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.build_sidebar()

        self.main = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(0, weight=1)

        self.build_quick_page()
        self.build_feishu_page()
        self.build_nga_page()
        self.build_ai_page()
        self.build_log_page()
        self.build_settings_page()
        self.build_global_action_bar()
        self.watch_config_changes()
        self.update_channel_visibility()
        self.show_page("quick")

        self.append_log(f"配置文件：{config_path()}")
        self.append_log(f"状态文件：{resolved_state_path(self.config)}")
        self.append_log(f"日志文件：{log_path()}")

    def build_global_action_bar(self) -> None:
        bar = ctk.CTkFrame(self.main, fg_color="#ffffff", corner_radius=0, border_width=1, border_color=BORDER)
        bar.grid(row=1, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        self.save_state_label = ctk.CTkLabel(
            bar,
            textvariable=self.save_state_var,
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        )
        self.save_state_label.grid(row=0, column=0, sticky="ew", padx=18, pady=12)
        self.global_save_button = ctk.CTkButton(
            bar,
            text="保存配置",
            width=112,
            height=34,
            corner_radius=10,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            command=self.save_from_ui,
        )
        self.global_save_button.grid(row=0, column=1, sticky="e", padx=(0, 18), pady=10)

    def watch_config_changes(self) -> None:
        variables: list[object] = [
            *self.vars.values(),
            self.auto_init_var,
            self.quiet_enabled_var,
            self.quiet_start_day_var,
            self.quiet_end_day_var,
            self.quiet_start_hour_var,
            self.quiet_start_minute_var,
            self.quiet_end_hour_var,
            self.quiet_end_minute_var,
            self.quiet_policy_var,
            self.ai_enabled_var,
            self.ai_auto_var,
            self.ai_schedule_var,
            self.ai_send_errors_var,
            self.ai_ignore_codex_user_config_var,
            self.ai_upload_long_result_var,
            self.ai_schedule_window_mode_var,
            self.watch_mode_label_var,
        ]
        for var in variables:
            var.trace_add("write", lambda *_args: self.mark_dirty())

    def mark_dirty(self) -> None:
        if self.dirty:
            return
        self.dirty = True
        self.save_state_var.set("有未保存修改")
        if hasattr(self, "save_state_label"):
            self.save_state_label.configure(text_color="#b45309")
        if hasattr(self, "global_save_button"):
            self.global_save_button.configure(fg_color="#f59e0b", hover_color="#d97706")

    def build_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(self.root, width=154, fg_color=SIDEBAR, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(8, weight=1)

        ctk.CTkLabel(
            sidebar,
            text="NGA Wolf",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color="#ffffff",
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(22, 2))
        ctk.CTkLabel(
            sidebar,
            text="Watcher",
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=17, weight="bold"),
            text_color="#cbd5e1",
        ).grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 20))

        items = [
            ("quick", "快速开始", "⌂"),
            ("feishu", "通道配置", "↗"),
            ("nga", "NGA配置", "◎"),
            ("ai", "AI分析", "AI"),
            ("log", "日志", "□"),
            ("settings", "设置", "⚙"),
        ]
        for row, (key, text, icon) in enumerate(items, start=2):
            button = ctk.CTkButton(
                sidebar,
                text=f"{icon}  {text}",
                anchor="w",
                height=38,
                corner_radius=10,
                fg_color="transparent",
                hover_color="#17324a",
                text_color="#dbeafe",
                font=ctk.CTkFont(size=13, weight="bold"),
                command=lambda page=key: self.show_page(page),
            )
            button.grid(row=row, column=0, sticky="ew", padx=12, pady=4)
            self.nav_buttons[key] = button

        ctk.CTkLabel(
            sidebar,
            text="NGA Wolf Watcher\nv1.0.8",
            justify="left",
            anchor="w",
            font=ctk.CTkFont(size=11),
            text_color="#93a4b8",
        ).grid(row=9, column=0, sticky="ew", padx=18, pady=(0, 18))

    def make_page(self, name: str, *, scroll: bool = True) -> ctk.CTkFrame:
        if scroll:
            page = ctk.CTkScrollableFrame(self.main, fg_color=BG, corner_radius=0)
        else:
            page = ctk.CTkFrame(self.main, fg_color=BG, corner_radius=0)
        page.grid_columnconfigure(0, weight=1)
        self.pages[name] = page
        return page

    def show_page(self, name: str) -> None:
        if self.current_page == name:
            return
        for page_name, page in self.pages.items():
            if page_name == name:
                page.grid(row=0, column=0, sticky="nsew", padx=18, pady=18)
            else:
                page.grid_forget()
        self.current_page = name
        for key, button in self.nav_buttons.items():
            if key == name:
                button.configure(fg_color=SIDEBAR_ACTIVE, hover_color=SIDEBAR_ACTIVE, text_color="#ffffff")
            else:
                button.configure(fg_color="transparent", hover_color="#17324a", text_color="#dbeafe")

    def build_quick_page(self) -> None:
        page = self.make_page("quick")
        self.status_card(page, 0)
        self.channel_card(page, 1)
        self.feishu_card(page, 2)
        self.wechat_card(page, 3)
        self.nga_card(page, 4)
        self.listen_rule_card(page, 5)
        self.actions_card(page, 6)
        self.path_card(page, 7)
        self.update_channel_visibility()

    def build_feishu_page(self) -> None:
        page = self.make_page("feishu")
        self.page_title(page, "消息通道配置", "维护飞书或微信机器人配置组；具体发送位置在监听规则和 AI 定时分析中直接选择。", 0)
        self.channel_card(page, 1)
        self.feishu_card(page, 2)
        self.wechat_card(page, 3)
        self.path_card(page, 4)
        self.update_channel_visibility()

    def build_nga_page(self) -> None:
        page = self.make_page("nga")
        self.page_title(page, "NGA 配置", "维护 NGA 资源库和监听规则；新用户只需要先配好 Cookie、用户/帖子和监听规则。", 0)
        self.nga_card(page, 1)
        self.listen_rule_card(page, 2)
        self.path_card(page, 3)

    def build_ai_page(self) -> None:
        page = self.make_page("ai")
        self.page_title(page, "AI 分析", "可选本地 Agent 增强；默认关闭，不影响原有监听和飞书推送。", 0)
        self.ai_card(page, 1)
        self.path_card(page, 2)

    def build_log_page(self) -> None:
        page = self.make_page("log", scroll=False)
        page.grid_rowconfigure(1, weight=1)
        self.page_title(page, "运行日志", "监听进程、查询、初始化和测试消息都会显示在这里。", 0)
        frame = self.card(page, 1, compact=True)
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        self.log_text = ctk.CTkTextbox(
            frame,
            fg_color="#0f172a",
            text_color="#dbeafe",
            border_width=0,
            corner_radius=12,
            font=ctk.CTkFont(family="Consolas", size=12),
            wrap="word",
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)
        self.log_text.configure(state="disabled")

    def build_settings_page(self) -> None:
        page = self.make_page("settings")
        self.page_title(page, "运行设置", "轮询、重试、超时和状态文件位置。相对路径会保存到 AppData 数据目录。", 0)
        frame = self.card(page, 1)
        frame.grid_columnconfigure(1, weight=1)
        fields = [
            ("轮询间隔（秒）", "interval"),
            ("用户回复随机抖动（秒）", "jitter"),
            ("重试次数", "retries"),
            ("重试初始等待（秒）", "retry_initial_delay"),
            ("重试递增步长（秒）", "retry_delay"),
            ("NGA 请求最小间隔（秒）", "nga_request_min_interval"),
            ("NGA 短缓存（秒）", "nga_cache_ttl"),
            ("帖内扫描间隔（秒）", "thread_watch_interval"),
            ("多用户最小间隔（秒）", "nga_target_min_delay"),
            ("多用户最大间隔（秒）", "nga_target_max_delay"),
            ("503 退避起始（秒）", "nga_unavailable_backoff_base"),
            ("503 退避上限（秒）", "nga_unavailable_backoff_max"),
            ("请求超时（秒）", "timeout"),
            ("状态文件名", "state_path"),
        ]
        for row, (label, key) in enumerate(fields):
            self.add_entry(frame, label, key, row)
        ctk.CTkCheckBox(
            frame,
            text="首次启动前自动初始化已读，避免历史回复刷屏",
            variable=self.auto_init_var,
            text_color=TEXT,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            border_color="#cbd5e1",
        ).grid(row=len(fields), column=1, sticky="w", padx=(0, 16), pady=(12, 16))
        self.quiet_hours_card(page, 2)
        self.path_card(page, 3)

    def quiet_hours_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_columnconfigure(2, weight=1)
        frame.grid_columnconfigure(3, weight=1)
        header = ctk.CTkFrame(frame, fg_color="transparent")
        header.grid(row=0, column=0, columnspan=4, sticky="ew", padx=16, pady=(14, 4))
        header.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            header,
            text="免打扰时段",
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")
        help_label = ctk.CTkLabel(
            header,
            text="?",
            width=22,
            height=22,
            corner_radius=11,
            fg_color="#e0e7ff",
            text_color=PRIMARY,
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        help_label.grid(row=0, column=2, sticky="e")
        HoverTooltip(
            help_label,
            "忽略新回复：免打扰时段内仍会监听并标记已读，免打扰结束后不会补发。\n\n"
            "暂存并汇总推送：免打扰时段内的新回复会先暂存，免打扰结束后发送一张汇总卡片。\n\n"
            "示例：周五 18:00 到周一 08:00，会覆盖周五晚上、周六、周日和周一早上。",
        )
        ctk.CTkLabel(
            frame,
            text="设置一个连续免打扰区间。区间内不会向飞书推送自动监听的新回复，手动查询和打包不受影响。",
            anchor="w",
            justify="left",
            wraplength=640,
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=1, column=0, columnspan=4, sticky="ew", padx=16, pady=(0, 10))
        ctk.CTkSwitch(
            frame,
            text="启用免打扰时段",
            variable=self.quiet_enabled_var,
            fg_color="#cbd5e1",
            progress_color=PRIMARY,
            button_color="#ffffff",
            text_color=TEXT,
        ).grid(row=2, column=0, columnspan=4, sticky="w", padx=16, pady=(2, 12))

        ctk.CTkLabel(frame, text="开始", anchor="w", text_color=TEXT).grid(row=3, column=0, sticky="w", padx=16, pady=(6, 8))
        start_frame = ctk.CTkFrame(frame, fg_color="transparent")
        start_frame.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=(0, 8))
        start_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkOptionMenu(
            start_frame,
            values=WEEKDAY_LABELS,
            variable=self.quiet_start_day_var,
            width=112,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.time_select(start_frame, self.quiet_start_hour_var, self.quiet_start_minute_var).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(frame, text="结束", anchor="w", text_color=TEXT).grid(row=4, column=0, sticky="w", padx=16, pady=(6, 8))
        end_frame = ctk.CTkFrame(frame, fg_color="transparent")
        end_frame.grid(row=4, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=(0, 8))
        end_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkOptionMenu(
            end_frame,
            values=WEEKDAY_LABELS,
            variable=self.quiet_end_day_var,
            width=112,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.time_select(end_frame, self.quiet_end_hour_var, self.quiet_end_minute_var).grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(
            frame,
            text="例：周五 18:00 → 周一 08:00",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=5, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=(0, 8))

        ctk.CTkLabel(frame, text="免打扰期间的新回复", anchor="w", text_color=TEXT).grid(
            row=6, column=0, sticky="nw", padx=16, pady=(8, 16)
        )
        policy_frame = ctk.CTkFrame(frame, fg_color="transparent")
        policy_frame.grid(row=6, column=1, columnspan=3, sticky="ew", padx=(0, 16), pady=(2, 16))
        ctk.CTkRadioButton(
            policy_frame,
            text="忽略新回复",
            value="ignore",
            variable=self.quiet_policy_var,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=(0, 18), pady=5)
        ctk.CTkRadioButton(
            policy_frame,
            text="暂存并在免打扰结束后汇总推送",
            value="defer",
            variable=self.quiet_policy_var,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            text_color=TEXT,
        ).grid(row=0, column=1, sticky="w", pady=5)

    def time_select(self, parent: ctk.CTkFrame, hour_var: StringVar, minute_var: StringVar) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        ctk.CTkOptionMenu(
            frame,
            values=HOUR_OPTIONS,
            variable=hour_var,
            width=76,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(frame, text=":", text_color=MUTED, width=18).grid(row=0, column=1)
        self.minute_button(frame, minute_var).grid(row=0, column=2, sticky="w")
        return frame

    def minute_button(self, parent: ctk.CTkFrame, minute_var: StringVar) -> ctk.CTkButton:
        button = ctk.CTkButton(
            parent,
            text=minute_var.get(),
            width=76,
            height=34,
            corner_radius=8,
            fg_color="#f8fafc",
            hover_color="#e2e8f0",
            text_color=TEXT,
            border_width=1,
            border_color=BORDER,
            command=lambda: self.open_minute_picker(button, minute_var),
        )
        minute_var.trace_add("write", lambda *_args: button.configure(text=minute_var.get()))
        return button

    def open_minute_picker(self, anchor: ctk.CTkButton, minute_var: StringVar) -> None:
        if self.minute_picker is not None:
            try:
                self.minute_picker.destroy()
            except Exception:
                pass
            self.minute_picker = None
            return
        picker = ctk.CTkToplevel(self.root)
        self.minute_picker = picker
        picker.overrideredirect(True)
        picker.attributes("-topmost", True)
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        picker.geometry(f"+{x}+{y}")
        panel = ctk.CTkFrame(picker, fg_color="#ffffff", corner_radius=12, border_width=1, border_color=BORDER)
        panel.grid(row=0, column=0, padx=1, pady=1)

        def close_picker() -> None:
            if self.minute_picker is picker:
                self.minute_picker = None
            try:
                picker.destroy()
            except Exception:
                pass

        def choose(value: str) -> None:
            minute_var.set(value)
            close_picker()

        current = minute_var.get()
        for index, value in enumerate(MINUTE_OPTIONS):
            selected = value == current
            ctk.CTkButton(
                panel,
                text=value,
                width=42,
                height=28,
                corner_radius=7,
                fg_color=PRIMARY if selected else "#f8fafc",
                hover_color=PRIMARY_HOVER if selected else "#e2e8f0",
                text_color="#ffffff" if selected else TEXT,
                command=lambda v=value: choose(v),
            ).grid(row=index // 10, column=index % 10, padx=3, pady=3)
        picker.bind("<Escape>", lambda _event: close_picker())
        picker.bind("<FocusOut>", lambda _event: self.root.after(120, close_picker))
        picker.protocol("WM_DELETE_WINDOW", close_picker)
        picker.focus_force()

    def page_title(self, parent: ctk.CTkFrame, title: str, subtitle: str, row: int) -> None:
        header = ctk.CTkFrame(parent, fg_color="transparent")
        header.grid(row=row, column=0, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(
            header,
            text=title,
            anchor="w",
            font=ctk.CTkFont(family="Segoe UI", size=23, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="ew")
        ctk.CTkLabel(
            header,
            text=subtitle,
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        ).grid(row=1, column=0, sticky="ew", pady=(3, 0))

    def card(self, parent: ctk.CTkFrame, row: int, *, compact: bool = False) -> ctk.CTkFrame:
        frame = ctk.CTkFrame(parent, fg_color=CARD, corner_radius=14, border_width=1, border_color=BORDER)
        frame.grid(row=row, column=0, sticky="nsew" if compact else "ew", pady=(0, 12))
        return frame

    def card_title(self, parent: ctk.CTkFrame, title: str, row: int = 0) -> None:
        ctk.CTkLabel(
            parent,
            text=title,
            anchor="w",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=TEXT,
        ).grid(row=row, column=0, columnspan=4, sticky="ew", padx=16, pady=(14, 6))

    def status_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        self.status_dot = ctk.CTkLabel(frame, text="", width=28, height=28, corner_radius=14, fg_color="#e2e8f0")
        self.status_dot.grid(row=0, column=0, rowspan=2, padx=(20, 14), pady=20)
        ctk.CTkLabel(
            frame,
            text="运行状态",
            anchor="w",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=TEXT,
        ).grid(row=0, column=1, sticky="sw", pady=(18, 0))
        self.status_badge = ctk.CTkLabel(
            frame,
            textvariable=self.status_var,
            width=118,
            height=30,
            corner_radius=15,
            fg_color="#f1f5f9",
            text_color="#334155",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.status_badge.grid(row=0, column=2, sticky="e", padx=(8, 16), pady=(16, 4))
        ctk.CTkLabel(
            frame,
            textvariable=self.status_detail_var,
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=MUTED,
        ).grid(row=1, column=1, columnspan=2, sticky="nw", pady=(2, 18))
        self.start_button = ctk.CTkButton(
            frame,
            text="▶ 启动监听",
            width=118,
            height=34,
            corner_radius=10,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            command=self.start_clicked,
        )
        self.start_button.grid(row=0, column=3, sticky="e", padx=(0, 16), pady=(16, 4))
        self.stop_button = ctk.CTkButton(
            frame,
            text="■ 停止监听",
            width=118,
            height=34,
            corner_radius=10,
            fg_color="#eef2f7",
            hover_color="#e2e8f0",
            text_color="#64748b",
            command=self.stop_clicked,
        )
        self.stop_button.grid(row=1, column=3, sticky="e", padx=(0, 16), pady=(4, 16))
        self.update_status_style()

    def channel_card(self, parent: ctk.CTkFrame, row: int) -> ctk.CTkFrame:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "消息通道")
        ctk.CTkLabel(frame, text="当前通道", anchor="w", text_color=TEXT).grid(row=1, column=0, sticky="w", padx=16, pady=(6, 8))
        ctk.CTkOptionMenu(
            frame,
            variable=self.channel_label_var,
            values=["飞书", "微信"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
            command=self.channel_changed,
        ).grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
        ctk.CTkLabel(
            frame,
            text="下拉只控制当前展示和默认消息入口；监听规则和 AI 定时分析可以分别选择飞书群或微信账号。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))
        return frame

    def channel_changed(self, label: str) -> None:
        channel = route_channel_value(label) or "feishu"
        self.vars["bot_channel"].set(channel)
        self.update_channel_visibility()

    def update_channel_visibility(self) -> None:
        if not hasattr(self, "feishu_frames"):
            return
        channel = self.vars["bot_channel"].get() if "bot_channel" in self.vars else "feishu"
        channel = channel if channel in {"feishu", "wechat"} else "feishu"
        if hasattr(self, "channel_label_var") and self.channel_label_var.get() != route_channel_label(channel):
            self.channel_label_var.set(route_channel_label(channel))
        for frame in self.feishu_frames:
            if channel == "feishu":
                frame.grid()
            else:
                frame.grid_remove()
        for frame in self.wechat_frames:
            if channel == "wechat":
                frame.grid()
            else:
                frame.grid_remove()

    def feishu_card(self, parent: ctk.CTkFrame, row: int) -> ctk.CTkFrame:
        frame = self.card(parent, row)
        self.feishu_frames.append(frame)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "飞书机器人配置组")
        self.add_profile_list_editor(frame, "配置组", "feishu", 1)
        ctk.CTkLabel(
            frame,
            text="飞书 App ID、App Secret、查询群组和测试消息都在配置组编辑弹窗里处理。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 8))
        ctk.CTkLabel(
            frame,
            text="已缓存群组",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=3, column=0, sticky="nw", padx=16, pady=(8, 16))
        result_frame = ctk.CTkFrame(frame, fg_color="#f8fafc", corner_radius=10, border_width=1, border_color=BORDER)
        result_frame.grid(row=3, column=1, sticky="ew", padx=(0, 16), pady=(8, 16))
        result_frame.grid_columnconfigure(0, weight=1)
        self.chat_result_frames.append(result_frame)
        self.render_chat_results([])
        return frame

    def wechat_card(self, parent: ctk.CTkFrame, row: int) -> ctk.CTkFrame:
        frame = self.card(parent, row)
        self.wechat_frames.append(frame)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "微信机器人配置组")
        self.add_profile_list_editor(frame, "配置组", "wechat", 1)
        bind_row = ctk.CTkFrame(frame, fg_color="transparent")
        bind_row.grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 8))
        bind_row.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            bind_row,
            text="扫码绑定",
            width=112,
            height=34,
            corner_radius=10,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            command=self.wechat_scan_bind_clicked,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            bind_row,
            text="自动打开二维码链接；手机微信确认后会回填 Token 和用户 ID。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, sticky="ew", padx=(10, 0))
        ctk.CTkLabel(
            frame,
            text="首次使用请先用目标微信给机器人发一条消息，程序拿到 context_token 后才能主动推送。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=3, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 16))
        return frame

    def push_target_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "发送目标")
        ctk.CTkLabel(frame, text="目标列表", anchor="w", text_color=TEXT).grid(row=1, column=0, sticky="nw", padx=16, pady=(8, 16))
        container = ctk.CTkFrame(frame, fg_color="transparent")
        container.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(8, 16))
        container.grid_columnconfigure(0, weight=1)
        listbox = Listbox(
            container,
            height=4,
            selectmode=SINGLE,
            exportselection=False,
            activestyle="dotbox",
            bg="#f8fafc",
            fg=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            relief="flat",
        )
        listbox.grid(row=0, column=0, sticky="ew")
        listbox.bind("<<ListboxSelect>>", lambda event: self.push_target_listbox_selected(event.widget))
        listbox.bind("<Double-Button-1>", self.push_target_listbox_double_clicked)
        buttons = ctk.CTkFrame(container, fg_color="transparent")
        buttons.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ctk.CTkButton(buttons, text="+", width=34, height=30, corner_radius=8, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=self.push_target_add_clicked).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(buttons, text="-", width=34, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=lambda source=listbox: self.push_target_delete_clicked(source)).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(buttons, text="编辑", width=48, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=lambda source=listbox: self.push_target_edit_current_clicked(source)).grid(row=2, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(buttons, text="导入", width=48, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=self.import_cached_feishu_chats_as_push_targets).grid(row=3, column=0, sticky="ew")
        self.push_target_listboxes.append(listbox)
        self.refresh_push_target_list()
        ctk.CTkLabel(
            frame,
            text="发送目标是“某个机器人 + 某个群/微信用户”。监听规则和 AI 定时分析都从这里选择发送位置。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))

    def listen_rule_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "监听规则")
        ctk.CTkLabel(frame, text="规则列表", anchor="w", text_color=TEXT).grid(row=1, column=0, sticky="nw", padx=16, pady=(8, 16))
        container = ctk.CTkFrame(frame, fg_color="transparent")
        container.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(8, 16))
        container.grid_columnconfigure(0, weight=1)
        listbox = Listbox(
            container,
            height=5,
            selectmode=SINGLE,
            exportselection=False,
            activestyle="dotbox",
            bg="#f8fafc",
            fg=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            relief="flat",
        )
        listbox.grid(row=0, column=0, sticky="ew")
        listbox.bind("<<ListboxSelect>>", lambda event: self.listen_rule_listbox_selected(event.widget))
        listbox.bind("<Double-Button-1>", self.listen_rule_listbox_double_clicked)
        buttons = ctk.CTkFrame(container, fg_color="transparent")
        buttons.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ctk.CTkButton(buttons, text="+", width=34, height=30, corner_radius=8, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=self.listen_rule_add_clicked).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(buttons, text="-", width=34, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=lambda source=listbox: self.listen_rule_delete_clicked(source)).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(buttons, text="编辑", width=48, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=lambda source=listbox: self.listen_rule_edit_current_clicked(source)).grid(row=2, column=0, sticky="ew")
        self.listen_rule_listboxes.append(listbox)
        self.refresh_listen_rule_list()
        ctk.CTkLabel(
            frame,
            text="监听规则直接选择发送通道：飞书选择机器人配置和群，微信选择机器人配置。手动查询不受规则限制。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))

    def nga_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "NGA 配置")
        ctk.CTkLabel(frame, text="NGA Cookie", anchor="nw", text_color=TEXT).grid(row=1, column=0, sticky="nw", padx=16, pady=(7, 8))
        cookie_box = ctk.CTkTextbox(
            frame,
            height=70,
            corner_radius=10,
            fg_color="#f8fafc",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(size=12),
        )
        cookie_box.grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
        cookie_box.insert("1.0", str(self.config.get("nga_cookie") or ""))
        cookie_box.bind("<KeyRelease>", lambda _event, box=cookie_box: self.sync_cookie_boxes(box))
        self.cookie_textboxes.append(cookie_box)
        self.add_target_list_editor(frame, "用户 ID 列表", "watch_author_ids", 2, fallback_key="default_author_id")
        self.add_target_list_editor(frame, "帖子预设 ID 列表", "preset_thread_ids", 3, fallback_key="default_tid")
        self.add_entry(frame, "帖内扫描条数", "thread_watch_tail_count", 4)
        self.add_entry(frame, "帖内扫描间隔（秒）", "thread_watch_interval", 5, bottom=True)
        ctk.CTkLabel(
            frame,
            text="这里是可复用的 NGA 资源库。监听方式和发送位置在“监听规则”里直接配置。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=6, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 16))

    def actions_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(0, weight=1)
        self.card_title(frame, "功能操作")
        self.action_tile(frame, 1, 0, "初始化已读", "避免历史刷屏", self.mark_seen_clicked)
        feedback = ctk.CTkFrame(frame, fg_color="#f8fafc", corner_radius=10, border_width=1, border_color=BORDER)
        feedback.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        feedback.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            feedback,
            text="状态",
            width=42,
            height=28,
            corner_radius=8,
            fg_color="#eef2ff",
            text_color=PRIMARY,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=10)
        ctk.CTkLabel(
            feedback,
            textvariable=self.action_feedback_var,
            anchor="w",
            text_color="#475569",
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=1, sticky="ew", padx=(0, 10), pady=10)

    def action_tile(
        self,
        parent: ctk.CTkFrame,
        row: int,
        column: int,
        title: str,
        subtitle: str,
        command: Callable[[], object],
    ) -> None:
        tile = ctk.CTkButton(
            parent,
            text=f"{title}\n{subtitle}",
            height=58,
            corner_radius=10,
            fg_color=CARD_ALT,
            hover_color="#eef2f7",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
            font=ctk.CTkFont(size=12),
            command=command,
        )
        tile.grid(row=row, column=column, sticky="ew", padx=(16 if column == 0 else 6, 16 if column == 3 else 6), pady=(4, 16))

    def ai_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "本地 AI Agent")
        ctk.CTkSwitch(
            frame,
            text="启用 AI 分析",
            variable=self.ai_enabled_var,
            fg_color="#cbd5e1",
            progress_color=PRIMARY,
            button_color="#ffffff",
            text_color=TEXT,
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 8))
        ctk.CTkSwitch(
            frame,
            text="新帖自动分析",
            variable=self.ai_auto_var,
            fg_color="#cbd5e1",
            progress_color=PRIMARY,
            button_color="#ffffff",
            text_color=TEXT,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 8))
        ctk.CTkLabel(frame, text="Provider", anchor="w", text_color=TEXT).grid(row=3, column=0, sticky="w", padx=16, pady=(6, 8))
        ctk.CTkOptionMenu(
            frame,
            variable=self.vars["ai_provider"],
            values=["codex", "claude", "codewhale", "custom"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
            command=lambda _value: self.update_ai_model_controls(),
        ).grid(row=3, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
        ctk.CTkLabel(frame, text="默认模型", anchor="w", text_color=TEXT).grid(row=4, column=0, sticky="w", padx=16, pady=(6, 8))
        self.ai_model_menu = ctk.CTkOptionMenu(
            frame,
            variable=self.vars["ai_model"],
            values=["default"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        )
        self.ai_model_entry = ctk.CTkEntry(
            frame,
            textvariable=self.vars["ai_model"],
            height=34,
            corner_radius=10,
            fg_color="#f8fafc",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        )
        ctk.CTkLabel(frame, text="默认思考强度", anchor="w", text_color=TEXT).grid(row=5, column=0, sticky="w", padx=16, pady=(6, 8))
        self.ai_reasoning_menu = ctk.CTkOptionMenu(
            frame,
            variable=self.vars["ai_reasoning_effort"],
            values=["default"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        )
        self.ai_reasoning_entry = ctk.CTkEntry(
            frame,
            textvariable=self.vars["ai_reasoning_effort"],
            height=34,
            corner_radius=10,
            fg_color="#f8fafc",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        )
        self.update_ai_model_controls()
        fields = [
            ("自动分析 Prompt", "ai_auto_analysis_prompt"),
            ("AI 工作目录", "ai_work_dir"),
            ("AI 超时(秒)", "ai_timeout"),
            ("Codex 命令", "ai_codex_command"),
            ("Claude 命令", "ai_claude_command"),
            ("CodeWhale 命令", "ai_codewhale_command"),
            ("Custom 命令模板", "ai_custom_command"),
            ("定时间隔(分钟)", "ai_schedule_interval_minutes"),
            ("定时 Prompt", "ai_schedule_prompt"),
            ("允许用户 ID", "ai_allowed_user_ids"),
            ("飞书最大字符", "ai_max_feishu_chars"),
        ]
        for offset, (label, key) in enumerate(fields, start=6):
            self.add_entry(frame, label, key, offset)
        window_row = 6 + len(fields)
        ctk.CTkLabel(frame, text="定时窗口", anchor="w", text_color=TEXT).grid(row=window_row, column=0, sticky="w", padx=16, pady=(6, 8))
        window_frame = ctk.CTkFrame(frame, fg_color="transparent")
        window_frame.grid(row=window_row, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
        window_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkOptionMenu(
            window_frame,
            variable=self.ai_schedule_window_mode_var,
            values=["A股开市时间", "自定义"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        ctk.CTkEntry(
            window_frame,
            textvariable=self.vars["ai_schedule_windows"],
            height=34,
            corner_radius=10,
            fg_color="#f8fafc",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        ).grid(row=0, column=1, sticky="ew")
        target_row = window_row + 1
        ctk.CTkLabel(frame, text="定时发送目标", anchor="w", text_color=TEXT).grid(row=target_row, column=0, sticky="nw", padx=16, pady=(6, 8))
        schedule_target_frame = ctk.CTkFrame(
            frame,
            bg_color="#f8fafc",
            fg_color="#f8fafc",
            corner_radius=10,
            border_width=1,
            border_color=BORDER,
        )
        schedule_target_frame.grid(row=target_row, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
        schedule_target_frame.grid_columnconfigure(0, weight=1)
        self.ai_schedule_target_frames.append(schedule_target_frame)
        self.refresh_ai_schedule_target_list()
        target_button_row = target_row + 1
        target_buttons = ctk.CTkFrame(frame, fg_color="transparent")
        target_buttons.grid(row=target_button_row, column=1, sticky="w", padx=(0, 16), pady=(0, 8))
        ctk.CTkButton(target_buttons, text="+", width=42, height=30, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color="#ffffff", command=self.ai_schedule_add_target_clicked).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(target_buttons, text="-", width=42, height=30, fg_color="#eef2ff", hover_color="#dbeafe", text_color=PRIMARY, command=self.ai_schedule_remove_selected_target).grid(row=0, column=1)
        switch_row = window_row + 3
        ctk.CTkSwitch(
            frame,
            text="启用定时分析",
            variable=self.ai_schedule_var,
            fg_color="#cbd5e1",
            progress_color=PRIMARY,
            button_color="#ffffff",
            text_color=TEXT,
        ).grid(row=switch_row, column=0, columnspan=2, sticky="w", padx=16, pady=(8, 6))
        ctk.CTkSwitch(
            frame,
            text="错误发送到飞书",
            variable=self.ai_send_errors_var,
            fg_color="#cbd5e1",
            progress_color=PRIMARY,
            button_color="#ffffff",
            text_color=TEXT,
        ).grid(row=switch_row + 1, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 6))
        ctk.CTkSwitch(
            frame,
            text="长结果上传文件",
            variable=self.ai_upload_long_result_var,
            fg_color="#cbd5e1",
            progress_color=PRIMARY,
            button_color="#ffffff",
            text_color=TEXT,
        ).grid(row=switch_row + 2, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 16))

    def update_ai_model_controls(self) -> None:
        provider = str(self.vars.get("ai_provider").get() if "ai_provider" in self.vars else "codex").strip().lower()
        if provider in {"codex", "claude", "codewhale"}:
            model_values = ["default", "auto", *ai_analysis.model_options(provider)]
            reasoning_values = ["default", *ai_analysis.reasoning_effort_options(provider)]
            if self.ai_model_menu is not None:
                self.ai_model_menu.configure(values=model_values)
                self.ai_model_menu.grid(row=4, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
            if self.ai_model_entry is not None:
                self.ai_model_entry.grid_forget()
            if self.ai_reasoning_menu is not None:
                self.ai_reasoning_menu.configure(values=reasoning_values)
                self.ai_reasoning_menu.grid(row=5, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
            if self.ai_reasoning_entry is not None:
                self.ai_reasoning_entry.grid_forget()
            if not self.vars["ai_model"].get().strip() or self.vars["ai_model"].get().strip() not in model_values:
                self.vars["ai_model"].set("default")
            if not self.vars["ai_reasoning_effort"].get().strip() or self.vars["ai_reasoning_effort"].get().strip() not in reasoning_values:
                self.vars["ai_reasoning_effort"].set("default")
            return

        if self.ai_model_menu is not None:
            self.ai_model_menu.grid_forget()
        if self.ai_reasoning_menu is not None:
            self.ai_reasoning_menu.grid_forget()
        if self.ai_model_entry is not None:
            self.ai_model_entry.grid(row=4, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
        if self.ai_reasoning_entry is not None:
            self.ai_reasoning_entry.grid(row=5, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))

    def path_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            frame,
            text="配置文件位置",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=0, column=0, sticky="w", padx=16, pady=14)
        ctk.CTkEntry(
            frame,
            textvariable=self.path_var,
            height=32,
            corner_radius=10,
            fg_color="#f8fafc",
            border_width=1,
            border_color=BORDER,
            text_color="#475569",
            state="disabled",
        ).grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=14)

    def add_entry(
        self,
        parent: ctk.CTkFrame,
        label: str,
        key: str,
        row: int,
        *,
        show: str | None = None,
        bottom: bool = False,
    ) -> None:
        pady = (6, 16) if bottom else (6, 8)
        ctk.CTkLabel(parent, text=label, anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="w", padx=16, pady=pady)
        ctk.CTkEntry(
            parent,
            textvariable=self.vars[key],
            show=show,
            height=34,
            corner_radius=10,
            fg_color="#f8fafc",
            border_width=1,
            border_color=BORDER,
            text_color=TEXT,
        ).grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=pady)

    def add_target_list_editor(
        self,
        parent: ctk.CTkFrame,
        label: str,
        key: str,
        row: int,
        *,
        fallback_key: str = "",
        bottom: bool = False,
    ) -> None:
        pady = (6, 16) if bottom else (6, 8)
        ctk.CTkLabel(parent, text=label, anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="nw", padx=16, pady=pady)
        if key not in self.target_lists:
            fallback = str(self.config.get(fallback_key) or "").strip() if fallback_key else ""
            self.target_lists[key] = list(nga_feishu_watch.parse_target_list(self.config.get(key), fallback))

        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=pady)
        container.grid_columnconfigure(0, weight=1)

        listbox = Listbox(
            container,
            height=4,
            selectmode=SINGLE,
            exportselection=False,
            activestyle="dotbox",
            bg="#f8fafc",
            fg=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            relief="flat",
        )
        listbox.grid(row=0, column=0, sticky="ew")
        listbox.bind("<<ListboxSelect>>", lambda event, item_key=key: self.target_listbox_selected(item_key, event.widget))
        listbox.bind("<Double-Button-1>", lambda event, item_key=key: self.target_listbox_double_clicked(item_key, event))

        button_frame = ctk.CTkFrame(container, fg_color="transparent")
        button_frame.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ctk.CTkButton(
            button_frame,
            text="+",
            width=34,
            height=30,
            corner_radius=8,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            command=lambda item_key=key, item_label=label: self.target_add_clicked(item_key, item_label),
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(
            button_frame,
            text="-",
            width=34,
            height=30,
            corner_radius=8,
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color=TEXT,
            command=lambda item_key=key, source=listbox: self.target_delete_clicked(item_key, source),
        ).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(
            button_frame,
            text="编辑",
            width=48,
            height=30,
            corner_radius=8,
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color=TEXT,
            command=lambda item_key=key, source=listbox: self.target_edit_current_clicked(item_key, source),
        ).grid(row=2, column=0, sticky="ew")

        self.target_listboxes.setdefault(key, []).append(listbox)
        if key not in self.selected_target_indices:
            self.selected_target_indices[key] = 0 if self.target_lists[key] else -1
        self.refresh_target_list(key)

    def add_thread_author_watch_editor(self, parent: ctk.CTkFrame, row: int, *, bottom: bool = False) -> None:
        pady = (6, 16) if bottom else (6, 8)
        ctk.CTkLabel(parent, text="帖内作者监听", anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="nw", padx=16, pady=pady)
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=pady)
        container.grid_columnconfigure(0, weight=1)

        listbox = Listbox(
            container,
            height=4,
            selectmode=SINGLE,
            exportselection=False,
            activestyle="dotbox",
            bg="#f8fafc",
            fg=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            relief="flat",
        )
        listbox.grid(row=0, column=0, sticky="ew")
        listbox.bind("<<ListboxSelect>>", lambda event: self.thread_author_listbox_selected(event.widget))
        listbox.bind("<Double-Button-1>", self.thread_author_listbox_double_clicked)

        button_frame = ctk.CTkFrame(container, fg_color="transparent")
        button_frame.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ctk.CTkButton(
            button_frame,
            text="+",
            width=34,
            height=30,
            corner_radius=8,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            command=self.thread_author_add_clicked,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(
            button_frame,
            text="-",
            width=34,
            height=30,
            corner_radius=8,
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color=TEXT,
            command=lambda source=listbox: self.thread_author_delete_clicked(source),
        ).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(
            button_frame,
            text="编辑",
            width=48,
            height=30,
            corner_radius=8,
            fg_color="#e2e8f0",
            hover_color="#cbd5e1",
            text_color=TEXT,
            command=lambda source=listbox: self.thread_author_edit_current_clicked(source),
        ).grid(row=2, column=0, sticky="ew")

        self.thread_author_listboxes.append(listbox)
        self.refresh_thread_author_list()

    def add_profile_list_editor(self, parent: ctk.CTkFrame, title: str, kind: str, row: int) -> None:
        ctk.CTkLabel(parent, text=title, anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="nw", padx=16, pady=(8, 16))
        container = ctk.CTkFrame(parent, fg_color="transparent")
        container.grid(row=row, column=1, sticky="ew", padx=(0, 16), pady=(8, 16))
        container.grid_columnconfigure(0, weight=1)
        listbox = Listbox(
            container,
            height=3,
            selectmode=SINGLE,
            exportselection=False,
            activestyle="dotbox",
            bg="#f8fafc",
            fg=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            relief="flat",
        )
        listbox.grid(row=0, column=0, sticky="ew")
        listbox.bind("<<ListboxSelect>>", lambda event, item_kind=kind: self.profile_listbox_selected(item_kind, event.widget))
        listbox.bind("<Double-Button-1>", lambda event, item_kind=kind: self.profile_listbox_double_clicked(item_kind, event))
        buttons = ctk.CTkFrame(container, fg_color="transparent")
        buttons.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ctk.CTkButton(buttons, text="+", width=34, height=30, corner_radius=8, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=lambda item_kind=kind: self.profile_dialog(item_kind)).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(buttons, text="-", width=34, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=lambda item_kind=kind, source=listbox: self.profile_delete_clicked(item_kind, source)).grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(buttons, text="编辑", width=48, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=lambda item_kind=kind, source=listbox: self.profile_edit_current_clicked(item_kind, source)).grid(row=2, column=0, sticky="ew")
        if kind == "feishu":
            self.feishu_profile_listboxes.append(listbox)
        else:
            self.wechat_profile_listboxes.append(listbox)
        self.refresh_profile_list(kind)

    def profiles_for_kind(self, kind: str) -> list[dict[str, Any]]:
        return self.feishu_profiles if kind == "feishu" else self.wechat_profiles

    def selected_profile_index_for_kind(self, kind: str) -> int:
        return self.selected_feishu_profile_index if kind == "feishu" else self.selected_wechat_profile_index

    def set_selected_profile_index(self, kind: str, index: int) -> None:
        if kind == "feishu":
            self.selected_feishu_profile_index = index
        else:
            self.selected_wechat_profile_index = index

    def refresh_profile_list(self, kind: str) -> None:
        boxes = self.feishu_profile_listboxes if kind == "feishu" else self.wechat_profile_listboxes
        for listbox in boxes:
            self.render_profile_listbox(kind, listbox)

    def render_profile_listbox(self, kind: str, listbox: Listbox) -> None:
        profiles = self.profiles_for_kind(kind)
        selected = self.selected_profile_index_for_kind(kind)
        listbox.delete(0, END)
        if not profiles:
            self.set_selected_profile_index(kind, -1)
            listbox.insert(END, "暂无配置组，点击 + 添加")
            listbox.itemconfig(0, foreground=MUTED)
            listbox.selection_clear(0, END)
            return
        for index, profile in enumerate(profiles, 1):
            suffix = ""
            if kind == "feishu":
                chats = profile.get("chats") if isinstance(profile.get("chats"), list) else []
                suffix = f" / {len(chats)} 个群" if chats else ""
            listbox.insert(END, f"{index}. {profile_label(profile, kind)}{suffix}")
        if selected < 0 or selected >= len(profiles):
            selected = 0
        self.set_selected_profile_index(kind, selected)
        listbox.selection_clear(0, END)
        listbox.selection_set(selected)
        listbox.activate(selected)

    def profile_listbox_selected(self, kind: str, listbox: Listbox | None = None) -> None:
        profiles = self.profiles_for_kind(kind)
        if not profiles:
            self.set_selected_profile_index(kind, -1)
            return
        if listbox is None:
            boxes = self.feishu_profile_listboxes if kind == "feishu" else self.wechat_profile_listboxes
            listbox = next((box for box in boxes if box.curselection()), None)
        if listbox is None or not listbox.curselection():
            return
        index = int(listbox.curselection()[0])
        self.set_selected_profile_index(kind, index if 0 <= index < len(profiles) else -1)
        if kind == "feishu" and 0 <= index < len(profiles):
            chats = profiles[index].get("chats") if isinstance(profiles[index].get("chats"), list) else []
            self.render_chat_results(chats)

    def profile_listbox_double_clicked(self, kind: str, event: object) -> None:
        profiles = self.profiles_for_kind(kind)
        listbox = getattr(event, "widget", None)
        if not profiles or listbox is None:
            return
        index = int(listbox.nearest(int(getattr(event, "y", 0))))
        if 0 <= index < len(profiles):
            self.set_selected_profile_index(kind, index)
            self.profile_dialog(kind, index)

    def profile_edit_current_clicked(self, kind: str, listbox: Listbox | None = None) -> None:
        self.profile_listbox_selected(kind, listbox)
        index = self.selected_profile_index_for_kind(kind)
        if not (0 <= index < len(self.profiles_for_kind(kind))):
            self.set_action_feedback("请先选择一个配置组。")
            return
        self.profile_dialog(kind, index)

    def profile_delete_clicked(self, kind: str, listbox: Listbox | None = None) -> None:
        self.profile_listbox_selected(kind, listbox)
        profiles = self.profiles_for_kind(kind)
        index = self.selected_profile_index_for_kind(kind)
        if not (0 <= index < len(profiles)):
            self.set_action_feedback("请先选择一个配置组。")
            return
        removed_profile_id = str(profiles[index].get("id") or "").strip()
        profiles.pop(index)
        removed_target_ids: set[str] = set()
        if removed_profile_id:
            kept_targets: list[dict[str, Any]] = []
            for target in self.push_targets:
                target_channel = str(target.get("channel") or "feishu")
                if target_channel == kind and str(target.get("profile_id") or "").strip() == removed_profile_id:
                    target_id = str(target.get("id") or "").strip()
                    if target_id:
                        removed_target_ids.add(target_id)
                else:
                    kept_targets.append(target)
            self.push_targets = kept_targets
        if removed_target_ids:
            for rule in self.listen_rules:
                if isinstance(rule.get("target_ids"), list):
                    rule["target_ids"] = [target_id for target_id in rule["target_ids"] if str(target_id) not in removed_target_ids]
            self.ai_schedule_selected_target_ids = [
                target_id for target_id in self.ai_schedule_selected_target_ids if target_id not in removed_target_ids
            ]
        self.set_selected_profile_index(kind, min(index, len(profiles) - 1))
        self.refresh_profile_list(kind)
        self.refresh_push_target_list()
        self.refresh_listen_rule_list()
        self.refresh_ai_schedule_target_list()
        self.mark_dirty()

    def profile_dialog(self, kind: str, edit_index: int | None = None) -> None:
        profiles = self.profiles_for_kind(kind)
        editing = edit_index is not None and 0 <= edit_index < len(profiles)
        current = profiles[edit_index] if editing and edit_index is not None else {}
        window = ctk.CTkToplevel(self.root)
        window.title(("编辑" if editing else "新增") + ("飞书配置组" if kind == "feishu" else "微信配置组"))
        window.geometry("660x560" if kind == "wechat" else "660x520")
        window.transient(self.root)
        window.grab_set()
        window.lift()
        window.grid_columnconfigure(1, weight=1)

        label_var = StringVar(value=str(current.get("label") or ""))
        ctk.CTkLabel(window, text="备注", anchor="w", text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
        ctk.CTkEntry(window, textvariable=label_var, height=34, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER).grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=(18, 6))
        feedback_var = StringVar(value="")
        row = 1
        if kind == "feishu":
            app_id_var = StringVar(value=str(current.get("app_id") or ""))
            app_secret_var = StringVar(value=str(current.get("app_secret") or ""))
            id_type_var = StringVar(value=feishu_id_type_label(str(current.get("id_type") or "chat_id")))
            profile_chats = list(current.get("chats") if isinstance(current.get("chats"), list) else [])
            test_chat_var = StringVar(value=chat_label(profile_chats[0]) if profile_chats else "")
            for label, var, secret in [("App ID", app_id_var, False), ("App Secret", app_secret_var, True)]:
                ctk.CTkLabel(window, text=label, anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="w", padx=18, pady=6)
                ctk.CTkEntry(window, textvariable=var, show="*" if secret else "", height=34, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=6)
                row += 1
            ctk.CTkLabel(window, text="ID 类型", anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="w", padx=18, pady=6)
            ctk.CTkOptionMenu(
                window,
                variable=id_type_var,
                values=list(FEISHU_ID_TYPE_LABELS.values()),
                height=34,
                fg_color="#f8fafc",
                button_color="#e2e8f0",
                button_hover_color="#cbd5e1",
                dropdown_fg_color="#ffffff",
                text_color=TEXT,
            ).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=6)
            row += 1
            ctk.CTkLabel(window, text="测试群", anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="w", padx=18, pady=6)
            test_chat_box = ctk.CTkComboBox(
                window,
                variable=test_chat_var,
                values=[chat_label(chat) for chat in profile_chats if chat_label(chat)] or [""],
                height=34,
                fg_color="#f8fafc",
                button_color="#e2e8f0",
                button_hover_color="#cbd5e1",
                text_color=TEXT,
            )
            test_chat_box.grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=6)
            row += 1

            def make_feishu_profile() -> dict[str, Any] | None:
                app_id = app_id_var.get().strip()
                app_secret = app_secret_var.get().strip()
                if not (app_id and app_secret):
                    feedback_var.set("App ID 和 App Secret 必填。")
                    return None
                profile = dict(current)
                profile.update({"label": label_var.get().strip(), "app_id": app_id, "app_secret": app_secret, "id_type": feishu_id_type_value(id_type_var.get())})
                profile["id"] = ensure_profile_id("feishu", profile)
                profile["chats"] = list(profile_chats)
                return profile

            def save_feishu_profile(profile: dict[str, Any]) -> None:
                nonlocal editing, edit_index, current
                if editing and edit_index is not None:
                    profiles[edit_index] = profile
                    self.selected_feishu_profile_index = edit_index
                else:
                    profiles.append(profile)
                    edit_index = len(profiles) - 1
                    editing = True
                    self.selected_feishu_profile_index = edit_index
                current = profile
                self.refresh_profile_list(kind)
                self.mark_dirty()

            def refresh_test_chats() -> None:
                values = [chat_label(chat) for chat in profile_chats if chat_label(chat)]
                test_chat_box.configure(values=values)
                if values and (not test_chat_var.get().strip() or test_chat_var.get().startswith("<")):
                    test_chat_var.set(values[0])

            def query_chats() -> None:
                profile = make_feishu_profile()
                if profile is None:
                    return
                feedback_var.set("正在查询群组...")

                def worker() -> None:
                    try:
                        chats = nga_feishu_watch.list_feishu_chats(profile["app_id"], profile["app_secret"], int_value(self.config, "timeout", 20))
                        cleaned = nga_feishu_watch.merge_feishu_chats(chats)

                        def apply() -> None:
                            profile_chats.clear()
                            profile_chats.extend(cleaned)
                            profile["chats"] = list(profile_chats)
                            save_feishu_profile(profile)
                            refresh_test_chats()
                            self.render_chat_results(profile_chats)
                            feedback_var.set(f"已查询并保存 {len(profile_chats)} 个群组。")

                        self.root.after(0, apply)
                    except Exception as exc:
                        self.root.after(0, lambda: feedback_var.set(f"查询失败：{exc}"))

                threading.Thread(target=worker, daemon=True).start()

            def test_feishu_profile() -> None:
                profile = make_feishu_profile()
                if profile is None:
                    return
                chat_id = self.chat_id_from_option(profile["id"], test_chat_var.get())
                if not chat_id:
                    chat_id = test_chat_var.get().strip()
                match = re.search(r"\(([^()]+)\)$", chat_id)
                if match:
                    chat_id = match.group(1).strip()
                if not chat_id:
                    feedback_var.set("请先选择或填写测试群 chat_id。")
                    return
                feedback_var.set("正在发送测试消息...")

                def worker() -> None:
                    try:
                        post = nga_feishu_watch.NgaPost(
                            key="profile-test",
                            subject="NGA Wolf Watcher 测试消息",
                            content=f"这是一条来自飞书配置组「{profile_label(profile, 'feishu')}」的测试消息。",
                            url="https://bbs.nga.cn/",
                            post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        )
                        nga_feishu_watch.push_feishu_app_posts(profile["app_id"], profile["app_secret"], chat_id, profile.get("id_type") or "chat_id", [post], "NGA Wolf Watcher 测试消息", int_value(self.config, "timeout", 20), "card")
                        self.root.after(0, lambda: feedback_var.set("测试消息已发送。"))
                    except Exception as exc:
                        self.root.after(0, lambda: feedback_var.set(f"测试失败：{exc}"))

                threading.Thread(target=worker, daemon=True).start()

            action_row = ctk.CTkFrame(window, fg_color="transparent")
            action_row.grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=(4, 6))
            ctk.CTkButton(action_row, text="查询群组并保存", width=130, height=32, fg_color="#eef2ff", hover_color="#dbeafe", text_color=PRIMARY, command=query_chats).grid(row=0, column=0, sticky="w", padx=(0, 8))
            ctk.CTkButton(action_row, text="发送测试消息", width=118, height=32, fg_color="#eef2ff", hover_color="#dbeafe", text_color=PRIMARY, command=test_feishu_profile).grid(row=0, column=1, sticky="w")
            row += 1

            def confirm() -> None:
                profile = make_feishu_profile()
                if profile is None:
                    return
                save_feishu_profile(profile)
                window.destroy()
        else:
            token_var = StringVar(value=str(current.get("token") or ""))
            base_var = StringVar(value=str(current.get("base_url") or "https://ilinkai.weixin.qq.com"))
            cdn_var = StringVar(value=str(current.get("cdn_base_url") or "https://novac2c.cdn.weixin.qq.com/c2c"))
            target_var = StringVar(value=str(current.get("target_user_id") or ""))
            allowed_var = StringVar(value=str(current.get("allowed_user_ids") or ""))
            poll_var = StringVar(value=str(current.get("poll_timeout_ms") or "35000"))
            account_var = StringVar(value=str(current.get("account_id") or "default"))
            route_var = StringVar(value=str(current.get("route_tag") or ""))
            fields = [("Token", token_var, True), ("Base URL", base_var, False), ("CDN Base URL", cdn_var, False), ("目标用户 ID", target_var, False), ("允许用户 ID", allowed_var, False), ("轮询超时(ms)", poll_var, False), ("Account ID", account_var, False), ("Route Tag", route_var, False)]
            for label, var, secret in fields:
                ctk.CTkLabel(window, text=label, anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="w", padx=18, pady=5)
                ctk.CTkEntry(window, textvariable=var, show="*" if secret else "", height=32, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=5)
                row += 1

            def make_wechat_profile() -> dict[str, Any] | None:
                token = token_var.get().strip()
                if not token:
                    feedback_var.set("Token 必填。")
                    return None
                profile = dict(current)
                profile.update({
                    "label": label_var.get().strip(),
                    "token": token,
                    "base_url": base_var.get().strip() or "https://ilinkai.weixin.qq.com",
                    "cdn_base_url": cdn_var.get().strip() or "https://novac2c.cdn.weixin.qq.com/c2c",
                    "target_user_id": target_var.get().strip(),
                    "allowed_user_ids": allowed_var.get().strip(),
                    "poll_timeout_ms": poll_var.get().strip() or "35000",
                    "account_id": account_var.get().strip() or "default",
                    "route_tag": route_var.get().strip(),
                })
                profile["id"] = ensure_profile_id("wechat", profile)
                return profile

            def save_wechat_profile(profile: dict[str, Any]) -> None:
                nonlocal editing, edit_index, current
                if editing and edit_index is not None:
                    profiles[edit_index] = profile
                    self.selected_wechat_profile_index = edit_index
                else:
                    profiles.append(profile)
                    edit_index = len(profiles) - 1
                    editing = True
                    self.selected_wechat_profile_index = edit_index
                current = profile
                self.refresh_profile_list(kind)
                self.mark_dirty()

            def test_wechat_profile() -> None:
                profile = make_wechat_profile()
                if profile is None:
                    return
                if not str(profile.get("target_user_id") or "").strip():
                    feedback_var.set("请先填写目标用户 ID。")
                    return
                feedback_var.set("正在发送测试消息...")

                def worker() -> None:
                    try:
                        args = build_args(self.config)
                        args.bot_channel = "wechat"
                        args.wechat_bot_token = str(profile.get("token") or "")
                        args.wechat_bot_base_url = str(profile.get("base_url") or "https://ilinkai.weixin.qq.com")
                        args.wechat_bot_cdn_base_url = str(profile.get("cdn_base_url") or "https://novac2c.cdn.weixin.qq.com/c2c")
                        args.wechat_bot_target_user_id = str(profile.get("target_user_id") or "")
                        args.wechat_bot_allowed_user_ids = str(profile.get("allowed_user_ids") or "")
                        args.wechat_bot_poll_timeout_ms = int(str(profile.get("poll_timeout_ms") or "35000"))
                        args.wechat_bot_route_tag = str(profile.get("route_tag") or "")
                        args.wechat_bot_account_id = str(profile.get("account_id") or "default")
                        client = nga_feishu_watch.wechat_client_for_args(args)
                        client.refresh_context_tokens(args.wechat_bot_target_user_id, timeout_ms=5000, mark_handled=True)
                        post = nga_feishu_watch.NgaPost(
                            key="profile-test",
                            subject="NGA Wolf Watcher 测试消息",
                            content=f"这是一条来自微信配置组「{profile_label(profile, 'wechat')}」的测试消息。",
                            url="https://bbs.nga.cn/",
                            post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                        )
                        nga_feishu_watch.push_channel_posts(args, [post], "NGA Wolf Watcher 测试消息")
                        self.root.after(0, lambda: feedback_var.set("测试消息已发送。"))
                    except Exception as exc:
                        self.root.after(0, lambda: feedback_var.set(f"测试失败：{exc}"))

                threading.Thread(target=worker, daemon=True).start()

            action_row = ctk.CTkFrame(window, fg_color="transparent")
            action_row.grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=(4, 6))
            ctk.CTkButton(action_row, text="发送测试消息", width=118, height=32, fg_color="#eef2ff", hover_color="#dbeafe", text_color=PRIMARY, command=test_wechat_profile).grid(row=0, column=0, sticky="w")
            row += 1

            def confirm() -> None:
                profile = make_wechat_profile()
                if profile is None:
                    return
                save_wechat_profile(profile)
                window.destroy()

        ctk.CTkLabel(window, textvariable=feedback_var, anchor="w", text_color="#dc2626").grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=(0, 6))
        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=row + 1, column=0, columnspan=2, sticky="e", padx=18, pady=(8, 18))
        ctk.CTkButton(button_row, text="取消", width=82, height=32, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=window.destroy).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(button_row, text="确定", width=82, height=32, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=confirm).grid(row=0, column=1)

    def refresh_target_list(self, key: str) -> None:
        for listbox in self.target_listboxes.get(key, []):
            self.render_target_listbox(key, listbox)

    def render_target_listbox(self, key: str, listbox: Listbox) -> None:
        targets = self.target_lists.get(key, [])
        selected = self.selected_target_indices.get(key, -1)

        listbox.delete(0, END)
        if not targets:
            self.selected_target_indices[key] = -1
            listbox.insert(END, "暂无条目，点击 + 添加")
            listbox.itemconfig(0, foreground=MUTED)
            listbox.selection_clear(0, END)
            listbox.update_idletasks()
            return

        for index, target in enumerate(targets, 1):
            route = ""
            if target.route_channel:
                route = f" -> {target.route_channel}"
                if target.route_profile_id:
                    route += f":{target.route_profile_id}"
                if target.route_receive_id:
                    route += f" / {target.route_receive_id}"
            listbox.insert(END, f"{index}. {nga_feishu_watch.target_display_name(target)}{route}")

        if selected < 0 or selected >= len(targets):
            selected = 0
        self.selected_target_indices[key] = selected
        listbox.selection_clear(0, END)
        listbox.selection_set(selected)
        listbox.activate(selected)
        listbox.see(selected)
        listbox.update_idletasks()

    def target_listbox_selected(self, key: str, listbox: Listbox | None = None) -> None:
        targets = self.target_lists.get(key, [])
        if not targets:
            self.selected_target_indices[key] = -1
            return
        if listbox is None:
            listbox = next((box for box in self.target_listboxes.get(key, []) if box.curselection()), None)
        if listbox is None:
            return
        selection = listbox.curselection()
        if not selection:
            return
        index = int(selection[0])
        if 0 <= index < len(targets):
            self.selected_target_indices[key] = index
        else:
            self.selected_target_indices[key] = -1
            listbox.selection_clear(0, END)

    def target_listbox_double_clicked(self, key: str, event: object) -> None:
        boxes = self.target_listboxes.get(key, [])
        listbox = getattr(event, "widget", None)
        if listbox not in boxes:
            listbox = boxes[0] if boxes else None
        targets = self.target_lists.get(key, [])
        if listbox is None or not targets:
            return
        index = int(listbox.nearest(int(getattr(event, "y", 0))))
        if not (0 <= index < len(targets)):
            return
        self.selected_target_indices[key] = index
        self.refresh_target_list(key)
        self.target_dialog(key, "编辑条目", edit_index=index)

    def target_list_config_text(self, key: str) -> str:
        lines: list[str] = []
        for target in self.target_lists.get(key, []):
            if target.label:
                line = f"{target.id}={target.label}"
            else:
                line = target.id
            if target.route_channel:
                line += f"|channel={target.route_channel}"
            if target.route_profile_id:
                line += f"|bot={target.route_profile_id}"
            if target.route_receive_id:
                line += f"|receive_id={target.route_receive_id}"
            if target.route_id_type and target.route_id_type != "chat_id":
                line += f"|id_type={target.route_id_type}"
            lines.append(line)
        return "\n".join(lines)

    def target_add_clicked(self, key: str, label: str) -> None:
        self.target_dialog(key, label)

    def target_select_clicked(self, key: str, index: int) -> None:
        if not (0 <= index < len(self.target_lists.get(key, []))):
            return
        self.selected_target_indices[key] = index
        self.refresh_target_list(key)

    def target_edit_clicked(self, key: str, index: int) -> None:
        if not (0 <= index < len(self.target_lists.get(key, []))):
            return
        self.selected_target_indices[key] = index
        self.refresh_target_list(key)
        self.target_dialog(key, "编辑条目", edit_index=index)

    def target_edit_current_clicked(self, key: str, listbox: Listbox | None = None) -> None:
        self.target_listbox_selected(key, listbox)
        index = self.selected_target_indices.get(key, -1)
        if not (0 <= index < len(self.target_lists.get(key, []))):
            self.set_action_feedback("请先选中要编辑的条目。")
            return
        self.target_dialog(key, "编辑条目", edit_index=index)

    def target_delete_clicked(self, key: str, listbox: Listbox | None = None) -> None:
        self.target_listbox_selected(key, listbox)
        index = self.selected_target_indices.get(key, -1)
        targets = self.target_lists.get(key, [])
        if not (0 <= index < len(targets)):
            self.set_action_feedback("请先选中要删除的条目。")
            return
        targets.pop(index)
        self.selected_target_indices[key] = min(index, len(targets) - 1)
        self.refresh_target_list(key)
        self.mark_dirty()
        self.set_action_feedback("列表已更新，记得保存配置。")
        self.root.update_idletasks()

    def open_target_add_dialog(self, key: str, label: str) -> None:
        self.target_add_clicked(key, label)

    def open_target_edit_dialog(self, key: str, index: int) -> None:
        self.target_edit_clicked(key, index)

    def remove_selected_target(self, key: str) -> None:
        self.target_delete_clicked(key)

    def profile_option_values(self, kind: str) -> list[str]:
        profiles = self.profiles_for_kind(kind)
        return [profile_label(profile, kind) for profile in profiles] or ["<none>"]

    def profile_id_from_option(self, kind: str, option: str) -> str:
        for profile in self.profiles_for_kind(kind):
            if option == profile_label(profile, kind) or option == str(profile.get("id") or ""):
                return str(profile.get("id") or "").strip()
        return ""

    def profile_by_id(self, kind: str, profile_id: str) -> dict[str, Any] | None:
        target = str(profile_id or "").strip()
        profiles = self.profiles_for_kind(kind)
        if not target and profiles:
            return profiles[0]
        for profile in profiles:
            if target in {str(profile.get("id") or ""), str(profile.get("label") or "")}:
                return profile
        return None

    def profile_option_for_id(self, kind: str, profile_id: str) -> str:
        profile = self.profile_by_id(kind, profile_id)
        if profile:
            return profile_label(profile, kind)
        values = self.profile_option_values(kind)
        return values[0] if values else "<none>"

    def chat_option_values(self, profile_id: str) -> list[str]:
        profile = self.profile_by_id("feishu", profile_id)
        chats = profile.get("chats") if isinstance(profile, dict) and isinstance(profile.get("chats"), list) else []
        return [chat_label(chat) for chat in chats if chat_label(chat)] or ["<no cached chats>"]

    def chat_id_from_option(self, profile_id: str, option: str) -> str:
        profile = self.profile_by_id("feishu", profile_id)
        chats = profile.get("chats") if isinstance(profile, dict) and isinstance(profile.get("chats"), list) else []
        for chat in chats:
            chat_id = str(chat.get("chat_id") or chat.get("id") or "").strip()
            if option == chat_label(chat) or option == chat_id:
                return chat_id
        return "" if option.startswith("<") else option.strip()

    def option_for_chat_id(self, profile_id: str, chat_id: str) -> str:
        chat_id = str(chat_id or "").strip()
        profile = self.profile_by_id("feishu", profile_id)
        chats = profile.get("chats") if isinstance(profile, dict) and isinstance(profile.get("chats"), list) else []
        for chat in chats:
            if chat_id and chat_id == str(chat.get("chat_id") or chat.get("id") or "").strip():
                return chat_label(chat)
        return chat_id or (self.chat_option_values(profile_id)[0])

    def target_choice_values(self, key: str, fallback: str) -> list[str]:
        targets = self.target_lists.get(key)
        if targets is None:
            targets = list(nga_feishu_watch.parse_target_list(self.config.get(key), fallback))
        values = [f"{nga_feishu_watch.target_display_name(target)}" for target in targets]
        return values or ([fallback] if fallback else [])

    def target_id_from_choice(self, key: str, choice: str) -> str:
        text = str(choice or "").strip()
        targets = self.target_lists.get(key, [])
        for target in targets:
            if text in {target.id, nga_feishu_watch.target_display_name(target), f"{target.label}({target.id})"}:
                return target.id
        match = re.search(r"\((\d+)\)$", text)
        return match.group(1) if match else text

    def push_target_option_values(self) -> list[str]:
        return [push_target_label(target) for target in self.push_targets] or ["<暂无发送目标>"]

    def configured_ai_schedule_target_id_list(self) -> list[str]:
        raw = str(self.config.get("ai_schedule_target_ids") or "").strip()
        if raw.lower() in {"__none__", "none", "off"}:
            return []
        if not raw:
            first_target_id = next((str(target.get("id") or "").strip() for target in self.push_targets if str(target.get("id") or "").strip()), "")
            return [first_target_id] if first_target_id else []
        selected: list[str] = []
        for part in re.split(r"[,，;；\s]+", raw):
            target_id = part.strip()
            if target_id and target_id not in selected:
                selected.append(target_id)
        return selected

    def configured_ai_schedule_target_id_set(self) -> set[str]:
        return set(self.configured_ai_schedule_target_id_list())

    def refresh_ai_schedule_target_list(self) -> None:
        valid_target_ids = {str(target.get("id") or "").strip() for target in self.push_targets if str(target.get("id") or "").strip()}
        self.ai_schedule_selected_target_ids = [
            target_id for target_id in self.ai_schedule_selected_target_ids if target_id in valid_target_ids
        ]
        if not self.ai_schedule_selected_target_ids and valid_target_ids and not str(self.config.get("ai_schedule_target_ids") or "").strip():
            first_target_id = next((str(target.get("id") or "").strip() for target in self.push_targets if str(target.get("id") or "").strip()), "")
            if first_target_id:
                self.ai_schedule_selected_target_ids = [first_target_id]
        self.ai_schedule_target_listboxes = []
        for frame in self.ai_schedule_target_frames:
            for child in frame.winfo_children():
                child.destroy()
            listbox = Listbox(
                frame,
                height=4,
                selectmode=SINGLE,
                exportselection=False,
                activestyle="dotbox",
                bg="#f8fafc",
                fg=TEXT,
                selectbackground="#dbeafe",
                selectforeground=TEXT,
                highlightthickness=0,
                relief="flat",
            )
            listbox.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
            if not self.ai_schedule_selected_target_ids:
                listbox.insert(END, "暂无定时发送目标，点击 + 添加")
                listbox.itemconfig(0, foreground=MUTED)
            else:
                for index, target_id in enumerate(self.ai_schedule_selected_target_ids, 1):
                    target = next((item for item in self.push_targets if str(item.get("id") or "") == target_id), None)
                    listbox.insert(END, f"{index}. {push_target_label(target) if target else target_id}")
            self.ai_schedule_target_listboxes.append(listbox)

    def ai_schedule_target_ids(self) -> list[str]:
        if not self.ai_schedule_target_frames:
            return list(self.configured_ai_schedule_target_id_set())
        valid_target_ids = {str(target.get("id") or "").strip() for target in self.push_targets if str(target.get("id") or "").strip()}
        return [target_id for target_id in self.ai_schedule_selected_target_ids if target_id in valid_target_ids]

    def ai_schedule_add_target_clicked(self) -> None:
        self.ai_schedule_target_dialog()

    def ai_schedule_remove_selected_target(self) -> None:
        listbox = next((box for box in self.ai_schedule_target_listboxes if box.curselection()), None)
        if listbox is None or not listbox.curselection() or not self.ai_schedule_selected_target_ids:
            self.set_action_feedback("请先选择一个定时发送目标。")
            return
        index = int(listbox.curselection()[0])
        if 0 <= index < len(self.ai_schedule_selected_target_ids):
            self.ai_schedule_selected_target_ids.pop(index)
            self.refresh_ai_schedule_target_list()
            self.mark_dirty()

    def ensure_route_push_target(self, channel: str, profile_id: str, receive_id: str, label: str) -> str:
        channel = "wechat" if channel == "wechat" else "feishu"
        profile_id = str(profile_id or "").strip()
        receive_id = str(receive_id or "").strip()
        for target in self.push_targets:
            if (
                str(target.get("channel") or "feishu") == channel
                and str(target.get("profile_id") or "").strip() == profile_id
                and str(target.get("receive_id") or "").strip() == receive_id
            ):
                return str(target.get("id") or "").strip()
        profile = self.profile_by_id(channel, profile_id)
        target = {
            "id": nga_feishu_watch.stable_profile_id("target", channel, profile_id, receive_id, label),
            "label": label,
            "channel": channel,
            "profile_id": profile_id,
            "receive_id": receive_id,
            "id_type": str(profile.get("id_type") or "chat_id") if channel == "feishu" and isinstance(profile, dict) else "user_id",
            "default_author_id": self.vars["default_author_id"].get().strip(),
            "default_tid": self.vars["default_tid"].get().strip(),
        }
        self.push_targets.append(target)
        self.selected_push_target_index = len(self.push_targets) - 1
        return str(target["id"])

    def ensure_schedule_push_target(self, channel: str, profile_id: str, receive_id: str, label: str) -> str:
        return self.ensure_route_push_target(channel, profile_id, receive_id, label)

    def route_target_dialog(
        self,
        title: str,
        on_confirm: Callable[[str], None],
        *,
        parent: ctk.CTkToplevel | ctk.CTk | None = None,
    ) -> None:
        default_channel = "feishu" if self.feishu_profiles else "wechat"
        window = ctk.CTkToplevel(self.root)
        window.title(title)
        window.geometry("640x300")
        window.transient(parent or self.root)
        window.grab_set()
        window.lift()
        window.grid_columnconfigure(1, weight=1)

        channel_var = StringVar(value=route_channel_label(default_channel))
        feishu_profile_var = StringVar(value=self.profile_option_for_id("feishu", ""))
        wechat_profile_var = StringVar(value=self.profile_option_for_id("wechat", ""))
        chat_var = StringVar(value=self.option_for_chat_id(self.profile_id_from_option("feishu", feishu_profile_var.get()), ""))
        feedback_var = StringVar(value="")

        ctk.CTkLabel(window, text="通道", anchor="w", text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
        channel_menu = ctk.CTkOptionMenu(
            window,
            variable=channel_var,
            values=["飞书", "微信"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        )
        channel_menu.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=(18, 6))

        feishu_profile_label = ctk.CTkLabel(window, text="飞书机器人", anchor="w", text_color=TEXT)
        feishu_profile_menu = ctk.CTkOptionMenu(
            window,
            variable=feishu_profile_var,
            values=self.profile_option_values("feishu"),
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            dropdown_fg_color="#ffffff",
            text_color=TEXT,
        )
        feishu_chat_label = ctk.CTkLabel(window, text="飞书群", anchor="w", text_color=TEXT)
        chat_box = ctk.CTkComboBox(
            window,
            variable=chat_var,
            values=self.chat_option_values(self.profile_id_from_option("feishu", feishu_profile_var.get())),
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        )
        wechat_profile_label = ctk.CTkLabel(window, text="微信机器人", anchor="w", text_color=TEXT)
        wechat_profile_menu = ctk.CTkOptionMenu(
            window,
            variable=wechat_profile_var,
            values=self.profile_option_values("wechat"),
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            dropdown_fg_color="#ffffff",
            text_color=TEXT,
        )

        def update_chat_options(_value: str | None = None) -> None:
            profile_id = self.profile_id_from_option("feishu", feishu_profile_var.get())
            values = self.chat_option_values(profile_id)
            chat_box.configure(values=values)
            if not chat_var.get().strip() or chat_var.get().startswith("<"):
                chat_var.set(values[0] if values else "")

        def update_channel_fields(_value: str | None = None) -> None:
            for widget in (feishu_profile_label, feishu_profile_menu, feishu_chat_label, chat_box, wechat_profile_label, wechat_profile_menu):
                widget.grid_remove()
            if route_channel_value(channel_var.get()) == "wechat":
                wechat_profile_label.grid(row=1, column=0, sticky="w", padx=18, pady=6)
                wechat_profile_menu.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=6)
            else:
                feishu_profile_label.grid(row=1, column=0, sticky="w", padx=18, pady=6)
                feishu_profile_menu.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=6)
                feishu_chat_label.grid(row=2, column=0, sticky="w", padx=18, pady=6)
                chat_box.grid(row=2, column=1, sticky="ew", padx=(0, 18), pady=6)

        feishu_profile_menu.configure(command=update_chat_options)
        channel_menu.configure(command=update_channel_fields)
        update_channel_fields()

        ctk.CTkLabel(window, textvariable=feedback_var, anchor="w", text_color="#dc2626").grid(row=5, column=1, sticky="ew", padx=(0, 18), pady=(0, 6))

        def confirm() -> None:
            channel = route_channel_value(channel_var.get()) or "feishu"
            if channel == "wechat":
                profile_id = self.profile_id_from_option("wechat", wechat_profile_var.get())
                profile = self.profile_by_id("wechat", profile_id)
                receive_id = str(profile.get("target_user_id") or "").strip() if isinstance(profile, dict) else ""
                if not (profile_id and receive_id):
                    feedback_var.set("请选择已绑定目标用户的微信配置。")
                    return
                label = profile_label(profile, "wechat") if isinstance(profile, dict) else profile_id
            else:
                profile_id = self.profile_id_from_option("feishu", feishu_profile_var.get())
                receive_id = self.chat_id_from_option(profile_id, chat_var.get())
                if not (profile_id and receive_id):
                    feedback_var.set("请选择飞书机器人和飞书群。")
                    return
                label = chat_var.get().strip() or receive_id
            target_id = self.ensure_route_push_target(channel, profile_id, receive_id, label)
            if target_id:
                on_confirm(target_id)
            self.refresh_push_target_list()
            self.refresh_listen_rule_list()
            self.mark_dirty()
            window.destroy()

        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=6, column=0, columnspan=2, sticky="e", padx=18, pady=(8, 18))
        ctk.CTkButton(button_row, text="取消", width=82, height=32, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=window.destroy).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(button_row, text="确认", width=82, height=32, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=confirm).grid(row=0, column=1)

    def ai_schedule_target_dialog(self) -> None:
        def add_target(target_id: str) -> None:
            if target_id and target_id not in self.ai_schedule_selected_target_ids:
                self.ai_schedule_selected_target_ids.append(target_id)
            self.refresh_ai_schedule_target_list()

        self.route_target_dialog("新增定时发送目标", add_target)

    def push_target_id_from_option(self, option: str) -> str:
        text = str(option or "").strip()
        for target in self.push_targets:
            if text in {str(target.get("id") or ""), push_target_label(target), str(target.get("label") or "")}:
                return str(target.get("id") or "").strip()
        return ""

    def push_target_display_text(self, target: dict[str, Any]) -> str:
        return push_target_label(target)

    def import_cached_feishu_chats_as_push_targets(self, select_for_schedule: bool = False) -> None:
        existing_routes = {
            (
                str(target.get("channel") or "feishu"),
                str(target.get("profile_id") or ""),
                str(target.get("receive_id") or ""),
            )
            for target in self.push_targets
        }
        existing_ids = {str(target.get("id") or "") for target in self.push_targets}
        new_target_ids: list[str] = []
        for profile in self.feishu_profiles:
            profile_id = str(profile.get("id") or "").strip()
            chats = profile.get("chats") if isinstance(profile.get("chats"), list) else []
            if not profile_id or not chats:
                continue
            for chat in chats:
                if not isinstance(chat, dict):
                    continue
                chat_id = str(chat.get("chat_id") or chat.get("id") or "").strip()
                if not chat_id or ("feishu", profile_id, chat_id) in existing_routes:
                    continue
                label = str(chat.get("name") or chat.get("title") or "").strip() or chat_id
                target_id = nga_feishu_watch.stable_profile_id("target", "feishu", profile_id, chat_id, label)
                if target_id in existing_ids:
                    target_id = nga_feishu_watch.stable_profile_id("target", "feishu", profile_id, chat_id, label, str(len(existing_ids)))
                existing_ids.add(target_id)
                existing_routes.add(("feishu", profile_id, chat_id))
                self.push_targets.append(
                    {
                        "id": target_id,
                        "label": label,
                        "channel": "feishu",
                        "profile_id": profile_id,
                        "receive_id": chat_id,
                        "id_type": str(profile.get("id_type") or "chat_id") or "chat_id",
                        "default_author_id": self.vars["default_author_id"].get().strip(),
                        "default_tid": self.vars["default_tid"].get().strip(),
                    }
                )
                new_target_ids.append(target_id)
        if not new_target_ids:
            self.set_action_feedback("没有可导入的新飞书群。请先在飞书配置组里查询群组。")
            return
        self.selected_push_target_index = len(self.push_targets) - 1
        self.refresh_push_target_list()
        self.refresh_listen_rule_list()
        if select_for_schedule:
            for target_id in new_target_ids:
                if target_id not in self.ai_schedule_selected_target_ids:
                    self.ai_schedule_selected_target_ids.append(target_id)
            self.refresh_ai_schedule_target_list()
        self.mark_dirty()
        self.set_action_feedback(f"已导入 {len(new_target_ids)} 个飞书群为发送目标。")

    def refresh_push_target_list(self) -> None:
        for listbox in self.push_target_listboxes:
            listbox.delete(0, END)
            if not self.push_targets:
                self.selected_push_target_index = -1
                listbox.insert(END, "暂无发送目标，点击 + 添加")
                listbox.itemconfig(0, foreground=MUTED)
                listbox.selection_clear(0, END)
                continue
            for index, target in enumerate(self.push_targets, 1):
                listbox.insert(END, f"{index}. {self.push_target_display_text(target)}")
            selected = self.selected_push_target_index
            if selected < 0 or selected >= len(self.push_targets):
                selected = 0
            self.selected_push_target_index = selected
            listbox.selection_clear(0, END)
            listbox.selection_set(selected)
            listbox.activate(selected)
        self.refresh_ai_schedule_target_list()

    def push_target_listbox_selected(self, listbox: Listbox | None = None) -> None:
        if not self.push_targets:
            self.selected_push_target_index = -1
            return
        if listbox is None:
            listbox = next((box for box in self.push_target_listboxes if box.curselection()), None)
        if listbox is None or not listbox.curselection():
            return
        index = int(listbox.curselection()[0])
        self.selected_push_target_index = index if 0 <= index < len(self.push_targets) else -1

    def push_target_listbox_double_clicked(self, event: object) -> None:
        listbox = getattr(event, "widget", None)
        if listbox is None or not self.push_targets:
            return
        index = int(listbox.nearest(int(getattr(event, "y", 0))))
        if 0 <= index < len(self.push_targets):
            self.selected_push_target_index = index
            self.push_target_dialog(index)

    def push_target_add_clicked(self) -> None:
        self.push_target_dialog()

    def push_target_edit_current_clicked(self, listbox: Listbox | None = None) -> None:
        self.push_target_listbox_selected(listbox)
        index = self.selected_push_target_index
        if not (0 <= index < len(self.push_targets)):
            self.set_action_feedback("请先选择一个发送目标。")
            return
        self.push_target_dialog(index)

    def push_target_delete_clicked(self, listbox: Listbox | None = None) -> None:
        self.push_target_listbox_selected(listbox)
        index = self.selected_push_target_index
        if not (0 <= index < len(self.push_targets)):
            self.set_action_feedback("请先选择一个发送目标。")
            return
        removed_id = str(self.push_targets[index].get("id") or "")
        self.push_targets.pop(index)
        for rule in self.listen_rules:
            if isinstance(rule.get("target_ids"), list):
                rule["target_ids"] = [target_id for target_id in rule["target_ids"] if target_id != removed_id]
        self.selected_push_target_index = min(index, len(self.push_targets) - 1)
        self.refresh_push_target_list()
        self.refresh_listen_rule_list()
        self.mark_dirty()

    def push_target_dialog(self, edit_index: int | None = None) -> None:
        editing = edit_index is not None and 0 <= edit_index < len(self.push_targets)
        current = self.push_targets[edit_index] if editing and edit_index is not None else {}
        window = ctk.CTkToplevel(self.root)
        window.title(("编辑" if editing else "新增") + "发送目标")
        window.geometry("660x430")
        window.transient(self.root)
        window.grab_set()
        window.lift()
        window.grid_columnconfigure(1, weight=1)

        label_var = StringVar(value=str(current.get("label") or ""))
        current_channel = str(current.get("channel") or "feishu")
        channel_var = StringVar(value=route_channel_label(current_channel))
        feishu_profile_var = StringVar(value=self.profile_option_for_id("feishu", str(current.get("profile_id") or "")))
        wechat_profile_var = StringVar(value=self.profile_option_for_id("wechat", str(current.get("profile_id") or "")))
        receive_var = StringVar(value=str(current.get("receive_id") or ""))
        wechat_user_var = StringVar(value=str(current.get("receive_id") or "") if current_channel == "wechat" else "")
        default_author_var = StringVar(value=str(current.get("default_author_id") or self.vars["default_author_id"].get()))
        default_tid_var = StringVar(value=str(current.get("default_tid") or self.vars["default_tid"].get()))
        chat_choice_var = StringVar(value=self.option_for_chat_id(self.profile_id_from_option("feishu", feishu_profile_var.get()), receive_var.get()))
        feedback_var = StringVar(value="")

        fields = [("备注", label_var), ("默认用户", default_author_var), ("默认帖子", default_tid_var)]
        ctk.CTkLabel(window, text="通道", anchor="w", text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=(18, 6))
        for offset, (label, var) in enumerate(fields, start=1):
            ctk.CTkLabel(window, text=label, anchor="w", text_color=TEXT).grid(row=offset, column=0, sticky="w", padx=18, pady=6)
            ctk.CTkEntry(window, textvariable=var, height=34, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER).grid(row=offset, column=1, sticky="ew", padx=(0, 18), pady=6)

        def update_chat_options(_value: str | None = None) -> None:
            profile_id = self.profile_id_from_option("feishu", feishu_profile_var.get())
            values = self.chat_option_values(profile_id)
            chat_box.configure(values=values)
            if chat_choice_var.get().startswith("<") or not chat_choice_var.get().strip():
                chat_choice_var.set(values[0] if values else "")

        feishu_profile_label = ctk.CTkLabel(window, text="飞书机器人", anchor="w", text_color=TEXT)
        feishu_profile_menu = ctk.CTkOptionMenu(window, variable=feishu_profile_var, values=self.profile_option_values("feishu"), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", dropdown_fg_color="#ffffff", text_color=TEXT, command=update_chat_options)
        feishu_chat_label = ctk.CTkLabel(window, text="飞书群", anchor="w", text_color=TEXT)
        chat_box = ctk.CTkComboBox(window, variable=chat_choice_var, values=self.chat_option_values(self.profile_id_from_option("feishu", feishu_profile_var.get())), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", text_color=TEXT)
        wechat_profile_label = ctk.CTkLabel(window, text="微信机器人", anchor="w", text_color=TEXT)
        wechat_profile_menu = ctk.CTkOptionMenu(window, variable=wechat_profile_var, values=self.profile_option_values("wechat"), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", dropdown_fg_color="#ffffff", text_color=TEXT)
        wechat_user_label = ctk.CTkLabel(window, text="微信用户", anchor="w", text_color=TEXT)
        wechat_user_entry = ctk.CTkEntry(window, textvariable=wechat_user_var, height=34, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER)

        def update_channel_fields(_value: str | None = None) -> None:
            channel = route_channel_value(channel_var.get()) or "feishu"
            for widget in (feishu_profile_label, feishu_profile_menu, feishu_chat_label, chat_box, wechat_profile_label, wechat_profile_menu, wechat_user_label, wechat_user_entry):
                widget.grid_remove()
            if channel == "wechat":
                profile = self.profile_by_id("wechat", self.profile_id_from_option("wechat", wechat_profile_var.get()))
                if not wechat_user_var.get().strip() and isinstance(profile, dict):
                    wechat_user_var.set(str(profile.get("target_user_id") or ""))
                wechat_profile_label.grid(row=4, column=0, sticky="w", padx=18, pady=6)
                wechat_profile_menu.grid(row=4, column=1, sticky="ew", padx=(0, 18), pady=6)
                wechat_user_label.grid(row=5, column=0, sticky="w", padx=18, pady=6)
                wechat_user_entry.grid(row=5, column=1, sticky="ew", padx=(0, 18), pady=6)
            else:
                feishu_profile_label.grid(row=4, column=0, sticky="w", padx=18, pady=6)
                feishu_profile_menu.grid(row=4, column=1, sticky="ew", padx=(0, 18), pady=6)
                feishu_chat_label.grid(row=5, column=0, sticky="w", padx=18, pady=6)
                chat_box.grid(row=5, column=1, sticky="ew", padx=(0, 18), pady=6)

        channel_menu = ctk.CTkOptionMenu(window, variable=channel_var, values=["飞书", "微信"], height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", text_color=TEXT, command=update_channel_fields)
        channel_menu.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=(18, 6))
        wechat_profile_menu.configure(command=update_channel_fields)
        update_channel_fields()
        ctk.CTkLabel(window, textvariable=feedback_var, anchor="w", text_color="#dc2626").grid(row=8, column=1, sticky="ew", padx=(0, 18), pady=(0, 6))

        def confirm() -> None:
            channel = route_channel_value(channel_var.get()) or "feishu"
            profile_id = self.profile_id_from_option(channel, wechat_profile_var.get() if channel == "wechat" else feishu_profile_var.get())
            receive_id = ""
            if channel == "feishu":
                receive_id = self.chat_id_from_option(profile_id, chat_choice_var.get()) or chat_choice_var.get().strip()
                if not (profile_id and receive_id):
                    feedback_var.set("请选择飞书机器人和飞书群。")
                    return
            else:
                profile = self.profile_by_id("wechat", profile_id)
                receive_id = wechat_user_var.get().strip() or (str(profile.get("target_user_id") or "") if isinstance(profile, dict) else "")
                if not (profile_id and receive_id):
                    feedback_var.set("请选择微信机器人并填写微信用户。")
                    return
            target = dict(current)
            target.update(
                {
                    "label": label_var.get().strip(),
                    "channel": channel,
                    "profile_id": profile_id,
                    "receive_id": receive_id,
                    "id_type": "chat_id",
                    "default_author_id": default_author_var.get().strip(),
                    "default_tid": default_tid_var.get().strip(),
                }
            )
            target["id"] = str(target.get("id") or "").strip() or nga_feishu_watch.stable_profile_id("target", channel, profile_id, receive_id, target.get("label", ""))
            if editing and edit_index is not None:
                self.push_targets[edit_index] = target
                self.selected_push_target_index = edit_index
            else:
                self.push_targets.append(target)
                self.selected_push_target_index = len(self.push_targets) - 1
            self.refresh_push_target_list()
            self.refresh_listen_rule_list()
            self.mark_dirty()
            window.destroy()

        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=9, column=0, columnspan=2, sticky="e", padx=18, pady=(8, 18))
        ctk.CTkButton(button_row, text="取消", width=82, height=32, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=window.destroy).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(button_row, text="确认", width=82, height=32, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=confirm).grid(row=0, column=1)

    def listen_rule_display_text(self, rule: dict[str, Any]) -> str:
        return listen_rule_label(rule)

    def refresh_listen_rule_list(self) -> None:
        for listbox in self.listen_rule_listboxes:
            listbox.delete(0, END)
            if not self.listen_rules:
                self.selected_listen_rule_index = -1
                listbox.insert(END, "暂无监听规则，点击 + 添加")
                listbox.itemconfig(0, foreground=MUTED)
                listbox.selection_clear(0, END)
                continue
            for index, rule in enumerate(self.listen_rules, 1):
                listbox.insert(END, f"{index}. {self.listen_rule_display_text(rule)}")
            selected = self.selected_listen_rule_index
            if selected < 0 or selected >= len(self.listen_rules):
                selected = 0
            self.selected_listen_rule_index = selected
            listbox.selection_clear(0, END)
            listbox.selection_set(selected)
            listbox.activate(selected)

    def listen_rule_listbox_selected(self, listbox: Listbox | None = None) -> None:
        if not self.listen_rules:
            self.selected_listen_rule_index = -1
            return
        if listbox is None:
            listbox = next((box for box in self.listen_rule_listboxes if box.curselection()), None)
        if listbox is None or not listbox.curselection():
            return
        index = int(listbox.curselection()[0])
        self.selected_listen_rule_index = index if 0 <= index < len(self.listen_rules) else -1

    def listen_rule_listbox_double_clicked(self, event: object) -> None:
        listbox = getattr(event, "widget", None)
        if listbox is None or not self.listen_rules:
            return
        index = int(listbox.nearest(int(getattr(event, "y", 0))))
        if 0 <= index < len(self.listen_rules):
            self.selected_listen_rule_index = index
            self.listen_rule_dialog(index)

    def listen_rule_add_clicked(self) -> None:
        self.listen_rule_dialog()

    def listen_rule_edit_current_clicked(self, listbox: Listbox | None = None) -> None:
        self.listen_rule_listbox_selected(listbox)
        index = self.selected_listen_rule_index
        if not (0 <= index < len(self.listen_rules)):
            self.set_action_feedback("请先选择一条监听规则。")
            return
        self.listen_rule_dialog(index)

    def listen_rule_delete_clicked(self, listbox: Listbox | None = None) -> None:
        self.listen_rule_listbox_selected(listbox)
        index = self.selected_listen_rule_index
        if not (0 <= index < len(self.listen_rules)):
            self.set_action_feedback("请先选择一条监听规则。")
            return
        self.listen_rules.pop(index)
        self.selected_listen_rule_index = min(index, len(self.listen_rules) - 1)
        self.refresh_listen_rule_list()
        self.mark_dirty()

    def listen_rule_dialog(self, edit_index: int | None = None) -> None:
        editing = edit_index is not None and 0 <= edit_index < len(self.listen_rules)
        current = self.listen_rules[edit_index] if editing and edit_index is not None else {}
        window = ctk.CTkToplevel(self.root)
        window.title(("编辑" if editing else "新增") + "监听规则")
        window.geometry("660x520")
        window.transient(self.root)
        window.grab_set()
        window.lift()
        window.grid_columnconfigure(1, weight=1)

        mode_labels = {"thread_author": "固定帖子中筛选用户", "author": "用户主页监听"}
        mode_values = {label: value for value, label in mode_labels.items()}
        mode_var = StringVar(value=mode_labels.get(str(current.get("mode") or "thread_author"), mode_labels["thread_author"]))
        label_var = StringVar(value=str(current.get("label") or ""))
        uid_var = StringVar(value=self.target_choice_values("watch_author_ids", self.vars["default_author_id"].get())[0] if not current.get("author_id") else str(current.get("author_id")))
        tid_var = StringVar(value=self.target_choice_values("preset_thread_ids", self.vars["default_tid"].get())[0] if not current.get("tid") else str(current.get("tid")))
        feedback_var = StringVar(value="")

        rows = [("监听方式", mode_var, "mode"), ("备注", label_var, "entry"), ("用户", uid_var, "user"), ("帖子", tid_var, "thread")]
        for row, (label, var, kind) in enumerate(rows):
            ctk.CTkLabel(window, text=label, anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="w", padx=18, pady=(18 if row == 0 else 6, 6))
            if kind == "mode":
                ctk.CTkOptionMenu(window, variable=var, values=list(mode_values.keys()), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", text_color=TEXT).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=(18, 6))
            elif kind == "user":
                ctk.CTkComboBox(window, variable=var, values=self.target_choice_values("watch_author_ids", self.vars["default_author_id"].get()), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", text_color=TEXT).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=6)
            elif kind == "thread":
                ctk.CTkComboBox(window, variable=var, values=self.target_choice_values("preset_thread_ids", self.vars["default_tid"].get()), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", text_color=TEXT).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=6)
            else:
                ctk.CTkEntry(window, textvariable=var, height=34, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=6)

        ctk.CTkLabel(window, text="发送目标", anchor="w", text_color=TEXT).grid(row=4, column=0, sticky="nw", padx=18, pady=6)
        target_container = ctk.CTkFrame(window, fg_color="transparent")
        target_container.grid(row=4, column=1, sticky="ew", padx=(0, 18), pady=6)
        target_container.grid_columnconfigure(0, weight=1)
        target_box = Listbox(
            target_container,
            height=6,
            selectmode=SINGLE,
            exportselection=False,
            bg="#f8fafc",
            fg=TEXT,
            selectbackground="#dbeafe",
            selectforeground=TEXT,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=PRIMARY,
            relief="flat",
        )
        target_box.grid(row=0, column=0, sticky="ew")
        target_buttons = ctk.CTkFrame(target_container, fg_color="transparent")
        target_buttons.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        selected_target_ids = [
            str(target_id).strip()
            for target_id in (current.get("target_ids") if isinstance(current.get("target_ids"), list) else [])
            if str(target_id).strip()
        ]

        def refresh_selected_targets() -> None:
            target_box.delete(0, END)
            if not selected_target_ids:
                target_box.insert(END, "暂无发送目标，点击 + 添加")
                target_box.itemconfig(0, foreground=MUTED)
                return
            for index, target_id in enumerate(selected_target_ids, 1):
                target = next((item for item in self.push_targets if str(item.get("id") or "") == target_id), None)
                target_box.insert(END, f"{index}. {push_target_label(target) if target else target_id}")

        def add_rule_target() -> None:
            def add_target(target_id: str) -> None:
                if target_id and target_id not in selected_target_ids:
                    selected_target_ids.append(target_id)
                refresh_selected_targets()

            self.route_target_dialog("新增规则发送目标", add_target, parent=window)

        def remove_rule_target() -> None:
            if not target_box.curselection() or not selected_target_ids:
                feedback_var.set("请先选择一个发送目标。")
                return
            index = int(target_box.curselection()[0])
            if 0 <= index < len(selected_target_ids):
                selected_target_ids.pop(index)
                refresh_selected_targets()

        ctk.CTkButton(target_buttons, text="+", width=34, height=30, corner_radius=8, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=add_rule_target).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(target_buttons, text="-", width=34, height=30, corner_radius=8, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=remove_rule_target).grid(row=1, column=0, sticky="ew")
        refresh_selected_targets()

        ctk.CTkLabel(window, textvariable=feedback_var, anchor="w", text_color="#dc2626").grid(row=5, column=1, sticky="ew", padx=(0, 18), pady=(0, 6))

        def confirm() -> None:
            mode = mode_values.get(mode_var.get(), "thread_author")
            author_id = self.target_id_from_choice("watch_author_ids", uid_var.get())
            tid = self.target_id_from_choice("preset_thread_ids", tid_var.get()) if mode == "thread_author" else ""
            if not author_id.isdigit() or (mode == "thread_author" and not tid.isdigit()):
                feedback_var.set("用户 ID 和帖子 ID 必须是数字。")
                return
            target_ids = [target_id for target_id in selected_target_ids if target_id]
            if not target_ids:
                feedback_var.set("请至少添加一个发送目标。")
                return
            rule = dict(current)
            rule.update(
                {
                    "label": label_var.get().strip(),
                    "mode": mode,
                    "author_id": author_id,
                    "tid": tid,
                    "target_ids": target_ids,
                }
            )
            rule["id"] = str(rule.get("id") or "").strip() or (f"author:{author_id}" if mode == "author" else f"thread_author:{tid}:{author_id}")
            if editing and edit_index is not None:
                self.listen_rules[edit_index] = rule
                self.selected_listen_rule_index = edit_index
            else:
                self.listen_rules.append(rule)
                self.selected_listen_rule_index = len(self.listen_rules) - 1
            self.refresh_listen_rule_list()
            self.mark_dirty()
            window.destroy()

        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=6, column=0, columnspan=2, sticky="e", padx=18, pady=(8, 18))
        ctk.CTkButton(button_row, text="取消", width=82, height=32, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=window.destroy).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(button_row, text="确认", width=82, height=32, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=confirm).grid(row=0, column=1)

    def target_dialog(self, key: str, label: str, edit_index: int | None = None) -> None:
        targets = self.target_lists.setdefault(key, [])
        editing = edit_index is not None and 0 <= edit_index < len(targets)
        current = targets[edit_index] if editing and edit_index is not None else None

        window = ctk.CTkToplevel(self.root)
        window.title("编辑条目" if editing else f"添加{label}")
        window.geometry("560x240")
        window.transient(self.root)
        window.grab_set()
        window.lift()
        window.grid_columnconfigure(1, weight=1)

        id_var = StringVar(value=current.id if current else "")
        note_var = StringVar(value=current.label if current else "")
        ctk.CTkLabel(window, text="ID", anchor="w", text_color=TEXT).grid(row=0, column=0, sticky="w", padx=18, pady=(20, 8))
        id_entry = ctk.CTkEntry(window, textvariable=id_var, height=34, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER)
        id_entry.grid(row=0, column=1, sticky="ew", padx=(0, 18), pady=(20, 8))
        ctk.CTkLabel(window, text="备注", anchor="w", text_color=TEXT).grid(row=1, column=0, sticky="w", padx=18, pady=8)
        note_entry = ctk.CTkEntry(window, textvariable=note_var, height=34, corner_radius=10, fg_color="#f8fafc", border_width=1, border_color=BORDER)
        note_entry.grid(row=1, column=1, sticky="ew", padx=(0, 18), pady=8)
        feedback_var = StringVar(value="")
        ctk.CTkLabel(window, textvariable=feedback_var, anchor="w", text_color="#dc2626").grid(row=2, column=1, sticky="ew", padx=(0, 18), pady=(0, 8))

        def confirm() -> None:
            target_id = id_var.get().strip()
            note = note_var.get().strip()
            if not target_id.isdigit():
                feedback_var.set("ID 必须是数字")
                return
            if any(item.id == target_id and (not editing or index != edit_index) for index, item in enumerate(targets)):
                feedback_var.set("这个 ID 已经在列表里")
                return
            target = nga_feishu_watch.WatchTarget(
                target_id,
                note,
            )
            if editing and edit_index is not None:
                targets[edit_index] = target
                self.selected_target_indices[key] = edit_index
            else:
                targets.append(target)
                self.selected_target_indices[key] = len(targets) - 1
            self.refresh_target_list(key)
            self.mark_dirty()
            self.set_action_feedback("列表已更新，记得保存配置。")
            window.destroy()
            self.root.update_idletasks()

        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=3, column=0, columnspan=2, sticky="e", padx=18, pady=(4, 18))
        ctk.CTkButton(button_row, text="取消", width=82, height=32, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=window.destroy).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(button_row, text="确认", width=82, height=32, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=confirm).grid(row=0, column=1)
        id_entry.bind("<Return>", lambda _event: confirm())
        note_entry.bind("<Return>", lambda _event: confirm())
        id_entry.focus_set()

    def thread_author_display_text(self, watch: nga_feishu_watch.ThreadAuthorWatch) -> str:
        text = nga_feishu_watch.thread_author_display_name(watch)
        if watch.route_channel:
            text += f" -> {watch.route_channel}"
            if watch.route_profile_id:
                text += f":{watch.route_profile_id}"
        if watch.feishu_receive_id:
            text += f" -> {watch.feishu_receive_id}"
        if watch.feishu_app_id:
            text += " / 独立机器人"
        return text

    def refresh_thread_author_list(self) -> None:
        for listbox in self.thread_author_listboxes:
            self.render_thread_author_listbox(listbox)

    def render_thread_author_listbox(self, listbox: Listbox) -> None:
        selected = self.selected_thread_author_index
        listbox.delete(0, END)
        if not self.thread_author_watches:
            self.selected_thread_author_index = -1
            listbox.insert(END, "暂无条目，点击 + 添加")
            listbox.itemconfig(0, foreground=MUTED)
            listbox.selection_clear(0, END)
            listbox.update_idletasks()
            return
        for index, watch in enumerate(self.thread_author_watches, 1):
            listbox.insert(END, f"{index}. {self.thread_author_display_text(watch)}")
        if selected < 0 or selected >= len(self.thread_author_watches):
            selected = 0
        self.selected_thread_author_index = selected
        listbox.selection_clear(0, END)
        listbox.selection_set(selected)
        listbox.activate(selected)
        listbox.see(selected)
        listbox.update_idletasks()

    def thread_author_listbox_selected(self, listbox: Listbox | None = None) -> None:
        if not self.thread_author_watches:
            self.selected_thread_author_index = -1
            return
        if listbox is None:
            listbox = next((box for box in self.thread_author_listboxes if box.curselection()), None)
        if listbox is None:
            return
        selection = listbox.curselection()
        if not selection:
            return
        index = int(selection[0])
        self.selected_thread_author_index = index if 0 <= index < len(self.thread_author_watches) else -1

    def thread_author_listbox_double_clicked(self, event: object) -> None:
        listbox = getattr(event, "widget", None)
        if listbox not in self.thread_author_listboxes or not self.thread_author_watches:
            return
        index = int(listbox.nearest(int(getattr(event, "y", 0))))
        if not (0 <= index < len(self.thread_author_watches)):
            return
        self.selected_thread_author_index = index
        self.refresh_thread_author_list()
        self.thread_author_dialog(edit_index=index)

    def thread_author_config_text(self) -> str:
        lines: list[str] = []
        for watch in self.thread_author_watches:
            line = f"{watch.tid}:{watch.author_id}"
            if watch.label:
                line += f"={watch.label}"
            if watch.route_channel:
                line += f"|channel={watch.route_channel}"
            if watch.route_profile_id:
                line += f"|bot={watch.route_profile_id}"
            if watch.feishu_receive_id:
                line += f"|receive_id={watch.feishu_receive_id}"
            if watch.feishu_app_id:
                line += f"|app_id={watch.feishu_app_id}"
            if watch.feishu_app_secret:
                line += f"|app_secret={watch.feishu_app_secret}"
            if watch.feishu_id_type and watch.feishu_id_type != "chat_id":
                line += f"|id_type={watch.feishu_id_type}"
            lines.append(line)
        return "\n".join(lines)

    def thread_author_add_clicked(self) -> None:
        self.thread_author_dialog()

    def thread_author_edit_current_clicked(self, listbox: Listbox | None = None) -> None:
        self.thread_author_listbox_selected(listbox)
        index = self.selected_thread_author_index
        if not (0 <= index < len(self.thread_author_watches)):
            self.set_action_feedback("请先选中要编辑的帖内作者规则。")
            return
        self.thread_author_dialog(edit_index=index)

    def thread_author_delete_clicked(self, listbox: Listbox | None = None) -> None:
        self.thread_author_listbox_selected(listbox)
        index = self.selected_thread_author_index
        if not (0 <= index < len(self.thread_author_watches)):
            self.set_action_feedback("请先选中要删除的帖内作者规则。")
            return
        self.thread_author_watches.pop(index)
        self.selected_thread_author_index = min(index, len(self.thread_author_watches) - 1)
        self.refresh_thread_author_list()
        self.mark_dirty()
        self.set_action_feedback("帖内作者监听已更新，记得保存配置。")
        self.root.update_idletasks()

    def thread_author_dialog(self, edit_index: int | None = None) -> None:
        editing = edit_index is not None and 0 <= edit_index < len(self.thread_author_watches)
        current = self.thread_author_watches[edit_index] if editing and edit_index is not None else None

        window = ctk.CTkToplevel(self.root)
        window.title("编辑帖内作者监听" if editing else "添加帖内作者监听")
        window.geometry("620x520")
        window.transient(self.root)
        window.grab_set()
        window.lift()
        window.grid_columnconfigure(1, weight=1)

        tid_var = StringVar(value=current.tid if current else str(self.config.get("default_tid") or ""))
        uid_var = StringVar(value=current.author_id if current else str(self.config.get("default_author_id") or ""))
        note_var = StringVar(value=current.label if current else "")
        receive_var = StringVar(value=current.feishu_receive_id if current else "")
        app_id_var = StringVar(value=current.feishu_app_id if current else "")
        app_secret_var = StringVar(value=current.feishu_app_secret if current else "")
        id_type_var = StringVar(value=feishu_id_type_label(current.feishu_id_type if current else "chat_id"))
        channel_var = StringVar(value=route_channel_label(current.route_channel if current and current.route_channel else ("feishu" if current and current.feishu_receive_id else "")))
        feishu_profile_var = StringVar(value=self.profile_option_for_id("feishu", current.route_profile_id if current else ""))
        wechat_profile_var = StringVar(value=self.profile_option_for_id("wechat", current.route_profile_id if current else ""))
        receive_choice_var = StringVar(value=self.option_for_chat_id(current.route_profile_id if current else "", current.feishu_receive_id if current else ""))
        fields = [
            ("帖子 ID", tid_var, False),
            ("作者 UID", uid_var, False),
            ("备注", note_var, False),
        ]
        for row, (label, var, secret) in enumerate(fields):
            ctk.CTkLabel(window, text=label, anchor="w", text_color=TEXT).grid(row=row, column=0, sticky="w", padx=18, pady=(16 if row == 0 else 6, 6))
            if row == 0:
                ctk.CTkComboBox(
                    window,
                    variable=var,
                    values=self.target_choice_values("preset_thread_ids", str(self.config.get("default_tid") or "")),
                    height=34,
                    corner_radius=10,
                    fg_color="#f8fafc",
                    border_width=1,
                    border_color=BORDER,
                ).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=(16 if row == 0 else 6, 6))
            elif row == 1:
                ctk.CTkComboBox(
                    window,
                    variable=var,
                    values=self.target_choice_values("watch_author_ids", str(self.config.get("default_author_id") or "")),
                    height=34,
                    corner_radius=10,
                    fg_color="#f8fafc",
                    border_width=1,
                    border_color=BORDER,
                ).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=(16 if row == 0 else 6, 6))
            else:
                ctk.CTkEntry(
                    window,
                    textvariable=var,
                    show="*" if secret else "",
                    height=34,
                    corner_radius=10,
                    fg_color="#f8fafc",
                    border_width=1,
                    border_color=BORDER,
                ).grid(row=row, column=1, sticky="ew", padx=(0, 18), pady=(16 if row == 0 else 6, 6))
        ctk.CTkLabel(window, text="ID 类型", anchor="w", text_color=TEXT).grid(row=3, column=0, sticky="w", padx=18, pady=6)
        ctk.CTkOptionMenu(
            window,
            variable=id_type_var,
            values=list(FEISHU_ID_TYPE_LABELS.values()),
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            dropdown_fg_color="#ffffff",
            text_color=TEXT,
        ).grid(row=3, column=1, sticky="ew", padx=(0, 18), pady=6)
        ctk.CTkLabel(window, text="通道", anchor="w", text_color=TEXT).grid(row=4, column=0, sticky="w", padx=18, pady=6)
        ctk.CTkOptionMenu(window, variable=channel_var, values=list(ROUTE_CHANNEL_VALUES.keys()), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", dropdown_fg_color="#ffffff", text_color=TEXT).grid(row=4, column=1, sticky="ew", padx=(0, 18), pady=6)
        ctk.CTkLabel(window, text="飞书群", anchor="w", text_color=TEXT).grid(row=6, column=0, sticky="w", padx=18, pady=6)
        receive_choice_box = ctk.CTkComboBox(window, variable=receive_choice_var, values=self.chat_option_values(current.route_profile_id if current else ""), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", text_color=TEXT)
        receive_choice_box.grid(row=6, column=1, sticky="ew", padx=(0, 18), pady=6)

        def update_thread_chat_options(_value: str | None = None) -> None:
            profile_id = self.profile_id_from_option("feishu", feishu_profile_var.get())
            values = self.chat_option_values(profile_id)
            receive_choice_box.configure(values=values)
            if receive_choice_var.get().startswith("<") or not receive_choice_var.get().strip():
                receive_choice_var.set(values[0] if values else "")

        ctk.CTkLabel(window, text="飞书机器人", anchor="w", text_color=TEXT).grid(row=5, column=0, sticky="w", padx=18, pady=6)
        ctk.CTkOptionMenu(window, variable=feishu_profile_var, values=self.profile_option_values("feishu"), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", dropdown_fg_color="#ffffff", text_color=TEXT, command=update_thread_chat_options).grid(row=5, column=1, sticky="ew", padx=(0, 18), pady=6)
        ctk.CTkLabel(window, text="微信机器人", anchor="w", text_color=TEXT).grid(row=7, column=0, sticky="w", padx=18, pady=6)
        ctk.CTkOptionMenu(window, variable=wechat_profile_var, values=self.profile_option_values("wechat"), height=34, fg_color="#f8fafc", button_color="#e2e8f0", button_hover_color="#cbd5e1", dropdown_fg_color="#ffffff", text_color=TEXT).grid(row=7, column=1, sticky="ew", padx=(0, 18), pady=6)
        feedback_var = StringVar(value="")
        ctk.CTkLabel(window, textvariable=feedback_var, anchor="w", text_color="#dc2626").grid(row=8, column=1, sticky="ew", padx=(0, 18), pady=(0, 6))

        def confirm() -> None:
            tid = self.target_id_from_choice("preset_thread_ids", tid_var.get())
            uid = self.target_id_from_choice("watch_author_ids", uid_var.get())
            if not tid.isdigit() or not uid.isdigit():
                feedback_var.set("帖子 ID 和作者 UID 必须是数字")
                return
            if any(item.key == f"{tid}:{uid}" and (not editing or index != edit_index) for index, item in enumerate(self.thread_author_watches)):
                feedback_var.set("这个帖子 + 作者组合已经存在")
                return
            app_id = app_id_var.get().strip()
            app_secret = app_secret_var.get().strip()
            route_channel = route_channel_value(channel_var.get())
            if route_channel == "feishu":
                route_profile_id = self.profile_id_from_option("feishu", feishu_profile_var.get())
                receive_id = self.chat_id_from_option(route_profile_id, receive_choice_var.get()) or receive_var.get().strip()
                if not receive_id:
                    feedback_var.set("请选择或填写飞书群 chat_id。")
                    return
            elif route_channel == "wechat":
                route_profile_id = self.profile_id_from_option("wechat", wechat_profile_var.get())
                receive_id = ""
            else:
                route_profile_id = ""
                receive_id = receive_var.get().strip()
            if (app_id or app_secret) and not (app_id and app_secret and receive_id):
                feedback_var.set("使用单独机器人时必须同时填写 App ID、App Secret 和 Receive ID")
                return
            watch = nga_feishu_watch.ThreadAuthorWatch(
                tid=tid,
                author_id=uid,
                label=note_var.get().strip(),
                route_channel=route_channel,
                route_profile_id=route_profile_id,
                feishu_app_id=app_id,
                feishu_app_secret=app_secret,
                feishu_receive_id=receive_id,
                feishu_id_type=feishu_id_type_value(id_type_var.get()),
            )
            if editing and edit_index is not None:
                self.thread_author_watches[edit_index] = watch
                self.selected_thread_author_index = edit_index
            else:
                self.thread_author_watches.append(watch)
                self.selected_thread_author_index = len(self.thread_author_watches) - 1
            self.refresh_thread_author_list()
            self.mark_dirty()
            self.set_action_feedback("帖内作者监听已更新，记得保存配置。")
            window.destroy()
            self.root.update_idletasks()

        button_row = ctk.CTkFrame(window, fg_color="transparent")
        button_row.grid(row=9, column=0, columnspan=2, sticky="e", padx=18, pady=(8, 18))
        ctk.CTkButton(button_row, text="取消", width=82, height=32, fg_color="#e2e8f0", hover_color="#cbd5e1", text_color=TEXT, command=window.destroy).grid(row=0, column=0, padx=(0, 8))
        ctk.CTkButton(button_row, text="确认", width=82, height=32, fg_color=PRIMARY, hover_color=PRIMARY_HOVER, command=confirm).grid(row=0, column=1)
    def sync_cookie_boxes(self, source: ctk.CTkTextbox) -> None:
        if self.syncing_cookie:
            return
        self.syncing_cookie = True
        try:
            text = source.get("1.0", "end").strip()
            for box in self.cookie_textboxes:
                if box is source:
                    continue
                box.delete("1.0", "end")
                box.insert("1.0", text)
            self.mark_dirty()
        finally:
            self.syncing_cookie = False

    def set_receive_id(self, chat_id: str) -> None:
        self.vars["feishu_receive_id"].set(chat_id)
        self.set_status(self.current_status_text(), "已填入 Receive ID，记得保存配置")
        self.append_log(f"已填入 Receive ID：{chat_id}")

    def render_chat_results(self, chats: list[dict[str, object]]) -> None:
        for result_frame in self.chat_result_frames:
            for child in result_frame.winfo_children():
                child.destroy()
            if not chats:
                ctk.CTkLabel(
                    result_frame,
                    text="暂无缓存群组。在飞书配置组编辑弹窗点击“查询群组并保存”后会显示。",
                    anchor="w",
                    justify="left",
                    wraplength=420,
                    text_color=MUTED,
                    font=ctk.CTkFont(size=12),
                ).grid(row=0, column=0, sticky="ew", padx=12, pady=12)
                continue

            for index, chat in enumerate(chats):
                chat_id = str(chat.get("chat_id") or "")
                name = str(chat.get("name") or "未命名群组")
                chat_type = str(chat.get("chat_type") or "group")
                row = ctk.CTkFrame(result_frame, fg_color="#ffffff", corner_radius=8, border_width=1, border_color="#e5e7eb")
                row.grid(row=index, column=0, sticky="ew", padx=8, pady=(8, 4 if index == len(chats) - 1 else 2))
                row.grid_columnconfigure(0, weight=1)
                ctk.CTkLabel(
                    row,
                    text=f"{name}  ·  {chat_type}",
                    anchor="w",
                    text_color=TEXT,
                    font=ctk.CTkFont(size=12, weight="bold"),
                ).grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
                ctk.CTkLabel(
                    row,
                    text=chat_id,
                    anchor="w",
                    text_color=MUTED,
                    font=ctk.CTkFont(family="Consolas", size=11),
                    wraplength=380,
                ).grid(row=1, column=0, sticky="ew", padx=10, pady=(2, 8))

    def collect_config(self) -> dict[str, object]:
        config = dict(self.config)
        config["nga_cookie"] = self.cookie_textboxes[0].get("1.0", "end").strip() if self.cookie_textboxes else ""
        config["thread_author_watches"] = self.thread_author_config_text()
        for key, var in self.vars.items():
            config[key] = var.get().strip()
        config["watch_mode"] = WATCH_MODE_VALUES.get(self.watch_mode_label_var.get(), str(config.get("watch_mode") or "author").strip())
        if self.listen_rules:
            modes = {str(rule.get("mode") or "thread_author") for rule in self.listen_rules}
            config["watch_mode"] = "both" if modes == {"author", "thread_author"} else ("author" if modes == {"author"} else "thread_author")
        for key in self.target_lists:
            config[key] = self.target_list_config_text(key)
        config["feishu_bot_profiles"] = json.dumps(self.feishu_profiles, ensure_ascii=False, indent=2)
        config["wechat_bot_profiles"] = json.dumps(self.wechat_profiles, ensure_ascii=False, indent=2)
        config["push_targets"] = json.dumps(self.push_targets, ensure_ascii=False, indent=2)
        config["listen_rules"] = json.dumps(self.listen_rules, ensure_ascii=False, indent=2)
        schedule_target_ids = self.ai_schedule_target_ids()
        config["ai_schedule_target_ids"] = ",".join(schedule_target_ids) if schedule_target_ids else ("__none__" if self.push_targets else "")
        if self.feishu_profiles:
            profile = self.feishu_profiles[0]
            config["feishu_app_id"] = str(profile.get("app_id") or "").strip()
            config["feishu_app_secret"] = str(profile.get("app_secret") or "").strip()
            config["feishu_id_type"] = str(profile.get("id_type") or "chat_id").strip() or "chat_id"
        else:
            config["feishu_app_id"] = ""
            config["feishu_app_secret"] = ""
            config["feishu_id_type"] = "chat_id"
        if self.wechat_profiles:
            profile = self.wechat_profiles[0]
            config["wechat_bot_token"] = str(profile.get("token") or "").strip()
            config["wechat_bot_base_url"] = str(profile.get("base_url") or "https://ilinkai.weixin.qq.com").strip()
            config["wechat_bot_cdn_base_url"] = str(profile.get("cdn_base_url") or "https://novac2c.cdn.weixin.qq.com/c2c").strip()
            config["wechat_bot_target_user_id"] = str(profile.get("target_user_id") or "").strip()
            config["wechat_bot_allowed_user_ids"] = str(profile.get("allowed_user_ids") or "").strip()
            config["wechat_bot_poll_timeout_ms"] = str(profile.get("poll_timeout_ms") or "35000").strip()
            config["wechat_bot_route_tag"] = str(profile.get("route_tag") or "").strip()
            config["wechat_bot_account_id"] = str(profile.get("account_id") or "default").strip() or "default"
        else:
            config["wechat_bot_token"] = ""
            config["wechat_bot_base_url"] = "https://ilinkai.weixin.qq.com"
            config["wechat_bot_cdn_base_url"] = "https://novac2c.cdn.weixin.qq.com/c2c"
            config["wechat_bot_target_user_id"] = ""
            config["wechat_bot_allowed_user_ids"] = ""
            config["wechat_bot_poll_timeout_ms"] = "35000"
            config["wechat_bot_route_tag"] = ""
            config["wechat_bot_account_id"] = "default"
        first_feishu_target = next((target for target in self.push_targets if str(target.get("channel") or "feishu") == "feishu"), None)
        config["feishu_receive_id"] = str(first_feishu_target.get("receive_id") or "").strip() if first_feishu_target else ""
        if first_feishu_target and str(first_feishu_target.get("id_type") or "").strip():
            config["feishu_id_type"] = str(first_feishu_target.get("id_type") or "chat_id").strip() or "chat_id"
        author_text = str(config.get("watch_author_ids") or "").strip()
        thread_text = str(config.get("preset_thread_ids") or "").strip()
        author_targets = nga_feishu_watch.parse_target_list(author_text, "")
        thread_targets = nga_feishu_watch.parse_target_list(thread_text, "")
        if author_targets:
            config["default_author_id"] = author_targets[0].id
        else:
            config["default_author_id"] = ""
        if thread_targets:
            config["default_tid"] = thread_targets[0].id
        else:
            config["default_tid"] = ""
        config["auto_mark_seen_first_start"] = self.auto_init_var.get()
        config["quiet_hours_enabled"] = self.quiet_enabled_var.get()
        config["quiet_start_day"] = str(weekday_index(self.quiet_start_day_var.get()))
        config["quiet_end_day"] = str(weekday_index(self.quiet_end_day_var.get()))
        config["quiet_start_time"] = f"{self.quiet_start_hour_var.get()}:{self.quiet_start_minute_var.get()}"
        config["quiet_end_time"] = f"{self.quiet_end_hour_var.get()}:{self.quiet_end_minute_var.get()}"
        config["quiet_policy"] = self.quiet_policy_var.get()
        config["ai_enabled"] = self.ai_enabled_var.get()
        config["ai_auto_analyze_new_post"] = self.ai_auto_var.get()
        config["ai_schedule_enabled"] = self.ai_schedule_var.get()
        config["ai_send_errors_to_feishu"] = self.ai_send_errors_var.get()
        config["ai_upload_long_result"] = self.ai_upload_long_result_var.get()
        config["ai_ignore_codex_user_config"] = self.ai_ignore_codex_user_config_var.get()
        window_mode = "custom" if self.ai_schedule_window_mode_var.get() == "自定义" else "a_share"
        config["ai_schedule_window_mode"] = window_mode
        if window_mode == "a_share":
            config["ai_schedule_windows"] = "weekday:09:30-11:30,13:00-15:00"
        return config

    def current_status_text(self) -> str:
        if self.process and self.process.poll() is None:
            return f"运行中 PID {self.process.pid}"
        return "未启动"

    def set_idle_status(self) -> None:
        self.status_var.set(self.current_status_text())
        self.update_status_style()

    def update_status_style(self) -> None:
        status = self.status_var.get()
        if status.startswith("运行中"):
            self.status_dot.configure(fg_color="#22c55e")
            self.status_badge.configure(fg_color="#dcfce7", text_color="#166534")
        elif "失败" in status or "退出" in status:
            self.status_dot.configure(fg_color="#ef4444")
            self.status_badge.configure(fg_color="#fee2e2", text_color="#991b1b")
        elif status.endswith("中"):
            self.status_dot.configure(fg_color="#f59e0b")
            self.status_badge.configure(fg_color="#fef3c7", text_color="#92400e")
        else:
            self.status_dot.configure(fg_color="#e2e8f0")
            self.status_badge.configure(fg_color="#f1f5f9", text_color="#334155")
        self.update_control_states()

    def update_control_states(self) -> None:
        if not hasattr(self, "start_button") or not hasattr(self, "stop_button"):
            return

        process_running = bool(self.process and self.process.poll() is None)
        pid_running = bool(self.known_watcher_pids(include_scan=False))

        if self.starting:
            self.start_button.configure(state="disabled", text="启动中")
            self.stop_button.configure(state="disabled")
            return
        if self.stopping:
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="disabled", text="停止中")
            return
        if process_running or pid_running:
            self.start_button.configure(state="disabled", text="▶ 启动监听")
            self.stop_button.configure(state="normal", text="■ 停止监听")
            return

        self.start_button.configure(state="normal", text="▶ 启动监听")
        self.stop_button.configure(state="disabled", text="■ 停止监听")

    def set_status(self, status: str, detail: str | None = None) -> None:
        self.status_var.set(status)
        if detail is not None:
            self.status_detail_var.set(detail)
        self.update_status_style()

    def set_action_feedback(self, text: str) -> None:
        self.action_feedback_var.set(text)

    def known_watcher_pids(self, *, include_scan: bool = False) -> set[int]:
        scanned_pids = find_watcher_process_ids() if include_scan else set()
        pids = set(scanned_pids)
        live_process_pid = 0
        if self.process and self.process.poll() is None:
            live_process_pid = int(self.process.pid)
            pids.add(live_process_pid)
        elif self.process and self.process.poll() is not None:
            self.process = None
        try:
            raw = watcher_pid_path().read_text(encoding="utf-8").strip()
            if raw:
                pid = int(raw)
                if pid in scanned_pids or pid == live_process_pid or (not include_scan and process_exists(pid)):
                    pids.add(pid)
        except (OSError, ValueError):
            pass
        pids.discard(os.getpid())
        return pids

    def stop_watcher_processes(self, *, include_scan: bool = True) -> list[int]:
        stopped: list[int] = []
        for pid in sorted(self.known_watcher_pids(include_scan=include_scan)):
            if kill_process_tree(pid):
                stopped.append(pid)
        if self.process:
            try:
                self.process.wait(timeout=2)
            except Exception:
                pass
        self.process = None
        try:
            watcher_pid_path().unlink()
        except OSError:
            pass
        return stopped

    def save_from_ui(self, *, require_receive_id: bool = True, require_cookie: bool = True) -> bool:
        config = self.collect_config()
        errors = validate_config(config, require_receive_id=require_receive_id, require_cookie=require_cookie)
        if errors:
            messagebox.showerror("配置不完整", "\n".join(errors))
            return False
        self.config = config
        save_config(self.config)
        self.append_log("配置已保存。")
        self.append_log(f"状态文件：{resolved_state_path(self.config)}")
        self.set_status(self.current_status_text(), "配置已保存")
        self.dirty = False
        self.save_state_var.set("配置已保存")
        self.save_state_label.configure(text_color=MUTED)
        self.global_save_button.configure(fg_color=PRIMARY, hover_color=PRIMARY_HOVER)
        feedback = f"配置已保存，状态文件：{resolved_state_path(self.config).name}"
        if self.known_watcher_pids(include_scan=False):
            feedback += "。免打扰配置会在下次启动监听后生效。"
            self.append_log("免打扰配置会在下次启动监听后生效。")
        self.set_action_feedback(feedback)
        return True

    def run_background(self, label: str, target: Callable[[], None], *, preserve_status: bool = False) -> None:
        def wrapper() -> None:
            self.root.after(0, lambda: self.set_status(f"{label}中"))
            self.root.after(0, lambda: self.set_action_feedback(f"{label}中..."))
            try:
                target()
                if not preserve_status:
                    self.root.after(0, self.set_idle_status)
            except Exception as exc:
                self.append_log(f"{label}失败：{exc}")
                self.root.after(0, lambda: self.set_status("操作失败", str(exc)))
                self.root.after(0, lambda: self.set_action_feedback(f"{label}失败：{exc}"))
                self.root.after(0, lambda: messagebox.showerror("操作失败", str(exc)))

        threading.Thread(target=wrapper, daemon=True).start()

    def mark_seen(self) -> None:
        self.append_log("开始初始化已读。")
        count = nga_feishu_watch.run_once(build_args(self.config, mark_seen=True))
        self.config["mark_seen_initialized"] = True
        save_config(self.config)
        self.append_log(f"初始化已读完成，已标记 {count} 条。")
        self.status_detail_var.set(f"已标记 {count} 条历史回复")
        self.root.after(0, lambda: self.set_action_feedback(f"初始化已读完成，已标记 {count} 条。"))

    def mark_seen_clicked(self) -> None:
        if not self.save_from_ui():
            return
        self.run_background("初始化已读", self.mark_seen)

    def send_test_clicked(self) -> None:
        if not self.save_from_ui():
            return

        def do_send() -> None:
            self.append_log("开始发送测试消息。")
            nga_feishu_watch.send_test_message(build_args(self.config))
            self.append_log("测试消息已发送。")
            self.status_detail_var.set("测试消息已发送")
            self.root.after(0, lambda: self.set_action_feedback("测试消息已发送。"))

        self.run_background("发送测试", do_send)

    def list_chats_clicked(self) -> None:
        if not self.save_from_ui(require_receive_id=False, require_cookie=False):
            return
        if str(self.config.get("bot_channel") or "feishu") == "wechat":
            self.append_log("微信通道没有群组查询；请先让目标微信给机器人发一条消息，再把用户 ID 填到目标用户 ID。")
            self.set_action_feedback("微信通道不需要查询群组；请按绑定说明先发一条消息。")
            messagebox.showinfo("微信绑定说明", "微信通道没有飞书 chat_id 查询。\n\n首次使用请先用目标微信给机器人发一条消息，程序收到后会缓存 context_token。然后把该微信用户 ID 填到“目标用户 ID”。")
            return
        profile_index = self.selected_feishu_profile_index
        profile = self.feishu_profiles[profile_index] if 0 <= profile_index < len(self.feishu_profiles) else None
        app_id = str((profile or {}).get("app_id") or self.config.get("feishu_app_id") or "").strip()
        app_secret = str((profile or {}).get("app_secret") or self.config.get("feishu_app_secret") or "").strip()

        def do_list() -> None:
            self.append_log("开始查询机器人可见群组。")
            chats = nga_feishu_watch.merge_feishu_chats(
                nga_feishu_watch.list_feishu_chats(app_id, app_secret, int_value(self.config, "timeout", 20))
            )
            if not chats:
                self.root.after(0, lambda: self.render_chat_results([]))
                self.append_log("未查询到群组。请确认机器人已加入目标群。")
                self.status_detail_var.set("未查询到群组")
                self.root.after(0, lambda: self.set_action_feedback("未查询到群组，请确认机器人已加入目标群。"))
                return
            for chat in chats:
                self.append_log(
                    f"chat_id={chat.get('chat_id', '')}，名称={chat.get('name', '')}，类型={chat.get('chat_type', '')}"
                )
            def apply_chats() -> None:
                if profile is not None:
                    profile["chats"] = chats
                    self.refresh_profile_list("feishu")
                    self.mark_dirty()
                self.render_chat_results(chats)

            self.root.after(0, apply_chats)
            self.append_log(f"共查询到 {len(chats)} 个群组。复制目标群 chat_id 到 Receive ID。")
            self.status_detail_var.set(f"查询到 {len(chats)} 个群组")
            self.root.after(0, lambda: self.set_action_feedback(f"查询到 {len(chats)} 个群组，可在飞书配置卡片里点击“填入”。"))

        self.run_background("查询群组", do_list)

    def wechat_scan_bind_clicked(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showwarning("监听运行中", "请先停止监听，再进行微信扫码绑定。")
            return
        self.vars["bot_channel"].set("wechat")
        self.update_channel_visibility()
        config = self.collect_config()
        base_url = str(config.get("wechat_bot_base_url") or "https://ilinkai.weixin.qq.com").strip()
        route_tag = str(config.get("wechat_bot_route_tag") or "").strip()
        timeout = int_value(config, "timeout", 20)

        def do_bind() -> None:
            self.append_log("开始获取微信扫码二维码。")
            qr = wechat_bot.begin_qr_login(base_url, route_tag=route_tag, timeout=max(timeout, 40))
            qr_url = qr["qr_url"]
            self.append_log(f"微信扫码 URL：{qr_url}")
            self.root.after(0, lambda: self.show_wechat_qr_window(qr_url))
            try:
                webbrowser.open(qr_url)
            except Exception as exc:
                self.append_log(f"打开二维码链接失败：{exc}")
            self.root.after(0, lambda: self.set_action_feedback("请用手机微信扫描/打开二维码，并在手机上确认登录。"))
            result = wechat_bot.poll_qr_login(qr["qr_key"], base_url, route_tag=route_tag, timeout_seconds=wechat_bot.DEFAULT_WECHAT_QR_TIMEOUT_SECONDS)

            def apply_result() -> None:
                self.vars["wechat_bot_token"].set(result.get("token", ""))
                if result.get("base_url"):
                    self.vars["wechat_bot_base_url"].set(result["base_url"])
                if result.get("user_id"):
                    self.vars["wechat_bot_target_user_id"].set(result["user_id"])
                    self.vars["wechat_bot_allowed_user_ids"].set(result["user_id"])
                if result.get("account_id"):
                    self.vars["wechat_bot_account_id"].set(result["account_id"])
                profile = {
                    "label": result.get("user_id") or "WeChat",
                    "token": result.get("token", ""),
                    "base_url": result.get("base_url") or self.vars["wechat_bot_base_url"].get(),
                    "cdn_base_url": self.vars["wechat_bot_cdn_base_url"].get() or "https://novac2c.cdn.weixin.qq.com/c2c",
                    "target_user_id": result.get("user_id", ""),
                    "allowed_user_ids": result.get("user_id", ""),
                    "poll_timeout_ms": self.vars["wechat_bot_poll_timeout_ms"].get() or "35000",
                    "route_tag": self.vars["wechat_bot_route_tag"].get(),
                    "account_id": result.get("account_id") or self.vars["wechat_bot_account_id"].get() or "default",
                }
                profile["id"] = ensure_profile_id("wechat", profile)
                existing = next((index for index, item in enumerate(self.wechat_profiles) if str(item.get("id") or "") == profile["id"]), -1)
                if existing >= 0:
                    self.wechat_profiles[existing] = profile
                    self.selected_wechat_profile_index = existing
                else:
                    self.wechat_profiles.append(profile)
                    self.selected_wechat_profile_index = len(self.wechat_profiles) - 1
                self.refresh_profile_list("wechat")
                self.config = self.collect_config()
                save_config(self.config)
                self.dirty = False
                self.save_state_var.set("配置已保存")
                self.save_state_label.configure(text_color=MUTED)
                self.set_action_feedback("微信扫码绑定成功，配置已保存。请给机器人发一条消息后再测试主动发送。")
                messagebox.showinfo("微信绑定成功", "已回填并保存 WECHAT_BOT_TOKEN 和微信用户 ID。\n\n微信主动发送需要 context_token：请先用目标微信给机器人发一条消息，然后点击测试。测试按钮会自动短轮询缓存这条消息，不需要先启动监听。")

            self.root.after(0, apply_result)

        self.run_background("微信扫码绑定", do_bind, preserve_status=True)

    def show_wechat_qr_window(self, qr_url: str) -> None:
        window = ctk.CTkToplevel(self.root)
        window.title("微信扫码绑定")
        window.geometry("560x240")
        window.transient(self.root)
        window.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            window,
            text="请用手机微信扫描或打开下面的二维码链接，并在手机上确认登录。",
            text_color=TEXT,
            anchor="w",
            wraplength=500,
        ).grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 8))
        textbox = ctk.CTkTextbox(window, height=90, fg_color="#f8fafc", text_color=TEXT, border_width=1, border_color=BORDER)
        textbox.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        textbox.insert("1.0", qr_url)
        textbox.configure(state="disabled")
        ctk.CTkButton(
            window,
            text="在浏览器打开",
            height=34,
            corner_radius=10,
            fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER,
            command=lambda: webbrowser.open(qr_url),
        ).grid(row=2, column=0, sticky="w", padx=18, pady=(0, 16))

    def start_clicked(self) -> None:
        with self.operation_lock:
            if self.starting:
                self.append_log("启动正在进行中，已忽略重复点击。")
                return
            if self.stopping:
                self.append_log("停止正在进行中，请稍后再启动。")
                return
            if self.process and self.process.poll() is None:
                messagebox.showinfo("已经启动", "监听已经在运行。")
                return
            self.starting = True
        self.update_control_states()

        if not self.save_from_ui():
            with self.operation_lock:
                self.starting = False
            self.update_control_states()
            return

        def do_start() -> None:
            try:
                existing = self.stop_watcher_processes()
                if existing:
                    self.append_log(f"已清理遗留监听进程：{', '.join(str(pid) for pid in existing)}。")
                state_missing = not resolved_state_path(self.config).exists()
                should_mark = bool(self.config.get("auto_mark_seen_first_start", True)) and (
                    state_missing or not bool(self.config.get("mark_seen_initialized", False))
                )
                if should_mark:
                    self.append_log("首次启动前先初始化已读，避免历史消息刷屏。")
                    self.mark_seen()
                runtime_config = dict(self.config)
                runtime_config["_log_path"] = str(log_path())
                save_runtime_config(runtime_config)
                log_path().write_text("", encoding="utf-8")
                self.log_offset = 0
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                process = subprocess.Popen(
                    command_for_mode("--watcher-config", str(watcher_config_path())),
                    cwd=str(app_dir()),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    creationflags=creationflags,
                )
                self.process = process
                pid = process.pid
                watcher_pid_path().write_text(str(pid), encoding="utf-8")
                self.append_log(f"监听已启动，PID {pid}。")
                channel_label = "微信 Bot" if str(self.config.get("bot_channel") or "feishu") == "wechat" else "飞书卡片"
                self.root.after(0, lambda: self.set_status(f"运行中 PID {pid}", f"正在监听 NGA 回复和{channel_label}操作"))
            finally:
                with self.operation_lock:
                    self.starting = False
                self.root.after(0, self.update_control_states)

        self.run_background("启动", do_start, preserve_status=True)

    def stop_clicked(self) -> None:
        with self.operation_lock:
            if self.stopping:
                self.append_log("停止正在进行中，已忽略重复点击。")
                return
            if self.starting:
                self.append_log("启动正在进行中，请稍后再停止。")
                return
            self.stopping = True
        self.update_control_states()

        def do_stop() -> None:
            try:
                stopped = self.stop_watcher_processes(include_scan=True)
                if stopped:
                    self.root.after(0, lambda: self.set_status("已停止", "监听已停止"))
                    self.append_log(f"监听已停止，PID {', '.join(str(pid) for pid in stopped)}。")
                else:
                    self.root.after(0, lambda: self.set_status("未启动", "监听未运行"))
                    self.append_log("监听未运行。")
            finally:
                with self.operation_lock:
                    self.stopping = False
                self.root.after(0, self.update_control_states)

        self.run_background("停止", do_stop, preserve_status=True)

    def append_log(self, text: str) -> None:
        if threading.get_ident() != self.ui_thread:
            self.root.after(0, lambda: self.append_log(text))
            return
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{timestamp}] {text}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def poll_logs(self) -> None:
        path = log_path()
        if path.exists():
            try:
                if self.log_offset > path.stat().st_size:
                    self.log_offset = 0
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(self.log_offset)
                    text = f.read()
                    self.log_offset = f.tell()
                lines = text.splitlines()
                if len(lines) > MAX_LOG_LINES_PER_POLL:
                    skipped = len(lines) - MAX_LOG_LINES_PER_POLL
                    lines = lines[-MAX_LOG_LINES_PER_POLL:]
                    self.append_log(f"日志更新较多，已跳过前 {skipped} 行。")
                for line in lines:
                    self.append_log(line)
            except OSError:
                pass
        self.root.after(LOG_POLL_MS, self.poll_logs)

    def poll_process(self) -> None:
        if self.process and self.process.poll() is not None:
            code = self.process.returncode
            self.append_log(f"监听进程已退出，退出码 {code}。")
            self.process = None
            self.set_status("已退出", f"监听进程退出，退出码 {code}")
        self.root.after(1000, self.poll_process)

    def on_close(self) -> None:
        if self.dirty:
            if not messagebox.askyesno("未保存配置", "当前有未保存配置，是否放弃修改并退出？"):
                return
        should_prompt = bool(self.known_watcher_pids(include_scan=False))
        if should_prompt:
            if not messagebox.askyesno("退出", "监听仍在运行，是否停止并退出？"):
                return

            def stop_then_destroy() -> None:
                self.stop_watcher_processes(include_scan=True)
                self.root.after(0, self.root.destroy)

            threading.Thread(target=stop_then_destroy, daemon=True).start()
            return
        self.root.destroy()


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--watcher-config":
        run_watcher_from_config(Path(sys.argv[2]), ws_no_watch="--ws-no-watch" in sys.argv[3:])
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-config":
        with Path(sys.argv[2]).open("r", encoding="utf-8-sig") as f:
            config = json.load(f)
        config["_log_path"] = str(log_path())
        runtime_path = watcher_config_path()
        save_runtime_config(config)
        log_path().write_text("", encoding="utf-8")
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            command_for_mode("--watcher-config", str(runtime_path), "--ws-no-watch"),
            cwd=str(app_dir()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        deadline = time.time() + 15
        while time.time() < deadline:
            code = process.poll()
            if code is not None:
                sys.exit(code or 1)
            time.sleep(0.25)
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        sys.exit(0)

    root = ctk.CTk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
