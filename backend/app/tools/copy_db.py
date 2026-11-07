"""Copy the SQLite database into PostgreSQL (or any empty database SQLAlchemy can reach).

    python -m app.tools.copy_db "postgresql+psycopg2://USER:PASSWORD@HOST:5432/revenueforge?sslmode=require"

Run it once, then set DATABASE_URL to the same address and restart. The SQLite file is left untouched as a fallback.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, inspect, text

from ..config import settings
from .dbtools import quick_check, salvage_copy


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    target = argv[0]
    src = settings.database_url
    if not src.startswith("sqlite:///"):
        print("DATABASE_URL already points at", src.split("@")[-1], "- unset it to copy from the SQLite file.")
        return 2
    eng = create_engine(target)
    with eng.connect() as c:
        c.execute(text("SELECT 1"))
    existing = [t for t in inspect(eng).get_table_names() if t in ("tenants", "users", "deals")]
    if existing:
        with eng.connect() as c:
            n = c.execute(text("SELECT count(*) FROM tenants")).scalar() if "tenants" in existing else 0
        if n:
            print(f"The target already has {n} companies. Use an empty database.")
            return 2
    eng.dispose()
    state = quick_check(src[len("sqlite:///"):])
    print("Source check:", "OK" if state == "ok" else f"DAMAGED ({state[:200]}) - copying every readable row")
    print("Copying ...")
    report = salvage_copy(src, target)
    total = sum(c for c, _ in report.values())
    print(f"\nDone: {total} rows copied. Now set DATABASE_URL to the target address and restart the app.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
