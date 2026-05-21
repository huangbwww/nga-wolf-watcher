from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import mimetypes
import os
import random
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_WECHAT_BASE_URL = "https://ilinkai.weixin.qq.com"
DEFAULT_WECHAT_CDN_BASE_URL = "https://novac2c.cdn.weixin.qq.com/c2c"
DEFAULT_WECHAT_POLL_TIMEOUT_MS = 35000
DEFAULT_WECHAT_QR_TIMEOUT_SECONDS = 480
DEFAULT_WECHAT_BOT_TYPE = "3"
MAX_WECHAT_CHARS = 3800
MAX_WECHAT_MEDIA_BYTES = 100 * 1024 * 1024
WECHAT_UPLOAD_MEDIA_TYPE_FILE = 3
WECHAT_TEXT_ASSUMED_DELIVERED_RETS = {-2}


@dataclass(frozen=True)
class WeChatAttachment:
    path: Path
    kind: str
    mime_type: str = ""


@dataclass(frozen=True)
class WeChatMessage:
    message_id: str
    user_id: str
    text: str
    context_token: str = ""
    create_time_ms: int = 0
    attachments: tuple[WeChatAttachment, ...] = ()


@dataclass(frozen=True)
class WeChatBotConfig:
    token: str
    base_url: str = DEFAULT_WECHAT_BASE_URL
    cdn_base_url: str = DEFAULT_WECHAT_CDN_BASE_URL
    target_user_id: str = ""
    allowed_user_ids: str = ""
    poll_timeout_ms: int = DEFAULT_WECHAT_POLL_TIMEOUT_MS
    route_tag: str = ""
    account_id: str = "default"
    state_dir: Path = Path(".wechat")
    timeout: int = 20

    @classmethod
    def from_namespace(cls, args: Any) -> "WeChatBotConfig":
        account_id = str(getattr(args, "wechat_bot_account_id", "") or os.getenv("WECHAT_BOT_ACCOUNT_ID", "default")).strip() or "default"
        state_dir = getattr(args, "wechat_bot_state_dir", "") or os.getenv("WECHAT_BOT_STATE_DIR", "")
        if state_dir:
            resolved_state_dir = Path(state_dir).expanduser()
        else:
            resolved_state_dir = default_state_dir(account_id)
        return cls(
            token=str(getattr(args, "wechat_bot_token", "") or os.getenv("WECHAT_BOT_TOKEN", "")).strip(),
            base_url=str(getattr(args, "wechat_bot_base_url", "") or os.getenv("WECHAT_BOT_BASE_URL", DEFAULT_WECHAT_BASE_URL)).strip() or DEFAULT_WECHAT_BASE_URL,
            cdn_base_url=str(getattr(args, "wechat_bot_cdn_base_url", "") or os.getenv("WECHAT_BOT_CDN_BASE_URL", DEFAULT_WECHAT_CDN_BASE_URL)).strip() or DEFAULT_WECHAT_CDN_BASE_URL,
            target_user_id=str(getattr(args, "wechat_bot_target_user_id", "") or os.getenv("WECHAT_BOT_TARGET_USER_ID", "")).strip(),
            allowed_user_ids=str(getattr(args, "wechat_bot_allowed_user_ids", "") or os.getenv("WECHAT_BOT_ALLOWED_USER_IDS", "")).strip(),
            poll_timeout_ms=safe_int(getattr(args, "wechat_bot_poll_timeout_ms", os.getenv("WECHAT_BOT_POLL_TIMEOUT_MS", DEFAULT_WECHAT_POLL_TIMEOUT_MS)), DEFAULT_WECHAT_POLL_TIMEOUT_MS),
            route_tag=str(getattr(args, "wechat_bot_route_tag", "") or os.getenv("WECHAT_BOT_ROUTE_TAG", "")).strip(),
            account_id=account_id,
            state_dir=resolved_state_dir,
            timeout=safe_int(getattr(args, "timeout", 20), 20),
        )


def default_state_dir(account_id: str) -> Path:
    root = os.getenv("LOCALAPPDATA")
    if root:
        return Path(root) / "NGA Wolf Watcher" / "wechat" / safe_segment(account_id)
    return Path(".nga-wolf-watcher") / "wechat" / safe_segment(account_id)


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def safe_segment(value: str) -> str:
    text = str(value or "").strip() or "default"
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text)
    return text.strip(" .") or "default"


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def allow_user(allowed: str, user_id: str) -> bool:
    text = str(allowed or "").strip()
    if not text or text == "*":
        return True
    return user_id.lower() in {item.strip().lower() for item in text.split(",") if item.strip()}


def random_wechat_uin() -> str:
    return base64.b64encode(str(random.randint(10000000, 4294967295)).encode("ascii")).decode("ascii")


def get_json(url: str, *, route_tag: str = "", timeout: int = 40) -> dict[str, Any]:
    headers: dict[str, str] = {}
    if route_tag:
        headers["SKRouteTag"] = route_tag
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(1024 * 1024 + 1)
            if resp.status != 200:
                raise RuntimeError(f"微信扫码接口 HTTP {resp.status}: {raw[:512].decode('utf-8', errors='replace')}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"微信扫码接口 HTTP {exc.code}: {detail}") from exc
    parsed = json.loads(raw.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


def begin_qr_login(
    base_url: str = DEFAULT_WECHAT_BASE_URL,
    *,
    route_tag: str = "",
    bot_type: str = DEFAULT_WECHAT_BOT_TYPE,
    timeout: int = 40,
) -> dict[str, str]:
    base = base_url.rstrip("/") + "/"
    url = urllib.parse.urljoin(base, "ilink/bot/get_bot_qrcode")
    query = urllib.parse.urlencode({"bot_type": bot_type or DEFAULT_WECHAT_BOT_TYPE})
    data = get_json(f"{url}?{query}", route_tag=route_tag, timeout=timeout)
    qr_key = str(data.get("qrcode") or "").strip()
    qr_url = str(data.get("qrcode_img_content") or "").strip()
    if not qr_key or not qr_url:
        raise RuntimeError(f"微信扫码接口返回缺少 qrcode/qrcode_img_content：{data}")
    return {"qr_key": qr_key, "qr_url": qr_url}


def poll_qr_login(
    qr_key: str,
    base_url: str = DEFAULT_WECHAT_BASE_URL,
    *,
    route_tag: str = "",
    timeout_seconds: int = DEFAULT_WECHAT_QR_TIMEOUT_SECONDS,
    poll_interval: float = 1.0,
) -> dict[str, str]:
    base = base_url.rstrip("/") + "/"
    url = urllib.parse.urljoin(base, "ilink/bot/get_qrcode_status")
    deadline = time.time() + max(30, timeout_seconds)
    while time.time() < deadline:
        query = urllib.parse.urlencode({"qrcode": qr_key})
        data = get_json(f"{url}?{query}", route_tag=route_tag, timeout=40)
        status = str(data.get("status") or "").strip().lower()
        if status == "confirmed":
            token = str(data.get("bot_token") or "").strip()
            bot_id = str(data.get("ilink_bot_id") or "").strip()
            user_id = str(data.get("ilink_user_id") or "").strip()
            returned_base = str(data.get("baseurl") or data.get("base_url") or "").strip()
            if not token:
                raise RuntimeError(f"微信扫码已确认，但返回缺少 bot_token：{data}")
            return {
                "token": token,
                "account_id": bot_id,
                "user_id": user_id,
                "base_url": returned_base or base_url,
            }
        if status == "expired":
            raise RuntimeError("微信二维码已过期，请重新点击扫码绑定。")
        time.sleep(max(0.5, poll_interval))
    raise RuntimeError("等待微信扫码确认超时，请重新点击扫码绑定。")


def post_json(config: WeChatBotConfig, endpoint: str, body: dict[str, Any], *, timeout_ms: int = 0) -> dict[str, Any]:
    base = config.base_url.rstrip("/") + "/"
    url = urllib.parse.urljoin(base, endpoint.lstrip("/"))
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {config.token}",
        "X-WECHAT-UIN": random_wechat_uin(),
    }
    if config.route_tag:
        headers["SKRouteTag"] = config.route_tag
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    timeout = config.timeout
    if timeout_ms > 0:
        timeout = max(timeout, int(timeout_ms / 1000) + 5)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(64 * 1024 * 1024 + 1)
            if resp.status != 200:
                raise RuntimeError(f"微信接口 {endpoint} HTTP {resp.status}: {raw[:512].decode('utf-8', errors='replace')}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"微信接口 {endpoint} HTTP {exc.code}: {detail}") from exc
    if not raw.strip():
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    return parsed if isinstance(parsed, dict) else {}


class WeChatBotClient:
    def __init__(self, config: WeChatBotConfig) -> None:
        self.config = config
        self.config.state_dir.mkdir(parents=True, exist_ok=True)
        self.buf_path = self.config.state_dir / "get_updates.buf"
        self.tokens_path = self.config.state_dir / "context_tokens.json"
        self.handled_path = self.config.state_dir / "handled_messages.json"

    def require_token(self) -> None:
        if not self.config.token:
            raise RuntimeError("缺少 WECHAT_BOT_TOKEN。请先通过 ilink/cc-connect 同类流程扫码或绑定 token。")

    def get_updates(self) -> list[WeChatMessage]:
        self.require_token()
        buf = self.buf_path.read_text(encoding="utf-8", errors="replace").strip() if self.buf_path.exists() else ""
        resp = post_json(
            self.config,
            "ilink/bot/getupdates",
            {"get_updates_buf": buf, "base_info": {"channel_version": "nga-wolf-watcher-wechat/1.0"}},
            timeout_ms=self.config.poll_timeout_ms,
        )
        if int(resp.get("errcode") or 0) == -14:
            raise RuntimeError("微信 ilink 会话已过期，请重新扫码/绑定 token。")
        next_buf = str(resp.get("get_updates_buf") or "")
        messages = []
        for raw in resp.get("msgs") or []:
            if isinstance(raw, dict):
                msg = self.parse_message(raw)
                if msg is not None:
                    messages.append(msg)
        if next_buf:
            self.buf_path.write_text(next_buf, encoding="utf-8")
        return messages

    def parse_message(self, raw: dict[str, Any]) -> WeChatMessage | None:
        if int(raw.get("message_type") or 0) == 2:
            return None
        user_id = str(raw.get("from_user_id") or "").strip()
        if not user_id or not allow_user(self.config.allowed_user_ids, user_id):
            return None
        context_token = str(raw.get("context_token") or "").strip()
        if context_token:
            tokens = read_json(self.tokens_path, {})
            if not isinstance(tokens, dict):
                tokens = {}
            tokens[user_id] = context_token
            write_json(self.tokens_path, tokens)
        msg_id = str(raw.get("message_id") or raw.get("client_id") or f"wechat-{int(time.time() * 1000)}")
        items = raw.get("item_list") if isinstance(raw.get("item_list"), list) else []
        text = body_from_items(items)
        attachments = tuple(self.collect_attachments(items, msg_id))
        if not text.strip() and not attachments and has_media_items(items):
            text = "收到微信图片或文件，但下载失败。请检查 WECHAT_BOT_CDN_BASE_URL；如果是加密图片，请安装 pycryptodome。"
        if not text.strip() and not attachments:
            return None
        return WeChatMessage(
            message_id=msg_id,
            user_id=user_id,
            text=text,
            context_token=context_token,
            create_time_ms=safe_int(raw.get("create_time_ms"), 0),
            attachments=attachments,
        )

    def is_handled(self, msg: WeChatMessage) -> bool:
        handled = read_json(self.handled_path, [])
        if not isinstance(handled, list):
            handled = []
        key = self.message_key(msg)
        return key in set(str(item) for item in handled)

    def mark_handled(self, msg: WeChatMessage) -> None:
        handled = read_json(self.handled_path, [])
        if not isinstance(handled, list):
            handled = []
        key = self.message_key(msg)
        values = [str(item) for item in handled if str(item) != key]
        values.append(key)
        write_json(self.handled_path, values[-500:])

    def message_key(self, msg: WeChatMessage) -> str:
        return f"{msg.user_id}|{msg.message_id}|{msg.create_time_ms}"

    def send_text_to_target(self, text: str, target_user_id: str = "") -> None:
        target = (target_user_id or self.config.target_user_id).strip()
        if not target:
            raise RuntimeError("缺少 WECHAT_BOT_TARGET_USER_ID，无法主动发送微信消息。")
        self.send_text(target, text)

    def send_file_to_target(self, path: Path, file_name: str = "", caption: str = "", target_user_id: str = "") -> None:
        target = (target_user_id or self.config.target_user_id).strip()
        if not target:
            raise RuntimeError("缺少 WECHAT_BOT_TARGET_USER_ID，无法主动发送微信文件。")
        self.send_file(target, path, file_name=file_name, caption=caption)

    def send_text(self, user_id: str, text: str) -> None:
        self.require_token()
        tokens = read_json(self.tokens_path, {})
        token = str(tokens.get(user_id) or "") if isinstance(tokens, dict) else ""
        if not token:
            raise RuntimeError(f"微信用户 {user_id} 尚未建立 context_token。请先让该用户给机器人发一条消息。")
        chunks = split_chunks(text, MAX_WECHAT_CHARS)
        for index, chunk in enumerate(chunks):
            if index:
                time.sleep(0.15)
            self._send_text_chunk(user_id, chunk, token)

    def _send_text_chunk(self, user_id: str, text: str, context_token: str) -> None:
        resp = post_json(
            self.config,
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": user_id,
                    "client_id": f"nga-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [{"type": 1, "text_item": {"text": text}}],
                },
                "base_info": {"channel_version": "nga-wolf-watcher-wechat/1.0"},
            },
        )
        ret = int(resp.get("ret") or 0)
        if ret in WECHAT_TEXT_ASSUMED_DELIVERED_RETS:
            print(
                f"微信 sendMessage 返回 ret={ret}，但文本消息可能已投递，按已发送处理：to={user_id} chars={len(text)} resp={resp}",
                file=sys.stderr,
            )
            return
        if ret != 0:
            raise RuntimeError(f"微信 sendMessage 失败：{resp}")

    def send_file(self, user_id: str, path: Path, file_name: str = "", caption: str = "") -> None:
        self.require_token()
        tokens = read_json(self.tokens_path, {})
        token = str(tokens.get(user_id) or "") if isinstance(tokens, dict) else ""
        if not token:
            raise RuntimeError(f"微信用户 {user_id} 尚未建立 context_token。请先让该用户给机器人发一条消息。")
        file_path = Path(path)
        uploaded = self.upload_file(file_path, user_id)
        if caption.strip():
            self.send_text(user_id, caption.strip())
        self._send_file_item(user_id, token, file_name or file_path.name, uploaded)

    def _send_file_item(self, user_id: str, context_token: str, file_name: str, uploaded: dict[str, Any]) -> None:
        resp = post_json(
            self.config,
            "ilink/bot/sendmessage",
            {
                "msg": {
                    "from_user_id": "",
                    "to_user_id": user_id,
                    "client_id": f"nga-{int(time.time() * 1000)}-{random.randint(1000, 9999)}",
                    "message_type": 2,
                    "message_state": 2,
                    "context_token": context_token,
                    "item_list": [
                        {
                            "type": 4,
                            "file_item": {
                                "media": {
                                    "encrypt_query_param": uploaded["encrypt_query_param"],
                                    "aes_key": uploaded["aes_key"],
                                    "encrypt_type": 1,
                                },
                                "file_name": file_name,
                                "len": str(uploaded["raw_size"]),
                            },
                        }
                    ],
                },
                "base_info": {"channel_version": "nga-wolf-watcher-wechat/1.0"},
            },
        )
        if int(resp.get("ret") or 0) != 0:
            raise RuntimeError(f"微信文件 sendMessage 失败：{resp}")

    def upload_file(self, path: Path, to_user_id: str) -> dict[str, Any]:
        file_path = Path(path)
        data = file_path.read_bytes()
        if len(data) > MAX_WECHAT_MEDIA_BYTES:
            raise RuntimeError("微信文件超过大小限制。")
        aes_key = secrets.token_bytes(16)
        aes_key_hex = aes_key.hex()
        file_key = secrets.token_hex(16)
        raw_size = len(data)
        upload_size = aes_ecb_padded_size(raw_size)
        upload_info = post_json(
            self.config,
            "ilink/bot/getuploadurl",
            {
                "filekey": file_key,
                "media_type": WECHAT_UPLOAD_MEDIA_TYPE_FILE,
                "to_user_id": to_user_id,
                "rawsize": raw_size,
                "rawfilemd5": hashlib.md5(data).hexdigest(),
                "filesize": upload_size,
                "no_need_thumb": True,
                "aeskey": aes_key_hex,
                "base_info": {"channel_version": "nga-wolf-watcher-wechat/1.0"},
            },
        )
        encrypted_param = upload_bytes_to_cdn(
            self.config,
            data,
            aes_key,
            file_key,
            upload_info.get("upload_full_url"),
            upload_info.get("upload_param"),
        )
        return {
            "encrypt_query_param": encrypted_param,
            "aes_key": base64.b64encode(aes_key_hex.encode("ascii")).decode("ascii"),
            "raw_size": raw_size,
        }

    def collect_attachments(self, items: list[Any], message_id: str, depth: int = 0) -> list[WeChatAttachment]:
        result: list[WeChatAttachment] = []
        if depth > 2:
            return result
        for index, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue
            kind = int(item.get("type") or 0)
            if kind == 2:
                image = item.get("image_item") if isinstance(item.get("image_item"), dict) else {}
                media = image.get("media") if isinstance(image.get("media"), dict) else {}
                try:
                    path = self.download_cdn_media(media, f"wechat_image_{message_id}_{index}", image.get("aeskey"))
                except Exception as exc:
                    print(f"微信图片附件处理失败: {exc}")
                    path = None
                if path:
                    result.append(WeChatAttachment(path=path, kind="image", mime_type=guess_mime(path)))
            elif kind in {4, 5}:
                file_item = item.get("file_item") if kind == 4 else item.get("video_item")
                file_item = file_item if isinstance(file_item, dict) else {}
                media = file_item.get("media") if isinstance(file_item.get("media"), dict) else {}
                raw_name = str(file_item.get("file_name") or ("video.mp4" if kind == 5 else "attachment.bin"))
                try:
                    path = self.download_cdn_media(media, safe_segment(Path(raw_name).stem), None, suffix=Path(raw_name).suffix)
                except Exception as exc:
                    print(f"微信文件附件处理失败: {exc}")
                    path = None
                if path:
                    result.append(WeChatAttachment(path=path, kind="file", mime_type=guess_mime(path)))
            ref = item.get("ref_msg") if isinstance(item.get("ref_msg"), dict) else {}
            ref_item = ref.get("message_item") if isinstance(ref.get("message_item"), dict) else {}
            if ref_item:
                result.extend(self.collect_attachments([ref_item], f"{message_id}_ref{index}", depth + 1))
        return result

    def download_cdn_media(self, media: dict[str, Any], stem: str, aeskey_hex: Any = None, suffix: str = "") -> Path | None:
        enc = str(media.get("encrypt_query_param") or "").strip()
        if not enc:
            return None
        url = f"{self.config.cdn_base_url.rstrip('/')}/download?encrypted_query_param={urllib.parse.quote(enc)}"
        req = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=max(60, self.config.timeout)) as resp:
                data = resp.read(MAX_WECHAT_MEDIA_BYTES + 1)
        except Exception as exc:
            print(f"微信附件下载失败: {exc}")
            return None
        if len(data) > MAX_WECHAT_MEDIA_BYTES:
            print("微信附件超过大小限制，已跳过。")
            return None
        aes_key = str(media.get("aes_key") or "").strip()
        if aeskey_hex:
            aes_key = base64.b64encode(bytes.fromhex(str(aeskey_hex))).decode("ascii")
        if aes_key:
            data = decrypt_aes_ecb_if_possible(data, aes_key)
        if not suffix:
            suffix = extension_from_bytes(data)
        attach_dir = self.config.state_dir / "attachments"
        attach_dir.mkdir(parents=True, exist_ok=True)
        path = attach_dir / f"{safe_segment(stem)}_{int(time.time() * 1000)}{suffix or '.bin'}"
        path.write_bytes(data)
        return path.resolve()


def body_from_items(items: list[Any]) -> str:
    lines: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = int(item.get("type") or 0)
        if kind == 1:
            text_item = item.get("text_item") if isinstance(item.get("text_item"), dict) else {}
            text = str(text_item.get("text") or "").strip()
            ref = item.get("ref_msg") if isinstance(item.get("ref_msg"), dict) else {}
            ref_text = ref_body(ref)
            if ref_text:
                lines.extend(["被回复内容：", ref_text])
            if text:
                if ref_text:
                    lines.extend(["", "本次回复：", text])
                else:
                    lines.append(text)
        elif kind == 3:
            voice = item.get("voice_item") if isinstance(item.get("voice_item"), dict) else {}
            text = str(voice.get("text") or "").strip()
            if text:
                lines.append(text)
    return "\n".join(lines).strip()


def has_media_items(items: list[Any]) -> bool:
    for item in items:
        if isinstance(item, dict) and int(item.get("type") or 0) in {2, 4, 5}:
            return True
    return False


def ref_body(ref: dict[str, Any]) -> str:
    parts: list[str] = []
    title = str(ref.get("title") or "").strip()
    if title:
        parts.append(title)
    item = ref.get("message_item")
    if isinstance(item, dict):
        nested = body_from_items([item])
        if nested:
            parts.append(nested)
    return " | ".join(parts)


def split_chunks(text: str, size: int) -> list[str]:
    raw = str(text or "")
    if not raw:
        return []
    chars = list(raw)
    return ["".join(chars[i : i + size]) for i in range(0, len(chars), size)]


def aes_ecb_padded_size(size: int) -> int:
    return ((max(0, size) // 16) + 1) * 16


def encrypt_aes_ecb_pkcs7(data: bytes, aes_key: bytes) -> bytes:
    try:
        from Crypto.Cipher import AES  # type: ignore
    except Exception as exc:
        raise RuntimeError("发送微信文件需要 pycryptodome。请安装后重试，或使用文本分段回退。") from exc
    pad_len = 16 - (len(data) % 16)
    padded = data + bytes([pad_len]) * pad_len
    return AES.new(aes_key, AES.MODE_ECB).encrypt(padded)


def upload_bytes_to_cdn(
    config: WeChatBotConfig,
    data: bytes,
    aes_key: bytes,
    file_key: str,
    upload_full_url: Any,
    upload_param: Any,
) -> str:
    encrypted = encrypt_aes_ecb_pkcs7(data, aes_key)
    url = str(upload_full_url or "").strip()
    if not url:
        param = str(upload_param or "").strip()
        if not param:
            raise RuntimeError("微信 getuploadurl 未返回 upload_full_url 或 upload_param。")
        url = (
            f"{config.cdn_base_url.rstrip('/')}/upload"
            f"?encrypted_query_param={urllib.parse.quote(param, safe='')}"
            f"&filekey={urllib.parse.quote(file_key, safe='')}"
        )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url,
                data=encrypted,
                headers={"Content-Type": "application/octet-stream"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=max(60, config.timeout)) as resp:
                if resp.status != 200:
                    detail = resp.read(1024).decode("utf-8", errors="replace")
                    raise RuntimeError(f"微信 CDN 上传 HTTP {resp.status}: {detail}")
                encrypted_param = str(resp.headers.get("x-encrypted-param") or "").strip()
                if not encrypted_param:
                    raise RuntimeError("微信 CDN 上传响应缺少 x-encrypted-param。")
                return encrypted_param
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"微信 CDN 上传 HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"微信 CDN 上传失败: {last_error}")


def decrypt_aes_ecb_if_possible(data: bytes, aes_key_base64: str) -> bytes:
    try:
        from Crypto.Cipher import AES  # type: ignore
    except Exception:
        print("微信加密附件需要 pycryptodome 才能解密，当前保留原始密文。")
        return data
    try:
        key = base64.b64decode(aes_key_base64)
        if len(key) == 32 and re.fullmatch(rb"[0-9a-fA-F]{32}", key):
            key = bytes.fromhex(key.decode("ascii"))
        cipher = AES.new(key, AES.MODE_ECB)
        plain = cipher.decrypt(data)
        pad = plain[-1]
        if 1 <= pad <= 16 and plain.endswith(bytes([pad]) * pad):
            return plain[:-pad]
        return plain
    except Exception as exc:
        print(f"微信附件解密失败，保留原始内容: {exc}")
        return data


def extension_from_bytes(data: bytes) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return ".bin"


def guess_mime(path: Path) -> str:
    return mimetypes.guess_type(str(path))[0] or "application/octet-stream"


def describe_binding(config: WeChatBotConfig) -> str:
    tokens = read_json(config.state_dir / "context_tokens.json", {})
    known = ", ".join(sorted(tokens)[:10]) if isinstance(tokens, dict) and tokens else "none"
    return "\n".join(
        [
            "微信 Bot 绑定状态",
            f"base_url: {config.base_url}",
            f"account_id: {config.account_id}",
            f"target_user_id: {config.target_user_id or 'not set'}",
            f"known users: {known}",
            f"state_dir: {config.state_dir}",
            "",
            "首次使用：请先用目标微信给机器人发一条消息，程序收到后会缓存 context_token，之后才能主动推送 NGA 消息。",
        ]
    )


class WeChatMenuState:
    def __init__(self, state_dir: Path) -> None:
        self.path = state_dir / "menu_state.json"

    def get(self, user_id: str) -> str:
        data = read_json(self.path, {})
        if not isinstance(data, dict):
            return ""
        item = data.get(user_id)
        if isinstance(item, dict):
            return str(item.get("menu") or "")
        return ""

    def set(self, user_id: str, menu: str) -> None:
        data = read_json(self.path, {})
        if not isinstance(data, dict):
            data = {}
        data[user_id] = {"menu": menu, "updated_at": int(time.time())}
        write_json(self.path, data)


@contextlib.contextmanager
def noop_typing() -> Any:
    yield
