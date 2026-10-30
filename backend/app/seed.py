"""Load data/master/* into the database. Rebuilds only the seeded tables, so runs and caches survive."""

import csv
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import REPO_ROOT
from app.db import Base
from app.models import SEEDED_TABLES, InvoiceHistory, POHeader, POLine, Vendor

MASTER_DIR = REPO_ROOT / "data" / "master"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _vendor(row: dict[str, str]) -> Vendor:
    return Vendor(**{**row, "payment_terms_days": int(row["payment_terms_days"])})


def _po_header(row: dict[str, str]) -> POHeader:
    money = ("taxable_value", "gst_amount", "total_value", "billed_value", "remaining_value")
    return POHeader(
        **{k: v for k, v in row.items() if k not in money + ("po_date", "payment_terms_days")},
        **{k: Decimal(row[k]) for k in money},
        po_date=date.fromisoformat(row["po_date"]),
        payment_terms_days=int(row["payment_terms_days"]),
    )


def _po_line(row: dict[str, str]) -> POLine:
    decimals = ("qty_ordered", "unit_price", "gst_rate", "line_value", "qty_billed", "qty_remaining")
    return POLine(
        po_number=row["po_number"],
        line_no=int(row["line_no"]),
        description=row["description"],
        hsn_sac=row["hsn_sac"],
        unit=row["unit"],
        **{k: Decimal(row[k]) for k in decimals},
    )


def _history(row: dict[str, str]) -> InvoiceHistory:
    money = ("taxable_value", "cgst", "sgst", "igst", "round_off", "total_amount")
    return InvoiceHistory(
        history_id=row["history_id"],
        vendor_id=row["vendor_id"],
        invoice_number=row["invoice_number"],
        invoice_date=date.fromisoformat(row["invoice_date"]),
        po_number=row["po_number"] or None,
        status=row["status"],
        payment_date=date.fromisoformat(row["payment_date"]) if row["payment_date"] else None,
        lines_json=json.loads(row["lines_json"]),
        **{k: Decimal(row[k]) for k in money},
    )


def seed_master(engine: Engine, master_dir: Path = MASTER_DIR) -> dict[str, int]:
    """Drop and recreate the seeded tables, load the CSVs, and return row counts per table."""
    Base.metadata.drop_all(engine, tables=list(reversed(SEEDED_TABLES)))
    Base.metadata.create_all(engine)
    vendors = [_vendor(r) for r in _read_csv(master_dir / "vendors.csv")]
    headers = [_po_header(r) for r in _read_csv(master_dir / "po_headers.csv")]
    lines = [_po_line(r) for r in _read_csv(master_dir / "po_lines.csv")]
    history = [_history(r) for r in _read_csv(master_dir / "invoice_history.csv")]
    with Session(engine) as session:
        for batch in (vendors, headers, lines, history):
            session.add_all(batch)
            session.flush()
        session.commit()
    return {"vendors": len(vendors), "po_headers": len(headers), "po_lines": len(lines), "invoice_history": len(history)}
