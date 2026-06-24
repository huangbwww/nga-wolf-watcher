from __future__ import annotations

from datetime import date

import stock_strategy


def test_calculate_row_observation_fib_and_signal() -> None:
    row = {
        "now": 62,
        "high": 100,
        "low": 50,
        "avg": 60,
        "cost": "",
    }

    stock_strategy.calculate_row(row, today=date(2026, 6, 22))

    assert row["f382"] == "80.900"
    assert row["f618"] == "69.100"
    assert row["f786"] == "60.700"
    assert row["topLine"] == "60.699"
    assert row["bottomLine"] == "59.309"
    assert row["signal"] == "跌破618(弱)"
    assert row["adviceClass"] == "advice-warning"


def test_calculate_row_position_stop_and_time_rules() -> None:
    stop_row = {
        "now": 93,
        "high": 110,
        "low": 96,
        "avg": 100,
        "cost": 100,
        "buyDate": "2026-06-01",
    }
    stock_strategy.calculate_row(stop_row, today=date(2026, 6, 22))
    assert stop_row["signal"] == "破底止损"

    time_row = {
        "now": 102,
        "high": 110,
        "low": 95,
        "avg": 100,
        "cost": 100,
        "buyDate": "2026-05-20",
        "highDate": "2026-06-01",
    }
    stock_strategy.calculate_row(time_row, today=date(2026, 6, 22))
    assert time_row["signal"] == "时间证伪(>13天)"


def test_macd_swing_defaults_from_reference_series_rules() -> None:
    klines = [
        {"date": f"2026-01-{idx + 1:02d}", "open": 10 + idx, "close": 10 + idx, "high": high, "low": low}
        for idx, (high, low) in enumerate(
            [
                (10, 8),
                (11, 7),
                (12, 9),
                (15, 10),
                (18, 12),
                (17, 13),
                (16, 12),
                (20, 11),
            ]
        )
    ]
    macd = [
        {"diff": -1, "dea": 0},
        {"diff": -0.5, "dea": 0},
        {"diff": 0.2, "dea": 0},
        {"diff": 0.5, "dea": 0},
        {"diff": 0.4, "dea": 0},
        {"diff": -0.1, "dea": 0},
        {"diff": -0.2, "dea": 0},
        {"diff": -0.3, "dea": 0},
    ]

    defaults = stock_strategy.find_macd_swing_defaults_from_series(klines, macd, 30)

    assert defaults["low"] == 7
    assert defaults["high"] == 20
    assert defaults["lowSource"] == "down-leg-low"
    assert defaults["highSource"] == "running-tail-high"


def test_shadow_advice_mapping() -> None:
    yesterday = {"open": 10, "close": 10.3, "high": 10.4, "low": 9.0}
    today = {"open": 10, "close": 10.5, "high": 12.0, "low": 9.9}

    advice = stock_strategy.calculate_advice2(yesterday=yesterday, today=today, trend="up")

    assert advice["text"] == "分歧但强势继续看新高"
    assert advice["className"] == "advice-cyan"
