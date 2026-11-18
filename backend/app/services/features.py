"""Per-workspace feature switches.

`generalised_response` turns on the RFP-Profile-driven response pipeline (evidence-gated answers, proposal validation,
scope-based team planning, eligibility gates and the full commercial model). It is off by default so existing workspaces
keep today's behaviour until an admin switches it on in Settings; RF_GENERALISED_DEFAULT=true flips the default (tests).
"""
from __future__ import annotations

import os

FLAGS = {"generalised_response": False}
NUMERIC = {"fte_per_24x7_seat": (4.8, 3.0, 6.0)}  # name: (default, min, max)


def _default(name: str) -> bool:
    if name == "generalised_response" and os.environ.get("RF_GENERALISED_DEFAULT", "").lower() in ("1", "true", "yes", "on"):
        return True
    return FLAGS.get(name, False)


def on(tenant, name: str = "generalised_response") -> bool:
    s = (getattr(tenant, "settings", None) or {}) if tenant is not None else {}
    v = s.get(name)
    return _default(name) if v is None else bool(v)


def number(tenant, name: str) -> float:
    d, lo, hi = NUMERIC[name]
    s = (getattr(tenant, "settings", None) or {}) if tenant is not None else {}
    try:
        return max(lo, min(hi, float(s.get(name, d))))
    except (TypeError, ValueError):
        return d
