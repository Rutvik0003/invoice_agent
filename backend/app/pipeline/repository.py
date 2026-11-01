"""Read-only access to master data for the rules engine.

The engine only sees the MasterRepository interface, so it runs unchanged on the database (live runs)
or on in-memory data loaded from data/master/*.csv (tests and the rules evaluation).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InvoiceHistory, POHeader, Run, Vendor
from app.pipeline.normalise import normalise_code, normalise_identifier


@dataclass(frozen=True)
class BuyerRecord:
    legal_name: str
    name_variants: tuple[str, ...]
    gstin: str
    state_code: str


@dataclass(frozen=True)
class VendorRecord:
    vendor_id: str
    legal_name: str
    trade_name: str
    gstin: str
    state_code: str
    status: str  # approved | pending | blocked
    bank_name: str
    bank_account: str
    ifsc: str


@dataclass(frozen=True)
class POLineRecord:
    line_no: int
    description: str
    unit: str
    qty_ordered: Decimal
    qty_billed: Decimal
    unit_price: Decimal
    gst_rate: Decimal

    @property
    def qty_remaining(self) -> Decimal:
        return self.qty_ordered - self.qty_billed

    @property
    def line_value(self) -> Decimal:
        return (self.qty_ordered * self.unit_price).quantize(Decimal("0.01"))


@dataclass(frozen=True)
class PORecord:
    po_number: str
    vendor_id: str
    po_date: date
    status: str  # open | partially_billed | closed
    taxable_value: Decimal
    billed_value: Decimal
    lines: tuple[POLineRecord, ...] = field(default_factory=tuple)

    @property
    def remaining_value(self) -> Decimal:
        return self.taxable_value - self.billed_value


@dataclass(frozen=True)
class ProcessedFile:
    """An earlier finished run of the same file: its id, its final decision and when it ran."""

    run_id: str
    decision: str | None  # APPROVE | HOLD | REJECT (a person's decision once a hold is resolved)
    created_at: datetime | None = None


@dataclass(frozen=True)
class HistoryRecord:
    history_id: str
    vendor_id: str
    invoice_number: str
    invoice_date: date
    po_number: str | None
    taxable_value: Decimal
    total_amount: Decimal
    status: str


class MasterRepository(Protocol):
    buyer: BuyerRecord

    def vendors(self) -> list[VendorRecord]: ...

    def vendor_by_gstin(self, gstin: str) -> VendorRecord | None: ...

    def po(self, po_number: str) -> PORecord | None: ...

    def open_pos_for_vendor(self, vendor_id: str) -> list[PORecord]: ...

    def history_for_vendor(self, vendor_id: str) -> list[HistoryRecord]: ...

    def processed_file(self, file_hash: str) -> ProcessedFile | None: ...


class InMemoryRepository:
    """Master data held in memory (from the CSVs). Each lookup treats the data as the seeded state."""

    def __init__(self, buyer: BuyerRecord, vendors: list[VendorRecord], pos: list[PORecord],
                 history: list[HistoryRecord], processed_hashes: dict[str, ProcessedFile] | None = None) -> None:
        self.buyer = buyer
        self._vendors = vendors
        self._by_gstin = {normalise_code(v.gstin): v for v in vendors}
        self._pos = {normalise_identifier(p.po_number): p for p in pos}
        self._history = history
        self._hashes = processed_hashes or {}

    def vendors(self) -> list[VendorRecord]:
        return list(self._vendors)

    def vendor_by_gstin(self, gstin: str) -> VendorRecord | None:
        return self._by_gstin.get(normalise_code(gstin))

    def po(self, po_number: str) -> PORecord | None:
        return self._pos.get(normalise_identifier(po_number))

    def open_pos_for_vendor(self, vendor_id: str) -> list[PORecord]:
        return [p for p in self._pos.values() if p.vendor_id == vendor_id and p.status != "closed"]

    def history_for_vendor(self, vendor_id: str) -> list[HistoryRecord]:
        return [h for h in self._history if h.vendor_id == vendor_id]

    def processed_file(self, file_hash: str) -> ProcessedFile | None:
        return self._hashes.get(file_hash)

    @classmethod
    def from_master_dir(cls, folder: Path) -> "InMemoryRepository":
        def rows(name: str) -> list[dict[str, str]]:
            with (folder / name).open(newline="", encoding="utf-8") as handle:
                return list(csv.DictReader(handle))

        buyer = json.loads((folder / "buyer.json").read_text(encoding="utf-8"))
        lines_by_po: dict[str, list[POLineRecord]] = {}
        for r in rows("po_lines.csv"):
            lines_by_po.setdefault(r["po_number"], []).append(POLineRecord(
                int(r["line_no"]), r["description"], r["unit"], Decimal(r["qty_ordered"]), Decimal(r["qty_billed"]),
                Decimal(r["unit_price"]), Decimal(r["gst_rate"])))
        pos = [PORecord(r["po_number"], r["vendor_id"], date.fromisoformat(r["po_date"]), r["status"],
                        Decimal(r["taxable_value"]), Decimal(r["billed_value"]), tuple(lines_by_po.get(r["po_number"], [])))
               for r in rows("po_headers.csv")]
        vendors = [VendorRecord(r["vendor_id"], r["legal_name"], r["trade_name"], r["gstin"], r["state_code"], r["status"],
                                r["bank_name"], r["bank_account"], r["ifsc"]) for r in rows("vendors.csv")]
        history = [HistoryRecord(r["history_id"], r["vendor_id"], r["invoice_number"], date.fromisoformat(r["invoice_date"]),
                                 r["po_number"] or None, Decimal(r["taxable_value"]), Decimal(r["total_amount"]), r["status"])
                   for r in rows("invoice_history.csv")]
        return cls(BuyerRecord(buyer["legal_name"], tuple(buyer["name_variants"]), buyer["gstin"], buyer["state_code"]),
                   vendors, pos, history)


class DbRepository:
    """Master data read from the database through a SQLAlchemy session."""

    def __init__(self, session: Session, buyer: BuyerRecord, exclude_run_id: str | None = None) -> None:
        self.session = session
        self.buyer = buyer
        self._exclude_run_id = exclude_run_id  # the run being processed must not count as its own duplicate

    @staticmethod
    def _vendor(v: Vendor) -> VendorRecord:
        return VendorRecord(v.vendor_id, v.legal_name, v.trade_name, v.gstin, v.state_code, v.status,
                            v.bank_name, v.bank_account, v.ifsc)

    @staticmethod
    def _po(p: POHeader) -> PORecord:
        lines = tuple(POLineRecord(l.line_no, l.description, l.unit, Decimal(l.qty_ordered), Decimal(l.qty_billed),
                                   Decimal(l.unit_price), Decimal(l.gst_rate)) for l in p.lines)
        return PORecord(p.po_number, p.vendor_id, p.po_date, p.status, Decimal(p.taxable_value), Decimal(p.billed_value), lines)

    def vendors(self) -> list[VendorRecord]:
        return [self._vendor(v) for v in self.session.scalars(select(Vendor))]

    def vendor_by_gstin(self, gstin: str) -> VendorRecord | None:
        target = normalise_code(gstin)
        return next((v for v in self.vendors() if normalise_code(v.gstin) == target), None)

    def po(self, po_number: str) -> PORecord | None:
        target = normalise_identifier(po_number)
        row = next((p for p in self.session.scalars(select(POHeader)) if normalise_identifier(p.po_number) == target), None)
        return self._po(row) if row else None

    def open_pos_for_vendor(self, vendor_id: str) -> list[PORecord]:
        query = select(POHeader).where(POHeader.vendor_id == vendor_id, POHeader.status != "closed")
        return [self._po(p) for p in self.session.scalars(query)]

    def history_for_vendor(self, vendor_id: str) -> list[HistoryRecord]:
        query = select(InvoiceHistory).where(InvoiceHistory.vendor_id == vendor_id)
        return [HistoryRecord(h.history_id, h.vendor_id, h.invoice_number, h.invoice_date, h.po_number,
                              Decimal(h.taxable_value), Decimal(h.total_amount), h.status)
                for h in self.session.scalars(query)]

    def processed_file(self, file_hash: str) -> ProcessedFile | None:
        """The earliest approved run of this file (it was paid), else the latest finished one. Only runs that
        finished count (a failed extraction can be retried); test runs never count."""
        query = select(Run).where(Run.file_hash == file_hash, Run.is_test_run.is_(False),
                                  Run.status.in_(("completed", "resolved_by_human")))
        if self._exclude_run_id:
            query = query.where(Run.id != self._exclude_run_id)
        runs = list(self.session.scalars(query.order_by(Run.created_at)))
        if not runs:
            return None
        run = next((r for r in runs if r.decision == "APPROVE"), runs[-1])
        return ProcessedFile(run.id, run.decision, run.created_at)
