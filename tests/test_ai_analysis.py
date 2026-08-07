from __future__ import annotations

from argparse import Namespace
import json
from pathlib import Path

import ai_analysis


def test_ai_config_uses_state_dir_for_stock_watchlist_path(tmp_path: Path) -> None:
    state_path = tmp_path / ".nga_seen.json"
    args = Namespace(ai_work_dir="agent", state_path=str(state_path))

    config = ai_analysis.AIConfig.from_namespace(args)

    assert config.work_dir == tmp_path / "agent"
    assert config.stock_watchlist_path == tmp_path / "stock_watchlist.json"


def test_ai_config_prefers_explicit_stock_watchlist_path(tmp_path: Path) -> None:
    explicit_path = tmp_path / "software" / "stock_watchlist.json"
    args = Namespace(ai_work_dir=str(tmp_path / "agent"), state_path="", stock_watchlist_path=str(explicit_path))

    config = ai_analysis.AIConfig.from_namespace(args)

    assert config.stock_watchlist_path == explicit_path


def test_local_history_context_syncs_positions_snapshot(tmp_path: Path) -> None:
    stock_path = tmp_path / "stock_watchlist.json"
    stock_path.write_text(
        json.dumps(
            {
                "groups": ["重点关注"],
                "items": [
                    {
                        "fullCode": "hk00700",
                        "name": "腾讯控股",
                        "group": "重点关注",
                        "now": 388,
                        "cost": 350,
                        "shares": 100,
                        "buyDate": "2026-06-01",
                    },
                    {"fullCode": "sh600000", "name": "浦发银行", "group": ""},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = ai_analysis.AIConfig(
        work_dir=tmp_path / ".ai_agent_workspace",
        stock_watchlist_path=stock_path,
    )

    context = ai_analysis.AIManager(config).local_history_context()

    assert f"- stock dashboard source: {stock_path.resolve()}" in context
    snapshot_path = tmp_path / ".ai_agent_workspace" / "context" / "positions.json"
    assert f"- synced positions snapshot: {snapshot_path.resolve()}" in context
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["holdings"][0]["fullCode"] == "hk00700"
    assert payload["focusWatch"][0]["fullCode"] == "hk00700"
    assert [item["fullCode"] for item in payload["items"]] == ["hk00700", "sh600000"]
