"""Stage 3b: confirm values the page check could not find, using our own records and the invoice's own arithmetic.

OCR can miss a value that the AI read correctly (a smudge, a stamp, a faint photo). Some of those values can
still be confirmed without trusting the AI:

- master data: the AI cannot know our records, so a value that exactly matches them was read correctly.
  Zenith is the only buyer, so the buyer GSTIN must be Zenith's; the vendor's GSTIN and name must belong to
  the same vendor-master record; the bank account and PO number must belong to that vendor.
- a misread GSTIN: the AI's GSTIN fails the GSTIN check digit (so it cannot be what is printed), it is at most
  two characters from a GSTIN in our records, and that GSTIN is printed on the page. The field then counts as
  confirmed with the master value as its reference (the AI's value is kept and shown).
- calculation: a missing amount that follows exactly from amounts that *were* found on the page (lines -> subtotal,
  CGST = SGST, subtotal + tax -> total). Arithmetic between AI values alone is never enough: one of the anchors
  must be on the page.

A confirmed field gets status `cross_checked` and counts as trusted. Nothing here changes a value or decides
anything, and a value that does not match is simply left as it was (not found / unavailable).
"""

from __future__ import annotations

from decimal import Decimal

from rapidfuzz import fuzz

from app.pipeline.normalise import gstin_valid, normalise_code, normalise_identifier, normalise_name, to_decimal
from app.pipeline.repository import MasterRepository, VendorRecord
from app.pipeline.vendor_check import vendor_by_gstin
from app.schemas import ExtractedInvoice, FieldVerification, VerificationResult
from app.verification.matchers import Candidate, candidates, match_code
from app.verification.page_text import PageWords

ONE_RUPEE = Decimal("1.00")
NAME_MATCH_MIN = 90  # same threshold as the vendor check (CLAUDE.md §6 Stage 5)
OPEN = ("not_found", "unavailable")  # statuses a cross-check may upgrade
MAX_MISREAD_CHARS = 2  # an invalid GSTIN this close to a master GSTIN printed on the page is a misreading of it


def _value(inv: ExtractedInvoice, name: str) -> object:
    return getattr(inv, name).value


def name_matches(name: str | None, vendor: VendorRecord) -> bool:
    """The name on the invoice is the vendor's legal or trade name (token_sort_ratio >= 90)."""
    if not name:
        return False
    target = normalise_name(name)
    return max(fuzz.token_sort_ratio(target, normalise_name(vendor.legal_name)),
               fuzz.token_sort_ratio(target, normalise_name(vendor.trade_name))) >= NAME_MATCH_MIN


def consistent_vendor(inv: ExtractedInvoice, repo: MasterRepository,
                      fields: dict[str, FieldVerification] | None = None) -> VendorRecord | None:
    """The vendor-master record whose GSTIN is the AI's GSTIN (or the master GSTIN the page showed instead of a
    misreading) *and* whose name is the AI's vendor name."""
    gstin = _value(inv, "vendor_gstin")
    confirmed = fields["vendor_gstin"].reference_value if fields else None
    vendor, _ = vendor_by_gstin(repo, str(gstin) if gstin else None, confirmed)
    if vendor is not None and name_matches(_value(inv, "vendor_name"), vendor):
        return vendor
    return None


def _confirm(fields: dict[str, FieldVerification], name: str, source: str, why: str) -> None:
    fields[name] = FieldVerification(status="cross_checked", source=source, matched_text=why)


def _differences(a: str, b: str) -> int:
    a, b = normalise_code(a), normalise_code(b)
    return sum(x != y for x, y in zip(a, b)) if len(a) == len(b) else len(a) + len(b)


def _printed(value: str, cands: list[Candidate]) -> Candidate | None:
    """Where on the page this exact value is printed (one OCR slip allowed, as in Stage 3)."""
    return next((c for c in cands if match_code(value, c.text, allow_one_difference=c.source == "ocr")), None)


def misread_gstin(read: object, known: list[str], cands: list[Candidate]) -> tuple[str, Candidate] | None:
    """(master GSTIN, where it is printed) when the AI's GSTIN is provably wrong (fails the check digit), at most
    two characters from exactly one master GSTIN, and that GSTIN is printed on the page."""
    if not read or gstin_valid(normalise_code(str(read))):
        return None
    near = [g for g in known if _differences(str(read), g) <= MAX_MISREAD_CHARS]
    found = [(g, c) for g in near if (c := _printed(g, cands)) is not None]
    return found[0] if len(found) == 1 else None


def _misread_checks(inv: ExtractedInvoice, repo: MasterRepository, fields: dict[str, FieldVerification],
                    pages: list[PageWords]) -> None:
    """Buyer / vendor GSTIN the AI misread, where the page shows the master GSTIN (status not_found only: the page
    was readable and the AI's value is not on it)."""
    cands = candidates([p for p in pages if p.source != "unavailable"])
    known = {"buyer_gstin": [repo.buyer.gstin], "vendor_gstin": [v.gstin for v in repo.vendors()]}
    for name, gstins in known.items():
        if fields[name].status != "not_found":
            continue
        hit = misread_gstin(_value(inv, name), gstins, cands)
        if hit is None:
            continue
        gstin, where = hit
        whose = (f"{repo.buyer.legal_name}'s GSTIN" if name == "buyer_gstin"
                 else f"the GSTIN of vendor master {repo.vendor_by_gstin(gstin).vendor_id}")
        fields[name] = FieldVerification(
            status="cross_checked", source="master_data", page=where.page, bbox=[round(c, 5) for c in where.bbox],
            reference_value=gstin,
            matched_text=f"{whose}, printed on the page; the AI read {_value(inv, name)}, which is not a valid GSTIN")


def _master_checks(inv: ExtractedInvoice, repo: MasterRepository, fields: dict[str, FieldVerification]) -> None:
    """Buyer GSTIN, vendor GSTIN + name, bank account and PO number against the master data."""
    buyer_gstin = _value(inv, "buyer_gstin")
    if fields["buyer_gstin"].status in OPEN and normalise_code(str(buyer_gstin)) == normalise_code(repo.buyer.gstin):
        _confirm(fields, "buyer_gstin", "master_data", f"{repo.buyer.legal_name}'s GSTIN (buyer master)")

    vendor = consistent_vendor(inv, repo, fields)
    if vendor is None:
        return
    record = f"vendor master {vendor.vendor_id} {vendor.trade_name or vendor.legal_name}"
    if fields["vendor_gstin"].status in OPEN:
        _confirm(fields, "vendor_gstin", "master_data", f"{record} (name on the invoice matches)")
    if fields["vendor_name"].status in OPEN:
        _confirm(fields, "vendor_name", "master_data", f"{record} (GSTIN on the invoice matches)")
    account = _value(inv, "bank_account")
    if fields["bank_account"].status in OPEN and normalise_code(str(account)) == normalise_code(vendor.bank_account):
        _confirm(fields, "bank_account", "master_data", f"account on file in {record}")
    po_ref = _value(inv, "po_reference")
    po = repo.po(str(po_ref)) if fields["po_reference"].status in OPEN and po_ref else None
    if po is not None and po.vendor_id == vendor.vendor_id and normalise_identifier(str(po_ref)) == normalise_identifier(po.po_number):
        _confirm(fields, "po_reference", "master_data", f"a purchase order of {record}")


def _on_page(fields: dict[str, FieldVerification], name: str) -> bool:
    return fields[name].status == "verified"


def _known(fields: dict[str, FieldVerification], name: str) -> bool:
    return fields[name].status in ("verified", "cross_checked")


def _calculation_checks(inv: ExtractedInvoice, ver: VerificationResult, fields: dict[str, FieldVerification],
                        threshold: float) -> None:
    """Subtotal from the line amounts, one GST half from the other, the total from its parts."""
    lines = inv.line_items
    subtotal = to_decimal(_value(inv, "subtotal"))
    if (fields["subtotal"].status in OPEN and subtotal is not None and lines and len(ver.line_items) == len(lines)
            and all(v.status == "verified" for v in ver.line_items)):
        line_sum = sum((to_decimal(l.amount) for l in lines), Decimal("0.00"))
        if abs(line_sum - subtotal) <= ONE_RUPEE:
            _confirm(fields, "subtotal", "calculation", "sum of the line amounts on the page")

    cgst, sgst = to_decimal(_value(inv, "cgst")), to_decimal(_value(inv, "sgst"))
    if cgst is not None and sgst is not None and abs(cgst - sgst) <= ONE_RUPEE:
        for missing, found in (("cgst", "sgst"), ("sgst", "cgst")):
            if fields[missing].status in OPEN and _on_page(fields, found):
                _confirm(fields, missing, "calculation", f"equals the {found.upper()} on the page (CGST = SGST)")

    total = to_decimal(_value(inv, "total_amount"))
    if fields["total_amount"].status not in OPEN or total is None or subtotal is None:
        return
    taxes = [n for n in ("cgst", "sgst", "igst") if _value(inv, n) is not None]
    if not _on_page(fields, "subtotal") and not any(_on_page(fields, n) for n in taxes):
        return  # nothing anchored on the page: AI values agreeing with each other prove nothing
    if not _known(fields, "subtotal") or not all(_known(fields, n) for n in taxes):
        return
    extras = [getattr(inv, n) for n in ("discount", "other_charges", "round_off")]
    if any(e.value not in (None, 0) and e.confidence < threshold for e in extras):
        return
    discount, charges, round_off = (to_decimal(e.value) or Decimal("0.00") for e in extras)
    expected = subtotal - abs(discount) + charges + sum((to_decimal(_value(inv, n)) for n in taxes), Decimal("0.00")) + round_off
    if abs(expected - total) <= ONE_RUPEE:
        _confirm(fields, "total_amount", "calculation", "subtotal + GST (and adjustments) on the page add up to it")


def cross_check(inv: ExtractedInvoice, ver: VerificationResult, repo: MasterRepository,
                threshold: float, pages: list[PageWords] | None = None) -> VerificationResult:
    """Upgrade not-found / unavailable fields that our records or the page's own arithmetic confirm.
    pages (the Stage 3 words) let a misread GSTIN be recognised by the master GSTIN printed on the page."""
    fields = dict(ver.fields)
    if not all(name in fields for name in ("buyer_gstin", "vendor_gstin", "vendor_name", "bank_account",
                                           "po_reference", "subtotal", "cgst", "sgst", "igst", "total_amount")):
        return ver
    if pages:
        _misread_checks(inv, repo, fields, pages)
    _master_checks(inv, repo, fields)
    _calculation_checks(inv, ver, fields, threshold)
    return ver.model_copy(update={"fields": fields})
