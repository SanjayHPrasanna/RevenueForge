from __future__ import annotations

import os

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30} if _is_sqlite else {},
    pool_pre_ping=True,
)

if _is_sqlite:
    @event.listens_for(engine, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        # WAL is fastest on a local disk; network storage (e.g. Azure App Service's /home) needs DELETE mode.
        mode = os.getenv("SQLITE_JOURNAL_MODE", "WAL").upper()
        cur.execute(f"PRAGMA journal_mode={mode if mode in ('WAL', 'DELETE', 'TRUNCATE') else 'WAL'}")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

if settings.database_url.startswith("postgresql"):
    # numpy numbers (scores from scikit-learn) are float/int subclasses whose repr is "np.float64(0.42)" in numpy 2;
    # psycopg2 would put that text straight into the SQL. Send them as plain numbers.
    import numpy as _np
    from psycopg2.extensions import AsIs, register_adapter
    for _t in (_np.float64, _np.float32, _np.float16):
        register_adapter(_t, lambda v: AsIs(repr(float(v))))
    for _t in (_np.int64, _np.int32, _np.int16, _np.int8, _np.uint64, _np.uint32):
        register_adapter(_t, lambda v: AsIs(int(v)))
    register_adapter(_np.bool_, lambda v: AsIs("true" if v else "false"))

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@event.listens_for(SessionLocal, "before_flush")
def _fit_text_to_columns(session, flush_context, instances):
    """PostgreSQL refuses text longer than a column allows (SQLite silently keeps it). Trim instead of failing the request,
    and drop NUL characters, which PostgreSQL can't store in text at all."""
    from sqlalchemy import String
    for obj in list(session.new) + list(session.dirty):
        table = getattr(obj, "__table__", None)
        if table is None:
            continue
        for col in table.columns:
            if not isinstance(col.type, String):
                continue
            v = getattr(obj, col.key, None)
            if not isinstance(v, str):
                continue
            nv = v.replace("\x00", "") if "\x00" in v else v
            if col.type.length and len(nv) > col.type.length:
                nv = nv[:col.type.length]
            if nv is not v:
                setattr(obj, col.key, nv)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


DB_STATE = {"ok": True, "detail": ""}


def check_database() -> dict:
    """SQLite only: a quick integrity check. A damaged file is reported on /api/health and background writers stand down."""
    if _is_sqlite:
        from .tools.dbtools import quick_check
        path = settings.database_url[len("sqlite:///"):]
        if os.path.exists(path):
            res = quick_check(path)
            DB_STATE.update(ok=res == "ok", detail="" if res == "ok" else res[:500])
            if res != "ok":
                import logging
                logging.getLogger("revenueforge").error("DATABASE DAMAGED: %s. Run: python -m app.tools.repair_db --apply", res[:300])
    return DB_STATE


def init_db() -> None:
    from . import models  # noqa: F401  (registers tables)

    check_database()
    Base.metadata.create_all(bind=engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Lightweight forward migration: add columns introduced after a database was created."""
    from sqlalchemy import inspect, text

    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                default = col.default.arg if col.default is not None and not callable(col.default.arg) else None
                dflt = ""
                if isinstance(default, bool):
                    dflt = f" DEFAULT {1 if default else 0}"
                elif isinstance(default, (int, float)):
                    dflt = f" DEFAULT {default}"
                elif isinstance(default, str):
                    dflt = f" DEFAULT '{default}'"
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}{dflt}'))
