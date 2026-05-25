from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from mimetypes import guess_type
from pathlib import Path
from typing import Iterable


DEFAULT_SMTP_HOST = "smtp.gmail.com"
DEFAULT_SMTP_PORT = 587
DEFAULT_SMTP_SECURITY = "starttls"


@dataclass(frozen=True)
class EmailAttachment:
    file_name: str
    content: bytes
    mime_type: str = "text/plain"


@dataclass(frozen=True)
class EmailSmtpConfig:
    smtp_host: str = DEFAULT_SMTP_HOST
    smtp_port: int = DEFAULT_SMTP_PORT
    smtp_security: str = DEFAULT_SMTP_SECURITY
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = "NGA Wolf Watcher"
    reply_to: str = ""
    timeout: int = 20

    @property
    def sender(self) -> str:
        return self.from_email or self.username


class EmailChannelError(RuntimeError):
    pass


def redact_secret(text: object, secrets: Iterable[str]) -> str:
    result = str(text)
    for secret in secrets:
        secret_text = str(secret or "")
        if not secret_text:
            continue
        result = result.replace(secret_text, "***")
        compact = secret_text.replace(" ", "")
        if compact and compact != secret_text:
            result = result.replace(compact, "***")
    return result


def _attachment_parts(attachment: EmailAttachment) -> tuple[str, str]:
    mime_type = attachment.mime_type or guess_type(attachment.file_name)[0] or "application/octet-stream"
    if "/" not in mime_type:
        return "application", "octet-stream"
    return tuple(mime_type.split("/", 1))  # type: ignore[return-value]


def build_email_message(
    config: EmailSmtpConfig,
    recipient: str,
    subject: str,
    text: str,
    *,
    html: str = "",
    attachments: Iterable[EmailAttachment] = (),
) -> EmailMessage:
    recipient = str(recipient or "").strip()
    sender = config.sender.strip()
    if not recipient:
        raise EmailChannelError("Missing email recipient")
    if not sender:
        raise EmailChannelError("Missing email sender")

    message = EmailMessage()
    message["Subject"] = str(subject or "NGA Wolf Watcher")
    message["From"] = formataddr((config.from_name, sender)) if config.from_name else sender
    message["To"] = recipient
    if config.reply_to:
        message["Reply-To"] = config.reply_to
    message.set_content(str(text or ""))
    if html:
        message.add_alternative(str(html), subtype="html")
    for attachment in attachments:
        maintype, subtype = _attachment_parts(attachment)
        message.add_attachment(
            attachment.content,
            maintype=maintype,
            subtype=subtype,
            filename=Path(attachment.file_name).name or "attachment.txt",
        )
    return message


def send_email(
    config: EmailSmtpConfig,
    recipient: str,
    subject: str,
    text: str,
    *,
    html: str = "",
    attachments: Iterable[EmailAttachment] = (),
) -> None:
    host = config.smtp_host.strip() or DEFAULT_SMTP_HOST
    port = int(config.smtp_port or DEFAULT_SMTP_PORT)
    security = (config.smtp_security or DEFAULT_SMTP_SECURITY).strip().lower()
    message = build_email_message(config, recipient, subject, text, html=html, attachments=attachments)
    secrets = [config.password, config.username]

    try:
        if security in {"ssl", "smtps"}:
            with smtplib.SMTP_SSL(host, port, timeout=config.timeout, context=ssl.create_default_context()) as smtp:
                if config.username or config.password:
                    smtp.login(config.username, config.password)
                smtp.send_message(message)
            return

        with smtplib.SMTP(host, port, timeout=config.timeout) as smtp:
            if security in {"starttls", "tls"}:
                smtp.starttls(context=ssl.create_default_context())
            if config.username or config.password:
                smtp.login(config.username, config.password)
            smtp.send_message(message)
    except Exception as exc:
        raise EmailChannelError(redact_secret(f"Email send failed: {exc}", secrets)) from exc
