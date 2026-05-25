from __future__ import annotations

import unittest
from argparse import Namespace

import email_channel
import nga_feishu_watch


class EmailChannelTests(unittest.TestCase):
    def test_build_email_message_with_attachment(self) -> None:
        config = email_channel.EmailSmtpConfig(
            username="sender@gmail.com",
            password="abcd efgh ijkl mnop",
            from_email="sender@gmail.com",
            from_name="NGA Wolf Watcher",
        )

        message = email_channel.build_email_message(
            config,
            "receiver@gmail.com",
            "NGA test",
            "body text",
            attachments=(
                email_channel.EmailAttachment(
                    file_name="result.txt",
                    content="full result".encode("utf-8"),
                    mime_type="text/plain",
                ),
            ),
        )

        self.assertEqual(message["To"], "receiver@gmail.com")
        self.assertEqual(message["Subject"], "NGA test")
        self.assertTrue(message.is_multipart())
        self.assertIn("result.txt", str(message))

    def test_redact_secret_removes_spaced_and_compact_password(self) -> None:
        text = email_channel.redact_secret(
            "failed for abcd efgh ijkl mnop / abcdefghijklmnop",
            ["abcd efgh ijkl mnop"],
        )

        self.assertNotIn("abcd efgh ijkl mnop", text)
        self.assertNotIn("abcdefghijklmnop", text)
        self.assertIn("***", text)

    def test_parse_email_profile_and_target(self) -> None:
        profiles = nga_feishu_watch.parse_email_smtp_profiles(
            '[{"id":"gmail","username":"sender@gmail.com","password":"app-password"}]'
        )
        targets = nga_feishu_watch.parse_push_targets(
            '[{"id":"mail","channel":"email","profile_id":"gmail","receive_id":"receiver@gmail.com"}]'
        )

        self.assertEqual(profiles[0].smtp_host, "smtp.gmail.com")
        self.assertEqual(profiles[0].smtp_security, "starttls")
        self.assertEqual(targets[0].channel, "email")
        self.assertEqual(targets[0].id_type, "email")

    def test_email_profiles_do_not_create_command_channel(self) -> None:
        args = Namespace(
            feishu_bot_profiles="[]",
            wechat_bot_profiles="[]",
            email_smtp_profiles='[{"id":"gmail","username":"sender@gmail.com","password":"app-password"}]',
        )

        self.assertEqual(nga_feishu_watch.command_channel_args(args), [])


if __name__ == "__main__":
    unittest.main()
