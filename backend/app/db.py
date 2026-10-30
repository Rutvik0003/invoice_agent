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
