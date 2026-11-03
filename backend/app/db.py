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
    """Anchor relative SQLite paths to backend/, so scripts and the server share one file whatever the cwd.
    A Postgres URL as Supabase/Render print it (postgres:// or postgresql://) gets the psycopg 3 driver."""
    url = url.strip()
    prefix = "sqlite:///"
    if url.startswith(prefix) and url != "sqlite:///:memory:":
        path = Path(url.removeprefix(prefix))
        if not path.is_absolute():
            return prefix + (BACKEND_DIR / path).resolve().as_posix()
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url.removeprefix(scheme)
    return url


def make_engine(url: str) -> Engine:
    """SQLite locally; Postgres (Supabase) in production, with a small pool that survives dropped connections.
    prepare_threshold=None: Supabase's pooler (PgBouncer, transaction mode) cannot keep prepared statements."""
    url = resolve_database_url(url)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=300,
                         connect_args={"prepare_threshold": None})


@lru_cache
def get_engine() -> Engine:
    """The app-wide engine for DATABASE_URL."""
    return make_engine(get_settings().database_url)


def get_session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


def init_db(engine: Engine) -> None:
    """Create missing tables. Run tables whose columns changed are migrated in place when the change only adds
    nullable columns (runs survive an upgrade); any other change rebuilds them (runs are derived, safe to drop)."""
    from sqlalchemy import inspect, text

    from app.models import RUN_TABLES

    inspector = inspect(engine)
    stale = []
    for table in RUN_TABLES:
        if not inspector.has_table(table.name):
            continue
        existing = {c["name"] for c in inspector.get_columns(table.name)}
        wanted = {c.name: c for c in table.columns}
        added = [wanted[name] for name in wanted.keys() - existing]
        if existing - wanted.keys() or any(not c.nullable for c in added):
            stale.append(table)
            continue
        with engine.begin() as conn:
            for column in added:
                kind = column.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {kind}'))
    if stale:
        Base.metadata.drop_all(engine, tables=list(reversed(RUN_TABLES)))
    Base.metadata.create_all(engine)
