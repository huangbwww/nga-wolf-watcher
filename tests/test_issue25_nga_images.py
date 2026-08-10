from __future__ import annotations

import urllib.error
from unittest.mock import patch

import nga_feishu_watch


class FakeImageResponse:
    def __init__(self, data: bytes, content_type: str = "image/jpeg") -> None:
        self.data = data
        self.headers = {
            "Content-Length": str(len(data)),
            "Content-Type": content_type,
        }

    def __enter__(self) -> "FakeImageResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int = -1) -> bytes:
        return self.data


def test_thread_payload_uses_advertised_attachment_base() -> None:
    payload = {
        "data": {
            "__GLOBAL": {"_ATTACH_BASE_VIEW": "img.nga.cn/attachments"},
            "__T": {"subject": "图片测试"},
            "__R": {
                "1": {
                    "tid": "47288722",
                    "pid": "877502328",
                    "content": "[img]./mon_202608/07/axyfQ45-test.jpg[/img]",
                }
            },
        }
    }

    posts, _page = nga_feishu_watch.extract_thread_posts(payload)

    assert posts[0].image_urls == (
        "https://img.nga.cn/attachments/mon_202608/07/axyfQ45-test.jpg",
    )


def test_relative_image_falls_back_to_current_nga_attachment_base() -> None:
    assert nga_feishu_watch.normalize_nga_image_url("./mon_202608/07/test.png") == (
        "https://img.nga.cn/attachments/mon_202608/07/test.png"
    )


def test_legacy_nga_image_host_is_migrated() -> None:
    assert nga_feishu_watch.normalize_nga_image_url(
        "https://img.nga.178.com/attachments/mon_202608/07/test.jpg"
    ) == "https://img.nga.cn/attachments/mon_202608/07/test.jpg"


def test_untrusted_payload_attachment_base_is_ignored() -> None:
    assert nga_feishu_watch.payload_nga_attachment_base(
        {"data": {"__GLOBAL": {"_ATTACH_BASE_VIEW": "images.example.com/attachments"}}}
    ) == nga_feishu_watch.NGA_DEFAULT_ATTACHMENT_BASE


def test_new_nga_image_host_retries_http_after_https_567() -> None:
    calls: list[str] = []

    def fake_urlopen(request: object, timeout: int) -> FakeImageResponse:
        del timeout
        url = request.full_url  # type: ignore[attr-defined]
        calls.append(url)
        if url.startswith("https://"):
            raise urllib.error.HTTPError(url, 567, "NGA image HTTPS rejected", {}, None)
        return FakeImageResponse(b"\xff\xd8\xff\xe0image")

    url = "https://img.nga.cn/attachments/mon_202608/07/test.jpg"
    with patch.object(nga_feishu_watch.urllib.request, "urlopen", side_effect=fake_urlopen):
        data, content_type = nga_feishu_watch.download_nga_image_bytes(url, "cookie", 10)

    assert calls == [url, url.replace("https://", "http://", 1)]
    assert data.startswith(b"\xff\xd8")
    assert content_type == "image/jpeg"


def test_card_fallback_link_uses_reachable_http_nga_url() -> None:
    elements: list[dict[str, object]] = []
    https_url = "https://img.nga.cn/attachments/mon_202608/07/test.jpg"

    nga_feishu_watch.append_post_image_elements(elements, [https_url], {}, "图片", 1)

    content = elements[0]["text"]["content"]  # type: ignore[index]
    assert "http://img.nga.cn/attachments/mon_202608/07/test.jpg" in content
