from __future__ import annotations

import unittest
from argparse import Namespace

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

    def test_dingtalk_short_commands(self) -> None:
        args = Namespace(default_author_id="150058", default_tid="45974302")

        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "hr10"), "/history_r 150058 10")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "pr 20"), "/pack_r 150058 20")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "ht"), "/history_t 45974302 10")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "pt50"), "/pack_t 45974302 50")
        self.assertEqual(nga_feishu_watch.dingtalk_normalize_short_command(args, "s"), "/setting")


if __name__ == "__main__":
    unittest.main()
