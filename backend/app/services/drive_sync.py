"""A Google Drive folder kept connected to the knowledge library.

The server never holds a Google key. The browser asks Google for a short-lived read-only token each time someone connects
or clicks Refresh, lists the folder itself, and sends the server only the list (file id, path, modified time, version).
The server compares that list with what it imported last time and says what is new, changed or gone. Only new and
changed files are downloaded, and they go through the normal review screen before anything in the library changes.

What the server remembers lives in tenant.settings["drive"] (system-managed; PUT /company can't write it):
    {"folder": {"id", "name"}, "connected_by", "connected_at", "last_refresh", "last_checked",
     "files": {drive_id: {"path", "modified", "version", "doc_id", "kind"}}}
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select

SIG_SKIP = {"id", "tenant_id", "source_doc"}


def _norm(v):
    # Unset, empty and zero all compare equal, so a column default filled in by the database isn't mistaken for an edit.
    if v is None or v == "" or v == [] or v == {} or (not isinstance(v, bool) and isinstance(v, (int, float)) and v == 0):
        return ""
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return round(float(v), 6)
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return [_norm(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in sorted(v.items())}
    return str(v)


def record_sig(M, obj) -> str:
    """A fingerprint of one library record, so we can tell later whether someone edited it in the app."""
    data = {c.name: _norm(getattr(obj, c.name, None)) for c in M.__table__.columns if c.name not in SIG_SKIP}
    return hashlib.sha1(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


def doc_records(db, M, tid: str, doc_id: str) -> list:
    return list(db.scalars(select(M).where(M.tenant_id == tid, M.source_doc == doc_id)))


def edited_count(db, M, tid: str, doc) -> int | None:
    """How many records from this file were changed in the app since it was imported (None = imported before we kept track)."""
    stored = (doc.parsed or {}).get("sigs")
    if stored is None:
        return None
    left = list(stored)
    n = 0
    for r in doc_records(db, M, tid, doc.id):
        s = record_sig(M, r)
        if s in left:
            left.remove(s)
        else:
            n += 1
    return n


def connection(tenant) -> dict | None:
    c = (tenant.settings or {}).get("drive")
    return json.loads(json.dumps(c, default=str)) if isinstance(c, dict) and c.get("folder") else None  # a copy: edits are saved explicitly


def save_connection(tenant, conn: dict | None):
    from sqlalchemy.orm.attributes import flag_modified
    s = json.loads(json.dumps(tenant.settings or {}, default=str))
    if conn is None:
        s.pop("drive", None)
    else:
        s["drive"] = json.loads(json.dumps(conn, default=str))
    tenant.settings = s
    flag_modified(tenant, "settings")  # the dict was edited in place; make sure it is written


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_listing(files) -> list[dict]:
    """The browser's listing, trimmed to what we use. Anything malformed is dropped."""
    out, seen = [], set()
    for f in files if isinstance(files, list) else []:
        if not isinstance(f, dict):
            continue
        fid = str(f.get("id") or "")[:128]
        if not fid or fid in seen:
            continue
        seen.add(fid)
        out.append({"id": fid, "path": str(f.get("path") or f.get("name") or "")[:500], "modified": str(f.get("modified") or "")[:40],
                    "version": str(f.get("version") or "")[:40]})
    return out[:1000]


def changed(old: dict, new: dict) -> bool:
    return (old.get("version") or "") != (new.get("version") or "") or (old.get("modified") or "") != (new.get("modified") or "")
