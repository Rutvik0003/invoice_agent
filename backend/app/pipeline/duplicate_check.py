"""Stage 5b: has this invoice (or this file) been received before?"""

from __future__ import annotations

from decimal import Decimal

from app.config import Settings
from app.pipeline.normalise import normalise_invoice_number, to_decimal
from app.pipeline.reason_codes import ReasonCode, inr, passed, raised
from app.pipeline.repository import MasterRepository, VendorRecord
from app.pipeline.self_check import invoice_date
from app.schemas import CheckEvidence, CheckResult, ExtractedInvoice, VerificationResult
from app.verification.verify import is_trusted

STAGE = "duplicate_check"


def check_duplicate_file(file_hash: str | None, repo: MasterRepository) -> CheckResult:
    """The exact same file (same SHA-256) must not be processed twice."""
    original = repo.run_with_file_hash(file_hash) if file_hash else None
    if original:
        return raised(STAGE, "duplicate_file", ReasonCode.DUPLICATE_FILE,
                      CheckEvidence(invoice_field="file_hash", invoice_value=file_hash, reference_source="runs",
                                    reference_value=original), run_id=original)
    return passed(STAGE, "duplicate_file", "This file has not been processed before.")


def check_duplicate_invoice(inv: ExtractedInvoice, vendor: VendorRecord | None, repo: MasterRepository,
                            ver: VerificationResult, settings: Settings) -> list[CheckResult]:
    """Same vendor + same normalised invoice number = duplicate (Reject); same vendor + same total within
    POSSIBLE_DUP_DAYS days = possible duplicate (Hold). An unconfirmed invoice number only ever Holds."""
    if vendor is None:
        return [passed(STAGE, "duplicate_invoice", "Duplicate check skipped: the vendor is not known.")]
    history = repo.history_for_vendor(vendor.vendor_id)
    number = inv.invoice_number.value
    out: list[CheckResult] = []
    same_number = None
    if number:
        target = normalise_invoice_number(number)
        same_number = next((h for h in history if normalise_invoice_number(h.invoice_number) == target), None)
    if same_number is not None:
        evidence = CheckEvidence(invoice_field="invoice_number", invoice_value=number,
                                 reference_source=f"invoice history {same_number.history_id}",
                                 reference_value=same_number.invoice_number)
        values = dict(number=number, original=same_number.invoice_number, original_date=same_number.invoice_date,
                      original_total=inr(same_number.total_amount), original_status=same_number.status)
        if is_trusted("invoice_number", inv, ver, settings.confidence_threshold):
            out.append(raised(STAGE, "duplicate_invoice", ReasonCode.DUPLICATE_INVOICE_NUMBER, evidence, **values))
        else:  # the number itself is doubtful, so we cannot be sure it is the same invoice
            out.append(raised(STAGE, "duplicate_invoice", ReasonCode.POSSIBLE_DUPLICATE, evidence,
                              reason=f"The invoice number {number} (not confirmed on the page) matches a past invoice.",
                              original=same_number.invoice_number, original_date=same_number.invoice_date,
                              original_total=inr(same_number.total_amount)))
    total = to_decimal(inv.total_amount.value)
    on = invoice_date(inv)
    if total is not None and on is not None:
        for h in history:
            if h is same_number:
                continue
            close_in_time = abs((h.invoice_date - on).days) <= settings.possible_dup_days
            if close_in_time and abs(h.total_amount - total) <= Decimal("1.00"):
                out.append(raised(STAGE, "possible_duplicate", ReasonCode.POSSIBLE_DUPLICATE,
                                  CheckEvidence(invoice_field="total_amount", invoice_value=float(total),
                                                reference_source=f"invoice history {h.history_id}",
                                                reference_value=f"{h.invoice_number} ₹{inr(h.total_amount)} {h.invoice_date}"),
                                  reason=f"Same vendor and same total (₹{inr(total)}) within "
                                         f"{settings.possible_dup_days} days, different invoice number.",
                                  original=h.invoice_number, original_date=h.invoice_date,
                                  original_total=inr(h.total_amount)))
                break
    return out or [passed(STAGE, "duplicate_invoice", "No earlier invoice with this number or amount from this vendor.")]


def run_duplicate_check(inv: ExtractedInvoice, vendor: VendorRecord | None, repo: MasterRepository,
                        ver: VerificationResult, settings: Settings, file_hash: str | None) -> list[CheckResult]:
    return [check_duplicate_file(file_hash, repo)] + check_duplicate_invoice(inv, vendor, repo, ver, settings)
