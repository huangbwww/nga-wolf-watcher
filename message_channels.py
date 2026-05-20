from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChannelAttachment:
    path: Path
    kind: str
    mime_type: str = ""


@dataclass(frozen=True)
class ChannelMessage:
    message_id: str
    sender_id: str
    text: str
    attachments: tuple[ChannelAttachment, ...] = ()


class ChannelError(RuntimeError):
    pass
