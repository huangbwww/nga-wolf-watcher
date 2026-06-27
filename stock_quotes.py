from __future__ import annotations

import codecs
import csv
import io
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import Request, urlopen

import stock_strategy


WATCHLIST_FILE = "stock_watchlist.json"
DEFAULT_FOCUS_GROUP = "重点关注"
HTTP_TIMEOUT = 10
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
INDEX_LIST = [
    {"code": "sh000001", "name": "上证指数"},
    {"code": "sz399001", "name": "深证成指"},
    {"code": "sz399006", "name": "创业板指"},
    {"code": "sh000688", "name": "科创50"},
]
SMALL_CAP_CODE = "sh000852"
WATCHLIST_LOCK = threading.RLock()


class WatchlistReadError(ValueError):
    pass


def watchlist_path(data_dir: Path) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / WATCHLIST_FILE


def watchlist_meta(data_dir: Path) -> dict[str, Any]:
    path = watchlist_path(data_dir)
    try:
        stat = path.stat()
        mtime_ns = stat.st_mtime_ns
        size = stat.st_size
    except OSError:
        mtime_ns = 0
        size = 0
    return {"dataPath": str(path), "dataMtime": mtime_ns, "dataSize": size}


def watchlist_signature(data_dir: Path) -> tuple[int, int]:
    meta = watchlist_meta(data_dir)
    return int(meta["dataMtime"]), int(meta["dataSize"])


def empty_watchlist() -> dict[str, Any]:
    return {
        "version": 1,
        "groups": [DEFAULT_FOCUS_GROUP],
        "activeGroup": "__all__",
        "items": [],
        "lastRefreshTime": "",
        "disclaimerAccepted": False,
    }


def load_watchlist(data_dir: Path) -> dict[str, Any]:
    path = watchlist_path(data_dir)
    if not path.exists():
        return empty_watchlist()
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except Exception as exc:
        raise WatchlistReadError(f"股票看板数据读取失败，请检查 {path}") from exc
    if not isinstance(data, dict):
        raise WatchlistReadError(f"股票看板数据格式错误，请检查 {path}")
    merged = empty_watchlist()
    merged.update(data)
    merged["groups"] = [str(group).strip() for group in merged.get("groups", []) if str(group).strip()]
    merged["items"] = [normalize_item(item) for item in merged.get("items", []) if isinstance(item, dict)]
    return merged


def save_watchlist(data_dir: Path, watchlist: dict[str, Any]) -> dict[str, Any]:
    cleaned = normalize_watchlist(watchlist)
    path = watchlist_path(data_dir)
    payload = json.dumps(cleaned, ensure_ascii=False, indent=2)
    tmp_path = path.with_name(f".{path.name}.{time.time_ns()}.tmp")
    try:
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
    return cleaned


def normalize_watchlist(watchlist: dict[str, Any] | None) -> dict[str, Any]:
    data = empty_watchlist()
    if isinstance(watchlist, dict):
        data.update(watchlist)
    groups: list[str] = [DEFAULT_FOCUS_GROUP]
    for group in data.get("groups", []):
        name = str(group or "").strip()
        if name and name not in groups:
            groups.append(name)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in data.get("items", []):
        if not isinstance(item, dict):
            continue
        normalized = normalize_item(item)
        code = normalized.get("fullCode")
        if not code or code in seen:
            continue
        seen.add(code)
        if normalized.get("group") and normalized["group"] not in groups:
            groups.append(normalized["group"])
        items.append(normalized)
    data["groups"] = groups
    data["items"] = items
    data["version"] = 1
    return data


def normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    code = normalize_code(item.get("fullCode") or item.get("code") or "")
    group = str(item.get("group") or "").strip()
    normalized = {
        "fullCode": code or str(item.get("fullCode") or "").strip().lower(),
        "name": str(item.get("name") or "").strip(),
        "group": group,
        "now": stock_strategy.to_number(item.get("now")),
        "changePct": stock_strategy.to_number(item.get("changePct")),
        "open": stock_strategy.to_number(item.get("open")),
        "prevClose": stock_strategy.to_number(item.get("prevClose")),
        "dayHigh": stock_strategy.to_number(item.get("dayHigh")),
        "dayLow": stock_strategy.to_number(item.get("dayLow")),
        "quoteDate": str(item.get("quoteDate") or "").strip(),
        "quoteTime": str(item.get("quoteTime") or "").strip(),
        "volume": stock_strategy.to_number(item.get("volume")),
        "amount": stock_strategy.to_number(item.get("amount")),
        "turnoverRate": stock_strategy.to_number(item.get("turnoverRate")),
        "avg": item.get("avg") if str(item.get("avg") or "").strip() else "",
        "high": item.get("high") if str(item.get("high") or "").strip() else "",
        "low": item.get("low") if str(item.get("low") or "").strip() else "",
        "cost": item.get("cost") if str(item.get("cost") or "").strip() else "",
        "shares": item.get("shares") if str(item.get("shares") or "").strip() else "",
        "buyDate": str(item.get("buyDate") or "").strip(),
        "positionNote": str(item.get("positionNote") or "").strip(),
        "highDate": str(item.get("highDate") or "").strip(),
        "f382": item.get("f382", "0.000"),
        "f618": item.get("f618", "0.000"),
        "f786": item.get("f786", "0.000"),
        "topLine": item.get("topLine", "0.00"),
        "bottomLine": item.get("bottomLine", "0.00"),
        "signal": str(item.get("signal") or "观望"),
        "adviceClass": str(item.get("adviceClass") or stock_strategy.ADVICE_NORMAL),
        "advice2": str(item.get("advice2") or "待计算"),
        "advice2Class": str(item.get("advice2Class") or stock_strategy.ADVICE_NORMAL),
        "klineStatus": str(item.get("klineStatus") or ""),
        "trend": str(item.get("trend") or ""),
        "anchorBaseDate": str(item.get("anchorBaseDate") or "").strip(),
        "anchorBaseClose": stock_strategy.to_number(item.get("anchorBaseClose")),
        "exRights": bool(item.get("exRights", False)),
        "isBreakLow": bool(item.get("isBreakLow", False)),
        "swingHighSource": str(item.get("swingHighSource") or ""),
        "swingLowSource": str(item.get("swingLowSource") or ""),
    }
    return stock_strategy.calculate_row(normalized)


def fetch_text(url: str, *, encoding: str = "utf-8") -> str:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://finance.qq.com/"})
    with urlopen(request, timeout=HTTP_TIMEOUT) as response:
        data = response.read()
    return data.decode(encoding, errors="replace")


def normalize_code(value: Any) -> str | None:
    code = str(value or "").strip().lower()
    if not code:
        return None
    if re.match(r"^(sh|sz|hk|bj)[a-z0-9]+$", code):
        return code
    if not re.match(r"^\d+$", code):
        return None
    if len(code) <= 4 or (len(code) == 5 and code.startswith("0")):
        return "hk" + code.zfill(5)
    if len(code) == 6:
        if re.match(r"^(5[168]|6)", code):
            return "sh" + code
        if re.match(r"^(1[568]|0|3)", code):
            return "sz" + code
        if re.match(r"^(4|8)", code):
            return "bj" + code
    return None


def market_label(code: str) -> str:
    if code.startswith("sh"):
        return "沪"
    if code.startswith("sz"):
        return "深"
    if code.startswith("bj"):
        return "北"
    if code.startswith("hk"):
        return "港"
    return "其他"


def fetch_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    normalized_codes = [code for code in [normalize_code(item) for item in codes] if code]
    if not normalized_codes:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for start in range(0, len(normalized_codes), 60):
        chunk = normalized_codes[start : start + 60]
        text = fetch_text(f"https://qt.gtimg.cn/q={','.join(chunk)}", encoding="gb18030")
        for match in re.finditer(r'v_([a-z0-9]+)="(.*?)";', text, flags=re.S):
            code = match.group(1).lower()
            fields = match.group(2).split("~")
            quote_data = parse_quote_fields(code, fields)
            if quote_data:
                result[code] = quote_data
    return result


def parse_quote_fields(code: str, fields: list[str]) -> dict[str, Any] | None:
    if len(fields) < 35:
        return None
    name = fields[1].strip()
    now = stock_strategy.to_number(fields[3])
    prev_close = stock_strategy.to_number(fields[4])
    open_price = stock_strategy.to_number(fields[5])
    timestamp = re.sub(r"\D", "", fields[30] if len(fields) > 30 else "")
    quote_date = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}" if len(timestamp) >= 8 else ""
    quote_time = f"{timestamp[8:10]}:{timestamp[10:12]}:{timestamp[12:14]}" if len(timestamp) >= 14 else ""
    day_high = stock_strategy.to_number(fields[33] if len(fields) > 33 else 0)
    day_low = stock_strategy.to_number(fields[34] if len(fields) > 34 else 0)
    volume = stock_strategy.to_number(fields[36] if len(fields) > 36 else 0)
    amount = stock_strategy.to_number(fields[37] if len(fields) > 37 else 0)
    avg = stock_strategy.to_number(fields[4])
    if volume > 0:
        if code.startswith("hk"):
            avg = amount / volume
        elif code.startswith("sh68") or code.startswith("bj"):
            avg = (amount * 10000) / volume
        else:
            avg = (amount * 10000) / (volume * 100)
    return {
        "fullCode": code,
        "code": re.sub(r"^(sh|sz|hk|bj)", "", code),
        "name": name,
        "market": market_label(code),
        "now": now,
        "prevClose": prev_close,
        "open": open_price,
        "change": stock_strategy.to_number(fields[31] if len(fields) > 31 else 0),
        "changePct": stock_strategy.to_number(fields[32] if len(fields) > 32 else 0),
        "dayHigh": day_high,
        "dayLow": day_low,
        "quoteDate": quote_date,
        "quoteTime": quote_time,
        "volume": volume,
        "amount": amount,
        "turnoverRate": stock_strategy.to_number(fields[38] if len(fields) > 38 else 0),
        "avg": round(avg, 3) if avg > 0 else "",
    }


def merge_quote(row: dict[str, Any], quote_data: dict[str, Any]) -> dict[str, Any]:
    for key in [
        "name",
        "now",
        "prevClose",
        "open",
        "change",
        "changePct",
        "dayHigh",
        "dayLow",
        "quoteDate",
        "quoteTime",
        "volume",
        "amount",
        "turnoverRate",
    ]:
        value = quote_data.get(key)
        if value not in (None, ""):
            row[key] = value
    if is_empty_string(row.get("avg")) and quote_data.get("avg"):
        row["avg"] = quote_data["avg"]
    elif stock_strategy.to_number(quote_data.get("avg")) > 0 and not bool(row.get("_focusAvg")):
        row["avg"] = quote_data["avg"]
    if not row.get("name"):
        row["name"] = quote_data.get("name") or row.get("fullCode")
    return row


def is_empty_string(value: Any) -> bool:
    return not str(value or "").strip()


def fetch_kline(code: str, period: str = "day") -> list[dict[str, Any]]:
    full_code = normalize_code(code)
    if not full_code:
        return []
    period = period if period in {"m5", "m15", "m30", "m60", "day", "week", "month"} else "day"
    var_name = f"kline_{full_code}_{int(time.time() * 1000)}"
    if period.startswith("m"):
        url = f"https://ifzq.gtimg.cn/appstock/app/kline/mkline?_var={var_name}&param={full_code},{period},,320"
    else:
        url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?_var={var_name}&param={full_code},{period},,,180,qfq"
    text = fetch_text(url)
    payload = parse_jsonp_object(text)
    node = (payload.get("data") or {}).get(full_code) if isinstance(payload, dict) else None
    if not isinstance(node, dict):
        return []
    rows = node.get("qfq" + period) or node.get(period) or []
    return stock_strategy.parse_kline_rows(rows)


def parse_minute_points(rows: list[Any]) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    for line in rows:
        parts = str(line).strip().split()
        if len(parts) < 3:
            continue
        price = stock_strategy.to_number(parts[1])
        if price <= 0:
            continue
        points.append(
            {
                "time": parts[0],
                "price": price,
                "volume": stock_strategy.to_number(parts[2]),
                "amount": stock_strategy.to_number(parts[3] if len(parts) > 3 else 0),
            }
        )
    return points


def minute_prev_close(node: dict[str, Any], full_code: str, fallback: Any = 0) -> float:
    prev_close = stock_strategy.to_number(fallback)
    qt = node.get("qt") if isinstance(node.get("qt"), dict) else {}
    qt_row = qt.get(full_code)
    if isinstance(qt_row, list) and len(qt_row) > 4:
        prev_close = stock_strategy.to_number(qt_row[4]) or prev_close
    return prev_close


def normalize_minute_date(value: Any) -> str:
    raw = re.sub(r"\D", "", str(value or ""))
    return raw if len(raw) == 8 else ""


def build_minute_payload(
    full_code: str,
    *,
    date: Any,
    rows: list[Any],
    prev_close: Any = 0,
    source: str = "minute-query",
    is_fallback: bool = False,
) -> dict[str, Any]:
    points = parse_minute_points(rows)
    prev_close_number = stock_strategy.to_number(prev_close)
    if prev_close_number <= 0 and points:
        prev_close_number = points[0]["price"]
    return {
        "code": full_code,
        "date": str(date or ""),
        "points": points,
        "prevClose": prev_close_number,
        "source": source,
        "isFallback": is_fallback,
    }


def fetch_recent_minutes(code: str, *, prev_close: Any = 0) -> list[dict[str, Any]]:
    full_code = normalize_code(code)
    if not full_code:
        return []
    text = fetch_text(f"https://web.ifzq.gtimg.cn/appstock/app/day/query?code={full_code}")
    payload = parse_jsonp_object(text)
    node = (payload.get("data") or {}).get(full_code) if isinstance(payload, dict) else None
    if not isinstance(node, dict):
        return []
    day_rows = node.get("data") if isinstance(node.get("data"), list) else []
    result: list[dict[str, Any]] = []
    for day in day_rows:
        if not isinstance(day, dict):
            continue
        rows = day.get("data") if isinstance(day.get("data"), list) else []
        if not rows:
            continue
        fallback_prev_close = minute_prev_close(node, full_code, day.get("prec") or prev_close)
        minute = build_minute_payload(
            full_code,
            date=day.get("date") or "",
            rows=rows,
            prev_close=fallback_prev_close,
            source="recent-trading-day",
            is_fallback=False,
        )
        if minute["points"]:
            result.append(minute)
    return result


def fetch_recent_minute(code: str, *, date: Any = "", prev_close: Any = 0, is_fallback: bool = True) -> dict[str, Any] | None:
    wanted_date = normalize_minute_date(date)
    recent_minutes = fetch_recent_minutes(code, prev_close=prev_close)
    if wanted_date:
        selected = next((minute for minute in recent_minutes if normalize_minute_date(minute.get("date")) == wanted_date), None)
        if selected:
            return {**selected, "source": "historical-trading-day", "isFallback": False}
        return None
    if recent_minutes:
        return {**recent_minutes[0], "isFallback": is_fallback}
    return None


def fetch_minute(code: str, *, date: Any = "") -> dict[str, Any] | None:
    full_code = normalize_code(code)
    if not full_code:
        return None
    selected_date = normalize_minute_date(date)
    if selected_date:
        return fetch_recent_minute(full_code, date=selected_date, is_fallback=False)
    var_name = f"min_{full_code}_{int(time.time() * 1000)}"
    text = fetch_text(f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var={var_name}&code={full_code}")
    payload = parse_jsonp_object(text)
    node = (payload.get("data") or {}).get(full_code) if isinstance(payload, dict) else None
    if not isinstance(node, dict):
        return None
    data_node = node.get("data") if isinstance(node.get("data"), dict) else {}
    rows = data_node.get("data") if isinstance(data_node.get("data"), list) else []
    prev_close = minute_prev_close(node, full_code)
    main = build_minute_payload(full_code, date=data_node.get("date") or "", rows=rows, prev_close=prev_close)
    if main["points"]:
        return main
    return fetch_recent_minute(full_code, prev_close=main.get("prevClose")) or main


def parse_jsonp_object(text: str) -> dict[str, Any]:
    match = re.search(r"^[^(=]+=(.*?);?\s*$", text.strip(), flags=re.S)
    raw = match.group(1) if match else text
    return json.loads(raw)


def update_kline_derived(row: dict[str, Any], *, apply_defaults: bool = False, force_defaults: bool = False) -> dict[str, Any]:
    klines = fetch_kline(str(row.get("fullCode") or ""), "day")
    if not klines:
        row["advice2"] = "K线不可用"
        row["advice2Class"] = stock_strategy.ADVICE_NORMAL
        row["klineStatus"] = "K线不可用"
        if apply_defaults:
            fallback_high = row.get("dayHigh") or row.get("now") or 0
            fallback_low = row.get("dayLow") or row.get("now") or 0
            if stock_strategy.is_empty_price(row.get("high")) or force_defaults:
                row["high"] = stock_strategy.fmt(fallback_high)
            if stock_strategy.is_empty_price(row.get("low")) or force_defaults:
                row["low"] = stock_strategy.fmt(fallback_low)
        return stock_strategy.calculate_row(row)
    if apply_defaults or force_defaults:
        stock_strategy.apply_swing_defaults(
            row,
            klines,
            fallback_high=row.get("dayHigh") or row.get("now") or 0,
            fallback_low=row.get("dayLow") or row.get("now") or 0,
            force=force_defaults,
        )
    stock_strategy.check_ex_rights(row, klines)
    stock_strategy.update_advice2(row, klines)
    return stock_strategy.calculate_row(row)


def refresh_items(items: list[dict[str, Any]], *, include_kline: bool = False, apply_defaults: bool = False) -> list[dict[str, Any]]:
    codes = [str(item.get("fullCode") or "") for item in items]
    quotes = fetch_quotes(codes) if codes else {}
    refreshed: list[dict[str, Any]] = []
    for item in items:
        row = normalize_item(item)
        quote_data = quotes.get(str(row.get("fullCode") or ""))
        if quote_data:
            merge_quote(row, quote_data)
        stock_strategy.calculate_row(row)
        needs_swing_defaults = stock_strategy.is_empty_price(row.get("high")) or stock_strategy.is_empty_price(row.get("low"))
        if include_kline or needs_swing_defaults:
            try:
                update_kline_derived(row, apply_defaults=apply_defaults or needs_swing_defaults)
            except Exception as exc:
                row["klineStatus"] = f"K线更新失败: {exc}"
        refreshed.append(normalize_item(row))
    refreshed.sort(key=lambda item: 0 if stock_strategy.to_number(item.get("cost")) > 0 else 1)
    return refreshed


def bootstrap(data_dir: Path) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
        if watchlist.get("items"):
            try:
                before = watchlist_signature(data_dir)
                watchlist["items"] = refresh_items(watchlist["items"], include_kline=False)
                watchlist["lastRefreshTime"] = datetime.now().strftime("%H:%M:%S")
                if before != watchlist_signature(data_dir):
                    watchlist = load_watchlist(data_dir)
                    watchlist["items"] = refresh_items(watchlist["items"], include_kline=False)
                    watchlist["lastRefreshTime"] = datetime.now().strftime("%H:%M:%S")
                save_watchlist(data_dir, watchlist)
            except WatchlistReadError:
                raise
            except Exception:
                pass
        return {
            "ok": True,
            "watchlist": watchlist,
            "indexes": safe_fetch_indexes(),
            **watchlist_meta(data_dir),
        }


def reload_watchlist(data_dir: Path, *, include_indexes: bool = False) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        result: dict[str, Any] = {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}
    if include_indexes:
        result["indexes"] = safe_fetch_indexes()
    return result


def fetch_indexes() -> list[dict[str, Any]]:
    codes = [item["code"] for item in INDEX_LIST]
    quotes = fetch_quotes(codes)
    indexes = []
    for item in INDEX_LIST:
        quote_data = quotes.get(item["code"], {})
        indexes.append({**item, **quote_data, "name": item["name"]})
    return indexes


def safe_fetch_indexes() -> list[dict[str, Any]]:
    try:
        return fetch_indexes()
    except Exception:
        return [{**item, "fullCode": item["code"], "now": 0, "changePct": 0} for item in INDEX_LIST]


def search_symbols(query: Any, *, current_items: list[dict[str, Any]] | None = None, limit: int = 12) -> list[dict[str, Any]]:
    text = str(query or "").strip()
    if not text:
        return []
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        code = normalize_code(item.get("fullCode") or item.get("code") or "")
        if not code or code in seen:
            return
        seen.add(code)
        results.append(
            {
                "fullCode": code,
                "code": re.sub(r"^(sh|sz|hk|bj)", "", code),
                "name": str(item.get("name") or code),
                "market": market_label(code),
                "pinyin": str(item.get("pinyin") or ""),
                "type": str(item.get("type") or ""),
                "source": str(item.get("source") or "remote"),
            }
        )

    for row in current_items or []:
        haystack = " ".join(
            [
                str(row.get("fullCode") or ""),
                str(row.get("name") or ""),
                str(row.get("pinyin") or ""),
            ]
        ).lower()
        if text.lower() in haystack:
            add({**row, "source": "watchlist"})

    direct_code = normalize_code(text)
    if direct_code:
        quote_data = fetch_quotes([direct_code]).get(direct_code)
        add({"fullCode": direct_code, "name": (quote_data or {}).get("name") or direct_code, "source": "code"})

    for item in search_tencent(text):
        add(item)
    if len(results) < limit:
        for item in search_sina(text):
            add(item)

    quote_codes = [item["fullCode"] for item in results[:limit]]
    quotes = fetch_quotes(quote_codes) if quote_codes else {}
    enriched = []
    for item in results[:limit]:
        quote_data = quotes.get(item["fullCode"], {})
        enriched.append({**item, **quote_data, "name": quote_data.get("name") or item.get("name")})
    return enriched


def search_tencent(query_text: str) -> list[dict[str, Any]]:
    try:
        text = fetch_text(f"https://smartbox.gtimg.cn/s3/?v=2&t=all&q={quote(query_text)}")
    except Exception:
        return []
    match = re.search(r'v_hint="(.*?)"', text, flags=re.S)
    if not match or match.group(1) == "N":
        return []
    content = codecs.decode(match.group(1), "unicode_escape")
    results: list[dict[str, Any]] = []
    for chunk in content.split("^"):
        parts = chunk.split("~")
        if len(parts) < 3:
            continue
        market, code, name = parts[:3]
        if market not in {"sh", "sz", "bj", "hk"}:
            continue
        results.append(
            {
                "fullCode": market + code,
                "name": name,
                "pinyin": parts[3] if len(parts) > 3 else "",
                "type": parts[4] if len(parts) > 4 else "",
                "source": "tencent",
            }
        )
    return results


def search_sina(query_text: str) -> list[dict[str, Any]]:
    try:
        text = fetch_text(f"https://suggest3.sinajs.cn/suggest/type=&key={quote(query_text)}", encoding="gb18030")
    except Exception:
        return []
    match = re.search(r'var suggestvalue="(.*?)"', text, flags=re.S)
    if not match:
        return []
    results: list[dict[str, Any]] = []
    for chunk in match.group(1).split(";"):
        cols = chunk.split(",")
        if len(cols) < 5:
            continue
        full_code = normalize_code(cols[3])
        if not full_code:
            continue
        results.append(
            {
                "fullCode": full_code,
                "name": cols[4] or cols[0],
                "pinyin": "",
                "type": cols[1],
                "source": "sina",
            }
        )
    return results


def add_codes(data_dir: Path, codes: list[Any], *, group: str = "") -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
        normalized_codes = [code for code in [normalize_code(item) for item in codes] if code]
        if not normalized_codes:
            return {"ok": False, "error": "请输入有效股票代码"}
        existing_by_code = {item["fullCode"]: item for item in watchlist["items"]}
        quotes = fetch_quotes(normalized_codes)
        for code in normalized_codes:
            quote_data = quotes.get(code)
            if not quote_data:
                continue
            row = existing_by_code.get(code) or {
                "fullCode": code,
                "name": quote_data.get("name") or code,
                "group": group if group and group not in {"__all__", "__none__"} else "",
                "cost": "",
                "shares": "",
                "high": "",
                "low": "",
                "buyDate": "",
                "positionNote": "",
                "highDate": "",
                "advice2": "待计算",
                "advice2Class": stock_strategy.ADVICE_NORMAL,
            }
            merge_quote(row, quote_data)
            stock_strategy.calculate_row(row)
            try:
                update_kline_derived(row, apply_defaults=True)
            except Exception as exc:
                row["klineStatus"] = f"K线更新失败: {exc}"
            existing_by_code[code] = normalize_item(row)
            if row.get("group") and row["group"] not in watchlist["groups"]:
                watchlist["groups"].append(row["group"])
        ordered_existing = [existing_by_code[item["fullCode"]] for item in watchlist["items"] if item["fullCode"] in existing_by_code]
        new_rows = [existing_by_code[code] for code in normalized_codes if code in existing_by_code and code not in {item["fullCode"] for item in watchlist["items"]}]
        watchlist["items"] = new_rows + ordered_existing
        watchlist["lastRefreshTime"] = datetime.now().strftime("%H:%M:%S")
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}


def refresh_watchlist(data_dir: Path, *, include_kline: bool = True) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        before = watchlist_signature(data_dir)
        watchlist = load_watchlist(data_dir)
        watchlist["items"] = refresh_items(watchlist["items"], include_kline=include_kline, apply_defaults=False)
        watchlist["lastRefreshTime"] = datetime.now().strftime("%H:%M:%S")
        if before != watchlist_signature(data_dir):
            watchlist = load_watchlist(data_dir)
            watchlist["items"] = refresh_items(watchlist["items"], include_kline=include_kline, apply_defaults=False)
            watchlist["lastRefreshTime"] = datetime.now().strftime("%H:%M:%S")
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": watchlist, "indexes": safe_fetch_indexes(), **watchlist_meta(data_dir)}


def update_item(data_dir: Path, code: str, patch: dict[str, Any]) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        full_code = normalize_code(code)
        if not full_code:
            return {"ok": False, "error": "无效股票代码"}
        watchlist = load_watchlist(data_dir)
        updated = False
        for item in watchlist["items"]:
            if item.get("fullCode") != full_code:
                continue
            for key in ["group", "cost", "shares", "high", "low", "avg", "buyDate", "positionNote", "highDate"]:
                if key in patch:
                    item[key] = patch[key]
            if item.get("group") and item["group"] not in watchlist["groups"]:
                watchlist["groups"].append(item["group"])
            stock_strategy.calculate_row(item)
            if any(key in patch for key in ["high", "low"]):
                try:
                    klines = fetch_kline(full_code, "day")
                    if klines:
                        stock_strategy.stamp_anchor_base(item, klines)
                        stock_strategy.update_advice2(item, klines)
                except Exception:
                    pass
            updated = True
            break
        if not updated:
            return {"ok": False, "error": "未找到股票"}
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}


def delete_item(data_dir: Path, code: str) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        full_code = normalize_code(code)
        if not full_code:
            return {"ok": False, "error": "无效股票代码"}
        watchlist = load_watchlist(data_dir)
        watchlist["items"] = [item for item in watchlist["items"] if item.get("fullCode") != full_code]
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}


def recalculate(data_dir: Path, code: str) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        full_code = normalize_code(code)
        if not full_code:
            return {"ok": False, "error": "无效股票代码"}
        watchlist = load_watchlist(data_dir)
        for item in watchlist["items"]:
            if item.get("fullCode") != full_code:
                continue
            update_kline_derived(item, apply_defaults=True, force_defaults=True)
            klines = fetch_kline(full_code, "day")
            high = stock_strategy.to_number(item.get("high"))
            high_bar = next((bar for bar in reversed(klines) if abs(stock_strategy.to_number(bar.get("high")) - high) < 0.0005), None)
            item["highDate"] = high_bar.get("date") if high_bar else ""
            stock_strategy.calculate_row(item)
            save_watchlist(data_dir, watchlist)
            return {"ok": True, "watchlist": load_watchlist(data_dir), "item": normalize_item(item), **watchlist_meta(data_dir)}
        return {"ok": False, "error": "未找到股票"}


def minute_options(minutes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "date": minute.get("date") or "",
            "pointCount": len(minute.get("points") or []),
        }
        for minute in minutes
        if minute.get("date")
    ]


def chart_data(data_dir: Path, code: str, *, period: str = "day", date: Any = "") -> dict[str, Any]:
    full_code = normalize_code(code)
    if not full_code:
        return {"ok": False, "error": "无效股票代码"}
    if period == "minute":
        selected_date = normalize_minute_date(date)
        main = fetch_minute(full_code, date=selected_date)
        recent_minutes = fetch_recent_minutes(full_code, prev_close=(main or {}).get("prevClose") if isinstance(main, dict) else 0)
        return {
            "ok": True,
            "kind": "minute",
            "code": full_code,
            "main": main,
            "selectedDate": selected_date,
            "recentMinutes": minute_options(recent_minutes),
        }
    klines = fetch_kline(full_code, period)
    watchlist = load_watchlist(data_dir)
    row = next((item for item in watchlist["items"] if item.get("fullCode") == full_code), None)
    if period == "day" and row and row.get("quoteDate") and not any(item.get("date") == row.get("quoteDate") for item in klines):
        open_price = stock_strategy.to_number(row.get("open"))
        high = stock_strategy.to_number(row.get("dayHigh"))
        low = stock_strategy.to_number(row.get("dayLow"))
        close = stock_strategy.to_number(row.get("now"))
        if open_price > 0 and high > 0 and low > 0 and close > 0:
            klines.append({"date": row["quoteDate"], "open": open_price, "close": close, "high": high, "low": low, "volume": row.get("volume", 0)})
    return {"ok": True, "kind": "kline", "code": full_code, "period": period, "klines": klines, "item": row}


def market_chart(code: str, *, period: str = "minute", date: Any = "") -> dict[str, Any]:
    full_code = normalize_code(code)
    if not full_code:
        return {"ok": False, "error": "无效指数代码"}
    if period == "minute":
        selected_date = normalize_minute_date(date)
        main = fetch_minute(full_code, date=selected_date)
        recent_minutes = fetch_recent_minutes(full_code, prev_close=(main or {}).get("prevClose") if isinstance(main, dict) else 0)
        return {
            "ok": True,
            "kind": "market-minute",
            "code": full_code,
            "main": main,
            "small": fetch_minute(SMALL_CAP_CODE, date=selected_date),
            "selectedDate": selected_date,
            "recentMinutes": minute_options(recent_minutes),
        }
    return {"ok": True, "kind": "kline", "code": full_code, "period": period, "klines": fetch_kline(full_code, period)}


def update_groups(data_dir: Path, groups: list[Any], active_group: str = "__all__") -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
        cleaned_groups: list[str] = [DEFAULT_FOCUS_GROUP]
        for group in groups:
            name = str(group or "").strip()
            if name and name not in cleaned_groups:
                cleaned_groups.append(name)
        watchlist["groups"] = cleaned_groups
        watchlist["activeGroup"] = active_group if active_group else "__all__"
        for item in watchlist["items"]:
            if item.get("group") and item["group"] not in cleaned_groups:
                item["group"] = ""
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}


def clear_watchlist(data_dir: Path) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
        watchlist["items"] = []
        watchlist["lastRefreshTime"] = datetime.now().strftime("%H:%M:%S")
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}


def accept_disclaimer(data_dir: Path) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
        watchlist["disclaimerAccepted"] = True
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}


def reorder_items(data_dir: Path, ordered_codes: list[Any]) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
        wanted = [code for code in [normalize_code(item) for item in ordered_codes] if code]
        rank = {code: index for index, code in enumerate(wanted)}
        watchlist["items"].sort(key=lambda item: rank.get(str(item.get("fullCode") or ""), len(rank)))
        save_watchlist(data_dir, watchlist)
        return {"ok": True, "watchlist": load_watchlist(data_dir), **watchlist_meta(data_dir)}


def export_csv(data_dir: Path) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["代码", "名称", "最新价", "阶段顶部", "阶段底部", "均价", "成本价", "持仓数量", "建仓日期", "持仓备注", "新高日期", "操作建议2", "分组"])
    for row in watchlist["items"]:
        writer.writerow(
            [
                row.get("fullCode", ""),
                row.get("name", ""),
                row.get("now", ""),
                row.get("high", ""),
                row.get("low", ""),
                row.get("avg", ""),
                row.get("cost", ""),
                row.get("shares", ""),
                row.get("buyDate", ""),
                row.get("positionNote", ""),
                row.get("highDate", ""),
                row.get("advice2", ""),
                row.get("group", ""),
            ]
        )
    return {"ok": True, "csv": "\ufeff" + output.getvalue(), "filename": "策略备份.csv"}


def import_csv(data_dir: Path, text: str) -> dict[str, Any]:
    with WATCHLIST_LOCK:
        watchlist = load_watchlist(data_dir)
        cleaned = str(text or "").lstrip("\ufeff")
        reader = csv.reader(io.StringIO(cleaned))
        rows = list(reader)
        if len(rows) <= 1:
            return {"ok": False, "error": "CSV 内容为空"}
        existing = {item["fullCode"]: item for item in watchlist["items"]}
        for cols in rows[1:]:
            if len(cols) < 2:
                continue
            code = normalize_code(cols[0])
            if not code:
                continue
            legacy_format = len(cols) <= 11
            group = (cols[10] if legacy_format and len(cols) > 10 else cols[12] if len(cols) > 12 else "").strip()
            if group and group not in watchlist["groups"]:
                watchlist["groups"].append(group)
            item = existing.get(code, {"fullCode": code})
            item.update(
                {
                    "name": cols[1].strip() if len(cols) > 1 else "",
                    "now": cols[2].strip() if len(cols) > 2 else 0,
                    "high": cols[3].strip() if len(cols) > 3 else "",
                    "low": cols[4].strip() if len(cols) > 4 else "",
                    "avg": cols[5].strip() if len(cols) > 5 else "",
                    "cost": cols[6].strip() if len(cols) > 6 else "",
                    "shares": "" if legacy_format else cols[7].strip() if len(cols) > 7 else "",
                    "buyDate": (cols[7] if legacy_format and len(cols) > 7 else cols[8] if len(cols) > 8 else "").strip(),
                    "positionNote": "" if legacy_format else cols[9].strip() if len(cols) > 9 else "",
                    "highDate": (cols[8] if legacy_format and len(cols) > 8 else cols[10] if len(cols) > 10 else "").strip(),
                    "advice2": (cols[9] if legacy_format and len(cols) > 9 else cols[11] if len(cols) > 11 else "待计算").strip(),
                    "group": group,
                }
            )
            stock_strategy.calculate_row(item)
            existing[code] = normalize_item(item)
        known_order = [item["fullCode"] for item in watchlist["items"]]
        extra = [code for code in existing if code not in known_order]
        watchlist["items"] = [existing[code] for code in [*extra, *known_order] if code in existing]
        save_watchlist(data_dir, watchlist)
        return refresh_watchlist(data_dir, include_kline=True)
