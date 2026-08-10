from __future__ import annotations

import unittest
from argparse import Namespace
from unittest.mock import patch

import nga_feishu_watch


class AuthorEnrichmentRetryTests(unittest.TestCase):
    def args(self, retries: int = 3) -> Namespace:
        return Namespace(
            cookie="cookie",
            timeout=10,
            retries=retries,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
        )

    def raw_author_post(self) -> nga_feishu_watch.NgaPost:
        return nga_feishu_watch.NgaPost(
            key="872882235",
            subject="自立自强",
            content="用户主页回复",
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=872882235",
            post_time="2026-06-25 14:06:20",
            author="150058",
            author_id="150058",
        )

    @staticmethod
    def closed_board(*_args: object, **_kwargs: object) -> None:
        raise nga_feishu_watch.NgaTemporaryUnavailable(
            "NGA 在 帖子 45974302 作者 150058 第 e 页 返回错误：2048:版面关闭",
            status_code=2048,
        )

    def test_author_name_enrichment_stops_after_first_closed_board_response(self) -> None:
        raw = self.raw_author_post()

        with patch.object(nga_feishu_watch, "fetch_nga_thread_page", side_effect=self.closed_board) as fetch, patch.object(
            nga_feishu_watch.time, "sleep"
        ) as sleep:
            posts = nga_feishu_watch.enrich_author_posts_from_threads(self.args(retries=20), [raw], "150058")

        self.assertEqual(posts, [raw])
        self.assertEqual(fetch.call_count, 1)
        sleep.assert_not_called()

    def test_normal_thread_fetch_still_retries_closed_board_response(self) -> None:
        with patch.object(nga_feishu_watch, "fetch_nga_thread_page", side_effect=self.closed_board) as fetch, patch.object(
            nga_feishu_watch.time, "sleep"
        ) as sleep:
            with self.assertRaises(nga_feishu_watch.NgaTemporaryUnavailable):
                nga_feishu_watch.collect_thread_tail_with_retries(self.args(retries=3), "45974302", 20, "150058")

        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
