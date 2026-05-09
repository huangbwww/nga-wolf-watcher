from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import traceback
import ctypes
from argparse import Namespace
from pathlib import Path
from tkinter import BooleanVar, StringVar, messagebox
from typing import Callable

import customtkinter as ctk

import nga_feishu_watch


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
    "nga_cookie": "",
    "feishu_app_id": "",
    "feishu_app_secret": "",
    "feishu_receive_id": "",
    "feishu_id_type": "chat_id",
    "default_author_id": "150058",
    "default_tid": "45974302",
    "interval": "60",
    "jitter": "20",
    "retries": "10",
    "retry_delay": "2",
    "timeout": "20",
    "state_path": ".nga_seen.json",
    "auto_mark_seen_first_start": True,
    "mark_seen_initialized": False,
}


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
    author_id = str(config.get("default_author_id") or "150058").strip()
    return Namespace(
        author_id=author_id,
        default_author_id=author_id,
        default_tid=str(config.get("default_tid") or "45974302").strip(),
        max_pages=1,
        state_path=str(resolved_state_path(config)),
        cookie=str(config.get("nga_cookie") or "").strip(),
        webhook="",
        secret="",
        feishu_app_id=str(config.get("feishu_app_id") or "").strip(),
        feishu_app_secret=str(config.get("feishu_app_secret") or "").strip(),
        feishu_receive_id=str(config.get("feishu_receive_id") or "").strip(),
        feishu_id_type=str(config.get("feishu_id_type") or "chat_id").strip(),
        timeout=int_value(config, "timeout", 20),
        dry_run=False,
        mark_seen=mark_seen,
        list_feishu_chats=False,
        send_test=False,
        message_format="card",
        disable_commands=False,
        command_lookback=600,
        retries=int_value(config, "retries", 10),
        retry_delay=float_value(config, "retry_delay", 2.0),
        interval=int_value(config, "interval", 60),
        jitter=int_value(config, "jitter", 20),
        once=False,
        ws=ws,
        ws_no_watch=ws_no_watch,
    )


def validate_config(
    config: dict[str, object],
    *,
    require_receive_id: bool = True,
    require_cookie: bool = True,
) -> list[str]:
    required = [
        ("feishu_app_id", "Feishu App ID"),
        ("feishu_app_secret", "Feishu App Secret"),
    ]
    if require_receive_id:
        required.append(("feishu_receive_id", "Receive ID"))
    if require_cookie:
        required.append(("nga_cookie", "NGA Cookie"))
    errors = [label for key, label in required if not str(config.get(key) or "").strip()]
    for key, label in [
        ("interval", "轮询间隔"),
        ("jitter", "随机抖动"),
        ("retries", "重试次数"),
        ("retry_delay", "重试延迟"),
        ("timeout", "请求超时"),
    ]:
        try:
            float_value(config, key, 0)
        except ValueError:
            errors.append(f"{label}必须是数字")
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
        args = build_args(config, ws=True, ws_no_watch=ws_no_watch)
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
                "feishu_app_id",
                "feishu_app_secret",
                "feishu_receive_id",
                "feishu_id_type",
                "default_author_id",
                "default_tid",
                "interval",
                "jitter",
                "retries",
                "retry_delay",
                "timeout",
                "state_path",
            ]
        }
        if not self.vars["feishu_id_type"].get():
            self.vars["feishu_id_type"].set("chat_id")

        self.auto_init_var = BooleanVar(value=bool(self.config.get("auto_mark_seen_first_start", True)))
        self.status_var = StringVar(value="未启动")
        self.status_detail_var = StringVar(value="监听服务尚未运行")
        self.action_feedback_var = StringVar(value="准备就绪")
        self.path_var = StringVar(value=str(config_path()))

        self.pages: dict[str, ctk.CTkBaseClass] = {}
        self.nav_buttons: dict[str, ctk.CTkButton] = {}
        self.current_page: str | None = None
        self.cookie_textboxes: list[ctk.CTkTextbox] = []
        self.chat_result_frames: list[ctk.CTkFrame] = []
        self.syncing_cookie = False
        self.log_text: ctk.CTkTextbox
        self.status_dot: ctk.CTkLabel
        self.status_badge: ctk.CTkLabel
        self.start_button: ctk.CTkButton
        self.stop_button: ctk.CTkButton

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
        self.build_log_page()
        self.build_settings_page()
        self.show_page("quick")

        self.append_log(f"配置文件：{config_path()}")
        self.append_log(f"状态文件：{resolved_state_path(self.config)}")
        self.append_log(f"日志文件：{log_path()}")

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
            ("feishu", "飞书配置", "↗"),
            ("nga", "NGA配置", "◎"),
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
            text="NGA Wolf Watcher\nv1.0.2",
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
        self.feishu_card(page, 1)
        self.nga_card(page, 2)
        self.actions_card(page, 3)
        self.path_card(page, 4)

    def build_feishu_page(self) -> None:
        page = self.make_page("feishu")
        self.page_title(page, "飞书配置", "填写机器人应用凭据，然后在快速开始里查询群组。", 0)
        self.feishu_card(page, 1)
        self.path_card(page, 2)

    def build_nga_page(self) -> None:
        page = self.make_page("nga")
        self.page_title(page, "NGA 配置", "维护 Cookie、默认用户和帖子 ID。", 0)
        self.nga_card(page, 1)
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
            ("重试延迟（秒）", "retry_delay"),
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
        self.path_card(page, 2)

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

    def feishu_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
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
        self.add_entry(frame, "默认用户 ID", "default_author_id", 2)
        self.add_entry(frame, "默认帖子 ID", "default_tid", 3, bottom=True)

    def actions_card(self, parent: ctk.CTkFrame, row: int) -> None:
        frame = self.card(parent, row)
        frame.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="actions")
        self.card_title(frame, "功能操作")
        self.action_tile(frame, 1, 0, "保存配置", "写入本地 AppData", self.save_from_ui)
        self.action_tile(frame, 1, 1, "查询群组", "获取 chat_id", self.list_chats_clicked)
        self.action_tile(frame, 1, 2, "初始化已读", "避免历史刷屏", self.mark_seen_clicked)
        self.action_tile(frame, 1, 3, "发送测试", "验证飞书推送", self.send_test_clicked)
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
        config["auto_mark_seen_first_start"] = self.auto_init_var.get()
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
        self.set_action_feedback(f"配置已保存，状态文件：{resolved_state_path(self.config).name}")
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
                self.root.after(0, lambda: self.set_status(f"运行中 PID {pid}", "正在监听 NGA 回复和飞书卡片操作"))
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
