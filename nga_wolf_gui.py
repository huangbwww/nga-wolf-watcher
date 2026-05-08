from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import traceback
from argparse import Namespace
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

import nga_feishu_watch


APP_TITLE = "NGA Wolf Watcher"
CONFIG_FILE = "nga_wolf_config.json"
RUNTIME_CONFIG_FILE = "nga_wolf_runtime_config.json"
LOG_FILE = "nga_wolf_gui.log"


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


def config_path() -> Path:
    return app_dir() / CONFIG_FILE


def load_config() -> dict[str, object]:
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


def save_config(config: dict[str, object]) -> None:
    path = config_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


def save_runtime_config(config: dict[str, object]) -> None:
    path = watcher_config_path()
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
        f.write("\n")
    tmp.replace(path)


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
        path = app_dir() / path
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


def validate_config(config: dict[str, object]) -> list[str]:
    required = [
        ("nga_cookie", "NGA Cookie"),
        ("feishu_app_id", "Feishu App ID"),
        ("feishu_app_secret", "Feishu App Secret"),
        ("feishu_receive_id", "Feishu Receive ID"),
    ]
    missing = [label for key, label in required if not str(config.get(key) or "").strip()]
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
            missing.append(f"{label}必须是数字")
    return missing


def watcher_config_path() -> Path:
    return app_dir() / RUNTIME_CONFIG_FILE


def log_path() -> Path:
    return app_dir() / LOG_FILE


def command_for_mode(*args: str) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    return [sys.executable, "-u", str(Path(__file__).resolve()), *args]


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
        print("Starting Feishu WebSocket watcher.")
        nga_feishu_watch.start_ws(args)
    except BaseException:
        traceback.print_exc()
        raise


class App:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("900x680")
        self.config = load_config()
        self.process: subprocess.Popen[str] | None = None
        self.log_offset = 0
        self.ui_thread = threading.get_ident()

        self.vars: dict[str, StringVar] = {}
        self.auto_init_var = BooleanVar(value=bool(self.config.get("auto_mark_seen_first_start", True)))
        self.cookie_text: ScrolledText
        self.log_text: ScrolledText
        self.status_var = StringVar(value="未启动")

        self.build_ui()
        self.poll_logs()
        self.poll_process()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        fields = ttk.LabelFrame(outer, text="配置", padding=10)
        fields.grid(row=0, column=0, sticky="ew")
        fields.columnconfigure(1, weight=1)
        fields.columnconfigure(3, weight=1)

        self.cookie_text = ScrolledText(fields, height=4, wrap="word")
        ttk.Label(fields, text="NGA Cookie").grid(row=0, column=0, sticky="nw", padx=(0, 8), pady=4)
        self.cookie_text.grid(row=0, column=1, columnspan=3, sticky="ew", pady=4)
        self.cookie_text.insert("1.0", str(self.config.get("nga_cookie") or ""))

        self.add_entry(fields, "Feishu App ID", "feishu_app_id", 1, 0)
        self.add_entry(fields, "Feishu App Secret", "feishu_app_secret", 1, 2, show="*")
        self.add_entry(fields, "Receive ID", "feishu_receive_id", 2, 0)

        ttk.Label(fields, text="ID Type").grid(row=2, column=2, sticky="w", padx=(16, 8), pady=4)
        id_type = StringVar(value=str(self.config.get("feishu_id_type") or "chat_id"))
        self.vars["feishu_id_type"] = id_type
        ttk.Combobox(fields, textvariable=id_type, values=["chat_id", "open_id", "user_id", "union_id"], width=18).grid(
            row=2, column=3, sticky="ew", pady=4
        )

        self.add_entry(fields, "默认 Author ID", "default_author_id", 3, 0)
        self.add_entry(fields, "默认 Thread ID", "default_tid", 3, 2)
        self.add_entry(fields, "轮询间隔秒", "interval", 4, 0)
        self.add_entry(fields, "随机抖动秒", "jitter", 4, 2)
        self.add_entry(fields, "重试次数", "retries", 5, 0)
        self.add_entry(fields, "重试延迟秒", "retry_delay", 5, 2)
        self.add_entry(fields, "请求超时秒", "timeout", 6, 0)
        self.add_entry(fields, "状态文件", "state_path", 6, 2)

        ttk.Checkbutton(
            fields,
            text="首次启动前自动初始化已读，避免历史消息刷屏",
            variable=self.auto_init_var,
        ).grid(row=7, column=1, columnspan=3, sticky="w", pady=(8, 0))

        log_frame = ttk.LabelFrame(outer, text="运行日志", padding=10)
        log_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = ScrolledText(log_frame, height=16, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")

        controls = ttk.Frame(outer)
        controls.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        controls.columnconfigure(6, weight=1)
        ttk.Button(controls, text="保存配置", command=self.save_from_ui).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(controls, text="初始化已读", command=self.mark_seen_clicked).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(controls, text="查询群组", command=self.list_chats_clicked).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(controls, text="启动监听", command=self.start_clicked).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(controls, text="停止监听", command=self.stop_clicked).grid(row=0, column=4, padx=(0, 8))
        ttk.Button(controls, text="发送测试", command=self.send_test_clicked).grid(row=0, column=5, padx=(0, 8))
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=6, sticky="e")

        self.append_log(f"配置文件: {config_path()}")
        self.append_log(f"状态文件: {resolved_state_path(self.config)}")
        self.append_log(f"日志文件: {log_path()}")

    def add_entry(
        self,
        parent: ttk.Frame,
        label: str,
        key: str,
        row: int,
        col: int,
        *,
        show: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=((0 if col == 0 else 16), 8), pady=4)
        var = StringVar(value=str(self.config.get(key) or ""))
        self.vars[key] = var
        ttk.Entry(parent, textvariable=var, show=show).grid(row=row, column=col + 1, sticky="ew", pady=4)

    def collect_config(self) -> dict[str, object]:
        config = dict(self.config)
        config["nga_cookie"] = self.cookie_text.get("1.0", "end").strip()
        for key, var in self.vars.items():
            config[key] = var.get().strip()
        config["auto_mark_seen_first_start"] = self.auto_init_var.get()
        return config

    def save_from_ui(self) -> bool:
        config = self.collect_config()
        errors = validate_config(config)
        if errors:
            messagebox.showerror("配置不完整", "\n".join(errors))
            return False
        self.config = config
        save_config(self.config)
        self.append_log("配置已保存。")
        self.append_log(f"状态文件: {resolved_state_path(self.config)}")
        return True

    def run_background(self, label: str, target: Callable[[], None]) -> None:
        def wrapper() -> None:
            self.root.after(0, lambda: self.status_var.set(f"{label}中..."))
            try:
                target()
                self.root.after(0, lambda: self.status_var.set("未启动"))
            except Exception as exc:
                self.append_log(f"{label}失败: {exc}")
                self.root.after(0, lambda: self.status_var.set("操作失败"))
                self.root.after(0, lambda: messagebox.showerror("操作失败", str(exc)))

        threading.Thread(target=wrapper, daemon=True).start()

    def mark_seen(self) -> None:
        self.append_log("开始初始化已读。")
        args = build_args(self.config, mark_seen=True)
        count = nga_feishu_watch.run_once(args)
        self.config["mark_seen_initialized"] = True
        save_config(self.config)
        self.append_log(f"初始化已读完成，返回 {count}。")

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

        self.run_background("发送测试", do_send)

    def list_chats_clicked(self) -> None:
        config = self.collect_config()
        app_id = str(config.get("feishu_app_id") or "").strip()
        app_secret = str(config.get("feishu_app_secret") or "").strip()
        if not app_id or not app_secret:
            messagebox.showerror("配置不完整", "请先填写 Feishu App ID 和 Feishu App Secret。")
            return
        self.config = config
        save_config(self.config)

        def do_list() -> None:
            self.append_log("开始查询机器人可见群组。")
            chats = nga_feishu_watch.list_feishu_chats(app_id, app_secret, int_value(self.config, "timeout", 20))
            if not chats:
                self.append_log("未查询到群组。请确认机器人已加入目标群。")
                return
            for chat in chats:
                self.append_log(
                    f"chat_id={chat.get('chat_id', '')} name={chat.get('name', '')} type={chat.get('chat_type', '')}"
                )
            self.append_log(f"共查询到 {len(chats)} 个群组。复制目标群 chat_id 到 Receive ID。")

        self.run_background("查询群组", do_list)

    def start_clicked(self) -> None:
        if self.process and self.process.poll() is None:
            messagebox.showinfo("已经启动", "监听已经在运行。")
            return
        if not self.save_from_ui():
            return

        def do_start() -> None:
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
            self.process = subprocess.Popen(
                command_for_mode("--watcher-config", str(watcher_config_path())),
                cwd=str(app_dir()),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                creationflags=creationflags,
            )
            self.root.after(0, lambda: self.status_var.set(f"运行中 PID {self.process.pid}"))
            self.append_log(f"监听已启动，PID {self.process.pid}。")

        self.run_background("启动", do_start)

    def stop_clicked(self) -> None:
        if not self.process or self.process.poll() is not None:
            self.status_var.set("未启动")
            self.append_log("监听未运行。")
            return
        pid = self.process.pid
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process = None
        self.status_var.set("已停止")
        self.append_log(f"监听已停止，PID {pid}。")

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
                with path.open("r", encoding="utf-8", errors="replace") as f:
                    f.seek(self.log_offset)
                    text = f.read()
                    self.log_offset = f.tell()
                for line in text.splitlines():
                    self.append_log(line)
            except OSError:
                pass
        self.root.after(250, self.poll_logs)

    def poll_process(self) -> None:
        if self.process and self.process.poll() is not None:
            code = self.process.returncode
            self.append_log(f"监听进程已退出，退出码 {code}。")
            self.process = None
            self.status_var.set("已退出")
        self.root.after(1000, self.poll_process)

    def on_close(self) -> None:
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("退出", "监听仍在运行，是否停止并退出？"):
                return
            self.stop_clicked()
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
    root = Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
