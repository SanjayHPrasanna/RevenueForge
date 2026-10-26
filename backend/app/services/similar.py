""""You've bid this before": the company's past deals most like this one, with how they went."""
from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select

from ..models import Deal, DealStage, Requirement
from .masking import deal_masker


def _features(reqs: list[Requirement]) -> tuple[set[str], set[str]]:
    tech, caps = set(), set()
    for r in reqs:
        tech.update(t.strip().lower() for t in (r.technologies or []) if t)
        for e in (r.match or {}).get("evidence", [])[:2]:
            if isinstance(e, dict) and e.get("type") == "Capability" and e.get("name"):
                caps.add(e["name"].lower())
    return tech, caps


def _jac(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


def similar(db, deal: Deal, limit: int = 3) -> list[dict]:
    others = db.scalars(select(Deal).where(Deal.tenant_id == deal.tenant_id, Deal.id != deal.id)).all()
    if not others:
        return []
    ids = [deal.id] + [d.id for d in others]
    reqs = defaultdict(list)
    for r in db.scalars(select(Requirement).where(Requirement.deal_id.in_(ids))):
        reqs[r.deal_id].append(r)
    stages = defaultdict(dict)
    for s in db.scalars(select(DealStage).where(DealStage.deal_id.in_(ids), DealStage.stage.in_(("gaps", "pricing")))):
        stages[s.deal_id][s.stage] = s.data or {}
    tech0, caps0 = _features(reqs[deal.id])
    out = []
    for d in others:
        tech, caps = _features(reqs[d.id])
        score = 0.55 * _jac(tech0, tech) + 0.25 * _jac(caps0, caps)
        score += 0.1 if deal.industry and d.industry and deal.industry.lower() == d.industry.lower() else 0
        score += 0.1 if deal.engagement_type and deal.engagement_type == d.engagement_type else 0
        if score < 0.12:
            continue
        g, pr = stages[d.id].get("gaps", {}), stages[d.id].get("pricing", {})
        sel = next((s for s in pr.get("scenarios", []) if s["name"] == pr.get("selected", "Target")), None) if pr else None
        mask = deal_masker(d)
        out.append({
            "id": d.id, "name": mask(d.name), "client": d.client_alias if d.confidential else d.client_name, "status": d.status,
            "industry": d.industry, "engagement_type": d.engagement_type, "created_at": d.created_at, "due_date": d.due_date,
            "similarity": round(score * 100), "common_technologies": sorted(tech0 & tech)[:8], "common_capabilities": sorted(caps0 & caps)[:5],
            "readiness": g.get("mitigated_readiness"), "verdict": g.get("verdict"),
            "value": round(sel["price"] * pr.get("fx_to_rfp", 1)) if sel else (d.final_value or None),
            "value_currency": pr.get("rfp_currency") or pr.get("currency") if sel else None,
            "margin_pct": sel["margin_pct"] if sel else None, "outcome_notes": mask(d.outcome_notes or "")[:240],
        })
    out.sort(key=lambda x: -x["similarity"])
    return out[:limit]
