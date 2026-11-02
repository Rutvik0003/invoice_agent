"""Real mode (Phase 11): Google sign-in for the owner only, the Gmail inbox, and runs from Gmail attachments.

Google and Gmail are replaced by fakes here (no network): the sign-in exchange is monkeypatched and the mailbox is
a FakeGmail with the golden invoices attached.
"""

import base64
import time
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from app.db import make_engine
from app.gmail import oauth
from app.gmail.client import parse_message
from app.main import create_app
from tests.test_api import INVOICES, fake_extract

OWNER = "owner@example.com"


class FakeGmail:
    """A mailbox with two vendor emails carrying golden invoices and one without attachments."""

    def __init__(self) -> None:
        def mail(mid, sender, address, subject, files):
            return {"id": mid, "thread_id": f"t-{mid}", "from_name": sender, "from_email": address,
                    "to": OWNER, "subject": subject, "received_at": "2026-10-20T10:00:00+00:00", "body": "Please pay.",
                    "attachments": [{"id": str(i + 2), "file_name": f, "mime": "application/pdf", "size": 100,
                                     "gmail_attachment_id": f"att-{i}"} for i, f in enumerate(files)]}

        self.messages = [
            mail("g1", "Vertex Enterprises", "accounts@vertexenterprises.in", "Invoice VE0393", ["01_happy_clean.pdf"]),
            mail("g2", "Borah Polymers", "sales@borahpolymers.in", "Tax invoice BP/343/26", ["07_E_wrong_gst.pdf"]),
            mail("g3", "Newsletter", "news@example.com", "Weekly news", []),
        ]
        self.queries: list[str] = []

    def list_messages(self, query, page_token=None, limit=20):
        self.queries.append(query)
        wanted = [m for m in self.messages if m["attachments"] or "has:attachment" not in query]
        return wanted, None

    def attachment(self, message_id, part_id):
        message = next(m for m in self.messages if m["id"] == message_id)
        info = next(a for a in message["attachments"] if a["id"] == part_id)
        return message, info, (INVOICES / "golden" / info["file_name"]).read_bytes()


@pytest.fixture
def google(monkeypatch):
    """Google sign-in configured, real mode locked to OWNER; the token exchange answers for whoever `who` is."""
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("OWNER_EMAIL", OWNER)
    who = {"email": OWNER, "scopes": f"openid email {oauth.GMAIL_READONLY}"}
    revoked: list[str] = []
    monkeypatch.setattr(oauth, "exchange_code", lambda settings, code, uri: oauth.Tokens(
        "access-" + code, "refresh-" + code, time.time() + 3600, who["scopes"]))
    monkeypatch.setattr(oauth, "signed_in_email", lambda token: who["email"])
    monkeypatch.setattr(oauth, "revoke", lambda token: revoked.append(token))
    return {"who": who, "revoked": revoked}


@pytest.fixture
def app_env(tmp_path, google):
    engine = make_engine(f"sqlite:///{(tmp_path / 'real.db').as_posix()}")
    app = create_app(frontend_dist=tmp_path, engine=engine, extract_fn=fake_extract, sandbox_root=tmp_path / "sb")
    gmail = FakeGmail()
    app.state.gmail_factory = lambda engine, email: gmail
    with TestClient(app):
        yield app, engine, gmail
    for sandbox in app.state.sandboxes.engines():
        sandbox.dispose()
    engine.dispose()


def sign_in(app) -> TestClient:
    """Go through the start -> Google -> callback round trip; returns the browser (cookies set)."""
    browser = TestClient(app)
    start = browser.get("/api/auth/google/start", follow_redirects=False)
    assert start.status_code == 303
    query = parse_qs(urlparse(start.headers["location"]).query)
    assert query["scope"][0].split() == ["openid", "email", oauth.GMAIL_READONLY]
    assert query["access_type"] == ["offline"]
    back = browser.get("/api/auth/google/callback", params={"code": "c1", "state": query["state"][0]},
                       follow_redirects=False)
    assert back.status_code == 303
    browser.last_redirect = back.headers["location"]
    return browser


# ---------------------------------------------------------------- sign-in and the owner lock


def test_the_owner_signs_in_and_lands_in_the_gmail_inbox(app_env):
    app, engine, _ = app_env
    owner = sign_in(app)
    assert owner.last_redirect == "/inbox"
    mode = owner.get("/api/mode").json()
    assert mode["mode"] == "real" and mode["auth"]["signed_in_as"] == OWNER and mode["auth"]["gmail"] == OWNER
    from sqlalchemy.orm import Session

    from app.models import GmailAccount
    with Session(engine) as session:
        stored = session.get(GmailAccount, OWNER).refresh_token_encrypted
    assert "refresh-c1" not in stored  # encrypted at rest


def test_real_mode_is_closed_to_everyone_else(app_env):
    app, _, _ = app_env
    stranger = TestClient(app)
    assert stranger.post("/api/mode", json={"mode": "real"}).status_code == 401
    assert stranger.get("/api/runs").status_code == 401
    assert stranger.get("/api/inbox").status_code == 401
    forged = TestClient(app, cookies={"ia_mode": "real", "ia_owner": "made-up"})
    assert forged.get("/api/mode").json()["mode"] is None
    assert forged.get("/api/runs").status_code == 401
    # the demo stays open to everyone
    assert stranger.post("/api/mode", json={"mode": "demo"}).status_code == 200
    assert stranger.get("/api/runs").status_code == 200


def test_another_google_account_is_turned_away_and_its_access_revoked(app_env, google):
    app, _, _ = app_env
    google["who"]["email"] = "someone@else.com"
    browser = sign_in(app)
    assert browser.last_redirect == "/?auth_error=not_owner"
    assert google["revoked"] == ["refresh-c1"]
    assert browser.get("/api/mode").json()["auth"]["gmail"] is None


def test_a_forged_callback_is_refused(app_env):
    app, _, _ = app_env
    browser = TestClient(app)
    browser.get("/api/auth/google/start", follow_redirects=False)
    back = browser.get("/api/auth/google/callback", params={"code": "c1", "state": "not-the-state"}, follow_redirects=False)
    assert back.headers["location"] == "/?auth_error=invalid_state"


def test_sign_in_without_gmail_permission_is_refused(app_env, google):
    app, _, _ = app_env
    google["who"]["scopes"] = "openid email"
    assert sign_in(app).last_redirect == "/?auth_error=no_gmail"


def test_sign_out_and_disconnect(app_env, google):
    app, _, _ = app_env
    owner = sign_in(app)
    owner.post("/api/auth/logout")
    assert owner.get("/api/mode").json()["mode"] is None
    assert owner.get("/api/runs").status_code == 401
    owner = sign_in(app)
    assert owner.post("/api/auth/disconnect").json()["disconnected"] == OWNER
    assert google["revoked"] == ["refresh-c1"]
    assert owner.get("/api/mode").json()["auth"]["gmail"] is None


# ---------------------------------------------------------------- the Gmail inbox


def test_the_inbox_lists_gmail_emails_with_bills(app_env):
    app, _, gmail = app_env
    owner = sign_in(app)
    inbox = owner.get("/api/inbox").json()
    assert inbox["source"] == "gmail" and inbox["connected"] and inbox["mailbox"] == OWNER
    assert [m["id"] for m in inbox["messages"]] == ["g1", "g2"]
    assert inbox["messages"][0]["attachments"][0]["is_invoice_file"]
    assert "has:attachment" in gmail.queries[-1]
    everything = owner.get("/api/inbox", params={"bills_only": False, "q": "from:borah"}).json()
    assert len(everything["messages"]) == 3 and gmail.queries[-1] == "in:inbox from:borah"


def test_a_gmail_attachment_runs_and_remembers_its_email(app_env):
    app, _, _ = app_env
    owner = sign_in(app)
    response = owner.post("/api/inbox/run", json={"items": [{"message_id": "g2", "attachment_id": "2"}]})
    assert response.status_code == 200, response.text
    run = owner.get(f"/api/runs/{response.json()['run_id']}").json()
    assert run["decision"] == "REJECT"
    assert run["source"]["kind"] == "gmail" and run["source"]["thread_id"] == "t-g2"
    # the inbox shows the result next to the attachment, and the vendor reply sits in that email's thread
    message = next(m for m in owner.get("/api/inbox").json()["messages"] if m["id"] == "g2")
    assert message["attachments"][0]["last_run"]["decision"] == "REJECT"
    preview = owner.get(f"/api/runs/{run['id']}/email").json()
    assert preview["subject"] == "Re: Tax invoice BP/343/26" and preview["recipient"] == "sales@borahpolymers.in"
    owner.post(f"/api/runs/{run['id']}/email")
    message = next(m for m in owner.get("/api/inbox").json()["messages"] if m["id"] == "g2")
    assert len(message["replies"]) == 1


def test_several_gmail_attachments_run_as_a_batch(app_env):
    app, _, _ = app_env
    owner = sign_in(app)
    items = [{"message_id": "g1", "attachment_id": "2"}, {"message_id": "g2", "attachment_id": "2"}]
    batch_id = owner.post("/api/inbox/run", json={"items": items, "model": "gemini"}).json()["batch_id"]
    deadline = time.monotonic() + 60
    while not (batch := owner.get(f"/api/batches/{batch_id}").json())["finished"]:
        assert time.monotonic() < deadline
        time.sleep(0.2)
    assert batch["by_decision"] == {"APPROVE": 1, "REJECT": 1}


def test_opening_a_gmail_attachment(app_env):
    app, _, _ = app_env
    owner = sign_in(app)
    pdf = owner.get("/api/inbox/g1/attachments/2")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


# ---------------------------------------------------------------- reading Gmail's message format


def test_parse_message_reads_sender_subject_body_and_attachments():
    def b64(text: str) -> str:
        return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")

    raw = {"id": "m1", "threadId": "t1", "internalDate": "1792828800000", "snippet": "snip",
           "payload": {"mimeType": "multipart/mixed", "headers": [
               {"name": "From", "value": "Vertex Enterprises <Accounts@VertexEnterprises.in>"},
               {"name": "To", "value": OWNER}, {"name": "Subject", "value": "Invoice VE0393"}],
               "parts": [
                   {"partId": "0", "mimeType": "multipart/alternative", "parts": [
                       {"partId": "0.0", "mimeType": "text/html", "body": {"data": b64("<p>Hello <b>team</b></p>")}},
                       {"partId": "0.1", "mimeType": "text/plain", "body": {"data": b64("Hello team")}}]},
                   {"partId": "1", "mimeType": "application/pdf", "filename": "VE0393.pdf",
                    "body": {"attachmentId": "ANGjdJ8...", "size": 51200}}]}}
    message = parse_message(raw)
    assert message["from_name"] == "Vertex Enterprises" and message["from_email"] == "accounts@vertexenterprises.in"
    assert message["subject"] == "Invoice VE0393" and message["body"] == "Hello team" and message["thread_id"] == "t1"
    assert message["attachments"] == [{"id": "1", "file_name": "VE0393.pdf", "mime": "application/pdf", "size": 51200,
                                       "gmail_attachment_id": "ANGjdJ8..."}]
    assert message["received_at"].startswith("2026-10-")


def test_tokens_are_encrypted_with_a_key_from_the_environment(monkeypatch):
    from app.config import get_settings

    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret-1")
    settings = get_settings()
    sealed = oauth.encrypt(settings, "refresh-token")
    assert "refresh-token" not in sealed and oauth.decrypt(settings, sealed) == "refresh-token"
    with pytest.raises(oauth.OAuthError):
        oauth.decrypt(settings.model_copy(update={"google_client_secret": "secret-2"}), sealed)
