from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path
from typing import Any

import ai_analysis
import nga_wolf_gui as legacy
import wechat_bot


APP_TITLE = "NGA Wolf Watcher Preview"
_ACTIVE_WINDOW: Any | None = None
_CLOSE_CONFIRMED = False


def _set_active_window(window: Any | None) -> None:
    global _ACTIVE_WINDOW, _CLOSE_CONFIRMED
    _ACTIVE_WINDOW = window
    _CLOSE_CONFIRMED = False


def _request_frontend_close_dialog() -> bool | None:
    if _CLOSE_CONFIRMED:
        return None
    window = _ACTIVE_WINDOW
    if window is None:
        return None

    def show_dialog() -> None:
        time.sleep(0.05)
        try:
            window.evaluate_js(
                "(function(){var el=document.getElementById('nga-close-request-trigger');"
                "if(el){el.click();}})()"
            )
        except Exception:
            pass

    threading.Thread(target=show_dialog, daemon=True).start()
    return False


class WebViewShutdownNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "pywebview":
            return True
        message = record.getMessage()
        exc_text = ""
        if record.exc_info and record.exc_info[1]:
            exc_text = str(record.exc_info[1])
        combined = f"{message}\n{exc_text}"
        if "ObjectDisposedException" in combined and "WebView2" in combined:
            return False
        if "无法访问已释放的对象" in combined and "WebView2" in combined:
            return False
        return True


def resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent


def webui_index_path() -> Path:
    return resource_dir() / "webui" / "dist" / "index.html"


def fallback_html() -> str:
    return """<!doctype html>
<meta charset="utf-8">
<title>NGA Wolf Watcher Preview</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f7fb;color:#111827}
main{max-width:760px;margin:80px auto;padding:32px;background:white;border:1px solid #e5e7eb;border-radius:16px}
code{background:#f3f4f6;padding:2px 6px;border-radius:6px}
</style>
<main>
  <h1>NGA Wolf Watcher Preview</h1>
  <p>The React preview UI has not been built yet.</p>
  <p>Run <code>npm.cmd install</code> and <code>npm.cmd run build</code> in <code>webui</code>, then reopen this preview.</p>
</main>"""


def read_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


class PreviewApi:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.closing = False

    def shutdown(self) -> dict[str, Any]:
        self.closing = True
        return {"ok": True}

    def mark_closing(self) -> None:
        self.closing = True

    def attach_window(self, window: Any) -> None:
        return

    def handle_window_closing(self) -> bool | None:
        self.closing = True
        return None

    def ensure_tray(self) -> bool:
        return False

    def stop_tray(self) -> None:
        return

    def _merged_config(self, value: dict[str, Any] | None = None) -> dict[str, Any]:
        config = legacy.load_config()
        if isinstance(value, dict):
            config.update(value)
        return config

    def _known_pids(self, include_scan: bool = False) -> set[int]:
        pids = legacy.find_watcher_process_ids() if include_scan else set()
        if self.process and self.process.poll() is None:
            pids.add(self.process.pid)
        try:
            raw = legacy.watcher_pid_path().read_text(encoding="utf-8").strip()
            if raw:
                pids.add(int(raw))
        except (OSError, ValueError):
            pass
        pids.discard(os.getpid())
        return pids

    def _stop_processes(self, include_scan: bool = True) -> list[int]:
        stopped: list[int] = []
        for pid in sorted(self._known_pids(include_scan=include_scan)):
            if legacy.kill_process_tree(pid):
                stopped.append(pid)
        if self.process:
            try:
                self.process.wait(timeout=2)
            except Exception:
                pass
        self.process = None
        try:
            legacy.watcher_pid_path().unlink()
        except OSError:
            pass
        return stopped

    def _status(self) -> dict[str, Any]:
        pids = sorted(self._known_pids(include_scan=False))
        return {
            "running": bool(pids),
            "pids": pids,
            "configPath": str(legacy.config_path()),
            "runtimeConfigPath": str(legacy.watcher_config_path()),
            "statePath": str(legacy.resolved_state_path(legacy.load_config())),
            "logPath": str(legacy.log_path()),
            "dataDir": str(legacy.data_dir()),
        }

    def bootstrap(self) -> dict[str, Any]:
        return {
            "config": self._merged_config(),
            "defaults": dict(legacy.DEFAULT_CONFIG),
            "status": self._status(),
            "options": {
                "botChannels": ["feishu", "wechat"],
                "watchModes": ["author", "thread_author", "both"],
                "feishuIdTypes": ["chat_id", "open_id", "union_id", "user_id"],
                "aiProviders": ["codex", "claude", "custom"],
                "aiModels": {
                    "codex": ["default", "auto", *ai_analysis.model_options("codex")],
                    "claude": ["default", "auto", *ai_analysis.model_options("claude")],
                },
                "aiReasoning": {
                    "codex": ["default", *ai_analysis.reasoning_effort_options("codex")],
                    "claude": ["default", *ai_analysis.reasoning_effort_options("claude")],
                },
            },
            "logs": self.read_logs(0),
        }

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        return {"ok": not errors, "errors": errors}

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        if errors:
            return {"ok": False, "errors": errors}
        legacy.save_config(merged)
        return {"ok": True, "config": merged, "status": self._status()}

    def mark_seen(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        if errors:
            return {"ok": False, "errors": errors}
        count = legacy.nga_feishu_watch.run_once(legacy.build_args(merged, mark_seen=True))
        merged["mark_seen_initialized"] = True
        legacy.save_config(merged)
        return {"ok": True, "count": count, "config": merged, "status": self._status()}

    def send_test(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        if errors:
            return {"ok": False, "errors": errors}
        legacy.save_config(merged)
        legacy.nga_feishu_watch.send_test_message(legacy.build_args(merged))
        return {"ok": True, "status": self._status()}

    def query_feishu_chats(self, config: dict[str, Any] | None = None, profile_id: str = "", search_query: str = "") -> dict[str, Any]:
        merged = self._merged_config(config)
        profiles = legacy.load_feishu_profiles(merged)
        profile = next((item for item in profiles if str(item.get("id") or "") == str(profile_id or "")), None)
        if profile is None and profiles:
            profile = profiles[0]
        if profile is None:
            return {"ok": False, "error": "请先添加飞书机器人配置组"}
        app_id = str(profile.get("app_id") or "").strip()
        app_secret = str(profile.get("app_secret") or "").strip()
        if not (app_id and app_secret):
            return {"ok": False, "error": "飞书 App ID 和 App Secret 必填"}
        chats = legacy.nga_feishu_watch.list_feishu_chats(app_id, app_secret, legacy.int_value(merged, "timeout", 20), search_query)
        cleaned = legacy.nga_feishu_watch.merge_feishu_chats(chats)
        for item in profiles:
            if str(item.get("id") or "") == str(profile.get("id") or ""):
                item["chats"] = cleaned
        merged["feishu_bot_profiles"] = json.dumps(profiles, ensure_ascii=False, indent=2)
        try:
            legacy.save_config(merged)
        except PermissionError as exc:
            return {
                "ok": True,
                "config": merged,
                "chats": cleaned,
                "status": self._status(),
                "warning": f"群组已查询成功，但配置文件暂时被占用，未能立即保存：{exc}",
            }
        return {"ok": True, "config": merged, "chats": cleaned, "status": self._status()}

    def send_test_target(self, config: dict[str, Any] | None = None, target_id: str = "") -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged, require_cookie=False)
        if errors:
            non_cookie_errors = [error for error in errors if error != "NGA Cookie"]
            if non_cookie_errors:
                return {"ok": False, "errors": non_cookie_errors}
        args = legacy.build_args(merged)
        target = legacy.nga_feishu_watch.find_push_target(args, target_id)
        if target is None:
            return {"ok": False, "error": "请选择有效推送目标"}
        scoped_args = legacy.nga_feishu_watch.args_for_push_target(args, target)
        if legacy.nga_feishu_watch.is_wechat_channel(scoped_args):
            legacy.nga_feishu_watch.wechat_client_for_args(scoped_args).refresh_context_tokens(
                getattr(scoped_args, "wechat_bot_target_user_id", ""),
                timeout_ms=5000,
                mark_handled=True,
            )
        post = legacy.nga_feishu_watch.NgaPost(
            key="target-test",
            subject="NGA Wolf Watcher 测试消息",
            content=f"这是一条来自推送目标「{target.label or target.id}」的测试消息。",
            url="https://bbs.nga.cn/",
            post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        )
        legacy.nga_feishu_watch.push_channel_posts(scoped_args, [post], "NGA Wolf Watcher 测试消息")
        return {"ok": True, "status": self._status()}

    def bind_wechat(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self._merged_config(config)
        merged["bot_channel"] = "wechat"
        base_url = str(merged.get("wechat_bot_base_url") or wechat_bot.DEFAULT_WECHAT_BASE_URL).strip()
        route_tag = str(merged.get("wechat_bot_route_tag") or "").strip()
        timeout = legacy.int_value(merged, "timeout", 20)
        qr = wechat_bot.begin_qr_login(base_url, route_tag=route_tag, timeout=max(timeout, 40))
        qr_url = str(qr["qr_url"])
        try:
            webbrowser.open(qr_url)
        except Exception:
            pass
        result = wechat_bot.poll_qr_login(
            str(qr["qr_key"]),
            base_url,
            route_tag=route_tag,
            timeout_seconds=wechat_bot.DEFAULT_WECHAT_QR_TIMEOUT_SECONDS,
        )
        merged["wechat_bot_token"] = result.get("token", "")
        if result.get("base_url"):
            merged["wechat_bot_base_url"] = result["base_url"]
        if result.get("user_id"):
            merged["wechat_bot_target_user_id"] = result["user_id"]
            merged["wechat_bot_allowed_user_ids"] = result["user_id"]
        if result.get("account_id"):
            merged["wechat_bot_account_id"] = result["account_id"]
        profile = {
            "label": result.get("user_id") or "WeChat",
            "token": result.get("token", ""),
            "base_url": result.get("base_url") or merged.get("wechat_bot_base_url") or wechat_bot.DEFAULT_WECHAT_BASE_URL,
            "cdn_base_url": merged.get("wechat_bot_cdn_base_url") or wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL,
            "target_user_id": result.get("user_id", ""),
            "allowed_user_ids": result.get("user_id", ""),
            "poll_timeout_ms": str(merged.get("wechat_bot_poll_timeout_ms") or "35000"),
            "route_tag": str(merged.get("wechat_bot_route_tag") or ""),
            "account_id": result.get("account_id") or merged.get("wechat_bot_account_id") or "default",
        }
        profile["id"] = legacy.ensure_profile_id("wechat", profile)
        profiles = legacy.load_wechat_profiles(merged)
        replaced = False
        for index, item in enumerate(profiles):
            if str(item.get("id") or "") == str(profile["id"]):
                profiles[index] = profile
                replaced = True
                break
        if not replaced:
            profiles.append(profile)
        merged["wechat_bot_profiles"] = json.dumps(profiles, ensure_ascii=False, indent=2)
        legacy.save_config(merged)
        return {"ok": True, "config": merged, "qrUrl": qr_url, "status": self._status()}

    def start(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        if errors:
            return {"ok": False, "errors": errors}
        stopped = self._stop_processes(include_scan=True)
        state_missing = not legacy.resolved_state_path(merged).exists()
        should_mark = bool(merged.get("auto_mark_seen_first_start", True)) and (
            state_missing or not bool(merged.get("mark_seen_initialized", False))
        )
        marked_count: int | None = None
        if should_mark:
            marked_count = legacy.nga_feishu_watch.run_once(legacy.build_args(merged, mark_seen=True))
            merged["mark_seen_initialized"] = True
        legacy.save_config(merged)
        runtime_config = dict(merged)
        runtime_config["_log_path"] = str(legacy.log_path())
        legacy.save_runtime_config(runtime_config)
        legacy.log_path().write_text("", encoding="utf-8")
        process = subprocess.Popen(
            legacy.command_for_mode("--watcher-config", str(legacy.watcher_config_path())),
            cwd=str(legacy.app_dir()),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self.process = process
        legacy.watcher_pid_path().write_text(str(process.pid), encoding="utf-8")
        return {
            "ok": True,
            "pid": process.pid,
            "stopped": stopped,
            "markedCount": marked_count,
            "config": merged,
            "status": self._status(),
        }

    def stop(self) -> dict[str, Any]:
        stopped = self._stop_processes(include_scan=True)
        return {"ok": True, "stopped": stopped, "status": self._status()}

    def close_confirmed(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        global _CLOSE_CONFIRMED
        data = payload if isinstance(payload, dict) else {}
        action = str(data.get("action") or "exit").strip().lower()
        if bool(data.get("remember_behavior")) and action in {"minimize", "exit", "ask"}:
            config = self._merged_config()
            config["web_close_behavior"] = action
            try:
                legacy.save_config(config)
            except Exception:
                pass
        if bool(data.get("stop")):
            self._stop_processes(include_scan=True)
        window = _ACTIVE_WINDOW
        if action == "minimize" and window is not None:
            try:
                window.minimize()
            except Exception:
                pass
            return {"ok": True, "action": "minimize", "warning": "系统托盘不可用，已改为最小化窗口。", "status": self._status()}
        _CLOSE_CONFIRMED = True
        self.closing = True
        if window is not None:
            try:
                window.destroy()
            except Exception:
                pass
        return {"ok": True, "action": "exit", "status": self._status()}

    def read_logs(self, offset: int = 0) -> dict[str, Any]:
        if self.closing:
            return {"ok": True, "offset": int(offset or 0), "text": ""}
        path = legacy.log_path()
        if not path.exists():
            return {"ok": True, "offset": 0, "text": ""}
        data = path.read_bytes()
        start = int(offset or 0)
        if start < 0 or start > len(data):
            start = 0
        chunk = data[start:]
        return {"ok": True, "offset": len(data), "text": chunk.decode("utf-8", errors="replace")}

    def status(self) -> dict[str, Any]:
        if self.closing:
            return {"ok": True, "status": {"running": False, "pids": []}}
        return {"ok": True, "status": self._status()}

    def open_data_dir(self) -> dict[str, Any]:
        path = legacy.data_dir()
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(path.as_uri())
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "path": str(path)}


def run_preview() -> None:
    try:
        import webview
    except ImportError as exc:
        raise SystemExit("pywebview is not installed. Run: python -m pip install pywebview") from exc

    api = PreviewApi()
    logging.getLogger("pywebview").addFilter(WebViewShutdownNoiseFilter())
    index_path = webui_index_path()
    if index_path.exists():
        window = webview.create_window(APP_TITLE, index_path.as_uri(), js_api=api, width=1180, height=780, min_size=(980, 680))
    else:
        window = webview.create_window(APP_TITLE, html=fallback_html(), js_api=api, width=900, height=560, min_size=(720, 480))
    _set_active_window(window)
    window.events.closing += _request_frontend_close_dialog
    window.events.closed += api.mark_closing
    window.events.closed += lambda: _set_active_window(None)
    webview.start(debug=bool(os.getenv("NGA_WEBGUI_DEBUG")))


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--watcher-config":
        legacy.run_watcher_from_config(Path(sys.argv[2]), ws_no_watch="--ws-no-watch" in sys.argv[3:])
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-config":
        with Path(sys.argv[2]).open("r", encoding="utf-8-sig") as f:
            config = json.load(f)
        errors = legacy.validate_config(config)
        if errors:
            print("\n".join(errors), file=sys.stderr)
            raise SystemExit(2)
        print("OK")
        return
    try:
        run_preview()
    except BaseException:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
