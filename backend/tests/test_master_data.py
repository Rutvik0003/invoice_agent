"""Tests for datagen.master_data: generated world, reproducibility, and Phase 2 scenario helpers."""

import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal

import pytest

from datagen.catalog import CATALOG
from datagen.gstin import validate_gstin
from datagen.master_data import (
    PO_PERIOD_END,
    PO_PERIOD_START,
    REFERENCE_DATE,
    HistoryLine,
    build_master,
    compute_invoice_totals,
    write_master,
)
from datagen.validate_master import load_master, run_checks


@pytest.fixture(scope="module")
def md():
    return build_master()


def test_same_seed_gives_identical_output(tmp_path):
    write_master(build_master(7), tmp_path / "a")
    write_master(build_master(7), tmp_path / "b")
    for name in ("buyer.json", "vendors.csv", "po_headers.csv", "po_lines.csv", "invoice_history.csv"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_different_seed_gives_different_vendors():
    assert build_master(1).vendors[0].legal_name != build_master(2).vendors[0].legal_name


def test_buyer_is_zenith_in_maharashtra(md):
    assert md.buyer.legal_name == "Zenith Retail Pvt Ltd"
    assert md.buyer.state_code == "27" and md.buyer.gstin.startswith("27")
    assert validate_gstin(md.buyer.gstin)


def test_vendor_mix(md):
    assert len(md.vendors) == 40
    assert Counter(v.status for v in md.vendors) == {"approved": 34, "pending": 3, "blocked": 3}
    assert len({v.state_code for v in md.vendors}) >= 12
    assert sum(v.is_intra_state for v in md.vendors) == 12  # 30% Maharashtra
    assert len({v.legal_name for v in md.vendors}) == 40
    assert any(v.legal_name != v.trade_name for v in md.vendors)
    assert len({v.category for v in md.vendors}) == len(CATALOG)


def test_purchase_orders(md):
    assert len(md.pos) == 200
    for po in md.pos:
        assert re.fullmatch(r"PO-2026-\d{4}", po.po_number)
        assert PO_PERIOD_START <= po.po_date <= PO_PERIOD_END
        assert 1 <= len(po.lines) <= 8
        assert {line.description for line in po.lines} <= {i.description for i in CATALOG[md.vendor_of(po).category]}
    assert set(Counter(po.status for po in md.pos)) == {"open", "partially_billed", "closed"}
    assert not any(md.vendor_of(po).status == "pending" for po in md.pos)


def test_history(md):
    assert 350 <= len(md.history) <= 450
    for inv in md.history:
        po = md.po(inv.po_number)
        assert po.po_date < inv.invoice_date < REFERENCE_DATE
        assert inv.vendor_id == po.vendor_id
    styles = {md.vendor(inv.vendor_id).invoice_style for inv in md.history}
    assert len(styles) >= 5


def test_generated_master_passes_all_consistency_checks(md, tmp_path):
    write_master(md, tmp_path)
    failed = [o for o in run_checks(load_master(tmp_path)) if not o.passed]
    assert failed == []


def test_compute_invoice_totals_intra_and_inter_state():
    lines = [HistoryLine(1, "Item", "8471", 3, "Nos", Decimal("1000.15"), 18.0)]
    intra = compute_invoice_totals(lines, intra_state=True)
    assert intra["taxable_value"] == Decimal("3000.45")
    assert intra["cgst"] == intra["sgst"] == Decimal("270.04")
    assert intra["igst"] == 0
    assert intra["total_amount"] == Decimal("3541.00")
    assert intra["round_off"] == Decimal("0.47")
    inter = compute_invoice_totals(lines, intra_state=False)
    assert inter["igst"] == Decimal("540.08") and inter["cgst"] == 0
    assert inter["taxable_value"] + inter["igst"] + inter["round_off"] == inter["total_amount"]


def test_reserve_po_never_returns_the_same_po_twice():
    md = build_master()
    picked = {md.reserve_po().po_number for _ in range(20)}
    assert len(picked) == 20
    intra = md.reserve_po(statuses=("open",), intra_state=True)
    assert intra.status == "open" and md.vendor_of(intra).is_intra_state


def test_reserve_raises_when_nothing_matches():
    md = build_master()
    for _ in range(3):
        md.reserve_vendor(status="blocked")
    with pytest.raises(LookupError):
        md.reserve_vendor(status="blocked")


def test_scenario_helpers_keep_data_consistent(tmp_path):
    """Phase 2 flow: add a PO, bill it in parts, and the ledger, status and checks stay right."""
    md = build_master()
    vendor = md.reserve_vendor(status="approved", intra_state=False)
    item = CATALOG[vendor.category][0]
    po = md.add_po(vendor, date(2026, 9, 1), [(item, 10, Decimal("1500.00"))])
    assert po.status == "open"
    assert po not in [md.reserve_po() for _ in range(5)]

    first = md.bill(po, {1: 4}, date(2026, 9, 10))
    second = md.bill(po, {1: 4}, date(2026, 9, 20))
    assert po.status == "partially_billed" and po.lines[0].qty_remaining == 2
    assert first.invoice_number != second.invoice_number
    assert second.igst > 0 and second.cgst == 0

    with pytest.raises(ValueError):
        md.bill(po, {1: 3}, date(2026, 9, 25))  # only 2 left
    md.bill(po, {1: 2}, date(2026, 9, 28))
    assert po.status == "closed"

    write_master(md, tmp_path)
    assert all(o.passed for o in run_checks(load_master(tmp_path)))


def test_next_invoice_number_follows_vendor_style():
    md = build_master()
    vendor = md.vendors[0]
    on = REFERENCE_DATE - timedelta(days=1)
    numbers = [md.next_invoice_number(vendor, on) for _ in range(3)]
    assert len(set(numbers)) == 3
