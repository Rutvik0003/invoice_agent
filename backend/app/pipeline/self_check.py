"""Stage 4: clean up and self-check the invoice on its own (no master data needed except the buyer)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz

from app.config import Settings
from app.pipeline.normalise import gstin_state, normalise_code, normalise_name, parse_date, to_decimal
from app.pipeline.reason_codes import ReasonCode, inr, passed, raised, show
from app.pipeline.po_match import lines_include_tax, total_tax
from app.pipeline.repository import BuyerRecord
from app.schemas import CheckEvidence, CheckResult, ExtractedInvoice, VerificationResult
from app.verification.verify import CRITICAL_FIELDS, doubtful_fields, field_trust

STAGE = "self_check"
ONE_RUPEE = Decimal("1.00")
GST_2_0 = date(2025, 9, 22)
RATES_FROM_GST_2_0 = (Decimal("0"), Decimal("0.25"), Decimal("3"), Decimal("5"), Decimal("18"), Decimal("40"))
RATES_BEFORE_GST_2_0 = (Decimal("0"), Decimal("0.25"), Decimal("3"), Decimal("5"), Decimal("12"), Decimal("18"), Decimal("28"))
TAX_FIELDS = ("cgst", "sgst", "igst")


def invoice_date(inv: ExtractedInvoice) -> date | None:
    return parse_date(inv.invoice_date.value) or parse_date(inv.invoice_date.printed)


def amount(inv: ExtractedInvoice, name: str) -> Decimal:
    """A money field as Decimal, absent = 0."""
    return to_decimal(getattr(inv, name).value) or Decimal("0.00")


def _verification_status(ver: VerificationResult, name: str) -> str | None:
    field = ver.fields.get(name)
    return field.status if field else None


DOC_TYPE_LABELS = {"proforma": "proforma invoice", "purchase_order": "purchase order copy",
                   "other": "document that is not an invoice (for example a receipt, letter or photo)"}


def check_document_type(inv: ExtractedInvoice) -> CheckResult:
    """Only a tax invoice can be paid; quotations, proformas, credit notes, challans and PO copies are rejected."""
    doc_type = inv.document_type.value
    if doc_type in (None, "tax_invoice"):
        return passed(STAGE, "document_type", "The document is a tax invoice.")
    label = DOC_TYPE_LABELS.get(doc_type, doc_type.replace("_", " "))
    return raised(STAGE, "document_type", ReasonCode.NOT_A_TAX_INVOICE,
                  CheckEvidence(invoice_field="document_type", invoice_value=doc_type), doc_type=label)


def check_required_fields(inv: ExtractedInvoice) -> CheckResult:
    """Vendor GSTIN and name, invoice number and date, total and at least one line item must be printed."""
    missing = [name for name in CRITICAL_FIELDS if getattr(inv, name).value in (None, "")]
    if not inv.line_items:
        missing.append("line_items")
    if not missing:
        return passed(STAGE, "required_fields", "All required fields are present.")
    return raised(STAGE, "required_fields", ReasonCode.MISSING_REQUIRED_FIELD,
                  CheckEvidence(invoice_field=", ".join(missing)), fields=", ".join(missing))


def check_doubtful_fields(inv: ExtractedInvoice, ver: VerificationResult, threshold: float) -> list[CheckResult]:
    """Every critical field must be confirmed on the page, or (when OCR is unavailable) read with high confidence."""
    out = []
    for name, reason in doubtful_fields(inv, ver, threshold):
        field = getattr(inv, name)
        evidence = CheckEvidence(invoice_field=name, invoice_value=field.value,
                                 verification_status=_verification_status(ver, name))
        code = ReasonCode(reason)
        out.append(raised(STAGE, f"trust_{name}", code, evidence, field=name, value=show(field.value),
                          confidence=field.confidence))
    if not out:
        out.append(passed(STAGE, "trust_critical_fields", "Every critical field is confirmed or confidently read."))
    return out


def check_ocr_available(inv: ExtractedInvoice, ver: VerificationResult) -> CheckResult | None:
    """If page verification could not run, say so: the decision then rests on the model's confidence."""
    unavailable = [n for n, f in ver.fields.items() if f.status == "unavailable"]
    if not unavailable:
        return None
    detail = "OCR unavailable" if ver.engine_used in ("unavailable", "mixed") else "not checked"
    return raised(STAGE, "ocr_available", ReasonCode.OCR_UNAVAILABLE, CheckEvidence(verification_status="unavailable"),
                  detail=detail, fields=", ".join(unavailable))


def _untrusted(inv: ExtractedInvoice, ver: VerificationResult, threshold: float, names: list[str],
               include_lines: bool = False) -> list[str]:
    """Which of the fields used in a calculation are not trusted (Stage 3 trust rule / model confidence)."""
    bad = []
    for name in names:
        if getattr(inv, name).value is None:
            continue
        if name in ver.fields:
            if field_trust(name, inv, ver, threshold) != ["trusted"]:
                bad.append(name)
        elif getattr(inv, name).confidence < threshold:
            bad.append(name)
    if include_lines and not lines_trusted(inv, ver, threshold):
        bad.append("line items")
    return bad


def lines_trusted(inv: ExtractedInvoice, ver: VerificationResult, threshold: float) -> bool:
    """Every line amount was found on the page; where the page could not be checked, the model was confident."""
    for index, line in enumerate(inv.line_items):
        status = ver.line_items[index].status if index < len(ver.line_items) else None
        if status == "verified":
            continue
        if status == "not_found" or line.confidence < threshold:
            return False
    return True


def _arithmetic_result(check: str, ok: bool, detail: str, untrusted: list[str], evidence: CheckEvidence,
                       pass_message: str) -> CheckResult:
    if ok:
        return passed(STAGE, check, pass_message, evidence)
    if untrusted:
        return raised(STAGE, check, ReasonCode.ARITHMETIC_UNCERTAIN, evidence, detail=detail, fields=", ".join(untrusted))
    return raised(STAGE, check, ReasonCode.ARITHMETIC_MISMATCH, evidence, detail=detail)


def check_lines_sum(inv: ExtractedInvoice, ver: VerificationResult, threshold: float) -> CheckResult:
    """The line amounts must add up to the subtotal (± ₹1)."""
    if inv.subtotal.value is None or not inv.line_items or any(l.amount is None for l in inv.line_items):
        return passed(STAGE, "lines_sum", "Lines vs subtotal not checked (subtotal or a line amount is not printed).")
    lines = sum((to_decimal(l.amount) for l in inv.line_items), Decimal("0.00"))
    subtotal = amount(inv, "subtotal")
    detail = f"line amounts add up to ₹{inr(lines)} but the subtotal is ₹{inr(subtotal)}"
    evidence = CheckEvidence(invoice_field="subtotal", invoice_value=float(subtotal),
                             verification_status=_verification_status(ver, "subtotal"),
                             reference_source="sum of line amounts", reference_value=float(lines))
    if lines_include_tax(inv):
        return passed(STAGE, "lines_sum", f"Line amounts include GST: they add up to the subtotal ₹{inr(subtotal)} "
                                          f"plus GST ₹{inr(total_tax(inv))}.", evidence)
    untrusted = _untrusted(inv, ver, threshold, ["subtotal"], include_lines=True)
    if lines < subtotal - ONE_RUPEE and "line items" not in untrusted:
        # a shortfall can mean the reader missed a line; finding the lines it did read cannot rule that out
        untrusted.append("line items (a line may have been missed)")
    return _arithmetic_result("lines_sum", abs(lines - subtotal) <= ONE_RUPEE, detail, untrusted, evidence,
                              f"Line amounts add up to the subtotal (₹{inr(subtotal)}).")


def check_total(inv: ExtractedInvoice, ver: VerificationResult, threshold: float) -> CheckResult:
    """Subtotal - discount + charges + CGST + SGST + IGST + round-off must equal the total (± ₹1)."""
    if inv.subtotal.value is None or inv.total_amount.value is None:
        return passed(STAGE, "total_arithmetic", "Total not checked (subtotal or total is not printed).")
    parts = ["subtotal", "discount", "other_charges", *TAX_FIELDS, "round_off"]
    computed = (amount(inv, "subtotal") - abs(amount(inv, "discount")) + amount(inv, "other_charges")
                + sum(amount(inv, t) for t in TAX_FIELDS) + amount(inv, "round_off"))
    total = amount(inv, "total_amount")
    detail = f"subtotal, discount, charges, taxes and round-off add up to ₹{inr(computed)} but the total says ₹{inr(total)}"
    evidence = CheckEvidence(invoice_field="total_amount", invoice_value=float(total),
                             verification_status=_verification_status(ver, "total_amount"),
                             reference_source="subtotal - discount + charges + taxes + round-off",
                             reference_value=float(computed))
    return _arithmetic_result("total_arithmetic", abs(computed - total) <= ONE_RUPEE, detail,
                              _untrusted(inv, ver, threshold, parts + ["total_amount"]), evidence,
                              f"The total ₹{inr(total)} adds up.")


def check_gst_type(inv: ExtractedInvoice, ver: VerificationResult, buyer: BuyerRecord, threshold: float) -> list[CheckResult]:
    """Same state as the buyer -> CGST + SGST; a different state -> IGST (state = first 2 digits of the vendor GSTIN)."""
    vendor_state = gstin_state(inv.vendor_gstin.value)
    if vendor_state is None or field_trust("vendor_gstin", inv, ver, threshold) != ["trusted"]:
        return [passed(STAGE, "gst_type", "GST type not checked: the vendor GSTIN is missing or not confirmed.")]
    split = amount(inv, "cgst") + amount(inv, "sgst")
    igst = amount(inv, "igst")
    intra = vendor_state == buyer.state_code
    required = "CGST + SGST" if intra else "IGST"
    charged = " and ".join(name for name, v in (("CGST + SGST", split), ("IGST", igst)) if v > 0) or "no GST"
    evidence = CheckEvidence(invoice_field="cgst/sgst/igst", invoice_value=charged,
                             reference_source=f"vendor state {vendor_state} vs buyer state {buyer.state_code}",
                             reference_value=required)
    if split == 0 and igst == 0:
        return [passed(STAGE, "gst_type", "No GST charged (nil-rated), so the GST type does not apply.", evidence)]
    if (intra and igst == 0) or (not intra and split == 0):
        return [passed(STAGE, "gst_type", f"{required} charged, as required for a "
                                          f"{'same' if intra else 'different'}-state supplier.", evidence)]
    # the wrong tax was charged; only reject when the tax figures themselves are trusted
    charged_fields = [n for n in TAX_FIELDS if amount(inv, n) > 0]
    untrusted = _untrusted(inv, ver, threshold, charged_fields)
    if untrusted:
        return [raised(STAGE, f"trust_{name}", ReasonCode.LOW_CONFIDENCE_FIELD,
                       CheckEvidence(invoice_field=name, invoice_value=getattr(inv, name).value,
                                     verification_status=_verification_status(ver, name)),
                       field=name, value=show(getattr(inv, name).value), confidence=getattr(inv, name).confidence)
                for name in untrusted]
    return [raised(STAGE, "gst_type", ReasonCode.GST_TYPE_INVALID, evidence, charged=charged,
                   vendor_state=vendor_state, buyer_state=buyer.state_code, required=required)]


def valid_rates(on: date | None) -> tuple[Decimal, ...]:
    """GST slabs legal on a date (GST 2.0 removed 12% and 28% from 22 Sep 2025)."""
    return RATES_BEFORE_GST_2_0 if on is not None and on < GST_2_0 else RATES_FROM_GST_2_0


def check_gst_rates(inv: ExtractedInvoice, ver: VerificationResult, buyer: BuyerRecord) -> list[CheckResult]:
    """Every line's GST rate must be a valid slab on the invoice date."""
    on = invoice_date(inv)
    allowed = valid_rates(on)
    intra = gstin_state(inv.vendor_gstin.value) == buyer.state_code
    out = []
    for line in inv.line_items:
        if line.tax_rate is None:
            continue
        rate = Decimal(str(line.tax_rate)).normalize()
        # a same-state invoice may print the CGST (= half) rate on each line, e.g. 9% for 18%
        if rate in allowed or (intra and rate * 2 in allowed):
            continue
        out.append(raised(STAGE, "gst_rate", ReasonCode.GST_RATE_UNUSUAL,
                          CheckEvidence(invoice_field="line_items.tax_rate", invoice_value=float(rate),
                                        reference_source="GST slabs", reference_value=[float(r) for r in allowed]),
                          rate=f"{rate:g}", item=line.description or "line", date=on or "the invoice date",
                          valid=", ".join(f"{r:g}%" for r in allowed)))
    return out or [passed(STAGE, "gst_rate", "All GST rates are valid slabs for the invoice date.")]


def check_buyer(inv: ExtractedInvoice, buyer: BuyerRecord, ver: VerificationResult | None = None) -> CheckResult:
    """The invoice must be addressed to our company: buyer GSTIN equal to ours, or (if no GSTIN) our name.
    A different GSTIN that is not on the page is a reading problem to confirm, not proof of a wrong buyer."""
    gstin = inv.buyer_gstin.value
    evidence = CheckEvidence(invoice_field="buyer_gstin", invoice_value=gstin, reference_source="buyer master",
                             reference_value=buyer.gstin,
                             verification_status=_verification_status(ver, "buyer_gstin") if ver else None)
    if gstin:
        if normalise_code(gstin) == normalise_code(buyer.gstin):
            return passed(STAGE, "buyer", f"Addressed to {buyer.legal_name} ({buyer.gstin}).", evidence)
        if ver is not None and _verification_status(ver, "buyer_gstin") == "not_found":
            return raised(STAGE, "trust_buyer_gstin", ReasonCode.FIELD_NOT_VERIFIED, evidence, field="buyer_gstin",
                          value=gstin, confidence=inv.buyer_gstin.confidence)
        return raised(STAGE, "buyer", ReasonCode.BUYER_MISMATCH, evidence, buyer=inv.buyer_name.value or "another company",
                      gstin=gstin, expected=f"{buyer.legal_name} ({buyer.gstin})")
    name = inv.buyer_name.value or ""
    best = max((fuzz.token_sort_ratio(normalise_name(name), normalise_name(v)) for v in buyer.name_variants), default=0)
    if name and best >= 90:
        return passed(STAGE, "buyer", f"Addressed to {buyer.legal_name} (by name; no buyer GSTIN printed).", evidence)
    return raised(STAGE, "buyer", ReasonCode.BUYER_MISMATCH, evidence, buyer=name or "nobody named",
                  gstin="no GSTIN", expected=buyer.legal_name)


def run_self_check(inv: ExtractedInvoice, ver: VerificationResult, buyer: BuyerRecord, settings: Settings) -> list[CheckResult]:
    threshold = settings.confidence_threshold
    checks = [check_document_type(inv), check_required_fields(inv)]
    checks += check_doubtful_fields(inv, ver, threshold)
    ocr = check_ocr_available(inv, ver)
    if ocr:
        checks.append(ocr)
    checks += [check_lines_sum(inv, ver, threshold), check_total(inv, ver, threshold)]
    checks += check_gst_type(inv, ver, buyer, threshold)
    checks += check_gst_rates(inv, ver, buyer)
    checks.append(check_buyer(inv, buyer, ver))
    return checks
