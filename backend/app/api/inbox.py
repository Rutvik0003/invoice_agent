"""Inbox: the emails invoices arrive in. Demo mode reads the demo inbox; real mode will read Gmail (Phase 11).

Choosing attachments starts runs exactly like an upload: one attachment is a single run, several are a batch.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.batches import BatchFile, queue_batch
from app.api.common import engine_of, iso_utc
from app.api.runs import create_run
from app.demo.inbox import InboxAttachment, InboxMessage, attachment_hash, demo_inbox, email_source
from app.demo.mode import check_demo_quota, is_demo
from app.models import EmailLog, Run
from app.runtime_settings import effective_settings

router = APIRouter(prefix="/api", tags=["inbox"])
INVOICE_TYPES = ("application/pdf", "image/png", "image/jpeg")


class InboxItem(BaseModel):
    message_id: str
    attachment_id: str


class InboxRunRequest(BaseModel):
    items: list[InboxItem] = Field(min_length=1, max_length=50)
    model_name: str | None = None  # one of the Gemini models (default: GEMINI_MODEL / DEMO_GEMINI_MODEL)


def _latest_runs_by_hash(request: Request) -> dict[str, Run]:
    """The newest run of each file in this database (so the inbox can show which attachments were processed)."""
    with Session(engine_of(request)) as session:
        runs = session.scalars(select(Run).where(Run.is_test_run.is_(False)).order_by(Run.created_at)).all()
        session.expunge_all()
    return {r.file_hash: r for r in runs}


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


def _attachment_dict(attachment: InboxAttachment, processed: dict[str, Run]) -> dict:
    run = processed.get(attachment_hash(attachment.path))
    return {"id": attachment.id, "file_name": attachment.file_name, "mime": attachment.mime,
            "size": attachment.file.stat().st_size, "is_invoice_file": attachment.mime in INVOICE_TYPES,
            "last_run": {"id": run.id, "status": run.status, "decision": run.decision} if run else None}


def _message_dict(message: InboxMessage, processed: dict[str, Run], replies: dict[str, list[dict]]) -> dict:
    return {**message.model_dump(mode="json", exclude={"attachments"}),
            "attachments": [_attachment_dict(a, processed) for a in message.attachments],
            "replies": replies.get(message.id, [])}


@router.get("/inbox")
def list_inbox(request: Request) -> dict:
    """The emails, newest first, with their attachments and whether each was processed already."""
    if not is_demo(request):
        return {"source": "gmail", "connected": False, "mailbox": None, "messages": []}
    inbox = demo_inbox()
    processed, replies = _latest_runs_by_hash(request), _replies_by_thread(request)
    return {"source": "demo", "connected": True, "mailbox": inbox.mailbox,
            "messages": [_message_dict(m, processed, replies) for m in inbox.messages]}


def _demo_attachment(request: Request, message_id: str, attachment_id: str) -> tuple[InboxMessage, InboxAttachment]:
    if not is_demo(request):
        raise HTTPException(status_code=409, detail="Gmail is not connected yet.")
    found = demo_inbox().find(message_id, attachment_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No such email attachment.")
    return found


@router.get("/inbox/{message_id}/attachments/{attachment_id}")
def attachment_file(message_id: str, attachment_id: str, request: Request) -> Response:
    """The attachment itself (to open it before deciding to run it)."""
    _, attachment = _demo_attachment(request, message_id, attachment_id)
    return Response(attachment.file.read_bytes(), media_type=attachment.mime,
                    headers={"Content-Disposition": f'inline; filename="{attachment.file_name}"'})


@router.post("/inbox/run")
def run_attachments(body: InboxRunRequest, request: Request, background: BackgroundTasks) -> dict:
    """Process the chosen attachments: one -> a single run (live view), several -> a batch."""
    chosen = [_demo_attachment(request, i.message_id, i.attachment_id) for i in body.items]
    engine = engine_of(request)
    settings = effective_settings(engine)
    check_demo_quota(request, engine, len(chosen), settings.demo_max_runs_per_hour)
    files = [BatchFile(a.file_name, a.file.read_bytes(), a.sample_id, email_source(m, a)) for m, a in chosen]
    if len(files) == 1:
        f = files[0]
        run_id = create_run(request, background, f.file_name, f.data, "gemini", False, sample_id=f.sample_id,
                            model_name=body.model_name, source=f.source)
        return {"run_id": run_id}
    return queue_batch(request, files, "gemini", body.model_name, False)
