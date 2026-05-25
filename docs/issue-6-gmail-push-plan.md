# Issue 6: Email SMTP push channel implementation plan

Issue: https://github.com/huangbwww/nga-wolf-watcher/issues/6

## Goal

Add an optional email push channel without changing the default Feishu or WeChat behavior. The sending account is any mailbox that supports standard SMTP authentication; the recipient can be any email address, including Gmail.

The MVP should support standard SMTP with password/app-password/auth-code authentication. Gmail SMTP with App Password is one supported example. OAuth should stay out of the first implementation because it adds browser consent, token refresh, and secret persistence complexity that is not needed for the issue's acceptance path.

## Current Architecture Notes

- `nga_feishu_watch.py` already routes structured destinations through `PushTarget(channel, profile_id, receive_id, id_type)`.
- Feishu and WeChat profile parsing is separate from push target parsing: `parse_feishu_bot_profiles`, `parse_wechat_bot_profiles`, `configured_push_targets`, `route_args_for_post`, and `ai_schedule_recipient_args`.
- Sending already funnels through `push_channel_raw_text`, `push_channel_text`, `push_channel_file`, `push_channel_posts`, `push_ai_markdown`, and `push_ai_result`.
- The preview web UI serializes `feishu_bot_profiles`, `wechat_bot_profiles`, `push_targets`, `listen_rules`, and `ai_schedule_target_ids`.
- The classic GUI has parallel profile and target editors in `nga_wolf_gui.py`, so it needs matching support or at least a safe advanced-config path.

## Proposed MVP Design

### Configuration Model

Add an email profile list:

```json
[
  {
    "id": "email_xxx",
    "label": "Primary SMTP",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "smtp_security": "starttls",
    "username": "sender@gmail.com",
    "password": "<smtp password or app password>",
    "from_email": "sender@gmail.com",
    "from_name": "NGA Wolf Watcher",
    "reply_to": ""
  }
]
```

Add email targets to existing `push_targets`:

```json
{
  "id": "target_xxx",
  "label": "My inbox",
  "channel": "email",
  "profile_id": "email_xxx",
  "receive_id": "recipient@gmail.com",
  "id_type": "email"
}
```

Environment/CLI compatibility:

- `EMAIL_SMTP_PROFILES` for JSON profiles. `GMAIL_SMTP_PROFILES` can remain as a compatibility alias.
- `EMAIL_SMTP_HOST`, `EMAIL_SMTP_PORT`, `EMAIL_SMTP_SECURITY`, `EMAIL_USERNAME`, `EMAIL_PASSWORD`, `EMAIL_FROM`, `EMAIL_TO` as a legacy single-profile fallback.
- Expand `--bot-channel` choices to include `email`, but keep default `feishu`.
- Add `--email-smtp-profiles` and single-profile CLI flags.

### Sending Behavior

Create `email_channel.py` or extend `message_channels.py` with:

- `EmailProfile` dataclass.
- `send_email(profile, recipient, subject, text, html=None, attachments=())`.
- SMTP implementation using Python stdlib: `smtplib`, `email.message.EmailMessage`, and `ssl`.
- STARTTLS on port 587 as default; support SSL on 465 for completeness.
- Secret redaction helper for logs and exceptions.

Route email through the existing send facade:

- `push_channel_raw_text`: plain text email.
- `push_channel_text`: subject = title, body = text.
- `push_channel_file`: attach `.txt` file instead of sending local path text.
- `push_channel_posts`: subject = watcher title, body = `posts_to_txt` or a new email-friendly text formatter.
- `push_ai_markdown`: send Markdown as text/plain and optionally HTML later.
- `push_ai_result`: use existing title logic; long result can be attachment via `push_channel_file`.

MVP format:

- Always include `text/plain`.
- Optional basic HTML can be added in the same implementation if low-risk, but it should not block acceptance.
- Attach `.txt` for pack commands and AI results that exceed the existing long-result threshold.

### Routing Changes

Update `nga_feishu_watch.py`:

- Add `EmailSmtpProfile`.
- Add `parse_email_smtp_profiles`, `email_smtp_profiles`, and `find_email_profile`.
- Allow `normalize_channel` / `bot_channel` / `route_channel_value` equivalents to accept `email`.
- Update `configured_push_targets` fallback to create an email target when `bot_channel=email` and `EMAIL_TO` is present.
- Update `args_for_configured_route`, `ai_schedule_recipient_args`, `route_args_for_post`, and `channel_route_key`.
- Preserve Feishu/WeChat command receiving behavior; email is outbound-only for MVP.

### GUI Changes

Preview React UI:

- Add `emailProfiles` parsing and serialization beside Feishu/WeChat.
- Extend channel picker from two choices to three: Feishu, WeChat, Email.
- Add email profile editor fields: label, SMTP host, port, security, username, app password, from email/name.
- Add email target editor where `receive_id` is recipient email.
- Include email targets in listen rules and AI scheduled target selection.
- Update validation/error-channel routing to understand email.

Classic GUI:

- Add a minimal email profile section and allow email push targets in the existing target editor.
- If a full classic editor is too large, at minimum ensure loading/saving preserves `email_smtp_profiles` and email `push_targets`, and document that preview UI is the recommended setup path.

### Tests

Unit-style tests can be added with stdlib `unittest` and mocks without sending real mail:

- Parse email profiles from JSON and legacy env-style config.
- Parse email `push_targets` without breaking Feishu/WeChat targets.
- `args_for_configured_route` returns email credentials and recipient for an email target.
- `push_channel_*` dispatches to the email sender when `bot_channel=email`.
- Email message builder creates correct subject, text body, and `.txt` attachment.
- Secret redaction prevents app password from appearing in raised errors/log strings.

Manual verification:

- Configure an SMTP sender account and send a test email.
- Trigger one NGA new reply and verify email delivery.
- Enable quiet-hours defer mode and verify summary email delivery.
- Enable AI auto analysis and scheduled analysis and verify emails are sent to selected email targets.
- Confirm default config with no email profiles still starts Feishu/WeChat unchanged.

## Implementation Phases

1. Core email sender
   - Add email dataclasses, config parsing, SMTP send helper, and redaction.
   - Add tests around parsing and message construction.

2. Runtime routing
   - Wire `channel=email` into `PushTarget`, `bot_channel`, route cloning, send facades, test message, listen rules, and AI schedule recipients.
   - Verify Feishu/WeChat behavior remains unchanged.

3. UI support
   - Update preview web UI first because it already owns structured profiles and targets.
   - Add classic GUI compatibility or a minimal editor based on scope.

4. Documentation and packaging
   - Document SMTP setup, Gmail App Password caveat, security caveats, and environment variable examples in both READMEs.
   - Ensure PyInstaller specs need no extra dependency, since the MVP uses stdlib SMTP/email modules.

5. End-to-end validation
   - Run unit tests and web UI build.
   - Send a real test email only with user-provided credentials.

## Security Rules

- Never log `password`, `app_password`, OAuth tokens, SMTP auth strings, or full JSON profile blobs.
- Store credentials only in the existing local config path unless/until a keyring integration is added.
- Mask email app password in UI fields.
- Redact secrets from exception messages before surfacing them in GUI status.
- Do not include credentials in issue comments, generated logs, test fixtures, or screenshots.

## Open Questions

- Should SMTP be generic email support with Gmail defaults, or explicitly named Gmail in the UI? Decision: generic SMTP internally and in the UI; Gmail appears only as an example/default provider.
- Should email failure be reported only to logs, or mirrored to other channels? Recommendation: logs only for MVP to avoid recursive notification complexity.
- Should HTML formatting ship in MVP? Recommendation: text/plain plus attachments first; add HTML after delivery is stable.
- Should OAuth be supported? Recommendation: not in issue #6 MVP. Track separately if users need Workspace policies that disable App Passwords.
