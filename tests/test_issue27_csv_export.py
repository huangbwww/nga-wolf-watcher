from __future__ import annotations

import codecs
import csv
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
import webview

import nga_wolf_webgui
import stock_quotes


@pytest.fixture
def export_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    data_dir = tmp_path / "data"
    stock_quotes.save_watchlist(
        data_dir,
        {
            "groups": ["重点关注"],
            "items": [{
                "fullCode": "sh600000",
                "name": "浦发银行",
                "group": "重点关注",
                "shares": 100,
                "positionNote": '观察, "分批"\n买入',
            }],
        },
    )
    window = Mock()
    monkeypatch.setattr(nga_wolf_webgui, "_ACTIVE_WINDOW", window)
    monkeypatch.setattr(nga_wolf_webgui.legacy, "data_dir", lambda: data_dir)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    api = nga_wolf_webgui.PreviewApi.__new__(nga_wolf_webgui.PreviewApi)
    return api, window, data_dir


@pytest.mark.parametrize("selection_type", [tuple, list, str])
def test_export_saves_chinese_csv_and_reports_actual_path(export_api, tmp_path: Path, selection_type) -> None:
    api, window, data_dir = export_api
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    destination = downloads / "我的 策略备份.csv"
    selected = str(destination)
    window.create_file_dialog.return_value = selected if selection_type is str else selection_type([selected])

    result = api.stock_export_csv()

    assert result["ok"] is True
    assert result["path"] == str(destination.resolve())
    assert result["filename"] == destination.name
    assert result["path"] in result["message"]
    window.create_file_dialog.assert_called_once_with(
        webview.FileDialog.SAVE,
        directory=str(downloads),
        save_filename="策略备份.csv",
        file_types=("CSV 文件 (*.csv)",),
    )
    raw = destination.read_bytes()
    assert raw == stock_quotes.export_csv(data_dir)["csv"].encode("utf-8")
    assert raw.startswith(codecs.BOM_UTF8)
    assert not raw.startswith(codecs.BOM_UTF8 * 2)
    assert b"\r\r\n" not in raw
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    assert rows[1][0:2] == ["sh600000", "浦发银行"]
    assert rows[1][9] == '观察, "分批"\n买入'
    assert list(downloads.iterdir()) == [destination]
    assert not list(data_dir.glob("*.csv"))


@pytest.mark.parametrize("selection", [None, (), [], ""])
def test_cancel_creates_no_file_and_is_not_success(export_api, tmp_path: Path, selection) -> None:
    api, window, _ = export_api
    window.create_file_dialog.return_value = selection
    before = set(tmp_path.rglob("*"))

    result = api.stock_export_csv()

    assert result == {"ok": False, "cancelled": True}
    assert set(tmp_path.rglob("*")) == before
    assert window.create_file_dialog.call_args.kwargs["directory"] == str(tmp_path)


def test_export_without_window_reports_error(export_api, monkeypatch: pytest.MonkeyPatch) -> None:
    api, window, _ = export_api
    monkeypatch.setattr(nga_wolf_webgui, "_ACTIVE_WINDOW", None)

    result = api.stock_export_csv()

    assert result["ok"] is False
    assert "窗口未就绪" in result["error"]
    window.create_file_dialog.assert_not_called()


def test_export_dialog_failure_reports_error(export_api) -> None:
    api, window, _ = export_api
    window.create_file_dialog.side_effect = RuntimeError("dialog unavailable")

    result = api.stock_export_csv()

    assert result["ok"] is False
    assert "dialog unavailable" in result["error"]
    assert "path" not in result


def test_export_invalid_watchlist_does_not_offer_save(export_api) -> None:
    api, window, data_dir = export_api
    stock_quotes.watchlist_path(data_dir).write_text("{invalid", encoding="utf-8")

    result = api.stock_export_csv()

    assert result["ok"] is False
    window.create_file_dialog.assert_not_called()


def test_export_replaces_chosen_backup(export_api, tmp_path: Path) -> None:
    api, window, data_dir = export_api
    destination = tmp_path / "backup.csv"
    destination.write_text("old backup", encoding="utf-8")
    window.create_file_dialog.return_value = (str(destination),)

    result = api.stock_export_csv()

    assert result["ok"] is True
    assert destination.read_bytes() == stock_quotes.export_csv(data_dir)["csv"].encode("utf-8")


def test_export_accepts_long_filename(export_api, tmp_path: Path) -> None:
    api, window, _ = export_api
    destination = tmp_path / ("a" * 245 + ".csv")
    window.create_file_dialog.return_value = (str(destination),)

    result = api.stock_export_csv()

    assert result["ok"] is True
    assert destination.is_file()


@pytest.mark.parametrize("failure_stage", ["write", "replace"])
def test_failed_save_preserves_backup_and_removes_temporary_file(
    export_api, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_stage: str,
) -> None:
    api, window, _ = export_api
    destination = tmp_path / "backup.csv"
    destination.write_bytes(b"previous backup")
    window.create_file_dialog.return_value = (str(destination),)
    before = set(tmp_path.rglob("*"))

    if failure_stage == "write":
        original = nga_wolf_webgui.tempfile.NamedTemporaryFile

        def failing_output(*args, **kwargs):
            output = original(*args, **kwargs)

            def fail_write(text):
                output.file.write(text[:5])
                raise OSError("disk full")

            output.write = fail_write
            return output

        monkeypatch.setattr(nga_wolf_webgui.tempfile, "NamedTemporaryFile", failing_output)
    else:
        monkeypatch.setattr(Path, "replace", Mock(side_effect=PermissionError("file in use")))

    result = api.stock_export_csv()

    assert result["ok"] is False
    assert "导出 CSV 失败" in result["error"]
    assert "path" not in result
    assert destination.read_bytes() == b"previous backup"
    assert set(tmp_path.rglob("*")) == before
