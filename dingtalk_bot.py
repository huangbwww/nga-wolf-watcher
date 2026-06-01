from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


DINGTALK_API = "https://api.dingtalk.com"
MAX_DINGTALK_CHARS = 3800


@dataclass(frozen=True)
class DingTalkMessage:
    message_id: str
    sender_id: str
    sender_name: str = ""
    conversation_id: str = ""
    conversation_title: str = ""
    text: str = ""
    session_webhook: str = ""
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class DingTalkBotConfig:
    client_id: str = ""
    client_secret: str = ""
    robot_code: str = ""
    target_user_ids: str = ""
    allowed_user_ids: str = ""
    state_dir: Path = Path(".dingtalk")
    session_webhook: str = ""
    timeout: int = 20

    @classmethod
    def from_namespace(cls, args: Any) -> "DingTalkBotConfig":
        account_id = str(getattr(args, "dingtalk_account_id", "") or os.getenv("DINGTALK_ACCOUNT_ID", "default")).strip() or "default"
        state_dir = str(getattr(args, "dingtalk_state_dir", "") or os.getenv("DINGTALK_STATE_DIR", "")).strip()
        return cls(
            client_id=str(getattr(args, "dingtalk_client_id", "") or os.getenv("DINGTALK_CLIENT_ID", "")).strip(),
            client_secret=str(getattr(args, "dingtalk_client_secret", "") or os.getenv("DINGTALK_CLIENT_SECRET", "")).strip(),
            robot_code=str(getattr(args, "dingtalk_robot_code", "") or os.getenv("DINGTALK_ROBOT_CODE", "")).strip(),
            target_user_ids=str(getattr(args, "dingtalk_target_user_ids", "") or os.getenv("DINGTALK_TARGET_USER_IDS", "")).strip(),
            allowed_user_ids=str(getattr(args, "dingtalk_allowed_user_ids", "") or os.getenv("DINGTALK_ALLOWED_USER_IDS", "")).strip(),
            state_dir=Path(state_dir) if state_dir else default_state_dir(account_id),
            session_webhook=str(getattr(args, "dingtalk_session_webhook", "") or "").strip(),
            timeout=int(getattr(args, "timeout", 20) or 20),
        )

    @property
    def effective_robot_code(self) -> str:
        return self.robot_code or self.client_id


def default_state_dir(account_id: str) -> Path:
    root = os.getenv("LOCALAPPDATA", "").strip()
    if root:
        return Path(root) / "NGA Wolf Watcher" / "dingtalk" / safe_segment(account_id)
    return Path(".nga-wolf-watcher") / "dingtalk" / safe_segment(account_id)


def safe_segment(value: str) -> str:
    text = str(value or "").strip() or "default"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:80] or "default"


def split_chunks(text: str, limit: int = MAX_DINGTALK_CHARS) -> list[str]:
    value = str(text or "")
    if len(value) <= limit:
        return [value]
    chunks: list[str] = []
    while value:
        chunks.append(value[:limit])
        value = value[limit:]
    return chunks


def csv_values(value: str) -> list[str]:
    return [part.strip() for part in re.split(r"[,;\s]+", str(value or "")) if part.strip()]


def is_allowed(allowed_user_ids: str, sender_id: str) -> bool:
    allowed = set(csv_values(allowed_user_ids))
    return not allowed or sender_id in allowed


class DingTalkBotClient:
    def __init__(self, config: DingTalkBotConfig) -> None:
        self.config = config
        self._token = ""
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()

    def validate_for_stream(self) -> None:
        if not self.config.client_id or not self.config.client_secret:
            raise RuntimeError("Missing DINGTALK_CLIENT_ID or DINGTALK_CLIENT_SECRET.")
        try:
            import dingtalk_stream  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("Missing dingtalk-stream. Install it with: python -m pip install dingtalk-stream") from exc

    def get_access_token(self) -> str:
        with self._token_lock:
            if self._token and time.time() < self._token_expires_at:
                return self._token
            if not self.config.client_id or not self.config.client_secret:
                raise RuntimeError("Missing DINGTALK_CLIENT_ID or DINGTALK_CLIENT_SECRET.")
            body = json.dumps(
                {"appKey": self.config.client_id, "appSecret": self.config.client_secret},
                ensure_ascii=False,
            ).encode("utf-8")
            req = urllib.request.Request(
                f"{DINGTALK_API}/v1.0/oauth2/accessToken",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=max(5, self.config.timeout)) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                raise RuntimeError(f"DingTalk accessToken request failed HTTP {exc.code}: {detail}") from exc
            token = str(payload.get("accessToken") or "").strip()
            if not token:
                raise RuntimeError(f"DingTalk accessToken response has no token: {payload}")
            expire_in = int(payload.get("expireIn") or 7200)
            self._token = token
            self._token_expires_at = time.time() + max(60, expire_in - 300)
            return token

    def reply_text(self, text: str, session_webhook: str = "") -> None:
        webhook = str(session_webhook or self.config.session_webhook or "").strip()
        if not webhook:
            self.send_text_to_targets(text)
            return
        for chunk in split_chunks(text):
            body = {
                "msgtype": "markdown",
                "markdown": {"title": "NGA Wolf Watcher", "text": preprocess_markdown(chunk)},
            }
            self._post_json(webhook, body)

    def send_text_to_targets(self, text: str, target_user_ids: str = "") -> None:
        user_ids = csv_values(target_user_ids or self.config.target_user_ids)
        if not user_ids:
            raise RuntimeError("Missing DINGTALK_TARGET_USER_IDS, cannot send proactive DingTalk messages.")
        if not self.config.effective_robot_code:
            raise RuntimeError("Missing DINGTALK_ROBOT_CODE or DINGTALK_CLIENT_ID, cannot send proactive DingTalk messages.")
        token = self.get_access_token()
        for chunk in split_chunks(text):
            msg_param = json.dumps({"title": "NGA Wolf Watcher", "text": preprocess_markdown(chunk)}, ensure_ascii=False)
            body = {
                "robotCode": self.config.effective_robot_code,
                "userIds": user_ids[:100],
                "msgKey": "sampleMarkdown",
                "msgParam": msg_param,
            }
            self._post_json(
                f"{DINGTALK_API}/v1.0/robot/oToMessages/batchSend",
                body,
                headers={"x-acs-dingtalk-access-token": token},
            )

    def _post_json(self, url: str, body: dict[str, Any], *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        req = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=max(5, self.config.timeout)) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DingTalk request failed HTTP {exc.code}: {detail}") from exc
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def start_stream(self, on_message: Callable[[DingTalkMessage], None]) -> None:
        self.validate_for_stream()
        import dingtalk_stream
        from dingtalk_stream import AckMessage

        client = dingtalk_stream.DingTalkStreamClient(
            dingtalk_stream.Credential(self.config.client_id, self.config.client_secret)
        )
        outer = self

        class Handler(dingtalk_stream.ChatbotHandler):
            async def process(self, callback: Any) -> Any:
                raw = callback.data if isinstance(callback.data, dict) else {}
                message = parse_stream_message(raw)
                if message and is_allowed(outer.config.allowed_user_ids, message.sender_id):
                    on_message(message)
                return AckMessage.STATUS_OK, "OK"

        client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, Handler())
        client.start_forever()


def parse_stream_message(raw: dict[str, Any]) -> DingTalkMessage | None:
    if not isinstance(raw, dict):
        return None
    text = ""
    raw_text = raw.get("text")
    if isinstance(raw_text, dict):
        text = str(raw_text.get("content") or "").strip()
    elif raw_text is not None:
        text = str(raw_text).strip()
    if not text and isinstance(raw.get("content"), dict):
        content = raw["content"]
        text = str(content.get("text") or content.get("content") or "").strip()
        if not text and isinstance(content.get("markdown"), dict):
            markdown = content["markdown"]
            text = str(markdown.get("text") or markdown.get("content") or "").strip()
        if not text and isinstance(content.get("richText"), dict):
            rich_text = content["richText"]
            text = str(rich_text.get("text") or rich_text.get("content") or "").strip()
    sender_id = str(raw.get("senderStaffId") or raw.get("senderId") or raw.get("senderNick") or "").strip()
    return DingTalkMessage(
        message_id=str(raw.get("msgId") or raw.get("msg_id") or raw.get("messageId") or f"dingtalk-{int(time.time() * 1000)}"),
        sender_id=sender_id,
        sender_name=str(raw.get("senderNick") or raw.get("senderName") or "").strip(),
        conversation_id=str(raw.get("conversationId") or "").strip(),
        conversation_title=str(raw.get("conversationTitle") or "").strip(),
        text=text,
        session_webhook=str(raw.get("sessionWebhook") or "").strip(),
        raw=raw,
    )


def preprocess_markdown(text: str) -> str:
    lines = str(text or "").splitlines()
    out: list[str] = []
    in_code = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        leading = len(line) - len(line.lstrip(" "))
        if leading:
            line = ("\u00a0" * leading) + line[leading:]
        out.append(line)
    return "  \n".join(out)
