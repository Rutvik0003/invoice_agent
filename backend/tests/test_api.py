"""End-to-end API tests: real intake, verification and rules; a fake extractor stands in for the AI (no network)."""

import hashlib
import json
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.common import sample_labels
from app.config import REPO_ROOT
from app.db import make_engine
from app.main import create_app
from app.models import POLine
from app.schemas import ExtractionError, ExtractionResult

sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))
from eval_rules import invoice_from_label  # noqa: E402

INVOICES = REPO_ROOT / "data" / "invoices"
GOLDEN = [l for l in sample_labels().values() if l["set_name"] == "golden"]


def _labels_by_hash() -> dict[str, dict]:
    out = {}
    for label in sample_labels().values():
        data = (INVOICES / label["set_name"] / label["file_name"]).read_bytes()
        out[hashlib.sha256(data).hexdigest()] = label
    return out


BY_HASH = _labels_by_hash()


def fake_extract(data, mime, provider, settings, engine=None, use_cache=False, page_images=None) -> ExtractionResult:
    """Returns the label's ground truth as if the model had read it perfectly (confidence from the label)."""
    label = BY_HASH[hashlib.sha256(data).hexdigest()]
    return ExtractionResult(invoice=invoice_from_label(label), model_name=f"fake-{provider}", provider=provider,
                            latency_ms=5, cached=use_cache)


def failing_extract(data, mime, provider, settings, engine=None, use_cache=False, page_images=None) -> ExtractionResult:
    return ExtractionResult(model_name="fake", provider=provider, error=ExtractionError(
        type="rate_limited", message="Gemini rate limit reached (free tier).", detail="429"))


@pytest.fixture
def client(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'api.db').as_posix()}")
    app = create_app(frontend_dist=tmp_path, engine=engine, extract_fn=fake_extract)
    with TestClient(app) as test_client:  # runs startup: create tables + seed master data
        test_client.engine = engine
        yield test_client
    engine.dispose()


def start(client, sample_id: str, model: str = "gemini") -> dict:
    response = client.post("/api/runs", data={"sample_id": sample_id, "model": model})
    assert response.status_code == 200, response.text
    return client.get(f"/api/runs/{response.json()['run_id']}").json()  # background task already ran


def po_lines(engine, po_number: str) -> list[tuple]:
    with Session(engine) as session:
        return [(l.line_no, float(l.qty_billed)) for l in session.query(POLine).filter_by(po_number=po_number)]


def test_every_golden_invoice_end_to_end(client):
    from app.pipeline.evaluation import judge

    results = {}
    for label in GOLDEN:
        run = start(client, label["invoice_id"])
        codes = [r["code"] for r in run["reasons"]]
        ok, problems = judge(label, run["decision"], codes)
        results[label["invoice_id"]] = (run["status"], run["decision"], problems)
        assert run["status"] == "completed" and ok, (label["invoice_id"], run["decision"], problems)
    assert len(results) == 12


def test_events_arrive_in_order_over_sse(client):
    run = start(client, "01_happy_clean")
    with client.stream("GET", f"/api/runs/{run['id']}/events") as stream:
        body = "".join(stream.iter_text())
    events = [json.loads(line[5:].strip()) for line in body.splitlines() if line.startswith("data:")]
    ids = [e["id"] for e in events]
    assert ids == sorted(ids) and events[-1]["type"] == "run_completed"
    started = [e["stage"] for e in events if e["type"] == "stage_started"]
    assert started == ["intake", "extraction", "verification", "self_check", "vendor_duplicate", "po_match",
                       "amount_match", "decision"]
    fields = [e["payload"] for e in events if e["stage"] == "verification" and e["type"] == "check_result"]
    total = next(f for f in fields if f["field"] == "total_amount")
    assert total["status"] == "verified" and total["source"] == "text_layer" and len(total["bbox"]) == 4
    # reconnecting with Last-Event-ID only replays what came after it
    with client.stream("GET", f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": str(ids[-3])}) as stream:
        replay = [json.loads(l[5:].strip()) for l in "".join(stream.iter_text()).splitlines() if l.startswith("data:")]
    assert [e["id"] for e in replay] == ids[-2:]


def test_approving_the_same_invoice_twice_is_a_duplicate_and_reset_restores_it(client):
    label = sample_labels()["01_happy_clean"]
    po = label["true_po_number"]
    seeded = po_lines(client.engine, po)
    first = start(client, "01_happy_clean")
    assert first["decision"] == "APPROVE" and first["rules"]["ledger_applied"]
    assert po_lines(client.engine, po) != seeded
    history = client.get("/api/data/history").json()
    assert any(h["from_run"] and h["invoice_number"] == label["ground_truth"]["invoice_number"]["value"] for h in history)
    second = start(client, "01_happy_clean")
    codes = {r["code"] for r in second["reasons"]}
    assert second["decision"] == "REJECT" and {"DUPLICATE_FILE", "DUPLICATE_INVOICE_NUMBER"} <= codes
    reset = client.post("/api/admin/reset-demo").json()
    assert reset["reset"] and client.get("/api/runs").json()["total"] == 0
    assert po_lines(client.engine, po) == seeded
    assert start(client, "01_happy_clean")["decision"] == "APPROVE"


def test_extraction_failure_stops_cleanly_and_retry_links_runs(client):
    client.app.state.extract_fn = failing_extract
    failed = start(client, "02_happy_tolerance")
    assert failed["status"] == "extraction_failed" and failed["decision"] is None
    assert failed["error"]["type"] == "rate_limited"
    assert [e["type"] for e in failed["events"]][-2:] == ["stage_failed", "run_completed"]
    client.app.state.extract_fn = fake_extract
    retry = client.post(f"/api/runs/{failed['id']}/retry", params={"model": "groq"}).json()
    retried = client.get(f"/api/runs/{retry['run_id']}").json()
    assert retried["retry_of"] == failed["id"] and retried["model"] == "groq" and retried["decision"] == "APPROVE"
    assert client.get(f"/api/runs/{failed['id']}").json()["retries"] == [retry["run_id"]]


def test_bad_uploads_get_clear_errors(client):
    assert client.post("/api/runs", files={"file": ("empty.pdf", b"", "application/pdf")}).status_code == 400
    response = client.post("/api/runs", files={"file": ("notes.txt", b"hello world", "text/plain")})
    assert response.status_code == 400 and "PDF, PNG or JPG" in response.json()["detail"]
    assert client.post("/api/runs", files={"file": ("broken.pdf", b"%PDF-1.4 garbage", "application/pdf")}).status_code == 400
    assert client.post("/api/runs", data={}).status_code == 400


def test_upload_a_file(client):
    data = (INVOICES / "golden" / "06_D_bank_change.pdf").read_bytes()
    response = client.post("/api/runs", files={"file": ("invoice.pdf", data, "application/pdf")}, data={"model": "gemini"})
    run = client.get(f"/api/runs/{response.json()['run_id']}").json()
    assert run["file_name"] == "invoice.pdf" and run["decision"] == "HOLD"
    assert "BANK_DETAILS_MISMATCH" in {r["code"] for r in run["reasons"]}
    page = client.get(f"/api/runs/{run['id']}/pages/1.png")
    assert page.status_code == 200 and page.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/runs/{run['id']}/pages/9.png").status_code == 404


def test_hold_queue_actions(client):
    held = start(client, "05_C_no_po")  # PO_INFERRED -> Hold for the buyer
    assert held["decision"] == "HOLD" and held["po_number"] == sample_labels()["05_C_no_po"]["true_po_number"]
    holds = client.get("/api/holds").json()
    assert [i["id"] for i in holds["items"]] == [held["id"]] and "Buyer" in holds["by_role"]
    url = f"/api/holds/{held['id']}/action"
    assert client.post(url, json={"action": "approve", "role": "Buyer", "comment": ""}).status_code == 422
    assert client.post(url, json={"action": "assign_po", "role": "Buyer", "comment": "x",
                                  "payload": {"po_number": "PO-2026-9999"}}).status_code == 400
    confirm = client.post(url, json={"action": "confirm_field", "role": "AP clerk", "comment": "checked the paper copy",
                                     "payload": {"field": "invoice_date", "value": "2026-10-20"}})
    assert confirm.status_code == 200 and confirm.json()["run"]["status"] == "completed"
    po = held["po_number"]
    before = po_lines(client.engine, po)
    approve = client.post(url, json={"action": "approve", "role": "Buyer", "comment": "Confirmed PO with the store manager"})
    assert approve.status_code == 200 and approve.json()["result"]["ledger_applied"]
    assert po_lines(client.engine, po) != before
    detail = client.get(f"/api/runs/{held['id']}").json()
    assert detail["status"] == "resolved_by_human" and detail["decision"] == "APPROVE"
    assert [a["action"] for a in detail["hold_actions"]] == ["confirm_field", "approve"]
    assert client.post(url, json={"action": "reject", "role": "Buyer", "comment": "again"}).status_code == 409
    assert client.get("/api/holds").json()["items"] == []
    assert len(client.get("/api/holds", params={"state": "resolved"}).json()["items"]) == 1


def test_test_suite_is_sandboxed(client):
    first = start(client, "01_happy_clean")  # a demo approval changes the ledger...
    assert first["decision"] == "APPROVE"
    po = sample_labels()["01_happy_clean"]["true_po_number"]
    after_demo = po_lines(client.engine, po)
    response = client.post("/api/eval/golden", json={"use_cache": True, "delay_s": 0})
    assert response.status_code == 200
    suite = client.get("/api/eval/latest").json()
    assert suite["status"] == "done" and suite["done"] == 12
    assert suite["passed"] == 12, [(i["sample_id"], i.get("problems")) for i in suite["items"] if not i.get("passed")]
    assert po_lines(client.engine, po) == after_demo  # ...but the test suite never touches it
    assert client.get("/api/runs").json()["total"] == 1  # test runs are hidden by default
    assert client.get("/api/runs", params={"include_test": True}).json()["total"] == 13


def test_lists_filters_stats_and_data(client):
    start(client, "01_happy_clean")
    start(client, "07_E_wrong_gst")
    start(client, "12_J_unapproved_vendor", model="groq")
    runs = client.get("/api/runs").json()
    assert runs["total"] == 3
    assert [r["decision"] for r in client.get("/api/runs", params={"decision": "reject"}).json()["items"]] == ["REJECT"]
    assert client.get("/api/runs", params={"model": "groq"}).json()["total"] == 1
    assert client.get("/api/runs", params={"search": "VE0393"}).json()["total"] == 1
    assert client.get("/api/runs", params={"page_size": 2, "page": 2}).json()["items"].__len__() == 1
    stats = client.get("/api/stats").json()
    assert stats["by_decision"] == {"APPROVE": 1, "REJECT": 1, "HOLD": 1}
    assert stats["decided_automatically"] == 2 and stats["ap_minutes_saved"] == 16 and "8 minutes" in stats["ap_minutes_assumption"]
    assert stats["fields_verified_pct"] > 90
    assert len(client.get("/api/data/vendors").json()) == 40
    pos = client.get("/api/data/pos").json()
    assert all({"billed_value", "remaining_value", "lines", "invoices"} <= set(p) for p in pos)
    assert len(client.get("/api/samples").json()) == len(sample_labels())


def test_config_and_ledger_snapshot(client):
    config = client.get("/api/config").json()
    assert {m["id"] for m in config["models"]} == {"gemini", "groq"} and config["confidence_threshold"] == 0.8
    run = start(client, "01_happy_clean")
    change = run["rules"]["ledger_change"]
    assert change["po_number"] == run["po_number"] and change["billed_after"] > change["billed_before"]
    assert all(line["billed_after"] > line["billed_before"] for line in change["lines"])
    # reopening a finished run's stream after its last event sends nothing more and ends (no hanging connection)
    with client.stream("GET", f"/api/runs/{run['id']}/events", headers={"Last-Event-ID": "999999"}) as stream:
        assert "".join(stream.iter_text()).count("data:") == 0
