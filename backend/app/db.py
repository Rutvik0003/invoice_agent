"""SQLAlchemy engine and session setup."""

from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


class Base(DeclarativeBase):
    pass


def resolve_database_url(url: str) -> str:
    """Anchor relative SQLite paths to backend/, so scripts and the server share one file whatever the cwd."""
    prefix = "sqlite:///"
    if url.startswith(prefix) and url != "sqlite:///:memory:":
        path = Path(url.removeprefix(prefix))
        if not path.is_absolute():
            return prefix + (BACKEND_DIR / path).resolve().as_posix()
    return url


def make_engine(url: str) -> Engine:
    url = resolve_database_url(url)
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


@lru_cache
def get_engine() -> Engine:
    """The app-wide engine for DATABASE_URL."""
    return make_engine(get_settings().database_url)


def get_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def init_db(engine: Engine) -> None:
    """Create missing tables; rebuild the run tables if their columns changed (runs are derived, safe to drop)."""
    from sqlalchemy import inspect

    from app.models import RUN_TABLES

    inspector = inspect(engine)
    stale = [
        table for table in RUN_TABLES
        if inspector.has_table(table.name)
        and {c["name"] for c in inspector.get_columns(table.name)} != {c.name for c in table.columns}
    ]
    if stale:
        Base.metadata.drop_all(engine, tables=list(reversed(RUN_TABLES)))
    Base.metadata.create_all(engine)
