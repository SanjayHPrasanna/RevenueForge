"""Shared by repair_db and copy_db: check a SQLite file, and copy every readable row of every table into another database."""
from __future__ import annotations

import sqlite3

from sqlalchemy import create_engine, select, text

CHUNK = 500


def quick_check(path: str) -> str:
    """'ok', or SQLite's description of the damage."""
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        try:
            rows = con.execute("PRAGMA quick_check(20)").fetchall()
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        return str(e)
    msgs = [r[0] for r in rows]
    return "ok" if msgs == ["ok"] else "; ".join(msgs)[:2000]


def salvage_copy(src_url: str, dst_url: str, log=print) -> dict:
    """Copy every table from a SQLite source into the destination (whose tables are created first), reading by rowid so a
    damaged page only costs the rows on it. Returns {table: (copied, lost)}."""
    from ..db import Base
    from .. import models  # noqa: F401  (registers every table)

    src = create_engine(src_url, connect_args={"timeout": 30})
    dst = create_engine(dst_url)
    Base.metadata.create_all(dst)
    report = {}
    with src.connect() as s, dst.begin() as d:
        for table in Base.metadata.sorted_tables:  # parents before children
            try:
                top = s.execute(text(f'SELECT max(rowid) FROM "{table.name}"')).scalar() or 0
            except Exception as e:
                log(f"  {table.name}: unreadable ({e.__class__.__name__}), skipped")
                report[table.name] = (0, -1)
                continue
            have = {c.name for c in table.columns}
            try:
                src_cols = [r[1] for r in s.execute(text(f'PRAGMA table_info("{table.name}")'))]
            except Exception:
                src_cols = list(have)
            cols = [table.c[c] for c in src_cols if c in have]  # an older file may lack newer columns
            copied = lost = 0
            last = 0
            while last < top:
                hi = min(top, last + CHUNK)
                q = select(*cols).where(text(f"rowid > {last} AND rowid <= {hi}"))
                try:
                    rows = [dict(r._mapping) for r in s.execute(q)]
                except Exception:
                    rows = []
                    for rid in range(last + 1, hi + 1):  # the chunk crosses a damaged page: rescue row by row
                        try:
                            rows += [dict(r._mapping) for r in s.execute(select(*cols).where(text(f"rowid = {rid}")))]
                        except Exception:
                            lost += 1
                if rows:
                    try:
                        d.execute(table.insert(), rows)
                        copied += len(rows)
                    except Exception:
                        for row in rows:  # a single bad row (e.g. a broken reference) mustn't sink the rest
                            try:
                                with d.begin_nested():
                                    d.execute(table.insert(), [row])
                                copied += 1
                            except Exception:
                                lost += 1
                last = hi
            report[table.name] = (copied, lost)
            log(f"  {table.name}: {copied} rows copied" + (f", {lost} unreadable" if lost else ""))
    if dst.dialect.name == "postgresql":  # move id counters past the copied rows, or the next insert would clash
        from sqlalchemy import Integer
        with dst.begin() as d:
            for table in Base.metadata.sorted_tables:
                for col in table.primary_key.columns:
                    if isinstance(col.type, Integer) and col.autoincrement in (True, "auto"):
                        d.execute(text(f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', '{col.name}'), "
                                       f"COALESCE((SELECT max({col.name}) FROM \"{table.name}\"), 0) + 1, false)"))
    src.dispose()
    dst.dispose()
    return report
