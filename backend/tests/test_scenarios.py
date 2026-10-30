"""Tests for datagen.scenarios: every scenario really sets up the situation its expected outcome claims.

These checks are independent arithmetic on the generated data (they never call a decision engine).
"""

from collections import Counter, defaultdict
from decimal import Decimal

import pytest

from datagen.master_data import DEFAULT_SEED, build_master, write_master
from datagen.scenarios import (
    STRESS_COUNTS,
    Planner,
    disguise_invoice_number,
    normalise_invoice_number,
    plan_golden,
    plan_stress,
)
from datagen.validate_master import load_master, run_checks

GOLDEN_IDS = [
    "01_happy_clean", "02_happy_tolerance", "03_A_split_overrun", "04_B_duplicate", "05_C_no_po", "06_D_bank_change",
    "07_E_wrong_gst", "08_F_blurry_scan", "09_G_price_variance", "10_H_bad_maths", "11_I_quotation",
    "12_J_unapproved_vendor",
]


@pytest.fixture(scope="module")
def world():
    md = build_master()
    planner = Planner(md, DEFAULT_SEED)
    golden = plan_golden(planner)
    stress = plan_stress(planner)
    return md, golden, stress


def by_scenario(items):
    groups = defaultdict(list)
    for item in items:
        groups[item.scenario].append(item)
    return groups


def billed_before(md, po_number):
    return sum((h.taxable_value for h in md.history if h.po_number == po_number), Decimal("0"))


@pytest.mark.parametrize("number", ["KOS-0457", "INV-00457", "SIT/26-27/0881", "2026/KOS/57", "BW1234", "1457", "GT/045/26"])
def test_disguised_numbers_look_different_but_normalise_the_same(number):
    import random

    rng = random.Random(1)
    for _ in range(10):
        disguised = disguise_invoice_number(number, rng)
        assert disguised != number
        assert normalise_invoice_number(disguised) == normalise_invoice_number(number)


def test_golden_set_is_exactly_the_twelve_cases(world):
    _, golden, _ = world
    assert [g.spec.invoice_id for g in golden] == GOLDEN_IDS
    expected = ["APPROVE", "APPROVE", "HOLD", "REJECT", "HOLD", "HOLD", "REJECT", "HOLD", "HOLD", "REJECT", "REJECT", "HOLD"]
    assert [g.expected_decision for g in golden] == expected
    assert len({g.spec.template for g in golden}) == 8


def test_stress_counts_match_the_scenario_table(world):
    _, _, stress = world
    assert Counter(s.scenario for s in stress) == STRESS_COUNTS
    assert [s.spec.invoice_id for s in stress] == [f"S{i:04d}" for i in range(1, len(stress) + 1)]
    mild = sum(s.scan == "mild" for s in stress)
    assert 0.25 <= mild / len(stress) <= 0.40


def test_master_data_stays_consistent_after_scenarios(world, tmp_path):
    md, _, _ = world
    write_master(md, tmp_path)
    assert all(o.passed for o in run_checks(load_master(tmp_path)))


def test_clean_invoices_match_their_po_exactly(world):
    md, golden, stress = world
    for item in by_scenario(golden + stress)["CLEAN_EXACT"]:
        po = md.po(item.true_po_number)
        assert item.spec.po_reference.replace("/", "-") == po.po_number
        assert md.vendor_of(po).status == "approved"
        for line in item.spec.lines:
            po_line = po.line(line.po_line_no)
            assert line.unit_price == po_line.unit_price
            assert line.quantity <= po_line.qty_remaining
        assert item.spec.bank_account == md.vendor_of(po).bank_account
        assert item.spec.buyer.gstin == md.buyer.gstin
        assert item.spec.invoice_date > po.po_date
        same_vendor_totals = {h.total_amount for h in md.history if h.vendor_id == po.vendor_id}
        assert item.spec.total_amount not in same_vendor_totals


def test_totals_add_up_except_in_arithmetic_scenarios(world):
    _, golden, stress = world
    for item in golden + stress:
        s = item.spec
        lines_ok = abs(sum(l.amount for l in s.lines) - s.subtotal) <= 1
        total_ok = abs(s.subtotal - s.discount + s.other_charges + s.cgst + s.sgst + s.igst + (s.round_off or 0) - s.total_amount) <= 1
        broken = "ARITHMETIC_MISMATCH" in item.expected_reason_codes
        assert (lines_ok and total_ok) != broken, item.spec.invoice_id


def test_within_tolerance_and_over_tolerance_prices(world):
    md, golden, stress = world
    groups = by_scenario(golden + stress)
    for item in groups["CLEAN_WITHIN_TOLERANCE"]:
        po = md.po(item.true_po_number)
        diffs = [(l.unit_price - po.line(l.po_line_no).unit_price, l) for l in item.spec.lines]
        changed = [(d, l) for d, l in diffs if d]
        assert len(changed) == 1
        diff, line = changed[0]
        line_diff = diff * line.quantity
        assert 0 < line_diff <= min(line.correct_amount * Decimal("0.01"), Decimal("500"))
        assert diff / po.line(line.po_line_no).unit_price < Decimal("0.01")
    for item in groups["PRICE_OVER_TOLERANCE"]:
        po = md.po(item.true_po_number)
        pcts = [(l.unit_price / po.line(l.po_line_no).unit_price - 1) * 100 for l in item.spec.lines]
        assert max(pcts) >= Decimal("2.9")


def test_overruns_really_exceed_the_po(world):
    md, golden, stress = world
    for item in by_scenario(golden + stress)["PO_OVERRUN"]:
        po = md.po(item.true_po_number)
        before = billed_before(md, po.po_number)
        assert before >= po.taxable_value * Decimal("0.85")
        assert before + item.spec.subtotal > po.taxable_value + Decimal("500")


def test_duplicates_point_at_a_real_history_row(world):
    md, golden, stress = world
    groups = by_scenario(golden + stress)
    for item in groups["DUPLICATE_EXACT_NUMBER"] + groups["DUPLICATE_DISGUISED_NUMBER"]:
        vendor_id = md.po(item.true_po_number).vendor_id
        matches = [h for h in md.history if h.vendor_id == vendor_id
                   and normalise_invoice_number(h.invoice_number) == normalise_invoice_number(item.spec.invoice_number)]
        assert len(matches) == 1
        if item.scenario == "DUPLICATE_DISGUISED_NUMBER":
            assert matches[0].invoice_number != item.spec.invoice_number
    golden_dup = next(g for g in golden if g.spec.invoice_id == "04_B_duplicate")
    assert "/" in golden_dup.spec.invoice_number


def test_possible_duplicates_share_vendor_and_total_within_three_days(world):
    md, _, stress = world
    for item in by_scenario(stress)["POSSIBLE_DUPLICATE"]:
        vendor_id = md.po(item.true_po_number).vendor_id
        close = [h for h in md.history if h.vendor_id == vendor_id and h.total_amount == item.spec.total_amount
                 and abs((h.invoice_date - item.spec.invoice_date).days) <= 2]
        assert close and all(h.invoice_number != item.spec.invoice_number for h in close)


def test_no_po_invoices_print_no_po_and_the_true_po_is_the_only_item_match(world):
    md, golden, stress = world
    groups = by_scenario(golden + stress)
    for item in groups["NO_PO_CLEAR_MATCH"] + groups["NO_PO_AMBIGUOUS"]:
        assert item.spec.po_reference is None
        vendor_id = next(v.vendor_id for v in md.vendors if v.gstin == item.spec.vendor.gstin)
        items = {l.description for l in item.spec.lines}
        matching = [p for p in md.pos if p.vendor_id == vendor_id and p.status != "closed"
                    and items <= {l.description for l in p.lines}]
        assert len(matching) == (1 if item.scenario == "NO_PO_CLEAR_MATCH" else 2)
        if item.scenario == "NO_PO_CLEAR_MATCH":
            assert matching[0].po_number == item.true_po_number
    golden_no_po = next(g for g in golden if g.spec.invoice_id == "05_C_no_po")
    vendor_id = md.po(golden_no_po.true_po_number).vendor_id
    assert sum(p.status != "closed" for p in md.pos if p.vendor_id == vendor_id) == 2


def test_gst_and_vendor_scenarios(world):
    md, golden, stress = world
    groups = by_scenario(golden + stress)
    for item in groups["GST_WRONG_TYPE"]:
        intra = item.spec.vendor.state_code == md.buyer.state_code
        assert (item.spec.tax_split == "igst") == intra  # the opposite of the rule
    for item in groups["GST_RATE_UNUSUAL"]:
        assert any(l.gst_rate in (12.0, 28.0) for l in item.spec.lines)
    statuses = {v.gstin: v.status for v in md.vendors}
    assert all(statuses[i.spec.vendor.gstin] == "pending" for i in groups["VENDOR_NOT_APPROVED"])
    assert all(statuses[i.spec.vendor.gstin] == "blocked" for i in groups["VENDOR_BLOCKED"])
    assert all(i.spec.vendor.gstin not in statuses for i in groups["VENDOR_UNKNOWN"])
    assert all(i.spec.buyer.gstin != md.buyer.gstin for i in groups["BUYER_MISMATCH"])
    assert all(md.po(i.true_po_number).status == "closed" for i in groups["PO_CLOSED"])
    assert all(i.spec.invoice_number is None for i in groups["MISSING_INVOICE_NUMBER"])
    assert all(i.spec.document_type != "tax_invoice" for i in groups["NOT_AN_INVOICE"])


def test_bank_change_and_obscured_fields(world):
    md, golden, stress = world
    groups = by_scenario(golden + stress)
    accounts = {v.gstin: v.bank_account for v in md.vendors}
    assert all(i.spec.bank_account != accounts[i.spec.vendor.gstin] for i in groups["BANK_CHANGE"])
    for name in ("HEAVY_SCAN_LOW_CONFIDENCE", "OBSCURED_INVOICE_NUMBER", "OBSCURED_GSTIN"):
        for item in groups[name]:
            assert item.expected_decision == "HOLD" and item.acceptable_decisions == ["HOLD"]
            assert item.expected_reason_codes_any_of == [["FIELD_NOT_VERIFIED", "LOW_CONFIDENCE_FIELD"]]
            signals = item.rules_eval_signals()
            for field_name in item.obscured_fields:
                assert signals[field_name] == {"confidence": 0.40, "verification_status": "not_found"}


def test_multi_issue_decision_follows_severity(world):
    _, _, stress = world
    for item in by_scenario(stress)["MULTI_ISSUE"]:
        assert 2 <= len(item.expected_reason_codes) <= 3
        rejects = {"GST_TYPE_INVALID", "ARITHMETIC_MISMATCH"} & set(item.expected_reason_codes)
        assert item.expected_decision == ("REJECT" if rejects else "HOLD")
