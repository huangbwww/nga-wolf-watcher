#!/usr/bin/env python3
"""Watch an NGA user's search-post page and push new replies to Feishu.

Environment variables:
  NGA_COOKIE          Required. Cookie copied from a logged-in bbs.nga.cn session.
  FEISHU_APP_ID      Feishu/Lark app id for app bot mode.
  FEISHU_APP_SECRET  Feishu/Lark app secret for app bot mode.
  FEISHU_RECEIVE_ID  chat_id/open_id/user_id for app bot mode.
  FEISHU_ID_TYPE     chat_id/open_id/user_id. Defaults to chat_id.
  FEISHU_WEBHOOK     Optional legacy custom bot webhook.
  FEISHU_SECRET      Optional legacy custom bot signing secret.
  NGA_AUTHOR_ID      Defaults to 150058.
  NGA_MAX_PAGES      Defaults to 1.
  NGA_STATE_PATH     Defaults to .nga_seen.json.
  NGA_INTERVAL       Defaults to 60 seconds in watch mode.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import random
import re
import copy
import sys
import threading
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


NGA_ENDPOINT = "https://bbs.nga.cn/thread.php"
NGA_READ_ENDPOINT = "https://bbs.nga.cn/read.php"
FEISHU_API = "https://open.feishu.cn/open-apis"
DEFAULT_AUTHOR_ID = "150058"
DEFAULT_TID = "45974302"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


@dataclass(frozen=True)
class NgaPost:
    key: str
    subject: str
    content: str
    url: str
    post_time: str
    author: str = ""
    author_id: str = ""
    floor: str = ""


@dataclass(frozen=True)
class BotCommand:
    action: str
    target_type: str = ""
    target_id: str = ""
    count: int = 20


def http_json(
    url: str,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json; charset=utf-8")
    req = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        detail = raw.decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc
    return json.loads(raw.decode("utf-8"))


def feishu_credentials(args: argparse.Namespace) -> tuple[str, str, str, str]:
    app_id = args.feishu_app_id or os.getenv("FEISHU_APP_ID", "")
    app_secret = args.feishu_app_secret or os.getenv("FEISHU_APP_SECRET", "")
    receive_id = args.feishu_receive_id or os.getenv("FEISHU_RECEIVE_ID", "")
    receive_id_type = args.feishu_id_type or os.getenv("FEISHU_ID_TYPE", "chat_id")
    return app_id, app_secret, receive_id, receive_id_type


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def fetch_nga_page(author_id: str, page: int, cookie: str, timeout: int) -> dict[str, Any]:
    params = {
        "searchpost": "1",
        "page": str(page),
        "__output": "8",
    }
    if author_id and author_id != "0":
        params["authorid"] = author_id
    query = urllib.parse.urlencode(params)
    return fetch_nga_json(f"{NGA_ENDPOINT}?{query}", cookie, timeout, f"author page {page}")


def fetch_nga_thread_page(tid: str, page: int, cookie: str, timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"tid": tid, "page": str(page), "__output": "8"})
    return fetch_nga_json(f"{NGA_READ_ENDPOINT}?{query}", cookie, timeout, f"thread {tid} page {page}")


def fetch_nga_json(url: str, cookie: str, timeout: int, label: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Cookie": cookie,
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://bbs.nga.cn/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "gb18030"
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        charset = exc.headers.get_content_charset() or "gb18030"

    text = raw.decode(charset, errors="replace")
    payload = json.loads(text, strict=False)
    if payload.get("error"):
        err = payload["error"]
        message = err.get("0") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"NGA returned error on {label}: {message}")
    return payload


def walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def first_str(item: dict[str, Any], *names: str) -> str:
    for name in names:
        value = item.get(name)
        if value is not None and value != "":
            return str(value)
    return ""


def strip_markup(value: str) -> str:
    value = html.unescape(value)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\[/?(?:quote|collapse|color|size|b|i|u|url|img|align)[^\]]*\]", "", value, flags=re.I)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def make_post(item: dict[str, Any], fallback_subject: str = "") -> NgaPost | None:
    raw_content = first_str(item, "content", "postcontent", "post_content", "message")
    if not raw_content:
        return None

    content = strip_markup(raw_content)
    if not content:
        return None

    tid = first_str(item, "tid", "threadid", "topic_id")
    pid = first_str(item, "pid", "postid", "reply_id")
    postdate = first_str(item, "postdate", "post_date", "time", "timestamp")
    author = strip_markup(first_str(item, "author", "username"))
    author_id = first_str(item, "authorid", "uid", "user_id")
    floor = first_str(item, "lou", "floor")
    subject = strip_markup(first_str(item, "subject", "title", "thread_subject"))
    subject = subject or strip_markup(fallback_subject) or "(无标题)"

    key_source = "|".join([tid, pid, postdate, subject, content[:80]])
    key = pid or hashlib.sha1(key_source.encode("utf-8")).hexdigest()
    url = "https://bbs.nga.cn/"
    if tid and pid:
        url = f"https://bbs.nga.cn/read.php?tid={urllib.parse.quote(tid)}&pid={urllib.parse.quote(pid)}"
    elif tid:
        url = f"https://bbs.nga.cn/read.php?tid={urllib.parse.quote(tid)}"

    return NgaPost(
        key=key,
        subject=subject,
        content=content,
        url=url,
        post_time=format_time(postdate),
        author=author,
        author_id=author_id,
        floor=floor,
    )


def format_time(value: str) -> str:
    if not value:
        return ""
    if value.isdigit():
        try:
            ts = int(value)
            if ts > 10_000_000_000:
                ts //= 1000
            return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        except (OSError, OverflowError, ValueError):
            return value
    return value


def extract_posts(payload: dict[str, Any]) -> list[NgaPost]:
    seen: set[str] = set()
    posts: list[NgaPost] = []
    topics = payload.get("data", {}).get("__T", {})
    if isinstance(topics, dict):
        for topic in topics.values():
            if not isinstance(topic, dict):
                continue
            reply = topic.get("__P")
            if not isinstance(reply, dict):
                continue
            post = make_post(reply, fallback_subject=first_str(topic, "subject", "title"))
            if post and post.key not in seen:
                seen.add(post.key)
                posts.append(post)

    for item in walk_dicts(payload.get("data", payload)):
        post = make_post(item)
        if post and post.key not in seen:
            seen.add(post.key)
            posts.append(post)
    return posts


def extract_thread_posts(payload: dict[str, Any]) -> tuple[list[NgaPost], int]:
    data = payload.get("data", {})
    topic = data.get("__T", {}) if isinstance(data, dict) else {}
    replies = data.get("__R", {}) if isinstance(data, dict) else {}
    users = data.get("__U", {}) if isinstance(data, dict) else {}
    subject = first_str(topic, "subject", "title") if isinstance(topic, dict) else ""
    page = int(data.get("__PAGE", 0) or 0) if isinstance(data, dict) else 0

    posts: list[NgaPost] = []
    if not isinstance(replies, dict):
        return posts, page
    for raw in replies.values():
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        uid = first_str(item, "authorid")
        user = users.get(uid) if isinstance(users, dict) else None
        if isinstance(user, dict):
            item["author"] = first_str(user, "username", "uname", "name")
        post = make_post(item, fallback_subject=subject)
        if post:
            posts.append(post)
    return posts, page


def feishu_sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        string_to_sign.encode("utf-8"),
        b"",
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def feishu_message_text(post: NgaPost) -> str:
    byline = f"Author: {post.author or post.author_id or 'unknown'}"
    if post.floor:
        byline += f" Floor: {post.floor}"
    lines = [
        f"NGA new reply: {post.subject}",
        f"Time: {post.post_time or 'unknown'}",
        byline,
        f"Link: {post.url}",
        "",
        post.content[:1800],
    ]
    return "\n".join(lines)


def feishu_history_text(posts: list[NgaPost], title: str) -> str:
    lines = [title]
    for idx, post in enumerate(posts, 1):
        excerpt = post.content.replace("\n", " ")[:300]
        lines.append(f"\n{idx}. {post.subject}")
        meta = post.post_time or "unknown"
        if post.author or post.author_id:
            meta += f" | {post.author or post.author_id}"
        if post.floor:
            meta += f" | #{post.floor}"
        lines.append(f"{meta} {post.url}")
        lines.append(excerpt)
    return "\n".join(lines)


def posts_to_txt(posts: list[NgaPost], title: str) -> str:
    chunks = [title, f"Generated at: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}", ""]
    for idx, post in enumerate(posts, 1):
        meta = [
            f"{idx}. {post.subject}",
            f"time: {post.post_time or 'unknown'}",
            f"author: {post.author or post.author_id or 'unknown'}",
            f"url: {post.url}",
        ]
        if post.floor:
            meta.append(f"floor: {post.floor}")
        chunks.append("\n".join(meta))
        chunks.append(post.content)
        chunks.append("-" * 60)
    return "\n".join(chunks)


def lark_md_escape(value: str) -> str:
    return value.replace("<", "&lt;").replace(">", "&gt;")


def post_card_element(post: NgaPost) -> list[dict[str, Any]]:
    excerpt = lark_md_escape(post.content.replace("\n", "\n\n")[:700])
    title = lark_md_escape(post.subject)
    time_text = lark_md_escape(post.post_time or "unknown")
    author_text = lark_md_escape(post.author or post.author_id or "unknown")
    floor_text = f" | #{lark_md_escape(post.floor)}" if post.floor else ""
    return [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{title}**\n{time_text} | {author_text}{floor_text}\n\n{excerpt}",
            },
        },
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "Open in NGA"},
                    "url": post.url,
                    "type": "default",
                }
            ],
        },
    ]


def feishu_posts_card(posts: list[NgaPost], title: str) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    for idx, post in enumerate(posts[:20]):
        if idx:
            elements.append({"tag": "hr"})
        elements.extend(post_card_element(post))
    if not elements:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "No replies found."}})
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": title[:60]},
        },
        "elements": elements,
    }


def push_feishu(webhook: str, secret: str | None, post: NgaPost, timeout: int) -> None:
    body: dict[str, Any] = {
        "msg_type": "text",
        "content": {"text": feishu_message_text(post)},
    }
    if secret:
        timestamp = str(int(time.time()))
        body["timestamp"] = timestamp
        body["sign"] = feishu_sign(secret, timestamp)

    result = http_json(webhook, method="POST", body=body, timeout=timeout)
    if result.get("code") not in (None, 0):
        raise RuntimeError(f"Feishu push failed: {result}")


def get_feishu_tenant_access_token(app_id: str, app_secret: str, timeout: int) -> str:
    result = http_json(
        f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
        method="POST",
        body={"app_id": app_id, "app_secret": app_secret},
        timeout=timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu token failed: {result}")
    token = result.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"Feishu token missing in response: {result}")
    return str(token)


def feishu_app_request(
    app_id: str,
    app_secret: str,
    path: str,
    timeout: int,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    token = get_feishu_tenant_access_token(app_id, app_secret, timeout)
    return http_json(
        f"{FEISHU_API}{path}",
        method=method,
        body=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=timeout,
    )


def feishu_app_token(args: argparse.Namespace) -> tuple[str, str, str, str, str]:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    if not (app_id and app_secret and receive_id):
        raise SystemExit("Missing FEISHU_APP_ID, FEISHU_APP_SECRET, or FEISHU_RECEIVE_ID.")
    token = get_feishu_tenant_access_token(app_id, app_secret, args.timeout)
    return app_id, app_secret, receive_id, receive_id_type, token


def push_feishu_app(
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    post: NgaPost,
    timeout: int,
    message_format: str = "card",
) -> None:
    if message_format == "text":
        msg_type = "text"
        content = json.dumps({"text": feishu_message_text(post)}, ensure_ascii=False)
    else:
        msg_type = "interactive"
        content = json.dumps(feishu_posts_card([post], "NGA new reply"), ensure_ascii=False)
    result = feishu_app_request(
        app_id,
        app_secret,
        f"/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
        timeout=timeout,
        method="POST",
        body={"receive_id": receive_id, "msg_type": msg_type, "content": content},
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu app push failed: {result}")


def multipart_body(fields: dict[str, str], file_field: str, file_name: str, file_bytes: bytes) -> tuple[bytes, str]:
    boundary = f"----nga-watch-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}\r\n".encode("utf-8"))
    chunks.append(
        (
            f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'
            "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        ).encode("utf-8")
    )
    chunks.append(file_bytes)
    chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def upload_feishu_file(token: str, file_name: str, text: str, timeout: int) -> str:
    body, content_type = multipart_body(
        {"file_type": "stream", "file_name": file_name},
        "file",
        file_name,
        text.encode("utf-8"),
    )
    req = urllib.request.Request(
        f"{FEISHU_API}/im/v1/files",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Feishu file upload failed: HTTP {exc.code}: {detail}") from exc
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu file upload failed: {result}")
    file_key = result.get("data", {}).get("file_key")
    if not file_key:
        raise RuntimeError(f"Feishu file_key missing: {result}")
    return str(file_key)


def push_feishu_file(args: argparse.Namespace, file_name: str, text: str) -> None:
    _app_id, _app_secret, receive_id, receive_id_type, token = feishu_app_token(args)
    file_key = upload_feishu_file(token, file_name, text, args.timeout)
    content = json.dumps({"file_key": file_key}, ensure_ascii=False)
    result = http_json(
        f"{FEISHU_API}/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        body={"receive_id": receive_id, "msg_type": "file", "content": content},
        timeout=args.timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu file message failed: {result}")


def push_feishu_app_posts(
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    posts: list[NgaPost],
    title: str,
    timeout: int,
    message_format: str = "card",
) -> None:
    if message_format == "text":
        msg_type = "text"
        content = json.dumps({"text": feishu_history_text(posts, title)}, ensure_ascii=False)
    else:
        msg_type = "interactive"
        content = json.dumps(feishu_posts_card(posts, title), ensure_ascii=False)
    result = feishu_app_request(
        app_id,
        app_secret,
        f"/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
        timeout=timeout,
        method="POST",
        body={"receive_id": receive_id, "msg_type": msg_type, "content": content},
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu app push failed: {result}")


def list_feishu_chats(app_id: str, app_secret: str, timeout: int) -> list[dict[str, Any]]:
    result = feishu_app_request(
        app_id,
        app_secret,
        "/im/v1/chats?page_size=50",
        timeout=timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu list chats failed: {result}")
    return list(result.get("data", {}).get("items", []))


def list_feishu_messages(
    app_id: str,
    app_secret: str,
    chat_id: str,
    lookback_seconds: int,
    timeout: int,
) -> list[dict[str, Any]]:
    now = int(time.time())
    query = urllib.parse.urlencode(
        {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": "50",
            "sort_type": "ByCreateTimeAsc",
            "start_time": str(now - lookback_seconds),
            "end_time": str(now + 60),
        }
    )
    result = feishu_app_request(app_id, app_secret, f"/im/v1/messages?{query}", timeout=timeout)
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu list messages failed: {result}")
    return list(result.get("data", {}).get("items", []))


def message_text(message: dict[str, Any]) -> str:
    body = message.get("body", {})
    content = body.get("content") if isinstance(body, dict) else message.get("content", "")
    if isinstance(content, dict):
        value = content
    else:
        try:
            value = json.loads(content or "{}")
        except json.JSONDecodeError:
            return str(content or "")
    text = str(value.get("text", ""))
    text = re.sub(r"<at[^>]*>.*?</at>", "", text, flags=re.I)
    return html.unescape(text).strip()


def content_text(content: str) -> str:
    try:
        value = json.loads(content or "{}")
    except json.JSONDecodeError:
        return content or ""
    text = str(value.get("text", ""))
    text = re.sub(r"<at[^>]*>.*?</at>", "", text, flags=re.I)
    return html.unescape(text).strip()


def clamp_count(value: str | None, default: int = 20, maximum: int = 200) -> int:
    count = int(value or str(default))
    return max(1, min(count, maximum))


def parse_bot_command(text: str, default_author_id: str, default_tid: str) -> BotCommand | None:
    compact = " ".join(text.split())
    if re.search(r"(?:^|\s)/start(?:\s|$)", compact):
        return BotCommand(action="start")

    legacy = re.search(r"(?:^|\s)/history(?:\s+(\d{1,3}))?(?:\s|$)", compact)
    if legacy:
        return BotCommand(
            action="history",
            target_type="reply",
            target_id=default_author_id,
            count=clamp_count(legacy.group(1), 20, 50),
        )

    match = re.search(r"(?:^|\s)/(history_r|pack_r|history_t|pack_t)(?:\s+(\d+))?(?:\s+(\d{1,4}))?(?:\s|$)", compact)
    if not match:
        return None

    name, raw_target, raw_count = match.groups()
    target = raw_target or (default_tid if name.endswith("_t") else default_author_id)
    count = clamp_count(raw_count, 20, 500 if name.startswith("pack_") else 100)
    target_type = "thread" if name.endswith("_t") else "reply"

    # Compatibility for the requested "/pack_r 45974302 100" spelling.
    if name == "pack_r" and target == default_tid:
        target_type = "thread"

    action = "pack" if name.startswith("pack_") else "history"
    return BotCommand(action=action, target_type=target_type, target_id=target, count=count)


def bot_command_from_form(form: dict[str, Any], default_author_id: str, default_tid: str) -> BotCommand:
    raw_name = str(form.get("command") or form.get("action") or "history_r")
    raw_target = str(form.get("target_id") or "").strip()
    raw_count = str(form.get("count") or "").strip()
    if raw_name not in {"history_r", "pack_r", "history_t", "pack_t"}:
        raw_name = "history_r"
    target = raw_target or (default_tid if raw_name.endswith("_t") else default_author_id)
    count = clamp_count(raw_count or None, 10, 500 if raw_name.startswith("pack_") else 100)
    target_type = "thread" if raw_name.endswith("_t") else "reply"
    action = "pack" if raw_name.startswith("pack_") else "history"
    if raw_name == "pack_r" and target == default_tid:
        target_type = "thread"
    return BotCommand(action=action, target_type=target_type, target_id=target, count=count)


def form_action_name(form: dict[str, Any]) -> str:
    return str(form.get("action") or "")


def start_card(default_author_id: str, default_tid: str) -> dict[str, Any]:
    commands = [
        f"/history_r {default_author_id} 10",
        f"/pack_r {default_author_id} 10",
        f"/history_t {default_tid} 100",
        f"/pack_t {default_tid} 100",
    ]
    content = "\n".join(
        [
            "**NGA watcher commands**",
            "",
            f"Default uid `{default_author_id}` = 狼大",
            f"Default tid `{default_tid}` = 狼大贴",
            "",
            "`/history_r <uid|0> <count>` recent replies by uid",
            "`/pack_r <uid|0> <count>` recent replies as txt",
            "`/history_t <tid> <count>` latest thread posts",
            "`/pack_t <tid> <count>` latest thread posts as txt",
            "",
            "Examples:",
            *[f"`{cmd}`" for cmd in commands],
            "",
            "Interactive input boxes need a Feishu callback URL; this card keeps the commands one tap away for now.",
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "NGA watcher"},
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": content}},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "Open wolf thread"},
                        "url": f"https://bbs.nga.cn/read.php?tid={default_tid}",
                        "type": "default",
                    }
                ],
            },
        ],
    }


def start_form_card(default_author_id: str, default_tid: str) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "NGA watcher"},
        },
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"默认 uid `{default_author_id}` = 狼大\n"
                        f"默认 tid `{default_tid}` = 狼大贴\n\n"
                        "先选一个功能，机器人会发出已预填默认参数的执行卡片。"
                    ),
                },
                *preset_actions_elements(default_author_id, default_tid),
                {
                    "tag": "hr",
                },
                {
                    "tag": "markdown",
                    "content": (
                        "也可以直接发命令：\n"
                        f"`/history_r {default_author_id} 10`\n"
                        f"`/pack_r {default_author_id} 10`\n"
                        f"`/history_t {default_tid} 100`\n"
                        f"`/pack_t {default_tid} 100`"
                    ),
                },
            ]
        },
    }


def preset_actions_elements(default_author_id: str, default_tid: str) -> list[dict[str, Any]]:
    return [
        preset_button("回复卡片", "history_r", default_author_id, "10"),
        preset_button("回复打包", "pack_r", default_author_id, "10"),
        preset_button("帖子卡片", "history_t", default_tid, "100"),
        preset_button("帖子打包", "pack_t", default_tid, "100"),
    ]


def preset_button(label: str, command: str, target_id: str, count: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": "default",
        "behaviors": [
            {
                "type": "callback",
                "value": {
                    "action": "open_preset_form",
                    "command": command,
                    "target_id": target_id,
                    "count": count,
                },
            }
        ],
    }


def preset_buttons_element_old(default_author_id: str, default_tid: str) -> dict[str, Any]:
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "columns": [
            preset_button_column("回复卡片", "history_r", default_author_id, "10"),
            preset_button_column("回复打包", "pack_r", default_author_id, "10"),
            preset_button_column("帖子卡片", "history_t", default_tid, "100"),
            preset_button_column("帖子打包", "pack_t", default_tid, "100"),
        ],
    }


def preset_button_column(label: str, command: str, target_id: str, count: str) -> dict[str, Any]:
    return {
        "tag": "column",
        "width": "weighted",
        "weight": 1,
        "elements": [
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": "default",
                "behaviors": [
                    {
                        "type": "callback",
                        "value": {
                            "action": "open_preset_form",
                            "command": command,
                            "target_id": target_id,
                            "count": count,
                        },
                    }
                ],
            }
        ],
    }


def command_form_card(command: str, target_id: str, count: str) -> dict[str, Any]:
    labels = {
        "history_r": "回复卡片",
        "pack_r": "回复打包",
        "history_t": "帖子卡片",
        "pack_t": "帖子打包",
    }
    target_label = "uid" if command.endswith("_r") else "tid"
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": labels.get(command, "NGA command")},
        },
        "body": {
            "elements": [
                {
                    "tag": "form",
                    "name": "nga_command_form",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "target_id",
                            "placeholder": {"tag": "plain_text", "content": target_label},
                            "default_value": target_id,
                        },
                        {
                            "tag": "input",
                            "name": "count",
                            "placeholder": {"tag": "plain_text", "content": "数量"},
                            "default_value": count,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "执行"},
                            "type": "primary",
                            "name": "execute",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {
                                        "action": "run_nga_command",
                                        "command": command,
                                    },
                                }
                            ],
                            "form_action_type": "submit",
                        },
                    ],
                }
            ]
        },
    }


def push_feishu_card(args: argparse.Namespace, card: dict[str, Any]) -> None:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    if not (app_id and app_secret and receive_id):
        raise SystemExit("Missing FEISHU_APP_ID, FEISHU_APP_SECRET, or FEISHU_RECEIVE_ID.")
    result = feishu_app_request(
        app_id,
        app_secret,
        f"/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
        timeout=args.timeout,
        method="POST",
        body={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu card push failed: {result}")


def args_for_chat(args: argparse.Namespace, chat_id: str) -> argparse.Namespace:
    cloned = copy.copy(args)
    cloned.feishu_receive_id = chat_id
    cloned.feishu_id_type = "chat_id"
    return cloned


def run_bot_command(args: argparse.Namespace, command: BotCommand) -> None:
    if command.action == "start":
        push_feishu_card(args, start_form_card(args.default_author_id, args.default_tid))
        return

    if command.target_type == "reply":
        posts = collect_replies_with_retries(args, command.target_id, command.count)
        label = f"uid {command.target_id or 'any'}"
    elif command.target_type == "thread":
        posts = collect_thread_tail_with_retries(args, command.target_id, command.count)
        label = f"tid {command.target_id}"
    else:
        raise RuntimeError(f"Unknown command target: {command}")

    title = f"NGA {label} latest {len(posts)}"
    if command.action == "pack":
        file_name = f"nga_{command.target_type}_{command.target_id or 'any'}_{len(posts)}_{int(time.time())}.txt"
        push_feishu_file(args, file_name, posts_to_txt(posts, title))
    else:
        creds = feishu_credentials(args)
        if args.message_format == "card" and len(posts) > 20:
            for start in range(0, len(posts), 20):
                chunk = posts[start : start + 20]
                chunk_title = f"{title} ({start + 1}-{start + len(chunk)})"
                push_feishu_app_posts(*creds, chunk, chunk_title, args.timeout, args.message_format)
                time.sleep(0.4)
        else:
            push_feishu_app_posts(*creds, posts, title, args.timeout, args.message_format)


def run_command_background(args: argparse.Namespace, command: BotCommand, label: str) -> None:
    def worker() -> None:
        try:
            print(f"handling {label}: {command}")
            run_bot_command(args, command)
            print(f"done {label}: {command}")
        except Exception as exc:
            print(f"command failed {label}: {exc}", file=sys.stderr)
            try:
                err_post = NgaPost(
                    key="ws-error",
                    subject="Command failed",
                    content=str(exc),
                    url="https://bbs.nga.cn/",
                    post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                )
                push_feishu_app_posts(*feishu_credentials(args), [err_post], "NGA command failed", args.timeout, "text")
            except Exception as nested:
                print(f"failed to send error message: {nested}", file=sys.stderr)

    threading.Thread(target=worker, daemon=True).start()


def card_action_to_form(event: Any) -> dict[str, Any]:
    action = getattr(getattr(event, "event", None), "action", None)
    if action is None:
        return {}
    form_value = getattr(action, "form_value", None) or {}
    value = getattr(action, "value", None) or {}
    if isinstance(form_value, dict):
        merged = dict(form_value)
    else:
        merged = {}
    if isinstance(value, dict):
        merged.update({k: v for k, v in value.items() if k not in merged})
    return merged


def card_action_chat_id(event: Any, fallback: str) -> str:
    context = getattr(getattr(event, "event", None), "context", None)
    chat_id = getattr(context, "open_chat_id", "") if context is not None else ""
    return chat_id or fallback


def start_ws(args: argparse.Namespace) -> None:
    try:
        import lark_oapi as lark
        from lark_oapi.event.callback.model.p2_card_action_trigger import P2CardActionTriggerResponse
    except ImportError as exc:
        raise SystemExit("Missing lark-oapi. Install with: python -m pip install lark-oapi") from exc

    app_id, app_secret, receive_id, _receive_id_type = feishu_credentials(args)
    if not app_id or not app_secret:
        raise SystemExit("Missing FEISHU_APP_ID or FEISHU_APP_SECRET.")

    def on_message(event: Any) -> None:
        msg = getattr(getattr(event, "event", None), "message", None)
        if msg is None:
            return
        text = content_text(getattr(msg, "content", "") or "")
        command = parse_bot_command(text, args.default_author_id, args.default_tid)
        if command is None:
            return
        chat_id = getattr(msg, "chat_id", "") or receive_id
        run_command_background(args_for_chat(args, chat_id), command, f"message:{getattr(msg, 'message_id', '')}")

    def on_card_action(event: Any) -> Any:
        form = card_action_to_form(event)
        chat_id = card_action_chat_id(event, receive_id)
        try:
            action = form_action_name(form)
            if action == "open_preset_form":
                command_name = str(form.get("command") or "history_r")
                target_id = str(form.get("target_id") or (args.default_tid if command_name.endswith("_t") else args.default_author_id))
                count = str(form.get("count") or ("100" if command_name.endswith("_t") else "10"))
                push_feishu_card(args_for_chat(args, chat_id), command_form_card(command_name, target_id, count))
                return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "已打开预填表单"}})
            command = bot_command_from_form(form, args.default_author_id, args.default_tid)
            run_command_background(args_for_chat(args, chat_id), command, "card-action")
            return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "已收到，正在处理"}})
        except Exception as exc:
            return P2CardActionTriggerResponse({"toast": {"type": "error", "content": f"参数错误: {exc}"}})

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(on_message)
        .register_p2_card_action_trigger(on_card_action)
        .build()
    )

    if not args.ws_no_watch:
        def watch_loop() -> None:
            while True:
                try:
                    run_once(args)
                except Exception as exc:
                    print(f"watch loop failed: {exc}", file=sys.stderr)
                jitter = random.uniform(-args.jitter, args.jitter) if args.jitter > 0 else 0
                time.sleep(max(1, args.interval + jitter))

        threading.Thread(target=watch_loop, daemon=True).start()
        print("Started NGA watch loop in the background.")

    print("Starting Feishu WebSocket client. Press Ctrl+C to stop.")
    print("Make sure the app uses event subscription via long connection and has message/card action events enabled.")
    lark.ws.Client(app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.INFO).start()


def send_test_message(args: argparse.Namespace) -> None:
    post = NgaPost(
        key="test",
        subject="NGA watcher test",
        content="This is a test message from nga_feishu_watch.py.",
        url="https://bbs.nga.cn/thread.php?searchpost=1&authorid=150058",
        post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    )
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    if app_id and app_secret and receive_id:
        push_feishu_app_posts(
            app_id,
            app_secret,
            receive_id,
            receive_id_type,
            [post],
            "NGA watcher test",
            args.timeout,
            args.message_format,
        )
    else:
        push_to_feishu(args, post)
    print("Sent test message.")


def push_to_feishu(args: argparse.Namespace, post: NgaPost) -> None:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")

    if app_id or app_secret or receive_id:
        if not (app_id and app_secret and receive_id):
            raise SystemExit("Missing FEISHU_APP_ID, FEISHU_APP_SECRET, or FEISHU_RECEIVE_ID.")
        push_feishu_app(app_id, app_secret, receive_id, receive_id_type, post, args.timeout, args.message_format)
        return

    if not webhook:
        raise SystemExit("Missing Feishu target. Set app credentials + receive id, or FEISHU_WEBHOOK.")
    push_feishu(webhook, secret, post, args.timeout)


def collect_posts(author_id: str, cookie: str, max_pages: int, timeout: int) -> list[NgaPost]:
    posts: list[NgaPost] = []
    for page in range(1, max_pages + 1):
        payload = fetch_nga_page(author_id, page, cookie, timeout)
        page_posts = extract_posts(payload)
        if page > 1 and not page_posts:
            break
        posts.extend(page_posts)
    return posts


def collect_recent_replies(author_id: str, count: int, cookie: str, timeout: int) -> list[NgaPost]:
    pages = max(1, (count + 19) // 20)
    return collect_posts(author_id, cookie, pages, timeout)[:count]


def collect_thread_tail(tid: str, count: int, cookie: str, timeout: int) -> list[NgaPost]:
    first_payload = fetch_nga_thread_page(tid, 99999, cookie, timeout)
    first_posts, last_page = extract_thread_posts(first_payload)
    if not last_page:
        last_page = 1

    posts_by_page: list[NgaPost] = list(first_posts)
    page = last_page - 1
    while len(posts_by_page) < count and page >= 1:
        payload = fetch_nga_thread_page(tid, page, cookie, timeout)
        page_posts, _ = extract_thread_posts(payload)
        posts_by_page = page_posts + posts_by_page
        page -= 1
    return posts_by_page[-count:]


def with_retries(label: str, attempts: int, delay: float, fn: Any) -> Any:
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt == attempts:
                break
            sleep_for = delay * attempt + random.uniform(0, delay)
            print(f"{label} failed ({attempt}/{attempts}): {exc}; retrying in {sleep_for:.1f}s", file=sys.stderr)
            time.sleep(sleep_for)
    raise RuntimeError(f"{label} failed after {attempts} attempts: {last_exc}")


def collect_posts_with_retries(args: argparse.Namespace, count_pages: int | None = None) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("Missing NGA_COOKIE. Copy Cookie from a logged-in bbs.nga.cn browser session.")
    max_pages = count_pages if count_pages is not None else args.max_pages
    return with_retries(
        "NGA fetch",
        args.retries,
        args.retry_delay,
        lambda: collect_posts(args.author_id, cookie, max_pages, args.timeout),
    )


def collect_replies_with_retries(args: argparse.Namespace, author_id: str, count: int) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("Missing NGA_COOKIE. Copy Cookie from a logged-in bbs.nga.cn browser session.")
    return with_retries(
        "NGA reply fetch",
        args.retries,
        args.retry_delay,
        lambda: collect_recent_replies(author_id, count, cookie, args.timeout),
    )


def collect_thread_tail_with_retries(args: argparse.Namespace, tid: str, count: int) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("Missing NGA_COOKIE. Copy Cookie from a logged-in bbs.nga.cn browser session.")
    return with_retries(
        "NGA thread fetch",
        args.retries,
        args.retry_delay,
        lambda: collect_thread_tail(tid, count, cookie, args.timeout),
    )


def handle_feishu_commands(args: argparse.Namespace, state: dict[str, Any]) -> bool:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    if args.disable_commands or not (app_id and app_secret and receive_id) or receive_id_type != "chat_id":
        return False

    handled = set(state.get("handled_commands", []))
    changed = False
    messages = list_feishu_messages(app_id, app_secret, receive_id, args.command_lookback, args.timeout)
    for message in messages:
        message_id = str(message.get("message_id", ""))
        if not message_id or message_id in handled:
            continue
        text = message_text(message)
        command = parse_bot_command(text, args.default_author_id, args.default_tid)
        if command is None:
            continue

        try:
            run_bot_command(args, command)
        except Exception as exc:
            err_post = NgaPost(
                key="history-error",
                subject="Command failed",
                content=str(exc),
                url="https://bbs.nga.cn/thread.php?searchpost=1&authorid=150058",
                post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
            )
            push_feishu_app_posts(
                app_id,
                app_secret,
                receive_id,
                receive_id_type,
                [err_post],
                "NGA history failed",
                args.timeout,
                "text",
            )
        handled.add(message_id)
        changed = True

    if changed:
        state["handled_commands"] = sorted(handled)[-300:]
        state["commands_updated_at"] = int(time.time())
    return changed


def run_once(args: argparse.Namespace) -> int:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("Missing NGA_COOKIE. Copy Cookie from a logged-in bbs.nga.cn browser session.")

    state_path = Path(args.state_path)
    state = read_json(state_path, {"seen": []})
    seen = set(state.get("seen", []))

    posts = collect_posts_with_retries(args)
    if args.mark_seen:
        for post in posts:
            seen.add(post.key)
        state["seen"] = sorted(seen)
        state["updated_at"] = int(time.time())
        write_json(state_path, state)
        print(f"Marked {len(posts)} fetched posts as seen.")
        return 0

    new_posts = [post for post in posts if post.key not in seen]
    new_posts.reverse()

    for post in new_posts:
        if args.dry_run:
            print(f"[DRY-RUN] {post.subject} {post.url}\n{post.content[:500]}\n")
        else:
            push_to_feishu(args, post)
            seen.add(post.key)

    if not args.dry_run:
        state["seen"] = sorted(seen)
        state["updated_at"] = int(time.time())
        write_json(state_path, state)
    print(f"Fetched {len(posts)} posts, pushed {len(new_posts)} new posts.")
    return len(new_posts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch an NGA user's replies and push new ones to Feishu.")
    parser.add_argument("--author-id", default=os.getenv("NGA_AUTHOR_ID", DEFAULT_AUTHOR_ID))
    parser.add_argument("--default-author-id", default=os.getenv("NGA_DEFAULT_AUTHOR_ID", DEFAULT_AUTHOR_ID))
    parser.add_argument("--default-tid", default=os.getenv("NGA_DEFAULT_TID", DEFAULT_TID))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("NGA_MAX_PAGES", "1")))
    parser.add_argument("--state-path", default=os.getenv("NGA_STATE_PATH", ".nga_seen.json"))
    parser.add_argument("--cookie", default="")
    parser.add_argument("--webhook", default="")
    parser.add_argument("--secret", default="")
    parser.add_argument("--feishu-app-id", default="")
    parser.add_argument("--feishu-app-secret", default="")
    parser.add_argument("--feishu-receive-id", default="")
    parser.add_argument("--feishu-id-type", default=os.getenv("FEISHU_ID_TYPE", "chat_id"))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mark-seen", action="store_true", help="Record current fetched posts without pushing.")
    parser.add_argument("--list-feishu-chats", action="store_true", help="List chats visible to the Feishu app bot.")
    parser.add_argument("--send-test", action="store_true", help="Send one Feishu test message and exit.")
    parser.add_argument("--message-format", choices=["card", "text"], default=os.getenv("FEISHU_MESSAGE_FORMAT", "card"))
    parser.add_argument("--disable-commands", action="store_true", help="Do not poll Feishu group commands.")
    parser.add_argument("--command-lookback", type=int, default=int(os.getenv("FEISHU_COMMAND_LOOKBACK", "600")))
    parser.add_argument("--retries", type=int, default=int(os.getenv("NGA_RETRIES", "10")))
    parser.add_argument("--retry-delay", type=float, default=float(os.getenv("NGA_RETRY_DELAY", "2")))
    parser.add_argument("--interval", type=int, default=int(os.getenv("NGA_INTERVAL", "60")))
    parser.add_argument("--jitter", type=int, default=int(os.getenv("NGA_JITTER", "20")))
    parser.add_argument("--once", action="store_true", help="Run one polling cycle and exit.")
    parser.add_argument("--ws", action="store_true", help="Use Feishu WebSocket events for messages and card actions.")
    parser.add_argument("--ws-no-watch", action="store_true", help="In --ws mode, do not start the NGA watch loop.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.ws:
        start_ws(args)
        return
    if args.list_feishu_chats:
        app_id = args.feishu_app_id or os.getenv("FEISHU_APP_ID", "")
        app_secret = args.feishu_app_secret or os.getenv("FEISHU_APP_SECRET", "")
        if not app_id or not app_secret:
            raise SystemExit("Missing FEISHU_APP_ID or FEISHU_APP_SECRET.")
        chats = list_feishu_chats(app_id, app_secret, args.timeout)
        for chat in chats:
            print(
                f"{chat.get('chat_id', '')}\t"
                f"{chat.get('name', '')}\t"
                f"{chat.get('chat_type', '')}"
            )
        print(f"Listed {len(chats)} chats.")
        return
    if args.send_test:
        send_test_message(args)
        return
    if args.mark_seen:
        run_once(args)
        return

    while True:
        try:
            state_path = Path(args.state_path)
            state = read_json(state_path, {"seen": []})
            try:
                if handle_feishu_commands(args, state):
                    write_json(state_path, state)
            except Exception as exc:
                print(f"Feishu command polling failed: {exc}", file=sys.stderr)
            run_once(args)
        except Exception as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        jitter = random.uniform(-args.jitter, args.jitter) if args.jitter > 0 else 0
        sleep_for = max(1, args.interval + jitter)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
