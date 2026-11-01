"""Unit tests for every rules-engine check (stages 4-8), including the boundary cases."""

from datetime import date
from decimal import Decimal

import pytest

from app.config import Settings
from app.pipeline.amount_match import run_amount_match, tolerance
from app.pipeline.duplicate_check import run_duplicate_check
from app.pipeline.engine import run_rules
from app.pipeline.normalise import (
    gstin_state,
    normalise_identifier,
    normalise_name,
    parse_amount,
    parse_date,
    to_decimal,
)
from app.pipeline.po_match import run_po_match, score_po
from app.pipeline.reason_codes import CODES, ReasonCode, inr
from app.pipeline.self_check import (
    check_buyer,
    check_doubtful_fields,
    check_gst_rates,
    check_gst_type,
    check_lines_sum,
    check_total,
    run_self_check,
)
from app.pipeline.vendor_check import run_vendor_check
from tests.rules_fixtures import (
    BUYER,
    BLOCKED,
    INTER,
    INTRA,
    PENDING,
    PO_CLOSED,
    PO_OPEN,
    PO_PARTIAL,
    SETTINGS,
    D,
    invoice,
    line,
    repo,
    verification,
)


def codes(checks) -> set[str]:
    return {c.code for c in checks if c.code}


# ---------------------------------------------------------------- reason codes & normalise


def test_every_reason_code_has_severity_role_and_template():
    for code in ReasonCode:
        info = CODES[code]
        assert info.severity in ("REJECT", "HOLD", "INFO") and info.role and info.template
        if info.severity == "REJECT":
            assert info.fix, f"{code} needs vendor-note fix text"
    assert ReasonCode.PO_OVERRUN.severity == "HOLD" and ReasonCode.GST_TYPE_INVALID.severity == "REJECT"


@pytest.mark.parametrize("a, b", [("KOS-0457", "KOS/457"), ("inv 00457", "INV-457"), ("SIT/26-27/0881", "sit-26-27-0881"),
                                  ("PO/2026/1050", "PO-2026-1050"), ("vcw0914", "VCW-914")])
def test_invoice_numbers_normalise_equal(a, b):
    assert normalise_identifier(a) == normalise_identifier(b)


@pytest.mark.parametrize("a, b", [("KOS-0457", "KOS-0475"), ("2026/KOS/57", "2026/KOS/75"), ("INV-1", "INV-11")])
def test_different_invoice_numbers_stay_different(a, b):
    assert normalise_identifier(a) != normalise_identifier(b)


@pytest.mark.parametrize("text, expected", [("₹1,18,000.00", "118000.00"), ("Rs. 1,18,000/-", "118000"),
                                            ("INR 118000.00", "118000.00"), ("1,23,45,678.9", "12345678.9")])
def test_amounts(text, expected):
    assert parse_amount(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["05/03/2026", "05-03-2026", "5 Mar 2026", "05-Mar-26", "March 5, 2026", "2026-03-05",
                                  "05.03.2026", "5-March-2026", "Mar 5, 2026"])
def test_dates_every_printed_format(text):
    assert parse_date(text) == date(2026, 3, 5)


def test_names_gstin_state_and_decimals():
    assert normalise_name("M/s Sharma IT Solutions Private Limited") == "sharma it solutions pvt ltd"
    assert normalise_name("Sharma IT Solutions Pvt. Ltd.") == "sharma it solutions pvt ltd"
    assert gstin_state("27 AABCS 1234 F1Z5") == "27" and gstin_state(None) is None
    assert to_decimal(1234.5) == Decimal("1234.50") and to_decimal("Rs. 1,000/-") == Decimal("1000.00")
    assert inr(118000) == "1,18,000.00" and inr(Decimal("-0.16")) == "-0.16"


# ---------------------------------------------------------------- stage 4: self-check


def test_clean_invoice_passes_every_self_check():
    inv = invoice()
    assert codes(run_self_check(inv, verification(inv), BUYER, SETTINGS)) == set()


def test_not_a_tax_invoice_and_missing_fields():
    inv = invoice(document_type="quotation", invoice_number=None)
    found = codes(run_self_check(inv, verification(inv), BUYER, SETTINGS))
    assert {"NOT_A_TAX_INVOICE", "MISSING_REQUIRED_FIELD"} <= found


def test_verified_but_low_confidence_field_is_trusted():
    inv = invoice(confidence=0.30)
    assert codes(check_doubtful_fields(inv, verification(inv), 0.8)) == set()


def test_not_found_field_is_field_not_verified():
    inv = invoice()
    checks = check_doubtful_fields(inv, verification(inv, invoice_number="not_found"), 0.8)
    assert codes(checks) == {"FIELD_NOT_VERIFIED"}
    assert "could not be found on the document" in checks[0].message


def test_ocr_unavailable_falls_back_to_model_confidence():
    confident = invoice(confidence=0.95)
    checks = run_self_check(confident, verification(confident, "unavailable"), BUYER, SETTINGS)
    assert codes(checks) == {"OCR_UNAVAILABLE"}  # info only: confident values are trusted
    unsure = invoice(confidence=0.50)
    checks = run_self_check(unsure, verification(unsure, "unavailable"), BUYER, SETTINGS)
    assert {"OCR_UNAVAILABLE", "LOW_CONFIDENCE_FIELD"} <= codes(checks)


@pytest.mark.parametrize("delta, expected", [(Decimal("1.00"), set()), (Decimal("-1.00"), set()),
                                             (Decimal("1.01"), {"ARITHMETIC_MISMATCH"})])
def test_total_tolerance_is_one_rupee(delta, expected):
    base = invoice()
    inv = invoice(total_amount=float(Decimal(str(base.total_amount.value)) + delta))
    assert codes([check_total(inv, verification(inv), 0.8)]) == expected


def test_line_sum_mismatch_is_reject_only_when_trusted():
    lines = [{"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1, "unit_price": 60000.0,
              "amount": 61000.0, "tax_rate": 18}]
    inv = invoice(lines=lines, subtotal=60000.0, total_amount=70800.0, cgst=5400.0, sgst=5400.0)
    assert codes([check_lines_sum(inv, verification(inv), 0.8)]) == {"ARITHMETIC_MISMATCH"}
    assert codes([check_lines_sum(inv, verification(inv, subtotal="not_found"), 0.8)]) == {"ARITHMETIC_UNCERTAIN"}
    low_conf_lines = [{**lines[0], "confidence": 0.4}]
    inv2 = invoice(lines=low_conf_lines, subtotal=60000.0, total_amount=70800.0, cgst=5400.0, sgst=5400.0)
    assert codes([check_lines_sum(inv2, verification(inv2), 0.8)]) == {"ARITHMETIC_UNCERTAIN"}


def test_gst_type_intra_and_inter_state():
    intra_ok = invoice(INTRA)
    assert codes(check_gst_type(intra_ok, verification(intra_ok), BUYER, 0.8)) == set()
    inter_ok = invoice(INTER, lines=[{"description": "Corrugated Box 5-Ply 18x12x12 in", "quantity": 10,
                                       "unit_price": 50.0, "tax_rate": 5}])
    assert codes(check_gst_type(inter_ok, verification(inter_ok), BUYER, 0.8)) == set()
    inter_wrong = invoice(INTER, intra=True, lines=[{"description": "Corrugated Box 5-Ply 18x12x12 in", "quantity": 10,
                                                     "unit_price": 50.0, "tax_rate": 5}])
    assert codes(check_gst_type(inter_wrong, verification(inter_wrong), BUYER, 0.8)) == {"GST_TYPE_INVALID"}
    intra_wrong = invoice(INTRA, intra=False)
    assert codes(check_gst_type(intra_wrong, verification(intra_wrong), BUYER, 0.8)) == {"GST_TYPE_INVALID"}
    # wrong tax but the tax figure could not be confirmed -> Hold, never Reject
    unsure = check_gst_type(intra_wrong, verification(intra_wrong, igst="not_found"), BUYER, 0.8)
    assert codes(unsure) == {"LOW_CONFIDENCE_FIELD"}


def test_zero_percent_gst_needs_no_tax_type():
    inv = invoice(lines=[{"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1,
                          "unit_price": 60000.0, "tax_rate": 0}])
    assert codes(check_gst_type(inv, verification(inv), BUYER, 0.8)) == set()
    assert codes(check_gst_rates(inv, verification(inv), BUYER)) == set()


@pytest.mark.parametrize("rate, on, unusual", [(12, "2026-10-20", True), (28, "2026-10-20", True), (40, "2026-10-20", False),
                                               (12, "2025-09-21", False), (12, "2025-09-22", True), (9, "2026-10-20", False),
                                               (6, "2026-10-20", True)])
def test_gst_rate_valid_for_date(rate, on, unusual):
    inv = invoice(lines=[{"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1,
                          "unit_price": 60000.0, "tax_rate": rate}], invoice_date=on)
    assert ("GST_RATE_UNUSUAL" in codes(check_gst_rates(inv, verification(inv), BUYER))) == unusual


def test_buyer_must_be_us():
    assert check_buyer(invoice(), BUYER).code is None
    assert check_buyer(invoice(buyer_gstin="27AABCH9999F1Z1", buyer_name="Horizon Lifestyle Pvt Ltd"), BUYER).code == "BUYER_MISMATCH"
    assert check_buyer(invoice(buyer_gstin=None, buyer_name="Zenith Retail Private Limited"), BUYER).code is None
    misread = invoice(buyer_gstin="27HRRC2546QN1Z7")  # the AI misread our GSTIN and it is not on the page
    assert check_buyer(misread, BUYER, verification(misread, buyer_gstin="not_found")).code == "FIELD_NOT_VERIFIED"


# ---------------------------------------------------------------- stage 5: vendor & duplicates


def test_vendor_by_gstin_name_only_unknown_and_status():
    vendor, checks = run_vendor_check(invoice(), repo())
    assert vendor is INTRA and codes(checks) == set()
    vendor, checks = run_vendor_check(invoice(vendor_gstin=None, vendor_name="Sharma IT Solutions Pvt. Ltd."), repo())
    assert vendor is INTRA and codes(checks) == {"VENDOR_MATCHED_BY_NAME_ONLY"}
    vendor, checks = run_vendor_check(invoice(vendor_gstin="24AABCZ1111F1Z1", vendor_name="Brand New Traders"), repo())
    assert vendor is None and codes(checks) == {"VENDOR_UNKNOWN"}
    assert codes(run_vendor_check(invoice(PENDING), repo())[1]) == {"VENDOR_NOT_APPROVED"}
    assert codes(run_vendor_check(invoice(BLOCKED), repo())[1]) == {"VENDOR_BLOCKED"}


def test_bank_details_must_match_master():
    assert codes(run_vendor_check(invoice(bank_account="50100999999999"), repo())[1]) == {"BANK_DETAILS_MISMATCH"}
    assert codes(run_vendor_check(invoice(bank_ifsc="HDFC0009999"), repo())[1]) == {"BANK_DETAILS_MISMATCH"}
    assert codes(run_vendor_check(invoice(bank_account=None, bank_ifsc=None), repo())[1]) == set()


def test_duplicates():
    from app.pipeline.repository import ProcessedFile

    r = repo(hashes={"abc": ProcessedFile("run-1", "APPROVE")})
    inv = invoice(INTER, invoice_number="KOS/457", invoice_date="2026-09-10")
    ver = verification(inv)
    found = codes(run_duplicate_check(inv, INTER, r, ver, SETTINGS, "abc"))
    assert {"DUPLICATE_FILE", "DUPLICATE_INVOICE_NUMBER"} <= found
    # same number but the number was not confirmed on the page -> only a possible duplicate (Hold)
    unsure = codes(run_duplicate_check(inv, INTER, r, verification(inv, invoice_number="not_found"), SETTINGS, None))
    assert unsure == {"POSSIBLE_DUPLICATE"}
    # same vendor + same total within 3 days, different number
    near = invoice(INTER, invoice_number="KOS-0999", invoice_date="2026-09-13", total_amount=46200.0)
    assert codes(run_duplicate_check(near, INTER, r, verification(near), SETTINGS, None)) == {"POSSIBLE_DUPLICATE"}
    far = invoice(INTER, invoice_number="KOS-0999", invoice_date="2026-09-14", total_amount=46200.0)
    assert codes(run_duplicate_check(far, INTER, r, verification(far), SETTINGS, None)) == set()


# ---------------------------------------------------------------- stage 6: find the PO


def test_po_by_reference_found_closed_wrong_vendor_or_missing():
    po, inferred, checks, _ = run_po_match(invoice(po_reference="PO/2026/1001"), INTRA, repo(), SETTINGS)
    assert po is PO_OPEN and not inferred and codes(checks) == set()
    po, _, checks, _ = run_po_match(invoice(po_reference="PO-2026-1003"), INTRA, repo(), SETTINGS)
    assert po is PO_CLOSED and codes(checks) == {"PO_CLOSED"}
    assert codes(run_po_match(invoice(po_reference="PO-2026-1002"), INTRA, repo(), SETTINGS)[2]) == {"PO_VENDOR_MISMATCH"}
    assert codes(run_po_match(invoice(po_reference="PO-2026-9999"), INTRA, repo(), SETTINGS)[2]) == {"PO_NOT_FOUND"}


def test_po_inferred_when_one_open_po_clearly_fits():
    inv = invoice(po_reference=None)
    po, inferred, checks, ranked = run_po_match(inv, INTRA, repo(), SETTINGS)
    assert codes(checks) == {"PO_INFERRED"} and po is PO_OPEN and inferred
    assert ranked[0].item_similarity == 1.0 and ranked[0].qty_match == 1.0


def test_inferred_po_gap_just_below_threshold_is_ambiguous(monkeypatch):
    import app.pipeline.po_match as po_match

    twin = PO_OPEN.__class__("PO-2026-1005", "V1", PO_OPEN.po_date, "open", PO_OPEN.taxable_value, D("0.00"), PO_OPEN.lines)
    r = repo(pos=[PO_OPEN, twin])
    real_score = po_match.score_po

    def scored(inv, po):  # best 0.90, second 0.751 -> gap 0.149, just below 0.15
        cand = real_score(inv, po)
        cand.score = 0.90 if po.po_number == "PO-2026-1001" else 0.751
        return cand

    monkeypatch.setattr(po_match, "score_po", scored)
    _, _, checks, _ = run_po_match(invoice(po_reference=None), INTRA, r, SETTINGS)
    assert codes(checks) == {"PO_AMBIGUOUS"}

    def scored_ok(inv, po):  # gap exactly 0.15 -> inferred
        cand = real_score(inv, po)
        cand.score = 0.90 if po.po_number == "PO-2026-1001" else 0.75
        return cand

    monkeypatch.setattr(po_match, "score_po", scored_ok)
    assert codes(run_po_match(invoice(po_reference=None), INTRA, r, SETTINGS)[2]) == {"PO_INFERRED"}


def test_po_not_found_when_nothing_fits():
    inv = invoice(po_reference=None, lines=[{"description": "Garden Maintenance", "quantity": 1, "unit_price": 900.0,
                                             "tax_rate": 18}])
    assert codes(run_po_match(inv, INTRA, repo(), SETTINGS)[2]) == {"PO_NOT_FOUND"}
    assert score_po(inv, PO_OPEN).item_similarity == 0.0


# ---------------------------------------------------------------- stage 7: amounts


def test_tolerance_is_min_of_percent_and_absolute():
    assert tolerance(Decimal("10000"), SETTINGS) == Decimal("100.00")
    assert tolerance(Decimal("100000"), SETTINGS) == Decimal("500")


@pytest.mark.parametrize("price, expected", [
    ("10000.00", set()),
    ("10025.00", {"PRICE_VARIANCE_WITHIN_TOLERANCE"}),
    ("10100.00", {"PRICE_VARIANCE_WITHIN_TOLERANCE"}),  # 4 x 100 = 400 = exactly 1% of the 40,000 line value
    ("10100.01", {"PRICE_VARIANCE_OVER_TOLERANCE"}),
    ("9900.00", set()),  # cheaper than the PO is fine
])
def test_unit_price_tolerance_boundary(price, expected):
    inv = invoice(lines=[{"description": "LED Monitor 24\" Full HD", "quantity": 4, "unit_price": float(price), "tax_rate": 18}])
    _, checks = run_amount_match(inv, PO_OPEN, SETTINGS)
    assert codes(checks) == expected


def test_item_not_on_po_and_quantity_exceeded():
    inv = invoice(lines=[{"description": "LED Monitor 24\" Full HD", "quantity": 5, "unit_price": 10000.0, "tax_rate": 18},
                         {"description": "Garden Maintenance", "quantity": 1, "unit_price": 900.0, "tax_rate": 18}])
    _, checks = run_amount_match(inv, PO_OPEN, SETTINGS)
    assert codes(checks) == {"QTY_EXCEEDS_PO", "ITEM_NOT_ON_PO"}


def test_po_overrun_uses_billing_history_and_tolerance():
    # 44,000 already billed on a 50,000 PO: 120 boxes x 50 = 6,000 fits exactly; 6,500 (+500 tolerance) still fits
    exact = invoice(INTER, po_reference="PO-2026-1002", lines=[{"description": "Corrugated Box 5-Ply 18x12x12 in",
                                                                "quantity": 120, "unit_price": 50.0, "tax_rate": 5}])
    assert codes(run_amount_match(exact, PO_PARTIAL, SETTINGS)[1]) == set()
    over = invoice(INTER, po_reference="PO-2026-1002", lines=[{"description": "Corrugated Box 5-Ply 18x12x12 in",
                                                               "quantity": 120, "unit_price": 50.0, "tax_rate": 5}],
                   subtotal=6500.01)
    assert "PO_OVERRUN" in codes(run_amount_match(over, PO_PARTIAL, SETTINGS)[1])


def test_fully_billed_po():
    inv = invoice(po_reference="PO-2026-1003", lines=[{"description": "Network Switch - 24 Port Gigabit", "quantity": 1,
                                                       "unit_price": 20000.0, "tax_rate": 18}])
    result = run_rules(inv, verification(inv), repo(), SETTINGS)
    assert result.decision.outcome == "REJECT"
    assert {"PO_CLOSED", "QTY_EXCEEDS_PO", "PO_OVERRUN"} <= set(result.codes)


# ---------------------------------------------------------------- stage 8: decision


def test_clean_invoice_is_approved_with_ledger_update():
    inv = invoice()
    result = run_rules(inv, verification(inv), repo(), SETTINGS)
    d = result.decision
    assert d.outcome == "APPROVE" and not d.approve_with_note and d.reasons == []
    assert d.ledger_update.po_number == "PO-2026-1001"
    assert [(l.po_line_no, l.quantity) for l in d.ledger_update.lines] == [(1, 1.0)]
    assert d.ledger_update.history_row["invoice_number"] == "INV-2001"


def test_info_codes_approve_with_note():
    inv = invoice(lines=[{"description": "LED Monitor 24\" Full HD", "quantity": 4, "unit_price": 10020.0, "tax_rate": 18}])
    d = run_rules(inv, verification(inv), repo(), SETTINGS).decision
    assert d.outcome == "APPROVE" and d.approve_with_note and "within tolerance" in d.summary


def test_hold_routes_one_question_per_role():
    inv = invoice(bank_account="50100999999999", lines=[{"description": "LED Monitor 24\" Full HD", "quantity": 4,
                                                         "unit_price": 10600.0, "tax_rate": 18}])
    d = run_rules(inv, verification(inv), repo(), SETTINGS).decision
    assert d.outcome == "HOLD" and d.vendor_note is None and d.ledger_update is None
    roles = {q.role: q for q in d.routed_questions}
    assert set(roles) == {"Finance controller", "Buyer"}
    assert "known contact" in roles["Finance controller"].question
    assert roles["Buyer"].codes == ["PRICE_VARIANCE_OVER_TOLERANCE"]


def test_reject_beats_hold_and_vendor_note_says_what_to_fix():
    inv = invoice(INTRA, intra=False, bank_account="50100999999999")
    d = run_rules(inv, verification(inv), repo(), SETTINGS).decision
    assert d.outcome == "REJECT" and d.routed_questions == []
    assert {c.code for c in d.reasons} >= {"GST_TYPE_INVALID", "BANK_DETAILS_MISMATCH"}
    assert d.reasons[0].severity == "REJECT"  # rejects listed first
    note = d.vendor_note
    assert note.startswith("Dear Sharma IT Solutions Private Limited") and "INV-2001" in note
    assert "reissue the invoice charging CGST + SGST instead of IGST" in note
    assert "bank" not in note.lower().split("to resolve")[1]  # internal fraud checks are not shared with the vendor


def test_engine_is_pure_and_lists_every_stage():
    inv = invoice()
    first = run_rules(inv, verification(inv), repo(), SETTINGS)
    second = run_rules(inv, verification(inv), repo(), SETTINGS)
    assert first.decision == second.decision  # same inputs, same decision (only timings differ)
    assert [s.stage for s in first.stages] == ["self_check", "vendor_duplicate", "po_match", "amount_match", "decision"]


def test_settings_change_the_rules():
    inv = invoice(lines=[{"description": "LED Monitor 24\" Full HD", "quantity": 4, "unit_price": 10020.0, "tax_rate": 18}])
    strict = Settings(_env_file=None, tolerance_abs_inr=50)
    assert run_rules(inv, verification(inv), repo(), strict).decision.outcome == "HOLD"


def test_lines_short_of_the_subtotal_could_be_a_missed_line_so_only_hold():
    """A live Groq run dropped a line: lines summed below a verified subtotal. That must Hold, not Reject."""
    from app.schemas import FieldVerification

    lines = [{"description": "Laptop - Intel Core i5, 16GB RAM, 512GB SSD", "quantity": 1, "unit_price": 60000.0,
              "tax_rate": 18}]
    short = invoice(lines=lines, subtotal=100000.0, total_amount=118000.0, cgst=9000.0, sgst=9000.0)
    ver = verification(short)
    ver.line_items = [FieldVerification(status="verified")]
    assert codes([check_lines_sum(short, ver, 0.8)]) == {"ARITHMETIC_UNCERTAIN"}
    over_lines = [{**lines[0], "amount": 70000.0}]
    excess = invoice(lines=over_lines, subtotal=60000.0, total_amount=70800.0, cgst=5400.0, sgst=5400.0)
    ver = verification(excess)
    ver.line_items = [FieldVerification(status="verified")]
    assert codes([check_lines_sum(excess, ver, 0.8)]) == {"ARITHMETIC_MISMATCH"}
    ver.line_items = [FieldVerification(status="not_found")]  # the AI's line amount is not on the page
    assert codes([check_lines_sum(excess, ver, 0.8)]) == {"ARITHMETIC_UNCERTAIN"}
