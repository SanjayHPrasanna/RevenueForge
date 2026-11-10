"""Recent warnings and errors kept in memory for the platform console's health view.

Only the app's own log lines, newest 300, with email addresses and anything that looks like a key masked. This is not a
replacement for Azure's Log stream: it resets on restart and each running copy of the app keeps its own.
"""
from __future__ import annotations

import logging
import re
import threading
from collections import deque
from datetime import datetime, timezone

_buf: deque = deque(maxlen=300)
_lock = threading.Lock()
_installed = False
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_SECRET = re.compile(r"(?i)(key|token|secret|password|bearer)(\W{1,3})[A-Za-z0-9._\-]{8,}")


def _clean(msg: str) -> str:
    msg = _EMAIL.sub(lambda m: m.group(0)[:2] + "***@" + m.group(0).split("@")[-1], msg)
    return _SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}[hidden]", msg)[:500]


class _Handler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = record.getMessage()
        except Exception:
            msg = str(record.msg)
        with _lock:
            _buf.append({"at": datetime.fromtimestamp(record.created, timezone.utc).isoformat(), "level": record.levelname,
                         "where": record.name, "message": _clean(msg)})


def install() -> None:
    global _installed
    if _installed:
        return
    h = _Handler(level=logging.WARNING)
    logging.getLogger("revenueforge").addHandler(h)  # every app logger is "revenueforge.<part>", so this catches them all
    _installed = True


def recent(limit: int = 100) -> list[dict]:
    with _lock:
        return list(_buf)[-limit:][::-1]
