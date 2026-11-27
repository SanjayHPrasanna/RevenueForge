"""Management dashboard and the knowledge-graph API."""
from __future__ import annotations

import re
import time
from collections import Counter, defaultdict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..models import Capability, CaseStudy, Deal, DealStage, Employee, GraphEdge, GraphNode, Requirement
from ..security import Ctx, current_ctx
from ..services.solution import FX_PER_USD
from ..services import graph, llm
from ..services.masking import deal_masker

router = APIRouter(prefix="/api", tags=["insights"])


_AGG: dict[str, tuple] = {}  # tenant -> (fingerprint, saved at, aggregates)


def _req_aggregates(ctx, tid: str, deals) -> dict:
    """Counts over every requirement of the company. Reading them means decoding each one's match details, which grows
    with every deal, so the result is kept until a requirement or deal changes (checked with one cheap query), or 5 min."""
    from sqlalchemy import case
    fp = tuple(ctx.db.execute(select(func.count(), func.sum(case((Requirement.verified, 1), else_=0)), func.count(Requirement.match_status),
                                     func.sum(case((Requirement.category == Requirement.original_category, 1), else_=0)),
                                     func.sum(func.length(Requirement.category)),
                                     *[func.sum(case((Requirement.match_status == m, 1), else_=0)) for m in ("strong", "partial", "gap", "confirm")])
                              .where(Requirement.tenant_id == tid)).one())
    fp += (len(deals), max((str(d.updated_at) for d in deals), default=""))
    hit = _AGG.get(tid)
    if hit and hit[0] == fp and time.time() - hit[1] < 300:
        return hit[2]
    # Only the columns this page counts: loading whole requirement rows decoded every JSON field of every requirement.
    reqs = ctx.db.execute(select(Requirement.deal_id, Requirement.category, Requirement.original_category, Requirement.match_status,
                                 Requirement.verified, Requirement.match).where(Requirement.tenant_id == tid)).all()
    per_deal = defaultdict(Counter)
    for r in reqs:
        if r.match_status:
            per_deal[r.deal_id][r.match_status] += 1
    cat = Counter(r.category for r in reqs)
    match = Counter(r.match_status for r in reqs if r.match_status)
    reviewed = [r for r in reqs if r.verified]
    acc = round(sum(1 for r in reviewed if r.category == r.original_category) / len(reviewed) * 100, 1) if reviewed else None
    missing = Counter()
    for r in reqs:
        for t in (r.match or {}).get("technologies_missing", []):
            missing[t] += 1
    demand = Counter()
    for r in reqs:
        for e in (r.match or {}).get("evidence", [])[:1]:
            if e["type"] == "Capability":
                demand[e["name"]] += 1

    per_deal = {k: dict(v) for k, v in per_deal.items()}
    out = {"per_deal": per_deal, "cat": dict(cat), "match": dict(match), "missing": missing, "demand": demand, "total": len(reqs),
           "reviewed": len(reviewed), "acc": acc}
    _AGG[tid] = (fp, time.time(), out)
    return out


@router.get("/dashboard")
def dashboard(ctx: Ctx = Depends(current_ctx)):
    tid = ctx.tenant_id
    deals = ctx.db.scalars(select(Deal).where(Deal.tenant_id == tid).order_by(Deal.created_at.desc())).all()
    from .deals import _summaries
    pre = _summaries(ctx, [d.id for d in deals])  # statuses for every stage, content only for pricing and gaps
    pipeline_value = 0.0
    weighted = 0.0
    rows = []
    status_counts = Counter(d.status for d in deals)
    readiness = []
    first_draft = []
    for d in deals:
        st = pre[d.id]["stages"]
        pr = pre[d.id]["pricing"]
        g = pre[d.id]["gaps"]
        sel = next((s for s in pr.get("scenarios", []) if s["name"] == pr.get("selected", "Target")), None) if pr else None
        base = pr.get("currency") or ctx.tenant.currency or "USD"
        price = sel["price"] if sel else 0
        # pipeline totals in the company's currency; each deal shown in its RFP's currency
        val_usd = price / FX_PER_USD.get(base, 1) * FX_PER_USD.get(ctx.tenant.currency or "USD", 1)
        deal_val, deal_ccy = price * pr.get("fx_to_rfp", 1), pr.get("rfp_currency") or base
        if d.status not in ("won", "lost", "no_bid"):  # the pipeline is open deals; a decided deal has left it
            pipeline_value += val_usd
            weighted += val_usd * (g.get("readiness", 0) / 100)  # weighted by what the company can show today
        if g.get("readiness") is not None:
            readiness.append(g["readiness"])
        if (d.meta or {}).get("first_draft_seconds"):
            first_draft.append(d.meta["first_draft_seconds"])
        approved = sum(1 for s in st.values() if s.status == "approved")
        mask = deal_masker(d)
        rows.append({"id": d.id, "name": mask(d.name), "client": d.client_alias if d.confidential else d.client_name, "status": d.status,
                     "industry": d.industry, "engagement_type": d.engagement_type, "value": deal_val if sel else 0, "value_currency": deal_ccy if sel else None, "margin_pct": sel["margin_pct"] if sel else None,
                     "coverage_pct": g.get("coverage_pct"), "readiness": g.get("readiness"), "mitigated_readiness": g.get("mitigated_readiness"), "verdict": g.get("verdict"),
                     "approved_stages": approved, "created_at": d.created_at, "due_date": d.due_date})
    from ..models import User
    names = {u.id: u.name for u in ctx.db.scalars(select(User).where(User.tenant_id == tid))}
    owner_of = {d.id: d.owner_id for d in deals}
    for row in rows:
        oid = owner_of.get(row["id"])
        row["owner"] = {"id": oid, "name": names[oid]} if oid in names else None
    agg = _req_aggregates(ctx, tid, deals)
    for row in rows:
        row["match_mix"] = agg["per_deal"].get(row["id"], {})
    cat, match, missing, demand = agg["cat"], agg["match"], agg["missing"], agg["demand"]
    reviewed_n, acc, req_total = agg["reviewed"], agg["acc"], agg["total"]
    won = status_counts.get("won", 0)
    lost = status_counts.get("lost", 0)
    team = ctx.db.scalar(select(func.count()).select_from(Employee).where(Employee.tenant_id == tid))
    bench = ctx.db.scalar(select(func.count()).select_from(Employee).where(Employee.tenant_id == tid, Employee.availability >= 50))
    return {
        "kpis": {"deals": len(deals), "active": sum(1 for d in deals if d.status in ("processing", "in_review", "submitted")),
                 "pipeline_value": round(pipeline_value, 2), "weighted_pipeline": round(weighted, 2), "currency": ctx.tenant.currency,
                 "requirements": req_total, "avg_readiness": round(sum(readiness) / len(readiness)) if readiness else None,
                 "avg_first_draft_seconds": round(sum(first_draft) / len(first_draft), 1) if first_draft else None,
                 "win_rate": round(won / (won + lost) * 100) if (won + lost) else None, "won": won, "lost": lost,
                 "classification_accuracy": acc, "reviewed": reviewed_n, "people": team, "available_people": bench},
        "deals": rows[:50],
        "status_counts": dict(status_counts),
        "requirement_categories": dict(cat),
        "match_mix": dict(match),
        "skill_gaps": [{"technology": t, "requirements": n} for t, n in missing.most_common(10)],
        "capability_demand": [{"capability": c, "requirements": n} for c, n in demand.most_common(8)],
        "llm": llm.status(),
    }


@router.get("/graph")
def get_graph(deal_id: str | None = None, types: str = "", ctx: Ctx = Depends(current_ctx)):
    tl = [t for t in types.split(",") if t] or None
    data = graph.subgraph(ctx.db, ctx.tenant_id, deal_id, tl)
    counts = Counter(n["type"] for n in data["nodes"])
    total_nodes = ctx.db.scalar(select(func.count()).select_from(GraphNode).where(GraphNode.tenant_id == ctx.tenant_id))
    total_edges = ctx.db.scalar(select(func.count()).select_from(GraphEdge).where(GraphEdge.tenant_id == ctx.tenant_id))
    return {**data, "counts": dict(counts), "totals": {"nodes": total_nodes, "edges": total_edges}}


@router.get("/graph/node")
def node_detail(key: str, ctx: Ctx = Depends(current_ctx)):
    n = ctx.db.scalar(select(GraphNode).where(GraphNode.tenant_id == ctx.tenant_id, GraphNode.key == key))
    if not n:
        return None
    edges = ctx.db.scalars(select(GraphEdge).where(GraphEdge.tenant_id == ctx.tenant_id, (GraphEdge.src == key) | (GraphEdge.dst == key))).all()
    other = {e.dst if e.src == key else e.src for e in edges}
    labels = {x.key: (x.type, x.label) for x in ctx.db.scalars(select(GraphNode).where(GraphNode.tenant_id == ctx.tenant_id, GraphNode.key.in_(other)))}
    return {"id": n.key, "type": n.type, "label": n.label, "props": n.props,
            "links": [{"rel": e.rel, "direction": "out" if e.src == key else "in", "id": e.dst if e.src == key else e.src,
                       "type": labels.get(e.dst if e.src == key else e.src, ("", ""))[0],
                       "label": labels.get(e.dst if e.src == key else e.src, ("", ""))[1]} for e in edges][:80]}


# --------------------------------------------------------------------------- win / loss
def _rate(won: int, lost: int):
    return round(won / (won + lost) * 100) if (won + lost) else None


@router.get("/insights/winloss")
def win_loss(ctx: Ctx = Depends(current_ctx)):
    """How decided deals (won or lost) break down by margin, size, industry, engagement type and readiness."""
    tid = ctx.tenant_id
    ccy = ctx.tenant.currency or "USD"
    deals = ctx.db.scalars(select(Deal).where(Deal.tenant_id == tid)).all()
    stages = defaultdict(dict)
    for s in ctx.db.scalars(select(DealStage).where(DealStage.tenant_id == tid, DealStage.stage.in_(("gaps", "pricing")))):
        stages[s.deal_id][s.stage] = s.data or {}
    rows = []
    for d in deals:
        g, pr = stages[d.id].get("gaps", {}), stages[d.id].get("pricing", {})
        sel = next((s for s in pr.get("scenarios", []) if s["name"] == pr.get("selected", "Target")), None) if pr else None
        base = pr.get("currency") or ccy
        if d.final_value and d.status in ("won", "lost"):
            # the contract value recorded at the outcome (entered in the RFP's currency) beats the price we proposed
            rccy = pr.get("rfp_currency") or base
            value = d.final_value / FX_PER_USD.get(rccy, 1) * FX_PER_USD.get(ccy, 1)
        else:
            value = (sel["price"] / FX_PER_USD.get(base, 1) * FX_PER_USD.get(ccy, 1)) if sel else (d.final_value or 0)
        mask = deal_masker(d)
        rows.append({"id": d.id, "name": mask(d.name), "client": d.client_alias if d.confidential else d.client_name, "status": d.status,
                     "industry": d.industry or "Not set", "engagement_type": d.engagement_type or "not_set", "value": round(value),
                     "margin_pct": sel["margin_pct"] if sel else None, "readiness": g.get("readiness"), "coverage": g.get("coverage_pct"),
                     "updated_at": d.updated_at, "notes": mask(d.outcome_notes or "")[:200]})
    decided = [r for r in rows if r["status"] in ("won", "lost")]

    def breakdown(key_fn, order=None):
        b = defaultdict(lambda: [0, 0, 0.0])
        for r in decided:
            k = key_fn(r)
            if k is None:
                continue
            b[k][0 if r["status"] == "won" else 1] += 1
            if r["status"] == "won":
                b[k][2] += r["value"]
        keys = order or sorted(b, key=lambda k: -(b[k][0] + b[k][1]))
        return [{"label": k, "won": b[k][0], "lost": b[k][1], "win_rate": _rate(b[k][0], b[k][1]), "won_value": round(b[k][2])} for k in keys if k in b]

    def margin_band(r):
        m = r["margin_pct"]
        return None if m is None else "Under 20%" if m < 20 else "20–30%" if m < 30 else "30% and above"

    def size_band(r):
        v = r["value"]
        return None if not v else f"Under {ccy} 0.5M" if v < 5e5 else f"{ccy} 0.5–2M" if v < 2e6 else f"{ccy} 2M and above"

    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs)) if xs else None

    won = [r for r in decided if r["status"] == "won"]
    lost = [r for r in decided if r["status"] == "lost"]
    return {
        "currency": ccy,
        "totals": {"decided": len(decided), "won": len(won), "lost": len(lost), "win_rate": _rate(len(won), len(lost)),
                   "won_value": round(sum(r["value"] for r in won)), "open": sum(1 for r in rows if r["status"] in ("in_review", "submitted", "processing")),
                   "no_bid": sum(1 for r in rows if r["status"] == "no_bid")},
        "won_vs_lost": {"readiness": [avg(r["readiness"] for r in won), avg(r["readiness"] for r in lost)],
                        "margin": [avg(r["margin_pct"] for r in won), avg(r["margin_pct"] for r in lost)],
                        "coverage": [avg(r["coverage"] for r in won), avg(r["coverage"] for r in lost)],
                        "value": [avg(r["value"] for r in won), avg(r["value"] for r in lost)]},
        "by_margin": breakdown(margin_band, ["Under 20%", "20–30%", "30% and above"]),
        "by_size": breakdown(size_band, [f"Under {ccy} 0.5M", f"{ccy} 0.5–2M", f"{ccy} 2M and above"]),
        "by_industry": breakdown(lambda r: r["industry"]),
        "by_engagement": breakdown(lambda r: r["engagement_type"]),
        "recent": sorted(decided, key=lambda r: r["updated_at"] or 0, reverse=True)[:10],
    }


@router.get("/insights/market")
def market_insights(ctx: Ctx = Depends(current_ctx)):
    """Where the company's capabilities and products are in demand, counted from public tenders the radar has read."""
    if (ctx.tenant.kind or "vendor") == "buyer":
        raise HTTPException(403, "Market insights are for supplier workspaces.")
    from ..services import market
    return market.market(ctx.db, ctx.tenant)


