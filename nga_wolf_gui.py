from __future__ import annotations

import json
import os
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
from typing import Callable

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


DEFAULT_CONFIG = {
    "bot_channel": "feishu",
    "nga_cookie": "",
    "feishu_app_id": "",
    "feishu_app_secret": "",
    "feishu_receive_id": "",
    "feishu_id_type": "chat_id",
    "wechat_bot_token": "",
    "wechat_bot_base_url": "https://ilinkai.weixin.qq.com",
    "wechat_bot_cdn_base_url": "https://novac2c.cdn.weixin.qq.com/c2c",
    "wechat_bot_target_user_id": "",
    "wechat_bot_allowed_user_ids": "",
    "wechat_bot_poll_timeout_ms": "35000",
    "wechat_bot_route_tag": "",
    "wechat_bot_account_id": "default",
    "default_author_id": "150058",
    "default_tid": "45974302",
    "watch_author_ids": "",
    "preset_thread_ids": "",
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
    "ai_custom_command": "",
    "ai_model": "",
    "ai_reasoning_effort": "default",
    "ai_ignore_codex_user_config": True,
    "ai_schedule_enabled": False,
    "ai_schedule_interval_minutes": "5",
    "ai_schedule_prompt": "",
    "ai_schedule_window_mode": "a_share",
    "ai_schedule_windows": "weekday:09:30-11:30,13:00-15:00",
    "ai_allowed_user_ids": "",
    "ai_send_errors_to_feishu": False,
    "ai_max_feishu_chars": "3500",
    "ai_upload_long_result": False,
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
    tmp.replace(path)


def save_config(config: dict[str, object]) -> None:
    write_json(config_path(), config)


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
        watch_author_ids=watch_author_ids,
        default_author_id=author_id,
        default_tid=default_tid,
        preset_thread_ids=preset_thread_ids,
        max_pages=1,
        state_path=str(resolved_state_path(config)),
        cookie=str(config.get("nga_cookie") or "").strip(),
        webhook="",
        secret="",
        feishu_app_id=str(config.get("feishu_app_id") or "").strip(),
        feishu_app_secret=str(config.get("feishu_app_secret") or "").strip(),
        feishu_receive_id=str(config.get("feishu_receive_id") or "").strip(),
        feishu_id_type=str(config.get("feishu_id_type") or "chat_id").strip(),
        wechat_bot_token=str(config.get("wechat_bot_token") or "").strip(),
        wechat_bot_base_url=str(config.get("wechat_bot_base_url") or "https://ilinkai.weixin.qq.com").strip(),
        wechat_bot_cdn_base_url=str(config.get("wechat_bot_cdn_base_url") or "https://novac2c.cdn.weixin.qq.com/c2c").strip(),
        wechat_bot_target_user_id=str(config.get("wechat_bot_target_user_id") or "").strip(),
        wechat_bot_allowed_user_ids=str(config.get("wechat_bot_allowed_user_ids") or "").strip(),
        wechat_bot_poll_timeout_ms=int_value(config, "wechat_bot_poll_timeout_ms", 35000),
        wechat_bot_route_tag=str(config.get("wechat_bot_route_tag") or "").strip(),
        wechat_bot_account_id=str(config.get("wechat_bot_account_id") or "default").strip(),
        wechat_bot_state_dir="",
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
        ai_custom_command=str(config.get("ai_custom_command") or "").strip(),
        ai_model=str(config.get("ai_model") or "").strip(),
        ai_reasoning_effort=str(config.get("ai_reasoning_effort") or "").strip(),
        ai_ignore_codex_user_config=bool(config.get("ai_ignore_codex_user_config", True)),
        ai_schedule_enabled=bool(config.get("ai_schedule_enabled", False)),
        ai_schedule_interval_minutes=int_value(config, "ai_schedule_interval_minutes", 5),
        ai_schedule_prompt=str(config.get("ai_schedule_prompt") or "").strip(),
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
    if channel == "feishu":
        required.extend(
            [
                ("feishu_app_id", "Feishu App ID"),
                ("feishu_app_secret", "Feishu App Secret"),
            ]
        )
        if require_receive_id:
            required.append(("feishu_receive_id", "Receive ID"))
    else:
        required.append(("wechat_bot_token", "微信 Bot Token"))
        if require_receive_id:
            required.append(("wechat_bot_target_user_id", "微信目标用户 ID"))
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
    for key, label in [
        ("interval", "轮询间隔"),
        ("jitter", "随机抖动"),
        ("retries", "重试次数"),
        ("retry_initial_delay", "重试初始等待"),
        ("retry_delay", "重试延迟"),
        ("nga_request_min_interval", "NGA 请求最小间隔"),
        ("nga_cache_ttl", "NGA 短缓存"),
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
    if provider not in {"codex", "claude", "custom"}:
        errors.append("AI Provider 必须是 codex、claude 或 custom")
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


def find_watcher_process_ids() -> set[int]:
    if sys.platform != "win32":
        return set()
    script = """
$own = $PID
Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $own -and
    ($_.Name -ieq 'python.exe' -or $_.Name -ieq 'pythonw.exe' -or $_.Name -ieq 'NGA-Wolf-Watcher.exe') -and
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
        self.ai_ignore_codex_user_config_var = BooleanVar(value=bool(self.config.get("ai_ignore_codex_user_config", True)))
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
        self.actions_card(page, 5)
        self.path_card(page, 6)

    def build_feishu_page(self) -> None:
        page = self.make_page("feishu")
        self.page_title(page, "消息通道配置", "选择飞书或微信；只需要填写当前通道的配置。", 0)
        self.channel_card(page, 1)
        self.feishu_card(page, 2)
        self.wechat_card(page, 3)
        self.path_card(page, 4)
        self.update_channel_visibility()

    def build_nga_page(self) -> None:
        page = self.make_page("nga")
        self.page_title(page, "NGA 配置", "维护 Cookie、默认用户和帖子 ID。", 0)
        self.nga_card(page, 1)
        self.path_card(page, 2)

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
            ("随机抖动（秒）", "jitter"),
            ("重试次数", "retries"),
            ("重试初始等待（秒）", "retry_initial_delay"),
            ("重试递增步长（秒）", "retry_delay"),
            ("NGA 请求最小间隔（秒）", "nga_request_min_interval"),
            ("NGA 短缓存（秒）", "nga_cache_ttl"),
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
            variable=self.vars["bot_channel"],
            values=["feishu", "wechat"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
            command=lambda _value: self.update_channel_visibility(),
        ).grid(row=1, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))
        ctk.CTkLabel(
            frame,
            text="选飞书就只校验飞书配置；选微信就只校验微信配置。NGA 和 AI 设置是公共设置。",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12),
        ).grid(row=2, column=0, columnspan=2, sticky="ew", padx=16, pady=(0, 14))
        return frame

    def update_channel_visibility(self) -> None:
        if not hasattr(self, "feishu_frames"):
            return
        channel = self.vars.get("bot_channel").get() if "bot_channel" in self.vars else "feishu"
        for frame in self.feishu_frames:
            if channel == "wechat":
                frame.grid_remove()
            else:
                frame.grid()
        for frame in self.wechat_frames:
            if channel == "wechat":
                frame.grid()
            else:
                frame.grid_remove()

    def feishu_card(self, parent: ctk.CTkFrame, row: int) -> ctk.CTkFrame:
        frame = self.card(parent, row)
        self.feishu_frames.append(frame)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "飞书应用配置")
        self.add_entry(frame, "App ID", "feishu_app_id", 1)
        self.add_entry(frame, "App Secret", "feishu_app_secret", 2, show="*")
        self.add_entry(frame, "Receive ID", "feishu_receive_id", 3)
        ctk.CTkLabel(frame, text="ID Type", anchor="w", text_color=TEXT).grid(row=4, column=0, sticky="w", padx=16, pady=(6, 8))
        ctk.CTkOptionMenu(
            frame,
            variable=self.vars["feishu_id_type"],
            values=["chat_id", "open_id", "user_id", "union_id"],
            height=34,
            fg_color="#f8fafc",
            button_color="#e2e8f0",
            button_hover_color="#cbd5e1",
            text_color=TEXT,
        ).grid(row=4, column=1, sticky="ew", padx=(0, 16), pady=(6, 8))

        ctk.CTkLabel(
            frame,
            text="群组查询结果",
            anchor="w",
            text_color=MUTED,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).grid(row=5, column=0, sticky="nw", padx=16, pady=(8, 16))
        result_frame = ctk.CTkFrame(frame, fg_color="#f8fafc", corner_radius=10, border_width=1, border_color=BORDER)
        result_frame.grid(row=5, column=1, sticky="ew", padx=(0, 16), pady=(8, 16))
        result_frame.grid_columnconfigure(0, weight=1)
        self.chat_result_frames.append(result_frame)
        self.render_chat_results([])
        return frame

    def wechat_card(self, parent: ctk.CTkFrame, row: int) -> ctk.CTkFrame:
        frame = self.card(parent, row)
        self.wechat_frames.append(frame)
        frame.grid_columnconfigure(1, weight=1)
        self.card_title(frame, "微信 Bot 配置")
        self.add_entry(frame, "Bot Token", "wechat_bot_token", 1, show="*")
        self.add_entry(frame, "Base URL", "wechat_bot_base_url", 2)
        self.add_entry(frame, "CDN Base URL", "wechat_bot_cdn_base_url", 3)
        self.add_entry(frame, "目标用户 ID", "wechat_bot_target_user_id", 4)
        self.add_entry(frame, "允许用户 ID", "wechat_bot_allowed_user_ids", 5)
        self.add_entry(frame, "轮询超时(ms)", "wechat_bot_poll_timeout_ms", 6)
        self.add_entry(frame, "Route Tag", "wechat_bot_route_tag", 7)
        self.add_entry(frame, "Account ID", "wechat_bot_account_id", 8)
        bind_row = ctk.CTkFrame(frame, fg_color="transparent")
        bind_row.grid(row=9, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 8))
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
        ).grid(row=10, column=0, columnspan=2, sticky="ew", padx=16, pady=(4, 16))
        return frame

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
        self.add_target_list_editor(frame, "监听用户 ID 列表", "watch_author_ids", 2, fallback_key="default_author_id")
        self.add_target_list_editor(frame, "帖子预设 ID 列表", "preset_thread_ids", 3, fallback_key="default_tid", bottom=True)

    def actions_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="actions")
        self.card_title(frame, "功能操作")
        self.action_tile(frame, 1, 0, "查询群组", "获取 chat_id", self.list_chats_clicked)
        self.action_tile(frame, 1, 1, "初始化已读", "避免历史刷屏", self.mark_seen_clicked)
        self.action_tile(frame, 1, 2, "发送测试", "验证飞书推送", self.send_test_clicked)
        feedback = ctk.CTkFrame(frame, fg_color="#f8fafc", corner_radius=10, border_width=1, border_color=BORDER)
        feedback.grid(row=2, column=0, columnspan=4, sticky="ew", padx=16, pady=(0, 16))
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
            values=["codex", "claude", "custom"],
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
        ctk.CTkSwitch(
            frame,
            text="忽略 Codex 用户配置",
            variable=self.ai_ignore_codex_user_config_var,
            fg_color="#cbd5e1",
            progress_color=PRIMARY,
            button_color="#ffffff",
            text_color=TEXT,
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=16, pady=(6, 8))
        fields = [
            ("自动分析 Prompt", "ai_auto_analysis_prompt"),
            ("AI 工作目录", "ai_work_dir"),
            ("AI 超时(秒)", "ai_timeout"),
            ("Codex 命令", "ai_codex_command"),
            ("Claude 命令", "ai_claude_command"),
            ("Custom 命令模板", "ai_custom_command"),
            ("定时间隔(分钟)", "ai_schedule_interval_minutes"),
            ("定时 Prompt", "ai_schedule_prompt"),
            ("允许用户 ID", "ai_allowed_user_ids"),
            ("飞书最大字符", "ai_max_feishu_chars"),
        ]
        for offset, (label, key) in enumerate(fields, start=7):
            self.add_entry(frame, label, key, offset)
        window_row = 7 + len(fields)
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
        switch_row = window_row + 1
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
        if provider in {"codex", "claude"}:
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
            listbox.insert(END, f"{index}. {nga_feishu_watch.target_display_name(target)}")

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
                lines.append(f"{target.id}={target.label}")
            else:
                lines.append(target.id)
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

    def target_dialog(self, key: str, label: str, edit_index: int | None = None) -> None:
        targets = self.target_lists.setdefault(key, [])
        editing = edit_index is not None and 0 <= edit_index < len(targets)
        current = targets[edit_index] if editing and edit_index is not None else None

        window = ctk.CTkToplevel(self.root)
        window.title("编辑条目" if editing else f"添加{label}")
        window.geometry("420x210")
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
            target = nga_feishu_watch.WatchTarget(target_id, note)
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
                    text="暂无查询结果。点击“查询群组”后会显示机器人可见群组。",
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
                ctk.CTkButton(
                    row,
                    text="填入",
                    width=58,
                    height=30,
                    corner_radius=8,
                    fg_color="#eef2ff",
                    hover_color="#dbeafe",
                    text_color=PRIMARY,
                    command=lambda cid=chat_id: self.set_receive_id(cid),
                ).grid(row=0, column=1, rowspan=2, sticky="e", padx=10, pady=8)

    def collect_config(self) -> dict[str, object]:
        config = dict(self.config)
        config["nga_cookie"] = self.cookie_textboxes[0].get("1.0", "end").strip() if self.cookie_textboxes else ""
        for key, var in self.vars.items():
            config[key] = var.get().strip()
        for key in self.target_lists:
            config[key] = self.target_list_config_text(key)
        author_targets = nga_feishu_watch.parse_target_list(config.get("watch_author_ids"), str(config.get("default_author_id") or "150058").strip())
        thread_targets = nga_feishu_watch.parse_target_list(config.get("preset_thread_ids"), str(config.get("default_tid") or "45974302").strip())
        if author_targets:
            config["default_author_id"] = author_targets[0].id
            if not str(config.get("watch_author_ids") or "").strip():
                config["watch_author_ids"] = author_targets[0].id
        if thread_targets:
            config["default_tid"] = thread_targets[0].id
            if not str(config.get("preset_thread_ids") or "").strip():
                config["preset_thread_ids"] = thread_targets[0].id
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
        pids = find_watcher_process_ids() if include_scan else set()
        if self.process and self.process.poll() is None:
            pids.add(self.process.pid)
        try:
            raw = watcher_pid_path().read_text(encoding="utf-8").strip()
            if raw:
                pids.add(int(raw))
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
        app_id = str(self.config.get("feishu_app_id") or "").strip()
        app_secret = str(self.config.get("feishu_app_secret") or "").strip()

        def do_list() -> None:
            self.append_log("开始查询机器人可见群组。")
            chats = nga_feishu_watch.list_feishu_chats(app_id, app_secret, int_value(self.config, "timeout", 20))
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
            self.root.after(0, lambda found=chats: self.render_chat_results(found))
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
                self.mark_dirty()
                self.set_action_feedback("微信扫码绑定成功，已回填配置。请保存配置后启动监听。")
                messagebox.showinfo("微信绑定成功", "已回填 WECHAT_BOT_TOKEN 和微信用户 ID。\n\n请点击“保存配置”，然后启动监听。首次主动推送前，建议再给机器人发一条消息完成 context_token 缓存。")

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
