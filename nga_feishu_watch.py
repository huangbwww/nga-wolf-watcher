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
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


NGA_ENDPOINT = "https://bbs.nga.cn/thread.php"
NGA_READ_ENDPOINT = "https://bbs.nga.cn/read.php"
FEISHU_API = "https://open.feishu.cn/open-apis"
DEFAULT_AUTHOR_ID = "150058"
DEFAULT_TID = "45974302"
DEFAULT_REPLY_COUNT = 5
DEFAULT_THREAD_COUNT = 10
DEFAULT_QUIET_START_DAY = 5
DEFAULT_QUIET_END_DAY = 0
DEFAULT_QUIET_DAYS = [5, 6]
DEFAULT_QUIET_START_TIME = "00:00"
DEFAULT_QUIET_END_TIME = "00:00"
DEFAULT_QUIET_POLICY = "ignore"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
QUOTE_END_MARKER = "__NGA_QUOTE_END__"


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
    count: int = DEFAULT_REPLY_COUNT

    def __str__(self) -> str:
        action_labels = {"start": "开始菜单", "history": "查询", "pack": "打包"}
        target_labels = {"reply": "用户回复", "thread": "帖子回复", "": "无目标"}
        return (
            f"{action_labels.get(self.action, self.action)} "
            f"{target_labels.get(self.target_type, self.target_type)} "
            f"{self.target_id or '-'} {self.count} 条"
        ).strip()


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
        raise RuntimeError(f"请求 {url} 返回 HTTP {exc.code}：{detail}") from exc
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


def parse_hhmm(value: str) -> int:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", str(value).strip())
    if not match:
        raise ValueError(f"时间格式无效：{value}，请使用 HH:MM")
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_quiet_days(value: Any) -> list[int]:
    if value is None or value == "":
        return list(DEFAULT_QUIET_DAYS)
    if isinstance(value, str):
        raw_items = [item.strip() for item in value.split(",") if item.strip()]
    elif isinstance(value, Iterable):
        raw_items = list(value)
    else:
        raw_items = [value]
    days: list[int] = []
    for raw in raw_items:
        day = int(raw)
        if day < 0 or day > 6:
            raise ValueError("免打扰星期必须在 0-6 之间")
        if day not in days:
            days.append(day)
    return sorted(days)


def parse_weekday(value: Any, default: int) -> int:
    try:
        day = int(value)
    except (TypeError, ValueError):
        day = default
    if day < 0 or day > 6:
        raise ValueError("免打扰星期必须在 0-6 之间")
    return day


def is_weekly_range_time(start_day: int, start_minute: int, end_day: int, end_minute: int, now: time.struct_time) -> bool:
    current = now.tm_wday * 1440 + now.tm_hour * 60 + now.tm_min
    start = start_day * 1440 + start_minute
    end = end_day * 1440 + end_minute
    if start == end:
        return True
    if start < end:
        return start <= current < end
    return current >= start or current < end


def is_legacy_quiet_time(args: argparse.Namespace, now: time.struct_time) -> bool:
    days = parse_quiet_days(getattr(args, "quiet_days", DEFAULT_QUIET_DAYS))
    if not days:
        return False
    start = parse_hhmm(str(getattr(args, "quiet_start_time", DEFAULT_QUIET_START_TIME)))
    end = parse_hhmm(str(getattr(args, "quiet_end_time", "23:59")))
    today = now.tm_wday
    minute = now.tm_hour * 60 + now.tm_min
    if start == end:
        return today in days
    if start < end:
        return today in days and start <= minute <= end
    previous_day = (today - 1) % 7
    return (today in days and minute >= start) or (previous_day in days and minute <= end)


def is_quiet_time(args: argparse.Namespace, now: time.struct_time | None = None) -> bool:
    if not bool(getattr(args, "quiet_hours_enabled", False)):
        return False
    local_now = now or time.localtime()
    if not hasattr(args, "quiet_start_day") and not hasattr(args, "quiet_end_day"):
        return is_legacy_quiet_time(args, local_now)
    start_day = parse_weekday(getattr(args, "quiet_start_day", DEFAULT_QUIET_START_DAY), DEFAULT_QUIET_START_DAY)
    end_day = parse_weekday(getattr(args, "quiet_end_day", DEFAULT_QUIET_END_DAY), DEFAULT_QUIET_END_DAY)
    start = parse_hhmm(str(getattr(args, "quiet_start_time", DEFAULT_QUIET_START_TIME)))
    end = parse_hhmm(str(getattr(args, "quiet_end_time", DEFAULT_QUIET_END_TIME)))
    return is_weekly_range_time(start_day, start, end_day, end, local_now)


def fetch_nga_page(author_id: str, page: int, cookie: str, timeout: int) -> dict[str, Any]:
    params = {
        "searchpost": "1",
        "page": str(page),
        "__output": "8",
    }
    if author_id and author_id != "0":
        params["authorid"] = author_id
    query = urllib.parse.urlencode(params)
    return fetch_nga_json(f"{NGA_ENDPOINT}?{query}", cookie, timeout, f"用户回复第 {page} 页")


def fetch_nga_thread_page(tid: str, page: int, cookie: str, timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode({"tid": tid, "page": str(page), "__output": "8"})
    return fetch_nga_json(f"{NGA_READ_ENDPOINT}?{query}", cookie, timeout, f"帖子 {tid} 第 {page} 页")


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
            status = getattr(resp, "status", 200)
            content_type = resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        charset = exc.headers.get_content_charset() or "gb18030"
        status = exc.code
        content_type = exc.headers.get("Content-Type", "")

    text = raw.decode(charset, errors="replace")
    try:
        payload = json.loads(text, strict=False)
    except json.JSONDecodeError as exc:
        preview = re.sub(r"\s+", " ", text[:300]).strip()
        if not preview:
            preview = "<空响应>"
        raise RuntimeError(
            f"NGA 在 {label} 返回的不是 JSON："
            f"状态码={status}，内容类型={content_type}，响应预览={preview}"
        ) from exc
    if payload.get("error"):
        err = payload["error"]
        message = err.get("0") if isinstance(err, dict) else str(err)
        raise RuntimeError(f"NGA 在 {label} 返回错误：{message}")
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
    value = re.sub(r"\[quote[^\]]*\]", "", value, flags=re.I)
    value = re.sub(r"\[/quote\]", f"\n\n{QUOTE_END_MARKER}\n\n", value, flags=re.I)
    value = re.sub(r"\[/?(?:collapse|color|size|b|i|u|url|img|align)[^\]]*\]", "", value, flags=re.I)
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


def parse_post_time(value: str) -> time.struct_time | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return time.strptime(text, fmt)
        except ValueError:
            continue
    return None


def post_in_quiet_range(args: argparse.Namespace, post: NgaPost) -> bool:
    post_time = parse_post_time(post.post_time)
    if post_time is None:
        return False
    return is_quiet_time(args, post_time)


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


def truncate_text(value: str, limit: int) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


def display_text(value: str) -> str:
    return value.replace(QUOTE_END_MARKER, "").strip()


def split_quoted_reply(content: str) -> tuple[str, str, str] | None:
    match = re.match(
        r"^\s*(\[[^\]\n]*pid[^\]\n]*\]\s*Reply\s*\[/pid\]\s*Post by\s+.*?(?:\([^)\n]*\))?:)\s*(.*)$",
        content,
        flags=re.I | re.S,
    )
    if not match:
        return None

    quote_header = match.group(1).strip()
    rest = match.group(2).strip()
    if not rest:
        return None

    if QUOTE_END_MARKER in rest:
        quote_body, reply_body = rest.split(QUOTE_END_MARKER, 1)
        quote_body = quote_body.strip()
        reply_body = reply_body.strip()
        if reply_body:
            return quote_header, quote_body, reply_body
        if quote_body:
            return quote_header, "", quote_body

    parts = re.split(r"\n\s*\n", rest, maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        return quote_header, "", rest
    return quote_header, parts[0].strip(), parts[1].strip()


def lark_quote(value: str) -> str:
    escaped = lark_md_escape(value.strip())
    if not escaped:
        return ""
    return "\n".join(f"> {line}" if line else ">" for line in escaped.splitlines())


def post_card_element(post: NgaPost) -> list[dict[str, Any]]:
    title = lark_md_escape(post.subject)
    time_text = lark_md_escape(post.post_time or "unknown")
    author_text = lark_md_escape(post.author or post.author_id or "unknown")
    floor_text = f" | #{lark_md_escape(post.floor)}" if post.floor else ""
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{title}**\n{time_text} | {author_text}{floor_text}",
            },
        },
    ]

    quoted = split_quoted_reply(post.content)
    if quoted:
        quote_header, quote_body, reply_body = quoted
        quote_lines = [quote_header]
        if quote_body:
            quote_lines.extend(["", truncate_text(display_text(quote_body), 420)])
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**被回复内容**\n{lark_quote(chr(10).join(quote_lines))}",
                },
            }
        )
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**本次回复**\n{lark_md_escape(truncate_text(display_text(reply_body), 700)).replace(chr(10), chr(10) + chr(10))}",
                },
            }
        )
    else:
        excerpt = lark_md_escape(truncate_text(display_text(post.content), 850)).replace("\n", "\n\n")
        elements.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": f"**回复内容**\n{excerpt}",
                },
            }
        )

    elements.append(
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "打开 NGA"},
                    "url": post.url,
                    "type": "default",
                }
            ],
        },
    )
    return elements


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


def feishu_deferred_summary_card(posts: list[NgaPost], total_count: int) -> dict[str, Any]:
    shown = posts[:20]
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"免打扰期间暂存了 **{total_count}** 条新回复。\n"
                    f"推送时间：{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
                ),
            },
        }
    ]
    if shown:
        elements.append({"tag": "hr"})
    for idx, post in enumerate(shown, 1):
        if idx > 1:
            elements.append({"tag": "hr"})
        elements.extend(post_card_element(post))
    remaining = total_count - len(shown)
    if remaining > 0:
        elements.append({"tag": "hr"})
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"还有 **{remaining}** 条未在卡片中展开，请打开 NGA 查看。"},
            }
        )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "免打扰期间新回复汇总"},
        },
        "elements": elements,
    }


def serialize_post(post: NgaPost) -> dict[str, str]:
    return {key: str(value) for key, value in asdict(post).items()}


def deserialize_post(value: Any) -> NgaPost | None:
    if not isinstance(value, dict):
        return None
    try:
        return NgaPost(
            key=str(value.get("key") or ""),
            subject=str(value.get("subject") or "(无标题)"),
            content=str(value.get("content") or ""),
            url=str(value.get("url") or "https://bbs.nga.cn/"),
            post_time=str(value.get("post_time") or ""),
            author=str(value.get("author") or ""),
            author_id=str(value.get("author_id") or ""),
            floor=str(value.get("floor") or ""),
        )
    except Exception:
        return None


def deferred_posts_from_state(state: dict[str, Any]) -> list[NgaPost]:
    posts: list[NgaPost] = []
    for item in state.get("deferred_posts", []):
        post = deserialize_post(item)
        if post and post.key:
            posts.append(post)
    return posts


def append_deferred_posts(state: dict[str, Any], posts: list[NgaPost]) -> int:
    existing = deferred_posts_from_state(state)
    seen_keys = {post.key for post in existing}
    added = 0
    for post in posts:
        if post.key in seen_keys:
            continue
        existing.append(post)
        seen_keys.add(post.key)
        added += 1
    if added:
        state["deferred_posts"] = [serialize_post(post) for post in existing]
        state.setdefault("deferred_started_at", int(time.time()))
        state["deferred_updated_at"] = int(time.time())
    return added


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
        raise RuntimeError(f"飞书 Webhook 推送失败：{result}")


def get_feishu_tenant_access_token(app_id: str, app_secret: str, timeout: int) -> str:
    result = http_json(
        f"{FEISHU_API}/auth/v3/tenant_access_token/internal",
        method="POST",
        body={"app_id": app_id, "app_secret": app_secret},
        timeout=timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"飞书访问凭证获取失败：{result}")
    token = result.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"飞书访问凭证响应缺少 token：{result}")
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
        raise SystemExit("缺少 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID。")
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
        raise RuntimeError(f"飞书应用消息推送失败：{result}")


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
        raise RuntimeError(f"飞书文件上传失败：HTTP {exc.code}: {detail}") from exc
    if result.get("code") != 0:
        raise RuntimeError(f"飞书文件上传失败：{result}")
    file_key = result.get("data", {}).get("file_key")
    if not file_key:
        raise RuntimeError(f"飞书文件上传响应缺少 file_key：{result}")
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
        raise RuntimeError(f"飞书文件消息发送失败：{result}")


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
        raise RuntimeError(f"飞书应用消息推送失败：{result}")


def push_feishu_app_card(
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    card: dict[str, Any],
    timeout: int,
) -> None:
    result = feishu_app_request(
        app_id,
        app_secret,
        f"/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
        timeout=timeout,
        method="POST",
        body={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
    )
    if result.get("code") != 0:
        raise RuntimeError(f"飞书卡片发送失败：{result}")


def list_feishu_chats(app_id: str, app_secret: str, timeout: int) -> list[dict[str, Any]]:
    result = feishu_app_request(
        app_id,
        app_secret,
        "/im/v1/chats?page_size=50",
        timeout=timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"飞书群组查询失败：{result}")
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
        raise RuntimeError(f"飞书消息查询失败：{result}")
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


def default_command_count(command_name: str) -> int:
    return DEFAULT_THREAD_COUNT if command_name.endswith("_t") else DEFAULT_REPLY_COUNT


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
            count=clamp_count(legacy.group(1), DEFAULT_REPLY_COUNT, 50),
        )

    match = re.search(r"(?:^|\s)/(history_r|pack_r|history_t|pack_t)(?:\s+(\d+))?(?:\s+(\d{1,4}))?(?:\s|$)", compact)
    if not match:
        return None

    name, raw_target, raw_count = match.groups()
    target = raw_target or (default_tid if name.endswith("_t") else default_author_id)
    count = clamp_count(raw_count, default_command_count(name), 500 if name.startswith("pack_") else 100)
    target_type = "thread" if name.endswith("_t") else "reply"

    # Compatibility for the older "/pack_r <default tid> <count>" spelling.
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
    count = clamp_count(raw_count or None, default_command_count(raw_name), 500 if raw_name.startswith("pack_") else 100)
    target_type = "thread" if raw_name.endswith("_t") else "reply"
    action = "pack" if raw_name.startswith("pack_") else "history"
    if raw_name == "pack_r" and target == default_tid:
        target_type = "thread"
    return BotCommand(action=action, target_type=target_type, target_id=target, count=count)


def form_action_name(form: dict[str, Any]) -> str:
    return str(form.get("action") or "")


def start_card(default_author_id: str, default_tid: str) -> dict[str, Any]:
    commands = [
        f"/history_r {default_author_id} {DEFAULT_REPLY_COUNT}",
        f"/pack_r {default_author_id} {DEFAULT_REPLY_COUNT}",
        f"/history_t {default_tid} {DEFAULT_THREAD_COUNT}",
        f"/pack_t {default_tid} {DEFAULT_THREAD_COUNT}",
    ]
    content = "\n".join(
        [
            "**NGA 监听命令**",
            "",
            f"默认 uid `{default_author_id}` = 狼大",
            f"默认 tid `{default_tid}` = 狼大帖",
            "",
            "`/history_r <uid|0> <count>` 查询用户回复",
            "`/pack_r <uid|0> <count>` 打包用户回复为 txt",
            "`/history_t <tid> <count>` 查询帖子回复",
            "`/pack_t <tid> <count>` 打包帖子回复为 txt",
            "",
            "示例：",
            *[f"`{cmd}`" for cmd in commands],
            "",
            "也可以直接点击下面的按钮快速发送常用命令。",
        ]
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "NGA 监听"},
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
            "title": {"tag": "plain_text", "content": "NGA 监听"},
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
                        f"`/history_r {default_author_id} {DEFAULT_REPLY_COUNT}`\n"
                        f"`/pack_r {default_author_id} {DEFAULT_REPLY_COUNT}`\n"
                        f"`/history_t {default_tid} {DEFAULT_THREAD_COUNT}`\n"
                        f"`/pack_t {default_tid} {DEFAULT_THREAD_COUNT}`"
                    ),
                },
            ]
        },
    }


def preset_actions_elements(default_author_id: str, default_tid: str) -> list[dict[str, Any]]:
    return [
        preset_button("查询用户回复", "history_r", default_author_id, str(DEFAULT_REPLY_COUNT)),
        preset_button("打包用户回复", "pack_r", default_author_id, str(DEFAULT_REPLY_COUNT)),
        preset_button("查询帖子回复", "history_t", default_tid, str(DEFAULT_THREAD_COUNT)),
        preset_button("打包帖子回复", "pack_t", default_tid, str(DEFAULT_THREAD_COUNT)),
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
            preset_button_column("查询用户回复", "history_r", default_author_id, str(DEFAULT_REPLY_COUNT)),
            preset_button_column("打包用户回复", "pack_r", default_author_id, str(DEFAULT_REPLY_COUNT)),
            preset_button_column("查询帖子回复", "history_t", default_tid, str(DEFAULT_THREAD_COUNT)),
            preset_button_column("打包帖子回复", "pack_t", default_tid, str(DEFAULT_THREAD_COUNT)),
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
        "history_r": "查询用户回复",
        "pack_r": "打包用户回复",
        "history_t": "查询帖子回复",
        "pack_t": "打包帖子回复",
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
        raise SystemExit("缺少 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID。")
    result = feishu_app_request(
        app_id,
        app_secret,
        f"/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
        timeout=args.timeout,
        method="POST",
        body={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
    )
    if result.get("code") != 0:
        raise RuntimeError(f"飞书卡片发送失败：{result}")


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
        label = f"用户 {command.target_id or '任意'}"
    elif command.target_type == "thread":
        posts = collect_thread_tail_with_retries(args, command.target_id, command.count)
        label = f"帖子 {command.target_id}"
    else:
        raise RuntimeError(f"未知命令目标：{command}")

    title = f"NGA {label} 最新 {len(posts)} 条"
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
            print(f"开始处理 {label}: {command}")
            run_bot_command(args, command)
            print(f"处理完成 {label}: {command}")
        except Exception as exc:
            print(f"命令处理失败 {label}: {exc}", file=sys.stderr)
            try:
                err_post = NgaPost(
                    key="ws-error",
                    subject="命令处理失败",
                    content=str(exc),
                    url="https://bbs.nga.cn/",
                    post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                )
                push_feishu_app_posts(*feishu_credentials(args), [err_post], "NGA 命令处理失败", args.timeout, "text")
            except Exception as nested:
                print(f"发送错误消息失败: {nested}", file=sys.stderr)

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
        raise SystemExit("缺少 lark-oapi。请执行：python -m pip install lark-oapi") from exc

    app_id, app_secret, receive_id, _receive_id_type = feishu_credentials(args)
    if not app_id or not app_secret:
        raise SystemExit("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET。")

    def on_message(event: Any) -> None:
        msg = getattr(getattr(event, "event", None), "message", None)
        if msg is None:
            return
        text = content_text(getattr(msg, "content", "") or "")
        command = parse_bot_command(text, args.default_author_id, args.default_tid)
        if command is None:
            return
        chat_id = getattr(msg, "chat_id", "") or receive_id
        run_command_background(args_for_chat(args, chat_id), command, f"飞书消息:{getattr(msg, 'message_id', '')}")

    def on_card_action(event: Any) -> Any:
        form = card_action_to_form(event)
        chat_id = card_action_chat_id(event, receive_id)
        try:
            action = form_action_name(form)
            if action == "open_preset_form":
                command_name = str(form.get("command") or "history_r")
                target_id = str(form.get("target_id") or (args.default_tid if command_name.endswith("_t") else args.default_author_id))
                count = str(form.get("count") or default_command_count(command_name))
                push_feishu_card(args_for_chat(args, chat_id), command_form_card(command_name, target_id, count))
                return P2CardActionTriggerResponse({"toast": {"type": "info", "content": "已打开预填表单"}})
            command = bot_command_from_form(form, args.default_author_id, args.default_tid)
            run_command_background(args_for_chat(args, chat_id), command, "卡片操作")
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
                    print(f"NGA 监听循环失败: {exc}", file=sys.stderr)
                jitter = random.uniform(-args.jitter, args.jitter) if args.jitter > 0 else 0
                time.sleep(max(1, args.interval + jitter))

        threading.Thread(target=watch_loop, daemon=True).start()
        print("已启动 NGA 后台监听循环。")

    print("正在启动飞书 WebSocket 客户端。")
    lark.ws.Client(app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.ERROR).start()


def send_test_message(args: argparse.Namespace) -> None:
    post = NgaPost(
        key="test",
        subject="NGA 监听测试",
        content="这是一条来自 NGA Wolf Watcher 的测试消息。",
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
            "NGA 监听测试",
            args.timeout,
            args.message_format,
        )
    else:
        push_to_feishu(args, post)
    print("测试消息已发送。")


def push_deferred_summary(args: argparse.Namespace, posts: list[NgaPost]) -> None:
    if not posts:
        return
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")
    title = f"免打扰期间新回复汇总（{len(posts)} 条）"
    if app_id or app_secret or receive_id:
        if not (app_id and app_secret and receive_id):
            raise SystemExit("缺少 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID。")
        if args.message_format == "text":
            push_feishu_app_posts(app_id, app_secret, receive_id, receive_id_type, posts, title, args.timeout, "text")
        else:
            push_feishu_app_card(
                app_id,
                app_secret,
                receive_id,
                receive_id_type,
                feishu_deferred_summary_card(posts, len(posts)),
                args.timeout,
            )
        return
    if not webhook:
        raise SystemExit("缺少飞书发送目标。请设置应用凭证和 Receive ID，或设置 FEISHU_WEBHOOK。")
    summary = NgaPost(
        key="deferred-summary",
        subject=title,
        content=feishu_history_text(posts[:20], title),
        url=posts[0].url if posts else "https://bbs.nga.cn/",
        post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    )
    push_feishu(webhook, secret, summary, args.timeout)


def push_to_feishu(args: argparse.Namespace, post: NgaPost) -> None:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")

    if app_id or app_secret or receive_id:
        if not (app_id and app_secret and receive_id):
            raise SystemExit("缺少 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID。")
        push_feishu_app(app_id, app_secret, receive_id, receive_id_type, post, args.timeout, args.message_format)
        return

    if not webhook:
        raise SystemExit("缺少飞书发送目标。请设置应用凭证和 Receive ID，或设置 FEISHU_WEBHOOK。")
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
            print(f"{label} 失败（{attempt}/{attempts}）：{exc}；{sleep_for:.1f} 秒后重试", file=sys.stderr)
            time.sleep(sleep_for)
    raise RuntimeError(f"{label} 在 {attempts} 次尝试后仍失败：{last_exc}")


def collect_posts_with_retries(args: argparse.Namespace, count_pages: int | None = None) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")
    max_pages = count_pages if count_pages is not None else args.max_pages
    return with_retries(
        "NGA 监听抓取",
        args.retries,
        args.retry_delay,
        lambda: collect_posts(args.author_id, cookie, max_pages, args.timeout),
    )


def collect_replies_with_retries(args: argparse.Namespace, author_id: str, count: int) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")
    return with_retries(
        "NGA 用户回复抓取",
        args.retries,
        args.retry_delay,
        lambda: collect_recent_replies(author_id, count, cookie, args.timeout),
    )


def collect_thread_tail_with_retries(args: argparse.Namespace, tid: str, count: int) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")
    return with_retries(
        "NGA 帖子回复抓取",
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
                subject="命令处理失败",
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
                "NGA 历史查询失败",
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
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")

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
        print(f"已标记 {len(posts)} 条已抓取回复为已读。")
        return len(posts)

    new_posts = [post for post in posts if post.key not in seen]
    new_posts.reverse()

    quiet_now = is_quiet_time(args)
    quiet_policy = str(getattr(args, "quiet_policy", DEFAULT_QUIET_POLICY) or DEFAULT_QUIET_POLICY).strip().lower()
    if quiet_policy not in {"ignore", "defer"}:
        quiet_policy = DEFAULT_QUIET_POLICY

    quiet_posts = [post for post in new_posts if post_in_quiet_range(args, post)]
    deliver_posts = [post for post in new_posts if post not in quiet_posts]

    if quiet_posts:
        for post in quiet_posts:
            seen.add(post.key)
        if args.dry_run:
            print(f"[试运行] {len(quiet_posts)} 条新回复属于免打扰时段，不会立即推送。")
        elif quiet_policy == "defer":
            added = append_deferred_posts(state, quiet_posts)
            print(f"已暂存 {added} 条免打扰时段新回复。")
        else:
            print(f"已忽略 {len(quiet_posts)} 条免打扰时段新回复。")

    if not quiet_now:
        deferred_posts = deferred_posts_from_state(state)
        if deferred_posts and not args.dry_run:
            push_deferred_summary(args, deferred_posts)
            state.pop("deferred_posts", None)
            state.pop("deferred_started_at", None)
            state.pop("deferred_updated_at", None)
            state["seen"] = sorted(seen)
            state["updated_at"] = int(time.time())
            write_json(state_path, state)
            print(f"已推送免打扰期间新回复汇总：{len(deferred_posts)} 条。")
    elif deliver_posts:
        for post in deliver_posts:
            seen.add(post.key)
        if args.dry_run:
            print(f"[试运行] 当前处于免打扰时段，本轮 {len(deliver_posts)} 条新回复不会推送。")
        else:
            print(f"当前处于免打扰时段，已标记 {len(deliver_posts)} 条非免打扰区间旧回复为已读，不纳入汇总。")
        deliver_posts = []

    for post in new_posts:
        if post not in deliver_posts:
            continue
        if args.dry_run:
            print(f"[试运行] {post.subject} {post.url}\n{post.content[:500]}\n")
        else:
            push_to_feishu(args, post)
            seen.add(post.key)

    if not args.dry_run:
        state["seen"] = sorted(seen)
        state["updated_at"] = int(time.time())
        write_json(state_path, state)
    pushed_count = 0 if quiet_now else len(deliver_posts)
    print(f"已抓取 {len(posts)} 条回复，已推送 {pushed_count} 条新回复。")
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
    parser.add_argument("--mark-seen", action="store_true", help="把当前抓取到的回复记为已读，不推送。")
    parser.add_argument("--list-feishu-chats", action="store_true", help="列出飞书机器人可见的群组。")
    parser.add_argument("--send-test", action="store_true", help="发送一条飞书测试消息后退出。")
    parser.add_argument("--message-format", choices=["card", "text"], default=os.getenv("FEISHU_MESSAGE_FORMAT", "card"))
    parser.add_argument("--disable-commands", action="store_true", help="不轮询飞书群组普通消息命令。")
    parser.add_argument("--command-lookback", type=int, default=int(os.getenv("FEISHU_COMMAND_LOOKBACK", "600")))
    parser.add_argument("--retries", type=int, default=int(os.getenv("NGA_RETRIES", "10")))
    parser.add_argument("--retry-delay", type=float, default=float(os.getenv("NGA_RETRY_DELAY", "2")))
    parser.add_argument("--interval", type=int, default=int(os.getenv("NGA_INTERVAL", "60")))
    parser.add_argument("--jitter", type=int, default=int(os.getenv("NGA_JITTER", "20")))
    parser.add_argument("--quiet-hours-enabled", action="store_true", default=os.getenv("NGA_QUIET_HOURS_ENABLED", "").lower() in {"1", "true", "yes", "on"})
    parser.add_argument("--quiet-start-day", type=int, default=int(os.getenv("NGA_QUIET_START_DAY", str(DEFAULT_QUIET_START_DAY))))
    parser.add_argument("--quiet-end-day", type=int, default=int(os.getenv("NGA_QUIET_END_DAY", str(DEFAULT_QUIET_END_DAY))))
    parser.add_argument("--quiet-days", default=os.getenv("NGA_QUIET_DAYS", ",".join(str(day) for day in DEFAULT_QUIET_DAYS)))
    parser.add_argument("--quiet-start-time", default=os.getenv("NGA_QUIET_START_TIME", DEFAULT_QUIET_START_TIME))
    parser.add_argument("--quiet-end-time", default=os.getenv("NGA_QUIET_END_TIME", DEFAULT_QUIET_END_TIME))
    parser.add_argument("--quiet-policy", choices=["ignore", "defer"], default=os.getenv("NGA_QUIET_POLICY", DEFAULT_QUIET_POLICY))
    parser.add_argument("--once", action="store_true", help="只执行一次轮询后退出。")
    parser.add_argument("--ws", action="store_true", help="使用飞书 WebSocket 接收消息和卡片操作。")
    parser.add_argument("--ws-no-watch", action="store_true", help="在 WebSocket 模式下不启动 NGA 后台监听循环。")
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
            raise SystemExit("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET。")
        chats = list_feishu_chats(app_id, app_secret, args.timeout)
        for chat in chats:
            print(
                f"{chat.get('chat_id', '')}\t"
                f"{chat.get('name', '')}\t"
                f"{chat.get('chat_type', '')}"
            )
        print(f"已列出 {len(chats)} 个群组。")
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
                print(f"飞书命令轮询失败: {exc}", file=sys.stderr)
            run_once(args)
        except Exception as exc:
            print(f"错误: {exc}", file=sys.stderr)
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        jitter = random.uniform(-args.jitter, args.jitter) if args.jitter > 0 else 0
        sleep_for = max(1, args.interval + jitter)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
