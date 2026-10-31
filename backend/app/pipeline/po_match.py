"""Stage 6: find the purchase order - by the printed reference, or (if none) by scoring the vendor's open POs.

Inference score = 0.5 x item similarity + 0.3 x amount closeness + 0.2 x quantity fit. An inferred PO is
never auto-approved: the best case is PO_INFERRED (Hold with one-click confirm).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from rapidfuzz import fuzz

from app.config import Settings
from app.pipeline.normalise import to_decimal
from app.pipeline.reason_codes import ReasonCode, inr, passed, raised
from app.pipeline.repository import MasterRepository, PORecord, POLineRecord, VendorRecord
from app.schemas import CheckEvidence, CheckResult, ExtractedInvoice, LineItem

STAGE = "po_match"
ITEM_MATCH_MIN = 90  # description similarity needed for an invoice line to count as "the same item"


@dataclass
class POCandidate:
    po: PORecord
    score: float
    item_similarity: float
    amount_closeness: float
    qty_match: float


def description_score(a: str | None, b: str | None) -> int:
    return int(fuzz.token_sort_ratio((a or "").lower(), (b or "").lower()))


def best_po_line(line: LineItem, po: PORecord) -> tuple[POLineRecord | None, int]:
    best, best_score = None, 0
    for po_line in po.lines:
        score = description_score(line.description, po_line.description)
        if score > best_score:
            best, best_score = po_line, score
    return best, best_score


ONE_RUPEE = Decimal("1.00")


def _money(inv: ExtractedInvoice, name: str) -> Decimal:
    return to_decimal(getattr(inv, name).value) or Decimal("0.00")


def total_tax(inv: ExtractedInvoice) -> Decimal:
    return _money(inv, "cgst") + _money(inv, "sgst") + _money(inv, "igst")


def lines_include_tax(inv: ExtractedInvoice) -> bool:
    """Retail-style invoices print line amounts that already include GST: the lines then add up to the
    taxable value plus GST (or, with no subtotal printed, to the total before round-off), not to the subtotal."""
    if not inv.line_items or any(l.amount is None for l in inv.line_items) or total_tax(inv) <= 0:
        return False
    lines = sum((to_decimal(l.amount) for l in inv.line_items), Decimal("0.00"))
    subtotal = to_decimal(inv.subtotal.value)
    if subtotal is not None:
        return abs(lines - subtotal) > ONE_RUPEE and abs(lines - (subtotal + total_tax(inv))) <= ONE_RUPEE
    total = to_decimal(inv.total_amount.value)
    if total is None:
        return False
    before_round_off = total - _money(inv, "round_off") - _money(inv, "other_charges") + abs(_money(inv, "discount"))
    return abs(lines - before_round_off) <= ONE_RUPEE


def is_adjustment(line: LineItem) -> bool:
    """A negative line (a discount, credit or return) is not an item bought on the PO."""
    return (line.amount is not None and line.amount < 0) or (line.unit_price is not None and line.unit_price < 0)


def invoice_taxable(inv: ExtractedInvoice) -> Decimal:
    """What this invoice bills before tax: the subtotal, or the sum of line amounts if no subtotal is printed
    (less the GST, when those line amounts include it)."""
    subtotal = to_decimal(inv.subtotal.value)
    if subtotal is not None:
        return subtotal
    lines = sum((to_decimal(l.amount) or Decimal("0") for l in inv.line_items), Decimal("0.00"))
    return lines - total_tax(inv) if lines_include_tax(inv) else lines


def score_po(inv: ExtractedInvoice, po: PORecord) -> POCandidate:
    """0.5 x item similarity + 0.3 x amount closeness + 0.2 x quantity fit (each 0-1)."""
    lines = [l for l in inv.line_items or [] if not is_adjustment(l)]
    sims, fits = [], []
    for line in lines:
        po_line, score = best_po_line(line, po)
        matched = po_line is not None and score >= ITEM_MATCH_MIN
        sims.append(score / 100 if matched else 0.0)
        qty = Decimal(str(line.quantity)) if line.quantity is not None else None
        fits.append(1.0 if matched and qty is not None and 0 < qty <= po_line.qty_remaining else 0.0)
    item = sum(sims) / len(sims) if sims else 0.0
    qty_fit = sum(fits) / len(fits) if fits else 0.0
    billed, remaining = invoice_taxable(inv), po.remaining_value
    bigger = max(billed, remaining)
    closeness = float(max(Decimal("0"), 1 - abs(billed - remaining) / bigger)) if bigger > 0 else 0.0
    total = 0.5 * item + 0.3 * closeness + 0.2 * qty_fit
    return POCandidate(po, round(total, 4), round(item, 4), round(closeness, 4), round(qty_fit, 4))


def infer_po(inv: ExtractedInvoice, vendor: VendorRecord, repo: MasterRepository) -> list[POCandidate]:
    return sorted((score_po(inv, po) for po in repo.open_pos_for_vendor(vendor.vendor_id)),
                  key=lambda c: c.score, reverse=True)


def run_po_match(inv: ExtractedInvoice, vendor: VendorRecord | None, repo: MasterRepository,
                 settings: Settings) -> tuple[PORecord | None, bool, list[CheckResult], list[POCandidate]]:
    """(PO to match amounts against, was it inferred?, checks, ranked candidates when inferring)."""
    ref = inv.po_reference.value
    if ref:
        return _by_reference(ref, vendor, repo)
    if vendor is None:
        return None, False, [raised(STAGE, "po_found", ReasonCode.PO_NOT_FOUND, CheckEvidence(invoice_field="po_reference"),
                                    detail="No PO is quoted, and the vendor is unknown, so no PO can be matched.")], []
    ranked = infer_po(inv, vendor, repo)
    if not ranked or ranked[0].score < settings.po_infer_floor:
        best = f" (best match {ranked[0].po.po_number} scored only {ranked[0].score:.2f})" if ranked else ""
        return None, False, [raised(STAGE, "po_found", ReasonCode.PO_NOT_FOUND, CheckEvidence(invoice_field="po_reference"),
                                    detail=f"No PO is quoted and no open PO of {vendor.legal_name} fits this "
                                           f"invoice{best}. Please assign the PO.")], ranked
    best = ranked[0]
    second = ranked[1].score if len(ranked) > 1 else 0.0
    evidence = CheckEvidence(invoice_field="po_reference", invoice_value=None, reference_source="open POs of the vendor",
                             reference_value=[f"{c.po.po_number}: {c.score:.2f}" for c in ranked[:3]])
    if best.score >= settings.po_infer_min_score and best.score - second >= settings.po_infer_min_gap:
        check = raised(STAGE, "po_found", ReasonCode.PO_INFERRED, evidence, po=best.po.po_number, score=best.score,
                       second=second)
        return best.po, True, [check], ranked
    candidates = ", ".join(f"{c.po.po_number} ({c.score:.2f})" for c in ranked[:3])
    return None, False, [raised(STAGE, "po_found", ReasonCode.PO_AMBIGUOUS, evidence, candidates=candidates)], ranked


def _by_reference(ref: str, vendor: VendorRecord | None, repo: MasterRepository):
    """Explicit PO reference -> exact lookup (normalised), then it must belong to this vendor and be open."""
    po = repo.po(ref)
    evidence = CheckEvidence(invoice_field="po_reference", invoice_value=ref, reference_source="purchase orders",
                             reference_value=po.po_number if po else None)
    if po is None:
        return None, False, [raised(STAGE, "po_found", ReasonCode.PO_NOT_FOUND, evidence,
                                    detail=f"PO {ref} quoted on the invoice does not exist. Please assign the right PO.")], []
    if vendor is not None and po.vendor_id != vendor.vendor_id:
        return None, False, [raised(STAGE, "po_vendor", ReasonCode.PO_VENDOR_MISMATCH, evidence, po=po.po_number,
                                    po_vendor=po.vendor_id, vendor=vendor.vendor_id)], []
    checks = [passed(STAGE, "po_found", f"{po.po_number} found (₹{inr(po.taxable_value)}, "
                                        f"₹{inr(po.billed_value)} billed so far).", evidence)]
    if po.status == "closed":
        checks.append(raised(STAGE, "po_open", ReasonCode.PO_CLOSED,
                             CheckEvidence(reference_source=po.po_number, reference_value=po.status), po=po.po_number))
    return po, False, checks, []
