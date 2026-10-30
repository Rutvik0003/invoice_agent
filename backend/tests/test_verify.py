"""Tests for Stage 3 verify() and the trust rule, using fixture word lists (no OCR, no AI)."""

import pytest

from app.config import Settings
from app.schemas import ExtractedInvoice, VerificationResult
from app.verification import ocr as ocr_module
from app.verification.page_text import PageWords, Word
from app.verification.verify import (
    VERIFIED_FIELDS,
    collect_page_words,
    doubtful_fields,
    field_trust,
    is_trusted,
    unavailable_result,
    verify,
)

SETTINGS = Settings(_env_file=None)


def line(y: float, *texts: str, source_conf: float | None = None, line_id: int = 0) -> list[Word]:
    """Words laid out left to right on one line."""
    words, x = [], 0.05
    for text in texts:
        width = 0.012 * len(text)
        words.append(Word(text, (x, y, x + width, y + 0.012), (line_id,), source_conf))
        x += width + 0.01
    return words


def page(source: str = "text_layer", conf: float | None = None) -> PageWords:
    words = (
        line(0.05, "Sharma", "IT", "Solutions", "Pvt", "Ltd", source_conf=conf, line_id=1)
        + line(0.08, "GSTIN:", "27", "AABCD", "1234", "F1Z5", source_conf=conf, line_id=2)
        + line(0.12, "Invoice", "No.", "INV", "/", "0881", source_conf=conf, line_id=3)
        + line(0.14, "Dated", "05-Mar-26", source_conf=conf, line_id=4)
        + line(0.16, "Buyer", "GSTIN:", "27RHRCZ5469N1Z7", source_conf=conf, line_id=5)
        + line(0.18, "Your", "Order", "No.", "PO/2026/1050", source_conf=conf, line_id=6)
        + line(0.60, "Sub", "Total", "1,00,000.00", source_conf=conf, line_id=7)
        + line(0.62, "CGST", "@", "9%", "9,000.00", source_conf=conf, line_id=8)
        + line(0.64, "SGST", "@", "9%", "9,000.00", source_conf=conf, line_id=9)
        + line(0.66, "Total", "Rs.", "1,18,000/-", source_conf=conf, line_id=10)
        + line(0.80, "A/c", "No:", "50100123456789", source_conf=conf, line_id=11)
    )
    return PageWords(1, source, words)


def invoice(**overrides) -> ExtractedInvoice:
    values = {
        "vendor_name": "Sharma IT Solutions Pvt. Ltd.", "vendor_gstin": "27AABCD1234F1Z5", "invoice_number": "INV/0881",
        "invoice_date": "2026-03-05", "po_reference": "PO-2026-1050", "subtotal": 100000.0, "cgst": 9000.0,
        "sgst": 9000.0, "igst": None, "total_amount": 118000.0, "bank_account": "50100123456789",
        "buyer_gstin": "27RHRCZ5469N1Z7",
    }
    values.update(overrides)
    data = {k: {"value": v, "confidence": 0.95} for k, v in values.items()}
    return ExtractedInvoice.model_validate(data)


def test_every_true_value_is_verified_on_the_text_layer():
    result = verify(invoice(), [page()], SETTINGS)
    assert result.engine_used == "text_layer"
    statuses = {k: v.status for k, v in result.fields.items()}
    assert statuses.pop("igst") == "not_applicable"
    assert set(statuses.values()) == {"verified"}, statuses
    total = result.fields["total_amount"]
    assert total.matched_text == "Rs. 1,18,000/-" and total.page == 1 and total.source == "text_layer"
    assert result.fields["invoice_number"].matched_text == "INV / 0881"
    assert result.fields["vendor_gstin"].matched_text == "27 AABCD 1234 F1Z5"


@pytest.mark.parametrize(
    "field, wrong",
    [("total_amount", 181000.0), ("total_amount", 118100.0), ("invoice_number", "INV/0818"),
     ("vendor_gstin", "27AABCE1234F1Z5"), ("invoice_date", "2026-03-06"), ("bank_account", "50100123456798")],
)
def test_hallucinated_values_are_not_found(field, wrong):
    result = verify(invoice(**{field: wrong}), [page()], SETTINGS)
    assert result.fields[field].status == "not_found"


def test_ocr_allows_one_character_in_gstin_but_text_layer_does_not():
    ocr_page = page("ocr", conf=88.0)
    for word in ocr_page.words:
        if word.text == "27RHRCZ5469N1Z7":
            word.text = "27RHRCZ5469NIZ7"  # OCR read 1 as I
    result = verify(invoice(), [ocr_page], SETTINGS)
    assert result.fields["buyer_gstin"].status == "verified"
    assert result.fields["buyer_gstin"].ocr_word_conf == 88.0
    text_page = page()
    for word in text_page.words:
        if word.text == "27RHRCZ5469N1Z7":
            word.text = "27RHRCZ5469NIZ7"
    assert verify(invoice(), [text_page], SETTINGS).fields["buyer_gstin"].status == "not_found"


def test_unavailable_pages_make_missing_fields_unavailable_not_not_found():
    broken = PageWords(2, "unavailable", error="tesseract crashed")
    result = verify(invoice(total_amount=999.0), [page(), broken], SETTINGS)
    assert result.engine_used == "mixed"
    assert result.fields["total_amount"].status == "unavailable"
    assert result.fields["invoice_number"].status == "verified"
    none = verify(invoice(), [PageWords(1, "unavailable")], SETTINGS)
    assert none.engine_used == "unavailable"
    assert {f.status for f in none.fields.values()} == {"unavailable", "not_applicable"}


def test_trust_rule():
    threshold = 0.8
    inv = invoice(total_amount=181000.0)
    result = verify(inv, [page()], SETTINGS)
    assert field_trust("total_amount", inv, result, threshold) == ["FIELD_NOT_VERIFIED"]
    assert is_trusted("invoice_number", inv, result, threshold)
    # verified overrides the model's own low confidence
    low = inv.model_copy(update={"invoice_number": inv.invoice_number.model_copy(update={"confidence": 0.3})})
    assert is_trusted("invoice_number", low, result, threshold)
    # OCR unavailable: fall back to model confidence
    unavailable = unavailable_result(low, 1)
    assert field_trust("invoice_number", low, unavailable, threshold) == ["LOW_CONFIDENCE_FIELD"]
    assert is_trusted("vendor_gstin", low, unavailable, threshold)
    # not found AND low confidence -> both reasons
    both = low.model_copy(update={"invoice_number": low.invoice_number.model_copy(update={"value": "XX/1"})})
    assert field_trust("invoice_number", both, verify(both, [page()], SETTINGS), threshold) == [
        "FIELD_NOT_VERIFIED", "LOW_CONFIDENCE_FIELD"]
    assert ("total_amount", "FIELD_NOT_VERIFIED") in doubtful_fields(inv, result, threshold)
    assert field_trust("igst", inv, result, threshold) == ["absent"]


def test_verification_result_has_every_field():
    result = verify(invoice(), [page()], SETTINGS)
    assert set(result.fields) == set(VERIFIED_FIELDS)
    assert VerificationResult.model_validate(result.model_dump()) == result


def test_ocr_crash_never_crashes_collection(monkeypatch):
    """Rule 14: a Tesseract failure marks the page unavailable and the run continues."""
    from io import BytesIO

    from PIL import Image

    def boom(*args, **kwargs):
        raise RuntimeError("tesseract exploded")

    monkeypatch.setattr(ocr_module.pytesseract, "image_to_data", boom)
    buffer = BytesIO()
    Image.new("RGB", (400, 300), "white").save(buffer, "PNG")
    pages = collect_page_words(buffer.getvalue(), "image/png", SETTINGS)
    assert pages[0].source == "unavailable" and "tesseract exploded" in pages[0].error
    assert verify(invoice(), pages, SETTINGS).engine_used == "unavailable"


def test_real_tesseract_reads_a_rendered_invoice_line():
    """End-to-end OCR on a synthetic image (skipped where Tesseract is not installed)."""
    from PIL import Image, ImageDraw, ImageFont

    if not ocr_module.tesseract_status(SETTINGS).available:
        pytest.skip("Tesseract not installed")
    image = Image.new("RGB", (1400, 260), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("arial.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    draw.text((40, 40), "Invoice No: INV/0881", fill="black", font=font)
    draw.text((40, 140), "Total Rs. 1,18,000/-", fill="black", font=font)
    page = ocr_module.ocr_image(image, 1, SETTINGS)
    result = verify(invoice(), [page], SETTINGS)
    assert result.fields["invoice_number"].status == "verified"
    assert result.fields["total_amount"].status == "verified"
    assert result.fields["total_amount"].source == "ocr"
