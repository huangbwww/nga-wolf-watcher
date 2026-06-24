from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any


ADVICE_NORMAL = "advice-normal"
ADVICE_DANGER = "advice-danger"
ADVICE_GOLD = "advice-gold"
ADVICE_BLUE = "advice-blue"
ADVICE_CYAN = "advice-cyan"
ADVICE_WARNING = "advice-warning"


def to_number(value: Any) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(n):
        return 0.0
    return n


def is_empty_price(value: Any) -> bool:
    return to_number(value) <= 0


def fmt(value: Any, digits: int = 3) -> str:
    return f"{to_number(value):.{digits}f}"


def average(values: list[float]) -> float:
    cleaned = [to_number(value) for value in values]
    return sum(cleaned) / len(cleaned) if cleaned else 0.0


def calc_ema(values: list[Any], period: int) -> list[float]:
    if not values:
        return []
    k = 2 / (period + 1)
    result = [to_number(values[0])]
    for value in values[1:]:
        result.append(to_number(value) * k + result[-1] * (1 - k))
    return result


def calc_macd(klines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    closes = [to_number(item.get("close")) for item in klines]
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    diff = [ema12[index] - ema26[index] for index in range(len(closes))]
    dea = calc_ema(diff, 9)
    return [
        {
            "date": item.get("date"),
            "diff": diff[index],
            "dea": dea[index],
            "macd": (diff[index] - dea[index]) * 2,
        }
        for index, item in enumerate(klines)
    ]


def calc_boll(closes: list[Any], n: int = 20, k: float = 2) -> list[dict[str, float | None]]:
    numbers = [to_number(value) for value in closes]
    result: list[dict[str, float | None]] = []
    for index, _value in enumerate(numbers):
        if index < n - 1:
            result.append({"mid": None, "up": None, "low": None})
            continue
        window = numbers[index - n + 1 : index + 1]
        mid = average(window)
        std = math.sqrt(sum((value - mid) ** 2 for value in window) / n)
        result.append(
            {
                "mid": round(mid, 3),
                "up": round(mid + k * std, 3),
                "low": round(mid - k * std, 3),
            }
        )
    return result


def find_macd_swing_defaults_from_series(
    klines: list[dict[str, Any]],
    macd_series: list[dict[str, Any]],
    window_size: int = 30,
    *,
    last_bar_incomplete: bool = False,
) -> dict[str, Any]:
    if not klines:
        return {"high": 0, "low": 0, "highSource": "none", "lowSource": "none"}

    recent = klines[-window_size:]
    fallback_high = max([to_number(item.get("high")) for item in recent] or [0])
    fallback_lows = [to_number(item.get("low")) for item in recent if to_number(item.get("low")) > 0]
    fallback_low = min(fallback_lows) if fallback_lows else 0

    def segment_high(start: int, end: int) -> float:
        value = 0.0
        for idx in range(max(start, 0), min(end, len(klines) - 1) + 1):
            value = max(value, to_number(klines[idx].get("high")))
        return value

    def segment_low(start: int, end: int) -> float:
        value = math.inf
        for idx in range(max(start, 0), min(end, len(klines) - 1) + 1):
            low = to_number(klines[idx].get("low"))
            if low > 0:
                value = min(value, low)
        return value if math.isfinite(value) else 0.0

    high = 0.0
    low = 0.0
    high_source = "range"
    low_source = "range"
    last_golden_idx = -1
    last_death_idx = -1
    cross_end = len(macd_series) - 1 if last_bar_incomplete else len(macd_series)

    for index in range(1, cross_end):
        prev = macd_series[index - 1]
        curr = macd_series[index]
        if not prev or not curr or index - 1 >= len(klines):
            continue
        if to_number(prev.get("diff")) <= to_number(prev.get("dea")) and to_number(curr.get("diff")) > to_number(curr.get("dea")):
            start = last_death_idx - 1 if last_death_idx > -1 else 0
            low = segment_low(start, index - 1)
            low_source = "down-leg-low"
            last_golden_idx = index
        if to_number(prev.get("diff")) >= to_number(prev.get("dea")) and to_number(curr.get("diff")) < to_number(curr.get("dea")):
            start = last_golden_idx - 1 if last_golden_idx > -1 else 0
            high = segment_high(start, index - 1)
            high_source = "up-leg-high"
            last_death_idx = index

    last_idx = len(klines) - 1
    last_cross_idx = max(last_golden_idx, last_death_idx)
    if last_cross_idx > -1:
        running_high = segment_high(last_cross_idx - 1, last_idx)
        if running_high > high:
            high = running_high
            high_source = "running-tail-high"
        if low > 0:
            running_low = segment_low(last_cross_idx - 1, last_idx)
            if 0 < running_low < low:
                low = running_low
                low_source = "running-tail-low"

    return {
        "high": high or fallback_high or 0,
        "low": low or fallback_low or 0,
        "highSource": high_source,
        "lowSource": low_source,
    }


def find_macd_swing_defaults(
    klines: list[dict[str, Any]],
    window_size: int = 30,
    *,
    last_bar_incomplete: bool = False,
) -> dict[str, Any]:
    return find_macd_swing_defaults_from_series(
        klines,
        calc_macd(klines),
        window_size,
        last_bar_incomplete=last_bar_incomplete,
    )


def classify_shadow(kline: dict[str, Any]) -> str:
    open_price = to_number(kline.get("open"))
    high = to_number(kline.get("high"))
    low = to_number(kline.get("low"))
    close = to_number(kline.get("close"))
    price_range = high - low
    if price_range <= 0:
        return "none"
    body = max(abs(close - open_price), price_range * 0.03)
    upper = high - max(open_price, close)
    lower = min(open_price, close) - low
    min_by_body = body * 1.5
    min_by_range = price_range * 0.4
    upper_ok = upper >= min_by_body and upper >= min_by_range
    lower_ok = lower >= min_by_body and lower >= min_by_range
    if upper_ok and not lower_ok:
        return "upper"
    if lower_ok and not upper_ok:
        return "lower"
    if upper_ok and lower_ok:
        return "upper" if upper > lower else "lower"
    return "none"


def calculate_trend(klines: list[dict[str, Any]], current_price: Any) -> str:
    closes = [to_number(item.get("close")) for item in klines if to_number(item.get("close")) > 0]
    now = to_number(current_price)
    if now > 0:
        closes.append(now)
    if len(closes) < 21:
        return "side"
    ma5 = average(closes[-5:])
    ma20 = average(closes[-20:])
    prev_ma20 = average(closes[-21:-1])
    price = now if now > 0 else closes[-1]
    up_votes = 0
    down_votes = 0

    def vote(a: float, b: float) -> None:
        nonlocal up_votes, down_votes
        margin = (abs(b) or 1) * 0.0005
        if a - b > margin:
            up_votes += 1
        elif b - a > margin:
            down_votes += 1

    vote(price, ma20)
    vote(ma5, ma20)
    vote(ma20, prev_ma20)
    if up_votes >= 2:
        return "up"
    if down_votes >= 2:
        return "down"
    return "side"


def get_candle_color(kline: dict[str, Any]) -> str:
    open_price = to_number(kline.get("open"))
    close = to_number(kline.get("close"))
    if close > open_price:
        return "red"
    if close < open_price:
        return "black"
    return "flat"


def calculate_advice2(*, yesterday: dict[str, Any], today: dict[str, Any], trend: str) -> dict[str, str]:
    if trend not in {"up", "down"}:
        return {"text": "趋势不明", "className": ADVICE_NORMAL}
    yesterday_shadow = classify_shadow(yesterday)
    today_shadow = classify_shadow(today)
    color = get_candle_color(today)
    if color == "flat":
        return {"text": "未触发", "className": ADVICE_NORMAL}
    sequence = ""
    if yesterday_shadow == "lower" and today_shadow == "upper":
        sequence = "lower-upper"
    if yesterday_shadow == "upper" and today_shadow == "lower":
        sequence = "upper-lower"
    if not sequence:
        return {"text": "未触发", "className": ADVICE_NORMAL}
    rules = {
        "down|black|lower-upper": {"text": "中继下跌", "className": ADVICE_DANGER},
        "down|red|lower-upper": {"text": "支撑位震荡选方向", "className": ADVICE_WARNING},
        "down|red|upper-lower": {"text": "支撑位资金抢反弹", "className": ADVICE_GOLD},
        "down|black|upper-lower": {"text": "短期止跌", "className": ADVICE_BLUE},
        "up|black|lower-upper": {"text": "开始有分歧", "className": ADVICE_WARNING},
        "up|red|lower-upper": {"text": "分歧但强势继续看新高", "className": ADVICE_CYAN},
        "up|red|upper-lower": {"text": "承接力度大但只承接不追高", "className": ADVICE_BLUE},
        "up|black|upper-lower": {"text": "承接低可能出现短期顶", "className": ADVICE_DANGER},
    }
    return rules.get(f"{trend}|{color}|{sequence}", {"text": "未触发", "className": ADVICE_NORMAL})


def parse_kline_rows(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, (list, tuple)) or len(row) < 5:
            continue
        item = {
            "date": str(row[0]),
            "open": to_number(row[1]),
            "close": to_number(row[2]),
            "high": to_number(row[3]),
            "low": to_number(row[4]),
            "volume": to_number(row[5]) if len(row) > 5 else 0,
        }
        if item["date"] and item["open"] > 0 and item["high"] > 0 and item["low"] > 0 and item["close"] > 0:
            parsed.append(item)
    return parsed


def parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def get_hold_days(start_date: Any, *, today: date | None = None) -> int:
    start = parse_date(start_date)
    current_today = today or date.today()
    if start is None:
        return 0
    if start > current_today:
        return 1
    days = 0
    current = start
    while current <= current_today:
        if current.weekday() < 5:
            days += 1
        current += timedelta(days=1)
    return days


def today_string() -> str:
    return date.today().isoformat()


def calculate_row(row: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
    now = to_number(row.get("now"))
    cost = to_number(row.get("cost"))
    low = to_number(row.get("low"))
    high = to_number(row.get("high"))
    avg = to_number(row.get("avg"))

    if not bool(row.get("_focusHigh")) and now > high and high > 0:
        high = now
        row["high"] = now
        row["highDate"] = today_string()
        row["_isNewHigh"] = True
    else:
        row["_isNewHigh"] = False

    diff = high - low
    row["f382"] = fmt(high - diff * 0.382)
    row["f618"] = fmt(high - diff * 0.618)
    row["f786"] = fmt(high - diff * 0.786)

    k_value = 0.98848
    if avg > 0:
        row["topLine"] = fmt(avg / k_value)
        row["bottomLine"] = fmt(avg * k_value)
    else:
        row["topLine"] = "0.00"
        row["bottomLine"] = "0.00"

    row["isBreakLow"] = False
    current_today = today or date.today()
    if cost > 0:
        if not str(row.get("buyDate") or "").strip():
            row["buyDate"] = current_today.isoformat()
        hold_days = get_hold_days(row.get("buyDate"), today=current_today)
        days_since_high = get_hold_days(row.get("highDate"), today=current_today) if row.get("highDate") else hold_days
        if low > 0 and now < low * 0.97:
            row["signal"] = "破底止损"
            row["adviceClass"] = ADVICE_DANGER
        elif now <= cost * 0.94:
            row["signal"] = "止损(-6%)"
            row["adviceClass"] = ADVICE_DANGER
        elif days_since_high >= 13 and high > 0 and not row.get("_isNewHigh"):
            row["signal"] = "时间证伪(>13天)"
            row["adviceClass"] = ADVICE_WARNING
        elif row.get("_isNewHigh") or (now == high and high > 0):
            row["signal"] = "突破新高"
            row["adviceClass"] = ADVICE_GOLD
        else:
            row["signal"] = f"持有({hold_days}天)"
            row["adviceClass"] = ADVICE_BLUE
    else:
        f382 = to_number(row.get("f382"))
        f618 = to_number(row.get("f618"))
        f786 = to_number(row.get("f786"))
        f500 = high - diff * 0.5
        if low > 0 and now < low:
            row["isBreakLow"] = True
            row["signal"] = "破位严禁"
            row["adviceClass"] = ADVICE_DANGER
        elif row.get("_isNewHigh"):
            row["signal"] = "突破跟进"
            row["adviceClass"] = ADVICE_DANGER
        elif low > 0:
            if now < f786:
                row["signal"] = "放弃(极弱)"
                row["adviceClass"] = ADVICE_NORMAL
            elif now < f618 * 0.99:
                row["signal"] = "跌破618(弱)"
                row["adviceClass"] = ADVICE_WARNING
            elif now <= f500 * 1.02:
                row["signal"] = "强防生死线"
                row["adviceClass"] = ADVICE_BLUE
            elif now <= f382 * 1.03:
                row["signal"] = "常规买点"
                row["adviceClass"] = ADVICE_CYAN
            else:
                row["signal"] = "高位观望"
                row["adviceClass"] = ADVICE_NORMAL
        else:
            row["signal"] = "观望"
            row["adviceClass"] = ADVICE_NORMAL
    return row


def is_trading_time(moment: datetime | None = None) -> bool:
    now = moment or datetime.now()
    if now.weekday() >= 5:
        return False
    time_number = now.hour * 100 + now.minute
    return (910 <= time_number <= 1205) or (1255 <= time_number <= 1605)


def is_last_bar_incomplete(row: dict[str, Any], klines: list[dict[str, Any]], *, moment: datetime | None = None) -> bool:
    if not klines:
        return False
    today_date = str(row.get("quoteDate") or date.today().isoformat())
    return str(klines[-1].get("date")) == today_date and is_trading_time(moment)


def stamp_anchor_base(row: dict[str, Any], klines: list[dict[str, Any]]) -> None:
    if not klines:
        return
    bar = klines[-1]
    if is_last_bar_incomplete(row, klines) and len(klines) > 1:
        bar = klines[-2]
    row["anchorBaseDate"] = bar.get("date")
    row["anchorBaseClose"] = to_number(bar.get("close"))
    row["exRights"] = False


def check_ex_rights(row: dict[str, Any], klines: list[dict[str, Any]]) -> None:
    anchor_date = str(row.get("anchorBaseDate") or "").strip()
    anchor_close = to_number(row.get("anchorBaseClose"))
    if not anchor_date or anchor_close <= 0:
        return
    bar = next((item for item in klines if str(item.get("date")) == anchor_date), None)
    if not bar:
        return
    drift = abs(to_number(bar.get("close")) - anchor_close) / anchor_close
    row["exRights"] = drift > 0.002


def apply_swing_defaults(
    row: dict[str, Any],
    klines: list[dict[str, Any]],
    *,
    fallback_high: Any = 0,
    fallback_low: Any = 0,
    force: bool = False,
) -> dict[str, Any]:
    defaults = find_macd_swing_defaults(klines, 30, last_bar_incomplete=is_last_bar_incomplete(row, klines))
    if force or is_empty_price(row.get("high")):
        row["high"] = fmt(defaults.get("high") or fallback_high)
        row["swingHighSource"] = defaults.get("highSource")
    if force or is_empty_price(row.get("low")):
        row["low"] = fmt(defaults.get("low") or fallback_low)
        row["swingLowSource"] = defaults.get("lowSource")
    stamp_anchor_base(row, klines)
    return row


def update_advice2(row: dict[str, Any], klines: list[dict[str, Any]]) -> dict[str, Any]:
    if not klines or len(klines) < 21:
        row["advice2"] = "数据不足"
        row["advice2Class"] = ADVICE_NORMAL
        row["klineStatus"] = "数据不足"
        return row
    today_date = str(row.get("quoteDate") or date.today().isoformat())
    complete_klines = [item for item in klines if str(item.get("date")) != today_date]
    yesterday = complete_klines[-1] if complete_klines else klines[-1]
    open_price = to_number(row.get("open"))
    high = to_number(row.get("dayHigh"))
    low = to_number(row.get("dayLow"))
    close = to_number(row.get("now"))
    if not yesterday or not open_price or not high or not low or not close:
        row["advice2"] = "数据不足"
        row["advice2Class"] = ADVICE_NORMAL
        row["klineStatus"] = "数据不足"
        return row
    today = {"date": today_date, "open": open_price, "high": high, "low": low, "close": close}
    trend = calculate_trend(complete_klines, close)
    advice = calculate_advice2(yesterday=yesterday, today=today, trend=trend)
    row["trend"] = trend
    row["advice2"] = advice["text"]
    row["advice2Class"] = advice["className"]
    row["klineStatus"] = "已更新"
    return row
