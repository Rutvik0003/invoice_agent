"""Inbox: the emails invoices arrive in. Demo mode reads the demo inbox; real mode reads the owner's Gmail.

Both give emails in the same shape, and choosing attachments starts runs exactly like an upload: one attachment is
a single run, several are a batch. The run remembers the email it came from (vendor replies go in that thread).
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.batches import BatchFile, queue_batch
from app.api.common import engine_of, iso_utc
from app.api.runs import create_run
from app.config import get_settings
from app.demo.inbox import InboxAttachment, InboxMessage, attachment_hash, demo_inbox, email_source
from app.demo.mode import check_demo_quota, is_demo, signed_in_owner
from app.gmail import accounts
from app.gmail.client import BILLS_QUERY, GmailClient, GmailError
from app.gmail.oauth import OAuthError
from app.models import EmailLog, Run
from app.runtime_settings import effective_settings

router = APIRouter(prefix="/api", tags=["inbox"])
INVOICE_TYPES = ("application/pdf", "image/png", "image/jpeg")
INVOICE_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg")


class InboxItem(BaseModel):
    message_id: str
    attachment_id: str


class InboxRunRequest(BaseModel):
    items: list[InboxItem] = Field(min_length=1, max_length=50)
    model: Literal["gemini", "groq"] | None = None  # real mode only; the demo always uses Gemini
    model_name: str | None = None  # one of that provider's models (default: its configured model)


def _runs(request: Request) -> list[Run]:
    with Session(engine_of(request)) as session:
        runs = session.scalars(select(Run).where(Run.is_test_run.is_(False)).order_by(Run.created_at)).all()
        session.expunge_all()
    return list(runs)


def _last_run(run: Run | None) -> dict | None:
    return {"id": run.id, "status": run.status, "decision": run.decision} if run else None


def _replies_by_thread(request: Request) -> dict[str, list[dict]]:
    """Our replies (vendor emails sent from a run), grouped by the inbox email they answer."""
    with Session(engine_of(request)) as session:
        rows = session.scalars(select(EmailLog).where(EmailLog.thread_message_id.is_not(None))
                               .order_by(EmailLog.id)).all()
        out: dict[str, list[dict]] = {}
        for r in rows:
            out.setdefault(r.thread_message_id, []).append({
                "sent_at": iso_utc(r.created_at), "from": r.sender, "to": r.recipient, "subject": r.subject,
                "body": r.body, "run_id": r.run_id})
    return out


# ---------------------------------------------------------------- demo inbox


def _demo_attachment_dict(attachment: InboxAttachment, processed: dict[str, Run]) -> dict:
    return {"id": attachment.id, "file_name": attachment.file_name, "mime": attachment.mime,
            "size": attachment.file.stat().st_size, "is_invoice_file": attachment.mime in INVOICE_TYPES,
            "last_run": _last_run(processed.get(attachment_hash(attachment.path)))}


def _demo_message_dict(message: InboxMessage, processed: dict[str, Run], replies: dict[str, list[dict]]) -> dict:
    return {**message.model_dump(mode="json", exclude={"attachments"}),
            "attachments": [_demo_attachment_dict(a, processed) for a in message.attachments],
            "replies": replies.get(message.id, [])}


def _demo_attachment(message_id: str, attachment_id: str) -> tuple[InboxMessage, InboxAttachment]:
    found = demo_inbox().find(message_id, attachment_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such email attachment.")
    return found


# ---------------------------------------------------------------- Gmail (real mode)


def gmail_account(request: Request) -> str | None:
    """The connected Gmail address real mode reads: the signed-in owner's, or (real mode not locked) any connected."""
    if is_demo(request):
        return None
    engine = request.app.state.engine
    email = signed_in_owner(request) or accounts.connected_email(engine)
    return email if accounts.account(engine, email) is not None else None


def gmail_client(request: Request, email: str) -> GmailClient:
    """One client per mailbox (it caches emails, which never change). Tests replace app.state.gmail_factory."""
    clients: dict = request.app.state.gmail_clients
    if email not in clients:
        clients[email] = request.app.state.gmail_factory(request.app.state.engine, email)
    return clients[email]


def default_gmail_factory(engine, email: str) -> GmailClient:
    return GmailClient(lambda: accounts.access_token(engine, get_settings(), email))


def _gmail_or_409(request: Request) -> GmailClient:
    email = gmail_account(request)
    if email is None:
        raise HTTPException(status_code=409, detail="Gmail is not connected.")
    return gmail_client(request, email)


def _is_invoice_file(attachment: dict) -> bool:
    return attachment["mime"] in INVOICE_TYPES or attachment["file_name"].lower().endswith(INVOICE_EXTENSIONS)


def _gmail_message_dict(message: dict, runs: list[Run], replies: dict[str, list[dict]]) -> dict:
    """An email as the UI shows it; an attachment's last run is found by the email and file it came from."""
    def last(attachment: dict) -> Run | None:
        matches = [r for r in runs if (r.source_json or {}).get("message_id") == message["id"]
                   and r.file_name == attachment["file_name"]]
        return matches[-1] if matches else None

    return {**{k: v for k, v in message.items() if k != "attachments"},
            "attachments": [{"id": a["id"], "file_name": a["file_name"], "mime": a["mime"], "size": a["size"],
                             "is_invoice_file": _is_invoice_file(a), "last_run": _last_run(last(a))}
                            for a in message["attachments"]],
            "replies": replies.get(message["id"], [])}


def _gmail_source(message: dict, attachment: dict) -> dict:
    return {"kind": "gmail", "message_id": message["id"], "thread_id": message.get("thread_id"),
            "attachment_id": attachment["id"], "from_name": message["from_name"], "from_email": message["from_email"],
            "subject": message["subject"], "received_at": message["received_at"]}


def _gmail_error(exc: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail={"type": "gmail_error", "message": str(exc)})


# ---------------------------------------------------------------- endpoints


@router.get("/inbox")
def list_inbox(request: Request, bills_only: bool = True, q: str = "", page_token: str | None = None) -> dict:
    """The emails, newest first, with their attachments and whether each was processed already.
    Gmail: bills_only limits the search to emails with a PDF/PNG/JPG attachment; q is any Gmail search text."""
    if is_demo(request):
        inbox = demo_inbox()
        processed = {r.file_hash: r for r in _runs(request)}
        replies = _replies_by_thread(request)
        return {"source": "demo", "connected": True, "mailbox": inbox.mailbox, "next_page_token": None,
                "messages": [_demo_message_dict(m, processed, replies) for m in inbox.messages]}
    engine_of(request)  # real-mode data: the owner only (once locked)
    email = gmail_account(request)
    if email is None:
        return {"source": "gmail", "connected": False, "can_connect": get_settings().google_configured,
                "mailbox": None, "next_page_token": None, "messages": []}
    query = " ".join(part for part in (BILLS_QUERY if bills_only else "in:inbox", q.strip()) if part)
    try:
        messages, next_token = gmail_client(request, email).list_messages(query, page_token)
    except (GmailError, OAuthError) as exc:
        raise _gmail_error(exc) from exc
    runs, replies = _runs(request), _replies_by_thread(request)
    return {"source": "gmail", "connected": True, "mailbox": email, "next_page_token": next_token,
            "messages": [_gmail_message_dict(m, runs, replies) for m in messages]}


@router.get("/inbox/{message_id}/attachments/{attachment_id}")
def attachment_file(message_id: str, attachment_id: str, request: Request) -> Response:
    """The attachment itself (to open it before deciding to run it)."""
    if is_demo(request):
        _, attachment = _demo_attachment(message_id, attachment_id)
        name, mime, data = attachment.file_name, attachment.mime, attachment.file.read_bytes()
    else:
        engine_of(request)
        try:
            _, info, data = _gmail_or_409(request).attachment(message_id, attachment_id)
        except (GmailError, OAuthError) as exc:
            raise _gmail_error(exc) from exc
        name, mime = info["file_name"], info["mime"] or "application/octet-stream"
    return Response(data, media_type=mime, headers={"Content-Disposition": f'inline; filename="{name}"'})


def _chosen_files(request: Request, items: list[InboxItem]) -> list[BatchFile]:
    if is_demo(request):
        return [BatchFile(a.file_name, a.file.read_bytes(), a.sample_id, email_source(m, a))
                for m, a in (_demo_attachment(i.message_id, i.attachment_id) for i in items)]
    client = _gmail_or_409(request)
    files = []
    try:
        for item in items:
            message, info, data = client.attachment(item.message_id, item.attachment_id)
            files.append(BatchFile(info["file_name"], data, None, _gmail_source(message, info)))
    except (GmailError, OAuthError) as exc:
        raise _gmail_error(exc) from exc
    return files


@router.post("/inbox/run")
def run_attachments(body: InboxRunRequest, request: Request, background: BackgroundTasks) -> dict:
    """Process the chosen attachments: one -> a single run (live view), several -> a batch."""
    engine = engine_of(request)
    settings = effective_settings(engine)
    check_demo_quota(request, engine, len(body.items), settings.demo_max_runs_per_hour)
    model = "gemini" if is_demo(request) else (body.model or settings.default_model)
    files = _chosen_files(request, body.items)
    if len(files) == 1:
        f = files[0]
        run_id = create_run(request, background, f.file_name, f.data, model, False, sample_id=f.sample_id,
                            model_name=body.model_name, source=f.source)
        return {"run_id": run_id}
    return queue_batch(request, files, model, body.model_name, False)
