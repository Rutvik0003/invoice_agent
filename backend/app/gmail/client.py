"""Read-only Gmail: list emails, read one, download an attachment (Gmail API v1 over HTTPS).

Emails come back in the same shape as the demo inbox, so the Inbox screen and the run flow are the same in both
modes. An attachment is identified by its MIME part id ("2", "1.2", ...), which stays the same for a message
(Gmail's own attachment ids are long, and they change between requests).
"""

from __future__ import annotations

import base64
import html
import re
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Callable

import httpx

API = "https://gmail.googleapis.com/gmail/v1/users/me"
TIMEOUT_S = 20
BILLS_QUERY = "has:attachment (filename:pdf OR filename:png OR filename:jpg OR filename:jpeg)"
CACHE_SIZE = 500


class GmailError(Exception):
    """Gmail could not be read; the message is safe to show."""


def _b64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _headers(payload: dict) -> dict[str, str]:
    return {h["name"].lower(): h["value"] for h in payload.get("headers", [])}


def _parts(part: dict):
    """Every MIME part of a message, depth first."""
    yield part
    for child in part.get("parts", []) or []:
        yield from _parts(child)


def _text(payload: dict) -> str:
    """The readable body: the plain-text part, else the HTML part without tags."""
    parts = list(_parts(payload))
    for mime in ("text/plain", "text/html"):
        part = next((p for p in parts if p.get("mimeType") == mime and p.get("body", {}).get("data")), None)
        if part is None:
            continue
        text = _b64(part["body"]["data"]).decode("utf-8", errors="replace")
        if mime == "text/html":
            text = html.unescape(re.sub(r"<[^>]+>", " ", re.sub(r"(?is)<(style|script).*?</\1>", "", text)))
            text = re.sub(r"[ \t]+", " ", text)
        return re.sub(r"\n{3,}", "\n\n", text).strip()
    return ""


def parse_message(raw: dict) -> dict:
    """A Gmail API message (format=full) -> the inbox shape used by the UI and the run flow."""
    payload = raw.get("payload", {})
    head = _headers(payload)
    name, address = parseaddr(head.get("from", ""))
    received = datetime.fromtimestamp(int(raw.get("internalDate", "0")) / 1000, tz=timezone.utc)
    attachments = [{"id": p.get("partId", ""), "file_name": p["filename"], "mime": p.get("mimeType", ""),
                    "size": int(p.get("body", {}).get("size", 0)), "gmail_attachment_id": p["body"]["attachmentId"]}
                   for p in _parts(payload) if p.get("filename") and p.get("body", {}).get("attachmentId")]
    return {"id": raw["id"], "thread_id": raw.get("threadId"), "from_name": name or address, "from_email": address.lower(),
            "to": head.get("to", ""), "subject": head.get("subject", "(no subject)"), "received_at": received.isoformat(),
            "body": _text(payload) or raw.get("snippet", ""), "attachments": attachments}


class GmailClient:
    """Read-only access to one mailbox. access_token() returns a valid token (refreshed by the caller's store)."""

    def __init__(self, access_token: Callable[[], str]) -> None:
        self._token = access_token
        self._cache: OrderedDict[str, dict] = OrderedDict()
        self._lock = threading.Lock()

    def _get(self, path: str, params: dict | None = None) -> dict:
        try:
            response = httpx.get(f"{API}/{path}", params=params, timeout=TIMEOUT_S,
                                 headers={"Authorization": f"Bearer {self._token()}"})
        except httpx.HTTPError as exc:
            raise GmailError(f"Could not reach Gmail ({type(exc).__name__}).") from exc
        if response.status_code == 401:
            raise GmailError("Gmail refused the stored access. Connect Gmail again.")
        if response.status_code == 429:
            raise GmailError("Gmail is limiting requests right now. Try again in a minute.")
        if response.status_code != 200:
            raise GmailError(f"Gmail answered {response.status_code}.")
        return response.json()

    def message(self, message_id: str) -> dict:
        """One email (cached: an email never changes)."""
        with self._lock:
            if message_id in self._cache:
                return self._cache[message_id]
        parsed = parse_message(self._get(f"messages/{message_id}", {"format": "full"}))
        with self._lock:
            self._cache[message_id] = parsed
            while len(self._cache) > CACHE_SIZE:
                self._cache.popitem(last=False)
        return parsed

    def list_messages(self, query: str, page_token: str | None = None, limit: int = 20) -> tuple[list[dict], str | None]:
        """The newest emails matching a Gmail search query, read in parallel, plus the token of the next page."""
        params = {"q": query, "maxResults": limit, **({"pageToken": page_token} if page_token else {})}
        page = self._get("messages", params)
        ids = [m["id"] for m in page.get("messages", [])]
        with ThreadPoolExecutor(max_workers=6) as pool:
            messages = list(pool.map(self.message, ids))
        return messages, page.get("nextPageToken")

    def attachment(self, message_id: str, part_id: str) -> tuple[dict, dict, bytes]:
        """(message, attachment info, file bytes) for one attachment of an email."""
        message = self.message(message_id)
        info = next((a for a in message["attachments"] if a["id"] == part_id), None)
        if info is None:
            raise GmailError("No such attachment in this email.")
        data = self._get(f"messages/{message_id}/attachments/{info['gmail_attachment_id']}")
        return message, info, _b64(data["data"])
