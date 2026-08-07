from __future__ import annotations

import unittest
import time
import urllib.parse
from argparse import Namespace
from unittest.mock import patch

import nga_feishu_watch


def thread_payload(tid: str, author_id: str, pid: str) -> dict:
    return {
        "data": {
            "__PAGE": 1,
            "__ROWS": 1,
            "__R__ROWS_PAGE": 20,
            "__T": {"subject": "主贴"},
            "__U": {author_id: {"username": f"user-{author_id}"}},
            "__R": {
                pid: {
                    "tid": tid,
                    "pid": pid,
                    "authorid": author_id,
                    "postdate": "2026-06-08 10:00:00",
                    "content": f"reply from {author_id}",
                }
            },
        }
    }


def thread_payload_at(tid: str, author_id: str, pid: str, postdate: str) -> dict:
    payload = thread_payload(tid, author_id, pid)
    payload["data"]["__R"][pid]["postdate"] = postdate
    return payload


class Issue18ThreadWatchTests(unittest.TestCase):
    def test_fetch_thread_page_can_request_author_filtered_url(self) -> None:
        payload = thread_payload("45974302", "150058", "p1")
        with patch.object(nga_feishu_watch, "fetch_nga_json", return_value=payload) as fetch_json:
            result = nga_feishu_watch.fetch_nga_thread_page("45974302", 2, "cookie", 10, 0, 0, "150058")

        self.assertIs(result, payload)
        called_url = fetch_json.call_args.args[0]
        referer = fetch_json.call_args.args[6]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(called_url).query)
        referer_query = urllib.parse.parse_qs(urllib.parse.urlparse(referer).query)
        self.assertEqual(query["tid"], ["45974302"])
        self.assertEqual(query["page"], ["2"])
        self.assertEqual(query["authorid"], ["150058"])
        self.assertEqual(referer_query["authorid"], ["150058"])

    def test_thread_author_watch_fetches_each_author_filtered_thread(self) -> None:
        requested_author_ids: list[str] = []

        def fake_fetch(url: str, *_args, **_kwargs) -> dict:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            author_id = query.get("authorid", [""])[0]
            requested_author_ids.append(author_id)
            return thread_payload(query["tid"][0], author_id, f"pid-{author_id}")

        args = Namespace(
            cookie="cookie",
            timeout=10,
            retries=1,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
            thread_watch_tail_count=20,
            nga_target_min_delay=0,
            nga_target_max_delay=0,
        )
        watches = [
            nga_feishu_watch.ThreadAuthorWatch("45974302", "150058", "wolf"),
            nga_feishu_watch.ThreadAuthorWatch("45974302", "123456", "other"),
        ]

        with patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch):
            posts, counts = nga_feishu_watch.collect_thread_author_watch_posts(args, watches)

        self.assertEqual(requested_author_ids, ["150058", "123456"])
        self.assertEqual([post.author_id for post in posts], ["150058", "123456"])
        self.assertEqual(counts, [("wolf(45974302:150058)", 1), ("other(45974302:123456)", 1)])

    def test_thread_author_tail_uses_author_filtered_end_page_directly(self) -> None:
        requested: list[tuple[str, str]] = []

        def fake_fetch(url: str, *_args, **_kwargs) -> dict:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            page = query["page"][0]
            author_id = query.get("authorid", [""])[0]
            requested.append((page, author_id))
            self.assertEqual(author_id, "150058")
            if page == "2":
                raise AssertionError("author-filtered scan should not trust a truncated HTML page count")
            if page == "e":
                payload = thread_payload(query["tid"][0], author_id, "pid-latest")
                payload["data"]["__PAGE"] = 3
                payload["data"]["__ROWS"] = 60
                payload["data"]["__R__ROWS_PAGE"] = 20
                return payload
            payload = thread_payload(query["tid"][0], author_id, "pid-initial")
            payload["data"]["__ROWS"] = 60
            payload["data"]["__R__ROWS_PAGE"] = 20
            return payload

        args = Namespace(
            cookie="cookie",
            timeout=10,
            retries=1,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
            thread_watch_tail_count=1,
            nga_target_min_delay=0,
            nga_target_max_delay=0,
        )

        with patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch):
            posts, counts = nga_feishu_watch.collect_thread_author_watch_posts(
                args,
                [nga_feishu_watch.ThreadAuthorWatch("45974302", "150058", "wolf")],
            )

        self.assertEqual(requested, [("e", "150058")])
        self.assertEqual([post.canonical_key for post in posts], ["pid-latest"])
        self.assertEqual(counts, [("wolf(45974302:150058)", 1)])

    def test_thread_author_tail_does_not_use_main_thread_last_page_for_multiple_threads_same_author(self) -> None:
        requested: list[tuple[str, str, str]] = []

        def fake_fetch(url: str, *_args, **_kwargs) -> dict:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            tid = query["tid"][0]
            page = query["page"][0]
            author_id = query.get("authorid", [""])[0]
            requested.append((tid, page, author_id))
            if not author_id:
                raise AssertionError("thread-author scan should always use the author-filtered URL")
            if page == "1188":
                raise AssertionError("author-filtered scan should not request the main thread last page")
            if page == "2":
                raise AssertionError("author-filtered scan should not trust a truncated HTML page count")
            return thread_payload(tid, author_id, f"pid-{tid}")

        args = Namespace(
            cookie="cookie",
            timeout=10,
            retries=1,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
            thread_watch_tail_count=1,
            nga_target_min_delay=0,
            nga_target_max_delay=0,
        )

        watches = [
            nga_feishu_watch.ThreadAuthorWatch("40795363", "150058", "wolf-a"),
            nga_feishu_watch.ThreadAuthorWatch("45974302", "150058", "wolf-b"),
        ]

        with patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch):
            posts, counts = nga_feishu_watch.collect_thread_author_watch_posts(args, watches)

        self.assertEqual(requested, [("40795363", "e", "150058"), ("45974302", "e", "150058")])
        self.assertEqual([post.canonical_key for post in posts], ["pid-40795363", "pid-45974302"])
        self.assertEqual(counts, [("wolf-a(40795363:150058)", 1), ("wolf-b(45974302:150058)", 1)])

    def test_thread_author_tail_does_not_walk_back_from_html_fallback_page_count(self) -> None:
        requested: list[str] = []

        def fake_fetch(tid: str, page: int | str, *_args, **_kwargs) -> dict:
            requested.append(str(page))
            if str(page) != "e":
                raise AssertionError("HTML fallback page count is inferred and must not drive backfill pages")
            payload = thread_payload(tid, "150058", "pid-latest")
            payload["data"]["__PAGE"] = 1
            payload["data"]["__ROWS"] = 40
            payload["data"]["__R__ROWS_PAGE"] = 20
            payload["data"]["__HTML_FALLBACK"] = True
            return payload

        with patch.object(nga_feishu_watch, "fetch_nga_thread_page", side_effect=fake_fetch):
            posts = nga_feishu_watch.collect_thread_tail(
                "45974302",
                20,
                "cookie",
                10,
                attempts=1,
                retry_initial_delay=0,
                retry_delay=0,
                page_delay=0,
                request_min_interval=0,
                cache_ttl=0,
                allow_partial=True,
                author_id="150058",
            )

        self.assertEqual(requested, ["e"])
        self.assertEqual([post.canonical_key for post in posts], ["pid-latest"])

    def test_thread_author_watch_skips_missing_author_thread_without_blocking_other_threads(self) -> None:
        requested: list[tuple[str, str, str]] = []

        def fake_fetch(url: str, *_args, **_kwargs) -> dict:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            tid = query["tid"][0]
            page = query["page"][0]
            author_id = query.get("authorid", [""])[0]
            requested.append((tid, page, author_id))
            if tid == "40795363":
                raise RuntimeError("NGA 在 帖子 40795363 作者 150058 最新页 返回错误：2048:找不到内容 或 没有更多页了")
            return thread_payload(tid, author_id, f"pid-{tid}")

        args = Namespace(
            cookie="cookie",
            timeout=10,
            retries=1,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
            thread_watch_tail_count=1,
            nga_target_min_delay=0,
            nga_target_max_delay=0,
        )

        watches = [
            nga_feishu_watch.ThreadAuthorWatch("40795363", "150058", "wolf-a"),
            nga_feishu_watch.ThreadAuthorWatch("45974302", "150058", "wolf-b"),
        ]

        with patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch):
            posts, counts = nga_feishu_watch.collect_thread_author_watch_posts(args, watches)

        self.assertEqual(requested, [("40795363", "e", "150058"), ("45974302", "e", "150058")])
        self.assertEqual([post.canonical_key for post in posts], ["pid-45974302"])
        self.assertEqual(counts, [("wolf-a(40795363:150058)", 0), ("wolf-b(45974302:150058)", 1)])

    def test_thread_author_day_pack_uses_author_filtered_end_page_directly(self) -> None:
        requested: list[tuple[str, str]] = []
        today = time.strftime("%Y-%m-%d 10:00:00", time.localtime())
        old_day = time.strftime("%Y-%m-%d 10:00:00", time.localtime(time.time() - 14 * 86400))

        def fake_fetch(url: str, *_args, **_kwargs) -> dict:
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            page = query["page"][0]
            author_id = query.get("authorid", [""])[0]
            requested.append((page, author_id))
            self.assertEqual(author_id, "150058")
            if page == "e":
                payload = thread_payload_at(query["tid"][0], author_id, "pid-latest", today)
                payload["data"]["__PAGE"] = 3
                payload["data"]["__ROWS"] = 60
                payload["data"]["__R__ROWS_PAGE"] = 20
                return payload
            payload = thread_payload_at(query["tid"][0], author_id, f"pid-old-{page}", old_day)
            payload["data"]["__ROWS"] = 60
            payload["data"]["__R__ROWS_PAGE"] = 20
            return payload

        args = Namespace(
            cookie="cookie",
            timeout=10,
            retries=1,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
        )

        with patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch):
            posts = nga_feishu_watch.collect_thread_in_days_with_retries(args, "45974302", 1, "150058")

        self.assertEqual(requested, [("e", "150058"), ("2", "150058")])
        self.assertEqual([post.key for post in posts], ["pid-latest"])

    def test_startup_catchup_uses_author_filtered_thread_url(self) -> None:
        requested_urls: list[str] = []

        def fake_fetch(url: str, *_args, **_kwargs) -> dict:
            requested_urls.append(url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            return thread_payload(query["tid"][0], query.get("authorid", ["150058"])[0], "pid-startup")

        args = Namespace(
            cookie="cookie",
            timeout=10,
            retries=1,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
            thread_watch_tail_count=20,
            nga_target_min_delay=0,
            nga_target_max_delay=0,
        )

        with patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch):
            posts, counts = nga_feishu_watch.collect_thread_author_startup_catchup_posts(
                args,
                [nga_feishu_watch.ThreadAuthorWatch("45974302", "150058", "wolf")],
            )

        content_query = urllib.parse.parse_qs(urllib.parse.urlparse(requested_urls[0]).query)
        self.assertEqual(content_query["tid"], ["45974302"])
        self.assertEqual(content_query["page"], ["e"])
        self.assertEqual(content_query["authorid"], ["150058"])
        self.assertEqual([post.author_id for post in posts], ["150058"])
        self.assertEqual(counts, [("wolf(45974302:150058) 启动补抓", 1)])

    def test_reply_command_aliases_can_include_optional_thread_scope(self) -> None:
        args = Namespace(
            default_author_id="150058",
            default_tid="45974302",
            watch_author_ids="150058=wolf",
            preset_thread_ids="45974302=main",
            listen_rules=(
                '[{"id":"r1","mode":"thread_author","tid":"45974302","author_id":"150058","label":"wolf","target_ids":[]},'
                '{"id":"r2","mode":"author","author_id":"47049660","label":"milk","target_ids":[]}]'
            ),
        )
        author_targets = nga_feishu_watch.command_author_targets(args)
        thread_targets = nga_feishu_watch.command_thread_targets(args)

        home_command = nga_feishu_watch.parse_bot_command(
            "/history_r u2 5",
            args.default_author_id,
            args.default_tid,
            author_targets,
            thread_targets,
        )
        scoped_command = nga_feishu_watch.parse_bot_command(
            "/history_r u2 t1 5",
            args.default_author_id,
            args.default_tid,
            author_targets,
            thread_targets,
        )
        raw_scoped_pack = nga_feishu_watch.parse_bot_command(
            "/pack_r 47049660 45974302 1d",
            args.default_author_id,
            args.default_tid,
            author_targets,
            thread_targets,
        )

        self.assertEqual([target.id for target in author_targets], ["150058", "47049660"])
        self.assertEqual([target.id for target in thread_targets], ["45974302"])
        self.assertEqual(home_command.target_id, "47049660")
        self.assertEqual(home_command.thread_id, "")
        self.assertEqual(home_command.count, 5)
        self.assertEqual(scoped_command.target_id, "47049660")
        self.assertEqual(scoped_command.thread_id, "45974302")
        self.assertEqual(raw_scoped_pack.target_id, "47049660")
        self.assertEqual(raw_scoped_pack.thread_id, "45974302")
        self.assertEqual(raw_scoped_pack.days, 1)

    def test_manual_reply_command_uses_user_home_unless_thread_id_is_explicit(self) -> None:
        requested_urls: list[str] = []

        def fake_fetch(url: str, *_args, **_kwargs) -> dict:
            requested_urls.append(url)
            query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
            if "tid" in query:
                return thread_payload(query["tid"][0], query.get("authorid", ["150058"])[0], "pid-thread")
            payload = thread_payload("40795363", query.get("authorid", ["150058"])[0], "pid-home")
            payload["data"]["__T"] = {
                "1": {
                    "tid": "40795363",
                    "subject": "user home topic",
                    "__P": payload["data"]["__R"]["pid-home"],
                }
            }
            return payload

        args = Namespace(
            cookie="cookie",
            timeout=10,
            retries=1,
            retry_initial_delay=0,
            retry_delay=0,
            nga_page_delay=0,
            nga_request_min_interval=0,
            nga_cache_ttl=0,
            thread_watch_tail_count=20,
            default_author_id="150058",
            default_tid="45974302",
            watch_author_ids="150058=wolf",
            preset_thread_ids="45974302=主贴",
            listen_rules='[{"id":"r1","mode":"thread_author","tid":"45974302","author_id":"150058","target_ids":[]}]',
            thread_author_watches="",
            push_targets="",
            bot_channel="feishu",
            message_format="text",
        )

        with (
            patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch),
            patch.object(nga_feishu_watch, "push_channel_posts") as push_posts,
        ):
            nga_feishu_watch.run_bot_command(
                args,
                nga_feishu_watch.BotCommand("history", "reply", "150058", count=5),
            )

        home_query = urllib.parse.parse_qs(urllib.parse.urlparse(requested_urls[0]).query)
        self.assertEqual(home_query["searchpost"], ["1"])
        self.assertEqual(home_query["authorid"], ["150058"])
        self.assertNotIn("tid", home_query)
        push_posts.assert_called_once()
        self.assertEqual(push_posts.call_args.args[1][0].key, "pid-home")

        requested_urls.clear()
        with (
            patch.object(nga_feishu_watch, "fetch_nga_json", side_effect=fake_fetch),
            patch.object(nga_feishu_watch, "push_channel_posts") as push_posts,
        ):
            nga_feishu_watch.run_bot_command(
                args,
                nga_feishu_watch.BotCommand("history", "reply", "150058", count=5, thread_id="45974302"),
            )

        thread_query = urllib.parse.parse_qs(urllib.parse.urlparse(requested_urls[0]).query)
        self.assertEqual(thread_query["tid"], ["45974302"])
        self.assertEqual(thread_query["page"], ["e"])
        self.assertEqual(thread_query["authorid"], ["150058"])
        push_posts.assert_called_once()
        self.assertEqual(push_posts.call_args.args[1][0].key, "pid-thread")

    def test_manual_reply_command_sorts_results_oldest_first(self) -> None:
        newer = nga_feishu_watch.NgaPost(
            key="newer",
            subject="topic",
            content="newer reply",
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=2",
            post_time="2026-06-27 10:00:00",
            author_id="150058",
        )
        older = nga_feishu_watch.NgaPost(
            key="older",
            subject="topic",
            content="older reply",
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=1",
            post_time="2026-06-27 09:00:00",
            author_id="150058",
        )
        args = Namespace(
            default_author_id="150058",
            default_tid="45974302",
            watch_author_ids="150058=wolf",
            preset_thread_ids="45974302=main",
            listen_rules="",
            thread_author_watches="",
            bot_channel="feishu",
            message_format="text",
        )

        with (
            patch.object(nga_feishu_watch, "collect_replies_with_retries", return_value=[newer, older]) as collect_home,
            patch.object(nga_feishu_watch, "push_channel_posts") as push_posts,
        ):
            nga_feishu_watch.run_bot_command(args, nga_feishu_watch.BotCommand("history", "reply", "150058", count=2))

        collect_home.assert_called_once()
        self.assertEqual([post.key for post in push_posts.call_args.args[1]], ["older", "newer"])

        with (
            patch.object(nga_feishu_watch, "collect_thread_tail_with_retries", return_value=[newer, older]) as collect_thread,
            patch.object(nga_feishu_watch, "push_channel_posts") as push_posts,
        ):
            nga_feishu_watch.run_bot_command(args, nga_feishu_watch.BotCommand("history", "reply", "150058", count=2, thread_id="45974302"))

        collect_thread.assert_called_once()
        self.assertEqual([post.key for post in push_posts.call_args.args[1]], ["older", "newer"])

    def test_thread_author_watch_inherits_author_and_thread_labels(self) -> None:
        args = Namespace(
            watch_mode="thread_author",
            default_author_id="",
            default_tid="",
            watch_author_ids="150058=\u72fc\u5927",
            preset_thread_ids="45974302=\u4e3b\u8d34\u5907\u6ce8",
            listen_rules='[{"id":"r1","mode":"thread_author","tid":"45974302","author_id":"150058","target_ids":[]}]',
            thread_author_watches="",
        )

        watches = nga_feishu_watch.thread_author_watches_for_watch(args)

        self.assertEqual(len(watches), 1)
        self.assertEqual(watches[0].label, "\u72fc\u5927")
        self.assertEqual(watches[0].thread_label, "\u4e3b\u8d34\u5907\u6ce8")


if __name__ == "__main__":
    unittest.main()
