from __future__ import annotations

import unittest
import tempfile
from argparse import Namespace
from unittest.mock import patch

import dingtalk_bot
import nga_feishu_watch


class DingTalkChannelTests(unittest.TestCase):
    def test_parse_stream_text_message(self) -> None:
        message = dingtalk_bot.parse_stream_message(
            {
                "msgId": "msg-1",
                "conversationId": "conv-1",
                "senderStaffId": "user-1",
                "text": {"content": "  /start  "},
                "sessionWebhook": "https://example.invalid/webhook",
            }
        )

        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message.message_id, "msg-1")
        self.assertEqual(message.conversation_id, "conv-1")
        self.assertEqual(message.sender_id, "user-1")
        self.assertEqual(message.text, "/start")
        self.assertEqual(message.session_webhook, "https://example.invalid/webhook")

    def test_parse_stream_markdown_message(self) -> None:
        message = dingtalk_bot.parse_stream_message(
            {
                "messageId": "msg-2",
                "senderId": "user-2",
                "content": {"markdown": {"title": "NGA", "text": "## Title\n\nbody"}},
            }
        )

        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message.message_id, "msg-2")
        self.assertEqual(message.sender_id, "user-2")
        self.assertIn("Title", message.text)
        self.assertIn("body", message.text)

    def test_parse_card_action_callback(self) -> None:
        action = dingtalk_bot.parse_card_action(
            {
                "userId": "user-1",
                "outTrackId": "card-1",
                "content": '{"cardPrivateData":"{\\"params\\":{\\"action\\":\\"command\\",\\"command\\":\\"/setting\\"}}"}',
            },
            "callback-1",
        )

        self.assertIsNotNone(action)
        assert action is not None
        self.assertEqual(action.message_id, "callback-1")
        self.assertEqual(action.user_id, "user-1")
        self.assertEqual(action.card_instance_id, "card-1")
        self.assertEqual(action.action, "command")
        self.assertEqual(action.command, "/setting")

    def test_allowed_users_empty_means_all(self) -> None:
        self.assertTrue(dingtalk_bot.is_allowed("", "user-1"))
        self.assertTrue(dingtalk_bot.is_allowed("user-1,user-2", "user-2"))
        self.assertFalse(dingtalk_bot.is_allowed("user-1,user-2", "user-3"))

    def test_parse_profiles_and_push_targets(self) -> None:
        profiles = nga_feishu_watch.parse_dingtalk_bot_profiles(
            '[{"id":"dt","client_id":"cid","client_secret":"secret","robot_code":"robot","target_user_ids":"u1,u2"}]'
        )
        targets = nga_feishu_watch.parse_push_targets(
            '[{"id":"dt-target","channel":"dingtalk","profile_id":"dt","target_user_ids":"u1,u2"}]'
        )

        self.assertEqual(profiles[0].id, "dt")
        self.assertEqual(profiles[0].client_id, "cid")
        self.assertEqual(profiles[0].robot_code, "robot")
        self.assertEqual(targets[0].channel, "dingtalk")
        self.assertEqual(targets[0].id_type, "user_id")
        self.assertEqual(targets[0].receive_id, "u1,u2")

    def test_legacy_dingtalk_args_create_command_channel(self) -> None:
        args = Namespace(
            dingtalk_bot_profiles="",
            dingtalk_client_id="cid",
            dingtalk_client_secret="secret",
            dingtalk_robot_code="robot",
            dingtalk_target_user_ids="user-1",
            dingtalk_allowed_user_ids="",
            dingtalk_account_id="default",
            dingtalk_state_dir="",
            push_targets="",
            listen_rules="",
        )

        channels = nga_feishu_watch.command_channel_args(args)

        self.assertEqual(len(channels), 1)
        self.assertEqual(channels[0].bot_channel, "dingtalk")
        self.assertTrue(channels[0].ws_no_watch)
        self.assertEqual(channels[0].dingtalk_client_id, "cid")
        self.assertEqual(channels[0].dingtalk_target_user_ids, "user-1")

    def test_unreferenced_dingtalk_profile_does_not_start_in_structured_routes(self) -> None:
        args = Namespace(
            bot_channel="feishu",
            feishu_bot_profiles='[{"id":"fs","app_id":"app","app_secret":"secret","id_type":"chat_id"}]',
            wechat_bot_profiles="",
            dingtalk_bot_profiles='[{"id":"dt","client_id":"cid","client_secret":"secret","target_user_ids":"u1"}]',
            push_targets='[{"id":"fs-target","channel":"feishu","profile_id":"fs","receive_id":"oc_xxx"}]',
            listen_rules='[{"id":"r","mode":"thread_author","tid":"45974302","author_id":"150058","target_ids":["fs-target"]}]',
            feishu_app_id="",
            feishu_app_secret="",
            feishu_receive_id="",
            feishu_id_type="chat_id",
            wechat_bot_token="",
            dingtalk_client_id="",
            dingtalk_client_secret="",
            dingtalk_robot_code="",
            dingtalk_target_user_ids="",
            dingtalk_allowed_user_ids="",
            dingtalk_account_id="default",
            dingtalk_state_dir="",
            email_profiles="",
        )

        channels = nga_feishu_watch.command_channel_args(args)

        self.assertEqual([channel.bot_channel for channel in channels], ["feishu"])

    def test_dingtalk_short_commands(self) -> None:
        args = Namespace(default_author_id="150058", default_tid="45974302")

        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "hr10"), "/history_r 150058 10")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "pr 20"), "/pack_r 150058 20")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "ht"), "/history_t 45974302 10")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "pt50"), "/pack_t 45974302 50")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "s"), "/setting")

    def test_dingtalk_current_target_state_and_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            args = Namespace(
                default_author_id="150058",
                default_tid="45974302",
                watch_author_ids="150058:狼大,123456:测试用户",
                preset_thread_ids="45974302:主贴,87021655:副贴",
                dingtalk_target_user_ids="sender-1",
                dingtalk_client_id="cid",
                dingtalk_client_secret="secret",
                dingtalk_robot_code="robot",
                dingtalk_allowed_user_ids="",
                dingtalk_account_id="state-test",
                dingtalk_state_dir=tmp,
            )

            self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "u2"), "/start")
            self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "t2"), "/start")
            self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "hr"), "/history_r 123456 5")
            self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "ht"), "/history_t 87021655 10")
            menu = nga_feishu_watch.dingtalk_start_markdown(args)
            self.assertIn("u2 测试用户", menu)
            self.assertIn("t2 副贴", menu)
            self.assertIn("当前", menu)

    def test_dingtalk_push_target_receive_matches_csv_member(self) -> None:
        args = Namespace(
            push_targets='[{"id":"dt","channel":"dingtalk","target_user_ids":"u1,u2","default_author_id":"123456"}]',
            feishu_app_id="",
            feishu_app_secret="",
            feishu_receive_id="",
            feishu_id_type="chat_id",
            feishu_bot_profiles="",
            wechat_bot_profiles="",
            dingtalk_bot_profiles="",
            email_profiles="",
        )

        target = nga_feishu_watch.push_target_for_channel_receive(args, "dingtalk", "u2")

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.id, "dt")
        self.assertEqual(target.default_author_id, "123456")

    def test_dingtalk_posts_markdown_cleans_nga_quote_header(self) -> None:
        post = nga_feishu_watch.NgaPost(
            key="1",
            subject="自立自强",
            content="[pid=870216155,45974302,6241]Reply[/pid] Post by stephanie1P (2026-06-01 14:31):\n狼大像半导体和PCB硬件这种暴跌的是不是得考虑下减仓保利润了\n\n反正半导体没调整完 我觉得就还有低",
            url="https://bbs.nga.cn/read.php?tid=45974302&pid=870216155",
            post_time="2026-06-01 14:34:18",
            author="150058",
        )

        markdown = nga_feishu_watch.dingtalk_posts_markdown([post], "NGA 用户 最新 1 条")

        self.assertIn("## NGA 用户 最新 1 条", markdown)
        self.assertIn("- 时间: 2026-06-01 14:34:18", markdown)
        self.assertIn("\u3010stephanie1P\u3011\u88ab\u56de\u590d\u5185\u5bb9\uff1a", markdown)
        self.assertIn("\u3010150058\u3011\u56de\u590d\u5185\u5bb9\uff1a", markdown)
        self.assertNotIn("[pid=", markdown)
        self.assertNotIn("Reply[/pid]", markdown)

    def test_dingtalk_ai_result_falls_back_when_status_update_fails(self) -> None:
        args = Namespace(bot_channel="dingtalk", dingtalk_ai_status_card_id="card-1")

        with (
            patch.object(nga_feishu_watch, "update_dingtalk_processing_card", return_value=False) as update,
            patch.object(nga_feishu_watch, "push_dingtalk_markdown_card") as send_card,
        ):
            nga_feishu_watch.push_ai_markdown(args, "AI 回复", "123")

        update.assert_called_once_with(args, "card-1", "AI 回复", "123")
        send_card.assert_called_once_with(args, "AI 回复", "123")
        self.assertTrue(getattr(args, "dingtalk_ai_result_sent"))

    def test_dingtalk_client_cache_keeps_reply_scope(self) -> None:
        base = Namespace(
            timeout=20,
            dingtalk_client_id="cid",
            dingtalk_client_secret="secret",
            dingtalk_robot_code="robot",
            dingtalk_target_user_ids="",
            dingtalk_allowed_user_ids="",
            dingtalk_account_id="test-cache",
            dingtalk_state_dir="",
            dingtalk_session_webhook="",
            dingtalk_bot_profiles="",
            push_targets="",
            feishu_app_id="",
            feishu_app_secret="",
            feishu_receive_id="",
            feishu_id_type="chat_id",
            feishu_bot_profiles="",
            wechat_bot_profiles="",
            email_profiles="",
            default_author_id="150058",
            default_tid="45974302",
        )

        nga_feishu_watch._DINGTALK_CLIENTS.clear()
        base_client = nga_feishu_watch.dingtalk_client_for_args(base)
        scoped = nga_feishu_watch.args_for_dingtalk_user(base, "sender-1", "https://example.invalid/session")
        scoped_client = nga_feishu_watch.dingtalk_client_for_args(scoped)

        self.assertIsNot(base_client, scoped_client)
        self.assertEqual(scoped_client.config.target_user_ids, "sender-1")
        self.assertEqual(scoped_client.config.session_webhook, "https://example.invalid/session")


if __name__ == "__main__":
    unittest.main()
