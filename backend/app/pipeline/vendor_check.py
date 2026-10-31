"""Stage 5a: who is the vendor, may we pay them, and do the bank details match the vendor master?"""

from __future__ import annotations

from rapidfuzz import fuzz

from app.pipeline.normalise import normalise_code, normalise_name, repair_gstin
from app.pipeline.reason_codes import ReasonCode, passed, raised
from app.pipeline.repository import MasterRepository, VendorRecord
from app.schemas import CheckEvidence, CheckResult, ExtractedInvoice, VerificationResult

STAGE = "vendor_check"
NAME_MATCH_MIN = 90


def vendor_by_gstin(repo: MasterRepository, gstin: str | None,
                    confirmed: str | None = None) -> tuple[VendorRecord | None, str | None]:
    """(vendor, corrected GSTIN or None): exact lookup; else the master GSTIN Stage 3b found printed on the page in
    place of a misreading (`confirmed`); else the GSTIN with a look-alike misread repaired (only where the GSTIN
    format forbids the character read, and only if the check character then validates)."""
    if not gstin:
        return None, None
    vendor = repo.vendor_by_gstin(gstin)
    if vendor is not None:
        return vendor, None
    if confirmed and repo.vendor_by_gstin(confirmed) is not None:
        return repo.vendor_by_gstin(confirmed), confirmed
    repaired = repair_gstin(gstin)
    vendor = repo.vendor_by_gstin(repaired) if repaired else None
    return (vendor, repaired) if vendor is not None else (None, None)


def match_vendor(inv: ExtractedInvoice, repo: MasterRepository,
                 confirmed_gstin: str | None = None) -> tuple[VendorRecord | None, str | None, int]:
    """(vendor, 'gstin' | 'gstin_corrected' | 'name' | None, name score): GSTIN match first (a format-impossible
    misread repaired), else name token_sort_ratio >= 90."""
    vendor, corrected = vendor_by_gstin(repo, inv.vendor_gstin.value, confirmed_gstin)
    if vendor is not None:
        return vendor, "gstin_corrected" if corrected else "gstin", 100
    name = normalise_name(inv.vendor_name.value or "")
    if not name:
        return None, None, 0
    best, best_score = None, 0
    for vendor in repo.vendors():
        score = max(fuzz.token_sort_ratio(name, normalise_name(vendor.legal_name)),
                    fuzz.token_sort_ratio(name, normalise_name(vendor.trade_name)))
        if score > best_score:
            best, best_score = vendor, int(score)
    if best is not None and best_score >= NAME_MATCH_MIN:
        return best, "name", best_score
    return None, None, best_score


def check_vendor_known(inv: ExtractedInvoice, vendor: VendorRecord | None, method: str | None, score: int) -> CheckResult:
    """The vendor must be in the vendor master; a match by name alone (no matching GSTIN) needs a person to confirm."""
    evidence = CheckEvidence(invoice_field="vendor_gstin", invoice_value=inv.vendor_gstin.value,
                             reference_source="vendor master", reference_value=vendor.gstin if vendor else None)
    if vendor is None:
        return raised(STAGE, "vendor_known", ReasonCode.VENDOR_UNKNOWN, evidence,
                      name=inv.vendor_name.value or "(no name)", gstin=inv.vendor_gstin.value or "not printed")
    if method == "name":
        return raised(STAGE, "vendor_known", ReasonCode.VENDOR_MATCHED_BY_NAME_ONLY, evidence,
                      name=inv.vendor_name.value, vendor=vendor.legal_name, score=score,
                      gstin=inv.vendor_gstin.value or "not printed", master_gstin=vendor.gstin)
    if method == "gstin_corrected":
        return passed(STAGE, "vendor_known", f"Vendor {vendor.legal_name} ({vendor.vendor_id}) found by GSTIN. The "
                                             f"GSTIN was read as {inv.vendor_gstin.value}, which is not a valid "
                                             f"GSTIN; the GSTIN on the invoice is {vendor.gstin}.", evidence)
    return passed(STAGE, "vendor_known", f"Vendor {vendor.legal_name} ({vendor.vendor_id}) found by GSTIN.", evidence)


def check_vendor_status(vendor: VendorRecord | None) -> CheckResult | None:
    """Only approved vendors can be paid: pending and blocked vendors go to procurement."""
    if vendor is None:
        return None
    evidence = CheckEvidence(reference_source=f"vendor master {vendor.vendor_id}", reference_value=vendor.status)
    if vendor.status == "pending":
        return raised(STAGE, "vendor_status", ReasonCode.VENDOR_NOT_APPROVED, evidence,
                      vendor=vendor.legal_name, vendor_id=vendor.vendor_id)
    if vendor.status == "blocked":
        return raised(STAGE, "vendor_status", ReasonCode.VENDOR_BLOCKED, evidence,
                      vendor=vendor.legal_name, vendor_id=vendor.vendor_id)
    return passed(STAGE, "vendor_status", "Vendor is approved.", evidence)


def check_bank_details(inv: ExtractedInvoice, vendor: VendorRecord | None) -> CheckResult | None:
    """Bank account and IFSC printed on the invoice must equal the vendor master (a change is a fraud signal)."""
    if vendor is None:
        return None
    account, ifsc = inv.bank_account.value, inv.bank_ifsc.value
    if not account and not ifsc:
        return passed(STAGE, "bank_details", "No bank details printed; payment goes to the account on file.")
    account_ok = not account or normalise_code(account) == normalise_code(vendor.bank_account)
    ifsc_ok = not ifsc or normalise_code(ifsc) == normalise_code(vendor.ifsc)
    invoice_bank = f"A/c {account or '-'}, IFSC {ifsc or '-'}"
    master_bank = f"A/c {vendor.bank_account}, IFSC {vendor.ifsc}"
    evidence = CheckEvidence(invoice_field="bank_account", invoice_value=invoice_bank,
                             reference_source=f"vendor master {vendor.vendor_id}", reference_value=master_bank)
    if account_ok and ifsc_ok:
        return passed(STAGE, "bank_details", "Bank details match the vendor master.", evidence)
    return raised(STAGE, "bank_details", ReasonCode.BANK_DETAILS_MISMATCH, evidence,
                  invoice_bank=invoice_bank, master_bank=master_bank)


def run_vendor_check(inv: ExtractedInvoice, repo: MasterRepository,
                     ver: VerificationResult | None = None) -> tuple[VendorRecord | None, list[CheckResult]]:
    field = ver.fields.get("vendor_gstin") if ver else None
    vendor, method, score = match_vendor(inv, repo, field.reference_value if field else None)
    checks = [check_vendor_known(inv, vendor, method, score)]
    checks += [c for c in (check_vendor_status(vendor), check_bank_details(inv, vendor)) if c is not None]
    return vendor, checks
