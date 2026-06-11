from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


WXPUSHER_API = "https://wxpusher.zjiecode.com/api/send/message"
WXPUSHER_SIMPLE_API = "https://wxpusher.zjiecode.com/api/send/message/simple-push"
DEFAULT_CONTENT_TYPE = "markdown"
CONTENT_TYPES = {
    "text": 1,
    "txt": 1,
    "html": 2,
    "markdown": 3,
    "md": 3,
}


class WxPusherChannelError(RuntimeError):
    pass


@dataclass(frozen=True)
class WxPusherConfig:
    spts: str = ""
    app_token: str = ""
    uids: str = ""
    topic_ids: str = ""
    content_type: str = DEFAULT_CONTENT_TYPE
    timeout: int = 20


def split_csv(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，;\s]+", value) if part.strip()]
    if isinstance(value, Iterable):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def content_type_code(value: object) -> int:
    text = str(value or DEFAULT_CONTENT_TYPE).strip().lower()
    if text.isdigit():
        code = int(text)
        return code if code in {1, 2, 3} else 3
    return CONTENT_TYPES.get(text, 3)


def redact_secret(text: object, secrets: Iterable[str]) -> str:
    result = str(text)
    for secret in secrets:
        secret_text = str(secret or "")
        if secret_text:
            result = result.replace(secret_text, "***")
    return result


def base_payload(title: str, content: str, content_type: object, *, url: str = "") -> dict[str, Any]:
    summary = str(title or "").strip()
    if len(summary) > 100:
        summary = summary[:100]
    payload: dict[str, Any] = {
        "content": str(content or ""),
        "contentType": content_type_code(content_type),
    }
    if summary:
        payload["summary"] = summary
    if url:
        payload["url"] = str(url)
    return payload


def build_simple_message_payload(config: WxPusherConfig, title: str, content: str, *, url: str = "") -> dict[str, Any]:
    spts = split_csv(config.spts)
    if not spts:
        raise WxPusherChannelError("Missing WxPusher SPT")
    payload = base_payload(title, content, config.content_type, url=url)
    payload["sptList"] = spts
    return payload


def build_message_payload(config: WxPusherConfig, title: str, content: str, *, url: str = "") -> dict[str, Any]:
    app_token = str(config.app_token or "").strip()
    if not app_token:
        raise WxPusherChannelError("Missing WxPusher appToken")

    uids = split_csv(config.uids)
    topic_ids: list[int] = []
    for value in split_csv(config.topic_ids):
        try:
            topic_ids.append(int(value))
        except ValueError as exc:
            raise WxPusherChannelError(f"Invalid WxPusher topic id: {value}") from exc
    if not uids and not topic_ids:
        raise WxPusherChannelError("Missing WxPusher UID or Topic ID")

    payload = base_payload(title, content, config.content_type, url=url)
    payload["appToken"] = app_token
    if uids:
        payload["uids"] = uids
    if topic_ids:
        payload["topicIds"] = topic_ids
    return payload


def send_message(config: WxPusherConfig, title: str, content: str, *, url: str = "") -> dict[str, Any]:
    simple = bool(split_csv(config.spts))
    payload = build_simple_message_payload(config, title, content, url=url) if simple else build_message_payload(config, title, content, url=url)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        WXPUSHER_SIMPLE_API if simple else WXPUSHER_API,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    secrets = [config.app_token, *split_csv(config.spts)]
    try:
        with urlopen(request, timeout=int(config.timeout or 20)) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise WxPusherChannelError(redact_secret(f"WxPusher request failed HTTP {exc.code}: {detail}", secrets)) from exc
    except URLError as exc:
        raise WxPusherChannelError(redact_secret(f"WxPusher request failed: {exc}", secrets)) from exc

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WxPusherChannelError(redact_secret(f"WxPusher response is not JSON: {raw}", secrets)) from exc
    if not result.get("success") or int(result.get("code") or 0) != 1000:
        raise WxPusherChannelError(redact_secret(f"WxPusher send failed: {result}", secrets))
    return result
