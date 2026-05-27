#!/usr/bin/env python3
"""Optional local AI agent support for NGA Wolf Watcher.

This module is deliberately self-contained and uses only the standard library.
The watcher can import it unconditionally; no Codex, Claude, Node.js, API key,
or other AI dependency is required unless the user explicitly enables AI tasks.
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import datetime as dt
import json
import logging
import mimetypes
import os
import queue
import re
import shutil
import shlex
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


DEFAULT_WORK_DIR = ".ai_agent_workspace"
DEFAULT_PROVIDER = "codex"
DEFAULT_HISTORY_LIMIT = 50
DEFAULT_TIMEOUT = 300
DEFAULT_SCHEDULE_WINDOWS = "weekday:09:30-11:30,13:00-15:00"
DEFAULT_MAX_FEISHU_CHARS = 3500
SOURCE_NAME = "nga-wolf-watcher"
CODEX_DEFAULT_MODEL = "gpt-5.5"
CLAUDE_DEFAULT_MODEL = "sonnet"
CODEWHALE_DEFAULT_MODEL = "deepseek-v4-pro"
CODEX_DEFAULT_REASONING_EFFORT = "medium"
CLAUDE_DEFAULT_REASONING_EFFORT = "medium"
CODEWHALE_DEFAULT_REASONING_EFFORT = "auto"
CODEX_MODEL_OPTIONS = [CODEX_DEFAULT_MODEL, "gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex", "gpt-5.3-codex-spark", "gpt-5.2"]
CLAUDE_MODEL_OPTIONS = [CLAUDE_DEFAULT_MODEL, "default", "opus[1m]", "haiku"]
CODEX_REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
CLAUDE_REASONING_EFFORTS = {"low", "medium", "high", "max"}
CODEWHALE_MODEL_OPTIONS = [CODEWHALE_DEFAULT_MODEL, "deepseek-v4-flash"]
CODEWHALE_REASONING_EFFORTS = {"auto", "off", "high", "max"}

DEFAULT_AUTO_ANALYSIS_PROMPT = "根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。"
DEFAULT_STOCK_ANALYSIS_PROMPT = DEFAULT_AUTO_ANALYSIS_PROMPT
DEFAULT_SCHEDULED_ANALYSIS_PROMPT = DEFAULT_AUTO_ANALYSIS_PROMPT
DEFAULT_MEMORY = """# NGA Wolf Watcher local memory

这个工作目录只记录本地上下文位置，不强制每次回复套用固定报告格式。

- NGA 最新回复：`events/latest_event.json`
- NGA 回复历史：`events/wolf_history.jsonl`
- NGA 来源索引：`events/source_index.json`，记录“狼大”“海”等备注对应的来源 ID 和历史文件
- NGA 按来源历史：`events/by_source/author_<id>.jsonl`，当用户点名某个备注或用户时优先读取对应文件
- NGA 回复图片：事件 JSON 里的 `image_urls` 是原图链接，`image_paths` 是已下载到本地的图片文件
- 我的持仓信息：`context/positions.json`
- 行情信息：需要时实时查询公开网页或公开 API
- 接下来重点观察：`context/watchlist.md`
- 其他补充笔记：`context/notes.md`

使用偏好：

- 普通聊天直接回答用户问题。
- 自动分析和定时分析按对应提示词执行即可，不需要输出复杂固定模板。
- 可以给观察重点、风险提示、仓位和操作思路，但不要替用户做最终买卖决定，也不要声称已经下单。
- 不要暴露 Cookie、飞书密钥、账号凭证或完整私密文件。
"""

def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def safe_int(value: Any, default: int, minimum: int | None = None) -> int:
    try:
        result = int(str(value).strip())
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    return result


def csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def provider_model_env(provider: str) -> str:
    generic = os.getenv("AI_MODEL")
    if generic is not None:
        return generic
    if provider == "codex":
        return os.getenv("AI_CODEX_MODEL", "")
    if provider == "claude":
        return os.getenv("AI_CLAUDE_MODEL", "")
    if provider == "codewhale":
        return os.getenv("AI_CODEWHALE_MODEL", "")
    return os.getenv("AI_CUSTOM_MODEL", "")


def provider_reasoning_env(provider: str) -> str:
    generic = os.getenv("AI_REASONING_EFFORT")
    if generic is not None:
        return generic
    if provider == "codex":
        return os.getenv("AI_CODEX_REASONING_EFFORT", "")
    if provider == "claude":
        return os.getenv("AI_CLAUDE_EFFORT", "")
    if provider == "codewhale":
        return os.getenv("AI_CODEWHALE_REASONING_EFFORT", "")
    return os.getenv("AI_CUSTOM_REASONING_EFFORT", "")


def normalize_model(raw: str) -> str:
    text = str(raw or "").strip()
    if text.lower() in {"unset"}:
        return ""
    return text


def provider_default_model(provider: str) -> str:
    if provider == "claude":
        return CLAUDE_DEFAULT_MODEL
    if provider == "codewhale":
        return CODEWHALE_DEFAULT_MODEL
    if provider == "codex":
        return CODEX_DEFAULT_MODEL
    return ""


def provider_default_reasoning_effort(provider: str) -> str:
    if provider == "claude":
        return CLAUDE_DEFAULT_REASONING_EFFORT
    if provider == "codewhale":
        return CODEWHALE_DEFAULT_REASONING_EFFORT
    if provider == "codex":
        return CODEX_DEFAULT_REASONING_EFFORT
    return ""


def normalize_provider_model(provider: str, raw: str) -> str:
    model = normalize_model(raw)
    if not model:
        return ""
    if model.lower() == "default":
        return "default" if provider == "claude" else provider_default_model(provider)
    if model.lower() == "auto":
        return ""
    if provider == "custom":
        return model
    options = model_options(provider)
    if not options:
        return model
    for option in options:
        if model.lower() == option.lower():
            return option
    return ""


def model_for_cli(provider: str, raw: str) -> str:
    model = normalize_provider_model(provider, raw)
    return "" if model == "default" else model


def is_valid_model(raw: str, provider: str = "codex") -> bool:
    text = normalize_model(raw)
    if not text:
        return True
    if text.lower() == "default":
        return provider == "claude"
    if text.lower() == "auto":
        return True
    if provider == "custom":
        return True
    options = model_options(provider)
    return not options or any(text.lower() == option.lower() for option in options)


def model_options(provider: str = "codex") -> list[str]:
    if provider == "claude":
        return list(CLAUDE_MODEL_OPTIONS)
    if provider == "codex":
        return list(CODEX_MODEL_OPTIONS)
    if provider == "codewhale":
        return list(CODEWHALE_MODEL_OPTIONS)
    return []


def model_label(provider: str, value: str) -> str:
    if provider == "codex":
        return {
            "gpt-5.5": "GPT-5.5",
            "gpt-5.4": "GPT-5.4",
            "gpt-5.4-mini": "GPT-5.4-Mini",
            "gpt-5.3-codex": "GPT-5.3-Codex",
            "gpt-5.3-codex-spark": "GPT-5.3-Codex-Spark",
            "gpt-5.2": "GPT-5.2",
        }.get(value, value)
    return value


def reasoning_effort_options(provider: str = "codex") -> list[str]:
    if provider == "claude":
        return sorted(CLAUDE_REASONING_EFFORTS, key=["low", "medium", "high", "max"].index)
    if provider == "codex":
        return sorted(CODEX_REASONING_EFFORTS, key=["low", "medium", "high", "xhigh"].index)
    if provider == "codewhale":
        return sorted(CODEWHALE_REASONING_EFFORTS, key=["auto", "off", "high", "max"].index)
    return []


def reasoning_effort_label(provider: str, value: str) -> str:
    return value


def normalize_reasoning_effort(raw: str, provider: str = "codex") -> str:
    text = str(raw or "").strip().lower()
    if text in {"", "default", "unset"}:
        return ""
    if text == "auto" and provider != "codewhale":
        return ""
    if provider == "claude" and text == "xhigh":
        return "max"
    options = reasoning_effort_options(provider)
    if options and text not in options:
        return ""
    return text


def is_valid_reasoning_effort(raw: str, provider: str = "codex") -> bool:
    text = str(raw or "").strip().lower()
    if text in {"", "default", "auto", "unset"}:
        return True
    if provider == "claude" and text == "xhigh":
        return True
    options = reasoning_effort_options(provider)
    return not options or text in options


@dataclass
class AIConfig:
    enabled: bool = False
    provider: str = DEFAULT_PROVIDER
    work_dir: Path = Path(DEFAULT_WORK_DIR)
    auto_analyze_new_post: bool = False
    auto_analysis_prompt: str = ""
    prompt_file: str = ""
    history_limit: int = DEFAULT_HISTORY_LIMIT
    timeout: int = DEFAULT_TIMEOUT
    codex_command: str = "codex"
    claude_command: str = "claude"
    codewhale_command: str = "codewhale"
    custom_command: str = ""
    schedule_enabled: bool = False
    schedule_interval_minutes: int = 5
    schedule_prompt: str = ""
    schedule_prompt_file: str = ""
    schedule_windows: str = DEFAULT_SCHEDULE_WINDOWS
    allowed_user_ids: set[str] = field(default_factory=set)
    send_errors_to_feishu: bool = False
    max_feishu_chars: int = DEFAULT_MAX_FEISHU_CHARS
    upload_long_result: bool = False
    permission_mode: str = "default"
    model: str = ""
    reasoning_effort: str = ""
    ignore_codex_user_config: bool = False

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "AIConfig":
        provider = str(getattr(args, "ai_provider", os.getenv("AI_PROVIDER", DEFAULT_PROVIDER)) or DEFAULT_PROVIDER).lower()
        if provider not in {"codex", "claude", "codewhale", "custom"}:
            provider = DEFAULT_PROVIDER
        raw_model = getattr(args, "ai_model", None)
        if raw_model is None or not str(raw_model).strip():
            raw_model = provider_model_env(provider)
        raw_reasoning = getattr(args, "ai_reasoning_effort", None)
        if raw_reasoning is None or not str(raw_reasoning).strip():
            raw_reasoning = provider_reasoning_env(provider)
        work_dir = resolve_work_dir(
            str(getattr(args, "ai_work_dir", os.getenv("AI_WORK_DIR", DEFAULT_WORK_DIR)) or DEFAULT_WORK_DIR),
            getattr(args, "state_path", ""),
        )
        return cls(
            enabled=bool_value(getattr(args, "ai_enabled", env_bool("AI_ENABLED", False))),
            provider=provider,
            work_dir=work_dir,
            auto_analyze_new_post=bool_value(
                getattr(args, "ai_auto_analyze_new_post", env_bool("AI_AUTO_ANALYZE_NEW_POST", False))
            ),
            auto_analysis_prompt=str(getattr(args, "ai_auto_analysis_prompt", os.getenv("AI_AUTO_ANALYSIS_PROMPT", "")) or ""),
            prompt_file=str(getattr(args, "ai_prompt_file", os.getenv("AI_PROMPT_FILE", "")) or ""),
            history_limit=safe_int(getattr(args, "ai_history_limit", os.getenv("AI_HISTORY_LIMIT", DEFAULT_HISTORY_LIMIT)), DEFAULT_HISTORY_LIMIT, 1),
            timeout=safe_int(getattr(args, "ai_timeout", os.getenv("AI_TIMEOUT", DEFAULT_TIMEOUT)), DEFAULT_TIMEOUT, 1),
            codex_command=str(getattr(args, "ai_codex_command", os.getenv("AI_CODEX_COMMAND", "codex")) or "codex"),
            claude_command=str(getattr(args, "ai_claude_command", os.getenv("AI_CLAUDE_COMMAND", "claude")) or "claude"),
            codewhale_command=str(getattr(args, "ai_codewhale_command", os.getenv("AI_CODEWHALE_COMMAND", "codewhale")) or "codewhale"),
            custom_command=str(getattr(args, "ai_custom_command", os.getenv("AI_CUSTOM_COMMAND", "")) or ""),
            schedule_enabled=bool_value(getattr(args, "ai_schedule_enabled", env_bool("AI_SCHEDULE_ENABLED", False))),
            schedule_interval_minutes=safe_int(
                getattr(args, "ai_schedule_interval_minutes", os.getenv("AI_SCHEDULE_INTERVAL_MINUTES", "5")), 5, 1
            ),
            schedule_prompt=str(getattr(args, "ai_schedule_prompt", os.getenv("AI_SCHEDULE_PROMPT", "")) or ""),
            schedule_prompt_file=str(getattr(args, "ai_schedule_prompt_file", os.getenv("AI_SCHEDULE_PROMPT_FILE", "")) or ""),
            schedule_windows=str(
                getattr(args, "ai_schedule_windows", os.getenv("AI_SCHEDULE_WINDOWS", DEFAULT_SCHEDULE_WINDOWS))
                or DEFAULT_SCHEDULE_WINDOWS
            ),
            allowed_user_ids=csv_set(str(getattr(args, "ai_allowed_user_ids", os.getenv("AI_ALLOWED_USER_IDS", "")) or "")),
            send_errors_to_feishu=bool_value(getattr(args, "ai_send_errors_to_feishu", env_bool("AI_SEND_ERRORS_TO_FEISHU", False))),
            max_feishu_chars=safe_int(
                getattr(args, "ai_max_feishu_chars", os.getenv("AI_MAX_FEISHU_CHARS", DEFAULT_MAX_FEISHU_CHARS)),
                DEFAULT_MAX_FEISHU_CHARS,
                200,
            ),
            upload_long_result=bool_value(getattr(args, "ai_upload_long_result", env_bool("AI_UPLOAD_LONG_RESULT", False))),
            permission_mode=normalize_permission_mode(
                str(getattr(args, "ai_permission_mode", os.getenv("AI_PERMISSION_MODE", "default")) or "default"),
                provider,
            ),
            model=normalize_provider_model(provider, str(raw_model or "")),
            reasoning_effort=normalize_reasoning_effort(
                str(raw_reasoning or ""),
                provider,
            ),
            ignore_codex_user_config=bool_value(
                getattr(args, "ai_ignore_codex_user_config", env_bool("AI_IGNORE_CODEX_USER_CONFIG", False))
            ),
        )


def resolve_work_dir(raw_work_dir: str, state_path: str | os.PathLike[str] | None = None) -> Path:
    path = Path(raw_work_dir or DEFAULT_WORK_DIR)
    if path.is_absolute():
        return path
    state_text = str(state_path or "")
    if state_text:
        state_parent = Path(state_text).expanduser().parent
        if state_parent != Path("."):
            return state_parent / path
    return path


@dataclass
class AITask:
    task_type: str
    user_prompt: str
    latest_event: Path
    history_file: Path
    output_file: Path
    work_dir: Path
    timeout: int
    image_paths: list[Path] = field(default_factory=list)
    file_paths: list[Path] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AIResult:
    ok: bool
    provider: str
    task_type: str
    output_file: Path
    text: str = ""
    error: str = ""
    exit_code: int | None = None
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: float = 0.0
    stdout: str = ""
    stderr: str = ""


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--ai-enabled", action="store_true", default=env_bool("AI_ENABLED", False))
    parser.add_argument("--ai-provider", choices=["codex", "claude", "codewhale", "custom"], default=os.getenv("AI_PROVIDER", DEFAULT_PROVIDER))
    parser.add_argument("--ai-work-dir", default=os.getenv("AI_WORK_DIR", DEFAULT_WORK_DIR))
    parser.add_argument("--ai-auto-analyze-new-post", action="store_true", default=env_bool("AI_AUTO_ANALYZE_NEW_POST", False))
    parser.add_argument("--ai-auto-analysis-prompt", default=os.getenv("AI_AUTO_ANALYSIS_PROMPT", ""))
    parser.add_argument("--ai-prompt-file", default=os.getenv("AI_PROMPT_FILE", ""))
    parser.add_argument("--ai-history-limit", type=int, default=int(os.getenv("AI_HISTORY_LIMIT", str(DEFAULT_HISTORY_LIMIT))))
    parser.add_argument("--ai-timeout", type=int, default=int(os.getenv("AI_TIMEOUT", str(DEFAULT_TIMEOUT))))
    parser.add_argument("--ai-codex-command", default=os.getenv("AI_CODEX_COMMAND", "codex"))
    parser.add_argument("--ai-claude-command", default=os.getenv("AI_CLAUDE_COMMAND", "claude"))
    parser.add_argument("--ai-codewhale-command", default=os.getenv("AI_CODEWHALE_COMMAND", "codewhale"))
    parser.add_argument("--ai-custom-command", default=os.getenv("AI_CUSTOM_COMMAND", ""))
    parser.add_argument("--ai-schedule-enabled", action="store_true", default=env_bool("AI_SCHEDULE_ENABLED", False))
    parser.add_argument("--ai-schedule-interval-minutes", type=int, default=int(os.getenv("AI_SCHEDULE_INTERVAL_MINUTES", "5")))
    parser.add_argument("--ai-schedule-prompt", default=os.getenv("AI_SCHEDULE_PROMPT", ""))
    parser.add_argument("--ai-schedule-prompt-file", default=os.getenv("AI_SCHEDULE_PROMPT_FILE", ""))
    parser.add_argument("--ai-schedule-windows", default=os.getenv("AI_SCHEDULE_WINDOWS", DEFAULT_SCHEDULE_WINDOWS))
    parser.add_argument("--ai-allowed-user-ids", default=os.getenv("AI_ALLOWED_USER_IDS", ""))
    parser.add_argument("--ai-send-errors-to-feishu", action="store_true", default=env_bool("AI_SEND_ERRORS_TO_FEISHU", False))
    parser.add_argument("--ai-max-feishu-chars", type=int, default=int(os.getenv("AI_MAX_FEISHU_CHARS", str(DEFAULT_MAX_FEISHU_CHARS))))
    parser.add_argument("--ai-upload-long-result", action="store_true", default=env_bool("AI_UPLOAD_LONG_RESULT", False))
    parser.add_argument("--ai-permission-mode", default=os.getenv("AI_PERMISSION_MODE", "default"))
    parser.add_argument("--ai-model", default=os.getenv("AI_MODEL", ""))
    parser.add_argument("--ai-reasoning-effort", default=os.getenv("AI_REASONING_EFFORT", ""))
    parser.add_argument(
        "--ai-ignore-codex-user-config",
        action=argparse.BooleanOptionalAction,
        default=env_bool("AI_IGNORE_CODEX_USER_CONFIG", False),
    )


def utcish_now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def parse_state_timestamp(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return 0.0


def safe_key(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", value or "event").strip("._-")
    return (text or "event")[:80]


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")
    tmp.replace(path)


def append_jsonl_unique(path: Path, event: dict[str, Any]) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(event.get("canonical_key") or event.get("key") or "")
    if key and path.exists():
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue
                existing_key = str(existing.get("canonical_key") or existing.get("key") or "")
                if existing_key == key:
                    return False
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False, sort_keys=True))
        f.write("\n")
    return True


def tail_jsonl(path: Path, limit: int) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    items: list[dict[str, Any]] = []
    for line in lines[-limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            items.append(value)
    return items


def event_source_type(event: dict[str, Any]) -> str:
    if str(event.get("author_id") or "").strip():
        return "author"
    return str(event.get("watch_source_type") or "author").strip() or "author"


def event_source_id(event: dict[str, Any]) -> str:
    return str(event.get("author_id") or event.get("watch_source_id") or "").strip()


def event_source_label(event: dict[str, Any]) -> str:
    return str(event.get("watch_source_label") or event.get("author") or event_source_id(event)).strip()


def event_source_key(event: dict[str, Any]) -> str:
    source_id = event_source_id(event)
    if not source_id:
        return ""
    return f"{safe_key(event_source_type(event))}_{safe_key(source_id)}"


def source_history_path(work_dir: Path, event: dict[str, Any]) -> Path | None:
    key = event_source_key(event)
    if not key:
        return None
    return work_dir / "events" / "by_source" / f"{key}.jsonl"


def legacy_source_history_path(work_dir: Path, event: dict[str, Any]) -> Path | None:
    watch_source_id = str(event.get("watch_source_id") or "").strip()
    watch_source_type = str(event.get("watch_source_type") or "").strip()
    if not watch_source_id or not watch_source_type or event_source_type(event) != "author":
        return None
    legacy_key = f"{safe_key(watch_source_type)}_{safe_key(watch_source_id)}"
    current_key = event_source_key(event)
    if not legacy_key or legacy_key == current_key:
        return None
    return work_dir / "events" / "by_source" / f"{legacy_key}.jsonl"


def migrate_legacy_source_history(work_dir: Path, event: dict[str, Any], destination: Path) -> None:
    legacy_path = legacy_source_history_path(work_dir, event)
    if legacy_path is None or legacy_path == destination or not legacy_path.exists():
        return
    author_id = str(event.get("author_id") or "").strip()
    author = str(event.get("author") or "").strip()
    with legacy_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            try:
                legacy_event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(legacy_event, dict):
                continue
            if author_id and not str(legacy_event.get("author_id") or "").strip():
                legacy_event["author_id"] = author_id
            if author and not str(legacy_event.get("author") or "").strip():
                legacy_event["author"] = author
            legacy_key = str(legacy_event.get("key") or "")
            if legacy_key.startswith("thread_author:") and not str(legacy_event.get("canonical_key") or "").strip():
                parts = legacy_key.split(":", 3)
                if len(parts) == 4 and parts[3]:
                    legacy_event["canonical_key"] = parts[3]
            append_jsonl_unique(destination, legacy_event)


def update_source_index(work_dir: Path, event: dict[str, Any], history_path: Path) -> None:
    key = event_source_key(event)
    source_id = event_source_id(event)
    if not key or not source_id:
        return
    index_path = work_dir / "events" / "source_index.json"
    index = read_json(index_path, {})
    if not isinstance(index, dict):
        index = {}
    sources = index.get("sources")
    if not isinstance(sources, dict):
        sources = {}
    label = event_source_label(event)
    aliases = {source_id}
    if label:
        aliases.add(label)
    for alias_key in ("author", "watch_source_id", "watch_source_label", "subject"):
        alias = str(event.get(alias_key) or "").strip()
        if alias:
            aliases.add(alias)
    watch_source_id = str(event.get("watch_source_id") or "").strip()
    watch_source_type = str(event.get("watch_source_type") or "").strip()
    watch_source_label = str(event.get("watch_source_label") or "").strip()
    legacy_key = ""
    if watch_source_id and watch_source_type and event_source_type(event) == "author":
        legacy_key = f"{safe_key(watch_source_type)}_{safe_key(watch_source_id)}"
    legacy_existing = sources.pop(legacy_key, None) if legacy_key and legacy_key != key else None
    existing = sources.get(key)
    if isinstance(existing, dict):
        for alias in existing.get("aliases") or []:
            if str(alias).strip():
                aliases.add(str(alias).strip())
    if isinstance(legacy_existing, dict):
        for alias in legacy_existing.get("aliases") or []:
            if str(alias).strip():
                aliases.add(str(alias).strip())
    watch_sources = []
    if isinstance(existing, dict) and isinstance(existing.get("watch_sources"), list):
        watch_sources.extend(item for item in existing.get("watch_sources") if isinstance(item, dict))
    if isinstance(legacy_existing, dict) and isinstance(legacy_existing.get("watch_sources"), list):
        watch_sources.extend(item for item in legacy_existing.get("watch_sources") if isinstance(item, dict))
    if watch_source_id or watch_source_type or watch_source_label:
        watch_item = {
            "source_type": watch_source_type,
            "source_id": watch_source_id,
            "label": watch_source_label,
            "subject": str(event.get("subject") or ""),
        }
        if watch_item not in watch_sources:
            watch_sources.append(watch_item)
    sources[key] = {
        "key": key,
        "source_type": event_source_type(event),
        "source_id": source_id,
        "label": label,
        "aliases": sorted(aliases),
        "watch_sources": watch_sources[-20:],
        "history_file": str(history_path.relative_to(work_dir)),
        "latest_event_at": event.get("post_time") or event.get("captured_at") or "",
        "latest_event_key": event.get("key") or "",
        "updated_at": utcish_now(),
    }
    index["sources"] = sources
    index["updated_at"] = utcish_now()
    write_json(index_path, index)


def source_index_summary(work_dir: Path) -> str:
    index_path = work_dir / "events" / "source_index.json"
    index = read_json(index_path, {})
    sources = index.get("sources") if isinstance(index, dict) else {}
    if not isinstance(sources, dict) or not sources:
        return ""
    lines = [
        "NGA author history files:",
        f"- source index: {index_path.resolve()}",
    ]
    for item in sorted(sources.values(), key=lambda value: str(value.get("label") or value.get("source_id") or "")):
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("source_id") or "")
        source_id = str(item.get("source_id") or "")
        author_source_id = source_id
        history_file = work_dir / str(item.get("history_file") or "")
        aliases = ", ".join(str(alias) for alias in item.get("aliases") or [] if str(alias).strip())
        watch_sources = item.get("watch_sources") if isinstance(item.get("watch_sources"), list) else []
        watch_hint = ""
        if watch_sources:
            hints = []
            for source in watch_sources[-3:]:
                if not isinstance(source, dict):
                    continue
                watch_source_id = str(source.get("source_id") or "").strip()
                subject = str(source.get("subject") or "").strip()
                if watch_source_id and subject:
                    hints.append(f"{watch_source_id} {subject}")
                elif watch_source_id:
                    hints.append(watch_source_id)
            if hints:
                watch_hint = "; watch sources: " + " | ".join(hints)
        lines.append(f"- {label} ({author_source_id}): {history_file.resolve()}; aliases: {aliases}{watch_hint}")
    lines.append("If the user names a source label such as 狼大 or 海, read that author's history file first, then use the global history only for comparison.")
    return "\n".join(lines)


def ensure_workspace(config: AIConfig) -> None:
    work_dir = config.work_dir
    for name in ("events", "analysis", "prompts", "context", "logs", "attachments"):
        (work_dir / name).mkdir(parents=True, exist_ok=True)
    (work_dir / "events" / "by_source").mkdir(parents=True, exist_ok=True)
    default_prompt = work_dir / "prompts" / "default_stock_analysis.md"
    scheduled_prompt = work_dir / "prompts" / "scheduled_analysis.md"
    if not default_prompt.exists():
        default_prompt.write_text(DEFAULT_STOCK_ANALYSIS_PROMPT, encoding="utf-8")
    else:
        existing_default = default_prompt.read_text(encoding="utf-8", errors="replace")
        if "# NGA wolf post analysis" in existing_default or "## 狼大发言要点" in existing_default:
            default_prompt.write_text(DEFAULT_STOCK_ANALYSIS_PROMPT, encoding="utf-8")
    if not scheduled_prompt.exists():
        scheduled_prompt.write_text(DEFAULT_SCHEDULED_ANALYSIS_PROMPT, encoding="utf-8")
    else:
        existing_scheduled = scheduled_prompt.read_text(encoding="utf-8", errors="replace")
        if "# Intraday scheduled market review" in existing_scheduled or "## 盘面变化摘要" in existing_scheduled:
            scheduled_prompt.write_text(DEFAULT_SCHEDULED_ANALYSIS_PROMPT, encoding="utf-8")
    memory = work_dir / "context" / "memory.md"
    if not memory.exists():
        memory.write_text(DEFAULT_MEMORY, encoding="utf-8")
    else:
        existing_memory = memory.read_text(encoding="utf-8", errors="replace")
        if "Default role:" in existing_memory or "Useful local files" in existing_memory:
            memory.write_text(DEFAULT_MEMORY, encoding="utf-8")
        elif "image_urls" not in existing_memory and "image_paths" not in existing_memory:
            memory.write_text(
                existing_memory.rstrip()
                + "\n\n- NGA 回复图片：事件 JSON 里的 `image_urls` 是原图链接，`image_paths` 是已下载到本地的图片文件。\n",
                encoding="utf-8",
            )
        elif "source_index.json" not in existing_memory:
            memory.write_text(
                existing_memory.rstrip()
                + "\n\n- NGA 来源索引：`events/source_index.json`，记录“狼大”“海”等备注对应的来源 ID 和历史文件。\n"
                + "- NGA 按来源历史：`events/by_source/author_<id>.jsonl`，当用户点名某个备注或用户时优先读取对应文件。\n",
                encoding="utf-8",
            )
    agents_md = work_dir / "AGENTS.md"
    if not agents_md.exists():
        agents_md.write_text(
            "Use `context/memory.md` as optional local memory for this workspace. "
            "Do not inject it into every answer; read it only when useful for the user's request.\n"
            "When current A-share quotes are needed, query public web pages or public APIs in real time.\n"
            "When the user names a monitored NGA source label such as 狼大 or 海, use `events/source_index.json` "
            "to resolve the label and read the matching `events/by_source/*.jsonl` history first.\n",
            encoding="utf-8",
        )
    else:
        existing_agents = agents_md.read_text(encoding="utf-8", errors="replace")
        if "current A-share quotes" not in existing_agents and "公开 A 股行情" not in existing_agents:
            with agents_md.open("a", encoding="utf-8") as f:
                f.write(
                    "\nWhen current A-share quotes are needed, query public web pages or public APIs in real time.\n"
                )
        if "source_index.json" not in existing_agents:
            with agents_md.open("a", encoding="utf-8") as f:
                f.write(
                    "\nWhen the user names a monitored NGA source label such as 狼大 or 海, use `events/source_index.json` "
                    "to resolve the label and read the matching `events/by_source/*.jsonl` history first.\n"
                )
    readme = work_dir / "context" / "README.md"
    if not readme.exists():
        readme.write_text(
            "Put optional local context here. Supported files: positions.json, watchlist.md, notes.md.\n"
            "Do not put credentials, cookies, or Feishu secrets in this directory.\n",
            encoding="utf-8",
        )
    watchlist = work_dir / "context" / "watchlist.md"
    if not watchlist.exists():
        watchlist.write_text("", encoding="utf-8")
    configure_logger(work_dir)


def configure_logger(work_dir: Path) -> logging.Logger:
    logger = logging.getLogger("nga_wolf_ai")
    logger.setLevel(logging.INFO)
    if not any(isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == str(work_dir / "logs" / "ai_agent.log") for handler in logger.handlers):
        (work_dir / "logs").mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(work_dir / "logs" / "ai_agent.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def event_from_post(post: Any) -> dict[str, Any]:
    image_urls = getattr(post, "image_urls", ()) or ()
    return {
        "key": str(getattr(post, "key", "")),
        "subject": str(getattr(post, "subject", "")),
        "content": str(getattr(post, "content", "")),
        "url": str(getattr(post, "url", "")),
        "canonical_key": str(getattr(post, "canonical_key", "") or getattr(post, "key", "")),
        "image_urls": [str(url) for url in image_urls if str(url).strip()],
        "image_paths": [],
        "post_time": str(getattr(post, "post_time", "")),
        "author": str(getattr(post, "author", "")),
        "author_id": str(getattr(post, "author_id", "")),
        "floor": str(getattr(post, "floor", "")),
        "watch_source_type": str(getattr(post, "source_type", "")),
        "watch_source_id": str(getattr(post, "source_id", "")),
        "watch_source_label": str(getattr(post, "source_label", "")),
        "captured_at": utcish_now(),
        "source": SOURCE_NAME,
    }


def image_suffix_from_url(url: str, content_type: str = "") -> str:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}:
        return suffix
    content_type = content_type.lower()
    if "png" in content_type:
        return ".png"
    if "gif" in content_type:
        return ".gif"
    if "webp" in content_type:
        return ".webp"
    if "bmp" in content_type:
        return ".bmp"
    return ".jpg"


def download_image(url: str, output_path: Path, timeout: int = 20) -> Path:
    headers = {
        "User-Agent": "Mozilla/5.0 nga-wolf-watcher",
        "Referer": "https://bbs.nga.cn/",
    }
    cookie = os.getenv("NGA_COOKIE", "").strip()
    if cookie:
        headers["Cookie"] = cookie
    candidates = [url]
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme == "https" and parsed.netloc.lower().endswith("nga.178.com"):
        candidates.append(urllib.parse.urlunparse(parsed._replace(scheme="http")))

    last_error: Exception | None = None
    for candidate_url in candidates:
        request = urllib.request.Request(
            candidate_url,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
                content_type = response.headers.get("Content-Type", "")
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
    suffix = image_suffix_from_url(url, content_type)
    if output_path.suffix.lower() != suffix:
        output_path = output_path.with_suffix(suffix)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(data)
    return output_path


def image_paths_from_event(event: dict[str, Any]) -> list[Path]:
    paths: list[Path] = []
    for raw in event.get("image_paths") or []:
        path = Path(str(raw))
        if path.exists() and path.is_file():
            paths.append(path)
    return paths


def split_command_line(command: str) -> list[str]:
    command = command.strip()
    if not command:
        return []
    if os.name != "nt":
        return shlex.split(command)
    argc = ctypes.c_int()
    ctypes.windll.shell32.CommandLineToArgvW.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
    ctypes.windll.shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    argv = ctypes.windll.shell32.CommandLineToArgvW(command, ctypes.byref(argc))
    if not argv:
        return shlex.split(command, posix=False)
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        ctypes.windll.kernel32.LocalFree(argv)


def quote_arg(value: str) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline([value])
    return shlex.quote(value)


def error_tail(value: str, limit: int = 1600) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return "..." + text[-limit:]


def normalize_permission_mode(raw: str, provider: str = "codex") -> str:
    value = str(raw or "").strip()
    lower = value.lower().replace("_", "-")
    if provider == "claude":
        if lower in {"acceptedits", "accept-edits", "edit", "auto-edit"}:
            return "acceptEdits"
        if lower == "plan":
            return "plan"
        if lower in {"auto", "full-auto", "fullauto"}:
            return "auto"
        if lower in {"bypasspermissions", "bypass-permissions", "yolo", "bypass", "dangerously-bypass"}:
            return "bypassPermissions"
        if lower in {"dontask", "dont-ask", "deny"}:
            return "dontAsk"
        return "default"
    if provider == "codewhale":
        if lower in {"auto", "full-auto", "fullauto", "auto-edit", "autoedit", "edit", "accept-edits", "acceptedits"}:
            return "auto"
        if lower in {"yolo", "bypass", "dangerously-bypass", "bypasspermissions", "bypass-permissions"}:
            return "yolo"
        return "default"
    if lower in {"auto-edit", "autoedit", "edit", "accept-edits", "acceptedits"}:
        return "auto-edit"
    if lower in {"full-auto", "fullauto", "auto"}:
        return "full-auto"
    if lower in {"yolo", "bypass", "dangerously-bypass", "bypasspermissions", "bypass-permissions"}:
        return "yolo"
    return "default"


def permission_mode_options(provider: str = "codex") -> list[tuple[str, str]]:
    if provider == "claude":
        return [
            ("default", "每次工具调用都由 Claude 按默认策略请求确认"),
            ("acceptEdits", "自动允许文件编辑，其他操作仍按 Claude 策略确认"),
            ("plan", "只规划，执行前需要确认"),
            ("auto", "由 Claude 自动判断何时请求确认"),
            ("bypassPermissions", "跳过权限确认"),
            ("dontAsk", "未预授权工具自动拒绝"),
        ]
    if provider == "codewhale":
        return [
            ("default", "后台非交互执行，使用 CodeWhale exec 自动处理本地上下文"),
            ("auto", "显式启用 CodeWhale agentic exec 模式"),
            ("yolo", "显式使用 CodeWhale 自动执行模式"),
        ]
    return [
        ("default", "默认只读/按 Codex 默认策略请求确认"),
        ("auto-edit", "自动允许编辑，shell 仍受 Codex 策略限制"),
        ("full-auto", "自动执行，使用工作区沙箱"),
        ("yolo", "跳过审批和沙箱"),
    ]


def format_command_template(template: str, values: dict[str, Path | str]) -> list[str]:
    rendered = template
    for name, value in values.items():
        replacement = str(value) if name in {"image_files", "file_files"} else quote_arg(str(value))
        rendered = rendered.replace("{" + name + "}", replacement)
    return split_command_line(rendered)


class BaseRunner:
    provider = "base"

    def __init__(self, config: AIConfig) -> None:
        self.config = config

    def build_command(self, task: AITask, prompt_file: Path, short_prompt: str) -> list[str]:
        raise NotImplementedError

    def build_commands(self, task: AITask, prompt_file: Path, short_prompt: str) -> list[list[str]]:
        return [self.build_command(task, prompt_file, short_prompt)]

    def stdin_prompt(self, prompt_text: str) -> str | None:
        return None

    def result_text_from_stdout(self, stdout: str, task: AITask) -> str:
        return stdout.strip()

    def build_env(self, task: AITask) -> dict[str, str]:
        env = dict(os.environ)
        if self.provider == "codex" and os.name == "nt":
            codex_home = env.get("CODEX_HOME") or str(Path.home() / ".codex")
            env["CODEX_HOME"] = codex_home
            fake_home = task.work_dir / ".codex_runtime_home"
            (fake_home / "Documents" / "WindowsPowerShell").mkdir(parents=True, exist_ok=True)
            (fake_home / "Documents" / "PowerShell").mkdir(parents=True, exist_ok=True)
            env["USERPROFILE"] = str(fake_home)
            env["HOME"] = str(fake_home)
            drive = fake_home.drive or "C:"
            env["HOMEDRIVE"] = drive
            env["HOMEPATH"] = str(fake_home).removeprefix(drive) or "\\"
        return env

    def run(self, task: AITask, prompt_file: Path, prompt_text: str, logger: logging.Logger) -> AIResult:
        started = time.time()
        started_at = utcish_now()
        result = AIResult(False, self.provider, task.task_type, task.output_file, started_at=started_at)
        short_prompt = f"Read and follow the full task prompt in {prompt_file.resolve()}."
        try:
            stdin_data = self.stdin_prompt(prompt_text)
            commands = self.build_commands(task, prompt_file, short_prompt)
            if not commands or not commands[0]:
                raise RuntimeError(f"Empty {self.provider} command")
            last_error = ""
            try:
                task.output_file.unlink(missing_ok=True)
            except OSError:
                pass
            for attempt, raw_command in enumerate(commands, start=1):
                if not raw_command:
                    continue
                if attempt > 1:
                    try:
                        task.output_file.unlink(missing_ok=True)
                    except OSError:
                        pass
                command = resolve_executable(raw_command, self.provider)
                logger.info(
                    "starting provider=%s task=%s attempt=%s/%s command=%s",
                    self.provider,
                    task.task_type,
                    attempt,
                    len(commands),
                    scrub_command_for_log(command),
                )
                run_kwargs: dict[str, Any] = {"input": stdin_data} if stdin_data is not None else {"stdin": subprocess.DEVNULL}
                completed = subprocess.run(
                    command,
                    cwd=str(task.work_dir),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=task.timeout,
                    shell=False,
                    env=self.build_env(task),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    **run_kwargs,
                )
                result.exit_code = completed.returncode
                result.stdout = completed.stdout[-12000:]
                result.stderr = completed.stderr[-12000:]
                result.text = ""
                if task.output_file.exists():
                    result.text = task.output_file.read_text(encoding="utf-8", errors="replace").strip()
                elif completed.stdout.strip():
                    result.text = self.result_text_from_stdout(completed.stdout, task)
                    task.output_file.parent.mkdir(parents=True, exist_ok=True)
                    if result.text:
                        task.output_file.write_text(result.text + "\n", encoding="utf-8")
                if completed.returncode == 0 and result.text:
                    result.ok = True
                    result.error = ""
                    break
                if completed.returncode != 0:
                    last_error = f"{self.provider} exited with code {completed.returncode}: {error_tail(completed.stderr)}"
                else:
                    last_error = f"{self.provider} produced empty output"
                if attempt < len(commands) and self.should_try_next_command(completed, result):
                    logger.warning(
                        "provider=%s task=%s attempt=%s failed, trying fallback: %s",
                        self.provider,
                        task.task_type,
                        attempt,
                        last_error,
                    )
                    continue
                result.error = last_error
                break
        except subprocess.TimeoutExpired as exc:
            result.error = f"{self.provider} timed out after {task.timeout} seconds"
            result.stdout = (exc.stdout or "")[-12000:] if isinstance(exc.stdout, str) else ""
            result.stderr = (exc.stderr or "")[-12000:] if isinstance(exc.stderr, str) else ""
        except FileNotFoundError as exc:
            missing = exc.filename or (command[0] if "command" in locals() and command else "")
            result.error = f"{self.provider} command not found: {missing}. Set AI_{self.provider.upper()}_COMMAND to the full executable path."
        except Exception as exc:
            result.error = f"{self.provider} failed: {exc}"
        finally:
            result.ended_at = utcish_now()
            result.duration_seconds = round(time.time() - started, 3)
            logger.info(
                "finished provider=%s task=%s ok=%s exit=%s duration=%s error=%s stdout=%s stderr=%s",
                self.provider,
                task.task_type,
                result.ok,
                result.exit_code,
                result.duration_seconds,
                result.error,
                result.stdout[-2000:],
                result.stderr[-2000:],
            )
            write_json(task.output_file.with_suffix(task.output_file.suffix + ".meta.json"), asdict(result) | {"output_file": str(task.output_file)})
        return result

    def should_try_next_command(self, completed: subprocess.CompletedProcess[str], result: AIResult) -> bool:
        return completed.returncode != 0


def scrub_command_for_log(command: list[str]) -> list[str]:
    return ["<redacted>" if re.search(r"(secret|cookie|token|password)", item, re.I) else item for item in command]


_RUNNER_SESSION_LOCKS: dict[str, threading.Lock] = {}
_RUNNER_SESSION_LOCKS_GUARD = threading.Lock()


def runner_session_lock(key: str) -> threading.Lock:
    with _RUNNER_SESSION_LOCKS_GUARD:
        lock = _RUNNER_SESSION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _RUNNER_SESSION_LOCKS[key] = lock
        return lock


def resolve_executable(command: list[str], provider: str) -> list[str]:
    if not command:
        return command
    executable = command[0]
    path = Path(executable)
    if path.is_absolute() or path.parent != Path("."):
        return command
    if os.name == "nt":
        candidates: list[Path] = []
        appdata = os.getenv("APPDATA")
        localappdata = os.getenv("LOCALAPPDATA")
        userprofile = os.getenv("USERPROFILE")
        executable_names = [executable]
        if not executable.lower().endswith((".exe", ".cmd", ".bat", ".ps1")):
            executable_names.extend([f"{executable}.exe", f"{executable}.cmd", f"{executable}.bat"])

        def add_named_candidates(directory: Path | None) -> None:
            if directory is None:
                return
            for name in executable_names:
                candidates.append(directory / name)

        if provider == "codex":
            if localappdata:
                candidates.append(Path(localappdata) / "OpenAI" / "Codex" / "bin" / "codex.exe")
            if appdata:
                candidates.append(Path(appdata) / "npm" / "codex.cmd")
        elif provider == "claude":
            add_named_candidates(Path(userprofile) / ".local" / "bin" if userprofile else None)
            add_named_candidates(Path(localappdata) / "Microsoft" / "WinGet" / "Links" if localappdata else None)
            add_named_candidates(Path(appdata) / "npm" if appdata else None)
        elif provider == "codewhale" and appdata:
            candidates.append(Path(appdata) / "npm" / "codewhale.cmd")
            candidates.append(Path(appdata) / "npm" / "deepseek.cmd")
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate), *command[1:]]
    found = shutil.which(executable)
    if found:
        return [found, *command[1:]]
    return command


class CodexRunner(BaseRunner):
    provider = "codex"

    def _model_args(self, task: AITask, *, allow_model: bool = True) -> list[str]:
        if not allow_model:
            return []
        model = model_for_cli("codex", str(task.metadata.get("model") or self.config.model or ""))
        return ["--model", model] if model else []

    def _has_model_arg(self, task: AITask) -> bool:
        model = model_for_cli("codex", str(task.metadata.get("model") or self.config.model or ""))
        return bool(model)

    def _reasoning_args(self, task: AITask) -> list[str]:
        effort = normalize_reasoning_effort(
            str(task.metadata.get("reasoning_effort") or self.config.reasoning_effort or ""),
            "codex",
        )
        if not effort or effort == "auto":
            return []
        return ["-c", f'model_reasoning_effort="{effort}"']

    def _mode_args(self, task: AITask) -> list[str]:
        mode = normalize_permission_mode(task.metadata.get("permission_mode") or self.config.permission_mode, "codex")
        if mode in {"auto-edit", "full-auto"}:
            return ["--full-auto"]
        if mode == "yolo":
            return ["--dangerously-bypass-approvals-and-sandbox"]
        return []

    def _image_args(self, task: AITask) -> list[str]:
        args: list[str] = []
        for image_path in task.image_paths:
            args.extend(["--image", str(image_path)])
        return args

    def build_command(
        self,
        task: AITask,
        prompt_file: Path,
        short_prompt: str,
        *,
        ignore_rules: bool = False,
        allow_model: bool = True,
    ) -> list[str]:
        base = split_command_line(self.config.codex_command)
        command = [
            *base,
            "exec",
            "--cd",
            str(task.work_dir),
            "--skip-git-repo-check",
        ]
        if ignore_rules:
            command.insert(len(base) + 1, "--ignore-rules")
        command.extend(self._model_args(task, allow_model=allow_model))
        command.extend(self._reasoning_args(task))
        command.extend(self._mode_args(task))
        command.extend(self._image_args(task))
        command.extend([
            "--output-last-message",
            str(task.output_file),
            "-",
        ])
        return command

    def build_resume_command(
        self,
        task: AITask,
        prompt_file: Path,
        short_prompt: str,
        *,
        ignore_rules: bool = False,
        allow_model: bool = True,
    ) -> list[str]:
        base = split_command_line(self.config.codex_command)
        command = [
            *base,
            "exec",
            "resume",
            "--last",
            "--skip-git-repo-check",
        ]
        if ignore_rules:
            command.insert(len(base) + 3, "--ignore-rules")
        command.extend(self._model_args(task, allow_model=allow_model))
        command.extend(self._reasoning_args(task))
        command.extend(self._mode_args(task))
        command.extend(self._image_args(task))
        command.extend([
            "--output-last-message",
            str(task.output_file),
            "-",
        ])
        return command

    def build_commands(self, task: AITask, prompt_file: Path, short_prompt: str) -> list[list[str]]:
        commands = [
            self.build_resume_command(task, prompt_file, short_prompt, ignore_rules=False, allow_model=True),
        ]
        if self._has_model_arg(task):
            commands.extend([
                self.build_resume_command(task, prompt_file, short_prompt, ignore_rules=False, allow_model=False),
            ])
        commands.append(self.build_command(task, prompt_file, short_prompt, ignore_rules=False, allow_model=True))
        if self._has_model_arg(task):
            commands.extend([
                self.build_command(task, prompt_file, short_prompt, ignore_rules=False, allow_model=False),
            ])
        return commands

    def should_try_next_command(self, completed: subprocess.CompletedProcess[str], result: AIResult) -> bool:
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        return completed.returncode != 0 and any(
            pattern in output
            for pattern in (
                "no sessions",
                "no session",
                "not found",
                "could not find",
                "not a valid session",
                "resume",
                "unexpected argument",
                "unknown argument",
                "--ignore-rules",
                "requires a newer version of codex",
                "invalid_request_error",
                "invalid model",
                "unknown model",
                "model_not_found",
            )
        )

    def stdin_prompt(self, prompt_text: str) -> str | None:
        if prompt_text.isascii():
            return prompt_text
        payload = json.dumps(prompt_text, ensure_ascii=True)
        return (
            "The exact task prompt is encoded below as a JSON string with Unicode escapes. "
            "Interpret the escapes as Unicode characters, then follow the decoded task prompt. "
            "If the decoded prompt is a user chat message, answer that message directly. "
            "Do not mention this transport wrapper.\n\n"
            f"JSON_ESCAPED_PROMPT:\n{payload}\n"
        )


_CLAUDE_STREAM_SESSIONS: dict[str, "ClaudeStreamSession"] = {}
_CLAUDE_STREAM_SESSIONS_GUARD = threading.Lock()


def _tail_append(parts: list[str], text: str, *, limit: int = 12000) -> None:
    if not text:
        return
    parts.append(text)
    total = sum(len(part) for part in parts)
    while parts and total > limit:
        removed = parts.pop(0)
        total -= len(removed)


def _claude_session_key(config: AIConfig, task: AITask) -> str:
    model = model_for_cli("claude", str(task.metadata.get("model") or config.model or ""))
    effort = normalize_reasoning_effort(str(task.metadata.get("reasoning_effort") or config.reasoning_effort or ""), "claude")
    mode = normalize_permission_mode(task.metadata.get("permission_mode") or config.permission_mode, "claude")
    return "\n".join([
        str(task.work_dir.resolve()),
        config.claude_command,
        model,
        effort,
        mode,
    ])


class ClaudeStreamSession:
    """Long-running Claude Code stream-json process, modeled after cc-connect."""

    def __init__(self, config: AIConfig, task: AITask, logger: logging.Logger) -> None:
        self.config = config
        self.work_dir = task.work_dir
        self.logger = logger
        self.events: queue.Queue[dict[str, Any]] = queue.Queue()
        self.turn_lock = threading.Lock()
        self.stdin_lock = threading.Lock()
        self.stderr_parts: list[str] = []
        self.stdout_parts: list[str] = []
        self.session_id = ""
        self.mode = normalize_permission_mode(task.metadata.get("permission_mode") or config.permission_mode, "claude")
        self.process = self._start(task)
        threading.Thread(target=self._stdout_loop, daemon=True).start()
        threading.Thread(target=self._stderr_loop, daemon=True).start()

    def _start(self, task: AITask) -> subprocess.Popen[str]:
        base = resolve_executable(split_command_line(self.config.claude_command), "claude")
        if not base:
            raise RuntimeError("Empty claude command")
        command = [
            *base,
            "--output-format",
            "stream-json",
            "--input-format",
            "stream-json",
            "--permission-prompt-tool",
            "stdio",
            "--replay-user-messages",
            "--verbose",
        ]
        if self.mode != "default":
            command.extend(["--permission-mode", self.mode])
        effort = normalize_reasoning_effort(
            str(task.metadata.get("reasoning_effort") or self.config.reasoning_effort or ""),
            "claude",
        )
        if effort:
            command.extend(["--effort", effort])
        model = model_for_cli("claude", str(task.metadata.get("model") or self.config.model or ""))
        if model:
            command.extend(["--model", model])
        self.logger.info("starting persistent claude stream command=%s", scrub_command_for_log(command))
        return subprocess.Popen(
            command,
            cwd=str(self.work_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env=BaseRunner(self.config).build_env(task),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def _stdout_loop(self) -> None:
        try:
            assert self.process.stdout is not None
            for line in self.process.stdout:
                _tail_append(self.stdout_parts, line)
                text = line.strip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    self.logger.debug("claude stream non-json stdout: %s", text[:500])
                    continue
                if isinstance(event, dict):
                    self._handle_event(event)
        finally:
            code = self.process.poll()
            if code is None:
                try:
                    code = self.process.wait(timeout=0.2)
                except subprocess.TimeoutExpired:
                    code = None
            self.events.put({"type": "_exit", "returncode": code, "stderr": self.stderr_tail()})

    def _stderr_loop(self) -> None:
        if self.process.stderr is None:
            return
        for line in self.process.stderr:
            _tail_append(self.stderr_parts, line)

    def _handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "")
        if event_type in {"system", "result"}:
            session_id = str(event.get("session_id") or "").strip()
            if session_id:
                self.session_id = session_id
        if event_type == "control_request":
            self._handle_control_request(event)
            return
        self.events.put(event)

    def _handle_control_request(self, event: dict[str, Any]) -> None:
        request_id = str(event.get("request_id") or "").strip()
        request = event.get("request")
        if not request_id or not isinstance(request, dict):
            return
        input_value = request.get("input")
        updated_input = input_value if isinstance(input_value, dict) else {}
        tool_name = str(request.get("tool_name") or "")
        allow = self.mode == "bypassPermissions" or (self.mode == "acceptEdits" and tool_name in {"Edit", "Write", "NotebookEdit", "MultiEdit"})
        if allow:
            response = {"behavior": "allow", "updatedInput": updated_input}
        else:
            response = {
                "behavior": "deny",
                "message": "Permission was not pre-approved by NGA Wolf Watcher. Switch AI permission mode if this tool should run.",
            }
        try:
            self._write_json({
                "type": "control_response",
                "response": {
                    "subtype": "success",
                    "request_id": request_id,
                    "response": response,
                },
            })
        except Exception as exc:
            self.logger.warning("claude permission response failed: %s", exc)

    def _write_json(self, payload: dict[str, Any]) -> None:
        if self.process.stdin is None:
            raise RuntimeError("claude stdin is not available")
        data = json.dumps(payload, ensure_ascii=True)
        with self.stdin_lock:
            self.process.stdin.write(data + "\n")
            self.process.stdin.flush()

    def alive(self) -> bool:
        return self.process.poll() is None

    def stdout_tail(self) -> str:
        return "".join(self.stdout_parts)[-12000:]

    def stderr_tail(self) -> str:
        return "".join(self.stderr_parts)[-12000:]

    def close(self) -> None:
        try:
            if self.process.stdin is not None:
                self.process.stdin.close()
        except Exception:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def send(self, prompt_text: str, task: AITask) -> tuple[str, str]:
        if not self.alive():
            raise RuntimeError(f"claude stream process is not running: {error_tail(self.stderr_tail())}")
        self._drain_events()
        payload: dict[str, Any] = {"type": "user", "message": {"role": "user", "content": self._message_content(prompt_text, task)}}
        self._write_json(payload)
        parts: list[str] = []
        deadline = time.monotonic() + max(1, int(task.timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise subprocess.TimeoutExpired("claude stream", task.timeout)
            try:
                event = self.events.get(timeout=min(1.0, remaining))
            except queue.Empty:
                if not self.alive():
                    raise RuntimeError(f"claude exited before result: {error_tail(self.stderr_tail())}")
                continue
            event_type = str(event.get("type") or "")
            if event_type == "assistant":
                parts.extend(self._assistant_text(event))
            elif event_type == "result":
                text = str(event.get("result") or "").strip()
                return (text or "".join(parts).strip(), self.session_id)
            elif event_type == "_exit":
                raise RuntimeError(f"claude exited with code {event.get('returncode')}: {error_tail(str(event.get('stderr') or self.stderr_tail()))}")

    def _drain_events(self) -> None:
        while True:
            try:
                self.events.get_nowait()
            except queue.Empty:
                return

    def _assistant_text(self, event: dict[str, Any]) -> list[str]:
        message = event.get("message")
        if not isinstance(message, dict):
            return []
        content = message.get("content")
        if not isinstance(content, list):
            return []
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = str(item.get("text") or "")
                if text:
                    parts.append(text)
        return parts

    def _message_content(self, prompt_text: str, task: AITask) -> str | list[dict[str, Any]]:
        image_parts: list[dict[str, Any]] = []
        for path in task.image_paths:
            try:
                data = Path(path).read_bytes()
            except OSError as exc:
                self.logger.warning("claude image read failed path=%s error=%s", path, exc)
                continue
            mime_type = mimetypes.guess_type(str(path))[0] or "image/png"
            image_parts.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime_type,
                    "data": base64.b64encode(data).decode("ascii"),
                },
            })
        if not image_parts:
            return prompt_text
        image_parts.append({"type": "text", "text": prompt_text or "Please analyze the attached image(s)."})
        return image_parts


def claude_stream_session(config: AIConfig, task: AITask, logger: logging.Logger) -> ClaudeStreamSession:
    key = _claude_session_key(config, task)
    with _CLAUDE_STREAM_SESSIONS_GUARD:
        session = _CLAUDE_STREAM_SESSIONS.get(key)
        if session is not None and session.alive():
            return session
        if session is not None:
            try:
                session.close()
            except Exception:
                pass
        session = ClaudeStreamSession(config, task, logger)
        _CLAUDE_STREAM_SESSIONS[key] = session
        return session


class ClaudeRunner(BaseRunner):
    provider = "claude"

    def build_command(
        self,
        task: AITask,
        prompt_file: Path,
        short_prompt: str,
        *,
        conversation_mode: str = "continue",
    ) -> list[str]:
        values = command_values(task, prompt_file)
        if "{" in self.config.claude_command:
            return format_command_template(self.config.claude_command, values)
        mode = normalize_permission_mode(task.metadata.get("permission_mode") or self.config.permission_mode, "claude")
        command = [*split_command_line(self.config.claude_command), "-p"]
        if conversation_mode == "continue":
            command.append("--continue")
        elif conversation_mode == "continue_fork":
            command.extend(["--continue", "--fork-session"])
        elif conversation_mode == "session_id":
            command.extend(["--session-id", str(values["session_id"])])
        model = model_for_cli("claude", str(task.metadata.get("model") or self.config.model or ""))
        if model:
            command.extend(["--model", model])
        effort = normalize_reasoning_effort(str(task.metadata.get("reasoning_effort") or self.config.reasoning_effort or ""), "claude")
        if effort:
            command.extend(["--effort", effort])
        if mode != "default":
            command.extend(["--permission-mode", mode])
        command.append(short_prompt)
        return command

    def build_commands(self, task: AITask, prompt_file: Path, short_prompt: str) -> list[list[str]]:
        if "{" in self.config.claude_command:
            return [self.build_command(task, prompt_file, short_prompt)]
        return [
            self.build_command(task, prompt_file, short_prompt, conversation_mode="continue"),
            self.build_command(task, prompt_file, short_prompt, conversation_mode="continue_fork"),
            self.build_command(task, prompt_file, short_prompt, conversation_mode="new"),
        ]

    def _session_id(self, task: AITask) -> str:
        return str(task.metadata.get("session_id") or shared_session_id(task.work_dir))

    def _session_busy(self, result: AIResult) -> bool:
        output = f"{result.error}\n{result.stdout}\n{result.stderr}".lower()
        return "session id" in output and "already in use" in output

    def run(self, task: AITask, prompt_file: Path, prompt_text: str, logger: logging.Logger) -> AIResult:
        if "{" in self.config.claude_command:
            return super().run(task, prompt_file, prompt_text, logger)

        started = time.time()
        started_at = utcish_now()
        result = AIResult(False, self.provider, task.task_type, task.output_file, started_at=started_at)
        session: ClaudeStreamSession | None = None
        try:
            task.output_file.unlink(missing_ok=True)
        except OSError:
            pass
        try:
            session = claude_stream_session(self.config, task, logger)
            with session.turn_lock:
                text, session_id = session.send(prompt_text, task)
            result.exit_code = 0
            result.stdout = session.stdout_tail()
            result.stderr = session.stderr_tail()
            result.text = text.strip()
            if session_id:
                self._save_session_id(task, session_id)
            if result.text:
                task.output_file.parent.mkdir(parents=True, exist_ok=True)
                task.output_file.write_text(result.text + "\n", encoding="utf-8")
                result.ok = True
            else:
                result.error = "claude produced empty output"
        except subprocess.TimeoutExpired as exc:
            result.error = f"claude timed out after {task.timeout} seconds"
            result.stdout = session.stdout_tail() if session else ""
            result.stderr = session.stderr_tail() if session else ""
            self._discard_stream_session(task)
        except FileNotFoundError as exc:
            missing = exc.filename or self.config.claude_command
            result.error = f"claude command not found: {missing}. Set AI_CLAUDE_COMMAND to the full executable path."
        except Exception as exc:
            result.error = f"claude failed: {exc}"
            result.stdout = session.stdout_tail() if session else ""
            result.stderr = session.stderr_tail() if session else ""
            if session and not session.alive():
                self._discard_stream_session(task)
        finally:
            result.ended_at = utcish_now()
            result.duration_seconds = round(time.time() - started, 3)
            logger.info(
                "finished provider=%s task=%s ok=%s exit=%s duration=%s error=%s stdout=%s stderr=%s",
                self.provider,
                task.task_type,
                result.ok,
                result.exit_code,
                result.duration_seconds,
                result.error,
                result.stdout[-2000:],
                result.stderr[-2000:],
            )
            write_json(task.output_file.with_suffix(task.output_file.suffix + ".meta.json"), asdict(result) | {"output_file": str(task.output_file)})
        return result

    def _save_session_id(self, task: AITask, session_id: str) -> None:
        state = read_json(task.work_dir / "state.json", {})
        if not isinstance(state, dict):
            state = {}
        state["claude_stream_session_id"] = session_id
        state["claude_stream_session_updated_at"] = utcish_now()
        write_json(task.work_dir / "state.json", state)

    def _discard_stream_session(self, task: AITask) -> None:
        key = _claude_session_key(self.config, task)
        with _CLAUDE_STREAM_SESSIONS_GUARD:
            session = _CLAUDE_STREAM_SESSIONS.pop(key, None)
        if session is not None:
            try:
                session.close()
            except Exception:
                pass


class CodeWhaleRunner(BaseRunner):
    provider = "codewhale"

    def _state_path(self, task: AITask) -> Path:
        return task.work_dir / "state.json"

    def _saved_session_id(self, task: AITask) -> str:
        state = read_json(self._state_path(task), {})
        if not isinstance(state, dict):
            return ""
        current_model = model_for_cli("codewhale", str(task.metadata.get("model") or self.config.model or ""))
        current_reasoning = normalize_reasoning_effort(
            str(task.metadata.get("reasoning_effort") or self.config.reasoning_effort or ""),
            "codewhale",
        )
        saved_model = str(state.get("codewhale_session_model") or "").strip()
        saved_reasoning = str(state.get("codewhale_session_reasoning_effort") or "").strip()
        if saved_model != current_model or saved_reasoning != current_reasoning:
            return ""
        return str(state.get("codewhale_session_id") or "").strip()

    def _save_session_id(self, task: AITask, session_id: str) -> None:
        session_id = str(session_id or "").strip()
        if not session_id:
            return
        state = read_json(self._state_path(task), {})
        if not isinstance(state, dict):
            state = {}
        state["codewhale_session_id"] = session_id
        state["codewhale_session_model"] = model_for_cli("codewhale", str(task.metadata.get("model") or self.config.model or ""))
        state["codewhale_session_reasoning_effort"] = normalize_reasoning_effort(
            str(task.metadata.get("reasoning_effort") or self.config.reasoning_effort or ""),
            "codewhale",
        )
        state["codewhale_session_updated_at"] = utcish_now()
        write_json(self._state_path(task), state)

    def _model_args(self, task: AITask) -> list[str]:
        model = model_for_cli("codewhale", str(task.metadata.get("model") or self.config.model or ""))
        return ["--model", model] if model else []

    def _has_model_arg(self, task: AITask) -> bool:
        model = model_for_cli("codewhale", str(task.metadata.get("model") or self.config.model or ""))
        return bool(model)

    def _reasoning_config_path(self, task: AITask) -> Path:
        existing = str(task.metadata.get("_codewhale_runtime_config_path") or "")
        if existing:
            return Path(existing)
        path = Path(tempfile.gettempdir()) / f"{SOURCE_NAME}_codewhale_{safe_key(task.task_type)}_{uuid.uuid4().hex}.toml"
        task.metadata["_codewhale_runtime_config_path"] = str(path)
        return path

    def _reasoning_config_args(self, task: AITask) -> list[str]:
        effort = normalize_reasoning_effort(
            str(task.metadata.get("reasoning_effort") or self.config.reasoning_effort or ""),
            "codewhale",
        )
        if not effort:
            return []
        path = self._reasoning_config_path(task)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"reasoning_effort = {json.dumps(effort, ensure_ascii=False)}\n", encoding="utf-8")
        return ["--config", str(path)]

    def build_command(
        self,
        task: AITask,
        prompt_file: Path,
        short_prompt: str,
        *,
        session_id: str = "",
        allow_model: bool = True,
        allow_reasoning: bool = True,
    ) -> list[str]:
        base = split_command_line(self.config.codewhale_command)
        command = [*base]
        if allow_reasoning:
            command.extend(self._reasoning_config_args(task))
        command.extend([
            "exec",
            "--output-format",
            "stream-json",
            "--auto",
        ])
        if session_id:
            command.extend(["--resume", session_id])
        if allow_model:
            command.extend(self._model_args(task))
        command.append(short_prompt)
        return command

    def build_commands(self, task: AITask, prompt_file: Path, short_prompt: str) -> list[list[str]]:
        session_id = self._saved_session_id(task)
        commands = [
            self.build_command(task, prompt_file, short_prompt, session_id=session_id, allow_model=True, allow_reasoning=True),
        ]
        if self._has_model_arg(task):
            commands.append(self.build_command(task, prompt_file, short_prompt, session_id=session_id, allow_model=False, allow_reasoning=True))
        if session_id:
            commands.append(self.build_command(task, prompt_file, short_prompt, session_id="", allow_model=True, allow_reasoning=True))
        if self._has_model_arg(task):
            commands.append(self.build_command(task, prompt_file, short_prompt, session_id="", allow_model=False, allow_reasoning=True))
        if self._reasoning_config_args(task):
            commands.append(self.build_command(task, prompt_file, short_prompt, session_id=session_id, allow_model=True, allow_reasoning=False))
        return commands

    def result_text_from_stdout(self, stdout: str, task: AITask) -> str:
        parts: list[str] = []
        session_id = ""
        for line in stdout.splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or event.get("event") or "").strip()
            if event_type == "content":
                parts.append(str(event.get("content") or ""))
            elif event_type == "session_capture":
                session_id = str(event.get("content") or "").strip() or session_id
            elif event_type == "metadata":
                meta = event.get("meta")
                if isinstance(meta, dict):
                    session_id = str(meta.get("session_id") or "").strip() or session_id
        if session_id:
            self._save_session_id(task, session_id)
        return "".join(parts).strip()

    def should_try_next_command(self, completed: subprocess.CompletedProcess[str], result: AIResult) -> bool:
        output = f"{completed.stdout}\n{completed.stderr}".lower()
        return completed.returncode != 0 and any(
            pattern in output
            for pattern in (
                "no sessions",
                "no session",
                "not found",
                "could not find",
                "not a valid session",
                "could not load session",
                "resume",
                "continue",
                "unexpected argument",
                "unknown argument",
                "invalid model",
                "unknown model",
                "model_not_found",
            )
        )

    def run(self, task: AITask, prompt_file: Path, prompt_text: str, logger: logging.Logger) -> AIResult:
        try:
            return super().run(task, prompt_file, prompt_text, logger)
        finally:
            config_path = str(task.metadata.pop("_codewhale_runtime_config_path", "") or "")
            if config_path:
                try:
                    Path(config_path).unlink(missing_ok=True)
                except OSError:
                    pass


class CustomCommandRunner(BaseRunner):
    provider = "custom"

    def build_command(self, task: AITask, prompt_file: Path, short_prompt: str) -> list[str]:
        if not self.config.custom_command.strip():
            raise RuntimeError("AI_CUSTOM_COMMAND is empty")
        return format_command_template(self.config.custom_command, command_values(task, prompt_file))


def command_values(task: AITask, prompt_file: Path) -> dict[str, Path | str]:
    return {
        "work_dir": task.work_dir,
        "prompt_file": prompt_file,
        "output_file": task.output_file,
        "task_type": task.task_type,
        "latest_event": task.latest_event,
        "history_file": task.history_file,
        "source_index": task.work_dir / "events" / "source_index.json",
        "source_history_dir": task.work_dir / "events" / "by_source",
        "image_files": " ".join(quote_arg(str(path)) for path in task.image_paths),
        "file_files": " ".join(quote_arg(str(path)) for path in task.file_paths),
        "permission_mode": task.metadata.get("permission_mode") or "",
        "model": task.metadata.get("model") or "",
        "reasoning_effort": task.metadata.get("reasoning_effort") or "",
        "session_id": task.metadata.get("session_id") or shared_session_id(task.work_dir),
    }


def shared_session_id(work_dir: Path) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{SOURCE_NAME}:{work_dir.resolve()}"))


def runner_for(config: AIConfig) -> BaseRunner:
    if config.provider == "claude":
        return ClaudeRunner(config)
    if config.provider == "codewhale":
        return CodeWhaleRunner(config)
    if config.provider == "custom":
        return CustomCommandRunner(config)
    return CodexRunner(config)


def parse_hhmm(value: str) -> int:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", value.strip())
    if not match:
        raise ValueError(f"Invalid HH:MM time: {value}")
    return int(match.group(1)) * 60 + int(match.group(2))


def parse_days(value: str) -> set[int]:
    value = value.strip().lower()
    if value in {"weekday", "weekdays", "mon-fri"}:
        return {0, 1, 2, 3, 4}
    names = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    if "-" in value:
        left, right = [part.strip() for part in value.split("-", 1)]
        start = names.get(left, None)
        end = names.get(right, None)
        if start is None:
            start = int(left) - 1
        if end is None:
            end = int(right) - 1
        return {day % 7 for day in range(start, end + 1)}
    if value in names:
        return {names[value]}
    return {int(value) - 1}


def schedule_window_matches(expression: str, when: dt.datetime | None = None) -> bool:
    local_when = when or dt.datetime.now()
    minute = local_when.hour * 60 + local_when.minute
    for block in [item.strip() for item in expression.split(";") if item.strip()]:
        if ":" not in block:
            continue
        day_expr, ranges_expr = block.split(":", 1)
        try:
            days = parse_days(day_expr)
        except (ValueError, TypeError):
            continue
        if local_when.weekday() not in days:
            continue
        for range_expr in [item.strip() for item in ranges_expr.split(",") if item.strip()]:
            if "-" not in range_expr:
                continue
            raw_start, raw_end = [part.strip() for part in range_expr.split("-", 1)]
            try:
                start = parse_hhmm(raw_start)
                end = parse_hhmm(raw_end)
            except ValueError:
                continue
            if start <= end and start <= minute <= end:
                return True
            if start > end and (minute >= start or minute <= end):
                return True
    return False


def should_trigger_schedule(state: dict[str, Any], config: AIConfig, now: dt.datetime | None = None) -> bool:
    if not config.schedule_enabled:
        return False
    local_now = now or dt.datetime.now()
    if not schedule_window_matches(config.schedule_windows, local_now):
        return False
    interval = max(1, config.schedule_interval_minutes)
    bucket = int(local_now.timestamp()) // (interval * 60)
    if str(state.get("last_scheduled_bucket", "")) == str(bucket):
        return False
    return True


class AIManager:
    def __init__(
        self,
        config: AIConfig,
        *,
        send_text: Callable[[str], None] | None = None,
        send_file: Callable[[str, str], None] | None = None,
        send_result: Callable[[AIResult], None] | None = None,
    ) -> None:
        self.config = config
        self.send_text = send_text
        self.send_file = send_file
        self.send_result = send_result
        self._queue: queue.Queue[tuple[AITask, str | None]] = queue.Queue(maxsize=8)
        self._worker_started = False
        self._lock = threading.Lock()
        self._started_at = time.time()

    @property
    def state_path(self) -> Path:
        return self.config.work_dir / "state.json"

    @property
    def latest_event_path(self) -> Path:
        return self.config.work_dir / "events" / "latest_event.json"

    @property
    def history_file(self) -> Path:
        return self.config.work_dir / "events" / "wolf_history.jsonl"

    def ensure_ready(self) -> None:
        ensure_workspace(self.config)

    def logger(self) -> logging.Logger:
        return configure_logger(self.config.work_dir)

    def read_state(self) -> dict[str, Any]:
        return read_json(self.state_path, {})

    def write_state(self, state: dict[str, Any]) -> None:
        write_json(self.state_path, state)

    def effective_enabled(self) -> bool:
        state = self.read_state()
        if "ai_enabled" in state:
            return bool_value(state.get("ai_enabled"))
        return self.config.enabled

    def effective_auto(self) -> bool:
        state = self.read_state()
        if "auto_analyze_new_post" in state:
            return bool_value(state.get("auto_analyze_new_post"))
        return self.config.auto_analyze_new_post

    def effective_schedule(self) -> bool:
        state = self.read_state()
        if "schedule_enabled" in state:
            return bool_value(state.get("schedule_enabled"))
        return self.config.schedule_enabled

    def effective_interval(self) -> int:
        state = self.read_state()
        return safe_int(state.get("schedule_interval_minutes", self.config.schedule_interval_minutes), self.config.schedule_interval_minutes, 1)

    def effective_windows(self) -> str:
        state = self.read_state()
        return str(state.get("schedule_windows") or self.config.schedule_windows or DEFAULT_SCHEDULE_WINDOWS)

    def effective_config(self) -> AIConfig:
        state = self.read_state()
        clone = AIConfig(**{**asdict(self.config), "work_dir": self.config.work_dir, "allowed_user_ids": set(self.config.allowed_user_ids)})
        clone.enabled = self.effective_enabled()
        clone.auto_analyze_new_post = self.effective_auto()
        clone.auto_analysis_prompt = str(state.get("auto_analysis_prompt") or self.config.auto_analysis_prompt or "")
        clone.schedule_enabled = self.effective_schedule()
        clone.schedule_interval_minutes = self.effective_interval()
        clone.schedule_prompt = str(state.get("schedule_prompt") or self.config.schedule_prompt or "")
        clone.schedule_windows = self.effective_windows()
        clone.permission_mode = self.effective_permission_mode()
        clone.model = self.effective_model()
        clone.reasoning_effort = self.effective_reasoning_effort()
        return clone

    def effective_permission_mode(self) -> str:
        state = self.read_state()
        raw = str(state.get("permission_mode") or self.config.permission_mode or "default")
        return normalize_permission_mode(raw, self.config.provider)

    def _runtime_setting_is_current(self, state: dict[str, Any], key: str) -> bool:
        marker = state.get(f"{key}_updated_at")
        return parse_state_timestamp(marker) >= self._started_at - 2

    def effective_model(self) -> str:
        state = self.read_state()
        if "model" in state and self._runtime_setting_is_current(state, "model"):
            raw = str(state.get("model") or "").strip()
            model = normalize_provider_model(self.config.provider, raw)
            if model or raw.lower() in {"", "auto", "unset", "default"}:
                return model
        config_raw = str(self.config.model or "").strip()
        if config_raw:
            model = normalize_provider_model(self.config.provider, config_raw)
            if model or config_raw.lower() in {"auto", "unset", "default"}:
                return model
        return provider_default_model(self.config.provider)

    def effective_reasoning_effort(self) -> str:
        state = self.read_state()
        if "reasoning_effort" in state and self._runtime_setting_is_current(state, "reasoning_effort"):
            raw = str(state.get("reasoning_effort") or "").strip()
            effort = normalize_reasoning_effort(raw, self.config.provider)
            if effort:
                return effort
            if raw.lower() in {"", "auto", "unset", "default"}:
                return provider_default_reasoning_effort(self.config.provider)
        config_raw = str(self.config.reasoning_effort or "").strip()
        if config_raw:
            effort = normalize_reasoning_effort(config_raw, self.config.provider)
            if effort:
                return effort
        return provider_default_reasoning_effort(self.config.provider)

    def clear_runtime_model_config(self) -> None:
        state = self.read_state()
        state.pop("model", None)
        state.pop("reasoning_effort", None)
        state.pop("model_updated_at", None)
        state.pop("reasoning_effort_updated_at", None)
        state["updated_at"] = utcish_now()
        self.write_state(state)

    def is_authorized(self, sender_id: str | None) -> bool:
        if not self.config.allowed_user_ids:
            return True
        return bool(sender_id and sender_id in self.config.allowed_user_ids)

    def save_event_images(self, event: dict[str, Any]) -> list[Path]:
        urls = [str(url).strip() for url in event.get("image_urls") or [] if str(url).strip()]
        if not urls:
            return []
        logger = self.logger()
        image_dir = self.config.work_dir / "attachments" / "nga" / safe_key(str(event.get("key") or "post"))
        saved: list[Path] = []
        seen: set[str] = set()
        for idx, url in enumerate(urls[:8], 1):
            if url in seen:
                continue
            seen.add(url)
            target = image_dir / f"image_{idx:02d}{image_suffix_from_url(url)}"
            try:
                if target.exists() and target.stat().st_size > 0:
                    saved.append(target)
                    continue
                saved.append(download_image(url, target, timeout=min(max(self.config.timeout, 5), 30)))
            except Exception as exc:
                logger.warning("failed to save NGA image %s: %s", url, exc)
        return saved

    def save_post_event(self, post: Any, *, force: bool = False) -> Path | None:
        if not force and not self.effective_enabled() and not self.config.auto_analyze_new_post and not self.state_path.exists():
            return None
        self.ensure_ready()
        event = event_from_post(post)
        event["image_paths"] = [str(path) for path in self.save_event_images(event)]
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        event_path = self.config.work_dir / "events" / f"{timestamp}_{safe_key(event['key'])}.json"
        write_json(event_path, event)
        write_json(self.latest_event_path, event)
        added = append_jsonl_unique(self.history_file, event)
        by_source_path = source_history_path(self.config.work_dir, event)
        if by_source_path is not None:
            migrate_legacy_source_history(self.config.work_dir, event, by_source_path)
            append_jsonl_unique(by_source_path, event)
            update_source_index(self.config.work_dir, event, by_source_path)
        state = self.read_state()
        state["latest_event_key"] = event.get("key", "")
        state["latest_event_path"] = str(event_path)
        state["latest_event_at"] = event.get("post_time") or event.get("captured_at")
        state["updated_at"] = utcish_now()
        state["history_count_hint"] = safe_int(state.get("history_count_hint", 0), 0) + (1 if added else 0)
        self.write_state(state)
        return event_path

    def output_path(self, task_type: str, key: str = "") -> Path:
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        return self.config.work_dir / "analysis" / f"{timestamp}_{safe_key(task_type)}_{safe_key(key)}.md"

    def local_history_context(self) -> str:
        lines = [
            "Local NGA context files:",
            f"- latest event: {self.latest_event_path.resolve()}",
            f"- global history: {self.history_file.resolve()}",
        ]
        summary = source_index_summary(self.config.work_dir)
        if summary:
            lines.extend(["", summary])
        return "\n".join(lines)

    def build_prompt(self, task_type: str, user_prompt: str) -> str:
        base_prompt = self.load_base_prompt(task_type)
        if task_type == "manual_ask":
            prompt = self.build_manual_prompt(base_prompt, user_prompt)
        else:
            prompt = (user_prompt or base_prompt).strip()
        context = self.local_history_context()
        if context:
            prompt = prompt.rstrip() + "\n\n" + context
        return prompt.strip() + "\n"

    def build_manual_prompt(self, base_prompt: str, user_prompt: str) -> str:
        return user_prompt.strip() + "\n"

    def load_base_prompt(self, task_type: str) -> str:
        if task_type == "manual_ask":
            return ""
        if task_type == "scheduled_analysis":
            if self.config.schedule_prompt_file:
                path = Path(self.config.schedule_prompt_file)
                if path.exists():
                    return path.read_text(encoding="utf-8", errors="replace")
            if self.config.schedule_prompt:
                return self.config.schedule_prompt
            path = self.config.work_dir / "prompts" / "scheduled_analysis.md"
            return path.read_text(encoding="utf-8", errors="replace") if path.exists() else DEFAULT_SCHEDULED_ANALYSIS_PROMPT
        if self.config.auto_analysis_prompt:
            return self.config.auto_analysis_prompt
        if self.config.prompt_file:
            path = Path(self.config.prompt_file)
            if path.exists():
                return path.read_text(encoding="utf-8", errors="replace")
        path = self.config.work_dir / "prompts" / "default_stock_analysis.md"
        return path.read_text(encoding="utf-8", errors="replace") if path.exists() else DEFAULT_STOCK_ANALYSIS_PROMPT

    def make_task(
        self,
        task_type: str,
        user_prompt: str,
        key: str = "",
        image_paths: list[Path] | None = None,
        file_paths: list[Path] | None = None,
    ) -> AITask:
        self.ensure_ready()
        return AITask(
            task_type=task_type,
            user_prompt=user_prompt,
            latest_event=self.latest_event_path,
            history_file=self.history_file,
            output_file=self.output_path(task_type, key or str(int(time.time()))),
            work_dir=self.config.work_dir,
            timeout=self.config.timeout,
            image_paths=list(image_paths or []),
            file_paths=list(file_paths or []),
            metadata={
                "created_at": utcish_now(),
                "provider": self.config.provider,
                "permission_mode": self.effective_permission_mode(),
                "model": self.effective_model(),
                "reasoning_effort": self.effective_reasoning_effort(),
            },
        )

    def run_task(self, task: AITask) -> AIResult:
        self.ensure_ready()
        logger = self.logger()
        prompt_text = self.build_prompt(task.task_type, task.user_prompt)
        if task.image_paths:
            prompt_text += "\n\nLocal image files attached to this task:\n" + "\n".join(f"- {path}" for path in task.image_paths) + "\n"
        if task.file_paths:
            prompt_text += "\n\nLocal files attached to this task:\n" + "\n".join(f"- {path}" for path in task.file_paths) + "\n"
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", prefix=f"{task.task_type}_", dir=self.config.work_dir / "prompts", delete=False) as f:
            f.write(prompt_text)
            prompt_file = Path(f.name)
        result = runner_for(self.effective_config()).run(task, prompt_file, prompt_text, logger)
        state = self.read_state()
        state["last_task_type"] = task.task_type
        state["last_provider"] = result.provider
        state["last_run_at"] = result.ended_at
        state["last_analysis_file"] = str(task.output_file)
        if result.ok:
            state["last_error"] = ""
            latest = self.config.work_dir / "analysis" / "latest_analysis.md"
            latest.write_text(result.text + "\n", encoding="utf-8")
        else:
            state["last_error"] = result.error
        self.write_state(state)
        return result

    def start_worker(self) -> None:
        with self._lock:
            if self._worker_started:
                return
            self._worker_started = True
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self) -> None:
        while True:
            task, chat_label = self._queue.get()
            try:
                try:
                    result = self.run_task(task)
                except Exception as exc:
                    self.logger().exception("AI worker task crashed task_type=%s", task.task_type)
                    result = AIResult(
                        ok=False,
                        provider=self.config.provider,
                        task_type=task.task_type,
                        output_file=task.output_file,
                        error=f"AI worker task crashed: {exc}",
                        started_at=utcish_now(),
                        ended_at=utcish_now(),
                    )
                    try:
                        state = self.read_state()
                        state["last_error"] = result.error
                        state["updated_at"] = utcish_now()
                        self.write_state(state)
                    except Exception:
                        self.logger().exception("failed to persist AI worker crash state")
                try:
                    if self.send_result:
                        if result.ok or self.config.send_errors_to_feishu:
                            self.send_result(result)
                    elif self.send_text:
                        if result.ok:
                            self.send_ai_result(result)
                        elif self.config.send_errors_to_feishu:
                            self.send_text(f"AI task failed: {result.error}")
                except Exception:
                    self.logger().exception("AI worker result delivery failed task_type=%s", task.task_type)
            finally:
                self._queue.task_done()

    def submit_task(self, task: AITask, chat_label: str | None = None, *, replace_scheduled: bool = False) -> bool:
        self.start_worker()
        if replace_scheduled and task.task_type == "scheduled_analysis":
            self._drop_pending_scheduled()
        try:
            self._queue.put_nowait((task, chat_label))
            return True
        except queue.Full:
            state = self.read_state()
            state["last_error"] = "AI task queue is full"
            self.write_state(state)
            return False

    def _drop_pending_scheduled(self) -> None:
        kept: list[tuple[AITask, str | None]] = []
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            task, label = item
            if task.task_type != "scheduled_analysis":
                kept.append(item)
            self._queue.task_done()
        for item in kept:
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                break

    def send_ai_result(self, result: AIResult) -> None:
        if not self.send_text:
            return
        text = result.text if result.ok else f"AI task failed: {result.error}"
        if len(text) <= self.config.max_feishu_chars:
            self.send_text(text)
            return
        summary = text[: self.config.max_feishu_chars] + "\n\n[truncated]"
        if self.config.upload_long_result and self.send_file:
            try:
                self.send_text(summary + f"\n\nFull result uploaded as `{result.output_file.name}`.")
                self.send_file(result.output_file.name, result.text)
            except Exception as exc:
                self.logger().warning("long result upload failed, sending truncated text: %s", exc)
                self.send_text(summary)
        else:
            self.send_text(summary)

    def maybe_auto_analyze(self, post: Any) -> None:
        self.maybe_auto_analyze_posts([post])

    def maybe_auto_analyze_posts(self, posts: list[Any]) -> None:
        saved_posts = [post for post in posts if post is not None]
        image_paths: list[Path] = []
        for post in saved_posts:
            event_path = self.save_post_event(post)
            if event_path and event_path.exists():
                image_paths.extend(image_paths_from_event(read_json(event_path, {})))
        if not saved_posts or not self.effective_enabled() or not self.effective_auto():
            return
        prompt = self.effective_config().auto_analysis_prompt or ""
        key = getattr(saved_posts[-1], "key", "") if len(saved_posts) == 1 else f"batch_{len(saved_posts)}_{getattr(saved_posts[-1], 'key', int(time.time()))}"
        task = self.make_task("new_post_analysis", prompt, key, image_paths=image_paths)
        self.submit_task(task)

    def maybe_scheduled_analysis(self, now: dt.datetime | None = None) -> bool:
        if not self.effective_enabled():
            return False
        effective = self.effective_config()
        state = self.read_state()
        if not should_trigger_schedule(state, effective, now):
            return False
        task = self.make_task("scheduled_analysis", effective.schedule_prompt or "", "scheduled")
        submitted = self.submit_task(task, replace_scheduled=True)
        if submitted:
            local_now = now or dt.datetime.now()
            state = self.read_state()
            state["last_scheduled_analysis_at"] = local_now.isoformat(timespec="seconds")
            state["last_scheduled_bucket"] = int(local_now.timestamp()) // (effective.schedule_interval_minutes * 60)
            self.write_state(state)
        return submitted

    def handle_command(
        self,
        text: str,
        sender_id: str | None = None,
        image_paths: list[Path] | None = None,
        file_paths: list[Path] | None = None,
    ) -> str:
        command = parse_ai_command(text)
        if command is None:
            return ""
        action, arg = command
        if action in {"help", "status", "prompt", "workdir", "history", "last", "mode", "model", "reasoning"}:
            pass
        elif not self.is_authorized(sender_id):
            return "AI command rejected: sender is not authorized."
        if action == "help":
            return ai_help_text()
        if action == "status":
            return self.status_text()
        self.ensure_ready()
        state = self.read_state()
        if action == "mode":
            if not arg.strip():
                options = "\n".join(f"- {key}: {desc}" for key, desc in permission_mode_options(self.config.provider))
                return f"Current AI permission mode: {self.effective_permission_mode()}\n\nAvailable modes:\n{options}"
            if not self.is_authorized(sender_id):
                return "AI command rejected: sender is not authorized."
            mode = normalize_permission_mode(arg, self.config.provider)
            state["permission_mode"] = mode
            self.write_state(state)
            return f"AI permission mode set to `{mode}`."
        if action == "model":
            if not arg.strip():
                model = self.effective_model()
                return f"Current AI model: `{model}`."
            if not self.is_authorized(sender_id):
                return "AI command rejected: sender is not authorized."
            raw = arg.strip()
            lowered = raw.lower()
            if lowered in {"default", "auto", "unset"}:
                if self.config.provider == "claude":
                    if lowered == "default":
                        state["model"] = "default"
                    else:
                        state.pop("model", None)
                else:
                    state.pop("model", None)
                state["updated_at"] = utcish_now()
                state["model_updated_at"] = state["updated_at"]
                self.write_state(state)
                model = self.effective_model()
                return f"AI model restored to default: `{model}`."
            if not is_valid_model(raw, self.config.provider):
                options = model_options(self.config.provider)
                if self.config.provider == "claude" and "default" not in options:
                    options = ["default", *options]
                detail = ", ".join(options) if options else "any custom string"
                return f"Unknown AI model for {self.config.provider}: `{raw}`. Available: {detail}."
            model = normalize_provider_model(self.config.provider, raw)
            state["model"] = model
            state["updated_at"] = utcish_now()
            state["model_updated_at"] = state["updated_at"]
            self.write_state(state)
            return f"AI model set to `{model}`."
        if action == "reasoning":
            if not arg.strip():
                effort = self.effective_reasoning_effort()
                return f"Current AI reasoning effort: `{effort}`."
            if not self.is_authorized(sender_id):
                return "AI command rejected: sender is not authorized."
            raw = arg.strip()
            lowered = raw.lower()
            if lowered in {"default", "unset"} or (lowered == "auto" and self.config.provider != "codewhale"):
                state.pop("reasoning_effort", None)
                state["updated_at"] = utcish_now()
                state["reasoning_effort_updated_at"] = state["updated_at"]
                self.write_state(state)
                effort = self.effective_reasoning_effort()
                return f"AI reasoning effort restored to default: `{effort}`."
            if not is_valid_reasoning_effort(raw, self.config.provider):
                options = reasoning_effort_options(self.config.provider)
                detail = ", ".join(options) if options else "any custom string"
                return f"Unknown AI reasoning effort: `{raw}`. Available: {detail}."
            effort = normalize_reasoning_effort(raw, self.config.provider)
            state["reasoning_effort"] = effort
            state["updated_at"] = utcish_now()
            state["reasoning_effort_updated_at"] = state["updated_at"]
            self.write_state(state)
            return f"AI reasoning effort set to `{effort}`."
        if action == "on":
            state["ai_enabled"] = True
            self.write_state(state)
            return "AI runtime switch is now on."
        if action == "off":
            state["ai_enabled"] = False
            self.write_state(state)
            return "AI runtime switch is now off."
        if action == "auto_on":
            state["auto_analyze_new_post"] = True
            self.write_state(state)
            return "New-post auto analysis is now on."
        if action == "auto_off":
            state["auto_analyze_new_post"] = False
            self.write_state(state)
            return "New-post auto analysis is now off."
        if action == "schedule_on":
            state["schedule_enabled"] = True
            self.write_state(state)
            return "Scheduled analysis is now on."
        if action == "schedule_off":
            state["schedule_enabled"] = False
            self.write_state(state)
            return "Scheduled analysis is now off."
        if action == "schedule_every":
            minutes = safe_int(arg, self.config.schedule_interval_minutes, 1)
            state["schedule_interval_minutes"] = minutes
            self.write_state(state)
            return f"Scheduled analysis interval set to {minutes} minute(s)."
        if action == "schedule_windows":
            state["schedule_windows"] = arg.strip() or DEFAULT_SCHEDULE_WINDOWS
            self.write_state(state)
            return f"Scheduled analysis windows set to `{state['schedule_windows']}`."
        if action == "schedule_prompt":
            state["schedule_prompt"] = arg.strip()
            self.write_state(state)
            return "Scheduled analysis prompt updated."
        if action == "auto_prompt":
            state["auto_analysis_prompt"] = arg.strip()
            self.write_state(state)
            return "New-post auto analysis prompt updated."
        if action == "prompt":
            prompt = Path(self.config.prompt_file) if self.config.prompt_file else self.config.work_dir / "prompts" / "default_stock_analysis.md"
            scheduled = Path(self.config.schedule_prompt_file) if self.config.schedule_prompt_file else self.config.work_dir / "prompts" / "scheduled_analysis.md"
            return f"Default prompt: {prompt}\nScheduled prompt: {scheduled}"
        if action == "workdir":
            return str(self.config.work_dir)
        if action == "history":
            count = safe_int(arg, 5, 1)
            return format_history(tail_jsonl(self.history_file, min(count, 50)))
        if action == "last":
            latest = self.config.work_dir / "analysis" / "latest_analysis.md"
            if not latest.exists():
                return "No AI analysis result yet."
            text = latest.read_text(encoding="utf-8", errors="replace").strip()
            return text if text else "Last AI analysis is empty."
        if not self.effective_enabled():
            return "AI is disabled. Use `/ai on` first, or `/ai status` to inspect current settings."
        if action == "latest":
            if not self.latest_event_path.exists():
                return "No latest wolf event has been saved yet."
            latest = read_json(self.latest_event_path, {})
            task = self.make_task("new_post_analysis", "", str(latest.get("key") or "latest"), image_paths=image_paths_from_event(latest))
            result = self.run_task(task)
            return format_feishu_result(result, self)
        if action == "ask":
            if not arg.strip():
                return "Usage: /ai ask <question>"
            task = self.make_task("manual_ask", arg.strip(), "ask", image_paths=image_paths, file_paths=file_paths)
            result = self.run_task(task)
            return format_feishu_result(result, self)
        return ai_help_text()

    def status_text(self) -> str:
        state = self.read_state()
        latest = read_json(self.latest_event_path, {})
        last_file = str(state.get("last_analysis_file") or "")
        return "\n".join(
            [
                "AI status",
                f"enabled: {self.effective_enabled()}",
                f"provider: {self.config.provider}",
                f"permission_mode: {self.effective_permission_mode()}",
                f"model: {self.effective_model()}",
                f"reasoning_effort: {self.effective_reasoning_effort()}",
                f"work_dir: {self.config.work_dir}",
                f"session_key: {shared_session_id(self.config.work_dir)}",
                f"auto_analyze_new_post: {self.effective_auto()}",
                f"schedule_enabled: {self.effective_schedule()}",
                f"schedule_interval_minutes: {self.effective_interval()}",
                f"schedule_windows: {self.effective_windows()}",
                f"latest_event: {latest.get('post_time', '')} {latest.get('url', '')}".strip(),
                f"last_analysis: {last_file}",
                f"last_error: {state.get('last_error', '')}",
            ]
        )


def parse_ai_command(text: str) -> tuple[str, str] | None:
    compact = " ".join(str(text or "").split())
    mode_match = re.search(r"(?:^|\s)/mode(?:\s+(.+?))?(?:\s|$)", compact, flags=re.I)
    if mode_match:
        return "mode", (mode_match.group(1) or "").strip()
    model_match = re.search(r"(?:^|\s)/model(?:\s+(.+?))?(?:\s|$)", compact, flags=re.I)
    if model_match:
        return "model", (model_match.group(1) or "").strip()
    reasoning_match = re.search(r"(?:^|\s)/(?:reasoning|effort)(?:\s+(.+?))?(?:\s|$)", compact, flags=re.I)
    if reasoning_match:
        return "reasoning", (reasoning_match.group(1) or "").strip()
    match = re.search(r"(?:^|\s)/ai(?:\s+(.*))?$", compact, flags=re.I)
    if not match:
        return None
    rest = (match.group(1) or "help").strip()
    lower = rest.lower()
    if lower in {"help", "status", "on", "off", "latest", "prompt", "workdir", "last"}:
        return lower, ""
    match_mode = re.fullmatch(r"mode(?:\s+(.+))?", rest, flags=re.I)
    if match_mode:
        return "mode", (match_mode.group(1) or "").strip()
    match_model = re.fullmatch(r"model(?:\s+(.+))?", rest, flags=re.I)
    if match_model:
        return "model", (match_model.group(1) or "").strip()
    match_reasoning = re.fullmatch(r"(?:reasoning|effort)(?:\s+(.+))?", rest, flags=re.I)
    if match_reasoning:
        return "reasoning", (match_reasoning.group(1) or "").strip()
    if lower == "auto on":
        return "auto_on", ""
    if lower == "auto off":
        return "auto_off", ""
    if lower == "schedule on":
        return "schedule_on", ""
    if lower == "schedule off":
        return "schedule_off", ""
    match_every = re.fullmatch(r"schedule\s+every\s+(\d+)", rest, flags=re.I)
    if match_every:
        return "schedule_every", match_every.group(1)
    match_windows = re.fullmatch(r"schedule\s+windows\s+(.+)", rest, flags=re.I)
    if match_windows:
        return "schedule_windows", match_windows.group(1)
    match_schedule_prompt = re.fullmatch(r"schedule\s+prompt(?:\s+(.+))?", rest, flags=re.I | re.S)
    if match_schedule_prompt:
        return "schedule_prompt", match_schedule_prompt.group(1) or ""
    match_auto_prompt = re.fullmatch(r"auto\s+prompt(?:\s+(.+))?", rest, flags=re.I | re.S)
    if match_auto_prompt:
        return "auto_prompt", match_auto_prompt.group(1) or ""
    match_history = re.fullmatch(r"history(?:\s+(\d+))?", rest, flags=re.I)
    if match_history:
        return "history", match_history.group(1) or "5"
    match_ask = re.fullmatch(r"ask(?:\s+(.+))?", rest, flags=re.I)
    if match_ask:
        return "ask", match_ask.group(1) or ""
    return "help", ""


def ai_help_text() -> str:
    return "\n".join(
        [
            "AI commands:",
            "/ai help",
            "/ai status",
            "/ai on | /ai off",
            "/ai auto on | /ai auto off",
            "/ai latest",
            "/ai ask <question> (optional; plain non-command messages also go to AI when AI is on)",
            "/mode [default|auto-edit|full-auto|yolo] or /ai mode <name>",
            "/model <name> or /ai model <name> (Claude also supports default)",
            "/reasoning <level> or /ai reasoning <level>",
            "/ai schedule on | /ai schedule off",
            "/ai schedule every <minutes>",
            f"/ai schedule windows {DEFAULT_SCHEDULE_WINDOWS}",
            "/ai schedule prompt <prompt>",
            "/ai auto prompt <prompt>",
            "/ai prompt",
            "/ai workdir",
            "/ai history <N>",
            "/ai last",
        ]
    )


def format_history(items: list[dict[str, Any]]) -> str:
    if not items:
        return "No saved wolf history yet."
    lines = ["Recent wolf posts:"]
    for item in items:
        content = re.sub(r"\s+", " ", str(item.get("content", ""))).strip()
        lines.append(f"- {item.get('post_time', '')} {item.get('url', '')}\n  {content[:160]}")
    return "\n".join(lines)


def format_feishu_result(result: AIResult, manager: AIManager) -> str:
    if result.ok:
        return result.text
    return f"AI task failed: {result.error}"
