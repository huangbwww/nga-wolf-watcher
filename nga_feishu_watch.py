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
  NGA_INTERVAL       Defaults to 30 seconds in watch mode.
  NGA_THREAD_WATCH_INTERVAL Defaults to 10 seconds for thread-author scans.
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
import wechat_bot


NGA_ENDPOINT = "https://bbs.nga.cn/thread.php"
NGA_READ_ENDPOINT = "https://bbs.nga.cn/read.php"
FEISHU_API = "https://open.feishu.cn/open-apis"
DEFAULT_AUTHOR_ID = "150058"
DEFAULT_TID = "45974302"
DEFAULT_REPLY_COUNT = 5
DEFAULT_THREAD_COUNT = 10
DEFAULT_THREAD_WATCH_TAIL_COUNT = 20
DEFAULT_THREAD_WATCH_INTERVAL = 10.0
DEFAULT_QUIET_START_DAY = 5
DEFAULT_QUIET_END_DAY = 0
DEFAULT_QUIET_DAYS = [5, 6]
DEFAULT_QUIET_START_TIME = "00:00"
DEFAULT_QUIET_END_TIME = "00:00"
DEFAULT_QUIET_POLICY = "ignore"
DEFAULT_NGA_PAGE_DELAY = 2.0
DEFAULT_NGA_UNAVAILABLE_RETRIES = 3
DEFAULT_RETRY_INITIAL_DELAY = 1.0
DEFAULT_NGA_REQUEST_MIN_INTERVAL = 1.0
DEFAULT_NGA_CACHE_TTL = 15.0
DEFAULT_NGA_TARGET_MIN_DELAY = 2.0
DEFAULT_NGA_TARGET_MAX_DELAY = 6.0
DEFAULT_NGA_UNAVAILABLE_BACKOFF_BASE = 60.0
DEFAULT_NGA_UNAVAILABLE_BACKOFF_MAX = 600.0
DEFAULT_FEISHU_CARD_IMAGE_LIMIT = 6
FEISHU_IMAGE_MAX_BYTES = 10 * 1024 * 1024
NGA_TEMPORARY_STATUS_CODES = {429, 500, 502, 503, 504}
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
QUOTE_END_MARKER = "__NGA_QUOTE_END__"
_AI_MANAGERS: dict[tuple[str, str], ai_analysis.AIManager] = {}
_AI_FEISHU_QUEUES: dict[tuple[str, str], "queue.Queue[Callable[[], None]]"] = {}
_AI_FEISHU_QUEUE_LOCK = threading.Lock()
_WATCHER_STATE_LOCK = threading.Lock()
_FEISHU_IMAGE_CACHE_LOCK = threading.Lock()
_NGA_REQUEST_LOCK = threading.Lock()
_NGA_LAST_REQUEST_AT = 0.0
_NGA_JSON_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_WECHAT_CLIENTS: dict[tuple[str, str], wechat_bot.WeChatBotClient] = {}


class NgaTemporaryUnavailable(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def nga_status_code(exc: BaseException | None) -> int | None:
    current = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, "status_code", None) or getattr(current, "code", None)
        try:
            if int(status) in range(100, 600):
                return int(status)
        except (TypeError, ValueError):
            pass
        text = str(current)
        for match in re.finditer(r"(?:状态码|status(?:_code)?|HTTP(?:\s+Error)?|code)\s*[=: ]\s*(\d{3})", text, flags=re.I):
            code = int(match.group(1))
            if code in range(100, 600):
                return code
        current = current.__cause__ or current.__context__
    return None


def is_nga_temporary_unavailable(exc: Exception) -> bool:
    status = nga_status_code(exc)
    return isinstance(exc, NgaTemporaryUnavailable) or status in NGA_TEMPORARY_STATUS_CODES


def is_nga_service_unavailable(exc: Exception) -> bool:
    return nga_status_code(exc) == 503


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
    source_type: str = ""
    source_id: str = ""
    source_label: str = ""
    canonical_key: str = ""


@dataclass(frozen=True)
class WatchTarget:
    id: str
    label: str = ""
    route_channel: str = ""
    route_profile_id: str = ""
    route_receive_id: str = ""
    route_id_type: str = "chat_id"


@dataclass(frozen=True)
class ThreadAuthorWatch:
    tid: str
    author_id: str
    label: str = ""
    route_channel: str = ""
    route_profile_id: str = ""
    feishu_app_id: str = ""
    feishu_app_secret: str = ""
    feishu_receive_id: str = ""
    feishu_id_type: str = "chat_id"

    @property
    def key(self) -> str:
        return f"{self.tid}:{self.author_id}"


@dataclass(frozen=True)
class FeishuBotProfile:
    id: str
    label: str = ""
    app_id: str = ""
    app_secret: str = ""
    id_type: str = "chat_id"
    chats: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class WeChatBotProfile:
    id: str
    label: str = ""
    token: str = ""
    base_url: str = wechat_bot.DEFAULT_WECHAT_BASE_URL
    cdn_base_url: str = wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL
    target_user_id: str = ""
    allowed_user_ids: str = ""
    poll_timeout_ms: int = wechat_bot.DEFAULT_WECHAT_POLL_TIMEOUT_MS
    route_tag: str = ""
    account_id: str = "default"


@dataclass(frozen=True)
class PushTarget:
    id: str
    label: str = ""
    channel: str = "feishu"
    profile_id: str = ""
    receive_id: str = ""
    id_type: str = "chat_id"
    default_author_id: str = ""
    default_tid: str = ""


@dataclass(frozen=True)
class ListenRule:
    id: str
    label: str = ""
    mode: str = "thread_author"
    author_id: str = ""
    tid: str = ""
    target_ids: tuple[str, ...] = ()

    @property
    def source_key(self) -> str:
        if self.mode == "thread_author":
            return f"{self.tid}:{self.author_id}"
        return self.author_id


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


TARGET_INLINE_SEPARATOR_RE = re.compile(r"[,，;；](?=\s*\d+(?:\s*[:=]|\s*(?:[,，;；]|$)))")


def stable_profile_id(prefix: str, *parts: str) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{digest}"


def json_list_value(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, tuple):
        return list(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return value if isinstance(value, list) else []
    return []


def parse_route_parts(route_parts: list[str]) -> dict[str, str]:
    route: dict[str, str] = {}
    for part in route_parts:
        text = part.strip()
        if not text:
            continue
        if "=" in text:
            key, value = text.split("=", 1)
            route[key.strip().lower().replace("-", "_")] = value.strip()
        elif text.startswith("oc_") or text.startswith("ou_") or text.startswith("on_"):
            route["receive_id"] = text
    return route


def route_channel_from_parts(route: dict[str, str], default: str = "") -> str:
    value = (route.get("channel") or route.get("route_channel") or default).strip().lower()
    if value in {"feishu", "wechat"}:
        return value
    if route.get("wechat_profile") or route.get("wechat_profile_id"):
        return "wechat"
    if route.get("bot") or route.get("profile") or route.get("profile_id") or route.get("receive_id"):
        return "feishu"
    return ""


def parse_target_list(raw: Any, fallback_id: str = "") -> list[WatchTarget]:
    text = str(raw or "").strip()
    targets: list[WatchTarget] = []
    seen: set[str] = set()
    parts: list[str] = []
    for line in re.split(r"[\r\n]+", text):
        item = line.strip()
        if not item:
            continue
        parts.extend(part.strip() for part in TARGET_INLINE_SEPARATOR_RE.split(item) if part.strip())
    for part in parts:
        item = part.strip()
        if not item:
            continue
        main, *route_parts = [part.strip() for part in item.split("|")]
        route = parse_route_parts(route_parts)
        if "=" in main:
            raw_id, raw_label = main.split("=", 1)
        elif ":" in main:
            raw_id, raw_label = main.split(":", 1)
        else:
            raw_id, raw_label = main, ""
        target_id = raw_id.strip()
        label = raw_label.strip()
        if not target_id or target_id in seen:
            continue
        seen.add(target_id)
        targets.append(
            WatchTarget(
                target_id,
                label,
                route_channel=route_channel_from_parts(route),
                route_profile_id=route.get("bot", "") or route.get("profile", "") or route.get("profile_id", "") or route.get("wechat_profile", "") or route.get("wechat_profile_id", ""),
                route_receive_id=route.get("receive_id", "") or route.get("feishu_receive_id", ""),
                route_id_type=route.get("id_type", "") or route.get("receive_id_type", "") or route.get("feishu_id_type", "chat_id"),
            )
        )
    fallback = str(fallback_id or "").strip()
    if not targets and fallback:
        targets.append(WatchTarget(fallback, ""))
    return targets


def target_display_name(target: WatchTarget) -> str:
    return f"{target.label}({target.id})" if target.label else target.id


def thread_author_display_name(watch: ThreadAuthorWatch) -> str:
    base = f"{watch.tid}:{watch.author_id}"
    return f"{watch.label}({base})" if watch.label else base


def parse_thread_author_watches(raw: Any) -> list[ThreadAuthorWatch]:
    text = str(raw or "").strip()
    watches: list[ThreadAuthorWatch] = []
    seen: set[str] = set()
    for line in re.split(r"[\r\n]+", text):
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        main, *route_parts = [part.strip() for part in item.split("|")]
        if "=" in main:
            raw_pair, raw_label = main.split("=", 1)
        else:
            raw_pair, raw_label = main, ""
        if ":" not in raw_pair:
            continue
        raw_tid, raw_authors = raw_pair.split(":", 1)
        tid = raw_tid.strip()
        label = raw_label.strip()
        route = parse_route_parts(route_parts)
        for author_part in re.split(r"[,，;；\s]+", raw_authors):
            author_id = author_part.strip()
            if not tid or not author_id:
                continue
            key = f"{tid}:{author_id}"
            if key in seen:
                continue
            seen.add(key)
            watches.append(
                ThreadAuthorWatch(
                    tid=tid,
                    author_id=author_id,
                    label=label,
                    route_channel=route_channel_from_parts(route),
                    route_profile_id=route.get("bot", "") or route.get("profile", "") or route.get("profile_id", "") or route.get("wechat_profile", "") or route.get("wechat_profile_id", ""),
                    feishu_app_id=route.get("app_id", "") or route.get("feishu_app_id", ""),
                    feishu_app_secret=route.get("app_secret", "") or route.get("feishu_app_secret", ""),
                    feishu_receive_id=route.get("receive_id", "") or route.get("feishu_receive_id", ""),
                    feishu_id_type=route.get("id_type", "") or route.get("receive_id_type", "") or route.get("feishu_id_type", "chat_id"),
                )
            )
    return watches


def post_source_display_name(post: NgaPost) -> str:
    return (post.source_label or post.source_id or "").strip()


def new_reply_title(post: NgaPost) -> str:
    source_name = post_source_display_name(post)
    if source_name:
        if post.source_type == "thread_author" and post.subject:
            title = post.subject.strip()
            if len(title) > 36:
                title = title[:36].rstrip() + "..."
            if post.source_label:
                return f"{source_name} 在《{title}》新回复"
            return f"帖内作者 {source_name} 在《{title}》新回复"
        if post.source_label:
            return f"{source_name} 新回复"
        if post.source_type == "author":
            return f"用户 {source_name} 新回复"
        return f"{source_name} 新回复"
    return "NGA 新回复"


def watch_author_targets(args: argparse.Namespace) -> list[WatchTarget]:
    raw = getattr(args, "author_ids", "") or getattr(args, "watch_author_ids", "")
    return parse_target_list(raw, getattr(args, "author_id", "") or getattr(args, "default_author_id", DEFAULT_AUTHOR_ID))


def preset_thread_targets(args: argparse.Namespace) -> list[WatchTarget]:
    raw = getattr(args, "preset_thread_ids", "")
    return parse_target_list(raw, getattr(args, "default_tid", DEFAULT_TID))


def thread_author_watches(args: argparse.Namespace) -> list[ThreadAuthorWatch]:
    return parse_thread_author_watches(getattr(args, "thread_author_watches", "") or os.getenv("NGA_THREAD_AUTHOR_WATCHES", ""))


def parse_feishu_bot_profiles(raw: Any) -> list[FeishuBotProfile]:
    profiles: list[FeishuBotProfile] = []
    seen: set[str] = set()
    for item in json_list_value(raw):
        if not isinstance(item, dict):
            continue
        app_id = str(item.get("app_id") or item.get("feishu_app_id") or "").strip()
        app_secret = str(item.get("app_secret") or item.get("feishu_app_secret") or "").strip()
        profile_id = str(item.get("id") or "").strip() or stable_profile_id("feishu", app_id, str(item.get("label") or ""))
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        raw_chats = item.get("chats") if isinstance(item.get("chats"), list) else []
        chats: list[dict[str, str]] = []
        for chat in raw_chats:
            if not isinstance(chat, dict):
                continue
            chat_id = str(chat.get("chat_id") or chat.get("id") or "").strip()
            if not chat_id:
                continue
            chats.append(
                {
                    "chat_id": chat_id,
                    "name": str(chat.get("name") or chat.get("title") or "").strip(),
                    "chat_type": str(chat.get("chat_type") or "").strip(),
                }
            )
        profiles.append(
            FeishuBotProfile(
                id=profile_id,
                label=str(item.get("label") or item.get("name") or "").strip(),
                app_id=app_id,
                app_secret=app_secret,
                id_type=str(item.get("id_type") or item.get("feishu_id_type") or "chat_id").strip() or "chat_id",
                chats=tuple(chats),
            )
        )
    return profiles


def parse_wechat_bot_profiles(raw: Any) -> list[WeChatBotProfile]:
    profiles: list[WeChatBotProfile] = []
    seen: set[str] = set()
    for item in json_list_value(raw):
        if not isinstance(item, dict):
            continue
        token = str(item.get("token") or item.get("wechat_bot_token") or "").strip()
        account_id = str(item.get("account_id") or item.get("wechat_bot_account_id") or "default").strip() or "default"
        profile_id = str(item.get("id") or "").strip() or stable_profile_id("wechat", account_id, token[:16])
        if not profile_id or profile_id in seen:
            continue
        seen.add(profile_id)
        profiles.append(
            WeChatBotProfile(
                id=profile_id,
                label=str(item.get("label") or item.get("name") or "").strip(),
                token=token,
                base_url=str(item.get("base_url") or item.get("wechat_bot_base_url") or wechat_bot.DEFAULT_WECHAT_BASE_URL).strip() or wechat_bot.DEFAULT_WECHAT_BASE_URL,
                cdn_base_url=str(item.get("cdn_base_url") or item.get("wechat_bot_cdn_base_url") or wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL).strip() or wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL,
                target_user_id=str(item.get("target_user_id") or item.get("wechat_bot_target_user_id") or "").strip(),
                allowed_user_ids=str(item.get("allowed_user_ids") or item.get("wechat_bot_allowed_user_ids") or "").strip(),
                poll_timeout_ms=wechat_bot.safe_int(item.get("poll_timeout_ms") or item.get("wechat_bot_poll_timeout_ms"), wechat_bot.DEFAULT_WECHAT_POLL_TIMEOUT_MS),
                route_tag=str(item.get("route_tag") or item.get("wechat_bot_route_tag") or "").strip(),
                account_id=account_id,
            )
        )
    return profiles


def normalize_channel(raw: Any, default: str = "feishu") -> str:
    value = str(raw or default).strip().lower()
    return value if value in {"feishu", "wechat"} else default


def normalize_listen_mode(raw: Any, default: str = "thread_author") -> str:
    value = str(raw or default).strip().lower().replace("-", "_")
    return value if value in {"author", "thread_author"} else default


def parse_push_targets(raw: Any) -> list[PushTarget]:
    targets: list[PushTarget] = []
    seen: set[str] = set()
    for item in json_list_value(raw):
        if not isinstance(item, dict):
            continue
        channel = normalize_channel(item.get("channel") or item.get("route_channel"))
        target_id = str(item.get("id") or "").strip()
        profile_id = str(item.get("profile_id") or item.get("profile") or item.get("bot") or item.get("route_profile_id") or "").strip()
        receive_id = str(
            item.get("receive_id")
            or item.get("chat_id")
            or item.get("target_user_id")
            or item.get("feishu_receive_id")
            or item.get("route_receive_id")
            or ""
        ).strip()
        if not target_id:
            target_id = stable_profile_id("target", channel, profile_id, receive_id, str(item.get("label") or item.get("name") or ""))
        if not target_id or target_id in seen:
            continue
        seen.add(target_id)
        targets.append(
            PushTarget(
                id=target_id,
                label=str(item.get("label") or item.get("name") or "").strip(),
                channel=channel,
                profile_id=profile_id,
                receive_id=receive_id,
                id_type=str(item.get("id_type") or item.get("receive_id_type") or item.get("feishu_id_type") or "chat_id").strip() or "chat_id",
                default_author_id=str(item.get("default_author_id") or item.get("author_id") or "").strip(),
                default_tid=str(item.get("default_tid") or item.get("tid") or "").strip(),
            )
        )
    return targets


def parse_listen_rules(raw: Any) -> list[ListenRule]:
    rules: list[ListenRule] = []
    seen: set[str] = set()
    for item in json_list_value(raw):
        if not isinstance(item, dict):
            continue
        mode = normalize_listen_mode(item.get("mode") or item.get("type") or item.get("watch_mode"))
        author_id = str(item.get("author_id") or item.get("uid") or item.get("user_id") or "").strip()
        tid = str(item.get("tid") or item.get("thread_id") or "").strip()
        if mode == "author":
            if not author_id:
                continue
            natural_id = f"author:{author_id}"
        else:
            if not (tid and author_id):
                continue
            natural_id = f"thread_author:{tid}:{author_id}"
        rule_id = str(item.get("id") or "").strip() or natural_id
        if rule_id in seen:
            continue
        seen.add(rule_id)
        raw_targets = item.get("target_ids")
        if raw_targets is None:
            raw_targets = item.get("targets")
        if isinstance(raw_targets, str):
            target_ids = [part.strip() for part in re.split(r"[,，;；\s]+", raw_targets) if part.strip()]
        elif isinstance(raw_targets, Iterable):
            target_ids = [str(part).strip() for part in raw_targets if str(part).strip()]
        else:
            target_ids = []
        rules.append(
            ListenRule(
                id=rule_id,
                label=str(item.get("label") or item.get("name") or "").strip(),
                mode=mode,
                author_id=author_id,
                tid=tid,
                target_ids=tuple(dict.fromkeys(target_ids)),
            )
        )
    return rules


def feishu_bot_profiles(args: argparse.Namespace) -> list[FeishuBotProfile]:
    raw = getattr(args, "feishu_bot_profiles", "") or os.getenv("FEISHU_BOT_PROFILES", "")
    profiles = parse_feishu_bot_profiles(raw)
    if profiles:
        return profiles
    app_id = getattr(args, "feishu_app_id", "") or os.getenv("FEISHU_APP_ID", "")
    app_secret = getattr(args, "feishu_app_secret", "") or os.getenv("FEISHU_APP_SECRET", "")
    if not (app_id or app_secret):
        return []
    return [
        FeishuBotProfile(
            id="default",
            label="default",
            app_id=str(app_id).strip(),
            app_secret=str(app_secret).strip(),
            id_type=str(getattr(args, "feishu_id_type", "") or os.getenv("FEISHU_ID_TYPE", "chat_id")).strip() or "chat_id",
        )
    ]


def wechat_bot_profiles(args: argparse.Namespace) -> list[WeChatBotProfile]:
    raw = getattr(args, "wechat_bot_profiles", "") or os.getenv("WECHAT_BOT_PROFILES", "")
    profiles = parse_wechat_bot_profiles(raw)
    if profiles:
        return profiles
    token = getattr(args, "wechat_bot_token", "") or os.getenv("WECHAT_BOT_TOKEN", "")
    if not token:
        return []
    return [
        WeChatBotProfile(
            id="default",
            label="default",
            token=str(token).strip(),
            base_url=str(getattr(args, "wechat_bot_base_url", "") or os.getenv("WECHAT_BOT_BASE_URL", wechat_bot.DEFAULT_WECHAT_BASE_URL)).strip() or wechat_bot.DEFAULT_WECHAT_BASE_URL,
            cdn_base_url=str(getattr(args, "wechat_bot_cdn_base_url", "") or os.getenv("WECHAT_BOT_CDN_BASE_URL", wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL)).strip() or wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL,
            target_user_id=str(getattr(args, "wechat_bot_target_user_id", "") or os.getenv("WECHAT_BOT_TARGET_USER_ID", "")).strip(),
            allowed_user_ids=str(getattr(args, "wechat_bot_allowed_user_ids", "") or os.getenv("WECHAT_BOT_ALLOWED_USER_IDS", "")).strip(),
            poll_timeout_ms=wechat_bot.safe_int(getattr(args, "wechat_bot_poll_timeout_ms", None) or os.getenv("WECHAT_BOT_POLL_TIMEOUT_MS", ""), wechat_bot.DEFAULT_WECHAT_POLL_TIMEOUT_MS),
            route_tag=str(getattr(args, "wechat_bot_route_tag", "") or os.getenv("WECHAT_BOT_ROUTE_TAG", "")).strip(),
            account_id=str(getattr(args, "wechat_bot_account_id", "") or os.getenv("WECHAT_BOT_ACCOUNT_ID", "default")).strip() or "default",
        )
    ]


def configured_push_targets(args: argparse.Namespace) -> list[PushTarget]:
    raw = getattr(args, "push_targets", "") or os.getenv("NGA_PUSH_TARGETS", "")
    targets = parse_push_targets(raw)
    if targets:
        return targets
    channel = bot_channel(args)
    if channel == "wechat":
        profile = find_wechat_profile(args, "")
        receive_id = str(getattr(args, "wechat_bot_target_user_id", "") or "").strip()
        if profile or receive_id:
            return [
                PushTarget(
                    id="default",
                    label="默认微信",
                    channel="wechat",
                    profile_id=profile.id if profile else "",
                    receive_id=receive_id or (profile.target_user_id if profile else ""),
                    default_author_id=str(getattr(args, "default_author_id", "") or DEFAULT_AUTHOR_ID),
                    default_tid=str(getattr(args, "default_tid", "") or DEFAULT_TID),
                )
            ]
        return []
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    profile = find_feishu_profile(args, "")
    if app_id or app_secret or receive_id or profile:
        return [
            PushTarget(
                id="default",
                label="默认飞书",
                channel="feishu",
                profile_id=profile.id if profile else "",
                receive_id=receive_id,
                id_type=receive_id_type or (profile.id_type if profile else "chat_id"),
                default_author_id=str(getattr(args, "default_author_id", "") or DEFAULT_AUTHOR_ID),
                default_tid=str(getattr(args, "default_tid", "") or DEFAULT_TID),
            )
        ]
    return []


def configured_listen_rules(args: argparse.Namespace) -> list[ListenRule]:
    raw = getattr(args, "listen_rules", "") or os.getenv("NGA_LISTEN_RULES", "")
    return parse_listen_rules(raw)


def find_push_target(args: argparse.Namespace, target_id: str) -> PushTarget | None:
    wanted = str(target_id or "").strip()
    targets = configured_push_targets(args)
    if not wanted and targets:
        return targets[0]
    for target in targets:
        if wanted in {target.id, target.label, target.receive_id}:
            return target
    return None


def push_target_for_channel_receive(args: argparse.Namespace, channel: str, receive_id: str) -> PushTarget | None:
    wanted_channel = normalize_channel(channel)
    wanted_receive = str(receive_id or "").strip()
    if not wanted_receive:
        return None
    for target in configured_push_targets(args):
        if target.channel == wanted_channel and target.receive_id == wanted_receive:
            return target
    return None


def csv_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,，;；\s]+", value) if part.strip()]
    if isinstance(value, Iterable):
        return [str(part).strip() for part in value if str(part).strip()]
    return []


def ai_schedule_recipient_args(args: argparse.Namespace) -> list[argparse.Namespace]:
    raw = getattr(args, "ai_schedule_target_ids", "") or os.getenv("AI_SCHEDULE_TARGET_IDS", "")
    target_ids = csv_values(raw)
    if any(target_id.lower() in {"__none__", "none", "off"} for target_id in target_ids):
        return []
    if not target_ids:
        configured_targets = configured_push_targets(args)
        if parse_push_targets(getattr(args, "push_targets", "")) and configured_targets:
            first_target_id = next((target.id for target in configured_targets if target.id), "")
            target_ids = [first_target_id] if first_target_id else []
        else:
            return [args]
    recipients: list[argparse.Namespace] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for target_id in target_ids:
        target = find_push_target(args, target_id)
        if target is None:
            continue
        scoped = args_for_push_target(args, target)
        key = channel_route_key(scoped)
        if key in seen:
            continue
        seen.add(key)
        recipients.append(scoped)
    return recipients


def args_for_push_target(args: argparse.Namespace, target: PushTarget) -> argparse.Namespace:
    if target.channel == "wechat":
        cloned = args_for_configured_route(args, route_channel="wechat", route_profile_id=target.profile_id)
        if target.receive_id:
            cloned.wechat_bot_target_user_id = target.receive_id
        if target.default_author_id:
            cloned.default_author_id = target.default_author_id
        if target.default_tid:
            cloned.default_tid = target.default_tid
        return cloned
    cloned = args_for_configured_route(
        args,
        route_channel="feishu",
        route_profile_id=target.profile_id,
        receive_id=target.receive_id,
        receive_id_type=target.id_type,
    )
    if target.default_author_id:
        cloned.default_author_id = target.default_author_id
    if target.default_tid:
        cloned.default_tid = target.default_tid
    return cloned


def watch_mode(args: argparse.Namespace) -> str:
    value = str(getattr(args, "watch_mode", "") or os.getenv("NGA_WATCH_MODE", "author")).strip().lower().replace("-", "_")
    return value if value in {"author", "thread_author", "both"} else "author"


def default_author_target(args: argparse.Namespace) -> WatchTarget:
    return watch_author_targets(args)[0]


def default_thread_target(args: argparse.Namespace) -> WatchTarget:
    return preset_thread_targets(args)[0]


def watch_author_targets_for_watch(args: argparse.Namespace) -> list[WatchTarget]:
    rules = [rule for rule in configured_listen_rules(args) if rule.mode == "author"]
    if not rules:
        mode = watch_mode(args)
        return watch_author_targets(args) if mode in {"author", "both"} else []
    labels_by_id: dict[str, str] = {}
    for rule in rules:
        labels_by_id.setdefault(rule.author_id, rule.label)
    return [WatchTarget(author_id, label) for author_id, label in labels_by_id.items()]


def thread_author_watches_for_watch(args: argparse.Namespace) -> list[ThreadAuthorWatch]:
    rules = [rule for rule in configured_listen_rules(args) if rule.mode == "thread_author"]
    if not rules:
        mode = watch_mode(args)
        return thread_author_watches(args) if mode in {"thread_author", "both"} else []
    watches: list[ThreadAuthorWatch] = []
    seen: set[str] = set()
    for rule in rules:
        key = f"{rule.tid}:{rule.author_id}"
        if key in seen:
            continue
        seen.add(key)
        watches.append(ThreadAuthorWatch(rule.tid, rule.author_id, rule.label))
    return watches


def resolve_target_alias(token: str, targets: list[WatchTarget], prefix: str) -> str:
    text = str(token or "").strip()
    match = re.fullmatch(rf"{re.escape(prefix)}(\d+)", text, flags=re.I)
    if not match:
        return text
    index = int(match.group(1)) - 1
    if 0 <= index < len(targets):
        return targets[index].id
    return text


def add_post_source(post: NgaPost, source_type: str, target: WatchTarget) -> NgaPost:
    return NgaPost(
        key=post.key,
        subject=post.subject,
        content=post.content,
        url=post.url,
        post_time=post.post_time,
        author=post.author,
        author_id=post.author_id,
        floor=post.floor,
        image_urls=post.image_urls,
        source_type=source_type,
        source_id=target.id,
        source_label=target.label,
        canonical_key=post.canonical_key or post.key,
    )


def add_thread_author_source(post: NgaPost, watch: ThreadAuthorWatch) -> NgaPost:
    return NgaPost(
        key=f"thread_author:{watch.tid}:{watch.author_id}:{post.key}",
        subject=post.subject,
        content=post.content,
        url=post.url,
        post_time=post.post_time,
        author=post.author,
        author_id=post.author_id,
        floor=post.floor,
        image_urls=post.image_urls,
        source_type="thread_author",
        source_id=watch.key,
        source_label=watch.label,
        canonical_key=post.canonical_key or post.key,
    )


def bot_channel(args: argparse.Namespace) -> str:
    channel = str(getattr(args, "bot_channel", "") or os.getenv("NGA_BOT_CHANNEL", "feishu")).strip().lower()
    return channel if channel in {"feishu", "wechat"} else "feishu"


def is_wechat_channel(args: argparse.Namespace) -> bool:
    return bot_channel(args) == "wechat"


def wechat_client_for_args(args: argparse.Namespace) -> wechat_bot.WeChatBotClient:
    config = wechat_bot.WeChatBotConfig.from_namespace(args)
    key = (str(config.state_dir.resolve()), config.token)
    client = _WECHAT_CLIENTS.get(key)
    if client is None:
        client = wechat_bot.WeChatBotClient(config)
        _WECHAT_CLIENTS[key] = client
    return client


def find_feishu_profile(args: argparse.Namespace, profile_id: str) -> FeishuBotProfile | None:
    target = str(profile_id or "").strip()
    profiles = feishu_bot_profiles(args)
    if not target and profiles:
        return profiles[0]
    for profile in profiles:
        if target in {profile.id, profile.label, profile.app_id}:
            return profile
    return None


def find_wechat_profile(args: argparse.Namespace, profile_id: str) -> WeChatBotProfile | None:
    target = str(profile_id or "").strip()
    profiles = wechat_bot_profiles(args)
    if not target and profiles:
        return profiles[0]
    for profile in profiles:
        if target in {profile.id, profile.label, profile.account_id, profile.target_user_id}:
            return profile
    return None


def args_for_configured_route(
    args: argparse.Namespace,
    *,
    route_channel: str = "",
    route_profile_id: str = "",
    receive_id: str = "",
    receive_id_type: str = "",
    legacy_feishu_app_id: str = "",
    legacy_feishu_app_secret: str = "",
) -> argparse.Namespace:
    channel = str(route_channel or "").strip().lower()
    if channel == "wechat":
        profile = find_wechat_profile(args, route_profile_id)
        cloned = copy.copy(args)
        cloned.bot_channel = "wechat"
        cloned.wechat_poll = True
        if profile:
            cloned.wechat_bot_token = profile.token
            cloned.wechat_bot_base_url = profile.base_url
            cloned.wechat_bot_cdn_base_url = profile.cdn_base_url
            cloned.wechat_bot_target_user_id = profile.target_user_id
            cloned.wechat_bot_allowed_user_ids = profile.allowed_user_ids
            cloned.wechat_bot_poll_timeout_ms = profile.poll_timeout_ms
            cloned.wechat_bot_route_tag = profile.route_tag
            cloned.wechat_bot_account_id = profile.account_id
        return cloned
    if channel == "feishu" or route_profile_id or receive_id or legacy_feishu_app_id or legacy_feishu_app_secret:
        profile = find_feishu_profile(args, route_profile_id)
        cloned = copy.copy(args)
        cloned.bot_channel = "feishu"
        if profile:
            cloned.feishu_app_id = profile.app_id
            cloned.feishu_app_secret = profile.app_secret
            cloned.feishu_id_type = receive_id_type or profile.id_type or "chat_id"
        if legacy_feishu_app_id:
            cloned.feishu_app_id = legacy_feishu_app_id
        if legacy_feishu_app_secret:
            cloned.feishu_app_secret = legacy_feishu_app_secret
        if receive_id:
            cloned.feishu_receive_id = receive_id
        if receive_id_type:
            cloned.feishu_id_type = receive_id_type
        return cloned
    return args


def args_for_wechat_user(args: argparse.Namespace, user_id: str) -> argparse.Namespace:
    cloned = copy.copy(args)
    cloned.wechat_bot_target_user_id = user_id
    target = push_target_for_channel_receive(args, "wechat", user_id)
    if target:
        if target.default_author_id:
            cloned.default_author_id = target.default_author_id
        if target.default_tid:
            cloned.default_tid = target.default_tid
    return cloned


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


def fetch_nga_page(
    author_id: str,
    page: int,
    cookie: str,
    timeout: int,
    request_min_interval: float = DEFAULT_NGA_REQUEST_MIN_INTERVAL,
    cache_ttl: float = DEFAULT_NGA_CACHE_TTL,
) -> dict[str, Any]:
    params = {
        "searchpost": "1",
        "page": str(page),
        "__output": "8",
    }
    if author_id and author_id != "0":
        params["authorid"] = author_id
    query = urllib.parse.urlencode(params)
    referer = "https://bbs.nga.cn/"
    if author_id and author_id != "0":
        referer = f"https://bbs.nga.cn/nuke.php?func=ucp&uid={urllib.parse.quote(str(author_id), safe='')}"
    return fetch_nga_json(f"{NGA_ENDPOINT}?{query}", cookie, timeout, f"用户回复第 {page} 页", request_min_interval, cache_ttl, referer)


def fetch_nga_thread_page(
    tid: str,
    page: int,
    cookie: str,
    timeout: int,
    request_min_interval: float = DEFAULT_NGA_REQUEST_MIN_INTERVAL,
    cache_ttl: float = DEFAULT_NGA_CACHE_TTL,
) -> dict[str, Any]:
    query = urllib.parse.urlencode({"tid": tid, "page": str(page), "__output": "8"})
    referer = f"https://bbs.nga.cn/read.php?tid={urllib.parse.quote(str(tid), safe='')}"
    return fetch_nga_json(f"{NGA_READ_ENDPOINT}?{query}", cookie, timeout, f"帖子 {tid} 第 {page} 页", request_min_interval, cache_ttl, referer)


def nga_json_cache_key(url: str, cookie: str) -> str:
    cookie_hash = hashlib.sha256(cookie.encode("utf-8", errors="ignore")).hexdigest()[:16]
    return f"{cookie_hash}:{url}"


def fetch_nga_json(
    url: str,
    cookie: str,
    timeout: int,
    label: str,
    request_min_interval: float = DEFAULT_NGA_REQUEST_MIN_INTERVAL,
    cache_ttl: float = DEFAULT_NGA_CACHE_TTL,
    referer: str = "https://bbs.nga.cn/",
) -> dict[str, Any]:
    global _NGA_LAST_REQUEST_AT
    request_min_interval = max(0.0, float(request_min_interval))
    cache_ttl = max(0.0, float(cache_ttl))
    cache_key = nga_json_cache_key(url, cookie)
    with _NGA_REQUEST_LOCK:
        now = time.monotonic()
        cached = _NGA_JSON_CACHE.get(cache_key)
        if cached and cache_ttl > 0 and now - cached[0] <= cache_ttl:
            return copy.deepcopy(cached[1])
        if cache_ttl > 0:
            expired_before = now - cache_ttl
            for key, (cached_at, _) in list(_NGA_JSON_CACHE.items()):
                if cached_at < expired_before:
                    _NGA_JSON_CACHE.pop(key, None)
        wait_for = request_min_interval - (now - _NGA_LAST_REQUEST_AT)
        if wait_for > 0:
            time.sleep(wait_for)
        try:
            payload = fetch_nga_json_uncached(url, cookie, timeout, label, referer)
        finally:
            _NGA_LAST_REQUEST_AT = time.monotonic()
        if cache_ttl > 0:
            _NGA_JSON_CACHE[cache_key] = (_NGA_LAST_REQUEST_AT, copy.deepcopy(payload))
        return payload


def parse_nga_json_text(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text, strict=False)
    except json.JSONDecodeError:
        stripped = text.strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
        # NGA occasionally returns JavaScript-ish JSON inside text/javascript:
        # single-quote escapes, \xNN escapes, or lone backslashes in post text.
        stripped = re.sub(r"\\x([0-9A-Fa-f]{2})", lambda match: chr(int(match.group(1), 16)), stripped)
        stripped = stripped.replace("\\'", "'")
        stripped = re.sub(r'\\(?!["\\/bfnrtu])', r"\\\\", stripped)
        value = json.loads(stripped, strict=False)
    if not isinstance(value, dict):
        raise json.JSONDecodeError("NGA response root is not an object", text, 0)
    return value


def fetch_nga_json_uncached(url: str, cookie: str, timeout: int, label: str, referer: str = "https://bbs.nga.cn/") -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Cookie": cookie,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": referer or "https://bbs.nga.cn/",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
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
        payload = parse_nga_json_text(text)
    except json.JSONDecodeError as exc:
        preview = re.sub(r"\s+", " ", text[:300]).strip()
        if not preview:
            preview = "<空响应>"
        message = (
            f"NGA 在 {label} 返回的不是 JSON："
            f"状态码={status}，内容类型={content_type}，解析错误={exc.msg}，响应预览={preview}"
        )
        if status in NGA_TEMPORARY_STATUS_CODES:
            raise NgaTemporaryUnavailable(message, status_code=status) from exc
        raise RuntimeError(message) from exc
    if status >= 400:
        message = f"NGA 在 {label} 返回 HTTP 状态码={status}，内容类型={content_type}"
        if status in NGA_TEMPORARY_STATUS_CODES:
            raise NgaTemporaryUnavailable(message, status_code=status)
        raise RuntimeError(message)
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
        canonical_key=key,
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


def post_sort_key(post: NgaPost) -> tuple[float, str]:
    parsed = parse_post_time(post.post_time)
    timestamp = time.mktime(parsed) if parsed is not None else 0.0
    return timestamp, post.key


def post_identity_key(post: NgaPost) -> str:
    return str(post.canonical_key or post.key or "").strip()


def post_seen_keys(post: NgaPost) -> set[str]:
    keys = {str(post.key or "").strip(), post_identity_key(post)}
    return {key for key in keys if key}


def mark_post_seen(seen: set[str], post: NgaPost) -> None:
    seen.update(post_seen_keys(post))


def is_post_seen(seen: set[str], post: NgaPost) -> bool:
    return bool(post_seen_keys(post) & seen)


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
    source_line = ""
    if post.source_id:
        source_name = post.source_label or post.source_id
        source_kind = "user" if post.source_type == "author" else post.source_type or "target"
        source_line = f"Watch: {source_kind} {source_name} ({post.source_id})"
    lines = [
        f"{new_reply_title(post)}: {post.subject}",
        f"Time: {post.post_time or 'unknown'}",
        byline,
    ]
    if source_line:
        lines.append(source_line)
    lines.extend([f"Link: {post.url}", "", friendly_post_content(post.content, quote_limit=700, reply_limit=1200)[:1800]])
    if post.image_urls:
        lines.extend(["", "Images:", *[f"- {url}" for url in post.image_urls]])
    return "\n".join(lines)


def feishu_history_text(posts: list[NgaPost], title: str) -> str:
    lines = [title]
    for idx, post in enumerate(posts, 1):
        excerpt = re.sub(r"\s+", " ", friendly_post_content(post.content, quote_limit=180, reply_limit=260)).strip()[:420]
        lines.append(f"\n{idx}. {post.subject}")
        meta = post.post_time or "unknown"
        if post.author or post.author_id:
            meta += f" | {post.author or post.author_id}"
        if post.floor:
            meta += f" | #{post.floor}"
        if post.source_id:
            meta += f" | watch {post.source_label or post.source_id}"
        lines.append(f"{meta} {post.url}")
        lines.append(excerpt)
        if post.image_urls:
            lines.append("Images: " + ", ".join(post.image_urls[:5]))
    return "\n".join(lines)


def wechat_posts_text(posts: list[NgaPost], title: str) -> str:
    lines = [title]
    for idx, post in enumerate(posts, 1):
        if idx > 1:
            lines.extend(["", "-" * 24])
        lines.append(f"\n{idx}. {post.subject}")
        meta = post.post_time or "unknown"
        if post.author or post.author_id:
            meta += f" | {post.author or post.author_id}"
        if post.floor:
            meta += f" | #{post.floor}"
        if post.source_id:
            meta += f" | watch {post.source_label or post.source_id}"
        lines.append(meta)
        lines.append(post.url)
        lines.append("")
        lines.append(friendly_post_content(post.content, quote_limit=900, reply_limit=1600))
        if post.image_urls:
            lines.extend(["", "图片：", *[f"- {url}" for url in post.image_urls[:6]]])
    return "\n".join(lines).strip()


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
        if post.source_id:
            meta.append(f"watch: {post.source_type or 'target'} {post.source_label or post.source_id} ({post.source_id})")
        if post.image_urls:
            meta.extend(f"image: {url}" for url in post.image_urls)
        chunks.append("\n".join(meta))
        chunks.append(friendly_post_content(post.content, quote_limit=1200, reply_limit=3000))
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


def friendly_post_content(value: str, *, quote_limit: int = 600, reply_limit: int = 1200) -> str:
    quoted = split_quoted_reply(value)
    if not quoted:
        if QUOTE_END_MARKER in value:
            quote_body, reply_body = value.split(QUOTE_END_MARKER, 1)
            lines: list[str] = []
            if quote_body.strip():
                lines.extend(["被回复内容：", truncate_text(display_text(quote_body), quote_limit)])
            if reply_body.strip():
                if lines:
                    lines.append("")
                lines.extend(["本次回复：", truncate_text(display_text(reply_body), reply_limit)])
            if lines:
                return "\n".join(lines).strip()
        return display_text(value)
    quote_header, quote_body, reply_body = quoted
    lines: list[str] = ["被回复内容："]
    quote_parts = [quote_header]
    if quote_body:
        quote_parts.append(quote_body)
    lines.append(truncate_text(display_text("\n".join(part for part in quote_parts if part)), quote_limit))
    if reply_body:
        lines.extend(["", "本次回复：", truncate_text(display_text(reply_body), reply_limit)])
    return "\n".join(lines).strip()


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


def post_card_element(post: NgaPost, image_keys_by_url: dict[str, str] | None = None) -> list[dict[str, Any]]:
    title = lark_md_escape(post.subject)
    time_text = lark_md_escape(post.post_time or "unknown")
    author_text = lark_md_escape(post.author or post.author_id or "unknown")
    floor_text = f" | #{lark_md_escape(post.floor)}" if post.floor else ""
    source_text = ""
    if post.source_id:
        source_name = post.source_label or post.source_id
        source_kind = "user" if post.source_type == "author" else post.source_type or "target"
        source_text = f"\nWatch: {lark_md_escape(source_kind)} {lark_md_escape(source_name)} ({lark_md_escape(post.source_id)})"
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**{title}**\n{time_text} | {author_text}{floor_text}{source_text}",
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
        image_keys_by_url = image_keys_by_url or {}
        fallback_lines: list[str] = []
        for idx, url in enumerate(post.image_urls[:6], 1):
            image_key = str(image_keys_by_url.get(url) or "").strip()
            if image_key:
                elements.append(
                    {
                        "tag": "img",
                        "img_key": image_key,
                        "alt": {"tag": "plain_text", "content": f"NGA image {idx}"},
                    }
                )
            else:
                fallback_lines.append(f"[image {idx}]({lark_md_escape(url)})")
        if fallback_lines:
            elements.append(
                {
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**Images**\n{chr(10).join(fallback_lines)}"},
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


def feishu_posts_card(
    posts: list[NgaPost],
    title: str,
    mention_user_id: str = "",
    image_keys_by_url: dict[str, str] | None = None,
) -> dict[str, Any]:
    elements: list[dict[str, Any]] = mention_card_elements(mention_user_id)
    for idx, post in enumerate(posts[:20]):
        if idx:
            elements.append({"tag": "hr"})
        elements.extend(post_card_element(post, image_keys_by_url))
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


def feishu_deferred_summary_card(
    posts: list[NgaPost],
    total_count: int,
    mention_user_id: str = "",
    image_keys_by_url: dict[str, str] | None = None,
) -> dict[str, Any]:
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
        elements.extend(post_card_element(post, image_keys_by_url))
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
            source_type=str(value.get("source_type") or ""),
            source_id=str(value.get("source_id") or ""),
            source_label=str(value.get("source_label") or ""),
            canonical_key=str(value.get("canonical_key") or value.get("key") or ""),
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


def state_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    return []


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
    *,
    args: argparse.Namespace | None = None,
) -> None:
    if message_format == "text":
        msg_type = "text"
        content = json.dumps({"text": feishu_message_text(post)}, ensure_ascii=False)
    else:
        msg_type = "interactive"
        image_keys_by_url = feishu_image_keys_for_posts(args, app_id, app_secret, [post])
        title = new_reply_title(post)
        content = json.dumps(feishu_posts_card([post], title, mention_user_id, image_keys_by_url), ensure_ascii=False)
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


def multipart_body(
    fields: dict[str, str],
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    file_content_type: str = "text/plain; charset=utf-8",
) -> tuple[bytes, str]:
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
            f"Content-Type: {file_content_type or 'application/octet-stream'}\r\n\r\n"
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


def image_content_type_for_extension(ext: str) -> str:
    ext = str(ext or "").lower()
    if ext in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if ext == ".gif":
        return "image/gif"
    if ext == ".webp":
        return "image/webp"
    if ext == ".bmp":
        return "image/bmp"
    if ext in {".tif", ".tiff"}:
        return "image/tiff"
    if ext == ".ico":
        return "image/x-icon"
    return "image/png"


def upload_feishu_image(token: str, file_name: str, data: bytes, content_type: str, timeout: int) -> str:
    body, multipart_content_type = multipart_body(
        {"image_type": "message"},
        "image",
        file_name,
        data,
        content_type or "application/octet-stream",
    )
    req = urllib.request.Request(
        f"{FEISHU_API}/im/v1/images",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": multipart_content_type},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Feishu image upload failed: HTTP {exc.code}: {detail}") from exc
    if result.get("code") != 0:
        raise RuntimeError(f"Feishu image upload failed: {result}")
    image_key = result.get("data", {}).get("image_key")
    if not image_key:
        raise RuntimeError(f"Feishu image upload response missing image_key: {result}")
    return str(image_key)


def feishu_image_cache_path(args: argparse.Namespace) -> Path:
    return Path(getattr(args, "state_path", ".nga_seen.json")).expanduser().resolve().with_name("feishu_image_cache.json")


def read_feishu_image_cache(path: Path) -> dict[str, Any]:
    try:
        data = read_json(path, {})
    except Exception:
        return {"images": {}}
    if not isinstance(data, dict):
        return {"images": {}}
    images = data.get("images")
    if not isinstance(images, dict):
        data["images"] = {}
    return data


def write_feishu_image_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cache["updated_at"] = int(time.time())
    images = cache.get("images")
    if isinstance(images, dict) and len(images) > 500:
        ordered = sorted(
            images.items(),
            key=lambda item: int(item[1].get("updated_at") or 0) if isinstance(item[1], dict) else 0,
            reverse=True,
        )
        cache["images"] = dict(ordered[:500])
    write_json(path, cache)


def download_nga_image_bytes(url: str, cookie: str, timeout: int) -> tuple[bytes, str]:
    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Referer": "https://bbs.nga.cn/",
        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    }
    if cookie:
        headers["Cookie"] = cookie

    def fetch(candidate_url: str) -> tuple[bytes, str]:
        req = urllib.request.Request(candidate_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_length = str(resp.headers.get("Content-Length") or "").strip()
            if content_length.isdigit() and int(content_length) > FEISHU_IMAGE_MAX_BYTES:
                raise RuntimeError("image is larger than Feishu 10MB limit")
            data = resp.read(FEISHU_IMAGE_MAX_BYTES + 1)
            content_type = str(resp.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        return data, content_type

    candidates = [url]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.netloc.lower().endswith("nga.178.com"):
        candidates.append(urllib.parse.urlunparse(parsed._replace(scheme="http")))

    last_error: Exception | None = None
    for candidate_url in candidates:
        try:
            data, content_type = fetch(candidate_url)
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if not (exc.code == 567 and candidate_url != candidates[-1]):
                raise
        except Exception as exc:
            last_error = exc
            if candidate_url == candidates[-1]:
                raise
    else:
        raise RuntimeError(f"image download failed: {last_error}")

    if not data:
        raise RuntimeError("image response is empty")
    if len(data) > FEISHU_IMAGE_MAX_BYTES:
        raise RuntimeError("image is larger than Feishu 10MB limit")
    return data, content_type


def card_image_urls(posts: list[NgaPost], limit: int) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for post in posts[:20]:
        for url in post.image_urls[:6]:
            normalized = str(url or "").strip()
            if normalized and normalized not in seen:
                seen.add(normalized)
                urls.append(normalized)
                if len(urls) >= limit:
                    return urls
    return urls


def feishu_image_keys_for_posts(args: argparse.Namespace | None, app_id: str, app_secret: str, posts: list[NgaPost]) -> dict[str, str]:
    if not args or not bool(getattr(args, "feishu_card_images", True)):
        return {}
    limit = max(0, int(getattr(args, "feishu_card_image_limit", DEFAULT_FEISHU_CARD_IMAGE_LIMIT) or 0))
    urls = card_image_urls(posts, limit)
    if not urls:
        return {}
    token = get_feishu_tenant_access_token(app_id, app_secret, int(getattr(args, "timeout", 20) or 20))
    timeout = max(3, min(int(getattr(args, "timeout", 20) or 20), 20))
    cookie = getattr(args, "cookie", "") or os.getenv("NGA_COOKIE", "")
    cache_path = feishu_image_cache_path(args)
    result: dict[str, str] = {}
    with _FEISHU_IMAGE_CACHE_LOCK:
        cache = read_feishu_image_cache(cache_path)
        images = cache.setdefault("images", {})
        changed = False
        for url in urls:
            cached = images.get(url) if isinstance(images, dict) else None
            if isinstance(cached, dict) and str(cached.get("image_key") or "").strip():
                result[url] = str(cached["image_key"])
                cached["last_used_at"] = int(time.time())
                changed = True
                continue
            try:
                data, content_type = download_nga_image_bytes(url, cookie, timeout)
                ext = image_extension(data, content_type)
                upload_content_type = content_type if content_type.startswith("image/") else image_content_type_for_extension(ext)
                file_name = f"nga_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:12]}{ext}"
                image_key = upload_feishu_image(token, file_name, data, upload_content_type, timeout)
                result[url] = image_key
                images[url] = {
                    "image_key": image_key,
                    "updated_at": int(time.time()),
                    "size": len(data),
                }
                changed = True
            except Exception as exc:
                print(f"Feishu card image inline failed for {url}: {exc}", file=sys.stderr)
        if changed:
            try:
                write_feishu_image_cache(cache_path, cache)
            except Exception as exc:
                print(f"Feishu card image cache write failed: {exc}", file=sys.stderr)
    return result


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
        push_feishu_app_posts(app_id, app_secret, receive_id, receive_id_type, [post], title, args.timeout, "text", args=args)
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


def push_channel_raw_text(args: argparse.Namespace, text: str) -> None:
    if is_wechat_channel(args):
        wechat_client_for_args(args).send_text_to_target(text)
        return
    push_feishu_raw_text(args, text)


def push_channel_text(args: argparse.Namespace, title: str, text: str) -> None:
    if is_wechat_channel(args):
        content = f"{title}\n\n{text}" if title else text
        wechat_client_for_args(args).send_text_to_target(content)
        return
    push_feishu_text(args, title, text)


def save_wechat_outgoing_file(args: argparse.Namespace, file_name: str, text: str) -> Path:
    config = wechat_client_for_args(args).config
    safe_name = wechat_bot.safe_segment(Path(file_name).name or f"nga_file_{int(time.time())}.txt")
    if not Path(safe_name).suffix:
        safe_name += ".txt"
    out_dir = config.state_dir / "outgoing_files"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / safe_name
    if path.exists():
        stem = path.stem
        suffix = path.suffix
        path = out_dir / f"{stem}_{int(time.time())}{suffix}"
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def push_channel_file(args: argparse.Namespace, file_name: str, text: str) -> None:
    if is_wechat_channel(args):
        path = save_wechat_outgoing_file(args, file_name, text)
        caption = "\n".join([file_name, f"本地文件: {path}"])
        try:
            wechat_client_for_args(args).send_file_to_target(path, file_name=file_name, caption=caption)
            return
        except Exception as exc:
            print(f"微信文件发送失败，回退为文本分段: {exc}", file=sys.stderr)
            push_channel_raw_text(
                args,
                "\n".join(
                    [
                        file_name,
                        f"本地文件: {path}",
                        f"微信文件发送失败，已回退为文本消息: {exc}",
                        "",
                        text,
                    ]
                ),
            )
        return
    push_feishu_file(args, file_name, text)


def push_channel_posts(args: argparse.Namespace, posts: list[NgaPost], title: str, mention_user_id: str = "") -> None:
    if is_wechat_channel(args):
        push_channel_raw_text(args, wechat_posts_text(posts, title))
        return
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    if not (app_id and app_secret and receive_id):
        for post in posts:
            push_to_feishu(args, post, mention_user_id)
        return
    push_feishu_app_posts(app_id, app_secret, receive_id, receive_id_type, posts, title, args.timeout, args.message_format, mention_user_id, args=args)


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
    if is_wechat_channel(args):
        prefix = f"{title}\n\n" if title else ""
        push_channel_raw_text(args, prefix + markdown)
        return
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
    target = getattr(args, "wechat_bot_target_user_id", "") if is_wechat_channel(args) else getattr(args, "feishu_receive_id", "")
    key = (str(config.work_dir.resolve()), f"{bot_channel(args)}:{target or ''}")
    manager = _AI_MANAGERS.get(key)
    if manager is not None:
        manager.config = config
        return manager

    def send_text(text: str) -> None:
        push_channel_text(args, "AI analysis", text)

    def send_file(file_name: str, text: str) -> None:
        push_channel_file(args, file_name, text)

    def send_result(result: ai_analysis.AIResult) -> None:
        push_ai_result(args, result)

    manager = ai_analysis.AIManager(config, send_text=send_text, send_file=send_file, send_result=send_result)
    _AI_MANAGERS[key] = manager
    return manager


def ai_manager_for_recipients(args: argparse.Namespace, recipients: list[argparse.Namespace], scope: str) -> ai_analysis.AIManager:
    config = ai_analysis.AIConfig.from_namespace(args)
    route_keys = sorted(":".join(channel_route_key(recipient)) for recipient in recipients)
    digest = hashlib.sha1("\n".join(route_keys).encode("utf-8")).hexdigest()[:12] if route_keys else "default"
    key = (str(config.work_dir.resolve()), f"{scope}:{digest}")
    manager = _AI_MANAGERS.get(key)
    if manager is not None:
        manager.config = config
        return manager

    def send_text(text: str) -> None:
        for recipient in recipients:
            push_channel_text(recipient, "AI analysis", text)

    def send_file(file_name: str, text: str) -> None:
        for recipient in recipients:
            push_channel_file(recipient, file_name, text)

    def send_result(result: ai_analysis.AIResult) -> None:
        for recipient in recipients:
            push_ai_result(recipient, result)

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
    key = (str(config.work_dir.resolve()), "global")
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
                push_channel_text(args, "AI queue full", "AI task queue is full, please retry later.")
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
        if is_wechat_channel(args):
            push_channel_raw_text(args, ai_mode_text(manager))
            return
        try:
            push_feishu_card(args, ai_mode_card(manager))
        except Exception as exc:
            print(f"AI mode card send failed, falling back to text: {exc}", file=sys.stderr)
            push_channel_raw_text(args, ai_mode_text(manager))
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
                    push_channel_raw_text(args, summary + "\n\nFull result uploaded as `ai_command_result.md`.")
                    push_channel_file(args, "ai_command_result.md", response)
                except Exception as exc:
                    print(f"AI 长结果上传失败，改为截断发送: {exc}", file=sys.stderr)
                    push_channel_raw_text(args, summary)
                return
            response = summary
        push_channel_raw_text(args, response)


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
                    push_channel_text(args, "AI command failed", str(exc))
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
                    push_channel_text(args, "AI conversation failed", str(exc))
            except Exception as nested:
                print(f"发送 AI 错误消息失败: {nested}", file=sys.stderr)

    enqueue_ai_feishu_job(args, label, queued_job)


def after_posts_pushed_for_ai(args: argparse.Namespace, posts: list[NgaPost]) -> None:
    if configured_listen_rules(args):
        grouped: dict[str, tuple[list[argparse.Namespace], list[NgaPost]]] = {}
        for post in posts:
            recipients = route_args_for_post(args, post)
            route_keys = sorted(":".join(channel_route_key(recipient)) for recipient in recipients)
            key = hashlib.sha1("\n".join(route_keys).encode("utf-8")).hexdigest()[:12] if route_keys else "default"
            if key not in grouped:
                grouped[key] = (recipients, [])
            grouped[key][1].append(post)
        for recipients, group_posts in grouped.values():
            try:
                ai_manager_for_recipients(args, recipients, "auto").maybe_auto_analyze_posts(group_posts)
            except Exception as exc:
                print(f"AI 新帖保存/分析失败: {exc}", file=sys.stderr)
        return
    grouped: dict[tuple[str, str, str, str, str], tuple[argparse.Namespace, list[NgaPost]]] = {}
    for post in posts:
        routed_args = args_for_thread_author_route(args, post)
        key = channel_route_key(routed_args)
        if key not in grouped:
            grouped[key] = (routed_args, [])
        grouped[key][1].append(post)
    for routed_args, group_posts in grouped.values():
        try:
            ai_manager_for_args(routed_args).maybe_auto_analyze_posts(group_posts)
        except Exception as exc:
            print(f"AI 新帖保存/分析失败: {exc}", file=sys.stderr)


def save_posts_for_ai_history(args: argparse.Namespace, posts: list[NgaPost]) -> None:
    if not posts:
        return
    try:
        manager = ai_manager_for_args(args)
        for post in posts:
            manager.save_post_event(post, force=True)
    except Exception as exc:
        print(f"AI 初始化历史保存失败: {exc}", file=sys.stderr)


def ai_source_history_needs_backfill(args: argparse.Namespace, target: WatchTarget) -> bool:
    try:
        config = ai_analysis.AIConfig.from_namespace(args)
        key = f"author_{ai_analysis.safe_key(target.id)}"
        history_path = config.work_dir / "events" / "by_source" / f"{key}.jsonl"
        if not history_path.exists() or history_path.stat().st_size <= 0:
            return True
        index = ai_analysis.read_json(config.work_dir / "events" / "source_index.json", {})
        sources = index.get("sources") if isinstance(index, dict) else {}
        item = sources.get(key) if isinstance(sources, dict) else None
        if not isinstance(item, dict):
            return True
        label = target.label.strip()
        if not label:
            return False
        aliases = {str(alias).strip() for alias in item.get("aliases") or [] if str(alias).strip()}
        return label != str(item.get("label") or "").strip() and label not in aliases
    except Exception:
        return False


def collect_author_seed_posts_for_ai(args: argparse.Namespace, author_id: str, label: str = "") -> list[NgaPost]:
    author_id = str(author_id or "").strip()
    if not author_id:
        return []
    try:
        target = WatchTarget(author_id, str(label or "").strip())
        return [add_post_source(post, "author", target) for post in collect_posts_for_author_with_retries(args, author_id)]
    except Exception as exc:
        print(f"AI 历史初始化拉取用户 {author_id} 回复失败: {exc}", file=sys.stderr)
        return []


def maybe_run_ai_schedule(args: argparse.Namespace) -> None:
    try:
        recipients = ai_schedule_recipient_args(args)
        if not recipients:
            return
        if len(recipients) == 1 and recipients[0] is args:
            ai_manager_for_args(args).maybe_scheduled_analysis()
        else:
            ai_manager_for_recipients(args, recipients, "schedule").maybe_scheduled_analysis()
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
    *,
    args: argparse.Namespace | None = None,
) -> None:
    if message_format == "text":
        msg_type = "text"
        content = json.dumps({"text": feishu_history_text(posts, title)}, ensure_ascii=False)
    else:
        msg_type = "interactive"
        image_keys_by_url = feishu_image_keys_for_posts(args, app_id, app_secret, posts)
        content = json.dumps(feishu_posts_card(posts, title, mention_user_id, image_keys_by_url), ensure_ascii=False)
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


def normalize_feishu_chat_item(chat: dict[str, Any]) -> dict[str, Any]:
    return {
        "chat_id": str(chat.get("chat_id") or chat.get("id") or "").strip(),
        "name": str(chat.get("name") or chat.get("title") or "").strip(),
        "chat_type": str(chat.get("chat_type") or "").strip(),
        "description": str(chat.get("description") or "").strip(),
    }


def merge_feishu_chats(*chat_lists: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chats in chat_lists:
        for raw_chat in chats:
            if not isinstance(raw_chat, dict):
                continue
            chat = normalize_feishu_chat_item(raw_chat)
            chat_id = chat["chat_id"]
            if not chat_id or chat_id in seen:
                continue
            seen.add(chat_id)
            merged.append(chat)
    return merged


def list_feishu_chats(app_id: str, app_secret: str, timeout: int) -> list[dict[str, Any]]:
    chats: list[dict[str, Any]] = []
    page_token = ""
    for _ in range(20):
        query = {"page_size": "100"}
        if page_token:
            query["page_token"] = page_token
        result = feishu_app_request(
            app_id,
            app_secret,
            f"/im/v1/chats?{urllib.parse.urlencode(query)}",
            timeout=timeout,
        )
        if result.get("code") != 0:
            raise RuntimeError(f"飞书群组查询失败：{result}")
        data = result.get("data", {}) if isinstance(result.get("data"), dict) else {}
        chats.extend(item for item in data.get("items", []) if isinstance(item, dict))
        if not data.get("has_more"):
            break
        page_token = str(data.get("page_token") or "").strip()
        if not page_token:
            break
    return merge_feishu_chats(chats)


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


def parse_bot_command(
    text: str,
    default_author_id: str,
    default_tid: str,
    author_targets: list[WatchTarget] | None = None,
    thread_targets: list[WatchTarget] | None = None,
    effective_author_id: str = "",
    effective_tid: str = "",
) -> BotCommand | None:
    compact = " ".join(text.split())
    author_targets = author_targets or parse_target_list("", default_author_id)
    thread_targets = thread_targets or parse_target_list("", default_tid)
    effective_author_id = str(effective_author_id or "").strip() or (author_targets[0].id if author_targets else default_author_id)
    effective_tid = str(effective_tid or "").strip() or (thread_targets[0].id if thread_targets else default_tid)
    if re.search(r"(?:^|\s)/start(?:\s|$)", compact):
        return BotCommand(action="start")
    if re.search(r"(?:^|\s)/setting(?:s)?(?:\s|$)", compact):
        return BotCommand(action="setting")

    legacy = re.search(r"(?:^|\s)/history(?:\s+(\d{1,3}))?(?:\s|$)", compact)
    if legacy:
        return BotCommand(
            action="history",
            target_type="reply",
            target_id=effective_author_id,
            count=clamp_count(legacy.group(1), DEFAULT_REPLY_COUNT, 50),
        )

    match = re.search(r"(?:^|\s)/(history_r|pack_r|history_t|pack_t)(?:\s+([A-Za-z]?\d+))?(?:\s+(\d{1,4}))?(?:\s|$)", compact)
    if not match:
        return None

    name, raw_target, raw_count = match.groups()
    target_type = "thread" if name.endswith("_t") else "reply"
    if target_type == "thread":
        target = resolve_target_alias(raw_target or "", thread_targets, "t") or effective_tid
    else:
        target = resolve_target_alias(raw_target or "", author_targets, "u") or effective_author_id
    count = clamp_count(raw_count, default_command_count(name), 500 if name.startswith("pack_") else 100)

    # Compatibility for the older "/pack_r <default tid> <count>" spelling.
    if name == "pack_r" and target == default_tid:
        target_type = "thread"

    action = "pack" if name.startswith("pack_") else "history"
    return BotCommand(action=action, target_type=target_type, target_id=target, count=count)


def bot_command_from_form(
    form: dict[str, Any],
    default_author_id: str,
    default_tid: str,
    author_targets: list[WatchTarget] | None = None,
    thread_targets: list[WatchTarget] | None = None,
) -> BotCommand:
    raw_name = str(form.get("command") or form.get("action") or "history_r")
    raw_custom_target = str(form.get("custom_target_id") or "").strip()
    raw_preset_target = str(form.get("preset_target_id") or "").strip()
    raw_target = raw_custom_target or raw_preset_target or str(form.get("target_id") or "").strip()
    raw_count = str(form.get("count") or "").strip()
    if raw_name not in {"history_r", "pack_r", "history_t", "pack_t"}:
        raw_name = "history_r"
    author_targets = author_targets or parse_target_list("", default_author_id)
    thread_targets = thread_targets or parse_target_list("", default_tid)
    if raw_name.endswith("_t"):
        target = resolve_target_alias(raw_target, thread_targets, "t") or (thread_targets[0].id if thread_targets else default_tid)
    else:
        target = resolve_target_alias(raw_target, author_targets, "u") or (author_targets[0].id if author_targets else default_author_id)
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


def target_select_options(targets: list[WatchTarget], prefix: str) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for index, target in enumerate(targets, 1):
        label = target_display_name(target)
        options.append({"text": {"tag": "plain_text", "content": f"{prefix}{index} {label}"[:80]}, "value": target.id})
    return options


def target_select_initial_option(targets: list[WatchTarget], prefix: str, target_id: str) -> dict[str, Any] | None:
    target_id = str(target_id or "").strip()
    if not target_id:
        return None
    for index, target in enumerate(targets, 1):
        if target.id == target_id:
            label = target_display_name(target)
            return {"text": {"tag": "plain_text", "content": f"{prefix}{index} {label}"[:80]}, "value": target.id}
    return {"text": {"tag": "plain_text", "content": target_id[:80]}, "value": target_id}


def command_form_card(
    command: str,
    target_id: str,
    count: str,
    author_targets: list[WatchTarget] | None = None,
    thread_targets: list[WatchTarget] | None = None,
) -> dict[str, Any]:
    labels = {
        "history_r": "查询用户回复",
        "pack_r": "打包用户回复",
        "history_t": "查询帖子回复",
        "pack_t": "打包帖子回复",
    }
    target_label = "uid" if command.endswith("_r") else "tid"
    targets = author_targets if command.endswith("_r") else thread_targets
    targets = targets or [WatchTarget(target_id, "")]
    prefix = "u" if command.endswith("_r") else "t"
    target_options = target_select_options(targets, prefix)
    initial_target = target_select_initial_option(targets, prefix, target_id)
    if initial_target and all(option.get("value") != initial_target.get("value") for option in target_options):
        target_options.append(initial_target)
    target_select = {
        "tag": "select_static",
        "name": "preset_target_id",
        "placeholder": {"tag": "plain_text", "content": "Preset target"},
        "options": target_options,
    }
    if initial_target:
        target_select["initial_option"] = initial_target
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
                        target_select,
                        {
                            "tag": "input",
                            "name": "custom_target_id",
                            "placeholder": {"tag": "plain_text", "content": f"Custom {target_label} (optional)"},
                            "default_value": "",
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
                                        "target_id": target_id,
                                        "count": count,
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
    current_model = manager.effective_model()
    current_reasoning = manager.effective_reasoning_effort()
    runtime_model = "model" in state
    runtime_reasoning = "reasoning_effort" in state
    model_choices = ["default", "auto", *ai_analysis.model_options(manager.config.provider)]
    reasoning_choices = ["default", *ai_analysis.reasoning_effort_options(manager.config.provider)]
    if manager.config.provider in {"codex", "claude"}:
        model_control = {
            "tag": "select_static",
            "name": "model",
            "placeholder": {"tag": "plain_text", "content": f"当前：{current_model or 'auto'}"},
            "options": [{"text": {"tag": "plain_text", "content": item}, "value": item} for item in model_choices],
        }
        reasoning_control = {
            "tag": "select_static",
            "name": "reasoning_effort",
            "placeholder": {"tag": "plain_text", "content": f"当前：{current_reasoning or 'default'}"},
            "options": [
                {"text": {"tag": "plain_text", "content": ai_analysis.reasoning_effort_label(manager.config.provider, item)}, "value": item}
                for item in reasoning_choices
            ],
        }
    else:
        model_control = {
            "tag": "input",
            "name": "model",
            "placeholder": {"tag": "plain_text", "content": "自定义模型名；留空为 auto"},
            "default_value": current_model,
        }
        reasoning_control = {
            "tag": "input",
            "name": "reasoning_effort",
            "placeholder": {"tag": "plain_text", "content": "自定义思考强度；留空为 default"},
            "default_value": current_reasoning,
        }
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
                        f"模型：`{current_model or 'auto'}`{'（运行时）' if runtime_model else '（默认）'}\n"
                        f"思考强度：`{current_reasoning or 'default'}`{'（运行时）' if runtime_reasoning else '（默认）'}\n"
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
                callback_action_row(
                    callback_button("恢复默认模型/强度", "reset_ai_model_config"),
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
                            "content": "**模型**\nCodex/Claude 使用下拉选择；`default` 回到 GUI/启动默认值，`auto` 表示本次运行时不指定模型。",
                        },
                        model_control,
                        {
                            "tag": "markdown",
                            "content": "**思考强度**\nCodex: `low/medium/high/xhigh`；Claude: `low/medium/high/xhigh/max`；`default` 使用默认。",
                        },
                        reasoning_control,
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


def wechat_target_state_path(args: argparse.Namespace) -> Path:
    return wechat_client_for_args(args).config.state_dir / "target_state.json"


def wechat_user_target_state(args: argparse.Namespace, user_id: str) -> dict[str, str]:
    data = read_json(wechat_target_state_path(args), {})
    if not isinstance(data, dict):
        return {}
    item = data.get(user_id or "default")
    if not isinstance(item, dict):
        return {}
    return {str(key): str(value) for key, value in item.items() if value is not None}


def wechat_set_active_target(args: argparse.Namespace, user_id: str, target_type: str, target_id: str) -> None:
    path = wechat_target_state_path(args)
    data = read_json(path, {})
    if not isinstance(data, dict):
        data = {}
    key = user_id or "default"
    item = data.get(key)
    if not isinstance(item, dict):
        item = {}
    if target_type == "author":
        item["author_id"] = str(target_id)
    elif target_type == "thread":
        item["thread_id"] = str(target_id)
    item["updated_at"] = int(time.time())
    data[key] = item
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, data)


def target_id_exists(targets: list[WatchTarget], target_id: str) -> bool:
    return any(target.id == target_id for target in targets)


def wechat_active_target_ids(
    args: argparse.Namespace,
    user_id: str,
    author_targets: list[WatchTarget] | None = None,
    thread_targets: list[WatchTarget] | None = None,
) -> tuple[str, str]:
    author_targets = author_targets or watch_author_targets(args)
    thread_targets = thread_targets or preset_thread_targets(args)
    default_uid = author_targets[0].id if author_targets else str(getattr(args, "default_author_id", DEFAULT_AUTHOR_ID))
    default_tid = thread_targets[0].id if thread_targets else str(getattr(args, "default_tid", DEFAULT_TID))
    state = wechat_user_target_state(args, user_id)
    active_uid = str(state.get("author_id") or "").strip()
    active_tid = str(state.get("thread_id") or "").strip()
    if not active_uid or not target_id_exists(author_targets, active_uid):
        active_uid = default_uid
    if not active_tid or not target_id_exists(thread_targets, active_tid):
        active_tid = default_tid
    return active_uid, active_tid


def target_alias_label(targets: list[WatchTarget], target_id: str, prefix: str) -> str:
    for index, target in enumerate(targets, 1):
        if target.id == target_id:
            return f"{prefix}{index} {target_display_name(target)}"
    return target_id


def command_target_label(target_type: str, target_id: str, author_targets: list[WatchTarget], thread_targets: list[WatchTarget]) -> str:
    if target_type == "reply":
        if not target_id or target_id == "0":
            return "用户 任意"
        for target in author_targets:
            if target.id == target_id:
                return f"用户 {target_display_name(target)}"
        return f"用户 {target_id}"
    if target_type == "thread":
        for target in thread_targets:
            if target.id == target_id:
                return f"帖子 {target_display_name(target)}"
        return f"帖子 {target_id}"
    return target_id or "未知目标"


def target_from_alias(token: str, targets: list[WatchTarget], prefix: str) -> WatchTarget | None:
    match = re.fullmatch(rf"{re.escape(prefix)}\s*(\d+)", str(token or "").strip(), flags=re.I)
    if not match:
        return None
    index = int(match.group(1)) - 1
    if 0 <= index < len(targets):
        return targets[index]
    return None


def wechat_start_text(
    default_author_id: str,
    default_tid: str,
    author_targets: list[WatchTarget] | None = None,
    thread_targets: list[WatchTarget] | None = None,
    active_author_id: str = "",
    active_tid: str = "",
) -> str:
    author_targets = author_targets or parse_target_list("", default_author_id)
    thread_targets = thread_targets or parse_target_list("", default_tid)
    active_author_id = active_author_id or (author_targets[0].id if author_targets else default_author_id)
    active_tid = active_tid or (thread_targets[0].id if thread_targets else default_tid)

    lines = [
        "NGA 快捷菜单",
        "",
        "当前默认",
        f"用户: {target_alias_label(author_targets, active_author_id, 'u')}",
        f"帖子: {target_alias_label(thread_targets, active_tid, 't')}",
        "",
        "数字菜单",
        f"1 查询当前用户最近 {DEFAULT_REPLY_COUNT} 条回复",
        "2 打包当前用户最近 20 条回复",
        f"3 查询当前帖子最近 {DEFAULT_THREAD_COUNT} 条",
        "4 打包当前帖子最近 50 条",
        "5 打开设置",
        "",
        "快捷命令",
        "hr10  查询当前用户最近 10 条回复",
        "pr20  打包当前用户最近 20 条回复",
        "ht10  查询当前帖子最近 10 条",
        "pt50  打包当前帖子最近 50 条",
        "u1    切换默认用户到第 1 个预设",
        "t1    切换默认帖子到第 1 个预设",
        "s     打开设置",
        "",
        "一次性指定",
        "/history_r u1 20  查询第 1 个用户预设",
        "/pack_t t1 50     打包第 1 个帖子预设",
        "完整命令: /history_r /pack_r /history_t /pack_t",
    ]
    if author_targets:
        lines.extend(["", "用户预设"])
        for index, target in enumerate(author_targets, 1):
            marker = "*" if target.id == active_author_id else " "
            lines.append(f"{marker} u{index} {target_display_name(target)}")
    if thread_targets:
        lines.extend(["", "帖子预设"])
        for index, target in enumerate(thread_targets, 1):
            marker = "*" if target.id == active_tid else " "
            lines.append(f"{marker} t{index} {target_display_name(target)}")
    # WeChat text bubbles collapse single newlines, so use paragraph breaks for menu items.
    return "\n\n".join(line for line in lines if line)

def wechat_settings_text(args: argparse.Namespace, manager: ai_analysis.AIManager) -> str:
    effective = manager.effective_config()
    cfg = wechat_bot.WeChatBotConfig.from_namespace(args)
    return "\n".join(
        [
            "NGA Wolf Watcher 设置",
            f"通道: wechat",
            f"AI: {'开' if effective.enabled else '关'}",
            f"自动分析: {'开' if effective.auto_analyze_new_post else '关'}",
            f"定时分析: {'开' if effective.schedule_enabled else '关'}",
            f"定时间隔: {effective.schedule_interval_minutes} 分钟",
            f"时间窗口: {effective.schedule_windows}",
            f"权限模式: {manager.effective_permission_mode()}",
            f"模型: {manager.effective_model() or 'auto'}",
            f"思考强度: {manager.effective_reasoning_effort() or 'default'}",
            f"微信目标用户: {cfg.target_user_id or '未设置'}",
            "",
            "可复制命令：",
            "1 AI 开",
            "2 AI 关",
            "3 自动分析开",
            "4 自动分析关",
            "5 定时分析开",
            "6 定时分析关",
            "7 AI 状态",
            "8 返回主菜单",
            "",
            "a1 AI 开 | a0 AI 关",
            "n1 自动分析开 | n0 自动分析关",
            "q1 定时分析开 | q0 定时分析关",
            "st AI 状态 | b 绑定状态",
            "/ai on | /ai off",
            "/ai auto on | /ai auto off",
            "/ai schedule on | /ai schedule off",
            "/ai schedule every 5",
            f"/ai schedule windows {ai_analysis.DEFAULT_SCHEDULE_WINDOWS}",
            "/mode default",
            "/model auto",
            "/reasoning high",
            "",
            wechat_bot.describe_binding(cfg),
        ]
    )


def wechat_normalize_short_command(args: argparse.Namespace, user_id: str, text: str) -> str:
    raw = str(text or "").strip()
    compact = " ".join(raw.split()).lower()
    if not compact:
        return raw
    menu = wechat_bot.WeChatMenuState(wechat_client_for_args(args).config.state_dir).get(user_id)
    author_targets = watch_author_targets(args)
    thread_targets = preset_thread_targets(args)
    default_uid, default_tid = wechat_active_target_ids(args, user_id, author_targets, thread_targets)

    def parse_short_count(prefix: str, default: int) -> int | None:
        match = re.fullmatch(rf"{re.escape(prefix)}(?:\s*(\d{{1,3}}))?", compact)
        if not match:
            return None
        if match.group(1):
            return max(1, min(int(match.group(1)), 500))
        return default

    aliases = {
        "s": "/setting",
        "st": "/ai status",
        "a1": "/ai on",
        "a0": "/ai off",
        "n1": "/ai auto on",
        "n0": "/ai auto off",
        "q1": "/ai schedule on",
        "q0": "/ai schedule off",
        "b": "/wechat binding",
    }
    if compact in aliases:
        return aliases[compact]
    author_switch = target_from_alias(compact, author_targets, "u")
    if author_switch is not None:
        wechat_set_active_target(args, user_id, "author", author_switch.id)
        return "/start"
    thread_switch = target_from_alias(compact, thread_targets, "t")
    if thread_switch is not None:
        wechat_set_active_target(args, user_id, "thread", thread_switch.id)
        return "/start"
    hr_count = parse_short_count("hr", DEFAULT_REPLY_COUNT)
    if hr_count is not None:
        return f"/history_r {default_uid} {hr_count}"
    pr_count = parse_short_count("pr", 20)
    if pr_count is not None:
        return f"/pack_r {default_uid} {pr_count}"
    ht_count = parse_short_count("ht", DEFAULT_THREAD_COUNT)
    if ht_count is not None:
        return f"/history_t {default_tid} {ht_count}"
    pt_count = parse_short_count("pt", 50)
    if pt_count is not None:
        return f"/pack_t {default_tid} {pt_count}"
    if compact in {"1", "2", "3", "4", "5"} and menu == "start":
        return {
            "1": f"/history_r {default_uid} {DEFAULT_REPLY_COUNT}",
            "2": f"/pack_r {default_uid} 20",
            "3": f"/history_t {default_tid} {DEFAULT_THREAD_COUNT}",
            "4": f"/pack_t {default_tid} 50",
            "5": "/setting",
        }[compact]
    if compact in {"1", "2", "3", "4", "5", "6", "7", "8"} and menu == "setting":
        return {
            "1": "/ai on",
            "2": "/ai off",
            "3": "/ai auto on",
            "4": "/ai auto off",
            "5": "/ai schedule on",
            "6": "/ai schedule off",
            "7": "/ai status",
            "8": "/start",
        }[compact]
    return raw


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
    target = push_target_for_channel_receive(args, "feishu", chat_id)
    if target:
        if target.default_author_id:
            cloned.default_author_id = target.default_author_id
        if target.default_tid:
            cloned.default_tid = target.default_tid
    return cloned


def args_for_thread_author_route(args: argparse.Namespace, post: NgaPost) -> argparse.Namespace:
    if not post.source_id:
        return args
    if post.source_type == "author":
        for target in watch_author_targets(args):
            if target.id != post.source_id:
                continue
            return args_for_configured_route(
                args,
                route_channel=target.route_channel,
                route_profile_id=target.route_profile_id,
                receive_id=target.route_receive_id,
                receive_id_type=target.route_id_type,
            )
        return args
    if post.source_type == "thread_author":
        for watch in thread_author_watches(args):
            if watch.key != post.source_id:
                continue
            return args_for_configured_route(
                args,
                route_channel=watch.route_channel,
                route_profile_id=watch.route_profile_id,
                receive_id=watch.feishu_receive_id,
                receive_id_type=watch.feishu_id_type,
                legacy_feishu_app_id=watch.feishu_app_id,
                legacy_feishu_app_secret=watch.feishu_app_secret,
            )
    return args


def post_tid(post: NgaPost) -> str:
    try:
        parsed = urllib.parse.urlparse(post.url)
        query = urllib.parse.parse_qs(parsed.query)
        return str((query.get("tid") or [""])[0]).strip()
    except Exception:
        return ""


def route_args_for_post(args: argparse.Namespace, post: NgaPost) -> list[argparse.Namespace]:
    rules = configured_listen_rules(args)
    if not rules:
        return [args_for_thread_author_route(args, post)]
    matched_by_id: dict[str, ListenRule] = {}
    author_id = str(post.author_id or (post.source_id if post.source_type == "author" else "")).strip()
    tid = post_tid(post)
    for rule in rules:
        if rule.mode == "author" and author_id and rule.author_id == author_id:
            matched_by_id[rule.id] = rule
        elif rule.mode == "thread_author" and author_id and tid and rule.author_id == author_id and rule.tid == tid:
            matched_by_id[rule.id] = rule
        elif post.source_type == "thread_author" and rule.mode == "thread_author" and rule.source_key == post.source_id:
            matched_by_id[rule.id] = rule
    matched = list(matched_by_id.values())
    if not matched:
        return [args]
    routed: list[argparse.Namespace] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for rule in matched:
        if not rule.target_ids:
            candidates = [None]
        else:
            candidates = [target for target_id in rule.target_ids if (target := find_push_target(args, target_id)) is not None]
        for target in candidates:
            scoped = args_for_push_target(args, target) if target is not None else args
            key = channel_route_key(scoped)
            if key in seen:
                continue
            seen.add(key)
            routed.append(scoped)
    return routed or [args]


def feishu_route_key(args: argparse.Namespace) -> tuple[str, str, str, str, str]:
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = getattr(args, "webhook", "") or os.getenv("FEISHU_WEBHOOK", "")
    secret_hash = hashlib.sha1(app_secret.encode("utf-8")).hexdigest()[:12] if app_secret else ""
    if app_id or app_secret or receive_id:
        return ("app", app_id, secret_hash, receive_id, receive_id_type)
    return ("webhook", webhook, "", "", "")


def channel_route_key(args: argparse.Namespace) -> tuple[str, str, str, str, str]:
    if is_wechat_channel(args):
        token = str(getattr(args, "wechat_bot_token", "") or "")
        token_hash = hashlib.sha1(token.encode("utf-8")).hexdigest()[:12] if token else ""
        return (
            "wechat",
            str(getattr(args, "wechat_bot_account_id", "") or ""),
            token_hash,
            str(getattr(args, "wechat_bot_target_user_id", "") or ""),
            str(getattr(args, "wechat_bot_route_tag", "") or ""),
        )
    return feishu_route_key(args)


def settings_card_for_args(args: argparse.Namespace, manager: ai_analysis.AIManager) -> dict[str, Any]:
    state = read_json(Path(args.state_path), {})
    return ai_settings_card(
        manager,
        mention_enabled=effective_mention_enabled(args, state),
        mention_user_id=effective_mention_user_id(args, state),
    )


def run_bot_command(args: argparse.Namespace, command: BotCommand) -> None:
    if command.action == "start":
        if is_wechat_channel(args):
            target_user = str(getattr(args, "wechat_bot_target_user_id", "") or "").strip()
            if target_user:
                wechat_bot.WeChatMenuState(wechat_client_for_args(args).config.state_dir).set(target_user, "start")
            author_targets = watch_author_targets(args)
            thread_targets = preset_thread_targets(args)
            active_uid, active_tid = wechat_active_target_ids(args, target_user, author_targets, thread_targets)
            push_channel_raw_text(args, wechat_start_text(args.default_author_id, args.default_tid, author_targets, thread_targets, active_uid, active_tid))
            return
        push_feishu_card(args, start_form_card(args.default_author_id, args.default_tid))
        return
    if command.action == "setting":
        manager = ai_manager_for_args(args)
        if is_wechat_channel(args):
            target_user = str(getattr(args, "wechat_bot_target_user_id", "") or "").strip()
            if target_user:
                wechat_bot.WeChatMenuState(wechat_client_for_args(args).config.state_dir).set(target_user, "setting")
            push_channel_raw_text(args, wechat_settings_text(args, manager))
            return
        push_feishu_card(args, settings_card_for_args(args, manager))
        return

    author_targets = watch_author_targets(args)
    thread_targets = preset_thread_targets(args)
    if command.target_type == "reply":
        posts = collect_replies_with_retries(args, command.target_id, command.count)
        label = command_target_label(command.target_type, command.target_id, author_targets, thread_targets)
    elif command.target_type == "thread":
        posts = collect_thread_tail_with_retries(args, command.target_id, command.count)
        label = command_target_label(command.target_type, command.target_id, author_targets, thread_targets)
    else:
        raise RuntimeError(f"未知命令目标：{command}")

    title = f"NGA {label} 最新 {len(posts)} 条"
    if len(posts) < command.count:
        title += f"（请求 {command.count} 条，NGA 临时限流时会先返回已获取部分）"
    if command.action == "pack":
        file_name = f"nga_{command.target_type}_{command.target_id or 'any'}_{len(posts)}_{int(time.time())}.txt"
        push_channel_file(args, file_name, posts_to_txt(posts, title))
    else:
        if not is_wechat_channel(args) and args.message_format == "card" and len(posts) > 20:
            creds = feishu_credentials(args)
            for start in range(0, len(posts), 20):
                chunk = posts[start : start + 20]
                chunk_title = f"{title} ({start + 1}-{start + len(chunk)})"
                push_feishu_app_posts(*creds, chunk, chunk_title, args.timeout, args.message_format, args=args)
                time.sleep(0.4)
        else:
            push_channel_posts(args, posts, title)


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
                push_channel_posts(args, [err_post], "NGA 命令处理失败")
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


def start_wechat_poll(args: argparse.Namespace) -> None:
    if not getattr(args, "ws_no_watch", False):
        def watch_loop() -> None:
            service_unavailable_failures = 0
            while True:
                round_error: Exception | None = None
                try:
                    run_once(args)
                    maybe_run_ai_schedule(args)
                    service_unavailable_failures = 0
                except Exception as exc:
                    round_error = exc
                    if is_nga_service_unavailable(exc):
                        service_unavailable_failures += 1
                    else:
                        service_unavailable_failures = 0
                    print(f"NGA 监听循环失败: {exc}", file=sys.stderr)
                sleep_for = watch_sleep_seconds(args, round_error, service_unavailable_failures)
                if round_error is not None and is_nga_service_unavailable(round_error):
                    print(f"NGA 503 backoff: next watch round in {sleep_for:.1f}s", file=sys.stderr)
                time.sleep(sleep_for)

        threading.Thread(target=watch_loop, daemon=True).start()

    while True:
        try:
            handle_wechat_commands(args)
        except Exception as exc:
            print(f"微信 Bot 长轮询失败: {exc}", file=sys.stderr)
            time.sleep(5)


def uses_structured_routes(args: argparse.Namespace) -> bool:
    return bool(parse_push_targets(getattr(args, "push_targets", "")) or parse_listen_rules(getattr(args, "listen_rules", "")))


def command_channel_args(args: argparse.Namespace) -> list[argparse.Namespace]:
    channels: list[argparse.Namespace] = []
    seen: set[tuple[str, str]] = set()
    for profile in feishu_bot_profiles(args):
        if not (profile.app_id and profile.app_secret):
            continue
        cloned = copy.copy(args)
        cloned.bot_channel = "feishu"
        cloned.feishu_app_id = profile.app_id
        cloned.feishu_app_secret = profile.app_secret
        cloned.feishu_id_type = profile.id_type or "chat_id"
        cloned.ws_no_watch = True
        key = ("feishu", profile.app_id)
        if key not in seen:
            seen.add(key)
            channels.append(cloned)
    for profile in wechat_bot_profiles(args):
        if not profile.token:
            continue
        cloned = args_for_configured_route(args, route_channel="wechat", route_profile_id=profile.id)
        cloned.ws_no_watch = True
        key = ("wechat", profile.token)
        if key not in seen:
            seen.add(key)
            channels.append(cloned)
    return channels


def start_multi_channel(args: argparse.Namespace) -> None:
    def watch_loop() -> None:
        service_unavailable_failures = 0
        while True:
            round_error: Exception | None = None
            try:
                run_once(args)
                maybe_run_ai_schedule(args)
                service_unavailable_failures = 0
            except Exception as exc:
                round_error = exc
                if is_nga_service_unavailable(exc):
                    service_unavailable_failures += 1
                else:
                    service_unavailable_failures = 0
                print(f"NGA 监听循环失败: {exc}", file=sys.stderr)
            sleep_for = watch_sleep_seconds(args, round_error, service_unavailable_failures)
            if round_error is not None and is_nga_service_unavailable(round_error):
                print(f"NGA 503 backoff: next watch round in {sleep_for:.1f}s", file=sys.stderr)
            time.sleep(sleep_for)

    threading.Thread(target=watch_loop, daemon=True).start()
    started = 0
    for scoped_args in command_channel_args(args):
        if is_wechat_channel(scoped_args):
            threading.Thread(target=start_wechat_poll, args=(scoped_args,), daemon=True).start()
            started += 1
        else:
            threading.Thread(target=start_ws, args=(scoped_args,), daemon=True).start()
            started += 1
    print(f"已启动结构化多通道监听：命令入口 {started} 个，NGA 监听循环 1 个。")
    while True:
        time.sleep(3600)


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
        command = parse_bot_command(text, args.default_author_id, args.default_tid, watch_author_targets(args), preset_thread_targets(args))
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
            if action == "reset_ai_model_config":
                if not manager.is_authorized(sender_id):
                    return card_response(None, "AI command rejected: sender is not authorized.", "error")
                manager.clear_runtime_model_config()
                return card_response(settings_card_for_args(scoped_args, manager), "已恢复默认模型/强度")
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
                model = str(form.get("model") or "").strip()
                reasoning_effort = str(form.get("reasoning_effort") or "").strip()
                if mode:
                    manager.handle_command(f"/mode {mode}", sender_id)
                if "model" in form:
                    manager.handle_command(f"/model {model or 'auto'}", sender_id)
                if "reasoning_effort" in form:
                    manager.handle_command(f"/reasoning {reasoning_effort or 'default'}", sender_id)
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
                return card_response(command_form_card(command_name, target_id, count, watch_author_targets(scoped_args), preset_thread_targets(scoped_args)), "已打开预填表单")
            command = bot_command_from_form(form, args.default_author_id, args.default_tid, watch_author_targets(scoped_args), preset_thread_targets(scoped_args))
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
            service_unavailable_failures = 0
            while True:
                round_error: Exception | None = None
                try:
                    run_once(args)
                    maybe_run_ai_schedule(args)
                    service_unavailable_failures = 0
                except Exception as exc:
                    round_error = exc
                    if is_nga_service_unavailable(exc):
                        service_unavailable_failures += 1
                    else:
                        service_unavailable_failures = 0
                    print(f"NGA 监听循环失败: {exc}", file=sys.stderr)
                sleep_for = watch_sleep_seconds(args, round_error, service_unavailable_failures)
                if round_error is not None and is_nga_service_unavailable(round_error):
                    print(f"NGA 503 backoff: next watch round in {sleep_for:.1f}s", file=sys.stderr)
                time.sleep(sleep_for)

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
    if is_wechat_channel(args):
        push_channel_posts(args, [post], "NGA 监听测试")
        print("测试消息已发送。")
        return
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
            args=args,
        )
    else:
        push_to_feishu(args, post)
    print("测试消息已发送。")


def push_deferred_summary_direct(args: argparse.Namespace, posts: list[NgaPost], mention_user_id: str = "") -> None:
    if not posts:
        return
    if is_wechat_channel(args):
        title = f"Quiet-hours summary ({len(posts)} posts)"
        push_channel_posts(args, posts, title)
        return
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")
    title = f"免打扰期间新回复汇总（{len(posts)} 条）"
    if app_id or app_secret or receive_id:
        if not (app_id and app_secret and receive_id):
            raise SystemExit("缺少 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID。")
        if args.message_format == "text":
            push_feishu_app_posts(app_id, app_secret, receive_id, receive_id_type, posts, title, args.timeout, "text", args=args)
        else:
            image_keys_by_url = feishu_image_keys_for_posts(args, app_id, app_secret, posts)
            push_feishu_app_card(
                app_id,
                app_secret,
                receive_id,
                receive_id_type,
                feishu_deferred_summary_card(posts, len(posts), mention_user_id, image_keys_by_url),
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


def push_deferred_summary(args: argparse.Namespace, posts: list[NgaPost]) -> None:
    if not posts:
        return
    state = read_json(Path(args.state_path), {})
    mention_user_id = feishu_mention_user_id(args, state)
    grouped: dict[tuple[str, str, str, str, str], tuple[argparse.Namespace, list[NgaPost]]] = {}
    for post in posts:
        for routed_args in route_args_for_post(args, post):
            key = channel_route_key(routed_args)
            if key not in grouped:
                grouped[key] = (routed_args, [])
            grouped[key][1].append(post)
    if not grouped:
        grouped[channel_route_key(args)] = (args, posts)
    for routed_args, group_posts in grouped.values():
        push_deferred_summary_direct(routed_args, group_posts, mention_user_id)


def push_single_channel_post(args: argparse.Namespace, post: NgaPost, mention_user_id: str = "") -> None:
    if is_wechat_channel(args):
        push_channel_raw_text(args, wechat_posts_text([post], new_reply_title(post)))
        return
    app_id, app_secret, receive_id, receive_id_type = feishu_credentials(args)
    webhook = args.webhook or os.getenv("FEISHU_WEBHOOK", "")
    secret = args.secret or os.getenv("FEISHU_SECRET")

    if app_id or app_secret or receive_id:
        if not (app_id and app_secret and receive_id):
            raise SystemExit("缺少 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID。")
        push_feishu_app(app_id, app_secret, receive_id, receive_id_type, post, args.timeout, args.message_format, mention_user_id, args=args)
        return

    if not webhook:
        raise SystemExit("缺少飞书发送目标。请设置应用凭证和 Receive ID，或设置 FEISHU_WEBHOOK。")
    push_feishu(webhook, secret, post, args.timeout)


def push_to_feishu(args: argparse.Namespace, post: NgaPost, mention_user_id: str = "") -> None:
    routed_args = route_args_for_post(args, post)
    for scoped_args in routed_args:
        push_single_channel_post(scoped_args, post, mention_user_id)


def sleep_between_nga_pages(page_delay: float) -> None:
    if page_delay <= 0:
        return
    time.sleep(page_delay + random.uniform(0, page_delay * 0.5))


def sleep_between_watch_targets(args: argparse.Namespace, target_index: int, total_targets: int) -> None:
    if total_targets <= 1 or target_index >= total_targets - 1:
        return
    min_delay = max(0.0, float(getattr(args, "nga_target_min_delay", DEFAULT_NGA_TARGET_MIN_DELAY)))
    max_delay = max(0.0, float(getattr(args, "nga_target_max_delay", DEFAULT_NGA_TARGET_MAX_DELAY)))
    if max_delay <= 0:
        return
    if max_delay < min_delay:
        max_delay = min_delay
    time.sleep(random.uniform(min_delay, max_delay))


def format_target_fetch_counts(counts: list[tuple[str, int]]) -> str:
    return "；".join(f"{name} {count}" for name, count in counts)


def collect_posts(
    author_id: str,
    cookie: str,
    max_pages: int,
    timeout: int,
    attempts: int = 1,
    retry_initial_delay: float = DEFAULT_RETRY_INITIAL_DELAY,
    retry_delay: float = 0,
    page_delay: float = DEFAULT_NGA_PAGE_DELAY,
    request_min_interval: float = DEFAULT_NGA_REQUEST_MIN_INTERVAL,
    cache_ttl: float = DEFAULT_NGA_CACHE_TTL,
    allow_partial: bool = False,
) -> list[NgaPost]:
    posts: list[NgaPost] = []
    for page in range(1, max_pages + 1):
        try:
            payload = with_retries(
                f"NGA 用户回复第 {page} 页",
                attempts,
                retry_initial_delay,
                retry_delay,
                lambda page=page: fetch_nga_page(author_id, page, cookie, timeout, request_min_interval, cache_ttl),
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
    retry_initial_delay: float = DEFAULT_RETRY_INITIAL_DELAY,
    retry_delay: float = 0,
    page_delay: float = DEFAULT_NGA_PAGE_DELAY,
    request_min_interval: float = DEFAULT_NGA_REQUEST_MIN_INTERVAL,
    cache_ttl: float = DEFAULT_NGA_CACHE_TTL,
    allow_partial: bool = False,
) -> list[NgaPost]:
    pages = max(1, (count + 19) // 20)
    return collect_posts(author_id, cookie, pages, timeout, attempts, retry_initial_delay, retry_delay, page_delay, request_min_interval, cache_ttl, allow_partial)[:count]


def collect_thread_tail(
    tid: str,
    count: int,
    cookie: str,
    timeout: int,
    attempts: int = 1,
    retry_initial_delay: float = DEFAULT_RETRY_INITIAL_DELAY,
    retry_delay: float = 0,
    page_delay: float = DEFAULT_NGA_PAGE_DELAY,
    request_min_interval: float = DEFAULT_NGA_REQUEST_MIN_INTERVAL,
    cache_ttl: float = DEFAULT_NGA_CACHE_TTL,
    allow_partial: bool = False,
) -> list[NgaPost]:
    first_payload = with_retries(
        f"NGA 帖子 {tid} 最新页",
        attempts,
        retry_initial_delay,
        retry_delay,
        lambda: fetch_nga_thread_page(tid, 99999, cookie, timeout, request_min_interval, cache_ttl),
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
                retry_initial_delay,
                retry_delay,
                lambda page=page: fetch_nga_thread_page(tid, page, cookie, timeout, request_min_interval, cache_ttl),
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


def with_retries(label: str, attempts: int, initial_delay: float, step_delay: float, fn: Any) -> Any:
    last_exc: Exception | None = None
    unavailable_limit = max(1, int(os.getenv("NGA_UNAVAILABLE_RETRIES", str(DEFAULT_NGA_UNAVAILABLE_RETRIES))))
    initial_delay = max(0.0, float(initial_delay))
    step_delay = max(0.0, float(step_delay))
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            effective_attempts = min(attempts, unavailable_limit) if is_nga_temporary_unavailable(exc) else attempts
            if attempt >= effective_attempts:
                break
            sleep_for = initial_delay + step_delay * (attempt - 1)
            print(f"{label} 失败（{attempt}/{effective_attempts}）：{exc}；{sleep_for:.1f} 秒后重试", file=sys.stderr)
            time.sleep(sleep_for)
    message = f"{label} 在 {effective_attempts} 次尝试后仍失败：{last_exc}"
    if last_exc and is_nga_temporary_unavailable(last_exc):
        raise NgaTemporaryUnavailable(message, status_code=nga_status_code(last_exc)) from last_exc
    raise RuntimeError(message)


def regular_watch_sleep_seconds(args: argparse.Namespace) -> float:
    jitter = random.uniform(-args.jitter, args.jitter) if args.jitter > 0 else 0
    base_interval = max(1.0, float(args.interval))
    if thread_author_watches_for_watch(args):
        thread_interval = max(1.0, float(getattr(args, "thread_watch_interval", DEFAULT_THREAD_WATCH_INTERVAL) or DEFAULT_THREAD_WATCH_INTERVAL))
        base_interval = min(base_interval, thread_interval)
    return max(1.0, base_interval + jitter)


def watch_due(state: dict[str, Any], key: str, interval: float, *, force: bool = False) -> bool:
    if force:
        return True
    try:
        last_at = float(state.get(key) or 0)
    except (TypeError, ValueError):
        last_at = 0
    return last_at <= 0 or time.time() - last_at >= max(1.0, float(interval))


def nga_unavailable_backoff_sleep_seconds(args: argparse.Namespace, failures: int) -> float:
    base = max(1.0, float(getattr(args, "nga_unavailable_backoff_base", DEFAULT_NGA_UNAVAILABLE_BACKOFF_BASE)))
    maximum = max(base, float(getattr(args, "nga_unavailable_backoff_max", DEFAULT_NGA_UNAVAILABLE_BACKOFF_MAX)))
    multiplier = 2 ** min(max(0, failures - 1), 6)
    sleep_for = min(maximum, base * multiplier)
    jitter = max(0.0, float(getattr(args, "jitter", 0)))
    if jitter > 0:
        sleep_for += random.uniform(0, min(jitter, max(1.0, sleep_for * 0.2)))
    return max(1.0, sleep_for)


def watch_sleep_seconds(args: argparse.Namespace, round_error: Exception | None, service_unavailable_failures: int) -> float:
    if round_error is not None and is_nga_service_unavailable(round_error):
        return nga_unavailable_backoff_sleep_seconds(args, service_unavailable_failures)
    return regular_watch_sleep_seconds(args)


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
        getattr(args, "retry_initial_delay", DEFAULT_RETRY_INITIAL_DELAY),
        args.retry_delay,
        getattr(args, "nga_page_delay", DEFAULT_NGA_PAGE_DELAY),
        getattr(args, "nga_request_min_interval", DEFAULT_NGA_REQUEST_MIN_INTERVAL),
        getattr(args, "nga_cache_ttl", DEFAULT_NGA_CACHE_TTL),
        False,
    )


def collect_posts_for_author_with_retries(args: argparse.Namespace, author_id: str, count_pages: int | None = None) -> list[NgaPost]:
    cloned = copy.copy(args)
    cloned.author_id = author_id
    return collect_posts_with_retries(cloned, count_pages)


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
        getattr(args, "retry_initial_delay", DEFAULT_RETRY_INITIAL_DELAY),
        args.retry_delay,
        getattr(args, "nga_page_delay", DEFAULT_NGA_PAGE_DELAY),
        getattr(args, "nga_request_min_interval", DEFAULT_NGA_REQUEST_MIN_INTERVAL),
        getattr(args, "nga_cache_ttl", DEFAULT_NGA_CACHE_TTL),
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
        getattr(args, "retry_initial_delay", DEFAULT_RETRY_INITIAL_DELAY),
        args.retry_delay,
        getattr(args, "nga_page_delay", DEFAULT_NGA_PAGE_DELAY),
        getattr(args, "nga_request_min_interval", DEFAULT_NGA_REQUEST_MIN_INTERVAL),
        getattr(args, "nga_cache_ttl", DEFAULT_NGA_CACHE_TTL),
        True,
    )


def collect_thread_author_watch_posts(args: argparse.Namespace, watches: list[ThreadAuthorWatch]) -> tuple[list[NgaPost], list[tuple[str, int]]]:
    posts: list[NgaPost] = []
    counts: list[tuple[str, int]] = []
    if not watches:
        return posts, counts
    tail_count = max(1, int(getattr(args, "thread_watch_tail_count", DEFAULT_THREAD_WATCH_TAIL_COUNT) or DEFAULT_THREAD_WATCH_TAIL_COUNT))
    by_tid: dict[str, list[ThreadAuthorWatch]] = {}
    for watch in watches:
        by_tid.setdefault(watch.tid, []).append(watch)
    tids = list(by_tid)
    for tid_index, tid in enumerate(tids):
        thread_posts = collect_thread_tail_with_retries(args, tid, tail_count)
        for watch in by_tid[tid]:
            matched = [add_thread_author_source(post, watch) for post in thread_posts if str(post.author_id) == str(watch.author_id)]
            posts.extend(matched)
            counts.append((thread_author_display_name(watch), len(matched)))
        sleep_between_watch_targets(args, tid_index, len(tids))
    return posts, counts


def collect_thread_author_startup_catchup_posts(args: argparse.Namespace, watches: list[ThreadAuthorWatch]) -> tuple[list[NgaPost], list[tuple[str, int]]]:
    posts: list[NgaPost] = []
    counts: list[tuple[str, int]] = []
    if not watches:
        return posts, counts
    by_author: dict[str, list[ThreadAuthorWatch]] = {}
    for watch in watches:
        by_author.setdefault(watch.author_id, []).append(watch)
    author_ids = list(by_author)
    for author_index, author_id in enumerate(author_ids):
        author_posts = collect_posts_for_author_with_retries(args, author_id)
        watches_for_author = by_author[author_id]
        for watch in watches_for_author:
            matched = [add_thread_author_source(post, watch) for post in author_posts if post_tid(post) == watch.tid]
            posts.extend(matched)
            counts.append((f"{thread_author_display_name(watch)} 启动补抓", len(matched)))
        sleep_between_watch_targets(args, author_index, len(author_ids))
    return posts, counts


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
        command = parse_bot_command(text, args.default_author_id, args.default_tid, watch_author_targets(args), preset_thread_targets(args))
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


def wechat_attachment_paths(message: wechat_bot.WeChatMessage) -> tuple[list[Path], list[Path]]:
    image_paths: list[Path] = []
    file_paths: list[Path] = []
    for attachment in message.attachments:
        if attachment.kind == "image":
            image_paths.append(attachment.path)
        else:
            file_paths.append(attachment.path)
    return image_paths, file_paths


def path_is_under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def local_file_paths_from_wechat_text(args: argparse.Namespace, text: str) -> list[Path]:
    if not text:
        return []
    roots = [
        wechat_client_for_args(args).config.state_dir,
        ai_analysis.AIConfig.from_namespace(args).work_dir,
    ]
    paths: list[Path] = []
    seen: set[str] = set()
    patterns = [
        r"(?:本地文件|Local file)\s*[:：]\s*(.+?)(?=\s+\|\s+|[\r\n\]]|$)",
        r"`([A-Za-z]:\\[^`]+)`",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw = (match.group(1) or "").strip().strip("`'\"")
            if not raw:
                continue
            candidate = Path(raw)
            try:
                resolved = candidate.expanduser().resolve()
            except Exception:
                continue
            if not resolved.exists() or not resolved.is_file():
                continue
            if not any(path_is_under(resolved, root) for root in roots):
                continue
            key = str(resolved).lower()
            if key not in seen:
                seen.add(key)
                paths.append(resolved)
    return paths


def enqueue_ai_direct_job(
    args: argparse.Namespace,
    label: str,
    fn: Callable[[], None],
) -> None:
    def queued_job() -> None:
        try:
            print(f"开始处理 {label}")
            fn()
            print(f"处理完成 {label}")
        except Exception as exc:
            print(f"AI 微信任务失败 {label}: {exc}", file=sys.stderr)
            try:
                if ai_analysis.AIConfig.from_namespace(args).send_errors_to_feishu:
                    push_channel_text(args, "AI task failed", str(exc))
            except Exception as nested:
                print(f"发送 AI 微信错误消息失败: {nested}", file=sys.stderr)

    enqueue_ai_feishu_job(args, label, queued_job)


def handle_wechat_commands(args: argparse.Namespace) -> bool:
    if args.disable_commands:
        return False
    client = wechat_client_for_args(args)
    changed = False
    for message in client.get_updates():
        if client.is_handled(message):
            continue
        scoped_args = args_for_wechat_user(args, message.user_id)
        text = wechat_normalize_short_command(scoped_args, message.user_id, message.text)
        sender_id = message.user_id
        image_paths, file_paths = wechat_attachment_paths(message)
        file_paths.extend(local_file_paths_from_wechat_text(scoped_args, text))
        try:
            if ai_analysis.parse_ai_command(text) is not None:
                enqueue_ai_direct_job(
                    scoped_args,
                    f"微信消息:{message.message_id} /ai",
                    lambda scoped_args=scoped_args, text=text, sender_id=sender_id, image_paths=image_paths, file_paths=file_paths: run_ai_command(
                        scoped_args,
                        text,
                        sender_id,
                        image_paths,
                        file_paths,
                    ),
                )
            else:
                if text == "/wechat binding":
                    push_channel_raw_text(scoped_args, wechat_bot.describe_binding(client.config))
                    client.mark_handled(message)
                    changed = True
                    continue
                author_targets = watch_author_targets(scoped_args)
                thread_targets = preset_thread_targets(scoped_args)
                active_uid, active_tid = wechat_active_target_ids(scoped_args, message.user_id, author_targets, thread_targets)
                command = parse_bot_command(text, args.default_author_id, args.default_tid, author_targets, thread_targets, active_uid, active_tid)
                if command is not None:
                    run_command_background(scoped_args, command, f"微信消息:{message.message_id}")
                elif (image_paths or file_paths) or should_forward_plain_text_to_ai(scoped_args, text, sender_id, [], []):
                    manager = ai_manager_for_args(scoped_args)
                    if not manager.effective_enabled() or not manager.is_authorized(sender_id):
                        client.mark_handled(message)
                        changed = True
                        continue
                    prompt_text = text or ("请分析我发送的图片。" if image_paths and not file_paths else "请分析我发送的附件。")
                    enqueue_ai_direct_job(
                        scoped_args,
                        f"微信消息:{message.message_id} AI conversation",
                        lambda scoped_args=scoped_args, text=prompt_text, sender_id=sender_id, image_paths=image_paths, file_paths=file_paths: run_ai_plain_text(
                            scoped_args,
                            text,
                            sender_id,
                            image_paths,
                            file_paths,
                        ),
                    )
        except Exception as exc:
            print(f"微信消息处理失败 {message.message_id}: {exc}", file=sys.stderr)
            try:
                push_channel_text(scoped_args, "微信命令处理失败", str(exc))
            except Exception as nested:
                print(f"发送微信错误消息失败: {nested}", file=sys.stderr)
        client.mark_handled(message)
        changed = True
    return changed


def run_once(args: argparse.Namespace) -> int:
    cookie = args.cookie or os.getenv("NGA_COOKIE", "")
    if not cookie:
        raise SystemExit("缺少 NGA_COOKIE。请从已登录 bbs.nga.cn 的浏览器会话复制 Cookie。")

    state_path = Path(args.state_path)
    state = read_json(state_path, {"seen": []})
    seen = set(state.get("seen", []))
    mention_user_id = feishu_mention_user_id(args, state)

    author_targets = watch_author_targets_for_watch(args)
    thread_watches = thread_author_watches_for_watch(args)
    force_watch = bool(getattr(args, "mark_seen", False) or getattr(args, "once", False))
    author_due = bool(author_targets) and watch_due(state, "last_author_watch_at", float(getattr(args, "interval", 30) or 30), force=force_watch)
    thread_due = bool(thread_watches) and watch_due(
        state,
        "last_thread_author_watch_at",
        float(getattr(args, "thread_watch_interval", DEFAULT_THREAD_WATCH_INTERVAL) or DEFAULT_THREAD_WATCH_INTERVAL),
        force=force_watch,
    )
    if not author_due:
        author_targets = []
    if not thread_due:
        thread_watches = []
    has_author_init_state = isinstance(state.get("watch_author_initialized_ids"), list)
    initialized_author_ids = set(state_list(state.get("watch_author_initialized_ids")))
    initialized_thread_author_keys = set(state_list(state.get("thread_author_initialized_keys")))
    posts: list[NgaPost] = []
    seen_in_fetch: set[str] = set()
    initialized_this_run = 0
    initialized_ai_posts: list[NgaPost] = []
    ai_backfill_posts: list[NgaPost] = []
    total_author_targets = len(author_targets)
    fetched_target_counts: list[tuple[str, int]] = []
    for target_index, target in enumerate(author_targets):
        try:
            target_posts = collect_posts_for_author_with_retries(args, target.id)
        except Exception as exc:
            if is_nga_service_unavailable(exc):
                raise NgaTemporaryUnavailable(
                    f"NGA 503 while watching {target_display_name(target)}; circuit-breaking current watch round.",
                    status_code=503,
                ) from exc
            raise
        sourced_posts: list[NgaPost] = []
        for post in target_posts:
            sourced = add_post_source(post, "author", target)
            sourced_posts.append(sourced)
        fetched_target_counts.append((target_display_name(target), len(sourced_posts)))
        if args.mark_seen:
            posts.extend(sourced_posts)
            initialized_author_ids.add(target.id)
            sleep_between_watch_targets(args, target_index, total_author_targets)
            continue

        if target.id not in initialized_author_ids:
            previously_seen_for_target = any(is_post_seen(seen, post) for post in sourced_posts)
            legacy_existing_target = not has_author_init_state and target_index == 0 and previously_seen_for_target
            if not legacy_existing_target:
                for post in sourced_posts:
                    mark_post_seen(seen, post)
                initialized_ai_posts.extend(sourced_posts)
                initialized_author_ids.add(target.id)
                initialized_this_run += len(sourced_posts)
                print(f"首次监听用户 {target_display_name(target)}，已把当前抓到的 {len(sourced_posts)} 条回复标记为已读。")
                sleep_between_watch_targets(args, target_index, total_author_targets)
                continue
            initialized_author_ids.add(target.id)

        if sourced_posts and not args.dry_run and ai_source_history_needs_backfill(args, target):
            ai_backfill_posts.extend(sourced_posts)

        for sourced in sourced_posts:
            identity = post_identity_key(sourced)
            if identity in seen_in_fetch:
                continue
            seen_in_fetch.add(identity)
            posts.append(sourced)
        sleep_between_watch_targets(args, target_index, total_author_targets)
    if author_due:
        state["last_author_watch_at"] = int(time.time())

    seeded_thread_author_ids: set[str] = set()
    if thread_watches:
        startup_catchup_done = bool(getattr(args, "_thread_author_startup_catchup_done", False))
        if not startup_catchup_done and not args.mark_seen:
            catchup_watches = [watch for watch in thread_watches if watch.key in initialized_thread_author_keys]
            try:
                catchup_posts, catchup_counts = collect_thread_author_startup_catchup_posts(args, catchup_watches)
                for sourced in catchup_posts:
                    identity = post_identity_key(sourced)
                    if identity in seen_in_fetch:
                        continue
                    seen_in_fetch.add(identity)
                    posts.append(sourced)
                fetched_target_counts.extend(catchup_counts)
                if catchup_watches:
                    print(f"启动补抓帖内作者用户回复完成：{sum(count for _, count in catchup_counts)} 条。")
            except Exception as exc:
                if is_nga_service_unavailable(exc):
                    raise NgaTemporaryUnavailable(
                        "NGA 503 while startup-catching thread-author targets; circuit-breaking current watch round.",
                        status_code=503,
                    ) from exc
                print(f"启动补抓帖内作者用户回复失败，继续执行帖内扫描: {exc}", file=sys.stderr)
            setattr(args, "_thread_author_startup_catchup_done", True)
        try:
            thread_posts, thread_counts = collect_thread_author_watch_posts(args, thread_watches)
        except Exception as exc:
            if is_nga_service_unavailable(exc):
                raise NgaTemporaryUnavailable(
                    "NGA 503 while watching thread-author targets; circuit-breaking current watch round.",
                    status_code=503,
                ) from exc
            raise
        fetched_target_counts.extend(thread_counts)
        for watch in thread_watches:
            watch_posts = [post for post in thread_posts if post.source_id == watch.key]
            if args.mark_seen:
                posts.extend(watch_posts)
                initialized_thread_author_keys.add(watch.key)
                continue
            if watch.key not in initialized_thread_author_keys:
                for post in watch_posts:
                    mark_post_seen(seen, post)
                initialized_ai_posts.extend(watch_posts)
                if watch.author_id not in seeded_thread_author_ids:
                    initialized_ai_posts.extend(collect_author_seed_posts_for_ai(args, watch.author_id, watch.label))
                    seeded_thread_author_ids.add(watch.author_id)
                initialized_thread_author_keys.add(watch.key)
                initialized_this_run += len(watch_posts)
                print(f"首次监听帖内作者 {thread_author_display_name(watch)}，已把当前抓到的 {len(watch_posts)} 条回复标记为已读。")
                continue
            if watch.author_id not in seeded_thread_author_ids and ai_source_history_needs_backfill(args, WatchTarget(watch.author_id, watch.label)):
                ai_backfill_posts.extend(collect_author_seed_posts_for_ai(args, watch.author_id, watch.label))
                seeded_thread_author_ids.add(watch.author_id)
            for sourced in watch_posts:
                identity = post_identity_key(sourced)
                if identity in seen_in_fetch:
                    continue
                seen_in_fetch.add(identity)
                posts.append(sourced)
        state["last_thread_author_watch_at"] = int(time.time())
    if args.mark_seen:
        for post in posts:
            mark_post_seen(seen, post)
        state["seen"] = sorted(seen)
        state["watch_author_initialized_ids"] = sorted(initialized_author_ids)
        state["thread_author_initialized_keys"] = sorted(initialized_thread_author_keys)
        state["updated_at"] = int(time.time())
        write_watcher_state(state_path, state)
        detail = format_target_fetch_counts(fetched_target_counts)
        suffix = f"（{detail}）" if detail else ""
        print(f"已标记 {len(posts)} 条已抓取回复为已读{suffix}。")
        return len(posts)

    new_posts = [post for post in posts if not is_post_seen(seen, post)]
    new_posts.sort(key=post_sort_key)

    quiet_now = is_quiet_time(args)
    quiet_policy = str(getattr(args, "quiet_policy", DEFAULT_QUIET_POLICY) or DEFAULT_QUIET_POLICY).strip().lower()
    if quiet_policy not in {"ignore", "defer"}:
        quiet_policy = DEFAULT_QUIET_POLICY

    quiet_posts = [post for post in new_posts if post_in_quiet_range(args, post)]
    deliver_posts = [post for post in new_posts if post not in quiet_posts]

    if quiet_posts:
        for post in quiet_posts:
            mark_post_seen(seen, post)
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
            mark_post_seen(seen, post)
        if args.dry_run:
            print(f"[试运行] 当前处于免打扰时段，本轮 {len(deliver_posts)} 条新回复不会推送。")
        else:
            print(f"当前处于免打扰时段，已标记 {len(deliver_posts)} 条非免打扰区间旧回复为已读，不纳入汇总。")
        deliver_posts = []

    ai_history_seed_posts = initialized_ai_posts + ai_backfill_posts
    if ai_history_seed_posts and not args.dry_run:
        save_posts_for_ai_history(args, ai_history_seed_posts)

    ai_pushed_posts: list[NgaPost] = []
    for post in new_posts:
        if post not in deliver_posts:
            continue
        if args.dry_run:
            print(f"[试运行] {post.subject} {post.url}\n{post.content[:500]}\n")
        else:
            push_to_feishu(args, post, mention_user_id)
            mark_post_seen(seen, post)
            ai_pushed_posts.append(post)

    if ai_pushed_posts:
        after_posts_pushed_for_ai(args, ai_pushed_posts)

    if not args.dry_run:
        state["seen"] = sorted(seen)
        state["watch_author_initialized_ids"] = sorted(initialized_author_ids)
        state["thread_author_initialized_keys"] = sorted(initialized_thread_author_keys)
        if initialized_this_run:
            state["watch_author_initialized_at"] = int(time.time())
        state["updated_at"] = int(time.time())
        write_watcher_state(state_path, state)
    pushed_count = 0 if quiet_now else len(deliver_posts)
    fetched_total = sum(count for _, count in fetched_target_counts)
    detail = format_target_fetch_counts(fetched_target_counts)
    suffix = f"（{detail}）" if detail else ""
    print(f"已抓取 {fetched_total} 条回复{suffix}，新回复 {len(new_posts)} 条，已推送 {pushed_count} 条。")
    return len(new_posts)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Watch an NGA user's replies and push new ones to Feishu or WeChat.")
    parser.add_argument("--bot-channel", choices=["feishu", "wechat"], default=os.getenv("NGA_BOT_CHANNEL", "feishu"))
    parser.add_argument("--author-id", default=os.getenv("NGA_AUTHOR_ID", DEFAULT_AUTHOR_ID))
    parser.add_argument("--author-ids", default=os.getenv("NGA_AUTHOR_IDS", ""), help="Comma or newline separated NGA user IDs to watch. Supports id=label.")
    parser.add_argument("--watch-mode", choices=["author", "thread_author", "both"], default=os.getenv("NGA_WATCH_MODE", "author"))
    parser.add_argument("--default-author-id", default=os.getenv("NGA_DEFAULT_AUTHOR_ID", DEFAULT_AUTHOR_ID))
    parser.add_argument("--default-tid", default=os.getenv("NGA_DEFAULT_TID", DEFAULT_TID))
    parser.add_argument("--preset-thread-ids", default=os.getenv("NGA_PRESET_TIDS", ""), help="Comma or newline separated thread presets. Supports tid=label.")
    parser.add_argument("--thread-author-watches", default=os.getenv("NGA_THREAD_AUTHOR_WATCHES", ""))
    parser.add_argument("--push-targets", default=os.getenv("NGA_PUSH_TARGETS", ""), help="JSON list of message push targets.")
    parser.add_argument("--listen-rules", default=os.getenv("NGA_LISTEN_RULES", ""), help="JSON list of NGA listen rules.")
    parser.add_argument("--thread-watch-tail-count", type=int, default=int(os.getenv("NGA_THREAD_WATCH_TAIL_COUNT", str(DEFAULT_THREAD_WATCH_TAIL_COUNT))))
    parser.add_argument("--thread-watch-interval", type=float, default=float(os.getenv("NGA_THREAD_WATCH_INTERVAL", str(DEFAULT_THREAD_WATCH_INTERVAL))))
    parser.add_argument("--max-pages", type=int, default=int(os.getenv("NGA_MAX_PAGES", "1")))
    parser.add_argument("--state-path", default=os.getenv("NGA_STATE_PATH", ".nga_seen.json"))
    parser.add_argument("--cookie", default="")
    parser.add_argument("--webhook", default="")
    parser.add_argument("--secret", default="")
    parser.add_argument("--feishu-app-id", default="")
    parser.add_argument("--feishu-app-secret", default="")
    parser.add_argument("--feishu-receive-id", default="")
    parser.add_argument("--feishu-id-type", default=os.getenv("FEISHU_ID_TYPE", "chat_id"))
    parser.add_argument("--feishu-bot-profiles", default=os.getenv("FEISHU_BOT_PROFILES", ""))
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mark-seen", action="store_true", help="把当前抓取到的回复记为已读，不推送。")
    parser.add_argument("--list-feishu-chats", action="store_true", help="列出飞书机器人可见的群组。")
    parser.add_argument("--send-test", action="store_true", help="发送一条飞书测试消息后退出。")
    parser.add_argument("--message-format", choices=["card", "text"], default=os.getenv("FEISHU_MESSAGE_FORMAT", "card"))
    parser.add_argument(
        "--feishu-card-images",
        action=argparse.BooleanOptionalAction,
        default=ai_analysis.env_bool("FEISHU_CARD_IMAGES", True),
        help="在飞书应用卡片中尝试直接显示 NGA 图片；失败时自动回退为图片链接。",
    )
    parser.add_argument(
        "--feishu-card-image-limit",
        type=int,
        default=int(os.getenv("FEISHU_CARD_IMAGE_LIMIT", str(DEFAULT_FEISHU_CARD_IMAGE_LIMIT))),
        help="每张飞书卡片最多内嵌上传的 NGA 图片数量。",
    )
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
    parser.add_argument("--wechat-bot-token", default=os.getenv("WECHAT_BOT_TOKEN", ""), help="微信 ilink bot Bearer token。")
    parser.add_argument("--wechat-bot-base-url", default=os.getenv("WECHAT_BOT_BASE_URL", wechat_bot.DEFAULT_WECHAT_BASE_URL))
    parser.add_argument("--wechat-bot-cdn-base-url", default=os.getenv("WECHAT_BOT_CDN_BASE_URL", wechat_bot.DEFAULT_WECHAT_CDN_BASE_URL))
    parser.add_argument("--wechat-bot-target-user-id", default=os.getenv("WECHAT_BOT_TARGET_USER_ID", ""))
    parser.add_argument("--wechat-bot-allowed-user-ids", default=os.getenv("WECHAT_BOT_ALLOWED_USER_IDS", ""))
    parser.add_argument("--wechat-bot-poll-timeout-ms", type=int, default=int(os.getenv("WECHAT_BOT_POLL_TIMEOUT_MS", str(wechat_bot.DEFAULT_WECHAT_POLL_TIMEOUT_MS))))
    parser.add_argument("--wechat-bot-route-tag", default=os.getenv("WECHAT_BOT_ROUTE_TAG", ""))
    parser.add_argument("--wechat-bot-account-id", default=os.getenv("WECHAT_BOT_ACCOUNT_ID", "default"))
    parser.add_argument("--wechat-bot-state-dir", default=os.getenv("WECHAT_BOT_STATE_DIR", ""))
    parser.add_argument("--wechat-bot-profiles", default=os.getenv("WECHAT_BOT_PROFILES", ""))
    parser.add_argument("--wechat-poll", action="store_true", help="使用微信 ilink 长轮询接收消息。bot_channel=wechat 时会自动启用。")
    parser.add_argument("--retries", type=int, default=int(os.getenv("NGA_RETRIES", "10")))
    parser.add_argument(
        "--retry-initial-delay",
        type=float,
        default=float(os.getenv("NGA_RETRY_INITIAL_DELAY", str(DEFAULT_RETRY_INITIAL_DELAY))),
        help="失败后第一次重试前等待的秒数。",
    )
    parser.add_argument("--retry-delay", type=float, default=float(os.getenv("NGA_RETRY_DELAY", "1")), help="每次失败后额外递增的重试等待秒数。")
    parser.add_argument("--nga-page-delay", type=float, default=float(os.getenv("NGA_PAGE_DELAY", str(DEFAULT_NGA_PAGE_DELAY))))
    parser.add_argument("--nga-request-min-interval", type=float, default=float(os.getenv("NGA_REQUEST_MIN_INTERVAL", str(DEFAULT_NGA_REQUEST_MIN_INTERVAL))))
    parser.add_argument("--nga-cache-ttl", type=float, default=float(os.getenv("NGA_CACHE_TTL", str(DEFAULT_NGA_CACHE_TTL))))
    parser.add_argument("--nga-target-min-delay", type=float, default=float(os.getenv("NGA_TARGET_MIN_DELAY", str(DEFAULT_NGA_TARGET_MIN_DELAY))))
    parser.add_argument("--nga-target-max-delay", type=float, default=float(os.getenv("NGA_TARGET_MAX_DELAY", str(DEFAULT_NGA_TARGET_MAX_DELAY))))
    parser.add_argument(
        "--nga-unavailable-backoff-base",
        type=float,
        default=float(os.getenv("NGA_UNAVAILABLE_BACKOFF_BASE", str(DEFAULT_NGA_UNAVAILABLE_BACKOFF_BASE))),
    )
    parser.add_argument(
        "--nga-unavailable-backoff-max",
        type=float,
        default=float(os.getenv("NGA_UNAVAILABLE_BACKOFF_MAX", str(DEFAULT_NGA_UNAVAILABLE_BACKOFF_MAX))),
    )
    parser.add_argument("--interval", type=int, default=int(os.getenv("NGA_INTERVAL", "30")))
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
    parser.add_argument("--ai-schedule-target-ids", default=os.getenv("AI_SCHEDULE_TARGET_IDS", ""), help="Comma separated push target ids that should receive one shared scheduled AI result.")
    return parser.parse_args()


def normalize_multi_target_defaults(args: argparse.Namespace) -> None:
    author_targets = watch_author_targets(args)
    thread_targets = preset_thread_targets(args)
    if author_targets:
        args.author_id = author_targets[0].id
        args.default_author_id = author_targets[0].id
    if thread_targets:
        args.default_tid = thread_targets[0].id


def main() -> None:
    args = parse_args()
    normalize_multi_target_defaults(args)
    if uses_structured_routes(args) and not (args.once or args.mark_seen or args.send_test or args.list_feishu_chats):
        start_multi_channel(args)
        return
    if args.ws and not is_wechat_channel(args):
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
    if is_wechat_channel(args) and not args.once:
        start_wechat_poll(args)
        return

    service_unavailable_failures = 0
    while True:
        round_error: Exception | None = None
        try:
            state_path = Path(args.state_path)
            state = read_json(state_path, {"seen": []})
            try:
                if is_wechat_channel(args):
                    changed = handle_wechat_commands(args)
                else:
                    changed = handle_feishu_commands(args, state)
                if changed:
                    write_watcher_state(state_path, state)
            except Exception as exc:
                print(f"{bot_channel(args)} 命令轮询失败: {exc}", file=sys.stderr)
            run_once(args)
            maybe_run_ai_schedule(args)
            service_unavailable_failures = 0
        except Exception as exc:
            round_error = exc
            if is_nga_service_unavailable(exc):
                service_unavailable_failures += 1
            else:
                service_unavailable_failures = 0
            print(f"错误: {exc}", file=sys.stderr)
            if args.once:
                raise SystemExit(1)
        if args.once:
            return
        sleep_for = watch_sleep_seconds(args, round_error, service_unavailable_failures)
        if round_error is not None and is_nga_service_unavailable(round_error):
            print(f"NGA 503 backoff: next watch round in {sleep_for:.1f}s", file=sys.stderr)
        time.sleep(sleep_for)


if __name__ == "__main__":
    main()
