from __future__ import annotations

import json
import logging
import os
import shutil
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


APP_TITLE = "NGA Wolf Watcher"
_ACTIVE_WINDOW: Any | None = None
_CLOSE_CONFIRMED = False
_TRAY_ICON: Any | None = None
_TRAY_LOCK = threading.Lock()


def _set_active_window(window: Any | None) -> None:
    global _ACTIVE_WINDOW, _CLOSE_CONFIRMED
    _ACTIVE_WINDOW = window
    _CLOSE_CONFIRMED = False


def _request_frontend_close_dialog() -> bool | None:
    if _CLOSE_CONFIRMED:
        return None
    _trigger_frontend_close("nga-close-request-trigger")
    return False


def _trigger_frontend_close(element_id: str) -> None:
    window = _ACTIVE_WINDOW
    if window is None:
        return

    def show_dialog() -> None:
        time.sleep(0.05)
        try:
            window.show()
            window.restore()
        except Exception:
            pass
        try:
            window.evaluate_js(
                f"(function(){{var el=document.getElementById('{element_id}');"
                "if(el){el.click();}})()"
            )
        except Exception:
            pass

    threading.Thread(target=show_dialog, daemon=True).start()


def _load_tray_image() -> Any | None:
    try:
        from PIL import Image
    except ImportError:
        return None
    for path in (resource_dir() / "assets" / "app_icon.png", app_icon_path()):
        if not path.exists():
            continue
        try:
            return Image.open(path).convert("RGBA")
        except Exception:
            continue
    return None


def _ensure_tray_icon(api: "PreviewApi") -> bool:
    global _TRAY_ICON
    with _TRAY_LOCK:
        if _TRAY_ICON is not None:
            return True
        try:
            import pystray
        except ImportError:
            return False
        image = _load_tray_image()
        if image is None:
            return False

        def show_window(icon: Any = None, item: Any = None) -> None:
            window = _ACTIVE_WINDOW
            if window is None:
                return
            try:
                window.show()
                window.restore()
            except Exception:
                pass

        def request_exit(icon: Any = None, item: Any = None) -> None:
            _trigger_frontend_close("nga-tray-exit-trigger")

        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", show_window, default=True),
            pystray.MenuItem("退出程序", request_exit),
        )
        _TRAY_ICON = pystray.Icon("NGA Wolf Watcher", image, APP_TITLE, menu)
        threading.Thread(target=_TRAY_ICON.run, daemon=True).start()
        return True


def _stop_tray_icon() -> None:
    global _TRAY_ICON
    with _TRAY_LOCK:
        icon = _TRAY_ICON
        _TRAY_ICON = None
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass


def _pid_has_watcher_config(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    if sys.platform != "win32":
        return legacy.process_exists(pid)
    script = (
        "$p = Get-CimInstance Win32_Process -Filter \"ProcessId = "
        + str(int(pid))
        + "\" -ErrorAction SilentlyContinue; "
        "$cmd = if ($p) { [string]$p.CommandLine } else { '' }; "
        "if ($cmd -like '*--watcher-config*') { '1' }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        return False
    return result.stdout.strip() == "1"


class WebViewShutdownNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "pywebview":
            return True
        message = record.getMessage()
        exc_text = ""
        if record.exc_info and record.exc_info[1]:
            exc_text = str(record.exc_info[1])
        combined = f"{message}\n{exc_text}"
        if "Failed to delete user data folder" in combined:
            return False
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


def app_icon_path() -> Path:
    return resource_dir() / "assets" / "app_icon.ico"


def fallback_html() -> str:
    return """<!doctype html>
<meta charset="utf-8">
<title>NGA Wolf Watcher</title>
<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f5f7fb;color:#111827}
main{max-width:760px;margin:80px auto;padding:32px;background:white;border:1px solid #e5e7eb;border-radius:16px}
code{background:#f3f4f6;padding:2px 6px;border-radius:6px}
</style>
<main>
  <h1>NGA Wolf Watcher</h1>
  <p>The React UI has not been built yet.</p>
  <p>Run <code>npm.cmd install</code> once if dependencies are missing, then run <code>npm.cmd run build</code> in <code>webui</code> and reopen this app.</p>
</main>"""


def build_webui_if_needed(index_path: Path) -> None:
    if index_path.exists() or getattr(sys, "frozen", False):
        return
    webui_dir = resource_dir() / "webui"
    package_lock = webui_dir / "package-lock.json"
    package_json = webui_dir / "package.json"
    if not package_json.exists() or not package_lock.exists():
        return
    node_modules = webui_dir / "node_modules"
    npm = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if not npm:
        return
    env = os.environ.copy()
    env.setdefault("CI", "1")
    try:
        if not node_modules.exists():
            if str(env.get("NGA_WEBGUI_AUTO_INSTALL") or "").strip().lower() not in {"1", "true", "yes", "on"}:
                logging.info("webui/dist is missing and webui/node_modules is not installed; skip automatic npm install")
                return
            subprocess.run([npm, "ci"], cwd=webui_dir, check=True, env=env)
        subprocess.run([npm, "run", "build"], cwd=webui_dir, check=True, env=env)
    except Exception:
        logging.exception("Failed to build web UI")


def read_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = legacy.nga_wolf_config.load_jsonc(f.read())
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def webui_preflight_errors(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    channel = str(config.get("bot_channel") or "feishu").strip().lower()
    if channel not in {"feishu", "wechat", "dingtalk", "email", "wxpusher"}:
        channel = "feishu"

    feishu_profiles = legacy.load_feishu_profiles(config)
    wechat_profiles = legacy.load_wechat_profiles(config)
    dingtalk_profiles = legacy.load_dingtalk_profiles(config)
    email_profiles = legacy.load_email_profiles(config)
    wxpusher_profiles = legacy.load_wxpusher_profiles(config)
    has_feishu = any(
        str(profile.get("app_id") or "").strip() and str(profile.get("app_secret") or "").strip()
        for profile in feishu_profiles
    )
    has_wechat = any(str(profile.get("token") or "").strip() for profile in wechat_profiles)
    has_dingtalk = any(str(profile.get("client_id") or "").strip() and str(profile.get("client_secret") or "").strip() for profile in dingtalk_profiles)
    has_email = any(
        str(profile.get("username") or "").strip() and str(profile.get("password") or "").strip()
        for profile in email_profiles
    )
    has_wxpusher = any(
        str(profile.get("spts") or "").strip() or str(profile.get("app_token") or "").strip()
        for profile in wxpusher_profiles
    )
    if channel == "wechat":
        if not has_wechat:
            errors.append("请先配置一个微信Bot配置")
    elif channel == "dingtalk":
        if not has_dingtalk:
            errors.append("请先配置一个钉钉机器人配置")
    elif channel == "email":
        if not has_email:
            errors.append("请先配置一个邮箱发信配置")
    elif channel == "wxpusher":
        if not has_wxpusher:
            errors.append("请先配置一个 WxPusher 配置")
    elif not has_feishu:
        errors.append("请先配置一个飞书配置")

    if not str(config.get("nga_cookie") or "").strip():
        errors.append("缺少 NGA Cookie")
    if not legacy.nga_feishu_watch.parse_target_list(config.get("watch_author_ids"), ""):
        errors.append("请先配置一条用户 ID")
    if not legacy.nga_feishu_watch.parse_target_list(config.get("preset_thread_ids"), ""):
        errors.append("请先配置一条帖子 ID")
    if not legacy.nga_feishu_watch.parse_listen_rules(config.get("listen_rules")):
        errors.append("缺少可用的监听配置")
    return errors


def webui_friendly_errors(config: dict[str, Any], errors: list[str], include_preflight: bool = False) -> list[str]:
    friendly: list[str] = []
    if include_preflight:
        friendly.extend(webui_preflight_errors(config))

    for error in errors:
        text = str(error or "").strip()
        if not text:
            continue
        if text in {"Feishu App ID", "Feishu App Secret", "Receive ID"} or "飞书机器人缺少 App ID" in text or "飞书机器人缺少 App ID 或 App Secret" in text:
            friendly.append("请先配置一个飞书配置")
        elif text in {"WxPusher SPT", "WxPusher App Token", "WxPusher UID 或 Topic ID"} or "WxPusher" in text:
            friendly.append("请先配置一个 WxPusher 配置，并填写 SPT")
        elif text in {"微信 Bot Token", "微信目标用户 ID"} or "微信机器人缺少 Token" in text:
            friendly.append("请先配置一个微信Bot配置")
        elif text == "NGA Cookie":
            friendly.append("缺少 NGA Cookie")
        elif text.startswith("监听用户 ID 列表 包含非数字 ID"):
            bad_id = text.rsplit("：", 1)[-1]
            friendly.append(f"用户 ID 只能填写数字：{bad_id}")
        elif text.startswith("帖子预设 ID 列表 包含非数字 ID"):
            bad_id = text.rsplit("：", 1)[-1]
            friendly.append(f"帖子 ID 只能填写数字：{bad_id}")
        elif "帖内作者监听模式需要至少一条" in text or "至少需要选择一个发送目标" in text:
            friendly.append("缺少可用的监听配置")
        elif text.startswith("监听规则") and "包含非数字 NGA ID" in text:
            friendly.append("监听规则里的用户 ID 和帖子 ID 只能填写数字")
        elif text.startswith("监听规则") and "选择了不存在的发送目标" in text:
            friendly.append("监听规则选择了不存在的发送目标，请重新选择发送位置")
        elif text.startswith("发送目标") and "缺少飞书群 chat_id" in text:
            friendly.append("发送目标缺少飞书群，请在监听规则里选择一个群")
        elif text.startswith("发送目标") and "未选择有效飞书机器人" in text:
            friendly.append("请先配置一个飞书配置")
        elif text.startswith("发送目标") and "未选择有效微信机器人" in text:
            friendly.append("请先配置一个微信Bot配置")
        elif "默认飞书 Receive ID" in text:
            friendly.append("缺少可用的监听配置，请在监听规则里选择发送目标")
        else:
            friendly.append(text)

    deduped: list[str] = []
    seen: set[str] = set()
    for error in friendly:
        if error not in seen:
            deduped.append(error)
            seen.add(error)
    return deduped


def _is_send_test_ignorable_validation_error(error: Any) -> bool:
    text = str(error or "").strip()
    return (
        text == "NGA Cookie"
        or text.startswith("监听规则 ")
        or text.startswith("监听用户 ID 列表")
        or text.startswith("帖子预设 ID 列表")
        or "存在未单独选择通道的监听项" in text
        or "帖内作者监听模式需要至少一条" in text
    )


def _first_target_id(raw: Any, fallback: str = "") -> str:
    targets = legacy.nga_feishu_watch.parse_target_list(raw, "")
    if targets:
        return str(targets[0].id or "").strip()
    return str(fallback or "").strip()


def _cookie_value(cookie: str, name: str) -> str:
    wanted = name.lower()
    for part in str(cookie or "").split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip().lower() == wanted:
            return value.strip()
    return ""


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
        return _ensure_tray_icon(self)

    def stop_tray(self) -> None:
        _stop_tray_icon()

    def _merged_config(self, value: dict[str, Any] | None = None) -> dict[str, Any]:
        config = legacy.load_config()
        if isinstance(value, dict):
            config.update(value)
        return config

    def _known_pids(self, include_scan: bool = False) -> set[int]:
        scanned_pids = legacy.find_watcher_process_ids() if include_scan else set()
        pids = set(scanned_pids)
        live_process_pid = 0
        if self.process and self.process.poll() is None:
            live_process_pid = int(self.process.pid)
            pids.add(live_process_pid)
        elif self.process and self.process.poll() is not None:
            self.process = None
        try:
            raw = legacy.watcher_pid_path().read_text(encoding="utf-8").strip()
            if raw:
                pid = int(raw)
                if pid in scanned_pids or pid == live_process_pid or (not include_scan and _pid_has_watcher_config(pid)):
                    pids.add(pid)
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
                "aiProviders": ["codex", "claude", "codewhale", "custom"],
                "aiModels": {
                    "codex": ai_analysis.model_options("codex"),
                    "claude": ai_analysis.model_options("claude"),
                    "codewhale": ai_analysis.model_options("codewhale"),
                },
                "aiReasoning": {
                    "codex": ai_analysis.reasoning_effort_options("codex"),
                    "claude": ai_analysis.reasoning_effort_options("claude"),
                    "codewhale": ai_analysis.reasoning_effort_options("codewhale"),
                },
            },
            "logs": self.read_logs(0),
        }

    def validate(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        friendly_errors = webui_friendly_errors(merged, errors, include_preflight=True)
        return {"ok": not friendly_errors, "errors": friendly_errors}

    def save_config(self, config: dict[str, Any]) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        if errors:
            return {"ok": False, "errors": webui_friendly_errors(merged, errors)}
        legacy.save_config(merged)
        return {"ok": True, "config": merged, "status": self._status()}

    def mark_seen(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        if errors:
            return {"ok": False, "errors": webui_friendly_errors(merged, errors)}
        count = legacy.nga_feishu_watch.run_once(legacy.build_args(merged, mark_seen=True))
        merged["mark_seen_initialized"] = True
        legacy.save_config(merged)
        return {"ok": True, "count": count, "config": merged, "status": self._status()}

    def send_test(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged)
        if errors:
            return {"ok": False, "errors": webui_friendly_errors(merged, errors)}
        legacy.save_config(merged)
        legacy.nga_feishu_watch.send_test_message(legacy.build_args(merged))
        return {"ok": True, "status": self._status()}

    def check_nga_cookie(self, config: dict[str, Any] | None = None) -> dict[str, Any]:
        merged = self._merged_config(config)
        cookie = str(merged.get("nga_cookie") or "").strip()
        if not cookie:
            return {"ok": False, "error": "缺少 NGA Cookie"}
        lower_cookie = cookie.lower()
        if "ngapassportuid=" not in lower_cookie or "ngapassportcid=" not in lower_cookie:
            return {
                "ok": False,
                "error": "Cookie 中缺少 ngaPassportUid 或 ngaPassportCid，请复制登录后的完整 NGA Cookie",
            }

        expected_uid = _cookie_value(cookie, "ngaPassportUid")
        tid = _first_target_id(merged.get("preset_thread_ids"), str(merged.get("default_tid") or "45974302"))
        if not tid.isdigit():
            return {"ok": False, "error": f"帖子 ID 只能填写数字：{tid}"}
        try:
            payload = legacy.nga_feishu_watch.fetch_nga_thread_page(
                tid,
                1,
                cookie,
                legacy.int_value(merged, "timeout", 20),
                0,
                0,
            )
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            current_user = data.get("__CU", {}) if isinstance(data, dict) else {}
            current_uid = str(current_user.get("uid") or "").strip() if isinstance(current_user, dict) else ""
        except Exception as exc:
            return {"ok": False, "error": f"NGA Cookie 检测失败：{exc}"}
        if not current_uid or current_uid == "0":
            return {"ok": False, "error": "NGA 请求成功，但服务器没有识别到登录态，请重新复制登录后的完整 Cookie"}
        if expected_uid and current_uid != expected_uid:
            return {
                "ok": False,
                "error": f"NGA 请求成功，但识别到的 UID 是 {current_uid}，和 Cookie 里的 {expected_uid} 不一致",
            }
        return {"ok": True, "message": f"NGA Cookie 可用。已通过帖子 {tid} 验证登录 UID：{current_uid}。"}

    def query_feishu_chats(self, config: dict[str, Any] | None = None, profile_id: str = "") -> dict[str, Any]:
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
        chats = legacy.nga_feishu_watch.list_feishu_chats(app_id, app_secret, legacy.int_value(merged, "timeout", 20))
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

    def query_feishu_chats_for_profile(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        data = profile if isinstance(profile, dict) else {}
        app_id = str(data.get("app_id") or "").strip()
        app_secret = str(data.get("app_secret") or "").strip()
        if not (app_id and app_secret):
            return {"ok": False, "error": "请先填写飞书 App ID 和 App Secret。"}
        merged = self._merged_config()
        chats = legacy.nga_feishu_watch.list_feishu_chats(app_id, app_secret, legacy.int_value(merged, "timeout", 20))
        cleaned = legacy.nga_feishu_watch.merge_feishu_chats(chats)
        return {"ok": True, "chats": cleaned, "status": self._status()}

    def recent_dingtalk_user_for_profile(self, profile: dict[str, Any] | None = None) -> dict[str, Any]:
        data = profile if isinstance(profile, dict) else {}
        merged = self._merged_config()
        if data:
            merged["dingtalk_client_id"] = str(data.get("client_id") or "").strip()
            merged["dingtalk_client_secret"] = str(data.get("client_secret") or "").strip()
            merged["dingtalk_robot_code"] = str(data.get("robot_code") or "").strip()
            merged["dingtalk_target_user_ids"] = str(data.get("target_user_ids") or "").strip()
            merged["dingtalk_allowed_user_ids"] = str(data.get("allowed_user_ids") or "").strip()
            merged["dingtalk_account_id"] = str(data.get("account_id") or "default").strip() or "default"
        if not (str(merged.get("dingtalk_client_id") or "").strip() and str(merged.get("dingtalk_client_secret") or "").strip()):
            return {"ok": False, "error": "请先填写钉钉 Client ID 和 Client Secret"}
        args = legacy.build_args(merged)
        user = legacy.nga_feishu_watch.read_last_dingtalk_user(args)
        user_id = str(user.get("user_id") or "").strip()
        if not user_id:
            return {"ok": False, "error": "还没有收到这个钉钉配置的用户消息。请先在钉钉给机器人发送 /start 或任意消息，再点击获取。"}
        return {"ok": True, "user": user, "user_id": user_id, "status": self._status()}

    def send_test_target(self, config: dict[str, Any] | None = None, target_id: str = "") -> dict[str, Any]:
        merged = self._merged_config(config)
        errors = legacy.validate_config(merged, require_cookie=False)
        if errors:
            send_test_errors = [error for error in errors if not _is_send_test_ignorable_validation_error(error)]
            if send_test_errors:
                return {"ok": False, "errors": webui_friendly_errors(merged, send_test_errors)}
        args = legacy.build_args(merged)
        target = legacy.nga_feishu_watch.find_push_target(args, target_id)
        if target is None:
            return {"ok": False, "error": "请选择有效发送目标"}
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
        friendly_errors = webui_friendly_errors(merged, errors, include_preflight=True)
        if friendly_errors:
            return {"ok": False, "errors": friendly_errors}
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
            has_tray = _ensure_tray_icon(self)
            try:
                if has_tray:
                    window.hide()
                else:
                    window.minimize()
            except Exception:
                pass
            warning = None if has_tray else "系统托盘不可用，已改为最小化窗口。"
            return {"ok": True, "action": "minimize", "warning": warning, "status": self._status()}
        _CLOSE_CONFIRMED = True
        self.closing = True
        _stop_tray_icon()
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
    build_webui_if_needed(index_path)
    if index_path.exists():
        window = webview.create_window(APP_TITLE, index_path.as_uri(), js_api=api, width=1180, height=780, min_size=(980, 680))
    else:
        window = webview.create_window(APP_TITLE, html=fallback_html(), js_api=api, width=900, height=560, min_size=(720, 480))
    _set_active_window(window)
    window.events.closing += _request_frontend_close_dialog
    window.events.closed += api.mark_closing
    window.events.closed += lambda: _set_active_window(None)
    icon_path = app_icon_path()
    webview.start(
        debug=bool(os.getenv("NGA_WEBGUI_DEBUG")),
        icon=str(icon_path) if icon_path.exists() else None,
        private_mode=False,
        storage_path=str(legacy.data_dir() / "webview_profile"),
    )


def main() -> None:
    if len(sys.argv) >= 3 and sys.argv[1] == "--watcher-config":
        legacy.run_watcher_from_config(Path(sys.argv[2]), ws_no_watch="--ws-no-watch" in sys.argv[3:])
        return
    if len(sys.argv) == 3 and sys.argv[1] == "--self-test-config":
        with Path(sys.argv[2]).open("r", encoding="utf-8-sig") as f:
            config = legacy.nga_wolf_config.load_jsonc(f.read())
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
