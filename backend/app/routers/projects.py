"""Delivery 360: what happens after a bid is won.

A won deal becomes a project. The bid seeds it: the plan's phases become milestones, the estimated team becomes the
staffing plan, the selected price and its cost become the contract value and the budget, and the bid's high-risk gaps
become the first risks. From there the delivery team tracks milestones, people, money (invoices, costs, change
requests), risks and issues, SLA months and status reports until the project closes.

Health is worked out from the facts (late milestones, overdue invoices, cost burning faster than progress, open
high risks) and always comes with the reasons, so a project is never shown green when the numbers say otherwise.

Client 360 brings every deal and project for one client together.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..models import Deal, DealStage, Project, ProjectItem, User
from ..security import Ctx, current_ctx, require_roles
from ..services.masking import deal_masker

router = APIRouter(prefix="/api", tags=["projects"])
EDIT = ("presales", "delivery", "finance", "architect")

KINDS = {
    "milestone": {"statuses": ["planned", "in_progress", "done"], "data": {"detail": str, "billing_pct": float}},
    "member": {"statuses": ["planned", "active", "released"], "data": {"person": str, "allocation_pct": float, "location": str, "day_rate": float, "start": str, "end": str}},
    "risk": {"statuses": ["open", "mitigating", "closed"], "data": {"impact": str, "likelihood": str, "mitigation": str, "source": str}},
    "issue": {"statuses": ["open", "resolved"], "data": {"severity": str, "resolution": str}},
    "change": {"statuses": ["proposed", "approved", "rejected"], "data": {"effort_days": float, "schedule_days": float, "reason": str}},
    "invoice": {"statuses": ["draft", "raised", "paid"], "data": {"number": str, "milestone": str}},
    "cost": {"statuses": [""], "data": {"category": str}},
    "sla": {"statuses": [""], "data": {"target_pct": float, "achieved_pct": float, "incidents": float, "breaches": float}},
    "update": {"statuses": ["green", "amber", "red"], "data": {"done": str, "next": str, "blockers": str}},
}
PROJECT_STATUSES = ["planning", "active", "on_hold", "completed", "cancelled"]
LEVELS = ("low", "medium", "high")


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _d(s: str) -> date | None:
    try:
        return date.fromisoformat((s or "")[:10])
    except ValueError:
        return None


def _date_in(v, field: str) -> str:
    if v in (None, ""):
        return ""
    if not isinstance(v, str) or not _d(v):
        raise HTTPException(400, f"{field.replace('_', ' ').capitalize()} must be a date (YYYY-MM-DD).")
    return v[:10]


def _num(v, field: str) -> float:
    try:
        x = float(v or 0)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{field.replace('_', ' ').capitalize()} must be a number.")
    if x != x or x in (float("inf"), float("-inf")):
        raise HTTPException(400, f"{field.replace('_', ' ').capitalize()} must be a number.")
    return x


def client_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "not-named"


def _deal_client(d: Deal) -> str:
    return (d.client_alias if d.confidential else d.client_name) or "Client not named"


def _stage_data(ctx: Ctx, deal_id: str, stage: str) -> dict:
    st = ctx.db.scalar(select(DealStage).where(DealStage.deal_id == deal_id, DealStage.stage == stage))
    return (st.data or {}) if st else {}


# =========================================================================== the numbers behind a project
def summarize(p: Project, items: list[ProjectItem]) -> dict:
    today = _today()
    by = defaultdict(list)
    for i in items:
        by[i.kind].append(i)
    ms = sorted(by["milestone"], key=lambda i: (i.due_date or "9999", i.sort))
    done = [m for m in ms if m.status == "done"]
    late = [m for m in ms if m.status != "done" and _d(m.due_date) and _d(m.due_date) < today]
    progress = round(len(done) / len(ms) * 100) if ms else None
    nxt = next((m for m in ms if m.status != "done"), None)

    s, e = _d(p.start_date), _d(p.end_date)
    time_pct = None
    if s and e and e > s:
        time_pct = max(0, min(100, round((today - s).days / (e - s).days * 100)))

    approved = [c for c in by["change"] if c.status == "approved"]
    value_total = (p.contract_value or 0) + sum(c.amount for c in approved)
    cost_actual = sum(c.amount for c in by["cost"])
    budget = (p.budget_cost or 0) + sum(float((c.data or {}).get("cost") or 0) for c in approved)
    burn = round(cost_actual / budget * 100) if budget else None
    inv = by["invoice"]
    invoiced = sum(i.amount for i in inv if i.status in ("raised", "paid"))
    paid = sum(i.amount for i in inv if i.status == "paid")
    overdue = [i for i in inv if i.status == "raised" and _d(i.due_date) and _d(i.due_date) < today]
    overdue_amt = sum(i.amount for i in overdue)
    oldest_overdue = max(((today - _d(i.due_date)).days for i in overdue), default=0)

    planned_margin = round((p.contract_value - p.budget_cost) / p.contract_value * 100, 1) if p.contract_value and p.budget_cost else None
    eac = forecast_margin = None
    if progress and progress >= 10 and cost_actual:
        eac = round(cost_actual / (progress / 100), 2)  # cost at this pace, if the rest goes like the part done so far
        forecast_margin = round((value_total - eac) / value_total * 100, 1) if value_total else None

    risks_open = [r for r in by["risk"] if r.status != "closed"]
    high_risks = [r for r in risks_open if (r.data or {}).get("impact") == "high"]
    issues_open = [i for i in by["issue"] if i.status == "open"]
    pending_changes = [c for c in by["change"] if c.status == "proposed"]
    members = [m for m in by["member"] if m.status != "released"]
    fte = round(sum(float((m.data or {}).get("allocation_pct") or 100) for m in members) / 100, 1)
    sla = sorted(by["sla"], key=lambda i: i.due_date or "")
    last_sla = sla[-1] if sla else None
    sla_miss = [x for x in sla if (x.data or {}).get("achieved_pct") is not None and (x.data or {}).get("target_pct") is not None
                and float(x.data["achieved_pct"]) < float(x.data["target_pct"])]
    updates = sorted(by["update"], key=lambda i: i.created_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    # health from the facts, with the reasons
    red, amber = [], []
    if len(late) >= 2:
        red.append(f"{len(late)} milestones are late")
    elif late:
        amber.append(f"Milestone late: {late[0].title} (due {late[0].due_date})")
    if overdue:
        (red if oldest_overdue > 30 else amber).append(f"{len(overdue)} invoice(s) overdue, oldest by {oldest_overdue} days")
    if burn is not None and progress is not None:
        gap = burn - progress
        if gap > 25:
            red.append(f"Cost is {burn}% of budget with {progress}% of milestones done")
        elif gap > 10:
            amber.append(f"Cost ({burn}% of budget) is ahead of progress ({progress}%)")
    if burn is not None and burn > 100:
        red.append(f"Over budget: cost is {burn}% of budget")
    if high_risks:
        amber.append(f"{len(high_risks)} open high-impact risk(s)")
    if [i for i in issues_open if (i.data or {}).get("severity") == "high"]:
        amber.append("Open high-severity issue")
    if sla_miss and last_sla in sla_miss:
        amber.append(f"SLA missed in {last_sla.title}")
    if time_pct is not None and progress is not None and time_pct - progress > 30 and p.status == "active":
        amber.append(f"{time_pct}% of the time used, {progress}% of milestones done")
    health = "red" if red else "amber" if amber else "green"
    if p.status in ("completed", "cancelled"):
        health = "closed"

    return {
        "health": health, "health_reasons": red + amber,
        "reported_health": updates[0].status if updates else None, "last_update_at": updates[0].created_at if updates else None,
        "progress_pct": progress, "time_pct": time_pct, "milestones": {"total": len(ms), "done": len(done), "late": len(late)},
        "next_milestone": {"id": nxt.id, "title": nxt.title, "due_date": nxt.due_date, "late": nxt in late} if nxt else None,
        "value_total": round(value_total, 2), "approved_changes": round(sum(c.amount for c in approved), 2), "pending_changes": len(pending_changes),
        "budget_cost": round(budget, 2), "cost_actual": round(cost_actual, 2), "burn_pct": burn,
        "planned_margin_pct": planned_margin, "forecast_cost": eac, "forecast_margin_pct": forecast_margin,
        "invoiced": round(invoiced, 2), "paid": round(paid, 2), "outstanding": round(invoiced - paid, 2), "unbilled": round(value_total - invoiced, 2),
        "overdue": round(overdue_amt, 2), "overdue_count": len(overdue),
        "risks_open": len(risks_open), "risks_high": len(high_risks), "issues_open": len(issues_open),
        "team_size": len(members), "fte": fte,
        "sla_latest": {"month": last_sla.title, **{k: (last_sla.data or {}).get(k) for k in ("target_pct", "achieved_pct", "breaches")}} if last_sla else None,
        "sla_missed_months": len(sla_miss),
    }


def item_out(i: ProjectItem) -> dict:
    today = _today()
    late = i.kind in ("milestone", "invoice") and i.status not in ("done", "paid", "draft") and bool(_d(i.due_date)) and _d(i.due_date) < today
    return {"id": i.id, "kind": i.kind, "title": i.title, "status": i.status, "owner": i.owner, "due_date": i.due_date, "done_date": i.done_date,
            "amount": i.amount, "data": i.data or {}, "sort": i.sort, "late": late, "created_at": i.created_at, "updated_at": i.updated_at}


def project_out(ctx: Ctx, p: Project, items: list[ProjectItem] | None = None, full: bool = False, users: dict | None = None) -> dict:
    if items is None:
        items = list(ctx.db.scalars(select(ProjectItem).where(ProjectItem.project_id == p.id)))
    mgr = (users.get(p.manager_id) if users is not None else ctx.db.get(User, p.manager_id)) if p.manager_id else None
    out = {"id": p.id, "deal_id": p.deal_id, "name": p.name, "client": p.client_name, "client_key": client_key(p.client_name), "status": p.status,
           "engagement_type": p.engagement_type, "industry": p.industry, "region": p.region, "currency": p.currency,
           "contract_value": p.contract_value, "budget_cost": p.budget_cost, "start_date": p.start_date, "end_date": p.end_date,
           "actual_end_date": p.actual_end_date, "description": p.description,
           "manager": {"id": mgr.id, "name": mgr.name} if mgr and mgr.tenant_id == p.tenant_id else None,
           "created_at": p.created_at, "updated_at": p.updated_at, "summary": summarize(p, items)}
    if full:
        out["bid"] = (p.meta or {}).get("bid") or None
        out["items"] = [item_out(i) for i in sorted(items, key=lambda i: (i.kind, i.sort, i.due_date or "9999", i.created_at or datetime.min.replace(tzinfo=timezone.utc)))]
    return out


def _project(ctx: Ctx, pid: str) -> Project:
    p = ctx.db.get(Project, pid)
    if not p or p.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Project not found.")
    return p


# =========================================================================== projects
@router.get("/projects")
def list_projects(ctx: Ctx = Depends(current_ctx)):
    rows = ctx.db.scalars(select(Project).where(Project.tenant_id == ctx.tenant_id).order_by(Project.created_at.desc())).all()
    items = defaultdict(list)
    if rows:
        for i in ctx.db.scalars(select(ProjectItem).where(ProjectItem.tenant_id == ctx.tenant_id)):
            items[i.project_id].append(i)
    users = {u.id: u for u in ctx.db.scalars(select(User).where(User.tenant_id == ctx.tenant_id))}
    projects = [project_out(ctx, p, items[p.id], users=users) for p in rows]
    have = {p.deal_id for p in rows if p.deal_id}
    won = ctx.db.scalars(select(Deal).where(Deal.tenant_id == ctx.tenant_id, Deal.status == "won").order_by(Deal.updated_at.desc())).all()
    ready = [{"deal_id": d.id, "name": deal_masker(d)(d.name), "client": _deal_client(d), "final_value": d.final_value,
              "currency": d.currency, "won_at": d.updated_at} for d in won if d.id not in have]
    return {"projects": projects, "ready": ready}


@router.post("/projects")
def create_project(body: dict, ctx: Ctx = Depends(require_roles(*EDIT))):
    if not isinstance(body, dict):
        raise HTTPException(400, "Send the project as an object.")
    did = str(body.get("deal_id") or "")
    if did:
        d = ctx.db.get(Deal, did)
        if not d or d.tenant_id != ctx.tenant_id:
            raise HTTPException(404, "Deal not found.")
        if d.status != "won":
            raise HTTPException(400, "Mark the deal as won first. Projects start from won deals.")
        existing = ctx.db.scalar(select(Project).where(Project.tenant_id == ctx.tenant_id, Project.deal_id == d.id))
        if existing:
            return project_out(ctx, existing, full=True)
        p = _seed_from_deal(ctx, d, _date_in(body.get("start_date"), "start_date") or _today().isoformat())
    else:
        name = str(body.get("name") or "").strip()
        if not name:
            raise HTTPException(400, "Give the project a name.")
        p = Project(tenant_id=ctx.tenant_id, name=name[:300], client_name=str(body.get("client_name") or "").strip()[:300],
                    currency=str(body.get("currency") or "")[:8].upper(), contract_value=_num(body.get("contract_value"), "contract_value"),
                    budget_cost=_num(body.get("budget_cost"), "budget_cost"), start_date=_date_in(body.get("start_date"), "start_date") or _today().isoformat(),
                    end_date=_date_in(body.get("end_date"), "end_date"), manager_id=ctx.user.id, status="planning")
        ctx.db.add(p)
    ctx.audit("project.create", p.name, deal=did)
    ctx.db.commit()
    return project_out(ctx, p, full=True)


def _seed_from_deal(ctx: Ctx, d: Deal, start: str) -> Project:
    est = _stage_data(ctx, d.id, "estimation")
    pr = _stage_data(ctx, d.id, "pricing")
    gaps = _stage_data(ctx, d.id, "gaps")
    sel = None
    if pr.get("scenarios"):
        sel = next((s for s in pr["scenarios"] if s.get("name") == pr.get("selected", "Target")), pr["scenarios"][0])
    fx = pr.get("fx_to_rfp") or 1
    price = round((sel or {}).get("price", 0) * fx, 2)
    cost = round(((sel or {}).get("price", 0) - (sel or {}).get("gross_profit", 0)) * fx, 2) if sel else 0
    value = d.final_value or price
    sd = _d(start) or _today()
    months = est.get("contract_months") or est.get("duration_months") or 6
    end = sd + timedelta(days=round(float(months) * 30.4))
    p = Project(tenant_id=ctx.tenant_id, deal_id=d.id, name=deal_masker(d)(d.name)[:300], client_name=_deal_client(d), status="planning",
                engagement_type=d.engagement_type or est.get("engagement_type") or "", industry=d.industry, region=d.region,
                currency=(pr.get("rfp_currency") or d.currency or "")[:8], contract_value=value, budget_cost=cost,
                start_date=sd.isoformat(), end_date=end.isoformat(), manager_id=ctx.user.id,
                meta={"bid": {"verdict": gaps.get("verdict"), "readiness": gaps.get("readiness"), "mitigated_readiness": gaps.get("mitigated_readiness"),
                              "coverage_pct": gaps.get("coverage_pct"), "price": price, "final_value": d.final_value,
                              "margin_pct": (sel or {}).get("margin_pct"), "scenario": (sel or {}).get("name"),
                              "headcount": est.get("headcount"), "months": months, "seeded": True}})
    ctx.db.add(p)
    ctx.db.flush()
    add = lambda **kw: ctx.db.add(ProjectItem(tenant_id=ctx.tenant_id, project_id=p.id, created_by=ctx.user.id, **kw))

    # milestones from the bid's delivery plan
    phases = est.get("phases") or []
    wk = 0.0
    n = 0
    for ph in phases:
        try:
            weeks = float(ph.get("weeks") or 0)
        except (TypeError, ValueError):
            weeks = 0
        wk += max(1, weeks)
        n += 1
        add(kind="milestone", title=f"{ph.get('name', 'Phase')} complete"[:400], status="planned", sort=n,
            due_date=(sd + timedelta(days=round(wk * 7))).isoformat(), data={"detail": str(ph.get("detail") or "")[:500]})
    if not phases:
        for n, (t, frac) in enumerate([("Mobilisation complete", 0.05), ("Design signed off", 0.25), ("Build complete", 0.6),
                                       ("User acceptance signed off", 0.8), ("Go-live", 0.9), ("Project closed", 1.0)], start=1):
            add(kind="milestone", title=t, status="planned", sort=n, due_date=(sd + timedelta(days=round((end - sd).days * frac))).isoformat())

    # the staffing plan: named people where the bid found them, open roles where it didn't
    for n, t in enumerate(est.get("team") or [], start=1):
        people = t.get("assigned") or []
        for person in people:
            add(kind="member", title=str(t.get("role") or "Role")[:400], status="planned", sort=n,
                data={"person": str(person.get("code") or person.get("name") or "")[:120], "allocation_pct": round(min(100, float(t.get("fte") or 1) / max(1, len(people)) * 100)),
                      "location": str(t.get("location") or ""), "start": "", "end": ""}, owner=str(t.get("phase") or ""))
        for _ in range(int(t.get("unfilled") or 0)):
            add(kind="member", title=str(t.get("role") or "Role")[:400], status="planned", sort=n,
                data={"person": "", "allocation_pct": 100, "location": str(t.get("location") or "")}, owner=str(t.get("phase") or ""))

    # risks the bid already knew about
    for n, g in enumerate((gaps.get("top_missing") or [])[:8], start=1):
        add(kind="risk", title=f"Capability gap: {g.get('technology')}"[:400], status="open", sort=n,
            data={"impact": "high" if n <= 3 else "medium", "likelihood": "medium",
                  "mitigation": str(g.get("recommendation") or "")[:500], "source": "bid gap analysis"})
    return p


@router.get("/projects/{pid}")
def get_project(pid: str, ctx: Ctx = Depends(current_ctx)):
    p = _project(ctx, pid)
    out = project_out(ctx, p, full=True)
    if p.deal_id:
        d = ctx.db.get(Deal, p.deal_id)
        out["deal"] = {"id": d.id, "name": deal_masker(d)(d.name), "status": d.status} if d and d.tenant_id == ctx.tenant_id else None
    return out


@router.patch("/projects/{pid}")
def update_project(pid: str, body: dict, ctx: Ctx = Depends(require_roles(*EDIT))):
    p = _project(ctx, pid)
    if not isinstance(body, dict):
        raise HTTPException(400, "Send the changes as an object.")
    for f, n in (("name", 300), ("client_name", 300), ("description", 4000), ("industry", 120), ("region", 120)):
        if f in body:
            v = str(body[f] or "").strip()
            if f == "name" and not v:
                raise HTTPException(400, "The project needs a name.")
            setattr(p, f, v[:n])
    if "currency" in body:
        p.currency = str(body["currency"] or "")[:8].upper()
    for f in ("contract_value", "budget_cost"):
        if f in body:
            v = _num(body[f], f)
            if v < 0:
                raise HTTPException(400, f"{f.replace('_', ' ').capitalize()} can't be negative.")
            setattr(p, f, v)
    for f in ("start_date", "end_date", "actual_end_date"):
        if f in body:
            setattr(p, f, _date_in(body[f], f))
    if "status" in body:
        if body["status"] not in PROJECT_STATUSES:
            raise HTTPException(400, "Unknown project status.")
        p.status = body["status"]
        if p.status == "completed" and not p.actual_end_date:
            p.actual_end_date = _today().isoformat()
        ctx.audit("project.status", p.id, status=p.status)
    if "manager_id" in body:
        u = ctx.db.get(User, str(body["manager_id"] or ""))
        if not u or u.tenant_id != ctx.tenant_id or not u.is_active:
            raise HTTPException(400, "Pick an active person from your company.")
        p.manager_id = u.id
    if p.start_date and p.end_date and p.end_date < p.start_date:
        raise HTTPException(400, "The end date is before the start date.")
    ctx.db.commit()
    return get_project(pid, ctx)


@router.delete("/projects/{pid}")
def delete_project(pid: str, ctx: Ctx = Depends(require_roles())):
    p = _project(ctx, pid)
    ctx.db.query(ProjectItem).filter(ProjectItem.project_id == p.id).delete()
    ctx.db.delete(p)
    ctx.audit("project.delete", pid)
    ctx.db.commit()
    return {"ok": True}


def _apply_item(i: ProjectItem, body: dict, creating: bool):
    spec = KINDS[i.kind]
    if "title" in body or creating:
        t = str(body.get("title") or "").strip()
        if not t:
            raise HTTPException(400, "Give it a title.")
        i.title = t[:400]
    if "status" in body or creating:
        st = body.get("status", spec["statuses"][0])
        if st not in spec["statuses"]:
            raise HTTPException(400, f"Status must be one of: {', '.join(s for s in spec['statuses'] if s) or 'none'}.")
        i.status = st
    if "owner" in body:
        i.owner = str(body["owner"] or "")[:200]
    for f in ("due_date", "done_date"):
        if f in body:
            setattr(i, f, _date_in(body[f], f))
    if "amount" in body:
        v = _num(body["amount"], "amount")
        if v < 0 and i.kind != "change":
            raise HTTPException(400, "Amount can't be negative.")
        i.amount = v
    if "data" in body:
        if not isinstance(body["data"], dict):
            raise HTTPException(400, "data must be an object.")
        d = dict(i.data or {})
        for k, v in body["data"].items():
            if k not in spec["data"]:
                continue
            if spec["data"][k] is float:
                d[k] = None if v in (None, "") else _num(v, k)
            else:
                d[k] = str(v or "")[:2000]
        for k in ("impact", "likelihood", "severity"):
            if k in d and d[k] and d[k] not in LEVELS:
                raise HTTPException(400, f"{k.capitalize()} must be low, medium or high.")
        i.data = d
    if i.kind == "milestone" and i.status == "done" and not i.done_date:
        i.done_date = _today().isoformat()
    if i.kind == "invoice" and i.status == "paid" and not i.done_date:
        i.done_date = _today().isoformat()


@router.post("/projects/{pid}/items")
def add_item(pid: str, body: dict, ctx: Ctx = Depends(require_roles(*EDIT))):
    p = _project(ctx, pid)
    if not isinstance(body, dict) or body.get("kind") not in KINDS:
        raise HTTPException(400, f"kind must be one of: {', '.join(KINDS)}.")
    if ctx.db.query(ProjectItem).filter(ProjectItem.project_id == p.id).count() >= 2000:
        raise HTTPException(400, "This project has 2,000 entries already.")
    i = ProjectItem(tenant_id=ctx.tenant_id, project_id=p.id, kind=body["kind"], title="", created_by=ctx.user.id, data={})
    if i.kind == "update":
        body = {**body, "title": body.get("title") or "Status update"}
    _apply_item(i, body, creating=True)
    i.sort = ctx.db.query(ProjectItem).filter(ProjectItem.project_id == p.id, ProjectItem.kind == i.kind).count() + 1
    ctx.db.add(i)
    if p.status == "planning" and i.kind in ("cost", "invoice", "update"):
        p.status = "active"  # money moving or status reported: the work has started
    p.updated_at = datetime.now(timezone.utc)
    ctx.audit("project.item_add", p.id, kind=i.kind)
    ctx.db.commit()
    return item_out(i)


def _item(ctx: Ctx, p: Project, iid: str) -> ProjectItem:
    i = ctx.db.get(ProjectItem, iid)
    if not i or i.project_id != p.id:
        raise HTTPException(404, "Entry not found.")
    return i


@router.patch("/projects/{pid}/items/{iid}")
def update_item(pid: str, iid: str, body: dict, ctx: Ctx = Depends(require_roles(*EDIT))):
    p = _project(ctx, pid)
    i = _item(ctx, p, iid)
    if not isinstance(body, dict):
        raise HTTPException(400, "Send the changes as an object.")
    _apply_item(i, body, creating=False)
    p.updated_at = datetime.now(timezone.utc)
    ctx.db.commit()
    return item_out(i)


@router.delete("/projects/{pid}/items/{iid}")
def delete_item(pid: str, iid: str, ctx: Ctx = Depends(require_roles(*EDIT))):
    p = _project(ctx, pid)
    i = _item(ctx, p, iid)
    ctx.db.delete(i)
    ctx.audit("project.item_delete", p.id, kind=i.kind)
    ctx.db.commit()
    return {"ok": True}


# =========================================================================== client 360
def _client_rows(ctx: Ctx):
    deals = ctx.db.scalars(select(Deal).where(Deal.tenant_id == ctx.tenant_id)).all()
    projects = ctx.db.scalars(select(Project).where(Project.tenant_id == ctx.tenant_id)).all()
    items = defaultdict(list)
    if projects:
        for i in ctx.db.scalars(select(ProjectItem).where(ProjectItem.tenant_id == ctx.tenant_id)):
            items[i.project_id].append(i)
    clients: dict[str, dict] = {}

    def c(name: str) -> dict:
        k = client_key(name)
        return clients.setdefault(k, {"key": k, "name": name or "Client not named", "deals": [], "projects": []})
    for d in deals:
        c(_deal_client(d))["deals"].append(d)
    for p in projects:
        c(p.client_name or "Client not named")["projects"].append((p, summarize(p, items[p.id])))
    return clients


def _money_by_ccy(pairs) -> dict:
    out: dict[str, float] = defaultdict(float)
    for ccy, v in pairs:
        if v:
            out[ccy or "?"] += v
    return {k: round(v, 2) for k, v in out.items()}


def _client_card(c: dict) -> dict:
    deals, projects = c["deals"], c["projects"]
    won = [d for d in deals if d.status == "won"]
    lost = [d for d in deals if d.status == "lost"]
    open_ = [d for d in deals if d.status in ("processing", "in_review", "submitted")]
    health_rank = {"red": 0, "amber": 1, "green": 2, "closed": 3}
    live = [(p, s) for p, s in projects if p.status not in ("completed", "cancelled")]
    worst = min((s["health"] for p, s in live), key=lambda h: health_rank[h], default=None)
    times = [d.updated_at for d in deals if d.updated_at] + [p.updated_at for p, _ in projects if p.updated_at]
    times = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in times]
    return {"key": c["key"], "name": c["name"],
            "deals": {"total": len(deals), "open": len(open_), "won": len(won), "lost": len(lost)},
            "win_rate": round(len(won) / (len(won) + len(lost)) * 100) if (won or lost) else None,
            "projects": {"total": len(projects), "live": len(live)},
            "contracted": _money_by_ccy((p.currency, s["value_total"]) for p, s in projects),
            "invoiced": _money_by_ccy((p.currency, s["invoiced"]) for p, s in projects),
            "paid": _money_by_ccy((p.currency, s["paid"]) for p, s in projects),
            "outstanding": _money_by_ccy((p.currency, s["outstanding"]) for p, s in projects),
            "overdue": _money_by_ccy((p.currency, s["overdue"]) for p, s in projects),
            "health": worst, "industry": next((d.industry for d in deals if d.industry), "") or next((p.industry for p, _ in projects if p.industry), ""),
            "last_activity": max(times) if times else None}


@router.get("/clients")
def list_clients(ctx: Ctx = Depends(current_ctx)):
    rows = [_client_card(c) for c in _client_rows(ctx).values()]
    rows.sort(key=lambda r: (r["last_activity"] or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    return rows


@router.get("/clients/{key}")
def get_client(key: str, ctx: Ctx = Depends(current_ctx)):
    c = _client_rows(ctx).get(key)
    if not c:
        raise HTTPException(404, "No deals or projects for this client.")
    card = _client_card(c)
    from .deals import _summaries
    pre = _summaries(ctx, [d.id for d in c["deals"]]) if c["deals"] else {}
    deals = []
    for d in sorted(c["deals"], key=lambda d: d.created_at, reverse=True):
        g = pre.get(d.id, {}).get("gaps") or {}
        pr = pre.get(d.id, {}).get("pricing") or {}
        sel = next((s for s in pr.get("scenarios") or [] if s["name"] == pr.get("selected", "Target")), None)
        deals.append({"id": d.id, "name": deal_masker(d)(d.name), "status": d.status, "verdict": g.get("verdict"), "readiness": g.get("readiness"),
                      "value": round(sel["price"] * pr.get("fx_to_rfp", 1), 2) if sel else None, "final_value": d.final_value,
                      "currency": pr.get("rfp_currency") or d.currency, "due_date": d.due_date, "created_at": d.created_at,
                      "engagement_type": d.engagement_type})
    projects = [{"id": p.id, "name": p.name, "status": p.status, "currency": p.currency, "start_date": p.start_date, "end_date": p.end_date,
                 "deal_id": p.deal_id, "summary": s} for p, s in sorted(c["projects"], key=lambda x: x[0].created_at, reverse=True)]
    # one timeline across bids and delivery
    ev = []
    for d in c["deals"]:
        dn = deal_masker(d)(d.name)
        ev.append({"at": d.created_at, "kind": "deal", "text": f"Bid started: {dn}", "link": f"/app/deals/{d.id}"})
        if d.status in ("won", "lost", "no_bid", "submitted"):
            ev.append({"at": d.updated_at, "kind": d.status, "text": f"{dn}: {d.status.replace('_', ' ')}", "link": f"/app/deals/{d.id}"})
    pids = {p.id: p for p, _ in c["projects"]}
    for p in pids.values():
        ev.append({"at": p.created_at, "kind": "project", "text": f"Project started: {p.name}", "link": f"/app/projects/{p.id}"})
    if pids:
        for i in ctx.db.scalars(select(ProjectItem).where(ProjectItem.project_id.in_(list(pids)), ProjectItem.kind.in_(["milestone", "invoice", "change", "update"]))):
            p = pids[i.project_id]
            if i.kind == "milestone" and i.status == "done":
                ev.append({"at": i.updated_at, "kind": "milestone", "text": f"{p.name}: {i.title}", "link": f"/app/projects/{p.id}/plan"})
            elif i.kind == "invoice" and i.status == "paid":
                ev.append({"at": i.updated_at, "kind": "paid", "text": f"{p.name}: invoice {(i.data or {}).get('number') or i.title} paid", "amount": i.amount,
                           "currency": p.currency, "link": f"/app/projects/{p.id}/money"})
            elif i.kind == "change" and i.status == "approved":
                ev.append({"at": i.updated_at, "kind": "change", "text": f"{p.name}: change approved, {i.title}", "amount": i.amount,
                           "currency": p.currency, "link": f"/app/projects/{p.id}/money"})
            elif i.kind == "update":
                ev.append({"at": i.created_at, "kind": "update", "text": f"{p.name}: status {i.status}, {i.title}", "link": f"/app/projects/{p.id}/updates"})
    for e in ev:
        if e["at"] and not e["at"].tzinfo:
            e["at"] = e["at"].replace(tzinfo=timezone.utc)
    ev.sort(key=lambda e: e["at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {**card, "deal_list": deals, "project_list": projects, "timeline": ev[:60]}
