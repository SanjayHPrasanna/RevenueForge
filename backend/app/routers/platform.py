"""Platform console: the server operator's view across every company.

Who: only the people listed in PLATFORM_ADMINS (Azure setting), signed in with their normal account.
What they see: companies, their people (name, email, role, activity), counts, AI usage, system health and security events.
What they never see: any company's deals, requirements, library entries, files, proposals or Maahi conversations; only
how many there are. What they can do: pause or reactivate a company or a person, change a role, and sign someone out
everywhere. Every one of those actions is recorded, in the company's own audit trail too.
"""
from __future__ import annotations

import os
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from ..config import OUTPUT_DIR, UPLOAD_DIR, settings
from ..models import (Accelerator, AiUsage, AuditLog, Award, CaseStudy, Capability, Certification, Deal, Employee, RateCard,
                      Tender, TenderSource, Tenant, User)
from ..security import Ctx, current_ctx
from ..services import ai_settings, company_ai, errlog, llm

router = APIRouter(prefix="/api/platform", tags=["platform"])
STARTED = datetime.now(timezone.utc)
ROLES = ["admin", "presales", "architect", "finance", "delivery", "viewer"]
SECURITY_ACTIONS = {
    "auth.sign_in": "Signed in", "auth.sign_in_failed": "Failed sign-in", "auth.locked_out": "Locked out (too many failures)",
    "auth.register": "New workspace created", "user.invite": "Person added", "user.role_change": "Role changed",
    "user.disable": "Person disabled", "user.enable": "Person re-enabled", "company.export": "All company data downloaded",
    "company.deleted": "Company deleted", "company.ai.update": "Company AI key changed", "ai.config.update": "Server AI changed",
    "ai.config.reset": "Server AI reset", "platform.company_suspend": "Platform: company paused",
    "platform.company_reactivate": "Platform: company reactivated", "platform.user_suspend": "Platform: person paused",
    "platform.user_reactivate": "Platform: person reactivated", "platform.user_role": "Platform: role changed",
    "platform.user_signout": "Platform: signed out everywhere",
}
SAFE_DETAIL = ("method", "reason", "before", "after", "role", "provider")  # detail fields shown; nothing else leaves a company


def platform_ctx(ctx: Ctx = Depends(current_ctx)) -> Ctx:
    if not ai_settings.is_platform_admin(ctx.user.email):
        raise HTTPException(403, "Only the server's platform admins can open the platform console.")
    return ctx


def _utc(d: datetime | None) -> datetime | None:
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=timezone.utc))


def _days(n: int) -> list[str]:
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _since(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


_size_cache: dict[str, tuple[float, int]] = {}
_size_lock = threading.Lock()


def _folder_bytes(tid: str) -> int:
    """Disk used by a company's uploaded and generated files (cached for 10 minutes: walking folders is slow)."""
    with _size_lock:
        hit = _size_cache.get(tid)
        if hit and time.time() - hit[0] < 600:
            return hit[1]
    total = 0
    for root in (UPLOAD_DIR / tid, OUTPUT_DIR / tid):
        if root.exists():
            for dirpath, _, files in os.walk(root):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
    with _size_lock:
        _size_cache[tid] = (time.time(), total)
    return total


def _count_by_tenant(db, model, *where) -> dict[str, int]:
    q = select(model.tenant_id, func.count()).group_by(model.tenant_id)
    for w in where:
        q = q.where(w)
    return {t: n for t, n in db.execute(q)}


def _ai_mode(t: Tenant) -> dict:
    v = company_ai.view(t)
    own = v["provider"] != "default"
    return {"own_key": own, "provider": v["provider"] if own else llm._usable(llm.server_profile()),
            "model": v.get("model", "") if own else ""}


def _event(e: AuditLog, names: dict[str, str]) -> dict:
    return {"at": _utc(e.at).isoformat() if e.at else "", "company": names.get(e.tenant_id, "") if e.tenant_id else "",
            "company_id": e.tenant_id, "user": e.user, "action": e.action, "label": SECURITY_ACTIONS.get(e.action, e.action),
            "network": e.target if e.action.startswith("auth.") else "",
            "detail": {k: v for k, v in (e.detail or {}).items() if k in SAFE_DETAIL}}


# --------------------------------------------------------------------------- overview
@router.get("/overview")
def overview(days: int = 30, ctx: Ctx = Depends(platform_ctx)):
    days = max(7, min(days, 180))
    db, since, axis = ctx.db, _since(days), _days(days)
    llm.flush_usage()
    tenants = db.scalars(select(Tenant)).all()
    users = db.scalars(select(User)).all()
    deals = db.execute(select(Deal.status, Deal.created_at)).all()
    signins = db.execute(select(AuditLog.at).where(AuditLog.action == "auth.sign_in", AuditLog.at >= since)).all()
    failed = db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action.in_(["auth.sign_in_failed", "auth.locked_out"]),
                                                                          AuditLog.at >= since)) or 0
    usage = db.scalars(select(AiUsage).where(AiUsage.day >= axis[0])).all()

    series = {d: {"day": d, "sign_ins": 0, "new_companies": 0, "deals": 0, "ai_calls": 0, "ai_failures": 0} for d in axis}
    for (at,) in signins:
        d = _utc(at).date().isoformat()
        if d in series:
            series[d]["sign_ins"] += 1
    for t in tenants:
        d = _utc(t.created_at).date().isoformat() if t.created_at else ""
        if d in series:
            series[d]["new_companies"] += 1
    for st, at in deals:
        d = _utc(at).date().isoformat() if at else ""
        if d in series:
            series[d]["deals"] += 1
    for u in usage:
        if u.day in series:
            series[u.day]["ai_calls"] += u.calls
            series[u.day]["ai_failures"] += u.failures

    now = datetime.now(timezone.utc)
    seen = [_utc(u.last_seen_at) for u in users if u.last_seen_at]
    calls, fails = sum(u.calls for u in usage), sum(u.failures for u in usage)
    return {
        "days": days,
        "companies": {"total": len(tenants), "sellers": sum(1 for t in tenants if (t.kind or "vendor") == "vendor"),
                      "buyers": sum(1 for t in tenants if t.kind == "buyer"), "paused": sum(1 for t in tenants if t.suspended_at),
                      "new": sum(1 for t in tenants if t.created_at and _utc(t.created_at) >= since)},
        "people": {"total": len(users), "paused": sum(1 for u in users if not u.is_active),
                   "active_7d": sum(1 for s in seen if now - s <= timedelta(days=7)),
                   "active_30d": sum(1 for s in seen if now - s <= timedelta(days=30)),
                   "roles": dict(Counter(u.role for u in users))},
        "deals": {"total": len(deals), "new": sum(1 for _, at in deals if at and _utc(at) >= since),
                  "by_status": dict(Counter(st for st, _ in deals))},
        "ai": {"calls": calls, "failures": fails, "failure_pct": round(100 * fails / calls, 1) if calls else 0,
               "tokens": sum(u.tokens for u in usage), "avg_seconds": round(sum(u.ms for u in usage) / calls / 1000, 1) if calls else 0},
        "security": {"failed_sign_ins": failed, "sign_ins": len(signins)},
        "series": list(series.values()),
    }


# --------------------------------------------------------------------------- companies
@router.get("/companies")
def companies(ctx: Ctx = Depends(platform_ctx)):
    db, since = ctx.db, _since(30)
    llm.flush_usage()
    tenants = db.scalars(select(Tenant).order_by(Tenant.created_at.desc())).all()
    users = db.scalars(select(User)).all()
    by_t: dict[str, list[User]] = defaultdict(list)
    for u in users:
        by_t[u.tenant_id].append(u)
    deals_all = _count_by_tenant(db, Deal)
    deals_30 = _count_by_tenant(db, Deal, Deal.created_at >= since)
    lib = {name: _count_by_tenant(db, m) for name, m in (("capabilities", Capability), ("people", Employee), ("case_studies", CaseStudy),
                                                          ("accelerators", Accelerator), ("certifications", Certification), ("rates", RateCard))}
    ai = defaultdict(lambda: [0, 0])
    for u in db.scalars(select(AiUsage).where(AiUsage.day >= since.date().isoformat())):
        ai[u.tenant_id][0] += u.calls
        ai[u.tenant_id][1] += u.failures
    out = []
    for t in tenants:
        us = by_t.get(t.id, [])
        last = max((_utc(u.last_seen_at) for u in us if u.last_seen_at), default=None)
        out.append({
            "id": t.id, "name": t.name, "kind": t.kind or "vendor", "created_at": _utc(t.created_at).isoformat() if t.created_at else "",
            "paused": bool(t.suspended_at), "pause_reason": t.suspend_reason or "",
            "people": len(us), "people_paused": sum(1 for u in us if not u.is_active), "roles": dict(Counter(u.role for u in us)),
            "active_30d": sum(1 for u in us if u.last_seen_at and _utc(u.last_seen_at) >= since),
            "last_active": last.isoformat() if last else "",
            "deals": deals_all.get(t.id, 0), "deals_30d": deals_30.get(t.id, 0),
            "library": {k: v.get(t.id, 0) for k, v in lib.items()},
            "ai": {**_ai_mode(t), "calls_30d": ai[t.id][0], "failures_30d": ai[t.id][1]},
            "storage_bytes": _folder_bytes(t.id),
            "is_mine": t.id == ctx.tenant_id,
        })
    return out


@router.get("/companies/{tid}")
def company(tid: str, days: int = 30, ctx: Ctx = Depends(platform_ctx)):
    db = ctx.db
    t = db.get(Tenant, tid)
    if not t:
        raise HTTPException(404, "Company not found.")
    days = max(7, min(days, 180))
    since, axis = _since(days), _days(days)
    llm.flush_usage()
    row = next((c for c in companies(ctx) if c["id"] == tid), None)
    users = db.scalars(select(User).where(User.tenant_id == tid).order_by(User.created_at)).all()
    series = {d: {"day": d, "sign_ins": 0, "deals": 0, "ai_calls": 0, "ai_failures": 0} for d in axis}
    for (at,) in db.execute(select(AuditLog.at).where(AuditLog.tenant_id == tid, AuditLog.action == "auth.sign_in", AuditLog.at >= since)):
        d = _utc(at).date().isoformat()
        if d in series:
            series[d]["sign_ins"] += 1
    for (at,) in db.execute(select(Deal.created_at).where(Deal.tenant_id == tid, Deal.created_at >= since)):
        d = _utc(at).date().isoformat()
        if d in series:
            series[d]["deals"] += 1
    models: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for u in db.scalars(select(AiUsage).where(AiUsage.tenant_id == tid, AiUsage.day >= axis[0])):
        if u.day in series:
            series[u.day]["ai_calls"] += u.calls
            series[u.day]["ai_failures"] += u.failures
        m = models[(u.provider, u.model)]
        m[0], m[1], m[2], m[3] = m[0] + u.calls, m[1] + u.failures, m[2] + u.tokens, m[3] + u.ms
    events = db.scalars(select(AuditLog).where(AuditLog.tenant_id == tid, AuditLog.action.in_(list(SECURITY_ACTIONS)))
                        .order_by(AuditLog.at.desc()).limit(100)).all()
    return {
        **(row or {}),
        "people_list": [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "active": u.is_active,
                         "sso": "Google" if u.google_sub else "Microsoft" if u.ms_oid else "Password",
                         "last_active": _utc(u.last_seen_at).isoformat() if u.last_seen_at else "",
                         "added": _utc(u.created_at).isoformat() if u.created_at else "",
                         "platform_admin": ai_settings.is_platform_admin(u.email), "is_me": u.id == ctx.user.id} for u in users],
        "series": list(series.values()),
        "ai_models": [{"provider": p, "model": m, "calls": v[0], "failures": v[1], "tokens": v[2],
                       "avg_seconds": round(v[3] / v[0] / 1000, 1) if v[0] else 0} for (p, m), v in sorted(models.items(), key=lambda x: -x[1][0])],
        "events": [_event(e, {tid: t.name}) for e in events],
    }


# --------------------------------------------------------------------------- controls
def _record(ctx: Ctx, tid: str, action: str, target: str, **detail) -> None:
    ctx.db.add(AuditLog(tenant_id=tid, user=ctx.user.email, action=action, target=target, detail=detail))


@router.post("/companies/{tid}/pause")
def pause_company(tid: str, body: dict | None = None, ctx: Ctx = Depends(platform_ctx)):
    t = ctx.db.get(Tenant, tid)
    if not t:
        raise HTTPException(404, "Company not found.")
    if t.id == ctx.tenant_id:
        raise HTTPException(400, "You can't pause your own company: you would lock yourself out of this console.")
    reason = str((body or {}).get("reason") or "").strip()[:300]
    t.suspended_at, t.suspend_reason = datetime.now(timezone.utc), reason
    _record(ctx, tid, "platform.company_suspend", t.name, reason=reason)
    ctx.db.commit()
    return {"ok": True}


@router.post("/companies/{tid}/reactivate")
def reactivate_company(tid: str, ctx: Ctx = Depends(platform_ctx)):
    t = ctx.db.get(Tenant, tid)
    if not t:
        raise HTTPException(404, "Company not found.")
    t.suspended_at, t.suspend_reason = None, ""
    _record(ctx, tid, "platform.company_reactivate", t.name)
    ctx.db.commit()
    return {"ok": True}


def _user(ctx: Ctx, uid: str) -> User:
    u = ctx.db.get(User, uid)
    if not u:
        raise HTTPException(404, "Person not found.")
    return u


def _other_active_admins(ctx: Ctx, u: User) -> int:
    return ctx.db.scalar(select(func.count()).select_from(User).where(
        User.tenant_id == u.tenant_id, User.role == "admin", User.is_active.is_(True), User.id != u.id)) or 0


@router.post("/users/{uid}/pause")
def pause_user(uid: str, ctx: Ctx = Depends(platform_ctx)):
    u = _user(ctx, uid)
    if u.id == ctx.user.id:
        raise HTTPException(400, "You can't pause your own account.")
    if u.role == "admin" and u.is_active and not _other_active_admins(ctx, u):
        raise HTTPException(400, "This is the company's only active admin. Pause the whole company instead, or make someone else admin first.")
    u.is_active = False
    _record(ctx, u.tenant_id, "platform.user_suspend", u.email)
    ctx.db.commit()
    return {"ok": True}


@router.post("/users/{uid}/reactivate")
def reactivate_user(uid: str, ctx: Ctx = Depends(platform_ctx)):
    u = _user(ctx, uid)
    u.is_active = True
    _record(ctx, u.tenant_id, "platform.user_reactivate", u.email)
    ctx.db.commit()
    return {"ok": True}


@router.post("/users/{uid}/role")
def change_role(uid: str, body: dict, ctx: Ctx = Depends(platform_ctx)):
    u = _user(ctx, uid)
    role = str((body or {}).get("role") or "")
    if role not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(ROLES)}.")
    if u.role == "admin" and role != "admin" and u.is_active and not _other_active_admins(ctx, u):
        raise HTTPException(400, "Every company needs at least one active admin. Make someone else admin first.")
    if role != u.role:
        _record(ctx, u.tenant_id, "platform.user_role", u.email, before=u.role, after=role)
        u.role = role
        ctx.db.commit()
    return {"ok": True}


@router.post("/users/{uid}/signout")
def sign_out_everywhere(uid: str, ctx: Ctx = Depends(platform_ctx)):
    u = _user(ctx, uid)
    if u.id == ctx.user.id:
        raise HTTPException(400, "Use Sign out in your own menu instead.")
    u.tokens_after = datetime.now(timezone.utc).replace(microsecond=0)
    _record(ctx, u.tenant_id, "platform.user_signout", u.email)
    ctx.db.commit()
    return {"ok": True}


# --------------------------------------------------------------------------- AI
@router.get("/ai")
def ai_usage(days: int = 30, ctx: Ctx = Depends(platform_ctx)):
    days = max(7, min(days, 180))
    axis = _days(days)
    llm.flush_usage()
    db = ctx.db
    names = {t.id: t.name for t in db.scalars(select(Tenant))}
    rows = db.scalars(select(AiUsage).where(AiUsage.day >= axis[0])).all()
    series = {d: {"day": d, "calls": 0, "failures": 0, "tokens": 0} for d in axis}
    by_model: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    by_co: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for r in rows:
        if r.day in series:
            s = series[r.day]
            s["calls"], s["failures"], s["tokens"] = s["calls"] + r.calls, s["failures"] + r.failures, s["tokens"] + r.tokens
        for agg in (by_model[(r.provider, r.model)], by_co[r.tenant_id]):
            agg[0], agg[1], agg[2], agg[3] = agg[0] + r.calls, agg[1] + r.failures, agg[2] + r.tokens, agg[3] + r.ms

    def shape(v):
        return {"calls": v[0], "failures": v[1], "failure_pct": round(100 * v[1] / v[0], 1) if v[0] else 0, "tokens": v[2],
                "avg_seconds": round(v[3] / v[0] / 1000, 1) if v[0] else 0}

    with llm.use_profile(llm.server_profile()):
        server = llm.status(usage=True)
    companies_ai = []
    for t in db.scalars(select(Tenant)):
        m = _ai_mode(t)
        companies_ai.append({"id": t.id, "name": t.name, **m, **shape(by_co.get(t.id, [0, 0, 0, 0]))})
    return {
        "days": days, "series": list(series.values()),
        "models": sorted([{"provider": p, "model": m, **shape(v)} for (p, m), v in by_model.items()], key=lambda x: -x["calls"]),
        "companies": sorted(companies_ai, key=lambda x: -x["calls"]),
        "website_chat": shape(by_co.get("", [0, 0, 0, 0])),
        "server": {"provider": server.get("provider"), "model": server.get("model"), "paid": server.get("paid"), "rpm": server.get("rpm"),
                   "last_error": (server.get("last_error") or "")[:300], "disabled_reason": server.get("disabled_reason", ""),
                   "embeddings": server.get("embeddings")},
        "maahi_own_key": bool(settings.maahi_gemini_api_key),
        "note": "Calls are counted per running copy of the app and saved every minute. Tokens are as reported by each provider; "
                "the app doesn't know your prices, so cost isn't shown in money.",
    }


# --------------------------------------------------------------------------- system health
def _bytes(path) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


@router.get("/health")
def health(ctx: Ctx = Depends(platform_ctx)):
    from ..db import DB_STATE, engine
    from ..services import notify

    db = ctx.db
    now = datetime.now(timezone.utc)
    srcs = []
    for s in db.scalars(select(TenderSource).order_by(TenderSource.key)):
        if s.key.startswith("_"):
            continue
        last_ok = _utc(s.last_ok)
        srcs.append({"key": s.key, "last_run": _utc(s.last_run).isoformat() if s.last_run else "", "last_ok": last_ok.isoformat() if last_ok else "",
                     "fetched": s.fetched, "error": (s.error or "")[:300],
                     "stale": bool(not last_ok or now - last_ok > timedelta(hours=36))})
    processing = db.execute(select(Deal.updated_at).where(Deal.status == "processing")).all()
    stuck = sum(1 for (u,) in processing if u and now - _utc(u) > timedelta(minutes=30))
    failed_7d = db.scalar(select(func.count()).select_from(Deal).where(Deal.status == "failed", Deal.updated_at >= _since(7))) or 0
    url = str(engine.url)
    data_dir = UPLOAD_DIR.parent
    disk = {"uploads": sum(_folder_bytes(t) for (t,) in db.execute(select(Tenant.id))), "database": 0}
    if url.startswith("sqlite"):
        disk["database"] = _bytes(url.split("///", 1)[-1])
    try:
        import shutil
        du = shutil.disk_usage(data_dir)
        disk.update(free=du.free, total=du.total)
    except OSError:
        pass
    threads = {t.name for t in threading.enumerate()}
    with llm.use_profile(llm.server_profile()):
        ai = llm.status(usage=True)
    return {
        "checked_at": now.isoformat(), "started_at": STARTED.isoformat(), "uptime_hours": round((now - STARTED).total_seconds() / 3600, 1),
        "version": os.getenv("APP_VERSION", "") or os.getenv("GITHUB_SHA", "")[:7],
        "database": {"ok": DB_STATE.get("ok", True), "detail": DB_STATE.get("detail", ""),
                     "engine": "PostgreSQL" if url.startswith("postgres") else "SQLite"},
        "deals": {"processing": len(processing), "stuck_over_30_min": stuck, "failed_7d": failed_7d},
        "feeds": srcs, "tenders_open": db.scalar(select(func.count()).select_from(Tender).where(Tender.deadline >= now)) or 0,
        "awards_stored": db.scalar(select(func.count()).select_from(Award)) or 0,
        "disk": disk,
        "background": {"tender_refresh": any("tender" in n or "radar" in n for n in threads), "ai_usage_saver": "ai-usage-flush" in threads,
                       "deadline_emails": any("deadline" in n for n in threads)},
        "services": {"email": notify.enabled(), "google_sign_in": bool(settings.google_client_id),
                     "microsoft_sign_in": bool(settings.ms_client_id), "maahi_own_key": bool(settings.maahi_gemini_api_key),
                     "platform_admins": len(settings.platform_admins)},
        "ai": {"provider": ai.get("provider"), "model": ai.get("model"), "paid": ai.get("paid"), "rpm": ai.get("rpm"),
               "last_error": (ai.get("last_error") or "")[:300], "disabled_reason": ai.get("disabled_reason", "")},
        "recent_errors": errlog.recent(100),
        "note": "Recent errors are kept in memory by this running copy of the app and reset on restart. Azure's Log stream has the full log.",
    }


# --------------------------------------------------------------------------- security
@router.get("/security")
def security(days: int = 30, ctx: Ctx = Depends(platform_ctx)):
    days = max(1, min(days, 180))
    since = _since(days)
    db = ctx.db
    names = {t.id: t.name for t in db.scalars(select(Tenant))}
    rows = db.scalars(select(AuditLog).where(AuditLog.action.in_(list(SECURITY_ACTIONS)), AuditLog.at >= since)
                      .order_by(AuditLog.at.desc()).limit(2000)).all()
    counts = Counter(r.action for r in rows)
    bad = [r for r in rows if r.action in ("auth.sign_in_failed", "auth.locked_out")]
    nets = Counter(r.target for r in bad if r.target)
    accounts = Counter(r.user for r in bad)
    return {
        "days": days,
        "summary": {"sign_ins": counts["auth.sign_in"], "failed_sign_ins": counts["auth.sign_in_failed"], "lockouts": counts["auth.locked_out"],
                    "role_changes": counts["user.role_change"] + counts["platform.user_role"],
                    "exports": counts["company.export"], "deletions": counts["company.deleted"],
                    "platform_actions": sum(v for k, v in counts.items() if k.startswith("platform."))},
        "top_failing_networks": [{"network": k, "failures": v} for k, v in nets.most_common(8)],
        "top_failing_accounts": [{"account": k, "failures": v} for k, v in accounts.most_common(8)],
        "events": [_event(r, names) for r in rows if r.action != "auth.sign_in"][:300],
        "sign_ins": [_event(r, names) for r in rows if r.action == "auth.sign_in"][:100],
    }
