"""Consistency checker for data/master: reads the CSVs as written and checks every business invariant.

Usage: python -m datagen.validate_master [--master-dir PATH]   (exit code 1 if any check fails)
"""

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Callable

from datagen.catalog import valid_gst_rates
from datagen.gstin import STATES, validate_bank_account, validate_gstin, validate_ifsc

MASTER_DIR = Path(__file__).resolve().parents[1] / "data" / "master"
TOLERANCE = Decimal("1.00")  # ₹1 for rounding
ZERO = Decimal("0")


@dataclass
class Master:
    buyer: dict
    vendors: list[dict]
    po_headers: list[dict]
    po_lines: list[dict]
    history: list[dict]

    def __post_init__(self) -> None:
        self.vendor_by_id = {v["vendor_id"]: v for v in self.vendors}
        self.po_by_number = {p["po_number"]: p for p in self.po_headers}
        self.lines_by_po: dict[str, list[dict]] = defaultdict(list)
        for line in self.po_lines:
            self.lines_by_po[line["po_number"]].append(line)


@dataclass
class CheckOutcome:
    name: str
    checked: int
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_master(master_dir: Path = MASTER_DIR) -> Master:
    return Master(
        buyer=json.loads((master_dir / "buyer.json").read_text(encoding="utf-8")),
        vendors=_read_csv(master_dir / "vendors.csv"),
        po_headers=_read_csv(master_dir / "po_headers.csv"),
        po_lines=_read_csv(master_dir / "po_lines.csv"),
        history=_read_csv(master_dir / "invoice_history.csv"),
    )


def _history_lines(invoice: dict) -> list[dict]:
    return json.loads(invoice["lines_json"])


# ---------------------------------------------------------------- checks


def check_gstins_valid(m: Master) -> CheckOutcome:
    """Every vendor and buyer GSTIN has a valid format and checksum."""
    outcome = CheckOutcome("GSTINs valid (format + checksum)", len(m.vendors) + 1)
    for party, gstin in [("buyer", m.buyer["gstin"])] + [(v["vendor_id"], v["gstin"]) for v in m.vendors]:
        if not validate_gstin(gstin):
            outcome.failures.append(f"{party}: invalid GSTIN {gstin}")
    return outcome


def check_vendor_state_matches_gstin(m: Master) -> CheckOutcome:
    """A vendor's state code, state name and PAN agree with its GSTIN."""
    outcome = CheckOutcome("Vendor state and PAN match GSTIN", len(m.vendors))
    for v in m.vendors:
        if v["gstin"][:2] != v["state_code"] or STATES.get(v["state_code"]) != v["state"]:
            outcome.failures.append(f"{v['vendor_id']}: state {v['state_code']}/{v['state']} vs GSTIN {v['gstin']}")
        if v["gstin"][2:12] != v["pan"]:
            outcome.failures.append(f"{v['vendor_id']}: PAN {v['pan']} not inside GSTIN {v['gstin']}")
    return outcome


def check_bank_details_format(m: Master) -> CheckOutcome:
    """Every vendor has a well-formed IFSC and a 9-18 digit account number."""
    outcome = CheckOutcome("Vendor bank details well-formed", len(m.vendors))
    for v in m.vendors:
        if not validate_ifsc(v["ifsc"]) or not validate_bank_account(v["bank_account"]):
            outcome.failures.append(f"{v['vendor_id']}: IFSC {v['ifsc']} / account {v['bank_account']}")
    return outcome


def check_references(m: Master) -> CheckOutcome:
    """Every PO line belongs to an existing PO; every PO and invoice to an existing vendor (the PO's own)."""
    outcome = CheckOutcome("PO lines, POs and invoices reference existing records", len(m.po_lines) + len(m.history))
    for line in m.po_lines:
        if line["po_number"] not in m.po_by_number:
            outcome.failures.append(f"PO line {line['po_number']}#{line['line_no']}: unknown PO")
    for po in m.po_headers:
        if po["vendor_id"] not in m.vendor_by_id:
            outcome.failures.append(f"{po['po_number']}: unknown vendor {po['vendor_id']}")
        if not m.lines_by_po.get(po["po_number"]):
            outcome.failures.append(f"{po['po_number']}: has no lines")
    for inv in m.history:
        po = m.po_by_number.get(inv["po_number"])
        if inv["vendor_id"] not in m.vendor_by_id:
            outcome.failures.append(f"{inv['history_id']}: unknown vendor {inv['vendor_id']}")
        elif po is None:
            outcome.failures.append(f"{inv['history_id']}: unknown PO {inv['po_number']}")
        elif po["vendor_id"] != inv["vendor_id"]:
            outcome.failures.append(f"{inv['history_id']}: vendor {inv['vendor_id']} but PO belongs to {po['vendor_id']}")
    return outcome


def check_po_totals(m: Master) -> CheckOutcome:
    """PO header values equal the sum of their lines, and remaining = value - billed."""
    outcome = CheckOutcome("PO header totals match their lines", len(m.po_headers))
    for po in m.po_headers:
        lines = m.lines_by_po[po["po_number"]]
        value = sum((Decimal(l["line_value"]) for l in lines), ZERO)
        billed = sum((Decimal(l["qty_billed"]) * Decimal(l["unit_price"]) for l in lines), ZERO)
        if abs(value - Decimal(po["taxable_value"])) > TOLERANCE or abs(billed - Decimal(po["billed_value"])) > TOLERANCE:
            outcome.failures.append(f"{po['po_number']}: header value/billed disagree with lines")
        if Decimal(po["remaining_value"]) != Decimal(po["taxable_value"]) - Decimal(po["billed_value"]):
            outcome.failures.append(f"{po['po_number']}: remaining_value != taxable_value - billed_value")
        for l in lines:
            if Decimal(l["qty_remaining"]) != Decimal(l["qty_ordered"]) - Decimal(l["qty_billed"]):
                outcome.failures.append(f"{po['po_number']}#{l['line_no']}: qty_remaining wrong")
    return outcome


def check_ledger_matches_history(m: Master) -> CheckOutcome:
    """Billed quantity on each PO line equals the quantities billed by invoices in history."""
    outcome = CheckOutcome("PO ledger (qty billed) matches invoice history", len(m.po_lines))
    billed: Counter = Counter()
    for inv in m.history:
        for hl in _history_lines(inv):
            billed[(inv["po_number"], int(hl["po_line_no"]))] += Decimal(str(hl["quantity"]))
    for line in m.po_lines:
        key = (line["po_number"], int(line["line_no"]))
        if billed[key] != Decimal(line["qty_billed"]):
            outcome.failures.append(f"{key[0]}#{key[1]}: ledger {line['qty_billed']} vs history {billed[key]}")
    return outcome


def check_billed_within_po_value(m: Master) -> CheckOutcome:
    """Total billed (taxable) per PO never exceeds the PO value."""
    outcome = CheckOutcome("Billed total per PO <= PO value", len(m.po_headers))
    billed: Counter = Counter()
    for inv in m.history:
        billed[inv["po_number"]] += Decimal(inv["taxable_value"])
    for po in m.po_headers:
        if billed[po["po_number"]] > Decimal(po["taxable_value"]) + TOLERANCE:
            outcome.failures.append(f"{po['po_number']}: billed {billed[po['po_number']]} > value {po['taxable_value']}")
    return outcome


def check_po_status(m: Master) -> CheckOutcome:
    """Closed POs are fully billed, open POs have nothing billed, partially billed POs are in between."""
    outcome = CheckOutcome("PO status consistent with billing", len(m.po_headers))
    for po in m.po_headers:
        lines = m.lines_by_po[po["po_number"]]
        nothing = all(Decimal(l["qty_billed"]) == 0 for l in lines)
        everything = all(Decimal(l["qty_remaining"]) == 0 for l in lines)
        expected = "open" if nothing else "closed" if everything else "partially_billed"
        if po["status"] != expected:
            outcome.failures.append(f"{po['po_number']}: status {po['status']} but billing says {expected}")
    return outcome


def check_invoice_dates(m: Master) -> CheckOutcome:
    """Every past invoice is dated after its PO, and paid invoices are paid after they were issued."""
    outcome = CheckOutcome("Invoice dates after PO dates", len(m.history))
    for inv in m.history:
        inv_date = date.fromisoformat(inv["invoice_date"])
        po = m.po_by_number.get(inv["po_number"])
        if po and inv_date <= date.fromisoformat(po["po_date"]):
            outcome.failures.append(f"{inv['history_id']}: dated {inv_date} on/before PO date {po['po_date']}")
        if inv["status"] == "paid" and (not inv["payment_date"] or date.fromisoformat(inv["payment_date"]) <= inv_date):
            outcome.failures.append(f"{inv['history_id']}: paid without a payment date after the invoice date")
    return outcome


def check_unique_invoice_numbers(m: Master) -> CheckOutcome:
    """No vendor has the same invoice number twice in history."""
    outcome = CheckOutcome("No duplicate invoice numbers per vendor", len(m.history))
    counts = Counter((inv["vendor_id"], inv["invoice_number"]) for inv in m.history)
    for (vendor_id, number), count in counts.items():
        if count > 1:
            outcome.failures.append(f"{vendor_id}: invoice number {number} appears {count} times")
    return outcome


def check_gst_rates_for_dates(m: Master) -> CheckOutcome:
    """Every GST rate on a PO line or past invoice line was a legal slab on that document's date."""
    outcome = CheckOutcome("GST rates valid for their dates", len(m.po_lines) + len(m.history))
    for line in m.po_lines:
        po_date = date.fromisoformat(m.po_by_number[line["po_number"]]["po_date"]) if line["po_number"] in m.po_by_number else None
        if po_date and float(line["gst_rate"]) not in valid_gst_rates(po_date):
            outcome.failures.append(f"{line['po_number']}#{line['line_no']}: {line['gst_rate']}% not valid on {po_date}")
    for inv in m.history:
        inv_date = date.fromisoformat(inv["invoice_date"])
        for hl in _history_lines(inv):
            if float(hl["gst_rate"]) not in valid_gst_rates(inv_date):
                outcome.failures.append(f"{inv['history_id']}: {hl['gst_rate']}% not valid on {inv_date}")
    return outcome


def check_history_arithmetic(m: Master) -> CheckOutcome:
    """Each past invoice adds up: lines = taxable value, taxable + GST + round-off = total, |round-off| <= ₹0.50."""
    outcome = CheckOutcome("Past invoices add up", len(m.history))
    for inv in m.history:
        lines_total = sum((Decimal(hl["amount"]) for hl in _history_lines(inv)), ZERO)
        taxable = Decimal(inv["taxable_value"])
        computed = taxable + sum(Decimal(inv[k]) for k in ("cgst", "sgst", "igst", "round_off"))
        if abs(lines_total - taxable) > TOLERANCE or abs(computed - Decimal(inv["total_amount"])) > TOLERANCE:
            outcome.failures.append(f"{inv['history_id']}: totals do not add up")
        if abs(Decimal(inv["round_off"])) > Decimal("0.50"):
            outcome.failures.append(f"{inv['history_id']}: round-off {inv['round_off']} too large")
    return outcome


def check_history_gst_type(m: Master) -> CheckOutcome:
    """Same-state vendors charge CGST + SGST (equal halves); other states charge IGST only."""
    outcome = CheckOutcome("Past invoices use the right GST type", len(m.history))
    buyer_state = m.buyer["state_code"]
    for inv in m.history:
        vendor = m.vendor_by_id.get(inv["vendor_id"])
        if vendor is None:
            continue
        cgst, sgst, igst = (Decimal(inv[k]) for k in ("cgst", "sgst", "igst"))
        if vendor["state_code"] == buyer_state:
            ok = igst == 0 and cgst == sgst
        else:
            ok = cgst == 0 and sgst == 0
        if not ok:
            outcome.failures.append(f"{inv['history_id']}: wrong GST type for vendor in state {vendor['state_code']}")
    return outcome


CHECKS: list[Callable[[Master], CheckOutcome]] = [
    check_gstins_valid,
    check_vendor_state_matches_gstin,
    check_bank_details_format,
    check_references,
    check_po_totals,
    check_ledger_matches_history,
    check_billed_within_po_value,
    check_po_status,
    check_invoice_dates,
    check_unique_invoice_numbers,
    check_gst_rates_for_dates,
    check_history_arithmetic,
    check_history_gst_type,
]


def run_checks(m: Master) -> list[CheckOutcome]:
    return [check(m) for check in CHECKS]


def summary_lines(m: Master) -> list[str]:
    vendor_status = Counter(v["status"] for v in m.vendors)
    po_status = Counter(p["status"] for p in m.po_headers)
    states = {v["state_code"] for v in m.vendors}
    maharashtra = sum(v["state_code"] == m.buyer["state_code"] for v in m.vendors)
    return [
        f"Vendors:         {len(m.vendors)}  ({', '.join(f'{k} {n}' for k, n in sorted(vendor_status.items()))}; "
        f"{len(states)} states, {maharashtra} in Maharashtra)",
        f"POs:             {len(m.po_headers)}  ({', '.join(f'{k} {n}' for k, n in sorted(po_status.items()))}); "
        f"{len(m.po_lines)} lines",
        f"Invoice history: {len(m.history)}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master-dir", type=Path, default=MASTER_DIR)
    args = parser.parse_args()
    m = load_master(args.master_dir)
    outcomes = run_checks(m)
    width = max(len(o.name) for o in outcomes)
    print(f"{'Check':<{width}}  Result  Checked")
    print("-" * (width + 18))
    for o in outcomes:
        print(f"{o.name:<{width}}  {'PASS' if o.passed else 'FAIL':<6}  {o.checked:>7}")
        for failure in o.failures[:5]:
            print(f"    - {failure}")
        if len(o.failures) > 5:
            print(f"    ... and {len(o.failures) - 5} more")
    print()
    print("\n".join(summary_lines(m)))
    failed = sum(not o.passed for o in outcomes)
    print(f"\n{len(outcomes) - failed}/{len(outcomes)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
