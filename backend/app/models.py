"""SQLAlchemy table models (CLAUDE.md §7).

Seeded tables (vendors, po_headers, po_lines, invoice_history) are rebuilt from data/master by the
seed / reset. Run tables (runs, run_events, hold_actions) and caches are never touched by seeding,
so they have no foreign keys into the seeded tables.
"""

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

Money = Numeric(14, 2)
Quantity = Numeric(14, 3)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Vendor(Base):
    __tablename__ = "vendors"

    vendor_id: Mapped[str] = mapped_column(String(10), primary_key=True)
    legal_name: Mapped[str] = mapped_column(String(200))
    trade_name: Mapped[str] = mapped_column(String(200))
    gstin: Mapped[str] = mapped_column(String(15), index=True)
    pan: Mapped[str] = mapped_column(String(10))
    state: Mapped[str] = mapped_column(String(50))
    state_code: Mapped[str] = mapped_column(String(2))
    address: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str] = mapped_column(String(30))
    bank_name: Mapped[str] = mapped_column(String(100))
    bank_account: Mapped[str] = mapped_column(String(18))
    ifsc: Mapped[str] = mapped_column(String(11))
    status: Mapped[str] = mapped_column(String(20))  # approved | pending | blocked
    category: Mapped[str] = mapped_column(String(50))
    payment_terms_days: Mapped[int] = mapped_column(Integer)


class POHeader(Base):
    __tablename__ = "po_headers"

    po_number: Mapped[str] = mapped_column(String(20), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"), index=True)
    po_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20))  # open | partially_billed | closed
    taxable_value: Mapped[Decimal] = mapped_column(Money)
    gst_amount: Mapped[Decimal] = mapped_column(Money)
    total_value: Mapped[Decimal] = mapped_column(Money)
    billed_value: Mapped[Decimal] = mapped_column(Money)  # taxable value billed so far (the PO ledger)
    remaining_value: Mapped[Decimal] = mapped_column(Money)
    delivery_location: Mapped[str] = mapped_column(String(200))
    requested_by: Mapped[str] = mapped_column(String(100))
    payment_terms_days: Mapped[int] = mapped_column(Integer)

    lines: Mapped[list["POLine"]] = relationship(back_populates="po", order_by="POLine.line_no")


class POLine(Base):
    __tablename__ = "po_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_number: Mapped[str] = mapped_column(ForeignKey("po_headers.po_number"), index=True)
    line_no: Mapped[int] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(String(200))
    hsn_sac: Mapped[str] = mapped_column(String(10))
    unit: Mapped[str] = mapped_column(String(20))
    qty_ordered: Mapped[Decimal] = mapped_column(Quantity)
    unit_price: Mapped[Decimal] = mapped_column(Money)
    gst_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    line_value: Mapped[Decimal] = mapped_column(Money)
    qty_billed: Mapped[Decimal] = mapped_column(Quantity)
    qty_remaining: Mapped[Decimal] = mapped_column(Quantity)

    po: Mapped[POHeader] = relationship(back_populates="lines")


class InvoiceHistory(Base):
    __tablename__ = "invoice_history"

    history_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    vendor_id: Mapped[str] = mapped_column(ForeignKey("vendors.vendor_id"), index=True)
    invoice_number: Mapped[str] = mapped_column(String(50))
    invoice_date: Mapped[date] = mapped_column(Date)
    po_number: Mapped[str | None] = mapped_column(String(20), index=True)
    taxable_value: Mapped[Decimal] = mapped_column(Money)
    cgst: Mapped[Decimal] = mapped_column(Money)
    sgst: Mapped[Decimal] = mapped_column(Money)
    igst: Mapped[Decimal] = mapped_column(Money)
    round_off: Mapped[Decimal] = mapped_column(Money)
    total_amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20))  # approved | paid
    payment_date: Mapped[date | None] = mapped_column(Date)
    lines_json: Mapped[list] = mapped_column(JSON)  # [{po_line_no, description, quantity, unit_price, ...}]


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    file_name: Mapped[str] = mapped_column(String(255))
    file_hash: Mapped[str] = mapped_column(String(64), index=True)
    file_bytes: Mapped[bytes] = mapped_column(LargeBinary)
    model: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    decision: Mapped[str | None] = mapped_column(String(30))
    total_amount: Mapped[Decimal | None] = mapped_column(Money)
    vendor_id: Mapped[str | None] = mapped_column(String(10))
    po_number: Mapped[str | None] = mapped_column(String(20))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    extracted_json: Mapped[dict | None] = mapped_column(JSON)
    verification_json: Mapped[dict | None] = mapped_column(JSON)
    reasons_json: Mapped[list | None] = mapped_column(JSON)
    is_test_run: Mapped[bool] = mapped_column(Boolean, default=False)
    # Phase 5 additions (needed for retry links, cache badges, the decision detail and the sample picker)
    mime_type: Mapped[str] = mapped_column(String(40), default="application/pdf")
    page_count: Mapped[int | None] = mapped_column(Integer)
    model_name: Mapped[str | None] = mapped_column(String(100))
    used_cache: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_of: Mapped[str | None] = mapped_column(String(36))
    sample_id: Mapped[str | None] = mapped_column(String(60))
    error_json: Mapped[dict | None] = mapped_column(JSON)
    decision_json: Mapped[dict | None] = mapped_column(JSON)  # full Decision + per-stage checks


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    stage: Mapped[str] = mapped_column(String(30))
    event_type: Mapped[str] = mapped_column(String(30))  # stage_started | check_result | stage_completed | ...
    payload: Mapped[dict] = mapped_column(JSON)


class HoldAction(Base):
    __tablename__ = "hold_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    actor_role: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(30))
    comment: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)  # e.g. {"po_number": ...} or {"field": ..., "value": ...}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ExtractionCache(Base):
    __tablename__ = "extraction_cache"

    file_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    model: Mapped[str] = mapped_column(String(100), primary_key=True)
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PageWordsCache(Base):
    __tablename__ = "page_words_cache"

    file_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    page: Mapped[int] = mapped_column(Integer, primary_key=True)
    words_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


SEEDED_TABLES = [Vendor.__table__, POHeader.__table__, POLine.__table__, InvoiceHistory.__table__]
RUN_TABLES = [Run.__table__, RunEvent.__table__, HoldAction.__table__]
