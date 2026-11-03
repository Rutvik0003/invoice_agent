"""Tests for loading master data into the database."""

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import BACKEND_DIR, make_engine, resolve_database_url
from app.models import InvoiceHistory, POHeader, POLine, Run, Vendor
from app.seed import seed_master
from datagen.master_data import build_master, write_master


@pytest.fixture(scope="module")
def master_dir(tmp_path_factory):
    path = tmp_path_factory.mktemp("master")
    write_master(build_master(), path)
    return path


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield engine
    engine.dispose()


def test_seed_loads_all_rows_and_is_idempotent(engine, master_dir):
    first = seed_master(engine, master_dir)
    second = seed_master(engine, master_dir)
    assert first == second
    assert first["vendors"] == 40 and first["po_headers"] == 200
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Vendor)) == 40
        assert session.scalar(select(func.count()).select_from(POLine)) == first["po_lines"]
        assert session.scalar(select(func.count()).select_from(InvoiceHistory)) == first["invoice_history"]


def test_seed_preserves_runs(engine, master_dir):
    seed_master(engine, master_dir)
    with Session(engine) as session:
        session.add(Run(id="r1", file_name="a.pdf", file_hash="x" * 64, file_bytes=b"%PDF", model="gemini", status="done"))
        session.commit()
    seed_master(engine, master_dir)
    with Session(engine) as session:
        assert session.get(Run, "r1") is not None


def test_seeded_values_round_trip(engine, master_dir):
    seed_master(engine, master_dir)
    md = build_master()
    expected_po = md.pos[0]
    expected_inv = md.history[0]
    with Session(engine) as session:
        po = session.get(POHeader, expected_po.po_number)
        assert po.taxable_value == expected_po.taxable_value
        assert po.status == expected_po.status
        assert [line.line_no for line in po.lines] == [line.line_no for line in expected_po.lines]
        inv = session.get(InvoiceHistory, expected_inv.history_id)
        assert inv.total_amount == expected_inv.total_amount
        assert isinstance(inv.lines_json, list) and Decimal(inv.lines_json[0]["unit_price"]) > 0


def test_relative_sqlite_paths_are_anchored_to_backend():
    assert resolve_database_url("sqlite:///./local.db") == f"sqlite:///{(BACKEND_DIR / 'local.db').as_posix()}"
    assert resolve_database_url("sqlite:///:memory:") == "sqlite:///:memory:"
    # Supabase / Render print postgres:// or postgresql://; the app uses the psycopg 3 driver (Phase 9)
    assert resolve_database_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert resolve_database_url("postgres://u:p@h:6543/db") == "postgresql+psycopg://u:p@h:6543/db"
    assert resolve_database_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
