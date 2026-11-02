"""The demo inbox: fixed emails from the fictional vendors, with the golden invoices attached (CLAUDE.md §12).

It plays the part Gmail plays in real mode: the Inbox screen lists these emails and the chosen attachments are
processed like any other invoice. The file is data/demo_inbox/inbox.json; attachment paths are under data/.
"""

from __future__ import annotations

import hashlib
import mimetypes
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.config import REPO_ROOT

DATA_DIR = REPO_ROOT / "data"
INBOX_FILE = DATA_DIR / "demo_inbox" / "inbox.json"


class InboxAttachment(BaseModel):
    id: str
    path: str  # relative to data/

    @property
    def file(self) -> Path:
        return DATA_DIR / self.path

    @property
    def file_name(self) -> str:
        return Path(self.path).name

    @property
    def mime(self) -> str:
        return mimetypes.guess_type(self.file_name)[0] or "application/octet-stream"

    @property
    def sample_id(self) -> str:
        """The generated invoice it is (its label explains the scenario on the run page)."""
        return Path(self.path).stem


class InboxMessage(BaseModel):
    id: str
    from_name: str
    from_email: str
    to: str
    subject: str
    received_at: datetime
    body: str
    attachments: list[InboxAttachment] = []


class DemoInbox(BaseModel):
    mailbox: str
    messages: list[InboxMessage]

    def find(self, message_id: str, attachment_id: str) -> tuple[InboxMessage, InboxAttachment] | None:
        message = next((m for m in self.messages if m.id == message_id), None)
        attachment = next((a for a in message.attachments if a.id == attachment_id), None) if message else None
        return (message, attachment) if attachment else None


@lru_cache
def demo_inbox() -> DemoInbox:
    return DemoInbox.model_validate_json(INBOX_FILE.read_text(encoding="utf-8"))


@lru_cache
def attachment_hash(path: str) -> str:
    """SHA-256 of an attachment (the same hash a run stores, so the inbox can show what was processed)."""
    return hashlib.sha256((DATA_DIR / path).read_bytes()).hexdigest()


def email_source(message: InboxMessage, attachment: InboxAttachment) -> dict:
    """What a run remembers about the email its invoice came from."""
    return {"kind": "demo_inbox", "message_id": message.id, "attachment_id": attachment.id,
            "from_name": message.from_name, "from_email": message.from_email, "subject": message.subject,
            "received_at": message.received_at.isoformat()}
