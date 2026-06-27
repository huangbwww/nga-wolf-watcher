from __future__ import annotations

import json
from typing import Any

import nga_wolf_webgui


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_version_compare_handles_tags_and_dev_suffix() -> None:
    assert nga_wolf_webgui._is_newer_version("v1.5.3", "v1.5.2")
    assert nga_wolf_webgui._is_newer_version("v1.10.0", "v1.5.9")
    assert not nga_wolf_webgui._is_newer_version("v1.5.2", "v1.5.2-dev")
    assert not nga_wolf_webgui._is_newer_version("", "v1.5.2")


def test_check_update_returns_latest_release(monkeypatch) -> None:
    monkeypatch.setattr(nga_wolf_webgui, "APP_VERSION", "v1.5.2")

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        assert timeout == 8
        assert request.full_url == nga_wolf_webgui.LATEST_RELEASE_API_URL
        return FakeResponse(
            {
                "tag_name": "v1.5.3",
                "html_url": "https://github.com/huangbwww/nga-wolf-watcher/releases/tag/v1.5.3",
                "name": "v1.5.3",
                "published_at": "2026-06-24T00:00:00Z",
                "assets": [{"name": f"nga-wolf-{nga_wolf_webgui._PLATFORM_ASSET_KEYWORD}.zip"}],
            }
        )

    monkeypatch.setattr(nga_wolf_webgui, "urlopen", fake_urlopen)

    result = nga_wolf_webgui.PreviewApi().check_update()

    assert result["ok"] is True
    assert result["currentVersion"] == "v1.5.2"
    assert result["latestVersion"] == "v1.5.3"
    assert result["hasUpdate"] is True
    assert result["releaseUrl"].endswith("/releases/tag/v1.5.3")


def test_open_latest_release_page_sanitizes_untrusted_url(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(nga_wolf_webgui.webbrowser, "open", lambda url: opened.append(url) or True)

    result = nga_wolf_webgui.PreviewApi().open_latest_release_page("https://example.com/bad")

    assert result["ok"] is True
    assert result["url"] == nga_wolf_webgui.LATEST_RELEASE_PAGE_URL
    assert opened == [nga_wolf_webgui.LATEST_RELEASE_PAGE_URL]


def test_open_repository_page_uses_project_home(monkeypatch) -> None:
    opened: list[str] = []
    monkeypatch.setattr(nga_wolf_webgui.webbrowser, "open", lambda url: opened.append(url) or True)

    result = nga_wolf_webgui.PreviewApi().open_repository_page()

    assert result["ok"] is True
    assert result["url"] == nga_wolf_webgui.REPO_PAGE_URL
    assert opened == [nga_wolf_webgui.REPO_PAGE_URL]
