"""Supplier network: buyers find suppliers who have proven they can do the work, and invite them to bid.

A vendor appears only after its admin switches on "List us in the supplier network" in Settings. What a buyer sees is
the vendor's public profile: capabilities, company certificates and partnerships, case-study summaries without client
names, technology depth as head-counts, and the regions and industries it serves. Never people's names, rates, deals or
client names.

Shortlist scores are computed the same way for every vendor, from the vendor's own library, with no AI and no paid
placement: coverage of the buyer's requirements, with missing certificates counted against it.
"""
from __future__ import annotations

import copy
import re
from collections import Counter, defaultdict

from sqlalchemy import select

from ..models import Accelerator, CaseStudy, Capability, Certification, Employee, Tenant
from . import knowledge as K
from .matching import match_requirements, standards_in
from .tender_feeds import REGIONS

TECH_SUBCATS_EXCLUDED = {"Pricing & Payment", "Bonds & Guarantees", "Insurance & Liability", "Contract Terms", "Evaluation & Award", "Submission"}


def network_settings(t: Tenant) -> dict:
    n = dict((t.settings or {}).get("network") or {})
    n.setdefault("listed", False)
    n.setdefault("regions", [])
    n.setdefault("industries", [])
    n.setdefault("summary", "")
    return n


def is_demo(t: Tenant) -> bool:
    return bool((t.settings or {}).get("demo"))


def listed_vendors(db) -> list[Tenant]:
    return [t for t in db.scalars(select(Tenant).where(Tenant.kind != "buyer")) if network_settings(t)["listed"]]


def _strip_client(text: str, client: str) -> str:
    if client and len(client) > 3:
        text = re.sub(re.escape(client), "a client", text or "", flags=re.I)
    return text or ""


def vendor_profile(db, t: Tenant) -> dict:
    """Everything a buyer may see about a listed vendor."""
    n = network_settings(t)
    caps = db.scalars(select(Capability).where(Capability.tenant_id == t.id)).all()
    certs = db.scalars(select(Certification).where(Certification.tenant_id == t.id, Certification.kind.in_(["company", "partner"]))).all()
    css = db.scalars(select(CaseStudy).where(CaseStudy.tenant_id == t.id)).all()
    accs = db.scalars(select(Accelerator).where(Accelerator.tenant_id == t.id)).all()
    people = db.scalars(select(Employee).where(Employee.tenant_id == t.id)).all()
    depth: Counter = Counter()
    for e in people:
        for s in e.skills or []:
            if s.get("level", 0) >= 3:
                depth[K.canonical_tech(s["name"])] += 1
    return {
        "id": t.id, "name": t.name, "demo": is_demo(t), "headquarters": t.headquarters, "headcount": t.headcount or len(people),
        "industry": t.industry, "summary": n["summary"] or (t.about or "")[:600], "website": t.website,
        "regions": n["regions"], "industries": n["industries"],
        "capabilities": [{"name": c.name, "service_line": c.service_line, "description": (c.description or "")[:400],
                          "technologies": (c.technologies or [])[:10]} for c in caps],
        "certifications": [{"name": c.name, "kind": c.kind, "issuer": c.issuer} for c in certs],
        "case_studies": [{"title": _strip_client(c.title, c.client), "industry": c.industry, "region": c.region, "year": c.year,
                          "summary": _strip_client(c.summary, c.client)[:500], "outcomes": [o.strip() for o in (c.outcomes or [])][:4]}
                         for c in css],
        "products": [{"name": a.name, "description": (a.description or "")[:300]} for a in accs],
        "skills": [{"technology": k, "people": v} for k, v in depth.most_common(15)],
    }


def _kb(db, tid: str):
    from .pipeline import load_kb
    return load_kb(db, tid)


def score_vendor(db, t: Tenant, reqs: list[dict], region: str = "", industry: str = "") -> dict:
    """How well one vendor's own library covers the buyer's requirements."""
    kb = _kb(db, t.id)
    work = [copy.deepcopy(r) for r in reqs if r.get("category") != "Commercial" and r.get("subcategory") not in TECH_SUBCATS_EXCLUDED]
    for i, r in enumerate(work):
        r.setdefault("code", f"R{i + 1}")
        r.setdefault("section", "")
    if not work or not (kb.capabilities or kb.case_studies):
        return {"score": 0, "coverage": {}, "strengths": [], "gaps": [], "missing_standards": [], "notes": ["No library to compare yet."]}
    match_requirements(work, kb, industry=industry, use_ai=False)
    weight = {"strong": 1.0, "partial": 0.6, "gap": 0.0}
    counted = [r for r in work if r["match_status"] in weight]
    mand = [r for r in counted if r.get("priority") == "Mandatory"] or counted
    score = round(100 * sum(weight[r["match_status"]] for r in mand) / len(mand)) if mand else 0
    held = {s for c in kb.certifications for s in standards_in(c["name"])}
    asked = set().union(*[standards_in(r["text"]) for r in work]) if work else set()
    missing_std = sorted(asked - held)
    ev: Counter = Counter()
    for r in work:
        if r["match_status"] in ("strong", "partial"):
            for e in r["match"]["evidence"][:2]:
                ev[(e["type"], e["name"])] += 1
    strengths = [{"type": k[0], "name": k[1], "requirements": v} for k, v in ev.most_common(5)]
    gaps = [{"text": r["text"][:200], "missing": r["match"].get("technologies_missing", [])[:3]}
            for r in work if r["match_status"] == "gap" and r.get("priority") == "Mandatory"][:6]
    n = network_settings(t)
    notes = []
    regions_done = {c.get("region", "") for c in kb.case_studies}
    if region:
        if region in n["regions"]:
            notes.append(f"Serves {region}.")
        else:
            notes.append(f"Doesn't list {region} among the regions it serves.")
    if industry:
        same = [c for c in kb.case_studies if industry.lower() in (c.get("industry") or "").lower()]
        notes.append(f"{len(same)} case stud{'y' if len(same) == 1 else 'ies'} in {industry}." if same else f"No case study in {industry}.")
    if missing_std:
        notes.append(f"Doesn't hold {', '.join(missing_std)}, which your requirements mention.")
    counts = Counter(r["match_status"] for r in work)
    return {"score": score, "coverage": dict(counts), "strengths": strengths, "gaps": gaps, "missing_standards": missing_std,
            "notes": notes, "regions_done": sorted(x for x in regions_done if x)[:6]}


def shortlist(db, reqs: list[dict], region: str = "", industry: str = "", exclude_tenant: str = "") -> list[dict]:
    out = []
    for t in listed_vendors(db):
        if t.id == exclude_tenant:
            continue
        s = score_vendor(db, t, reqs, region, industry)
        n = network_settings(t)
        out.append({"vendor_id": t.id, "name": t.name, "demo": is_demo(t), "headquarters": t.headquarters, "regions": n["regions"],
                    "industries": n["industries"], **s})
    out.sort(key=lambda x: (-x["score"], len(x["missing_standards"]), x["name"]))
    return out
