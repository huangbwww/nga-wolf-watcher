from __future__ import annotations

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
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
class DingTalkCardAction:
    message_id: str
    user_id: str
    card_instance_id: str = ""
    action: str = ""
    command: str = ""
    params: dict[str, Any] | None = None
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

    def reply_markdown_card(self, raw_message: dict[str, Any] | None, markdown: str, title: str = "NGA Wolf Watcher") -> str:
        raw = raw_message if isinstance(raw_message, dict) else {}
        card_target = self._card_target_from_raw(raw)
        if not card_target:
            raise RuntimeError("DingTalk card target is unavailable for this message.")
        card_id = f"nga-wolf-{int(time.time() * 1000)}-{uuid.uuid4().hex[:12]}"
        body: dict[str, Any] = {
            "cardTemplateId": "589420e2-c1e2-46ef-a5ed-b8728e654da9.schema",
            "outTrackId": card_id,
            "callbackType": "STREAM",
            "userIdType": 1,
            "cardData": {
                "cardParamMap": {
                    "title": title,
                    "markdown": preprocess_markdown(markdown),
                }
            },
            "imGroupOpenSpaceModel": {"supportForward": True},
            "imRobotOpenSpaceModel": {"supportForward": True},
            **card_target,
        }
        self._post_json(
            f"{DINGTALK_API}/v1.0/card/instances/createAndDeliver",
            body,
            headers={"x-acs-dingtalk-access-token": self.get_access_token()},
        )
        return card_id

    def reply_action_card(
        self,
        raw_message: dict[str, Any] | None,
        markdown: str,
        buttons: list[dict[str, str]],
        title: str = "NGA Wolf Watcher",
    ) -> str:
        raw = raw_message if isinstance(raw_message, dict) else {}
        card_target = self._card_target_from_raw(raw)
        if not card_target:
            raise RuntimeError("DingTalk card target is unavailable for this message.")
        card_id = f"nga-wolf-{int(time.time() * 1000)}-{uuid.uuid4().hex[:12]}"
        msg_buttons = []
        for button in buttons[:8]:
            command = str(button.get("command") or "").strip()
            text = str(button.get("text") or command or "执行").strip()
            if not command:
                continue
            msg_buttons.append(
                {
                    "text": text,
                    "color": str(button.get("color") or "blue"),
                    "actionType": "callback",
                    "params": {"command": command, "action": str(button.get("action") or "command")},
                }
            )
        body: dict[str, Any] = {
            "cardTemplateId": "1366a1eb-bc54-4859-ac88-517c56a9acb1.schema",
            "outTrackId": card_id,
            "callbackType": "STREAM",
            "userIdType": 1,
            "cardData": {
                "cardParamMap": {
                    "title": title,
                    "markdown": preprocess_markdown(markdown),
                    "tips": "点击按钮或直接回复短命令",
                    "sys_full_json_obj": json.dumps({"msgButtons": msg_buttons}, ensure_ascii=False),
                }
            },
            "imGroupOpenSpaceModel": {"supportForward": True},
            "imRobotOpenSpaceModel": {"supportForward": True},
            **card_target,
        }
        self._post_json(
            f"{DINGTALK_API}/v1.0/card/instances/createAndDeliver",
            body,
            headers={"x-acs-dingtalk-access-token": self.get_access_token()},
        )
        return card_id

    def update_markdown_card(self, card_instance_id: str, markdown: str, title: str = "NGA Wolf Watcher") -> None:
        if not card_instance_id:
            return
        body = {
            "outTrackId": card_instance_id,
            "cardData": {
                "cardParamMap": {
                    "title": title,
                    "markdown": preprocess_markdown(markdown),
                }
            },
            "cardUpdateOptions": {"updateCardDataByKey": True, "updatePrivateDataByKey": True},
        }
        result = self._post_json(
            f"{DINGTALK_API}/v1.0/card/instances",
            body,
            headers={"x-acs-dingtalk-access-token": self.get_access_token()},
        )
        if isinstance(result, dict):
            errcode = result.get("errcode")
            code = result.get("code")
            success = result.get("success")
            if (errcode not in (None, 0, "0")) or (code not in (None, 0, "0")) or success is False:
                raise RuntimeError(f"DingTalk card update failed: {result}")

    def _card_target_from_raw(self, raw: dict[str, Any]) -> dict[str, Any]:
        conversation_type = str(raw.get("conversationType") or "").strip()
        conversation_id = str(raw.get("conversationId") or "").strip()
        sender_staff_id = str(raw.get("senderStaffId") or raw.get("senderId") or "").strip()
        if conversation_type == "2" and conversation_id:
            return {
                "openSpaceId": f"dtv1.card//IM_GROUP.{conversation_id}",
                "imGroupOpenDeliverModel": {"robotCode": self.config.effective_robot_code},
            }
        if sender_staff_id:
            return {
                "openSpaceId": f"dtv1.card//IM_ROBOT.{sender_staff_id}",
                "imRobotOpenDeliverModel": {"spaceType": "IM_ROBOT"},
            }
        return {}

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

    def start_stream(
        self,
        on_message: Callable[[DingTalkMessage], None],
        on_card_action: Callable[[DingTalkCardAction], None] | None = None,
    ) -> None:
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

        class CardHandler(dingtalk_stream.CallbackHandler):
            async def process(self, callback: Any) -> Any:
                raw = callback.data if isinstance(callback.data, dict) else {}
                action = parse_card_action(raw, getattr(getattr(callback, "headers", None), "message_id", ""))
                if action and on_card_action:
                    on_card_action(action)
                return AckMessage.STATUS_OK, "OK"

        client.register_callback_handler(dingtalk_stream.chatbot.ChatbotMessage.TOPIC, Handler())
        client.register_callback_handler(dingtalk_stream.CallbackHandler.TOPIC_CARD_CALLBACK, CardHandler())
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


def parse_card_action(raw: dict[str, Any], message_id: str = "") -> DingTalkCardAction | None:
    if not isinstance(raw, dict):
        return None
    content = raw.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except Exception:
            content = {}
    if not isinstance(content, dict):
        content = {}
    card_private = content.get("cardPrivateData")
    if isinstance(card_private, str):
        try:
            card_private = json.loads(card_private)
        except Exception:
            card_private = {}
    if not isinstance(card_private, dict):
        card_private = {}
    params = card_private.get("params") or content.get("params") or raw.get("params") or {}
    if isinstance(params, str):
        try:
            params = json.loads(params)
        except Exception:
            params = {}
    if not isinstance(params, dict):
        params = {}
    action = str(params.get("action") or content.get("action") or raw.get("action") or "").strip()
    command = str(params.get("command") or params.get("cmd") or "").strip()
    user_id = str(raw.get("userId") or raw.get("user_id") or "").strip()
    card_instance_id = str(raw.get("outTrackId") or raw.get("cardInstanceId") or "").strip()
    if not (action or command or user_id or card_instance_id):
        return None
    return DingTalkCardAction(
        message_id=str(message_id or raw.get("messageId") or raw.get("msgId") or f"dingtalk-card-{int(time.time() * 1000)}"),
        user_id=user_id,
        card_instance_id=card_instance_id,
        action=action,
        command=command,
        params=params,
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
