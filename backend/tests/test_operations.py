"""Bulk upload queue, AI request pacing, editable settings, Gemini model choice, vendor email and PO comparison."""

import time

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import init_db
from app.extraction import pacing
from app.models import Run
from app.vendor_email import VENDOR_TEXT, compose, vendor_problems
from tests.test_api import INVOICES, client, start  # noqa: F401  (client is a fixture)


def golden(name: str) -> tuple[str, bytes, str]:
    return name, (INVOICES / "golden" / name).read_bytes(), "application/pdf"


def wait_for_batch(client, batch_id: str, timeout_s: float = 60) -> dict:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        batch = client.get(f"/api/batches/{batch_id}").json()
        if batch["finished"]:
            return batch
        time.sleep(0.2)
    raise AssertionError(f"batch not finished: {batch}")


# ---------------------------------------------------------------- bulk upload


def test_batch_runs_every_valid_file_in_order_and_lists_bad_ones(client):
    files = [("files", golden("01_happy_clean.pdf")), ("files", ("notes.txt", b"hello", "text/plain")),
             ("files", golden("07_E_wrong_gst.pdf")), ("files", golden("05_C_no_po.pdf"))]
    response = client.post("/api/batches", files=files, data={"model": "gemini"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["run_ids"]) == 3
    assert body["file_errors"][0]["file_name"] == "notes.txt"

    batch = wait_for_batch(client, body["batch_id"])
    assert batch["total"] == 3 and batch["done"] == 3
    assert [i["file_name"] for i in batch["items"]] == ["01_happy_clean.pdf", "07_E_wrong_gst.pdf", "05_C_no_po.pdf"]
    assert batch["by_decision"] == {"APPROVE": 1, "REJECT": 1, "HOLD": 1}
    rejected = next(i for i in batch["items"] if i["decision"] == "REJECT")
    assert rejected["reasons"][0]["code"] == "GST_TYPE_INVALID"
    assert client.get("/api/batches").json()[0]["id"] == body["batch_id"]


def test_a_batch_of_only_bad_files_is_refused(client):
    response = client.post("/api/batches", files=[("files", ("a.txt", b"x", "text/plain"))])
    assert response.status_code == 400 and "a.txt" in response.json()["detail"]


def test_queued_batch_runs_survive_a_restart(client):
    from app.pipeline.batch_queue import next_queued_run
    from app.pipeline.orchestrator import create_run_record, mark_interrupted_runs

    name, data, _ = golden("01_happy_clean.pdf")
    client.app.state.batch_worker.stop()  # keep it queued
    run_id = create_run_record(client.engine, name, data, "gemini", batch_id="b1")
    assert mark_interrupted_runs(client.engine) == []
    assert next_queued_run(client.engine) == (run_id, False)


# ---------------------------------------------------------------- pacing and settings


def test_ai_requests_are_spaced_by_the_gap():
    pacing.reset()
    now, slept = [100.0], []

    def sleep(s):
        slept.append(s)
        now[0] += s

    assert pacing.wait_for_turn(6, sleep, lambda: now[0]) == 0
    now[0] += 2
    assert pacing.wait_for_turn(6, sleep, lambda: now[0]) == pytest.approx(4)
    now[0] += 10
    assert pacing.wait_for_turn(6, sleep, lambda: now[0]) == 0
    assert slept == [pytest.approx(4)]
    pacing.reset()


def test_extraction_waits_for_its_turn(monkeypatch):
    from app import extraction
    from app.schemas import ExtractionResult

    waits = []
    monkeypatch.setattr(extraction, "wait_for_turn", lambda gap: waits.append(gap) or 0)

    class Fake:
        def extract(self, *args):
            return ExtractionResult(model_name="m", provider="gemini")

    monkeypatch.setattr(extraction, "get_extractor", lambda provider, settings: Fake())
    extraction.extract_document(b"%PDF", "application/pdf", "gemini", Settings(_env_file=None, ai_request_gap_s=9))
    assert waits == [9]


def test_settings_are_saved_validated_and_survive_a_demo_reset(client):
    saved = client.put("/api/admin/settings", json={"ai_request_gap_s": 12})
    assert saved.status_code == 200 and saved.json()["ai_request_gap_s"] == 12
    assert client.get("/api/config").json()["ai_request_gap_s"] == 12
    assert client.put("/api/admin/settings", json={"ai_request_gap_s": -1}).status_code == 422
    client.post("/api/admin/reset-demo")
    assert client.get("/api/admin/settings").json()["ai_request_gap_s"] == 12


# ---------------------------------------------------------------- Gemini model choice


def test_a_run_can_pick_one_of_the_configured_gemini_models(client):
    choices = next(m for m in client.get("/api/config").json()["models"] if m["id"] == "gemini")["choices"]
    assert "gemini-3.6-flash" in choices and "gemini-3.8-flash" in choices
    response = client.post("/api/runs", data={"sample_id": "01_happy_clean", "model": "gemini",
                                               "model_name": "gemini-3.8-flash"})
    run_id = response.json()["run_id"]
    with Session(client.engine) as session:
        assert session.get(Run, run_id).model == "gemini"
    bad = client.post("/api/runs", data={"sample_id": "01_happy_clean", "model": "gemini", "model_name": "gpt-9"})
    assert bad.status_code == 400 and "not one of the configured" in bad.json()["detail"]


def test_the_picked_model_reaches_the_extractor(tmp_path):
    from app.db import make_engine
    from app.main import prepare_database
    from app.pipeline.orchestrator import create_run_record, process_run
    from tests.test_api import fake_extract

    seen = []

    def spy(data, mime, provider, settings, *args, **kwargs):
        seen.append(settings.gemini_model)
        return fake_extract(data, mime, provider, settings, *args, **kwargs)

    engine = make_engine(f"sqlite:///{(tmp_path / 'm.db').as_posix()}")
    prepare_database(engine)
    name, data, _ = golden("01_happy_clean.pdf")
    run_id = create_run_record(engine, name, data, "gemini", model_name="gemini-3.6-flash")
    process_run(run_id, engine, Settings(_env_file=None, gemini_model="gemini-2.5-flash"), extract_fn=spy)
    assert seen == ["gemini-3.6-flash"]
    engine.dispose()


# ---------------------------------------------------------------- vendor email


def test_every_vendor_problem_has_vendor_facing_text_without_internal_wording():
    for code, text in VENDOR_TEXT.items():
        for part in (text.title, text.problem, text.change):
            assert "fraud" not in part.lower() and "AI " not in part, code


def test_email_subject_body_and_attachment(client):
    run = start(client, "07_E_wrong_gst")
    preview = client.get(f"/api/runs/{run['id']}/email").json()
    vendor = client.get("/api/data/vendors").json()
    legal_name = next(v["legal_name"] for v in vendor if v["vendor_id"] == run["vendor_id"])
    assert preview["subject"] == f"{legal_name} - Wrong GST type - Invoice {run['invoice_number']}"
    assert preview["body"].startswith(f"Dear {legal_name},")
    assert "Problem:" in preview["body"] and "Change needed: Please reissue the invoice charging" in preview["body"]
    assert preview["attachment_name"] == "07_E_wrong_gst.pdf"
    on_file = next(v for v in vendor if v["vendor_id"] == run["vendor_id"])
    assert preview["recipient"] == on_file["email"]


def test_approved_invoices_have_no_vendor_email(client):
    run = start(client, "01_happy_clean")
    assert client.get(f"/api/runs/{run['id']}/email").status_code == 409


def test_bank_change_email_never_asks_for_bank_details_by_email(client):
    run = start(client, "06_D_bank_change")
    body = client.get(f"/api/runs/{run['id']}/email").json()["body"]
    assert "Bank details differ" in body and "Please do not send new bank details by email" in body
    assert "fraud" not in body.lower()


def test_sending_is_a_logged_demo_send(client):
    run = start(client, "09_G_price_variance")
    response = client.post(f"/api/runs/{run['id']}/email")
    assert response.status_code == 200 and response.json()["sent"]
    assert "Price above the purchase order" in response.json()["subject"]
    client.post(f"/api/runs/{run['id']}/email")
    history = client.get(f"/api/runs/{run['id']}/email").json()["history"]
    assert [h["sent"] for h in history] == [True, True]


def test_held_invoice_email_lists_hold_problems():
    reasons = [{"code": "FIELD_NOT_VERIFIED", "severity": "HOLD", "details": {"field": "invoice_number", "value": "INV-1"}},
               {"code": "PRICE_VARIANCE_WITHIN_TOLERANCE", "severity": "INFO", "details": {}}]
    problems = vendor_problems(reasons, "HOLD")
    assert [p.title for p in problems] == ["Unclear invoice number"]
    mail = compose(vendor_name="Kosmic Cartons", invoice_number="INV-1", invoice_date=None, total=1180.0,
                   outcome="HOLD", reasons=reasons, buyer_name="Zenith Retail Pvt Ltd", recipient=None,
                   file_name="x.pdf", mime="application/pdf")
    assert mail.subject == "Kosmic Cartons - Unclear invoice number - Invoice INV-1"
    assert "we read: INV-1" in mail.body and "on hold" in mail.body
    assert mail.recipient == "(no email on file)"


# ---------------------------------------------------------------- PO comparison


def test_po_comparison_shows_the_price_difference_line_by_line(client):
    run = start(client, "09_G_price_variance")
    data = client.get(f"/api/runs/{run['id']}/po-compare").json()
    assert data["selected"] == run["po_number"]
    comparison = data["comparison"]
    assert comparison["belongs_to_vendor"] and not comparison["closed"]
    over = [l for l in comparison["lines"] if "price_over_tolerance" in l["issues"]]
    assert over and over[0]["unit_price"] > over[0]["po_line"]["unit_price"]


def test_po_comparison_for_a_missing_po_offers_the_candidates(client):
    run = start(client, "05_C_no_po")
    data = client.get(f"/api/runs/{run['id']}/po-compare").json()
    assert data["candidates"] and data["selected"] == data["candidates"][0]
    other = next((o for o in data["options"] if o != data["selected"]), None)
    if other:
        assert client.get(f"/api/runs/{run['id']}/po-compare", params={"po": other}).json()["selected"] == other
    assert client.get(f"/api/runs/{run['id']}/po-compare", params={"po": "PO-0000"}).status_code == 404


# ---------------------------------------------------------------- schema migration


def test_new_run_columns_are_added_without_losing_runs(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'old.db').as_posix()}")
    init_db(engine)
    with engine.begin() as conn:
        conn.execute(text("DROP INDEX ix_runs_batch_id"))
        conn.execute(text("ALTER TABLE runs DROP COLUMN batch_id"))
        conn.execute(text("ALTER TABLE runs DROP COLUMN use_cache"))
        conn.execute(text("INSERT INTO runs (id, created_at, file_name, file_hash, file_bytes, model, status, is_test_run, mime_type, "
                          "used_cache) VALUES ('r1', '2026-10-31 10:00:00', 'a.pdf', 'h', x'00', 'gemini', 'completed', 0, 'application/pdf', 0)"))
    init_db(engine)
    assert "batch_id" in {c["name"] for c in inspect(engine).get_columns("runs")}
    with Session(engine) as session:
        assert session.get(Run, "r1").file_name == "a.pdf"
    engine.dispose()


def test_failed_batch_invoices_retry_with_the_other_model_in_place(client):
    from tests.test_api import failing_extract, fake_extract

    client.app.state.batch_worker.extract_fn = failing_extract
    files = [("files", golden("01_happy_clean.pdf")), ("files", golden("07_E_wrong_gst.pdf"))]
    batch_id = client.post("/api/batches", files=files, data={"model": "gemini"}).json()["batch_id"]
    batch = wait_for_batch(client, batch_id)
    assert batch["failed"] == 2 and batch["by_status"] == {"extraction_failed": 2}

    client.app.state.batch_worker.extract_fn = fake_extract
    first = batch["items"][0]["id"]
    retried = client.post(f"/api/batches/{batch_id}/retry", json={"model": "groq", "run_ids": [first]})
    assert retried.status_code == 200 and len(retried.json()["run_ids"]) == 1
    batch = wait_for_batch(client, batch_id)
    assert batch["total"] == 2 and batch["failed"] == 1
    assert [(i["file_name"], i["model"], i["attempt"]) for i in batch["items"]] == [
        ("01_happy_clean.pdf", "groq", 2), ("07_E_wrong_gst.pdf", "gemini", 1)]
    assert batch["items"][0]["retry_of"] == first and batch["items"][0]["decision"] == "APPROVE"

    client.post(f"/api/batches/{batch_id}/retry", json={"model": "groq"})  # all remaining failures
    batch = wait_for_batch(client, batch_id)
    assert batch["failed"] == 0 and batch["by_decision"] == {"APPROVE": 1, "REJECT": 1}
    assert client.post(f"/api/batches/{batch_id}/retry", json={"model": "groq"}).status_code == 409


def test_description_with_extra_words_still_matches_the_po_line():
    """Golden 10's layout prints '<item> - supplied as per agreed specification and delivery schedule'."""
    from app.pipeline.po_match import description_score

    suffix = " - supplied as per agreed specification and delivery schedule"
    assert description_score("Online UPS 3 kVA" + suffix, "Online UPS 3 kVA") == 100
    assert description_score("Laptop - Intel Core i7, 16GB RAM, 1TB SSD" + suffix,
                             "Laptop - Intel Core i5, 16GB RAM, 512GB SSD") < 85


# ---------------------------------------------------------------- GSTIN misreads, approving without an invoice number


def test_a_format_impossible_gstin_misread_is_repaired_only_with_a_valid_check_digit():
    from app.pipeline.normalise import repair_gstin

    assert repair_gstin("33BUZC02645S1Z8") == "33BUZCO2645S1Z8"  # 7th character is a PAN letter: 0 -> O
    assert repair_gstin("07YNRCB166511ZX") == "07YNRCB1665I1ZX"  # 12th character is a PAN letter: 1 -> I
    assert repair_gstin("33BUZCO2645S1Z8") is None  # already valid: untouched
    assert repair_gstin("33BUZC02645S1Z9") is None  # repaired, but the check digit fails: not trusted
    assert repair_gstin("33BUZC0264") is None


def test_vendor_found_by_a_misread_gstin_is_not_a_name_only_match():
    from dataclasses import replace

    from app.pipeline.normalise import gstin_check_char
    from app.pipeline.repository import InMemoryRepository
    from app.pipeline.vendor_check import run_vendor_check
    from tests.rules_fixtures import BUYER, INTRA, invoice

    vendor_record = replace(INTRA, gstin="27AABCS1234F1Z" + gstin_check_char("27AABCS1234F1Z"))
    misread = vendor_record.gstin.replace("CS", "C5", 1)  # 6th character is a PAN letter: S read as 5
    vendor, checks = run_vendor_check(invoice(vendor_record, vendor_gstin=misread),
                                      InMemoryRepository(BUYER, [vendor_record], [], []))
    known = next(c for c in checks if c.check == "vendor_known")
    assert vendor == vendor_record and known.passed and known.code is None
    assert "which is not a valid GSTIN" in known.message and vendor_record.gstin in known.message


def test_approving_without_an_invoice_number_asks_for_it_instead_of_failing(client):
    from app.api.common import sample_labels

    sample = next(k for k, l in sample_labels().items() if l["scenario"] == "MISSING_INVOICE_NUMBER")
    run = start(client, sample)
    body = {"role": "AP clerk", "comment": "Verified"}
    refused = client.post(f"/api/holds/{run['id']}/action", json={**body, "action": "approve"})
    assert refused.status_code == 400 and "invoice number" in refused.json()["detail"]
    confirmed = client.post(f"/api/holds/{run['id']}/action",
                            json={**body, "action": "confirm_field", "payload": {"field": "invoice_number", "value": "INV-77"}})
    assert confirmed.status_code == 200
    approved = client.post(f"/api/holds/{run['id']}/action", json={**body, "action": "approve"})
    assert approved.status_code == 200 and approved.json()["result"]["decision"] == "APPROVE"
