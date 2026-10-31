"""Phase 8: real-world invoice behaviour - unusual but legitimate invoices must get sensible decisions."""

from __future__ import annotations

from app.pipeline.engine import run_rules
from app.pipeline.normalise import parse_amount, parse_date
from app.schemas import FieldVerification
from app.verification.matchers import words_to_amount
from tests.rules_fixtures import INTRA, SETTINGS, invoice, repo, verification


def outcome_and_codes(inv, ver=None):
    result = run_rules(inv, ver or verification(inv), repo(), SETTINGS)
    return result.decision.outcome, set(result.codes)


def test_unknown_vendor_no_po_other_buyer_is_hold_with_clear_reasons():
    """A real invoice from a stranger, addressed to someone else, with no PO: Hold for people, never Reject."""
    stranger = INTRA.__class__("X", "Acme Online Retail Pvt Ltd", "Acme", "29AAECA1234F1Z2", "29", "approved",
                               "Kotak", "1234567890", "KKBK0000001")
    inv = invoice(stranger, buyer_name="Rutvik Kachhadiya", buyer_gstin=None, po_reference=None)
    decision, codes = outcome_and_codes(inv)
    assert decision == "HOLD"
    assert {"VENDOR_UNKNOWN", "BUYER_MISMATCH", "PO_NOT_FOUND"} <= codes


def test_tax_inclusive_line_prices_are_not_an_arithmetic_reject():
    """Retail invoices often print line amounts that already include GST; lines then add up to the total."""
    lines = [{"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1, "unit_price": 70800.0,
              "amount": 70800.0, "tax_rate": 18}]
    inv = invoice(lines=lines, subtotal=60000.0, cgst=5400.0, sgst=5400.0, total_amount=70800.0)
    ver = verification(inv)
    ver.line_items = [FieldVerification(status="verified")]
    decision, codes = outcome_and_codes(inv, ver)
    assert decision == "APPROVE", codes  # prices compared with the PO without their GST


def test_multiple_tax_rates_on_one_invoice_approve():
    lines = [
        {"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1, "unit_price": 60000.0, "tax_rate": 18},
        {"description": "LED Monitor 24\" Full HD", "quantity": 2, "unit_price": 10000.0, "tax_rate": 5},
    ]
    decision, codes = outcome_and_codes(invoice(lines=lines))
    assert decision == "APPROVE", codes


def test_negative_discount_line_is_not_an_item_missing_from_the_po():
    lines = [
        {"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1, "unit_price": 60000.0, "tax_rate": 18},
        {"description": "Less: Festive discount", "quantity": 1, "unit_price": -1000.0, "tax_rate": 18},
    ]
    decision, codes = outcome_and_codes(invoice(lines=lines))
    assert decision == "APPROVE", codes


def test_round_off_within_one_rupee_adds_up():
    inv = invoice(round_off=0.4, total_amount=70800.4)
    assert outcome_and_codes(inv)[0] == "APPROVE"
    inv = invoice(round_off=-0.45, total_amount=70799.55)
    assert outcome_and_codes(inv)[0] == "APPROVE"


def test_total_printed_only_in_words_is_read_from_the_words():
    assert words_to_amount("Rupees Seventy Thousand Eight Hundred Only") == 70800
    assert words_to_amount("INR One Lakh Eighteen Thousand and Fifty Paise Only") == 118000.50
    assert words_to_amount("Rs. Twelve Crore Three Lakh Forty-Five Thousand Six Hundred Seventy Eight only") == 120345678
    assert words_to_amount("Total amount chargeable") is None


def test_hindi_labels_and_devanagari_digits():
    assert parse_amount("रु. 1,18,000") == 118000
    assert parse_amount("₹ १,१८,०००.००") == 118000
    assert str(parse_date("२०/१०/२०२६")) == "2026-10-20"


def test_total_only_in_words_is_verified_on_the_page():
    from app.verification.page_text import PageWords, Word
    from app.verification.verify import verify

    printed = "Amount in words : Rupees Seventy Thousand Eight Hundred Only".split()
    words = [Word(t, (0.05 + i * 0.07, 0.8, 0.1 + i * 0.07, 0.82), (1, 1)) for i, t in enumerate(printed)]
    inv = invoice()
    result = verify(inv, [PageWords(1, "text_layer", words)], SETTINGS)
    assert result.fields["total_amount"].status == "verified"
    assert "Seventy Thousand" in result.fields["total_amount"].matched_text
    assert result.fields["subtotal"].status == "not_found"  # words only stand in for the total


def test_non_invoice_document_is_rejected_with_a_readable_reason():
    """A random photo or letter: the model says document_type 'other' and finds nothing; Reject cleanly."""
    from app.schemas import ExtractedInvoice

    inv = ExtractedInvoice.model_validate({"document_type": {"value": "other", "confidence": 0.9}})
    result = run_rules(inv, verification(inv), repo(), SETTINGS)
    assert result.decision.outcome == "REJECT" and "NOT_A_TAX_INVOICE" in result.codes
    assert "a document that is not an invoice" in result.decision.summary
    assert " a other" not in result.decision.vendor_note


# ---------------------------------------------------------------- awkward files get clean messages


def _pdf(pages: int = 1, password: str | None = None) -> bytes:
    import pymupdf

    doc = pymupdf.open()
    for _ in range(pages):
        doc.new_page().insert_text((72, 72), "TAX INVOICE  Invoice No INV-1  Total 1,180.00")
    if password:
        return doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=password, owner_pw=password)
    return doc.tobytes()


def _png(size: tuple[int, int] = (200, 100)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


ZERO_PAGE_PDF = (b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
                 b"trailer<</Root 1 0 R>>\n%%EOF")


import pytest  # noqa: E402

from app.pipeline.intake import IntakeError, intake  # noqa: E402


@pytest.mark.parametrize("name, data, message", [
    ("empty.pdf", b"", "empty"),
    ("big.pdf", b"%PDF-" + b"0" * (10 * 1024 * 1024 + 1), "limit is 10 MB"),
    ("locked.pdf", _pdf(password="secret"), "password-protected"),
    ("broken.pdf", b"%PDF-1.4\nthis is not really a pdf", "could not be opened"),
    ("zero.pdf", ZERO_PAGE_PDF, "no pages"),
    ("long.pdf", _pdf(pages=21), "the limit is 20"),
    ("half.png", _png()[:-40], "could not be read"),
    ("notes.docx", b"PK\x03\x04 a word file", "Unsupported file type"),
])
def test_awkward_files_are_refused_with_a_clear_message(name, data, message):
    with pytest.raises(IntakeError, match=message):
        intake(name, data)


def test_six_page_pdf_and_any_photo_are_accepted():
    assert intake("six.pdf", _pdf(pages=6)).page_count == 6
    assert intake("photo.png", _png()).page_count == 1


def test_image_bomb_is_refused(monkeypatch):
    from PIL import Image

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)  # a 200x100 image is then "too large"
    with pytest.raises(IntakeError, match="too large"):
        intake("huge.png", _png())


# ---------------------------------------------------------------- OCR resilience (rule 14)

import pytesseract  # noqa: E402

from pathlib import Path  # noqa: E402

from app.config import Settings  # noqa: E402

SCAN = "08_F_blurry_scan.pdf"


def _run_scan(tmp_path, settings: Settings) -> dict:
    """The scanned golden invoice through the real pipeline (fake extractor), returning the stored run."""
    from sqlalchemy.orm import Session

    from app.config import REPO_ROOT
    from app.db import make_engine
    from app.main import prepare_database
    from app.models import Run
    from app.pipeline.orchestrator import create_run_record, process_run
    from tests.test_api import fake_extract

    engine = make_engine(f"sqlite:///{(tmp_path / 'ocr.db').as_posix()}")
    prepare_database(engine)
    data = (REPO_ROOT / "data" / "invoices" / "golden" / SCAN).read_bytes()
    run_id = create_run_record(engine, SCAN, data, "gemini")
    process_run(run_id, engine, settings, extract_fn=fake_extract)
    with Session(engine) as session:
        run = session.get(Run, run_id)
        out = {"status": run.status, "decision": run.decision, "codes": [r["code"] for r in run.reasons_json or []],
               "engine": (run.verification_json or {}).get("engine_used")}
    engine.dispose()
    return out


def _assert_completed_without_ocr(run: dict) -> None:
    assert run["status"] == "completed"
    assert run["engine"] == "unavailable"
    assert "OCR_UNAVAILABLE" in run["codes"]
    assert run["decision"] in ("HOLD", "APPROVE", "REJECT")


def test_tesseract_missing_run_completes_with_warning(tmp_path, monkeypatch):
    monkeypatch.setattr(pytesseract.pytesseract, "tesseract_cmd", pytesseract.pytesseract.tesseract_cmd)
    _assert_completed_without_ocr(_run_scan(tmp_path, Settings(_env_file=None, tesseract_cmd="C:/no/such/tesseract.exe")))


def test_tesseract_crash_run_completes_with_warning(tmp_path, monkeypatch):
    def crash(*args, **kwargs):
        raise pytesseract.TesseractError(-11, "segmentation fault")

    monkeypatch.setattr(pytesseract, "image_to_data", crash)
    _assert_completed_without_ocr(_run_scan(tmp_path, Settings(_env_file=None)))


def test_tesseract_timeout_run_completes_with_warning(tmp_path, monkeypatch):
    from app.verification import ocr

    seen = {}

    def slow(*args, timeout=0, **kwargs):
        seen["timeout"] = timeout
        raise RuntimeError("Tesseract process timeout")  # what pytesseract raises when `timeout` expires

    monkeypatch.setattr(pytesseract, "image_to_data", slow)
    _assert_completed_without_ocr(_run_scan(tmp_path, Settings(_env_file=None)))
    assert seen["timeout"] == ocr.pass_timeout(ocr.available_cpus())


def test_verification_disabled_run_completes_with_warning(tmp_path):
    _assert_completed_without_ocr(_run_scan(tmp_path, Settings(_env_file=None, verify_enabled=False)))


# ---------------------------------------------------------------- mixed PDFs and big photos


def test_mixed_pdf_uses_text_layer_and_ocr_per_page(monkeypatch):
    import pymupdf

    from app.verification import verify as verify_mod
    from app.verification.page_text import PageWords

    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "TAX INVOICE Invoice No INV-1 Date 20/10/2026 Total 1,180.00")
    scanned = doc.new_page()
    pix = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 400, 500), False)
    pix.set_rect(pix.irect, (255, 255, 255))
    scanned.insert_image(scanned.rect, pixmap=pix)
    ocred = []

    def fake_ocr(image, page_no, settings, **kwargs):
        ocred.append(page_no)
        return PageWords(page_no, "ocr", [])

    monkeypatch.setattr(verify_mod, "ocr_image", fake_ocr)
    pages = verify_mod.collect_page_words(doc.tobytes(), "application/pdf", Settings(_env_file=None))
    assert [p.source for p in pages] == ["text_layer", "ocr"] and ocred == [2]
    result = verify_mod.verify(invoice(invoice_number="INV-1", total_amount=1180.0), pages, Settings(_env_file=None))
    assert result.engine_used == "mixed"
    assert result.fields["invoice_number"].source == "text_layer"


def test_huge_photo_is_scaled_down_before_ocr():
    import io

    from PIL import Image

    from app.verification.verify import MAX_OCR_SIDE, ocr_page_image

    buf = io.BytesIO()
    Image.new("RGB", (8000, 6000), "white").save(buf, "JPEG")
    image = ocr_page_image(buf.getvalue(), "image/jpeg", None, 0, Settings(_env_file=None))
    assert max(image.size) == MAX_OCR_SIDE and image.size[0] / image.size[1] == pytest.approx(8000 / 6000, rel=0.01)


# ---------------------------------------------------------------- reliability: restarts, logging


def test_server_restart_marks_unfinished_runs_interrupted(tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import Session

    from app.config import REPO_ROOT
    from app.db import make_engine
    from app.main import create_app, prepare_database
    from app.models import Run
    from app.pipeline.orchestrator import EventLog, create_run_record
    from tests.test_api import fake_extract

    engine = make_engine(f"sqlite:///{(tmp_path / 'restart.db').as_posix()}")
    prepare_database(engine)
    data = (REPO_ROOT / "data" / "invoices" / "golden" / "01_happy_clean.pdf").read_bytes()
    run_id = create_run_record(engine, "01.pdf", data, "gemini")
    with Session(engine) as session:  # the old server died during extraction
        session.get(Run, run_id).status = "running"
        session.commit()
    EventLog(engine, run_id).start("extraction")

    app = create_app(frontend_dist=tmp_path, engine=engine, extract_fn=fake_extract)
    with TestClient(app) as client:  # startup = the server coming back
        run = client.get(f"/api/runs/{run_id}").json()
        assert run["status"] == "interrupted"
        assert run["error"]["type"] == "interrupted" and "Retry" in run["error"]["message"]
        types = [(e["stage"], e["type"]) for e in run["events"]]
        assert ("extraction", "stage_failed") in types and types[-1] == ("run", "run_completed")
        stream = client.get(f"/api/runs/{run_id}/events")  # the live stream ends instead of waiting forever
        assert "run_completed" in stream.text
        retry = client.post(f"/api/runs/{run_id}/retry", params={"model": "gemini"}).json()
        assert client.get(f"/api/runs/{retry['run_id']}").json()["status"] == "completed"
    engine.dispose()


def test_logs_are_json_per_run_and_never_contain_keys_or_file_contents(tmp_path, monkeypatch):
    import io
    import json
    import logging

    from app.logging_setup import LOGGER_NAME, JsonFormatter, get_logger

    secret = "AIzaSy-TEST-SECRET-KEY-123456"
    monkeypatch.setenv("GEMINI_API_KEY", secret)
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(handler)
    monkeypatch.setattr(logger, "level", logging.INFO)
    try:
        run = _run_scan(tmp_path, Settings(_env_file=None, verify_enabled=False))
        get_logger("test").warning("provider said: key=%s is invalid", secret)  # e.g. an SDK error echoing the key
    finally:
        logger.removeHandler(handler)
    lines = [json.loads(line) for line in stream.getvalue().splitlines()]
    assert run["status"] == "completed"
    messages = {l["message"] for l in lines}
    assert {"run started", "stage completed", "run completed"} <= messages
    assert all(l["run_id"] for l in lines if l["message"] in ("run started", "stage completed", "run completed"))
    assert secret not in stream.getvalue() and "[redacted]" in stream.getvalue()
    assert "%PDF" not in stream.getvalue() and "GSTIN" not in stream.getvalue()


def test_hand_written_real_world_label_is_completed_for_the_evaluations(tmp_path):
    import shutil
    import sys

    from app.config import REPO_ROOT

    sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))
    from eval_common import complete_label, ground_truth_invoice

    path = tmp_path / "shop.pdf"
    shutil.copy(REPO_ROOT / "data" / "invoices" / "golden" / "01_happy_clean.pdf", path)
    label = complete_label({"ground_truth": {"invoice_number": "INV-9", "total_amount": 2999.0,
                                             "line_items": []}, "expected_decision": "HOLD"}, path)
    assert label["invoice_id"] == "shop" and label["scan_level"] == "digital" and label["expected_decision"] == "HOLD"
    assert label["ground_truth"]["invoice_number"] == {"value": "INV-9", "printed": "INV-9"}
    assert label["ground_truth"]["po_reference"] == {"value": None, "printed": None}  # left out = not printed
    inv = ground_truth_invoice(label)
    assert inv.total_amount.value == 2999.0 and inv.document_type.value == "tax_invoice"


# ---------------------------------------------------------------- phone photos (real Tesseract)

from app.verification.ocr import tesseract_status  # noqa: E402

needs_tesseract = pytest.mark.skipif(not tesseract_status(Settings(_env_file=None)).available,
                                     reason="Tesseract not installed")


@needs_tesseract
@pytest.mark.parametrize("sample", ["01_happy_clean", "06_D_bank_change", "10_H_bad_maths"])
def test_phone_photo_gets_the_expected_decision_or_a_careful_hold(sample):
    """Perspective, glare and shadow make OCR find less; that may turn a decision into a Hold that names the
    unconfirmed fields, but never into a wrong Approve or Reject."""
    import io
    import random
    import sys

    from app.config import REPO_ROOT
    from app.pipeline.orchestrator import load_buyer, seeded_repository
    from app.verification.verify import collect_page_words, verify
    from datagen.degrade import phone_photo, rasterise

    sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))
    from eval_common import ground_truth_invoice, load_labels

    path, label = next(item for item in load_labels("golden") if item[1]["invoice_id"] == sample)
    buf = io.BytesIO()
    phone_photo(rasterise(path.read_bytes(), 200)[0][0], random.Random(sample)).save(buf, "JPEG", quality=85)
    settings = Settings(_env_file=None)
    inv = ground_truth_invoice(label)
    ver = verify(inv, collect_page_words(buf.getvalue(), "image/jpeg", settings), settings)
    result = run_rules(inv, ver, seeded_repository(load_buyer()), settings)
    assert ver.engine_used == "ocr"
    assert result.decision.outcome == label["expected_decision"] or result.decision.outcome == "HOLD", result.codes
    if result.decision.outcome != label["expected_decision"]:
        assert {"FIELD_NOT_VERIFIED", "ARITHMETIC_UNCERTAIN", "LOW_CONFIDENCE_FIELD"} & set(result.codes)


def test_every_machine_runs_every_ocr_pass_within_its_memory(monkeypatch):
    """Accuracy first: small machines run the same passes one after another instead of skipping any."""
    from app.verification import ocr

    assert ocr.parallel_passes(16, None) == 5
    assert ocr.parallel_passes(16, 512) == 2  # the server + 2 Tesseract processes stay well under 512 MB
    assert ocr.parallel_passes(16, 2048) == 5
    assert ocr.parallel_passes(0.1, 512) == 1 and ocr.parallel_passes(0.5, 512) == 1  # Render free / Starter
    assert ocr.pass_timeout(16) == 20 and ocr.pass_timeout(0.5) == 40 and ocr.pass_timeout(0.1) == 200
    real_read = Path.read_text
    fake = {"/sys/fs/cgroup/cpu.max": "10000 100000", "/sys/fs/cgroup/memory.max": "536870912"}
    monkeypatch.setattr(Path, "read_text", lambda self, *a, **k: fake[self.as_posix()] if self.as_posix() in fake
                        else real_read(self, *a, **k))
    assert ocr.available_cpus() == 0.1 and ocr.available_memory_mb() == 512  # read from the container's cgroup


def test_one_failed_ocr_pass_keeps_the_words_of_the_others(monkeypatch):
    from PIL import Image

    from app.verification import ocr

    calls = []

    def flaky(image, config, output_type, timeout):
        calls.append(config)
        if "psm 11" in config:
            raise RuntimeError("Tesseract process timeout")
        return {"text": ["INV-1"], "conf": [90], "left": [10], "top": [10], "width": [50], "height": [12],
                "block_num": [1], "par_num": [1], "line_num": [1]}

    monkeypatch.setattr(pytesseract, "image_to_data", flaky)
    page = ocr.ocr_image(Image.new("RGB", (400, 300), "white"), 1, Settings(_env_file=None))
    assert len(calls) == len(ocr.OCR_PASSES) and page.source == "ocr" and {w.text for w in page.words} == {"INV-1"}


def test_small_images_are_enlarged_for_ocr_and_dollar_amounts_parse():
    import io

    from PIL import Image

    from app.verification.verify import MIN_OCR_SIDE, ocr_page_image

    buf = io.BytesIO()
    Image.new("RGB", (465, 659), "white").save(buf, "PNG")
    image = ocr_page_image(buf.getvalue(), "image/png", None, 0, Settings(_env_file=None))
    assert max(image.size) == MIN_OCR_SIDE
    assert parse_amount("$2,338.35") == parse_amount("USD 2338.35") == parse_amount("₹2,338.35")


def test_page_words_cached_by_an_older_ocr_version_are_read_again(tmp_path, monkeypatch):
    """A user's re-upload kept showing CGST/SGST 'not found': the words came from a cache made before an OCR fix."""
    from sqlalchemy.orm import Session

    from app.db import make_engine
    from app.models import Base, PageWordsCache
    from app.verification import verify as verify_mod
    from app.verification.page_text import PageWords, Word

    engine = make_engine(f"sqlite:///{(tmp_path / 'cache.db').as_posix()}")
    Base.metadata.create_all(engine)
    stale = PageWords(1, "ocr", [Word("old", (0, 0, 0.1, 0.1), (0, 1, 1, 1), 90.0)])
    with Session(engine) as session:  # written by the previous version: no version stamp
        session.add(PageWordsCache(file_hash="h", page=1, words_json=stale.to_json()))
        session.commit()
    monkeypatch.setattr(verify_mod, "ocr_image",
                        lambda image, page_no, settings, **k: PageWords(page_no, "ocr", [Word("54.77", (0, 0, .1, .1), (0, 1, 1, 1), 90.0)]))
    png = _png((300, 400))
    first = verify_mod.collect_page_words(png, "image/png", Settings(_env_file=None), engine, "h")
    assert [w.text for w in first[0].words] == ["54.77"]  # stale entry ignored, OCR ran again
    monkeypatch.setattr(verify_mod, "ocr_image", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no OCR")))
    again = verify_mod.collect_page_words(png, "image/png", Settings(_env_file=None), engine, "h")
    assert [w.text for w in again[0].words] == ["54.77"]  # the fresh entry is reused
    engine.dispose()


def test_cord_labels_keep_printed_text_and_rupiah_value():
    import sys

    from app.config import REPO_ROOT

    sys.path.insert(0, str(REPO_ROOT / "backend" / "scripts"))
    from fetch_cord import idr_value, label_for

    assert idr_value("Rp. 111,000") == idr_value("111.000") == idr_value("111000") == 111000
    assert idr_value(None) is None
    label = label_for(7, {"sub_total": {"subtotal_price": "100,909"}, "total": {"total_price": "Rp. 111,000"}})
    assert label["invoice_id"] == "cord_test_007"
    assert label["ground_truth"]["total_amount"] == {"value": 111000.0, "printed": "Rp. 111,000"}
    assert label["ground_truth"]["subtotal"] == {"value": 100909.0, "printed": "100,909"}
    missing = label_for(9, {"sub_total": {"subtotal_price": ["36000", "36000"]}, "total": {"cashprice": "50000"}})
    assert missing["ground_truth"]["total_amount"] == {"value": None, "printed": None}  # not printed = null
    assert missing["ground_truth"]["subtotal"]["value"] == 36000.0


def test_adaptive_threshold_recovers_faint_print_on_a_shaded_page():
    """Faded thermal print on a page darkening from left to right: one global threshold loses the faint text on
    the bright side or blackens the shaded side; a local threshold keeps the text and drops the shading."""
    import numpy as np
    from PIL import Image

    from app.verification.ocr import adaptive_threshold

    shade = np.tile(np.linspace(230, 120, 300), (100, 1))  # background: bright -> dark
    page = shade.copy()
    page[40:60, 20:280] -= 30  # a faint stroke, only 30 levels darker than its surroundings
    out = np.asarray(adaptive_threshold(Image.fromarray(page.astype(np.uint8))))
    assert (out[45:55, 30:270] == 0).mean() > 0.9  # the stroke is ink everywhere along the page
    assert (out[5:30, :] == 255).mean() > 0.99 and (out[70:95, :] == 255).mean() > 0.99  # the shading is gone


def test_adaptive_pass_is_skipped_when_its_image_is_mostly_noise():
    """On a heavy, speckled scan the thresholded image is mostly black dots: the pass read nothing there but took
    ~5x longer and ~100 MB more memory, so it is skipped; clean pages keep it."""
    import numpy as np
    from PIL import Image

    from app.verification import ocr

    rng = np.random.default_rng(1)
    clean = np.full((200, 300), 235, np.uint8)
    clean[90:100, 20:280] = 120  # one line of text
    noisy = np.clip(rng.normal(180, 45, (200, 300)), 0, 255).astype(np.uint8)  # speckle everywhere
    assert "adaptive" in ocr.variants(Image.fromarray(clean), {"sharp", "adaptive"})
    assert "adaptive" not in ocr.variants(Image.fromarray(noisy), {"sharp", "adaptive"})
