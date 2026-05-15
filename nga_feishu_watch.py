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
import queue
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
from typing import Any, Callable

import ai_analysis


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
DEFAULT_NGA_PAGE_DELAY = 2.0
DEFAULT_NGA_UNAVAILABLE_RETRIES = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
QUOTE_END_MARKER = "__NGA_QUOTE_END__"
_AI_MANAGERS: dict[tuple[str, str], ai_analysis.AIManager] = {}
_AI_FEISHU_QUEUES: dict[tuple[str, str], "queue.Queue[Callable[[], None]]"] = {}
_AI_FEISHU_QUEUE_LOCK = threading.Lock()
_WATCHER_STATE_LOCK = threading.Lock()


class NgaTemporaryUnavailable(RuntimeError):
    pass


def is_nga_temporary_unavailable(exc: Exception) -> bool:
    text = str(exc)
    return isinstance(exc, NgaTemporaryUnavailable) or any(
        marker in text for marker in ("状态码=429", "状态码=500", "状态码=502", "状态码=503", "状态码=504")
    )


@dataclass(frozen=True)
class FeishuFileRef:
    file_key: str
    file_name: str = ""
    resource_type: str = "file"
    source_message_id: str = ""


@dataclass(frozen=True)
class FeishuImageRef:
    image_key: str
    source_message_id: str = ""


@dataclass(frozen=True)
class FeishuReplyContext:
    text: str = ""
    image_refs: tuple[FeishuImageRef, ...] = ()
    file_refs: tuple[FeishuFileRef, ...] = ()


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
    image_urls: tuple[str, ...] = ()


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


def write_watcher_state(path: Path, state: dict[str, Any]) -> None:
    with _WATCHER_STATE_LOCK:
        current = read_json(path, {})
        if isinstance(current, dict):
            current_mention_at = int(current.get("mention_updated_at") or 0)
            state_mention_at = int(state.get("mention_updated_at") or 0)
            if current_mention_at > state_mention_at or (
                current_mention_at and not any(key in state for key in ("mention_enabled", "mention_user_id", "mention_updated_at"))
            ):
                for key in ("mention_enabled", "mention_user_id", "mention_updated_at"):
                    if key in current:
                        state[key] = current[key]
        write_json(path, state)


def effective_mention_enabled(args: argparse.Namespace, state: dict[str, Any]) -> bool:
    if "mention_enabled" in state:
        return ai_analysis.bool_value(state.get("mention_enabled"))
    return ai_analysis.bool_value(getattr(args, "feishu_mention_enabled", False))


def effective_mention_user_id(args: argparse.Namespace, state: dict[str, Any]) -> str:
    return str(state.get("mention_user_id") or getattr(args, "feishu_mention_user_id", "") or "").strip()


def feishu_mention_user_id(args: argparse.Namespace, state: dict[str, Any]) -> str:
    user_id = effective_mention_user_id(args, state)
    if effective_mention_enabled(args, state) and user_id:
        return user_id
    return ""


def feishu_mention_md(user_id: str) -> str:
    safe_user_id = str(user_id or "").strip()
    return f"<at id={safe_user_id}></at>" if safe_user_id else ""


def mention_card_elements(user_id: str) -> list[dict[str, Any]]:
    mention = feishu_mention_md(user_id)
    if not mention:
        return []
    return [
        {
            "tag": "div",
            "text": {"tag": "lark_md", "content": mention},
        },
        {"tag": "hr"},
    ]


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
        error_cls = NgaTemporaryUnavailable if status in {429, 500, 502, 503, 504} else RuntimeError
        raise error_cls(
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
    value = re.sub(r"<img[^>]*>", "", value, flags=re.I)
    value = re.sub(r"\[img[^\]]*\].*?\[/img\]", "", value, flags=re.I | re.S)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\[quote[^\]]*\]", "", value, flags=re.I)
    value = re.sub(r"\[/quote\]", f"\n\n{QUOTE_END_MARKER}\n\n", value, flags=re.I)
    value = re.sub(r"\[/?(?:collapse|color|size|b|i|u|url|img|align)[^\]]*\]", "", value, flags=re.I)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


IMAGE_EXT_RE = r"(?:jpg|jpeg|png|gif|webp|bmp)"


def normalize_nga_image_url(value: str) -> str:
    url = html.unescape(str(value or "")).strip().strip("'\"")
    url = re.sub(r"^\[img[^\]]*\]", "", url, flags=re.I)
    url = re.sub(r"\[/img\]$", "", url, flags=re.I).strip().strip("'\"")
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if url.startswith("./"):
        url = url[2:]
    if url.startswith("/attachments/"):
        return "https://img.nga.178.com" + url
    if url.startswith("attachments/"):
        return "https://img.nga.178.com/" + url
    if url.startswith("mon_"):
        return "https://img.nga.178.com/attachments/" + url
    return url


def extract_image_urls(raw_content: str, item: dict[str, Any] | None = None) -> tuple[str, ...]:
    candidates: list[str] = []
    values = [raw_content or ""]
    if item:
        for name in ("attachments", "attachs", "attach", "images", "image", "img"):
            raw = item.get(name)
            if isinstance(raw, str):
                values.append(raw)
            elif isinstance(raw, dict):
                values.extend(str(v) for v in raw.values() if isinstance(v, (str, int, float)))
            elif isinstance(raw, list):
                values.extend(str(v) for v in raw if isinstance(v, (str, int, float, dict)))

    for value in values:
        text = str(value)
        candidates.extend(re.findall(r"<img[^>]+src=[\"']([^\"']+)", text, flags=re.I))
        candidates.extend(re.findall(r"\[img[^\]]*\](.*?)\[/img\]", text, flags=re.I | re.S))
        candidates.extend(re.findall(r"https?://[^\s\]\"']+\." + IMAGE_EXT_RE + r"(?:\?[^\s\]\"']*)?", text, flags=re.I))
        candidates.extend(re.findall(r"//[^\s\]\"']+\." + IMAGE_EXT_RE + r"(?:\?[^\s\]\"']*)?", text, flags=re.I))
        candidates.extend(re.findall(r"(?:\./)?(?:attachments/)?mon_[^\s\]\"']+\." + IMAGE_EXT_RE + r"(?:\?[^\s\]\"']*)?", text, flags=re.I))

    seen: set[str] = set()
    urls: list[str] = []
    for candidate in candidates:
        url = normalize_nga_image_url(candidate)
        if url and url not in seen:
            seen.add(url)
            urls.append(url)
    return tuple(urls)


def make_post(item: dict[str, Any], fallback_subject: str = "") -> NgaPost | None:
    raw_content = first_str(item, "content", "postcontent", "post_content", "message")
    if not raw_content:
        return None

    image_urls = extract_image_urls(raw_content, item)
    content = strip_markup(raw_content)
    if not content:
        if not image_urls:
            return None
        content = "[image reply]"

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
        image_urls=image_urls,
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
    if post.image_urls:
        lines.extend(["", "Images:", *[f"- {url}" for url in post.image_urls]])
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
        if post.image_urls:
            lines.append("Images: " + ", ".join(post.image_urls[:5]))
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
        if post.image_urls:
            meta.extend(f"image: {url}" for url in post.image_urls)
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

    if post.image_urls:
        image_lines = "\n".join(f"[image {idx}]({lark_md_escape(url)})" for idx, url in enumerate(post.image_urls[:6], 1))
        elements.append(
            {
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**Images**\n{image_lines}"},
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


def feishu_posts_card(posts: list[NgaPost], title: str, mention_user_id: str = "") -> dict[str, Any]:
    elements: list[dict[str, Any]] = mention_card_elements(mention_user_id)
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


def split_text_chunks(text: str, limit: int) -> list[str]:
    text = str(text or "")
    if not text:
        return [""]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n## ", 0, limit)
        if split_at < max(300, limit // 3):
            split_at = remaining.rfind("\n", 0, limit)
        if split_at < max(200, limit // 4):
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks or [""]


def ai_result_title(task_type: str) -> str:
    if task_type == "new_post_analysis":
        return "AI 新帖分析"
    if task_type == "scheduled_analysis":
        return "AI 定时分析"
    if task_type == "manual_ask":
        return "AI 回复"
    return "AI 分析"


def feishu_ai_markdown_card(title: str, markdown: str, part: int = 1, total: int = 1, *, is_error: bool = False) -> dict[str, Any]:
    suffix = f" ({part}/{total})" if total > 1 else ""
    content = (str(markdown or "").strip() or "(empty)").replace("<", "&lt;")
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "red" if is_error else "blue",
            "title": {"tag": "plain_text", "content": (title + suffix)[:60]},
        },
        "elements": [
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": content,
                },
            }
        ],
    }


def feishu_deferred_summary_card(posts: list[NgaPost], total_count: int, mention_user_id: str = "") -> dict[str, Any]:
    shown = posts[:20]
    elements: list[dict[str, Any]] = mention_card_elements(mention_user_id) + [
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


def serialize_post(post: NgaPost) -> dict[str, Any]:
    data = asdict(post)
    data["image_urls"] = list(post.image_urls or ())
    return data


def deserialize_post(value: Any) -> NgaPost | None:
    if not isinstance(value, dict):
        return None
    raw_images = value.get("image_urls") or ()
    if isinstance(raw_images, str):
        image_urls = tuple(url.strip() for url in raw_images.splitlines() if url.strip())
    elif isinstance(raw_images, (list, tuple)):
        image_urls = tuple(str(url) for url in raw_images if str(url).strip())
    else:
        image_urls = ()
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
            image_urls=image_urls,
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
    mention_user_id: str = "",
) -> None:
    if message_format == "text":
        msg_type = "text"
        content = json.dumps({"text": feishu_message_text(post)}, ensure_ascii=False)
    else:
        msg_type = "interactive"
        content = json.dumps(feishu_posts_card([post], "NGA new reply", mention_user_id), ensure_ascii=False)
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


def push_feishu_text(args: argparse.Namespace, title: str, text: str) -> None:
    post = NgaPost(
        key=f"ai-{int(time.time())}",
        subject=title,
        content=text,
        url="https://bbs.nga.cn/",
        post_time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
    )
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    if app_id and app_secret and receive_id:
        push_feishu_app_posts(app_id, app_secret, receive_id, receive_id_type, [post], title, args.timeout, "text")
        return
    push_to_feishu(args, post)


def push_feishu_raw_text(args: argparse.Namespace, text: str) -> None:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")
    if app_id and app_secret and receive_id:
        result = feishu_app_request(
            app_id,
            app_secret,
            f"/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
            timeout=args.timeout,
            method="POST",
            body={"receive_id": receive_id, "msg_type": "text", "content": json.dumps({"text": text}, ensure_ascii=False)},
        )
        if result.get("code") != 0:
            raise RuntimeError(f"飞书应用文本消息发送失败：{result}")
        return
    if not webhook:
        raise SystemExit("缺少飞书发送目标。请设置应用凭证和 Receive ID，或设置 FEISHU_WEBHOOK。")
    body: dict[str, Any] = {"msg_type": "text", "content": {"text": text}}
    if secret:
        timestamp = str(int(time.time()))
        body["timestamp"] = timestamp
        body["sign"] = feishu_sign(secret, timestamp)
    result = http_json(webhook, method="POST", body=body, timeout=args.timeout)
    if result.get("code") not in (None, 0):
        raise RuntimeError(f"飞书 Webhook 文本发送失败：{result}")


def push_feishu_raw_card(args: argparse.Namespace, card: dict[str, Any]) -> None:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")
    if app_id and app_secret and receive_id:
        result = feishu_app_request(
            app_id,
            app_secret,
            f"/im/v1/messages?receive_id_type={urllib.parse.quote(receive_id_type)}",
            timeout=args.timeout,
            method="POST",
            body={"receive_id": receive_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
        )
        if result.get("code") != 0:
            raise RuntimeError(f"Feishu app card message failed: {result}")
        return
    if not webhook:
        raise SystemExit("Missing Feishu target. Set app credentials and Receive ID, or FEISHU_WEBHOOK.")
    body: dict[str, Any] = {"msg_type": "interactive", "card": card}
    if secret:
        timestamp = str(int(time.time()))
        body["timestamp"] = timestamp
        body["sign"] = feishu_sign(secret, timestamp)
    result = http_json(webhook, method="POST", body=body, timeout=args.timeout)
    if result.get("code") not in (None, 0):
        raise RuntimeError(f"Feishu webhook card message failed: {result}")


def create_feishu_reaction(args: argparse.Namespace, message_id: str, emoji_type: str = "WITTY") -> str:
    if not message_id:
        return ""
    app_id, app_secret, _receive_id, _receive_id_type = feishu_credentials(args)
    if not (app_id and app_secret):
        return ""
    token = get_feishu_tenant_access_token(app_id, app_secret, args.timeout)
    result = http_json(
        f"{FEISHU_API}/im/v1/messages/{urllib.parse.quote(message_id, safe='')}/reactions",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
        body={"reaction_type": {"emoji_type": emoji_type}},
        timeout=args.timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu reaction create failed: {result}")
    data = result.get("data", {})
    reaction = data.get("reaction", {}) if isinstance(data, dict) else {}
    if not isinstance(reaction, dict):
        reaction = {}
    return str(data.get("reaction_id") or reaction.get("reaction_id") or "")


def delete_feishu_reaction(args: argparse.Namespace, message_id: str, reaction_id: str) -> None:
    if not message_id or not reaction_id:
        return
    app_id, app_secret, _receive_id, _receive_id_type = feishu_credentials(args)
    if not (app_id and app_secret):
        return
    token = get_feishu_tenant_access_token(app_id, app_secret, args.timeout)
    result = http_json(
        f"{FEISHU_API}/im/v1/messages/{urllib.parse.quote(message_id, safe='')}/reactions/{urllib.parse.quote(reaction_id, safe='')}",
        method="DELETE",
        headers={"Authorization": f"Bearer {token}"},
        timeout=args.timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu reaction delete failed: {result}")


def get_feishu_message(args: argparse.Namespace, message_id: str) -> dict[str, Any]:
    app_id, app_secret, _receive_id, _receive_id_type = feishu_credentials(args)
    if not (message_id and app_id and app_secret):
        return {}
    result = feishu_app_request(
        app_id,
        app_secret,
        f"/im/v1/messages/{urllib.parse.quote(message_id, safe='')}",
        timeout=args.timeout,
    )
    if result.get("code") != 0:
        raise RuntimeError(f"飞书消息读取失败：{result}")
    data = result.get("data", {})
    if isinstance(data, dict):
        if isinstance(data.get("item"), dict):
            return data["item"]
        if isinstance(data.get("message"), dict):
            return data["message"]
        items = data.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        if "body" in data or "content" in data:
            return data
    return {}


def with_file_source(file_refs: Iterable[FeishuFileRef], message_id: str) -> list[FeishuFileRef]:
    result: list[FeishuFileRef] = []
    for ref in file_refs:
        result.append(
            FeishuFileRef(
                file_key=ref.file_key,
                file_name=ref.file_name,
                resource_type=ref.resource_type,
                source_message_id=ref.source_message_id or message_id,
            )
        )
    return result


def with_image_source(image_keys: Iterable[str], message_id: str) -> list[FeishuImageRef]:
    return [
        FeishuImageRef(image_key=str(key or "").strip(), source_message_id=message_id)
        for key in image_keys
        if str(key or "").strip()
    ]


def card_summary_text(message: dict[str, Any]) -> str:
    if str(message.get("msg_type") or message.get("message_type") or "").lower() != "interactive":
        return ""
    body = message.get("body", {})
    raw = body.get("content") if isinstance(body, dict) else message.get("content", "")
    value = parse_feishu_content(raw)
    lines: list[str] = []
    header = value.get("header") if isinstance(value.get("header"), dict) else {}
    title = header.get("title") if isinstance(header.get("title"), dict) else {}
    title_text = str(title.get("content") or title.get("text") or "").strip()
    if title_text:
        lines.append(title_text)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            tag = str(node.get("tag") or "").lower()
            if tag in {"plain_text", "lark_md", "markdown"}:
                content = str(node.get("content") or node.get("text") or "").strip()
                if content:
                    lines.append(content)
            elif isinstance(node.get("text"), str):
                content = str(node.get("text") or "").strip()
                if content:
                    lines.append(content)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(value.get("elements"))
    walk(value.get("body"))
    return "\n".join(list(dict.fromkeys(strip_feishu_mentions(line) for line in lines if strip_feishu_mentions(line)))[:20])


def enrich_reply_context(
    args: argparse.Namespace,
    current_message_id: str,
    image_keys: list[str],
    file_refs: list[FeishuFileRef],
    parent_id: str = "",
    root_id: str = "",
) -> tuple[FeishuReplyContext, list[FeishuImageRef], list[FeishuFileRef]]:
    image_refs = with_image_source(image_keys, current_message_id)
    refs = with_file_source(file_refs, current_message_id)
    seen_images = {(ref.source_message_id, ref.image_key) for ref in image_refs}
    seen_files = {(ref.source_message_id, ref.file_key) for ref in refs}
    reply_texts: list[str] = []
    for related_id in dict.fromkeys([parent_id, root_id]):
        related_id = str(related_id or "").strip()
        if not related_id or related_id == current_message_id:
            continue
        try:
            related = get_feishu_message(args, related_id)
            related_text, related_images, related_files = message_parts(related)
            if not related_text:
                related_text = card_summary_text(related)
            if related_text:
                reply_texts.append(f"[引用消息 {related_id}]\n{related_text}")
            for ref in with_image_source(related_images, related_id):
                marker = (ref.source_message_id, ref.image_key)
                if marker not in seen_images:
                    image_refs.append(ref)
                    seen_images.add(marker)
            for ref in with_file_source(related_files, related_id):
                marker = (ref.source_message_id, ref.file_key)
                if marker not in seen_files:
                    refs.append(ref)
                    seen_files.add(marker)
        except Exception as exc:
            print(f"读取飞书回复上下文失败 {related_id}: {exc}", file=sys.stderr)
    return FeishuReplyContext(text="\n\n".join(reply_texts), image_refs=tuple(image_refs), file_refs=tuple(refs)), image_refs, refs


def enrich_reply_file_refs(args: argparse.Namespace, current_message_id: str, file_refs: list[FeishuFileRef], parent_id: str = "", root_id: str = "") -> list[FeishuFileRef]:
    refs = with_file_source(file_refs, current_message_id)
    seen = {(ref.source_message_id, ref.file_key) for ref in refs}
    for related_id in dict.fromkeys([parent_id, root_id]):
        related_id = str(related_id or "").strip()
        if not related_id or related_id == current_message_id:
            continue
        try:
            related = get_feishu_message(args, related_id)
            _text, _images, related_files = message_parts(related)
            for ref in with_file_source(related_files, related_id):
                marker = (ref.source_message_id, ref.file_key)
                if marker not in seen:
                    refs.append(ref)
                    seen.add(marker)
        except Exception as exc:
            print(f"读取飞书回复关联文件失败 {related_id}: {exc}", file=sys.stderr)
    return refs


def with_ai_reply_status(args: argparse.Namespace, message_id: str, label: str, fn: Callable[[], None]) -> None:
    reaction_id = ""
    emoji_type = os.getenv("AI_REPLY_STATUS_EMOJI", "WITTY").strip().upper() or "WITTY"
    try:
        app_id, app_secret, _receive_id, _receive_id_type = feishu_credentials(args)
        if message_id and app_id and app_secret:
            try:
                reaction_id = create_feishu_reaction(args, message_id, emoji_type)
            except Exception as exc:
                print(f"AI 回复状态添加失败 {label}: {exc}", file=sys.stderr)
        fn()
    finally:
        if reaction_id:
            try:
                delete_feishu_reaction(args, message_id, reaction_id)
            except Exception as exc:
                print(f"AI 回复状态清理失败 {label}: {exc}", file=sys.stderr)


def download_feishu_message_resource(args: argparse.Namespace, message_id: str, file_key: str, resource_type: str = "image") -> tuple[bytes, str]:
    app_id, app_secret, _receive_id, _receive_id_type = feishu_credentials(args)
    if not (app_id and app_secret):
        raise RuntimeError("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET，无法下载飞书图片。")
    token = get_feishu_tenant_access_token(app_id, app_secret, args.timeout)
    query = urllib.parse.urlencode({"type": resource_type})
    url = (
        f"{FEISHU_API}/im/v1/messages/{urllib.parse.quote(message_id, safe='')}"
        f"/resources/{urllib.parse.quote(file_key, safe='')}?{query}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as resp:
            data = resp.read()
            content_type = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
            return data, content_type
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"飞书资源下载失败 HTTP {exc.code}: {detail}") from exc


def image_extension(data: bytes, content_type: str = "") -> str:
    if content_type == "image/jpeg" or data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if content_type == "image/gif" or data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return ".gif"
    if content_type == "image/webp" or (len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        return ".webp"
    if content_type == "image/bmp" or data.startswith(b"BM"):
        return ".bmp"
    if content_type == "image/png" or data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    return ".png"


def safe_attachment_name(raw_name: str, fallback_stem: str) -> str:
    name = Path(str(raw_name or "")).name.strip()
    if not name or name in {".", ".."}:
        return ai_analysis.safe_key(fallback_stem)
    stem = ai_analysis.safe_key(Path(name).stem) or ai_analysis.safe_key(fallback_stem)
    suffix = Path(name).suffix
    if not re.fullmatch(r"\.[A-Za-z0-9]{1,12}", suffix or ""):
        suffix = ""
    return stem + suffix


def prepare_ai_message_for_agent(
    args: argparse.Namespace,
    text: str,
    message_id: str = "",
    image_keys: Iterable[str | FeishuImageRef] | None = None,
    file_refs: Iterable[FeishuFileRef] | None = None,
    reply_context: FeishuReplyContext | None = None,
) -> tuple[str, list[Path], list[Path]]:
    prompt = str(text or "").strip()
    image_refs: list[FeishuImageRef] = []
    seen_image_refs: set[tuple[str, str]] = set()
    for item in image_keys or []:
        if isinstance(item, FeishuImageRef):
            ref = item
        else:
            ref = FeishuImageRef(image_key=str(item or "").strip(), source_message_id=message_id)
        if not ref.image_key:
            continue
        marker = (ref.source_message_id or message_id, ref.image_key)
        if marker not in seen_image_refs:
            image_refs.append(ref)
            seen_image_refs.add(marker)
    files = list(file_refs or [])
    quoted_text = (reply_context.text if reply_context else "").strip()
    if quoted_text:
        prompt = (prompt + "\n\n" if prompt else "") + "[被回复/引用的飞书消息]\n" + quoted_text
    if not image_refs and not files:
        return prompt, [], []

    manager = ai_manager_for_args(args)
    manager.ensure_ready()
    timestamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    attachment_dir = manager.config.work_dir / "attachments" / timestamp
    attachment_dir.mkdir(parents=True, exist_ok=True)

    image_paths: list[Path] = []
    file_paths: list[Path] = []
    failures: list[str] = []
    for index, image_ref in enumerate(image_refs, start=1):
        try:
            source_message_id = image_ref.source_message_id or message_id
            data, content_type = download_feishu_message_resource(args, source_message_id, image_ref.image_key, "image")
            ext = image_extension(data, content_type)
            file_name = f"feishu_image_{index}_{ai_analysis.safe_key(image_ref.image_key)}{ext}"
            path = attachment_dir / file_name
            path.write_bytes(data)
            image_paths.append(path.resolve())
        except Exception as exc:
            failures.append(f"- {image_ref.image_key}: {exc}")

    for index, file_ref in enumerate(files, start=1):
        if not file_ref.file_key:
            continue
        try:
            source_message_id = file_ref.source_message_id or message_id
            data, _content_type = download_feishu_message_resource(args, source_message_id, file_ref.file_key, file_ref.resource_type or "file")
            file_name = safe_attachment_name(file_ref.file_name, f"feishu_file_{index}_{file_ref.file_key}")
            path = attachment_dir / file_name
            path.write_bytes(data)
            file_paths.append(path.resolve())
        except Exception as exc:
            failures.append(f"- {file_ref.file_name or file_ref.file_key}: {exc}")

    if image_paths or file_paths:
        if not prompt:
            prompt = "请分析我发送的附件。"
    if image_paths:
        image_lines = "\n".join(f"- {path}" for path in image_paths)
        prompt += "\n\n[飞书图片附件已下载到本机，必要时请直接读取这些图片文件]\n" + image_lines
    if file_paths:
        file_lines = "\n".join(f"- {path}" for path in file_paths)
        prompt += "\n\n[飞书文件附件已下载到本机，必要时请直接读取这些文件]\n" + file_lines
    elif files and not prompt:
        prompt = "我发送了文件，但程序未能下载文件附件，无法直接读取。"
    if failures:
        prompt += "\n\n[附件下载失败]\n" + "\n".join(failures)
    return prompt, image_paths, file_paths


def push_ai_markdown(args: argparse.Namespace, title: str, markdown: str, *, is_error: bool = False) -> None:
    chunks = split_text_chunks(markdown, 2800)
    total = len(chunks)
    try:
        for index, chunk in enumerate(chunks, start=1):
            push_feishu_raw_card(args, feishu_ai_markdown_card(title, chunk, index, total, is_error=is_error))
            if index < total:
                time.sleep(0.25)
    except Exception as exc:
        print(f"AI card send failed, falling back to text chunks: {exc}", file=sys.stderr)
        fallback_chunks = split_text_chunks(markdown, max(1000, getattr(args, "ai_max_feishu_chars", 3500)))
        for index, chunk in enumerate(fallback_chunks, start=1):
            prefix = f"{title} ({index}/{len(fallback_chunks)})\n\n" if len(fallback_chunks) > 1 else ""
            push_feishu_raw_text(args, prefix + chunk)
            if index < len(fallback_chunks):
                time.sleep(0.25)


def push_ai_result(args: argparse.Namespace, result: ai_analysis.AIResult) -> None:
    if result.ok:
        push_ai_markdown(args, ai_result_title(result.task_type), result.text)
        return
    push_ai_markdown(args, "AI 任务失败", f"AI task failed: {result.error}", is_error=True)


def ai_manager_for_args(args: argparse.Namespace) -> ai_analysis.AIManager:
    config = ai_analysis.AIConfig.from_namespace(args)
    key = (str(config.work_dir.resolve()), getattr(args, "feishu_receive_id", "") or "")
    manager = _AI_MANAGERS.get(key)
    if manager is not None:
        manager.config = config
        return manager

    def send_text(text: str) -> None:
        push_feishu_text(args, "AI analysis", text)

    def send_file(file_name: str, text: str) -> None:
        push_feishu_file(args, file_name, text)

    def send_result(result: ai_analysis.AIResult) -> None:
        push_ai_result(args, result)

    manager = ai_analysis.AIManager(config, send_text=send_text, send_file=send_file, send_result=send_result)
    _AI_MANAGERS[key] = manager
    return manager


def sender_id_from_message(message: dict[str, Any]) -> str:
    sender = message.get("sender", {})
    sender_id = sender.get("sender_id", {}) if isinstance(sender, dict) else {}
    if isinstance(sender_id, dict):
        for key in ("open_id", "user_id", "union_id"):
            value = str(sender_id.get(key) or "").strip()
            if value:
                return value
    return ""


def is_feishu_bot_message(message: dict[str, Any]) -> bool:
    sender = message.get("sender", {})
    sender_type = str(sender.get("sender_type") or "").lower() if isinstance(sender, dict) else ""
    return sender_type in {"app", "bot"}


def value_get(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def identity_id(value: Any) -> str:
    if value is None:
        return ""
    for key in ("open_id", "user_id", "union_id"):
        found = value_get(value, key)
        if isinstance(found, (str, int)) and str(found).strip():
            return str(found).strip()
    for nested_key in ("sender_id", "operator_id", "user", "user_id"):
        nested = value_get(value, nested_key)
        if nested is value:
            continue
        found = identity_id(nested)
        if found:
            return found
    return ""


def object_sender_id(value: Any) -> str:
    for owner_name in ("sender", "operator"):
        found = identity_id(value_get(value, owner_name))
        if found:
            return found
    return identity_id(value)
    return ""


def should_forward_plain_text_to_ai(
    args: argparse.Namespace,
    text: str,
    sender_id: str = "",
    image_keys: Iterable[str] | None = None,
    file_refs: Iterable[FeishuFileRef] | None = None,
) -> bool:
    has_image = any(str(item or "").strip() for item in (image_keys or []))
    has_file = any(bool(item.file_key) for item in (file_refs or []))
    if not text.strip() and not has_image and not has_file:
        return False
    manager = ai_manager_for_args(args)
    return manager.effective_enabled() and manager.is_authorized(sender_id)


def ai_feishu_queue_for_args(args: argparse.Namespace) -> "queue.Queue[Callable[[], None]]":
    config = ai_analysis.AIConfig.from_namespace(args)
    key = (str(config.work_dir.resolve()), getattr(args, "feishu_receive_id", "") or "")
    with _AI_FEISHU_QUEUE_LOCK:
        existing = _AI_FEISHU_QUEUES.get(key)
        if existing is not None:
            return existing
        task_queue: "queue.Queue[Callable[[], None]]" = queue.Queue(maxsize=32)
        _AI_FEISHU_QUEUES[key] = task_queue

        def worker() -> None:
            while True:
                job = task_queue.get()
                try:
                    job()
                except Exception as exc:
                    print(f"AI 飞书队列任务失败: {exc}", file=sys.stderr)
                finally:
                    task_queue.task_done()

        threading.Thread(target=worker, daemon=True).start()
        return task_queue


def enqueue_ai_feishu_job(args: argparse.Namespace, label: str, job: Callable[[], None]) -> bool:
    task_queue = ai_feishu_queue_for_args(args)
    try:
        task_queue.put_nowait(job)
        queued_ahead = task_queue.qsize() - 1
        if queued_ahead > 0:
            print(f"AI 飞书任务已排队 {label}: 前面还有 {queued_ahead} 个任务")
        return True
    except queue.Full:
        print(f"AI 飞书任务队列已满 {label}", file=sys.stderr)
        try:
            if ai_analysis.AIConfig.from_namespace(args).send_errors_to_feishu:
                push_feishu_text(args, "AI queue full", "AI task queue is full, please retry later.")
        except Exception as exc:
            print(f"发送 AI 队列已满提示失败: {exc}", file=sys.stderr)
        return False


def run_ai_command(
    args: argparse.Namespace,
    text: str,
    sender_id: str = "",
    image_paths: list[Path] | None = None,
    file_paths: list[Path] | None = None,
) -> None:
    manager = ai_manager_for_args(args)
    parsed = ai_analysis.parse_ai_command(text)
    if parsed and parsed[0] == "mode" and not parsed[1].strip():
        try:
            push_feishu_card(args, ai_mode_card(manager))
        except Exception as exc:
            print(f"AI mode card send failed, falling back to text: {exc}", file=sys.stderr)
            push_feishu_raw_text(args, ai_mode_text(manager))
        return
    response = manager.handle_command(text, sender_id, image_paths=image_paths, file_paths=file_paths)
    if response:
        if parsed and parsed[0] in {"ask", "latest", "last"}:
            push_ai_markdown(args, "AI 回复" if parsed[0] == "ask" else "AI 新帖分析", response)
            return
        config = manager.config
        if len(response) > config.max_feishu_chars:
            summary = response[: config.max_feishu_chars] + "\n\n[truncated]"
            if config.upload_long_result:
                try:
                    push_feishu_raw_text(args, summary + "\n\nFull result uploaded as `ai_command_result.md`.")
                    push_feishu_file(args, "ai_command_result.md", response)
                except Exception as exc:
                    print(f"AI 长结果上传失败，改为截断发送: {exc}", file=sys.stderr)
                    push_feishu_raw_text(args, summary)
                return
            response = summary
        push_feishu_raw_text(args, response)


def run_ai_plain_text(
    args: argparse.Namespace,
    text: str,
    sender_id: str = "",
    image_paths: list[Path] | None = None,
    file_paths: list[Path] | None = None,
) -> None:
    manager = ai_manager_for_args(args)
    if not manager.effective_enabled():
        return
    if not manager.is_authorized(sender_id):
        return
    task = manager.make_task("manual_ask", text.strip(), "chat", image_paths=image_paths, file_paths=file_paths)
    result = manager.run_task(task)
    push_ai_result(args, result)


def run_ai_command_background(
    args: argparse.Namespace,
    text: str,
    sender_id: str,
    label: str,
    message_id: str = "",
    image_keys: Iterable[str | FeishuImageRef] | None = None,
    file_refs: Iterable[FeishuFileRef] | None = None,
    reply_context: FeishuReplyContext | None = None,
) -> None:
    def queued_job() -> None:
        try:
            print(f"开始处理 {label}: /ai")
            def job() -> None:
                parsed = ai_analysis.parse_ai_command(text)
                if parsed and parsed[0] == "ask":
                    prompt, image_paths, file_paths = prepare_ai_message_for_agent(args, text, message_id, image_keys, file_refs, reply_context)
                else:
                    prompt, image_paths, file_paths = text, [], []
                run_ai_command(args, prompt, sender_id, image_paths, file_paths)

            with_ai_reply_status(args, message_id, label, job)
            print(f"处理完成 {label}: /ai")
        except Exception as exc:
            print(f"AI 命令处理失败 {label}: {exc}", file=sys.stderr)
            try:
                if ai_analysis.AIConfig.from_namespace(args).send_errors_to_feishu:
                    push_feishu_text(args, "AI command failed", str(exc))
            except Exception as nested:
                print(f"发送 AI 错误消息失败: {nested}", file=sys.stderr)

    enqueue_ai_feishu_job(args, label, queued_job)


def run_ai_plain_text_background(
    args: argparse.Namespace,
    text: str,
    sender_id: str,
    label: str,
    message_id: str = "",
    image_keys: Iterable[str | FeishuImageRef] | None = None,
    file_refs: Iterable[FeishuFileRef] | None = None,
    reply_context: FeishuReplyContext | None = None,
) -> None:
    def queued_job() -> None:
        try:
            print(f"开始处理 {label}: AI conversation")
            def job() -> None:
                prompt, image_paths, file_paths = prepare_ai_message_for_agent(args, text, message_id, image_keys, file_refs, reply_context)
                run_ai_plain_text(args, prompt, sender_id, image_paths, file_paths)

            with_ai_reply_status(args, message_id, label, job)
            print(f"处理完成 {label}: AI conversation")
        except Exception as exc:
            print(f"AI 对话处理失败 {label}: {exc}", file=sys.stderr)
            try:
                if ai_analysis.AIConfig.from_namespace(args).send_errors_to_feishu:
                    push_feishu_text(args, "AI conversation failed", str(exc))
            except Exception as nested:
                print(f"发送 AI 错误消息失败: {nested}", file=sys.stderr)

    enqueue_ai_feishu_job(args, label, queued_job)


def after_posts_pushed_for_ai(args: argparse.Namespace, posts: list[NgaPost]) -> None:
    try:
        ai_manager_for_args(args).maybe_auto_analyze_posts(posts)
    except Exception as exc:
        print(f"AI 新帖保存/分析失败: {exc}", file=sys.stderr)


def maybe_run_ai_schedule(args: argparse.Namespace) -> None:
    try:
        ai_manager_for_args(args).maybe_scheduled_analysis()
    except Exception as exc:
        print(f"AI 定时分析检查失败: {exc}", file=sys.stderr)


def push_feishu_app_posts(
    app_id: str,
    app_secret: str,
    receive_id: str,
    receive_id_type: str,
    posts: list[NgaPost],
    title: str,
    timeout: int,
    message_format: str = "card",
    mention_user_id: str = "",
) -> None:
    if message_format == "text":
        msg_type = "text"
        content = json.dumps({"text": feishu_history_text(posts, title)}, ensure_ascii=False)
    else:
        msg_type = "interactive"
        content = json.dumps(feishu_posts_card(posts, title, mention_user_id), ensure_ascii=False)
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
    text, _image_keys, _file_refs = message_parts(message)
    return text


def strip_feishu_mentions(text: str) -> str:
    text = re.sub(r"<at[^>]*>.*?</at>", "", str(text or ""), flags=re.I)
    return html.unescape(text).strip()


def parse_feishu_content(content: Any) -> dict[str, Any]:
    if isinstance(content, dict):
        return content
    try:
        parsed = json.loads(content or "{}")
    except json.JSONDecodeError:
        return {"text": str(content or "")}
    return parsed if isinstance(parsed, dict) else {"text": str(parsed or "")}


def post_text_and_image_keys(value: dict[str, Any]) -> tuple[str, list[str]]:
    def post_lang_items(raw: dict[str, Any]) -> tuple[str, list[Any]]:
        return str(raw.get("title") or ""), raw.get("content") if isinstance(raw.get("content"), list) else []

    candidates: list[dict[str, Any]] = []
    if isinstance(value.get("content"), list):
        candidates.append(value)
    for item in value.values():
        if isinstance(item, dict) and isinstance(item.get("content"), list):
            candidates.append(item)

    texts: list[str] = []
    image_keys: list[str] = []
    for candidate in candidates[:1]:
        title, lines = post_lang_items(candidate)
        if title:
            texts.append(title)
        for line in lines:
            elements = line if isinstance(line, list) else [line]
            for element in elements:
                if not isinstance(element, dict):
                    continue
                tag = str(element.get("tag") or "").lower()
                if tag in {"text", "a", "markdown"}:
                    text = str(element.get("text") or "").strip()
                    if text:
                        texts.append(text)
                elif tag == "code_block":
                    text = str(element.get("text") or "").strip()
                    if text:
                        language = str(element.get("language") or "")
                        texts.append(f"```{language}\n{text}\n```")
                elif tag == "at":
                    user_name = str(element.get("user_name") or element.get("user_id") or "").strip()
                    if user_name and user_name != "all":
                        texts.append("@" + user_name)
                elif tag in {"img", "image"}:
                    image_key = str(element.get("image_key") or "").strip()
                    if image_key:
                        image_keys.append(image_key)
    return strip_feishu_mentions("\n".join(texts)), image_keys


def content_parts(message_type: str, content: Any) -> tuple[str, list[str], list[FeishuFileRef]]:
    value = parse_feishu_content(content)
    msg_type = str(message_type or value.get("msg_type") or value.get("message_type") or "").lower()
    if msg_type == "post" or isinstance(value.get("content"), list) or any(isinstance(v, dict) and isinstance(v.get("content"), list) for v in value.values()):
        text, image_keys = post_text_and_image_keys(value)
        return text, image_keys, []
    text = strip_feishu_mentions(str(value.get("text") or ""))
    image_keys: list[str] = []
    image_key = str(value.get("image_key") or "").strip()
    if image_key:
        image_keys.append(image_key)
    file_refs: list[FeishuFileRef] = []
    file_key = str(value.get("file_key") or "").strip()
    if file_key:
        file_refs.append(
            FeishuFileRef(
                file_key=file_key,
                file_name=str(value.get("file_name") or value.get("name") or "").strip(),
                resource_type="file",
            )
        )
    return text, image_keys, file_refs


def content_text_and_image_keys(message_type: str, content: Any) -> tuple[str, list[str]]:
    text, image_keys, _file_refs = content_parts(message_type, content)
    return text, image_keys


def message_parts(message: dict[str, Any]) -> tuple[str, list[str], list[FeishuFileRef]]:
    body = message.get("body", {})
    content = body.get("content") if isinstance(body, dict) else message.get("content", "")
    message_type = str(message.get("msg_type") or message.get("message_type") or "")
    return content_parts(message_type, content)


def message_text_and_image_keys(message: dict[str, Any]) -> tuple[str, list[str]]:
    text, image_keys, _file_refs = message_parts(message)
    return text, image_keys


def content_text(content: str) -> str:
    text, _image_keys, _file_refs = content_parts("", content)
    return text


def clamp_count(value: str | None, default: int = 20, maximum: int = 200) -> int:
    count = int(value or str(default))
    return max(1, min(count, maximum))


def default_command_count(command_name: str) -> int:
    return DEFAULT_THREAD_COUNT if command_name.endswith("_t") else DEFAULT_REPLY_COUNT


def parse_bot_command(text: str, default_author_id: str, default_tid: str) -> BotCommand | None:
    compact = " ".join(text.split())
    if re.search(r"(?:^|\s)/start(?:\s|$)", compact):
        return BotCommand(action="start")
    if re.search(r"(?:^|\s)/setting(?:s)?(?:\s|$)", compact):
        return BotCommand(action="setting")

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


def card_callback_value(action: str, **values: Any) -> dict[str, Any]:
    return {"action": action, **{key: value for key, value in values.items() if value is not None}}


def callback_button(label: str, action: str, button_type: str = "default", **values: Any) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": button_type,
        "behaviors": [{"type": "callback", "value": card_callback_value(action, **values)}],
    }


def callback_action_row(*buttons: dict[str, Any]) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []
    for button in buttons:
        columns.append(
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [button],
            }
        )
    return {
        "tag": "column_set",
        "flex_mode": "none",
        "background_style": "default",
        "columns": columns,
    }


def menu_back_row(action: str = "open_main_menu") -> dict[str, Any]:
    return callback_action_row(callback_button("← 返回", action))


def main_menu_card(args: argparse.Namespace, manager: ai_analysis.AIManager) -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": "NGA Wolf Watcher"}},
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"默认 uid `{args.default_author_id}`，默认 tid `{args.default_tid}`\n\n"
                        f"AI：`{'开' if manager.effective_enabled() else '关'}` | "
                        f"自动分析：`{'开' if manager.effective_auto() else '关'}` | "
                        f"定时分析：`{'开' if manager.effective_schedule() else '关'}`"
                    ),
                },
                callback_action_row(
                    callback_button("拉取信息", "open_fetch_menu", "primary"),
                    callback_button("设置", "open_settings"),
                ),
                callback_action_row(
                    callback_button("对话权限", "open_mode_settings"),
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "打开 NGA"},
                        "url": f"https://bbs.nga.cn/read.php?tid={args.default_tid}",
                        "type": "default",
                    },
                ),
            ]
        },
    }


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


def start_form_card(default_author_id: str, default_tid: str, *, show_back: bool = False) -> dict[str, Any]:
    elements: list[dict[str, Any]] = []
    if show_back:
        elements.append(menu_back_row("open_main_menu"))
    elements.extend(
        [
            {
                "tag": "markdown",
                "content": (
                    f"默认 uid `{default_author_id}` = 狼大\n"
                    f"默认 tid `{default_tid}` = 狼大贴\n\n"
                    "先选一个功能，机器人会在当前卡片打开已预填默认参数的执行表单。"
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
    )
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "拉取信息"},
        },
        "body": {"elements": elements},
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
                menu_back_row("open_fetch_menu"),
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


def ai_settings_card(manager: ai_analysis.AIManager, mention_enabled: bool = False, mention_user_id: str = "") -> dict[str, Any]:
    effective = manager.effective_config()
    state = manager.read_state()
    current_mode = manager.effective_permission_mode()
    mode_options = ai_analysis.permission_mode_options(manager.config.provider)
    schedule_prompt = str(state.get("schedule_prompt") or effective.schedule_prompt or ai_analysis.DEFAULT_SCHEDULED_ANALYSIS_PROMPT)
    auto_prompt = str(state.get("auto_analysis_prompt") or effective.auto_analysis_prompt or ai_analysis.DEFAULT_AUTO_ANALYSIS_PROMPT)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": "设置"}},
        "body": {
            "elements": [
                {
                    "tag": "markdown",
                    "content": (
                        f"AI：`{'开' if effective.enabled else '关'}` | "
                        f"自动新帖分析：`{'开' if effective.auto_analyze_new_post else '关'}` | "
                        f"定时分析：`{'开' if effective.schedule_enabled else '关'}`\n"
                        f"定时间隔：`{effective.schedule_interval_minutes}` 分钟\n"
                        f"时间窗口：`{effective.schedule_windows}`\n"
                        f"权限模式：`{manager.effective_permission_mode()}`\n"
                        f"@提醒：`{'开' if mention_enabled else '关'}`"
                        f"{f' | 当前对象：`{mention_user_id}`' if mention_user_id else ''}"
                    ),
                },
                callback_action_row(
                    callback_button("AI 开", "set_ai_enabled", "primary" if effective.enabled else "default", enabled=True),
                    callback_button("AI 关", "set_ai_enabled", "primary" if not effective.enabled else "default", enabled=False),
                ),
                callback_action_row(
                    callback_button("自动分析开", "set_ai_auto", "primary" if effective.auto_analyze_new_post else "default", enabled=True),
                    callback_button("自动分析关", "set_ai_auto", "primary" if not effective.auto_analyze_new_post else "default", enabled=False),
                ),
                callback_action_row(
                    callback_button("定时分析开", "set_ai_schedule", "primary" if effective.schedule_enabled else "default", enabled=True),
                    callback_button("定时分析关", "set_ai_schedule", "primary" if not effective.schedule_enabled else "default", enabled=False),
                ),
                callback_action_row(
                    callback_button("开启并@我", "set_mention_me", "primary" if mention_enabled else "default"),
                    callback_button("关闭@提醒", "disable_mention", "primary" if not mention_enabled else "default"),
                ),
                {"tag": "hr"},
                {
                    "tag": "form",
                    "name": "ai_settings_form",
                    "elements": [
                        {
                            "tag": "markdown",
                            "content": "**对话权限模式**\n控制本地 agent 执行工具和修改文件时的权限。`default` 最保守；`yolo`/`bypassPermissions` 风险最高。",
                        },
                        {
                            "tag": "select_static",
                            "name": "permission_mode",
                            "placeholder": {"tag": "plain_text", "content": "选择对话权限模式"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": mode}, "value": mode}
                                for mode, _desc in mode_options
                            ],
                        },
                        {
                            "tag": "markdown",
                            "content": "**定时分析频率（分钟）**\n每隔多少分钟在命中时间窗口时触发一次定时分析。",
                        },
                        {
                            "tag": "input",
                            "name": "schedule_interval",
                            "placeholder": {"tag": "plain_text", "content": "定时间隔分钟"},
                            "default_value": str(effective.schedule_interval_minutes),
                        },
                        {
                            "tag": "markdown",
                            "content": "**定时分析时间窗口**\n默认 A 股开市时间：`weekday:09:30-11:30,13:00-15:00`。",
                        },
                        {
                            "tag": "input",
                            "name": "schedule_windows",
                            "placeholder": {"tag": "plain_text", "content": "定时窗口，例如 weekday:09:30-11:30,13:00-15:00"},
                            "default_value": effective.schedule_windows,
                        },
                        {
                            "tag": "markdown",
                            "content": "**定时分析提示词**\n定时任务触发时发给本地 agent 的内容。",
                        },
                        {
                            "tag": "input",
                            "name": "schedule_prompt",
                            "placeholder": {"tag": "plain_text", "content": "定时分析提示词"},
                            "default_value": schedule_prompt,
                        },
                        {
                            "tag": "markdown",
                            "content": "**新帖自动分析提示词**\n监听到 NGA 新回复且自动分析开启时发给本地 agent 的内容。",
                        },
                        {
                            "tag": "input",
                            "name": "auto_prompt",
                            "placeholder": {"tag": "plain_text", "content": "新帖自动分析提示词"},
                            "default_value": auto_prompt,
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "保存设置"},
                            "type": "primary",
                            "name": "save",
                            "behaviors": [{"type": "callback", "value": {"action": "save_ai_settings"}}],
                            "form_action_type": "submit",
                        },
                    ],
                },
            ]
        },
    }


def processing_card(title: str, detail: str, back_action: str = "open_main_menu") -> dict[str, Any]:
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": title}},
        "body": {"elements": [menu_back_row(back_action), {"tag": "markdown", "content": detail}]},
    }


def ai_mode_card(manager: ai_analysis.AIManager, *, back_action: str = "open_main_menu") -> dict[str, Any]:
    provider = manager.config.provider
    current = manager.effective_permission_mode()
    options = ai_analysis.permission_mode_options(provider)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "orange" if current == "yolo" or current == "bypassPermissions" else "blue",
            "title": {"tag": "plain_text", "content": "AI 权限模式"},
        },
        "body": {
            "elements": [
                menu_back_row(back_action),
                {
                    "tag": "markdown",
                    "content": (
                        f"Provider: `{provider}`\n"
                        f"Current: `{current}`\n\n"
                        + "\n".join(f"- `{mode}`: {desc}" for mode, desc in options)
                    ),
                },
                {
                    "tag": "form",
                    "name": "ai_mode_form",
                    "elements": [
                        {
                            "tag": "select_static",
                            "name": "mode",
                            "placeholder": {"tag": "plain_text", "content": "选择权限模式"},
                            "options": [
                                {"text": {"tag": "plain_text", "content": mode}, "value": mode}
                                for mode, _desc in options
                            ],
                        },
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "保存权限模式"},
                            "type": "primary",
                            "name": "save",
                            "behaviors": [{"type": "callback", "value": {"action": "set_ai_mode"}}],
                            "form_action_type": "submit",
                        },
                    ],
                },
            ]
        },
    }


def ai_mode_text(manager: ai_analysis.AIManager) -> str:
    provider = manager.config.provider
    current = manager.effective_permission_mode()
    lines = [
        "AI permission modes",
        f"provider: {provider}",
        f"current: {current}",
        "",
        "Use `/mode <name>` to switch:",
    ]
    lines.extend(f"- {mode}: {desc}" for mode, desc in ai_analysis.permission_mode_options(provider))
    return "\n".join(lines)


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


def settings_card_for_args(args: argparse.Namespace, manager: ai_analysis.AIManager) -> dict[str, Any]:
    state = read_json(Path(args.state_path), {})
    return ai_settings_card(
        manager,
        mention_enabled=effective_mention_enabled(args, state),
        mention_user_id=effective_mention_user_id(args, state),
    )


def run_bot_command(args: argparse.Namespace, command: BotCommand) -> None:
    if command.action == "start":
        push_feishu_card(args, start_form_card(args.default_author_id, args.default_tid))
        return
    if command.action == "setting":
        manager = ai_manager_for_args(args)
        push_feishu_card(args, settings_card_for_args(args, manager))
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
    if len(posts) < command.count:
        title += f"（请求 {command.count} 条，NGA 临时限流时会先返回已获取部分）"
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


def card_action_sender_id(event: Any) -> str:
    event_body = getattr(event, "event", None)
    return object_sender_id(event_body) or object_sender_id(event)


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
        event_body = getattr(event, "event", None)
        msg = getattr(event_body, "message", None)
        if msg is None:
            return
        text, image_keys, file_refs = content_parts(
            getattr(msg, "message_type", "") or getattr(msg, "msg_type", "") or "",
            getattr(msg, "content", "") or "",
        )
        chat_id = getattr(msg, "chat_id", "") or receive_id
        sender_id = object_sender_id(event_body)
        message_id = getattr(msg, "message_id", "") or ""
        parent_id = getattr(msg, "parent_id", "") or getattr(msg, "root_id", "") or ""
        root_id = getattr(msg, "root_id", "") or ""
        reply_context, image_refs, file_refs = enrich_reply_context(args_for_chat(args, chat_id), message_id, image_keys, file_refs, parent_id, root_id)
        if ai_analysis.parse_ai_command(text) is not None:
            run_ai_command_background(args_for_chat(args, chat_id), text, sender_id, f"飞书消息:{message_id}", message_id, image_refs, file_refs, reply_context)
            return
        command = parse_bot_command(text, args.default_author_id, args.default_tid)
        if command is None:
            if should_forward_plain_text_to_ai(args_for_chat(args, chat_id), text, sender_id, image_keys, file_refs):
                run_ai_plain_text_background(args_for_chat(args, chat_id), text, sender_id, f"飞书消息:{message_id}", message_id, image_refs, file_refs, reply_context)
            return
        chat_id = getattr(msg, "chat_id", "") or receive_id
        run_command_background(args_for_chat(args, chat_id), command, f"飞书消息:{message_id}")

    def on_card_action(event: Any) -> Any:
        form = card_action_to_form(event)
        chat_id = card_action_chat_id(event, receive_id)
        sender_id = card_action_sender_id(event)

        def card_response(card: dict[str, Any] | None = None, content: str = "已更新", toast_type: str = "info") -> Any:
            payload: dict[str, Any] = {"toast": {"type": toast_type, "content": content}}
            if card is not None:
                payload["card"] = {"type": "raw", "data": card}
            return P2CardActionTriggerResponse(payload)

        try:
            action = form_action_name(form)
            scoped_args = args_for_chat(args, chat_id)
            manager = ai_manager_for_args(scoped_args)
            if action == "open_main_menu":
                return card_response(start_form_card(args.default_author_id, args.default_tid), "已返回查询菜单")
            if action == "open_fetch_menu":
                return card_response(start_form_card(args.default_author_id, args.default_tid, show_back=True), "已打开拉取信息")
            if action == "open_settings":
                return card_response(settings_card_for_args(scoped_args, manager), "已打开设置")
            if action == "open_mode_settings":
                return card_response(ai_mode_card(manager, back_action="open_settings"), "已打开权限设置")
            if action == "set_mention_me":
                if not sender_id:
                    return card_response(None, "无法识别当前飞书用户。", "error")
                state_path = Path(scoped_args.state_path)
                state = read_json(state_path, {})
                state["mention_enabled"] = True
                state["mention_user_id"] = sender_id
                state["mention_updated_at"] = int(time.time())
                write_watcher_state(state_path, state)
                print(f"已开启飞书 @ 提醒：{sender_id}")
                return card_response(settings_card_for_args(scoped_args, manager), "@提醒已开启")
            if action == "disable_mention":
                state_path = Path(scoped_args.state_path)
                state = read_json(state_path, {})
                state["mention_enabled"] = False
                state["mention_updated_at"] = int(time.time())
                write_watcher_state(state_path, state)
                print("已关闭飞书 @ 提醒")
                return card_response(settings_card_for_args(scoped_args, manager), "@提醒已关闭")
            if action == "set_ai_enabled":
                if not manager.is_authorized(sender_id):
                    return card_response(None, "AI command rejected: sender is not authorized.", "error")
                enabled = ai_analysis.bool_value(form.get("enabled"))
                manager.handle_command("/ai on" if enabled else "/ai off", sender_id)
                return card_response(settings_card_for_args(scoped_args, manager), "AI 已开启" if enabled else "AI 已关闭")
            if action == "set_ai_auto":
                if not manager.is_authorized(sender_id):
                    return card_response(None, "AI command rejected: sender is not authorized.", "error")
                enabled = ai_analysis.bool_value(form.get("enabled"))
                manager.handle_command("/ai auto on" if enabled else "/ai auto off", sender_id)
                return card_response(settings_card_for_args(scoped_args, manager), "自动分析已开启" if enabled else "自动分析已关闭")
            if action == "set_ai_schedule":
                if not manager.is_authorized(sender_id):
                    return card_response(None, "AI command rejected: sender is not authorized.", "error")
                enabled = ai_analysis.bool_value(form.get("enabled"))
                manager.handle_command("/ai schedule on" if enabled else "/ai schedule off", sender_id)
                return card_response(settings_card_for_args(scoped_args, manager), "定时分析已开启" if enabled else "定时分析已关闭")
            if action == "save_ai_settings":
                if not manager.is_authorized(sender_id):
                    return card_response(None, "AI command rejected: sender is not authorized.", "error")
                interval = str(form.get("schedule_interval") or "").strip()
                windows = str(form.get("schedule_windows") or "").strip()
                schedule_prompt = str(form.get("schedule_prompt") or "").strip()
                auto_prompt = str(form.get("auto_prompt") or "").strip()
                mode = str(form.get("permission_mode") or "").strip()
                if mode:
                    manager.handle_command(f"/mode {mode}", sender_id)
                if interval:
                    manager.handle_command(f"/ai schedule every {interval}", sender_id)
                if windows:
                    manager.handle_command(f"/ai schedule windows {windows}", sender_id)
                manager.handle_command(f"/ai schedule prompt {schedule_prompt}", sender_id)
                manager.handle_command(f"/ai auto prompt {auto_prompt}", sender_id)
                return card_response(settings_card_for_args(scoped_args, manager), "AI 设置已保存")
            if action == "set_ai_mode":
                mode = str(form.get("mode") or "")
                if not manager.is_authorized(sender_id):
                    return card_response(None, "AI command rejected: sender is not authorized.", "error")
                manager.handle_command(f"/mode {mode}", sender_id)
                return card_response(ai_mode_card(manager, back_action="open_settings"), f"AI mode set to {manager.effective_permission_mode()}")
            if action == "open_preset_form":
                command_name = str(form.get("command") or "history_r")
                target_id = str(form.get("target_id") or (args.default_tid if command_name.endswith("_t") else args.default_author_id))
                count = str(form.get("count") or default_command_count(command_name))
                return card_response(command_form_card(command_name, target_id, count), "已打开预填表单")
            command = bot_command_from_form(form, args.default_author_id, args.default_tid)
            run_command_background(scoped_args, command, "卡片操作")
            return card_response(processing_card("正在处理", f"已收到 `{command}`，结果会发送到当前群。", "open_fetch_menu"), "已收到，正在处理")
        except Exception as exc:
            return card_response(None, f"参数错误: {exc}", "error")

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
                    maybe_run_ai_schedule(args)
                except Exception as exc:
                    print(f"NGA 监听循环失败: {exc}", file=sys.stderr)
                jitter = random.uniform(-args.jitter, args.jitter) if args.jitter > 0 else 0
                time.sleep(max(1, args.interval + jitter))

        threading.Thread(target=watch_loop, daemon=True).start()
        print("已启动 NGA 后台监听循环。")

    while True:
        try:
            print("正在启动飞书 WebSocket 客户端。")
            lark.ws.Client(app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.ERROR).start()
            print("飞书 WebSocket 客户端已退出，5 秒后重连。", file=sys.stderr)
        except Exception as exc:
            print(f"飞书 WebSocket 客户端异常退出，5 秒后重连: {exc}", file=sys.stderr)
        time.sleep(5)


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
    state = read_json(Path(args.state_path), {})
    mention_user_id = feishu_mention_user_id(args, state)
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
                feishu_deferred_summary_card(posts, len(posts), mention_user_id),
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


def push_to_feishu(args: argparse.Namespace, post: NgaPost, mention_user_id: str = "") -> None:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")

    if app_id or app_secret or receive_id:
        if not (app_id and app_secret and receive_id):
            raise SystemExit("缺少 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID。")
        push_feishu_app(app_id, app_secret, receive_id, receive_id_type, post, args.timeout, args.message_format, mention_user_id)
        return

    if not webhook:
        raise SystemExit("缺少飞书发送目标。请设置应用凭证和 Receive ID，或设置 FEISHU_WEBHOOK。")
    push_feishu(webhook, secret, post, args.timeout)


def sleep_between_nga_pages(page_delay: float) -> None:
    if page_delay <= 0:
        return
    time.sleep(page_delay + random.uniform(0, page_delay * 0.5))


def collect_posts(
    author_id: str,
    cookie: str,
    max_pages: int,
    timeout: int,
    attempts: int = 1,
    retry_delay: float = 0,
    page_delay: float = DEFAULT_NGA_PAGE_DELAY,
    allow_partial: bool = False,
) -> list[NgaPost]:
    posts: list[NgaPost] = []
    for page in range(1, max_pages + 1):
        try:
            payload = with_retries(
                f"NGA 用户回复第 {page} 页",
                attempts,
                retry_delay,
                lambda page=page: fetch_nga_page(author_id, page, cookie, timeout),
            )
        except Exception as exc:
            if allow_partial and posts and is_nga_temporary_unavailable(exc):
                print(f"NGA 用户回复第 {page} 页临时不可用，返回已抓到的 {len(posts)} 条。", file=sys.stderr)
                break
            raise
        page_posts = extract_posts(payload)
        if page > 1 and not page_posts:
            break
        posts.extend(page_posts)
        if page < max_pages:
            sleep_between_nga_pages(page_delay)
    return posts


def collect_recent_replies(
    author_id: str,
    count: int,
    cookie: str,
    timeout: int,
    attempts: int = 1,
    retry_delay: float = 0,
    page_delay: float = DEFAULT_NGA_PAGE_DELAY,
    allow_partial: bool = False,
) -> list[NgaPost]:
    pages = max(1, (count + 19) // 20)
    return collect_posts(author_id, cookie, pages, timeout, attempts, retry_delay, page_delay, allow_partial)[:count]


def collect_thread_tail(
    tid: str,
    count: int,
    cookie: str,
    timeout: int,
    attempts: int = 1,
    retry_delay: float = 0,
    page_delay: float = DEFAULT_NGA_PAGE_DELAY,
    allow_partial: bool = False,
) -> list[NgaPost]:
    first_payload = with_retries(
        f"NGA 帖子 {tid} 最新页",
        attempts,
        retry_delay,
        lambda: fetch_nga_thread_page(tid, 99999, cookie, timeout),
    )
    first_posts, last_page = extract_thread_posts(first_payload)
    if not last_page:
        last_page = 1

    posts_by_page: list[NgaPost] = list(first_posts)
    page = last_page - 1
    while len(posts_by_page) < count and page >= 1:
        sleep_between_nga_pages(page_delay)
        try:
            payload = with_retries(
                f"NGA 帖子 {tid} 第 {page} 页",
                attempts,
                retry_delay,
                lambda page=page: fetch_nga_thread_page(tid, page, cookie, timeout),
            )
        except Exception as exc:
            if allow_partial and posts_by_page and is_nga_temporary_unavailable(exc):
                print(f"NGA 帖子 {tid} 第 {page} 页临时不可用，返回已抓到的 {len(posts_by_page)} 条。", file=sys.stderr)
                break
            raise
        page_posts, _ = extract_thread_posts(payload)
        posts_by_page = page_posts + posts_by_page
        page -= 1
    return posts_by_page[-count:]


def with_retries(label: str, attempts: int, delay: float, fn: Any) -> Any:
    last_exc: Exception | None = None
    unavailable_limit = max(1, int(os.getenv("NGA_UNAVAILABLE_RETRIES", str(DEFAULT_NGA_UNAVAILABLE_RETRIES))))
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            effective_attempts = min(attempts, unavailable_limit) if is_nga_temporary_unavailable(exc) else attempts
            if attempt >= effective_attempts:
                break
            if is_nga_temporary_unavailable(exc):
                sleep_for = max(delay * attempt, 5 * attempt) + random.uniform(0, max(delay, 2))
            else:
                sleep_for = delay * attempt + random.uniform(0, delay)
            print(f"{label} 失败（{attempt}/{effective_attempts}）：{exc}；{sleep_for:.1f} 秒后重试", file=sys.stderr)
            time.sleep(sleep_for)
    message = f"{label} 在 {effective_attempts} 次尝试后仍失败：{last_exc}"
    if last_exc and is_nga_temporary_unavailable(last_exc):
        raise NgaTemporaryUnavailable(message) from last_exc
    raise RuntimeError(message)


def collect_posts_with_retries(args: argparse.Namespace, count_pages: int | None = None) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")
    max_pages = count_pages if count_pages is not None else args.max_pages
    return collect_posts(
        args.author_id,
        cookie,
        max_pages,
        args.timeout,
        args.retries,
        args.retry_delay,
        getattr(args, "nga_page_delay", DEFAULT_NGA_PAGE_DELAY),
        False,
    )


def collect_replies_with_retries(args: argparse.Namespace, author_id: str, count: int) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")
    return collect_recent_replies(
        author_id,
        count,
        cookie,
        args.timeout,
        args.retries,
        args.retry_delay,
        getattr(args, "nga_page_delay", DEFAULT_NGA_PAGE_DELAY),
        True,
    )


def collect_thread_tail_with_retries(args: argparse.Namespace, tid: str, count: int) -> list[NgaPost]:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")
    return collect_thread_tail(
        tid,
        count,
        cookie,
        args.timeout,
        args.retries,
        args.retry_delay,
        getattr(args, "nga_page_delay", DEFAULT_NGA_PAGE_DELAY),
        True,
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
        if is_feishu_bot_message(message):
            handled.add(message_id)
            changed = True
            continue
        text, image_keys, file_refs = message_parts(message)
        parent_id = str(message.get("parent_id") or message.get("root_id") or "")
        root_id = str(message.get("root_id") or "")
        reply_context, image_refs, file_refs = enrich_reply_context(args, message_id, image_keys, file_refs, parent_id, root_id)
        sender_id = sender_id_from_message(message)
        if ai_analysis.parse_ai_command(text) is not None:
            try:
                run_ai_command_background(args, text, sender_id, f"飞书消息轮询:{message_id}", message_id, image_refs, file_refs, reply_context)
            except Exception as exc:
                if ai_analysis.AIConfig.from_namespace(args).send_errors_to_feishu:
                    push_feishu_text(args, "AI command failed", str(exc))
                else:
                    print(f"AI 命令轮询处理失败: {exc}", file=sys.stderr)
            handled.add(message_id)
            changed = True
            continue
        command = parse_bot_command(text, args.default_author_id, args.default_tid)
        if command is None:
            if should_forward_plain_text_to_ai(args, text, sender_id, image_keys, file_refs):
                run_ai_plain_text_background(args, text, sender_id, f"飞书消息轮询:{message_id}", message_id, image_refs, file_refs, reply_context)
                handled.add(message_id)
                changed = True
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
    mention_user_id = feishu_mention_user_id(args, state)

    posts = collect_posts_with_retries(args)
    if args.mark_seen:
        for post in posts:
            seen.add(post.key)
        state["seen"] = sorted(seen)
        state["updated_at"] = int(time.time())
        write_watcher_state(state_path, state)
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
            write_watcher_state(state_path, state)
            print(f"已推送免打扰期间新回复汇总：{len(deferred_posts)} 条。")
    elif deliver_posts:
        for post in deliver_posts:
            seen.add(post.key)
        if args.dry_run:
            print(f"[试运行] 当前处于免打扰时段，本轮 {len(deliver_posts)} 条新回复不会推送。")
        else:
            print(f"当前处于免打扰时段，已标记 {len(deliver_posts)} 条非免打扰区间旧回复为已读，不纳入汇总。")
        deliver_posts = []

    ai_pushed_posts: list[NgaPost] = []
    for post in new_posts:
        if post not in deliver_posts:
            continue
        if args.dry_run:
            print(f"[试运行] {post.subject} {post.url}\n{post.content[:500]}\n")
        else:
            push_to_feishu(args, post, mention_user_id)
            seen.add(post.key)
            ai_pushed_posts.append(post)

    if ai_pushed_posts:
        after_posts_pushed_for_ai(args, ai_pushed_posts)

    if not args.dry_run:
        state["seen"] = sorted(seen)
        state["updated_at"] = int(time.time())
        write_watcher_state(state_path, state)
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
    parser.add_argument(
        "--feishu-mention-enabled",
        "--mention-enabled",
        dest="feishu_mention_enabled",
        action="store_true",
        default=ai_analysis.env_bool("FEISHU_MENTION_ENABLED", False),
        help="在自动新回复和免打扰汇总卡片中 @ 指定飞书用户。",
    )
    parser.add_argument(
        "--feishu-mention-user-id",
        "--mention-user-id",
        dest="feishu_mention_user_id",
        default=os.getenv("FEISHU_MENTION_USER_ID", ""),
        help="卡片 @ 的飞书用户 ID。通常通过 /setting 卡片点击“开启并@我”自动保存。",
    )
    parser.add_argument("--disable-commands", action="store_true", help="不轮询飞书群组普通消息命令。")
    parser.add_argument("--command-lookback", type=int, default=int(os.getenv("FEISHU_COMMAND_LOOKBACK", "600")))
    parser.add_argument("--retries", type=int, default=int(os.getenv("NGA_RETRIES", "10")))
    parser.add_argument("--retry-delay", type=float, default=float(os.getenv("NGA_RETRY_DELAY", "2")))
    parser.add_argument("--nga-page-delay", type=float, default=float(os.getenv("NGA_PAGE_DELAY", str(DEFAULT_NGA_PAGE_DELAY))))
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
    ai_analysis.add_cli_arguments(parser)
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
                    write_watcher_state(state_path, state)
            except Exception as exc:
                print(f"飞书命令轮询失败: {exc}", file=sys.stderr)
            run_once(args)
            maybe_run_ai_schedule(args)
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
