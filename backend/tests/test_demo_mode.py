"""Demo mode (CLAUDE.md §12): a sandbox per visitor, the demo inbox, demo-only AI settings and restrictions."""

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.demo.inbox import demo_inbox
from app.main import create_app
from app.models import Run
from tests.test_api import GOLDEN, INVOICES, fake_extract, failing_extract

SEEN_KEYS: list[tuple[str, str, str]] = []


def recording_extract(data, mime, provider, settings, engine=None, use_cache=False, page_images=None):
    """The fake reader, remembering which provider, key and model each request would have used."""
    SEEN_KEYS.append((provider, settings.gemini_api_key, settings.gemini_model))
    return fake_extract(data, mime, provider, settings, engine, use_cache, page_images)


@pytest.fixture
def demo_env(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "real-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-real")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GROQ_MODEL", "groq-model")
    monkeypatch.setenv("DEMO_GEMINI_API_KEY", "demo-key")
    monkeypatch.setenv("DEMO_GEMINI_MODEL", "gemini-demo")
    # independent of the developer's .env
    monkeypatch.setenv("GEMINI_MODELS", "gemini-2.5-flash,gemini-3.6-flash,gemini-3.8-flash")
    monkeypatch.setenv("DEMO_GEMINI_MODELS", "")
    SEEN_KEYS.clear()


def make_app(tmp_path, extract_fn=recording_extract):
    engine = make_engine(f"sqlite:///{(tmp_path / 'real.db').as_posix()}")
    app = create_app(frontend_dist=tmp_path, engine=engine, extract_fn=extract_fn, sandbox_root=tmp_path / "sandboxes")
    return app, engine


@pytest.fixture
def app_and_engine(tmp_path, demo_env):
    app, engine = make_app(tmp_path)
    with TestClient(app):  # startup: real database tables + seed, batch worker
        yield app, engine
    for sandbox in app.state.sandboxes.engines():
        sandbox.dispose()
    engine.dispose()


def visitor(app) -> TestClient:
    client = TestClient(app)
    assert client.post("/api/mode", json={"mode": "demo"}).status_code == 200
    return client


def first_attachment(name: str) -> dict:
    message = next(m for m in demo_inbox().messages if any(a.file_name == name for a in m.attachments))
    attachment = next(a for a in message.attachments if a.file_name == name)
    return {"message_id": message.id, "attachment_id": attachment.id}


def run_from_inbox(client, *names: str) -> dict:
    response = client.post("/api/inbox/run", json={"items": [first_attachment(n) for n in names]})
    assert response.status_code == 200, response.text
    return response.json()


def run_count(engine) -> int:
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(Run))


def wait_for_batch(client, batch_id: str) -> dict:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        batch = client.get(f"/api/batches/{batch_id}").json()
        if batch["finished"]:
            return batch
        time.sleep(0.2)
    raise AssertionError(batch)


# ---------------------------------------------------------------- choosing a mode


def test_no_mode_chosen_means_the_start_screen_and_the_real_database(app_and_engine):
    app, _ = app_and_engine
    client = TestClient(app)
    assert client.get("/api/mode").json() == {"mode": None}
    assert client.get("/api/inbox").json()["source"] == "gmail"


def test_choosing_demo_creates_a_sandbox_and_leaving_keeps_it(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    mode = client.get("/api/mode").json()
    assert mode["mode"] == "demo" and mode["demo"]["model_name"] == "gemini-demo" and mode["demo"]["uses_demo_key"]
    assert len(app.state.sandboxes.engines()) == 1
    assert client.delete("/api/mode").json() == {"mode": None}
    assert client.get("/api/mode").json() == {"mode": None}
    client.post("/api/mode", json={"mode": "demo"})  # coming back: the same sandbox
    assert len(app.state.sandboxes.engines()) == 1


# ---------------------------------------------------------------- sandbox isolation


def test_demo_runs_stay_in_the_visitors_sandbox(app_and_engine):
    app, real = app_and_engine
    alice, bob = visitor(app), visitor(app)
    run_id = run_from_inbox(alice, "01_happy_clean.pdf")["run_id"]
    run = alice.get(f"/api/runs/{run_id}").json()
    assert run["decision"] == "APPROVE"
    assert run["source"]["kind"] == "demo_inbox" and run["source"]["from_email"] == "accounts@vertexenterprises.in"
    assert run["sample"]["id"] == "01_happy_clean"

    assert bob.get(f"/api/runs/{run_id}").status_code == 404
    assert bob.get("/api/runs").json()["total"] == 0
    assert TestClient(app).get("/api/runs").json()["total"] == 0  # real mode
    assert run_count(real) == 0

    # Bob's first try of the same invoice is a first visit: approved, not "already paid"
    again = bob.get(f"/api/runs/{run_from_inbox(bob, '01_happy_clean.pdf')['run_id']}").json()
    assert again["decision"] == "APPROVE"
    # Alice's second try is a duplicate of what she approved
    second = alice.get(f"/api/runs/{run_from_inbox(alice, '01_happy_clean.pdf')['run_id']}").json()
    assert second["decision"] == "REJECT"


def test_real_mode_runs_never_appear_in_the_demo(app_and_engine):
    app, real = app_and_engine
    owner = TestClient(app)
    owner.post("/api/mode", json={"mode": "real"})
    response = owner.post("/api/runs", data={"sample_id": "01_happy_clean", "model": "gemini"})
    assert response.status_code == 200
    assert run_count(real) == 1
    assert visitor(app).get("/api/runs").json()["total"] == 0


def test_reset_resets_only_the_visitors_sandbox(app_and_engine):
    app, _ = app_and_engine
    alice, bob = visitor(app), visitor(app)
    run_from_inbox(alice, "01_happy_clean.pdf")
    run_from_inbox(bob, "07_E_wrong_gst.pdf")
    assert alice.post("/api/admin/reset-demo").json()["runs"] == 0
    assert alice.get("/api/runs").json()["total"] == 0
    assert bob.get("/api/runs").json()["total"] == 1


# ---------------------------------------------------------------- demo AI settings


def test_demo_uses_the_demo_key_and_gemini_only(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    config = client.get("/api/config").json()
    gemini, groq = config["models"]
    assert gemini["choices"] == ["gemini-demo", "gemini-2.5-flash", "gemini-3.6-flash", "gemini-3.8-flash"]
    assert not groq["configured"] and groq["choices"] == []
    assert "demo-key" not in str(config)

    run_from_inbox(client, "01_happy_clean.pdf")
    assert SEEN_KEYS[-1] == ("gemini", "demo-key", "gemini-demo")

    owner = TestClient(app)
    owner.post("/api/runs", data={"sample_id": "01_happy_clean", "model": "gemini"})
    assert SEEN_KEYS[-1] == ("gemini", "real-key", "gemini-real")  # real mode is unchanged
    assert owner.get("/api/config").json()["models"][1]["configured"]


def test_without_a_demo_key_the_demo_falls_back_to_the_main_gemini_key(tmp_path, demo_env, monkeypatch):
    monkeypatch.setenv("DEMO_GEMINI_API_KEY", "")
    monkeypatch.setenv("DEMO_GEMINI_MODEL", "")
    app, engine = make_app(tmp_path)
    with TestClient(app):
        client = visitor(app)
        assert client.get("/api/mode").json()["demo"]["uses_demo_key"] is False
        run_from_inbox(client, "01_happy_clean.pdf")
        assert SEEN_KEYS[-1] == ("gemini", "real-key", "gemini-real")
        for sandbox in app.state.sandboxes.engines():
            sandbox.dispose()
    engine.dispose()


# ---------------------------------------------------------------- demo restrictions


def test_demo_only_processes_its_inbox(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    upload = ("x.pdf", (INVOICES / "golden" / "01_happy_clean.pdf").read_bytes(), "application/pdf")
    for response in (client.post("/api/runs", files={"file": upload}),
                     client.post("/api/runs", data={"sample_id": "01_happy_clean"}),
                     client.post("/api/batches", files=[("files", upload)]),
                     client.post("/api/eval/golden", json={})):
        assert response.status_code == 403
        assert response.json()["detail"]["type"] == "demo_restricted"
    assert client.get("/api/eval/latest").json()["status"] == "never_run"


def test_demo_run_limit_per_hour(app_and_engine, monkeypatch):
    app, _ = app_and_engine
    monkeypatch.setenv("DEMO_MAX_RUNS_PER_HOUR", "2")
    client = visitor(app)
    first = run_from_inbox(client, "01_happy_clean.pdf")["run_id"]
    run_from_inbox(client, "07_E_wrong_gst.pdf")
    refused = client.post("/api/inbox/run", json={"items": [first_attachment("05_C_no_po.pdf")]})
    assert refused.status_code == 429 and refused.json()["detail"]["type"] == "demo_limit"
    assert "try again after some time" in refused.json()["detail"]["message"]
    assert client.post(f"/api/runs/{first}/retry", params={"model": "gemini"}).status_code == 429
    # the limit is per visitor, and real mode has none
    assert visitor(app).post("/api/inbox/run", json={"items": [first_attachment("05_C_no_po.pdf")]}).status_code == 200


def test_rate_limited_demo_run_is_reported_as_a_rate_limit(tmp_path, demo_env):
    app, engine = make_app(tmp_path, extract_fn=failing_extract)
    with TestClient(app):
        client = visitor(app)
        run = client.get(f"/api/runs/{run_from_inbox(client, '01_happy_clean.pdf')['run_id']}").json()
        assert run["status"] == "extraction_failed" and run["error_detail"]["type"] == "rate_limited"
        for sandbox in app.state.sandboxes.engines():
            sandbox.dispose()
    engine.dispose()


# ---------------------------------------------------------------- demo inbox


def test_inbox_lists_every_golden_invoice_and_emails_without_bills(app_and_engine):
    app, _ = app_and_engine
    inbox = visitor(app).get("/api/inbox").json()
    assert inbox["source"] == "demo" and inbox["mailbox"]
    names = sorted(a["file_name"] for m in inbox["messages"] for a in m["attachments"])
    assert names == sorted(l["file_name"] for l in GOLDEN)
    assert any(not m["attachments"] for m in inbox["messages"])
    times = [m["received_at"] for m in inbox["messages"]]
    assert times == sorted(times, reverse=True)


def test_inbox_senders_are_the_vendors_on_file(app_and_engine):
    import csv

    from app.config import REPO_ROOT

    with open(REPO_ROOT / "data" / "master" / "vendors.csv", encoding="utf-8") as f:
        emails = {row["email"] for row in csv.DictReader(f)}
    for message in demo_inbox().messages:
        if message.attachments:
            assert message.from_email in emails, message.subject
        for attachment in message.attachments:
            assert attachment.file.is_file(), attachment.path


def test_inbox_shows_what_was_processed_and_serves_the_file(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    item = first_attachment("01_happy_clean.pdf")
    run_id = run_from_inbox(client, "01_happy_clean.pdf")["run_id"]
    message = next(m for m in client.get("/api/inbox").json()["messages"] if m["id"] == item["message_id"])
    assert message["attachments"][0]["last_run"] == {"id": run_id, "status": "completed", "decision": "APPROVE"}
    pdf = client.get(f"/api/inbox/{item['message_id']}/attachments/{item['attachment_id']}")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/inbox/{item['message_id']}/attachments/nope").status_code == 404


def test_several_attachments_run_as_a_batch(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    body = run_from_inbox(client, "01_happy_clean.pdf", "07_E_wrong_gst.pdf", "05_C_no_po.pdf")
    batch = wait_for_batch(client, body["batch_id"])
    assert batch["by_decision"] == {"APPROVE": 1, "REJECT": 1, "HOLD": 1}
    assert all(i["source"]["kind"] == "demo_inbox" for i in batch["items"])


def test_real_mode_inbox_is_not_connected_yet(app_and_engine):
    app, _ = app_and_engine
    owner = TestClient(app)
    owner.post("/api/mode", json={"mode": "real"})
    assert owner.get("/api/inbox").json() == {"source": "gmail", "connected": False, "mailbox": None, "messages": []}
    assert owner.post("/api/inbox/run", json={"items": [first_attachment("01_happy_clean.pdf")]}).status_code == 409


def test_a_bad_visitor_cookie_is_ignored(app_and_engine):
    app, _ = app_and_engine
    client = TestClient(app, cookies={"ia_mode": "demo", "ia_visitor": "../../etc"})
    assert client.get("/api/mode").json() == {"mode": None}  # back to the start screen
    assert app.state.sandboxes.engines() == []


def test_unused_sandboxes_are_deleted_after_the_ttl(tmp_path):
    from app.demo.sandbox import SandboxPool
    from app.main import prepare_database

    pool = SandboxPool(prepare_database, directory=tmp_path, ttl_hours=1)
    pool.engine_for("visitor-aaaaaaaaaaaaaaaa")
    assert (tmp_path / "visitor-aaaaaaaaaaaaaaaa.db").exists()
    pool._last_used["visitor-aaaaaaaaaaaaaaaa"] -= 2 * 3600  # not used for two hours
    pool._last_sweep = 0
    pool.engine_for("visitor-bbbbbbbbbbbbbbbb")  # any visit sweeps
    assert not (tmp_path / "visitor-aaaaaaaaaaaaaaaa.db").exists()
    assert pool.engines() and len(pool.engines()) == 1
    for engine in pool.engines():
        engine.dispose()
    with pytest.raises(ValueError):
        pool.engine_for("../escape")


def test_a_demo_visitor_can_pick_another_gemini_model(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    item = first_attachment("01_happy_clean.pdf")
    assert client.post("/api/inbox/run", json={"items": [item], "model_name": "gemini-3.6-flash"}).status_code == 200
    assert SEEN_KEYS[-1] == ("gemini", "demo-key", "gemini-3.6-flash")
    refused = client.post("/api/inbox/run", json={"items": [item], "model_name": "groq-model"})
    assert refused.status_code == 400


# ---------------------------------------------------------------- vendor email in the invoice's thread


def test_vendor_email_replies_in_the_thread_the_invoice_came_in(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    item = first_attachment("07_E_wrong_gst.pdf")
    run_id = run_from_inbox(client, "07_E_wrong_gst.pdf")["run_id"]
    preview = client.get(f"/api/runs/{run_id}/email").json()
    assert preview["subject"] == "Re: Tax invoice BP/343/26"
    assert preview["recipient"] == "sales@borahpolymers.in"
    assert preview["body"].startswith("Borah Polymers") and "wrote:" in preview["body"]
    assert preview["thread"]["message_id"] == item["message_id"]

    sent = client.post(f"/api/runs/{run_id}/email").json()
    assert sent["sent"] and sent["in_thread"]
    message = next(m for m in client.get("/api/inbox").json()["messages"] if m["id"] == item["message_id"])
    assert len(message["replies"]) == 1
    assert message["replies"][0]["subject"] == "Re: Tax invoice BP/343/26" and message["replies"][0]["run_id"] == run_id
    assert all(not m["replies"] for m in client.get("/api/inbox").json()["messages"] if m["id"] != item["message_id"])


def test_an_uploaded_invoice_still_gets_a_new_email(app_and_engine):
    app, _ = app_and_engine
    owner = TestClient(app)
    run_id = owner.post("/api/runs", data={"sample_id": "07_E_wrong_gst", "model": "gemini"}).json()["run_id"]
    preview = owner.get(f"/api/runs/{run_id}/email").json()
    assert preview["subject"].startswith("Borah Polymers") and preview["thread"] is None


# ---------------------------------------------------------------- running processes


def test_running_lists_work_in_progress_and_recent_results(app_and_engine):
    app, _ = app_and_engine
    client = visitor(app)
    app.state.batch_worker.stop()  # keep the batch queued
    batch = run_from_inbox(client, "01_happy_clean.pdf", "05_C_no_po.pdf")
    single = run_from_inbox(client, "07_E_wrong_gst.pdf")["run_id"]
    now = client.get("/api/running").json()
    assert now["active"] == 1 and now["batches"][0]["id"] == batch["batch_id"] and now["batches"][0]["done"] == 0
    assert now["runs"] == []  # the single run already finished (background task)
    assert now["recent_runs"][0]["id"] == single and now["recent_runs"][0]["decision"] == "REJECT"
    assert TestClient(app).get("/api/running").json()["active"] == 0  # real mode has its own list
