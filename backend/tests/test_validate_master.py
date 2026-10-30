"""Tests for datagen.validate_master: each check catches the inconsistency it is meant to catch."""

import json

import pytest

from datagen.master_data import build_master, write_master
from datagen.validate_master import (
    check_billed_within_po_value,
    check_gst_rates_for_dates,
    check_gstins_valid,
    check_history_gst_type,
    check_ledger_matches_history,
    check_po_status,
    check_references,
    check_unique_invoice_numbers,
    check_vendor_state_matches_gstin,
    load_master,
    run_checks,
)


@pytest.fixture(scope="module")
def master_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("master")
    write_master(build_master(), path)
    return path


@pytest.fixture
def m(master_dir):
    return load_master(master_dir)  # fresh copy per test, safe to tamper with


def test_clean_data_passes_everything(m):
    assert all(o.passed for o in run_checks(m))


def test_bad_gstin_checksum_is_caught(m):
    gstin = m.vendors[0]["gstin"]
    m.vendors[0]["gstin"] = gstin[:14] + ("A" if gstin[14] != "A" else "B")
    assert not check_gstins_valid(m).passed


def test_state_mismatch_is_caught(m):
    m.vendors[0]["state_code"] = "07" if m.vendors[0]["state_code"] != "07" else "27"
    assert not check_vendor_state_matches_gstin(m).passed


def test_orphan_po_line_is_caught(m):
    m.po_lines.append({**m.po_lines[0], "po_number": "PO-2026-9999"})
    assert not check_references(m).passed


def test_closed_po_with_remaining_quantity_is_caught(m):
    closed = next(p for p in m.po_headers if p["status"] == "closed")
    line = m.lines_by_po[closed["po_number"]][0]
    line["qty_billed"] = str(int(line["qty_billed"]) - 1)
    line["qty_remaining"] = "1"
    assert not check_po_status(m).passed
    assert not check_ledger_matches_history(m).passed


def test_overbilling_is_caught(m):
    invoice = m.history[0]
    invoice["taxable_value"] = str(float(m.po_by_number[invoice["po_number"]]["taxable_value"]) * 2)
    assert not check_billed_within_po_value(m).passed


def test_duplicate_invoice_number_is_caught(m):
    first = m.history[0]
    other = next(h for h in m.history[1:] if h["vendor_id"] == first["vendor_id"])
    other["invoice_number"] = first["invoice_number"]
    assert not check_unique_invoice_numbers(m).passed


def test_12_percent_after_gst_2_0_is_caught(m):
    invoice = m.history[0]
    lines = json.loads(invoice["lines_json"])
    lines[0]["gst_rate"] = 12.0
    invoice["lines_json"] = json.dumps(lines)
    assert not check_gst_rates_for_dates(m).passed


def test_wrong_gst_type_is_caught(m):
    intra = next(h for h in m.history if m.vendor_by_id[h["vendor_id"]]["state_code"] == "27")
    intra["igst"], intra["cgst"], intra["sgst"] = "100.00", "0.00", "0.00"
    assert not check_history_gst_type(m).passed
