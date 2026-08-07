from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import ANY, patch

import nga_feishu_watch


def card_text(card: dict) -> str:
    parts: list[str] = []
    for element in card.get("elements", []):
        text = element.get("text") if isinstance(element, dict) else None
        if isinstance(text, dict):
            parts.append(str(text.get("content") or ""))
    return "\n".join(parts)


class FeishuCardFormatTests(unittest.TestCase):
    def test_extract_posts_uses_payload_user_table_for_author_name(self) -> None:
        payload = {
            "data": {
                "__U": {"150058": {"uid": "150058", "username": "-\u963f\u72fc-"}},
                "post": {
                    "pid": "872882235",
                    "tid": "45974302",
                    "authorid": "150058",
                    "postdate": "2026-06-25 14:06:20",
                    "subject": "\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635",
                    "content": "\u6d4b\u8bd5\u56de\u590d",
                    "lou": "3448",
                },
            }
        }

        posts = nga_feishu_watch.extract_posts(payload)

        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].author, "-\u963f\u72fc-")

    def test_feishu_card_uses_author_name_without_watch_source_line(self) -> None:
        post = nga_feishu_watch.NgaPost(
            key="872882235",
            subject="\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635",
            content="\u6d4b\u8bd5\u56de\u590d",
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=872882235",
            post_time="2026-06-25 14:06:20",
            author="-\u963f\u72fc-",
            author_id="150058",
            floor="3448",
            source_type="author",
            source_id="150058",
            source_label="\u72fc\u5927",
        )

        text = card_text(nga_feishu_watch.feishu_posts_card([post], "test"))

        self.assertIn(
            "**\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635**\n"
            "2026-06-25 14:06:20 | -\u963f\u72fc- | #3448",
            text,
        )
        self.assertIn("\u3010-\u963f\u72fc-\u3011\u56de\u590d\u5185\u5bb9\uff1a", text)
        self.assertNotIn("Watch:", text)

    def test_feishu_card_rewrites_nga_quote_header(self) -> None:
        post = nga_feishu_watch.NgaPost(
            key="872882235",
            subject="\u81ea\u7acb\u81ea\u5f3a",
            content=(
                "[pid=872881881,45974302,8136]Reply[/pid] Post by vxxxxv (2026-06-25 14:03):\n"
                "\u539f\u56de\u590d\u5185\u5bb9\n\n"
                "\u672c\u6b21\u56de\u590d\u5185\u5bb9"
            ),
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=872882235",
            post_time="2026-06-25 14:06:20",
            author="-\u963f\u72fc-",
            author_id="150058",
        )

        text = card_text(nga_feishu_watch.feishu_posts_card([post], "test"))

        self.assertIn("\u3010vxxxxv\u3011\u88ab\u56de\u590d\u5185\u5bb9\uff1a", text)
        self.assertIn("\u3010-\u963f\u72fc-\u3011\u56de\u590d\u5185\u5bb9\uff1a", text)
        self.assertNotIn("\u56de\u590d\u4e86\u4e0a\u9762\u8fd9\u53e5\u8bdd", text)
        self.assertNotIn("[pid=", text)
        self.assertNotIn("Reply[/pid]", text)
        self.assertNotIn("Post by", text)

    def test_author_watch_without_label_enriches_forum_author_name(self) -> None:
        raw = nga_feishu_watch.NgaPost(
            key="872882235",
            subject="\u81ea\u7acb\u81ea\u5f3a",
            content="\u539f\u59cb\u7528\u6237\u9875\u56de\u590d",
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=872882235",
            post_time="2026-06-25 14:06:20",
            author="150058",
            author_id="150058",
        )
        enriched = nga_feishu_watch.NgaPost(
            key="872882235",
            subject="\u81ea\u7acb\u81ea\u5f3a",
            content="\u5e16\u5b50\u9875\u56de\u590d",
            url=raw.url,
            post_time=raw.post_time,
            author="-\u963f\u72fc-",
            author_id="150058",
            floor="3448",
        )

        with patch.object(nga_feishu_watch, "collect_thread_tail_with_retries", return_value=[enriched]) as collect_thread:
            posts = nga_feishu_watch.enrich_author_posts_from_threads(Namespace(), [raw], "150058")

        collect_thread.assert_called_once_with(ANY, "45974302", 20, "150058")
        sourced = nga_feishu_watch.add_post_source(posts[0], "author", nga_feishu_watch.WatchTarget("150058", ""))

        self.assertEqual(posts[0].author, "-\u963f\u72fc-")
        self.assertEqual(posts[0].floor, "3448")
        self.assertEqual(
            nga_feishu_watch.new_reply_title(sourced),
            "\u3010-\u963f\u72fc-\u3011\u5728\u3010\u81ea\u7acb\u81ea\u5f3a\u3011\u65b0\u56de\u590d",
        )


if __name__ == "__main__":
    unittest.main()
