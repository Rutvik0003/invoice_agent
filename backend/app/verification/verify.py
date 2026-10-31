"""Stage 3: find each AI-extracted value on the page (text layer or OCR) and apply the trust rule.

Verification never changes a value and never decides anything; it only reports, per field, whether the
value is visibly printed and where.
"""

from __future__ import annotations

import time
from typing import Literal

from PIL import Image
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import Settings
from app.extraction.pdf_utils import PDF, open_pdf, render_page_images, text_layer_pages
from app.logging_setup import get_logger
from app.models import PageWordsCache
from app.schemas import ExtractedInvoice, FieldVerification, PageVerificationInfo, VerificationResult
from app.verification.matchers import (
    Candidate,
    amount_in_words_candidates,
    candidates,
    match_amount,
    match_amount_in_words,
    match_code,
    match_date,
    match_identifier,
    match_name,
)
from app.verification.ocr import OcrUnavailable, ocr_image
from app.verification.page_text import PageWords, text_layer_words

logger = get_logger("verification")
CRITICAL_FIELDS = ("vendor_gstin", "vendor_name", "invoice_number", "invoice_date", "total_amount")
VERIFIED_FIELDS = CRITICAL_FIELDS + ("po_reference", "subtotal", "cgst", "sgst", "igst", "bank_account", "buyer_gstin")
FIELD_KIND = {
    "vendor_gstin": "code", "buyer_gstin": "code", "bank_account": "code",
    "invoice_number": "identifier", "po_reference": "identifier",
    "invoice_date": "date", "vendor_name": "name",
    "total_amount": "amount", "subtotal": "amount", "cgst": "amount", "sgst": "amount", "igst": "amount",
}


# ---------------------------------------------------------------- collecting page words


def _cached_page(engine: Engine | None, file_hash: str | None, page_no: int) -> PageWords | None:
    if engine is None or file_hash is None:
        return None
    with Session(engine) as session:
        row = session.get(PageWordsCache, (file_hash, page_no))
        return PageWords.from_json(row.words_json) if row else None


def _store_page(engine: Engine | None, file_hash: str | None, page: PageWords) -> None:
    if engine is None or file_hash is None or page.source == "unavailable":
        return
    with Session(engine) as session:
        session.merge(PageWordsCache(file_hash=file_hash, page=page.page, words_json=page.to_json()))
        session.commit()


MAX_OCR_SIDE = 3508  # pixels on the long side = an A4 page at 300 DPI; more costs time and memory, not accuracy


def ocr_page_image(file_bytes: bytes, mime: str, pdf, index: int, settings: Settings) -> Image.Image:
    """The page as an image for OCR, at OCR_DPI but never larger than MAX_OCR_SIDE (large pages, 48 MP photos)."""
    if pdf is not None:
        rect = pdf[index].rect
        dpi = min(settings.ocr_dpi, int(MAX_OCR_SIDE * 72 / max(rect.width, rect.height, 1)))
        pix = pdf[index].get_pixmap(dpi=dpi)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image = render_page_images(file_bytes, mime, settings.ocr_dpi)[0]
    if max(image.size) > MAX_OCR_SIDE:
        image.thumbnail((MAX_OCR_SIDE, MAX_OCR_SIDE), Image.LANCZOS)
    return image


def collect_page_words(file_bytes: bytes, mime: str, settings: Settings, engine: Engine | None = None,
                       file_hash: str | None = None) -> list[PageWords]:
    """Words for every page: text layer where it exists, Tesseract OCR otherwise (cached by file hash + page)."""
    has_text = text_layer_pages(file_bytes, mime)
    pdf = open_pdf(file_bytes) if mime == PDF else None
    all_words = settings.model_copy(update={"ocr_min_word_conf": 0})  # cache every word; filter on the way out
    pages = []
    for index, text_layer in enumerate(has_text):
        page_no = index + 1
        cached = _cached_page(engine, file_hash, page_no)
        if cached is not None:
            pages.append(_confident(cached, settings))
            continue
        if text_layer:
            page = text_layer_words(pdf[index], page_no)
        else:
            try:
                page = ocr_image(ocr_page_image(file_bytes, mime, pdf, index, settings), page_no, all_words)
            except OcrUnavailable as exc:
                page = PageWords(page_no, "unavailable", error=str(exc))
            except Exception as exc:  # noqa: BLE001 - rule 14: OCR problems never crash a run
                page = PageWords(page_no, "unavailable", error=f"{type(exc).__name__}: {exc}")
            if page.source == "unavailable":
                logger.warning("OCR unavailable for a page", extra={"file_hash": file_hash, "page": page_no,
                                                                     "error": page.error})
        _store_page(engine, file_hash, page)
        pages.append(_confident(page, settings))
    return pages


def _confident(page: PageWords, settings: Settings) -> PageWords:
    """Drop OCR words below OCR_MIN_WORD_CONF (text-layer words have no confidence and are always kept)."""
    if page.source != "ocr":
        return page
    kept = [w for w in page.words if w.conf is None or w.conf >= settings.ocr_min_word_conf]
    return PageWords(page.page, page.source, kept, page.error)


# ---------------------------------------------------------------- matching


def score_candidate(field: str, value: object, cand: Candidate, settings: Settings) -> int | None:
    kind = FIELD_KIND[field]
    if kind == "amount":
        return match_amount(float(value), cand.text, ocr=cand.source == "ocr")
    if kind == "identifier":
        return match_identifier(str(value), cand.text, settings.verify_fuzzy_min)
    if kind == "code":
        return match_code(str(value), cand.text, allow_one_difference=cand.source == "ocr")
    if kind == "date":
        return match_date(str(value), cand.text)
    return match_name(str(value), cand.text)


def best_match(field: str, value: object, cands: list[Candidate], settings: Settings) -> Candidate | None:
    """Highest score wins; ties go to the run whose length best fits the value (longest for typed values,
    so 'Rs. 1,18,000/-' beats '1,18,000/-'), then to the first on the page."""
    best, best_key = None, None
    for cand in cands:
        score = score_candidate(field, value, cand, settings)
        if score is None:
            continue
        if FIELD_KIND[field] == "name":
            fit = -abs(len(cand.text) - len(str(value)))
        else:
            fit = cand.n_words
        key = (score, fit, -cand.page, -cand.bbox[1], -cand.bbox[0])
        if best_key is None or key > best_key:
            best, best_key = cand, key
    return best


def total_in_words(value: object, pages: list[PageWords]) -> Candidate | None:
    """Some invoices print the total only in words ("Rupees Seventy Thousand Eight Hundred Only"):
    the total then counts as found if a printed line, read as words, is the same amount (± ₹1)."""
    try:
        target = float(value)
    except (TypeError, ValueError):
        return None
    return next((c for c in amount_in_words_candidates(pages) if match_amount_in_words(target, c.text)), None)


def field_value(invoice: ExtractedInvoice, name: str) -> object:
    return getattr(invoice, name).value


def verify(invoice: ExtractedInvoice, pages: list[PageWords], settings: Settings) -> VerificationResult:
    """Look for every verified field's value on the pages -> VerificationResult (CLAUDE.md §7)."""
    started = time.monotonic()
    usable = [p for p in pages if p.source != "unavailable"]
    some_unavailable = len(usable) < len(pages) or not pages
    cands = candidates(usable)
    fields = {}
    for name in VERIFIED_FIELDS:
        value = field_value(invoice, name)
        if value is None or value == "":
            fields[name] = FieldVerification(status="not_applicable")
            continue
        match = best_match(name, value, cands, settings)
        if match is None and name == "total_amount":
            match = total_in_words(value, usable)
        if match is not None:
            fields[name] = FieldVerification(
                status="verified", source=match.source, page=match.page,
                bbox=[round(c, 5) for c in match.bbox], matched_text=match.text, ocr_word_conf=match.conf,
            )
        else:
            fields[name] = FieldVerification(status="unavailable" if some_unavailable else "not_found")
    line_items = []
    for line in invoice.line_items:
        if line.amount is None:
            line_items.append(FieldVerification(status="not_applicable"))
            continue
        match = best_match("subtotal", line.amount, cands, settings)  # an amount, matched like any other
        line_items.append(FieldVerification(
            status="verified", source=match.source, page=match.page, bbox=[round(c, 5) for c in match.bbox],
            matched_text=match.text, ocr_word_conf=match.conf,
        ) if match else FieldVerification(status="unavailable" if some_unavailable else "not_found"))
    sources = {p.source for p in usable}
    if not usable:
        engine_used = "unavailable"
    elif len(sources) > 1 or some_unavailable:
        engine_used = "mixed"
    else:
        engine_used = sources.pop()
    return VerificationResult(
        engine_used=engine_used,
        pages=[PageVerificationInfo(page=p.page, source=p.source, word_count=len(p.words), mean_ocr_conf=p.mean_conf)
               for p in pages],
        fields=fields,
        line_items=line_items,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def unavailable_result(invoice: ExtractedInvoice, page_count: int) -> VerificationResult:
    """Verification disabled or impossible: every printed field is 'unavailable' (rule 14)."""
    fields = {name: FieldVerification(status="not_applicable" if field_value(invoice, name) in (None, "") else "unavailable")
              for name in VERIFIED_FIELDS}
    return VerificationResult(engine_used="unavailable",
                              pages=[PageVerificationInfo(page=i + 1, source="unavailable", word_count=0)
                                     for i in range(page_count)],
                              fields=fields,
                              line_items=[FieldVerification(status="not_applicable" if l.amount is None else "unavailable")
                                          for l in invoice.line_items])


# ---------------------------------------------------------------- trust rule (used by Stage 4+)

Trust = Literal["trusted", "absent", "FIELD_NOT_VERIFIED", "LOW_CONFIDENCE_FIELD"]


def field_trust(name: str, invoice: ExtractedInvoice, verification: VerificationResult, threshold: float) -> list[Trust]:
    """CLAUDE.md §6 Stage 3 trust rule for one field.

    Trusted if verified on the page, or if verification was unavailable and the model is confident.
    Not found on the page -> FIELD_NOT_VERIFIED; not verified and model confidence below the threshold
    -> LOW_CONFIDENCE_FIELD. Independent verification overrides the model's own low self-rating.
    """
    status = verification.fields.get(name)
    value = field_value(invoice, name)
    if value is None or value == "":
        return ["absent"]
    if status is not None and status.status == "verified":
        return ["trusted"]
    reasons: list[Trust] = []
    if status is not None and status.status == "not_found":
        reasons.append("FIELD_NOT_VERIFIED")
    if getattr(invoice, name).confidence < threshold:
        reasons.append("LOW_CONFIDENCE_FIELD")
    return reasons or ["trusted"]


def is_trusted(name: str, invoice: ExtractedInvoice, verification: VerificationResult, threshold: float) -> bool:
    return field_trust(name, invoice, verification, threshold) == ["trusted"]


def doubtful_fields(invoice: ExtractedInvoice, verification: VerificationResult, threshold: float,
                    names: tuple[str, ...] = CRITICAL_FIELDS) -> list[tuple[str, str]]:
    """(field, reason code) for every printed field among `names` that is not trusted."""
    out = []
    for name in names:
        for reason in field_trust(name, invoice, verification, threshold):
            if reason not in ("trusted", "absent"):
                out.append((name, reason))
    return out
