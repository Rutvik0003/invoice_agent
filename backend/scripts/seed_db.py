"""Load data/master/* into the database (idempotent: drops and recreates the seeded tables).

Usage: python backend/scripts/seed_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # make `app` importable from any cwd

from app.db import get_engine  # noqa: E402
from app.seed import seed_master  # noqa: E402


def main() -> None:
    engine = get_engine()
    counts = seed_master(engine)
    target = engine.url.database if engine.url.drivername.startswith("sqlite") else engine.url.host
    print(f"Seeded {engine.url.drivername} database: {target}")
    for table, count in counts.items():
        print(f"  {table:<16} {count:>5} rows")


if __name__ == "__main__":
    main()
