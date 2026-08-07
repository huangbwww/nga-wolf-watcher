from __future__ import annotations

import json
import unittest
from argparse import Namespace
from unittest.mock import patch

import nga_feishu_watch
import nga_wolf_gui
import nga_wolf_webgui
import wxpusher_channel


class WxPusherChannelTests(unittest.TestCase):
    def test_build_payload_targets_uids_and_topics_as_markdown(self) -> None:
        config = wxpusher_channel.WxPusherConfig(
            app_token="AT_secret",
            uids="UID_one, UID_two",
            topic_ids="123,456",
        )

        payload = wxpusher_channel.build_message_payload(
            config,
            "NGA test",
            "# Title\n\nbody",
            url="https://bbs.nga.cn/read.php?tid=1",
        )

        self.assertEqual(payload["appToken"], "AT_secret")
        self.assertEqual(payload["contentType"], 3)
        self.assertEqual(payload["summary"], "NGA test")
        self.assertEqual(payload["uids"], ["UID_one", "UID_two"])
        self.assertEqual(payload["topicIds"], [123, 456])
        self.assertEqual(payload["url"], "https://bbs.nga.cn/read.php?tid=1")

    def test_build_simple_payload_targets_spts_as_markdown(self) -> None:
        config = wxpusher_channel.WxPusherConfig(spts="SPT_one, SPT_two")

        payload = wxpusher_channel.build_simple_message_payload(
            config,
            "NGA test",
            "# Title\n\nbody",
            url="https://bbs.nga.cn/read.php?tid=1",
        )

        self.assertEqual(payload["contentType"], 3)
        self.assertEqual(payload["summary"], "NGA test")
        self.assertEqual(payload["sptList"], ["SPT_one", "SPT_two"])
        self.assertEqual(payload["url"], "https://bbs.nga.cn/read.php?tid=1")

    def test_send_message_uses_simple_push_and_redacts_spt(self) -> None:
        config = wxpusher_channel.WxPusherConfig(spts="SPT_secret")

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({"code": 1001, "msg": "bad token SPT_secret", "success": False}).encode("utf-8")

        captured = {}

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse()

        with patch("wxpusher_channel.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(wxpusher_channel.WxPusherChannelError) as caught:
                wxpusher_channel.send_message(config, "NGA test", "body")

        self.assertEqual(captured["url"], wxpusher_channel.WXPUSHER_SIMPLE_API)
        self.assertEqual(captured["payload"]["sptList"], ["SPT_secret"])
        message = str(caught.exception)
        self.assertIn("***", message)
        self.assertNotIn("SPT_secret", message)

    def test_send_message_raises_redacted_error_for_failed_response(self) -> None:
        config = wxpusher_channel.WxPusherConfig(app_token="AT_secret", uids="UID_one")

        class FakeResponse:
            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, exc_type, exc, tb) -> None:
                return None

            def read(self) -> bytes:
                return json.dumps({"code": 1001, "msg": "bad token AT_secret", "success": False}).encode("utf-8")

        with patch("wxpusher_channel.urlopen", return_value=FakeResponse()):
            with self.assertRaises(wxpusher_channel.WxPusherChannelError) as caught:
                wxpusher_channel.send_message(config, "NGA test", "body")

        message = str(caught.exception)
        self.assertIn("***", message)
        self.assertNotIn("AT_secret", message)

    def test_parse_profile_target_and_scope_args(self) -> None:
        profiles = nga_feishu_watch.parse_wxpusher_profiles(
            '[{"id":"wxp","app_token":"AT_secret","uids":"UID_default","topic_ids":"123"}]'
        )
        targets = nga_feishu_watch.parse_push_targets(
            '[{"id":"wxp-target","channel":"wxpusher","profile_id":"wxp","receive_id":"UID_one","id_type":"uid"}]'
        )
        base = Namespace(
            wxpusher_profiles='[{"id":"wxp","app_token":"AT_secret","uids":"UID_default","topic_ids":"123"}]',
            wxpusher_app_token="",
            wxpusher_uids="",
            wxpusher_topic_ids="",
            wxpusher_content_type="markdown",
            default_author_id="150058",
            default_tid="45974302",
        )

        scoped = nga_feishu_watch.args_for_push_target(base, targets[0])

        self.assertEqual(profiles[0].app_token, "AT_secret")
        self.assertEqual(targets[0].channel, "wxpusher")
        self.assertEqual(targets[0].id_type, "uid")
        self.assertEqual(scoped.bot_channel, "wxpusher")
        self.assertEqual(scoped.wxpusher_app_token, "AT_secret")
        self.assertEqual(scoped.wxpusher_uids, "UID_one")
        self.assertEqual(scoped.wxpusher_topic_ids, "123")

    def test_wxpusher_spt_profile_creates_default_target_without_receive_id(self) -> None:
        args = Namespace(
            wxpusher_profiles='[{"id":"wxp","spts":"SPT_secret"}]',
            wxpusher_spts="",
            wxpusher_app_token="",
            wxpusher_uids="",
            wxpusher_topic_ids="",
            wxpusher_content_type="markdown",
            bot_channel="wxpusher",
            default_author_id="150058",
            default_tid="45974302",
            push_targets="",
        )

        profiles = nga_feishu_watch.parse_wxpusher_profiles(args.wxpusher_profiles)
        targets = nga_feishu_watch.configured_push_targets(args)
        scoped = nga_feishu_watch.args_for_push_target(args, targets[0])

        self.assertEqual(profiles[0].spts, "SPT_secret")
        self.assertEqual(targets[0].id_type, "spt")
        self.assertEqual(targets[0].receive_id, "")
        self.assertEqual(scoped.wxpusher_spts, "SPT_secret")
        self.assertEqual(scoped.wxpusher_app_token, "")

    def test_legacy_route_topic_ids_select_topic_target_type(self) -> None:
        targets = nga_feishu_watch.parse_target_list(
            "150058=wolf|channel=wxpusher|wxpusher_topic_ids=123|profile=wxp",
            "",
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].route_channel, "wxpusher")
        self.assertEqual(targets[0].route_profile_id, "wxp")
        self.assertEqual(targets[0].route_receive_id, "123")
        self.assertEqual(targets[0].route_id_type, "topic_id")

    def test_structured_target_topic_ids_select_topic_target_type(self) -> None:
        targets = nga_feishu_watch.parse_push_targets(
            '[{"id":"wxp-topic","channel":"wxpusher","profile_id":"wxp","wxpusher_topic_ids":"123"}]'
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].channel, "wxpusher")
        self.assertEqual(targets[0].receive_id, "123")
        self.assertEqual(targets[0].id_type, "topic_id")

    def test_gui_load_push_targets_normalizes_wxpusher_topic_target(self) -> None:
        targets = nga_wolf_gui.load_push_targets(
            {
                "push_targets": '[{"id":"wxp-topic","channel":"wxpusher","profile_id":"wxp","wxpusher_topic_ids":"123"}]'
            },
            [],
            [],
            [],
            [],
            [{"id": "wxp", "app_token": "AT_secret"}],
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["receive_id"], "123")
        self.assertEqual(targets[0]["id_type"], "topic_id")

    def test_wxpusher_profiles_do_not_create_command_channel(self) -> None:
        args = Namespace(
            feishu_bot_profiles="[]",
            wechat_bot_profiles="[]",
            dingtalk_bot_profiles="[]",
            email_smtp_profiles="[]",
            wxpusher_profiles='[{"id":"wxp","app_token":"AT_secret","uids":"UID_one"}]',
            push_targets="",
            listen_rules="",
        )

        self.assertEqual(nga_feishu_watch.command_channel_args(args), [])

    def test_webgui_send_test_target_scopes_feishu_target(self) -> None:
        config = dict(nga_wolf_gui.DEFAULT_CONFIG)
        config.update(
            {
                "feishu_bot_profiles": '[{"id":"fs","app_id":"cli_a","app_secret":"sec"}]',
                "push_targets": '[{"id":"fs-target","channel":"feishu","profile_id":"fs","receive_id":"oc_chat","id_type":"chat_id"}]',
            }
        )
        api = nga_wolf_webgui.PreviewApi()

        with patch("nga_wolf_webgui.legacy.load_config", return_value=dict(nga_wolf_gui.DEFAULT_CONFIG)):
            with patch("nga_wolf_webgui.legacy.nga_feishu_watch.push_channel_posts") as pushed:
                result = api.send_test_target(config, "fs-target")

        self.assertTrue(result["ok"], result)
        scoped_args = pushed.call_args.args[0]
        self.assertEqual(scoped_args.bot_channel, "feishu")
        self.assertEqual(scoped_args.feishu_app_id, "cli_a")
        self.assertEqual(scoped_args.feishu_receive_id, "oc_chat")

    def test_webgui_send_test_target_allows_wxpusher_spt_target(self) -> None:
        config = dict(nga_wolf_gui.DEFAULT_CONFIG)
        config.update(
            {
                "bot_channel": "wxpusher",
                "wxpusher_profiles": '[{"id":"wx","spts":"SPT_secret"}]',
                "push_targets": '[{"id":"wx-target","channel":"wxpusher","profile_id":"wx","receive_id":"","id_type":"spt"}]',
            }
        )
        api = nga_wolf_webgui.PreviewApi()

        with patch("nga_wolf_webgui.legacy.load_config", return_value=dict(nga_wolf_gui.DEFAULT_CONFIG)):
            with patch("nga_wolf_webgui.legacy.nga_feishu_watch.push_channel_posts") as pushed:
                result = api.send_test_target(config, "wx-target")

        self.assertTrue(result["ok"], result)
        scoped_args = pushed.call_args.args[0]
        self.assertEqual(scoped_args.bot_channel, "wxpusher")
        self.assertEqual(scoped_args.wxpusher_spts, "SPT_secret")
        self.assertEqual(scoped_args.wxpusher_uids, "")

    def test_webgui_send_test_target_allows_legacy_wxpusher_target_without_id_type(self) -> None:
        config = dict(nga_wolf_gui.DEFAULT_CONFIG)
        config.update(
            {
                "bot_channel": "wxpusher",
                "wxpusher_profiles": '[{"id":"wxpusher_mq98aqx0_aokvi","spts":"SPT_secret"}]',
                "push_targets": '[{"id":"wxpusher_mq98aqx0_aokvi","channel":"wxpusher","profile_id":"wxpusher_mq98aqx0_aokvi","receive_id":""}]',
            }
        )
        api = nga_wolf_webgui.PreviewApi()

        with patch("nga_wolf_webgui.legacy.load_config", return_value=dict(nga_wolf_gui.DEFAULT_CONFIG)):
            with patch("nga_wolf_webgui.legacy.nga_feishu_watch.push_channel_posts") as pushed:
                result = api.send_test_target(config, "wxpusher_mq98aqx0_aokvi")

        self.assertTrue(result["ok"], result)
        scoped_args = pushed.call_args.args[0]
        self.assertEqual(scoped_args.bot_channel, "wxpusher")
        self.assertEqual(scoped_args.wxpusher_spts, "SPT_secret")
        self.assertEqual(scoped_args.wxpusher_uids, "")

    def test_wxpusher_markdown_uses_compact_title(self) -> None:
        content = nga_feishu_watch.wxpusher_markdown("狼大最近 2 条回复", "body")

        self.assertTrue(content.startswith("**狼大最近 2 条回复**\n\n"))
        self.assertNotIn("# 狼大最近", content)

    def test_wxpusher_posts_markdown_uses_stable_numbering_and_compact_reply_label(self) -> None:
        posts = [
            nga_feishu_watch.NgaPost(
                key="p1",
                subject="自立自强，科学技术打头阵",
                content="[pid=1,1,1]Reply[/pid] Post by user (2026-06-11 16:31):\n# quoted heading\n[/quote]\n# reply heading\n1. reply list",
                url="https://bbs.nga.cn/read.php?tid=1&pid=1",
                post_time="2026-06-11 16:50:06",
                author="150058",
            ),
            nga_feishu_watch.NgaPost(
                key="p2",
                subject="自立自强，科学技术打头阵",
                content="plain reply",
                url="https://bbs.nga.cn/read.php?tid=1&pid=2",
                post_time="2026-06-11 16:38:52",
                author="150058",
            ),
        ]

        markdown = nga_feishu_watch.wxpusher_posts_markdown(posts)

        self.assertIn("**第 1 条：自立自强，科学技术打头阵**", markdown)
        self.assertIn("**第 2 条：自立自强，科学技术打头阵**", markdown)
        self.assertNotIn("\n1. 自立自强", markdown)
        self.assertIn("\u3010user\u3011\u88ab\u56de\u590d\u5185\u5bb9\uff1a", markdown)
        self.assertIn("\u3010150058\u3011\u56de\u590d\u5185\u5bb9\uff1a", markdown)
        self.assertNotIn('style="color:#d93025;font-weight:700;"', markdown)
        self.assertIn("\\# reply heading", markdown)
        self.assertIn("1\\. reply list", markdown)

    def test_new_reply_title_uses_author_name_when_source_has_no_label(self) -> None:
        post = nga_feishu_watch.NgaPost(
            key="p1",
            subject="\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635",
            content="plain reply",
            url="https://bbs.nga.cn/read.php?tid=1&pid=1",
            post_time="2026-06-11 16:50:06",
            author="\u72fc\u5927",
            author_id="150058",
            source_type="author",
            source_id="150058",
        )

        self.assertEqual(
            nga_feishu_watch.new_reply_title(post),
            "\u3010\u72fc\u5927\u3011\u5728\u3010\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635\u3011\u65b0\u56de\u590d",
        )

    def test_new_reply_title_keeps_configured_source_label_first(self) -> None:
        post = nga_feishu_watch.NgaPost(
            key="p1",
            subject="\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635",
            content="plain reply",
            url="https://bbs.nga.cn/read.php?tid=1&pid=1",
            post_time="2026-06-11 16:50:06",
            author="\u72fc\u5927",
            author_id="150058",
            source_type="author",
            source_id="150058",
            source_label="\u91cd\u70b9\u7528\u6237",
        )

        self.assertEqual(
            nga_feishu_watch.new_reply_title(post),
            "\u3010\u91cd\u70b9\u7528\u6237\u3011\u5728\u3010\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635\u3011\u65b0\u56de\u590d",
        )

    def test_new_reply_title_uses_thread_label_before_subject(self) -> None:
        post = nga_feishu_watch.NgaPost(
            key="p1",
            subject="\u81ea\u7acb\u81ea\u5f3a\uff0c\u79d1\u5b66\u6280\u672f\u6253\u5934\u9635",
            content="plain reply",
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=1",
            post_time="2026-06-11 16:50:06",
            author="150058",
            author_id="150058",
            source_type="thread_author",
            source_id="45974302:150058",
            source_label="\u72fc\u5927",
            thread_id="45974302",
            thread_label="\u4e3b\u8d34\u5907\u6ce8",
        )

        self.assertEqual(
            nga_feishu_watch.new_reply_title(post),
            "\u3010\u72fc\u5927\u3011\u5728\u3010\u4e3b\u8d34\u5907\u6ce8\u3011\u65b0\u56de\u590d",
        )

    def test_push_channel_posts_uses_wxpusher_markdown_formatter(self) -> None:
        args = Namespace(
            bot_channel="wxpusher",
            wxpusher_spts="SPT_secret",
            wxpusher_app_token="",
            wxpusher_uids="",
            wxpusher_topic_ids="",
            wxpusher_content_type="markdown",
            timeout=20,
        )
        posts = [
            nga_feishu_watch.NgaPost(
                key="p1",
                subject="自立自强，科学技术打头阵",
                content="plain reply",
                url="https://bbs.nga.cn/read.php?tid=1&pid=1",
                post_time="2026-06-11 16:50:06",
                author="150058",
            )
        ]
        captured = {}

        def fake_send_message(config, title, content, *, url=""):
            captured["title"] = title
            captured["content"] = content
            captured["url"] = url
            return {"success": True, "code": 1000}

        with patch("wxpusher_channel.send_message", side_effect=fake_send_message):
            nga_feishu_watch.push_channel_posts(args, posts, "狼大最近 1 条回复")

        self.assertEqual(captured["title"], "狼大最近 1 条回复")
        self.assertIn("**第 1 条：自立自强，科学技术打头阵**", captured["content"])
        self.assertIn("\u3010150058\u3011\u56de\u590d\u5185\u5bb9\uff1a", captured["content"])
        self.assertNotIn("Generated at:", captured["content"])
        self.assertNotIn("\n1. 自立自强", captured["content"])


if __name__ == "__main__":
    unittest.main()
