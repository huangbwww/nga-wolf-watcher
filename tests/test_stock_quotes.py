from __future__ import annotations

from pathlib import Path

import pytest

import stock_quotes


def test_empty_watchlist_has_default_focus_group(tmp_path: Path) -> None:
    watchlist = stock_quotes.load_watchlist(tmp_path)

    assert stock_quotes.DEFAULT_FOCUS_GROUP in watchlist["groups"]


def test_watchlist_persists_holding_fields(tmp_path: Path) -> None:
    stock_quotes.save_watchlist(
        tmp_path,
        {
            "groups": [],
            "items": [
                {
                    "fullCode": "sh600000",
                    "name": "浦发银行",
                    "group": stock_quotes.DEFAULT_FOCUS_GROUP,
                    "now": 12,
                    "cost": 10,
                    "shares": 100,
                    "buyDate": "2026-06-01",
                    "positionNote": "半仓",
                    "high": 13,
                    "low": 9,
                    "avg": 11,
                }
            ],
        },
    )

    watchlist = stock_quotes.load_watchlist(tmp_path)
    item = watchlist["items"][0]

    assert item["group"] == stock_quotes.DEFAULT_FOCUS_GROUP
    assert item["cost"] == 10
    assert item["shares"] == 100
    assert item["buyDate"] == "2026-06-01"
    assert item["positionNote"] == "半仓"


def test_refresh_does_not_overwrite_invalid_watchlist(tmp_path: Path) -> None:
    path = stock_quotes.watchlist_path(tmp_path)
    path.write_text("{invalid json", encoding="utf-8")

    with pytest.raises(stock_quotes.WatchlistReadError):
        stock_quotes.refresh_watchlist(tmp_path)

    assert path.read_text(encoding="utf-8") == "{invalid json"


def test_refresh_preserves_external_watchlist_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stock_quotes.save_watchlist(
        tmp_path,
        {
            "groups": [stock_quotes.DEFAULT_FOCUS_GROUP],
            "items": [
                {
                    "fullCode": "sh600000",
                    "name": "浦发银行",
                    "group": "",
                    "now": 10,
                    "high": 12,
                    "low": 8,
                    "avg": 10,
                }
            ],
        },
    )
    external = stock_quotes.normalize_watchlist(
        {
            "groups": [stock_quotes.DEFAULT_FOCUS_GROUP],
            "items": [
                {
                    "fullCode": "sh600000",
                    "name": "浦发银行",
                    "group": stock_quotes.DEFAULT_FOCUS_GROUP,
                    "now": 10,
                    "cost": 9,
                    "shares": 100,
                    "high": 12,
                    "low": 8,
                    "avg": 10,
                }
            ],
        }
    )
    calls = 0

    def fake_fetch_quotes(_codes: list[str]) -> dict[str, dict[str, object]]:
        nonlocal calls
        calls += 1
        if calls == 1:
            stock_quotes.watchlist_path(tmp_path).write_text(
                stock_quotes.json.dumps(external, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return {
            "sh600000": {
                "fullCode": "sh600000",
                "name": "浦发银行",
                "now": 11,
                "prevClose": 10,
                "open": 10,
                "changePct": 10,
                "dayHigh": 11,
                "dayLow": 10,
                "volume": 1000,
                "amount": 100,
                "turnoverRate": 1,
            }
        }

    monkeypatch.setattr(stock_quotes, "fetch_quotes", fake_fetch_quotes)

    result = stock_quotes.refresh_watchlist(tmp_path, include_kline=False)
    item = result["watchlist"]["items"][0]

    assert item["group"] == stock_quotes.DEFAULT_FOCUS_GROUP
    assert item["cost"] == 9
    assert item["shares"] == 100
    assert item["now"] == 11


def test_refresh_auto_fills_missing_swing_high_low(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    stock_quotes.save_watchlist(
        tmp_path,
        {
            "items": [
                {
                    "fullCode": "sh600000",
                    "name": "浦发银行",
                    "now": 10,
                    "open": 10,
                    "dayHigh": 11,
                    "dayLow": 9,
                    "avg": 10,
                }
            ],
        },
    )

    monkeypatch.setattr(
        stock_quotes,
        "fetch_quotes",
        lambda _codes: {
            "sh600000": {
                "fullCode": "sh600000",
                "name": "浦发银行",
                "now": 10,
                "open": 10,
                "prevClose": 10,
                "changePct": 0,
                "dayHigh": 11,
                "dayLow": 9,
                "volume": 1000,
                "amount": 100,
                "turnoverRate": 1,
            }
        },
    )
    monkeypatch.setattr(
        stock_quotes,
        "fetch_kline",
        lambda _code, _period="day": [
            {"date": f"2026-01-{idx + 1:02d}", "open": 10, "close": 10, "high": high, "low": low, "volume": 1000}
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
                    (19, 12),
                    (18, 12),
                    (17, 11),
                    (16, 10),
                    (15, 9),
                    (14, 8),
                    (13, 7),
                    (14, 8),
                    (15, 9),
                    (16, 10),
                    (17, 11),
                    (18, 12),
                    (19, 13),
                ]
            )
        ],
    )

    result = stock_quotes.refresh_watchlist(tmp_path, include_kline=False)
    item = result["watchlist"]["items"][0]

    assert float(item["high"]) > 0
    assert float(item["low"]) > 0
    assert item["f382"] != "0.000"


def test_clear_watchlist_keeps_default_group(tmp_path: Path) -> None:
    stock_quotes.save_watchlist(
        tmp_path,
        {
            "groups": [stock_quotes.DEFAULT_FOCUS_GROUP, "短线"],
            "activeGroup": "短线",
            "items": [{"fullCode": "sh600000", "name": "浦发银行"}],
        },
    )

    result = stock_quotes.clear_watchlist(tmp_path)

    assert result["ok"] is True
    assert result["watchlist"]["items"] == []
    assert stock_quotes.DEFAULT_FOCUS_GROUP in result["watchlist"]["groups"]


def test_accept_disclaimer_persists(tmp_path: Path) -> None:
    assert stock_quotes.load_watchlist(tmp_path)["disclaimerAccepted"] is False

    result = stock_quotes.accept_disclaimer(tmp_path)

    assert result["ok"] is True
    assert stock_quotes.load_watchlist(tmp_path)["disclaimerAccepted"] is True


def test_reorder_items_persists_manual_order(tmp_path: Path) -> None:
    stock_quotes.save_watchlist(
        tmp_path,
        {
            "items": [
                {"fullCode": "sh600000", "name": "浦发银行"},
                {"fullCode": "sz000001", "name": "平安银行"},
                {"fullCode": "sh688981", "name": "中芯国际"},
            ]
        },
    )

    result = stock_quotes.reorder_items(tmp_path, ["sh688981", "sh600000", "sz000001"])
    codes = [item["fullCode"] for item in result["watchlist"]["items"]]

    assert codes == ["sh688981", "sh600000", "sz000001"]
