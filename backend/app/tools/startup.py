"""Runs once before the web server starts (see the Dockerfile), in its own process.

- SQLite: checks the file. If it's damaged and REPAIR_DATABASE=true, builds a repaired copy and switches to it
  (the same as `python -m app.tools.repair_db --apply`).
- PostgreSQL: on the first start against an empty PostgreSQL database, copies everything from the SQLite file in
  /home/data (if there is one), so moving is just "set DATABASE_URL and restart".

It never stops the app from starting: any problem is logged and the server starts anyway.
"""
from __future__ import annotations

import os
import sys


def main() -> int:
    from ..config import DATA_DIR, _sqlite_file, settings
    from .dbtools import quick_check
    url = settings.database_url
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
        if not os.path.exists(path):
            return 0
        state = quick_check(path)
        if state == "ok":
            print("[startup] database check: OK", flush=True)
            return 0
        print(f"[startup] DATABASE DAMAGED: {state[:300]}", flush=True)
        if os.getenv("REPAIR_DATABASE", "").lower() in ("1", "true", "yes"):
            from .repair_db import main as repair
            return repair(["--apply"])
        print("[startup] Set REPAIR_DATABASE=true and restart to repair it (see DEPLOY.md).", flush=True)
        return 0
    # PostgreSQL (or another server database)
    from sqlalchemy import create_engine, inspect, text
    eng = create_engine(url)
    try:
        has = "tenants" in inspect(eng).get_table_names()
        with eng.connect() as c:
            n = c.execute(text("SELECT count(*) FROM tenants")).scalar() if has else 0
    finally:
        eng.dispose()
    if n:
        print(f"[startup] database: {n} companies", flush=True)
        return 0
    src = _sqlite_file()
    if not src.is_file():
        print("[startup] empty database, no SQLite file to bring across: starting fresh", flush=True)
        return 0
    import sqlite3
    try:
        con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
        companies = con.execute("SELECT count(*) FROM tenants").fetchone()[0]
        con.close()
    except sqlite3.DatabaseError:
        companies = 1  # damaged: try anyway, salvage_copy reads what it can
    if not companies:
        return 0
    print(f"[startup] empty database: copying {src.name} into it ...", flush=True)
    from .dbtools import salvage_copy
    report = salvage_copy(f"sqlite:///{src.as_posix()}", url, log=lambda m: print("[startup]" + m, flush=True))
    print(f"[startup] copied {sum(c for c, _ in report.values())} rows. The SQLite file is kept in {DATA_DIR} as a fallback.", flush=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # never block start-up
        print(f"[startup] skipped: {e}", flush=True)
        sys.exit(0)
