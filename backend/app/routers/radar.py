"""Opportunity radar: public tenders from open-data sources, scored against the signed-in company's own library."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func, or_, select

from ..config import UPLOAD_DIR
from ..models import Deal, Document, Tender, TenderFit, TenderSource
from ..security import Ctx, current_ctx, require_roles
from ..services import pipeline, radar, tender_feeds

router = APIRouter(prefix="/api/radar", tags=["radar"])


def _aware(d: datetime | None) -> datetime | None:
    return d.replace(tzinfo=timezone.utc) if d and d.tzinfo is None else d


def tender_out(t: Tender, f: TenderFit | None, full: bool = False) -> dict:
    d = (f.detail if f else {}) or {}
    out = {
        "id": t.id, "source": t.source, "source_name": tender_feeds.SOURCES.get(t.source, {}).get("name", t.source),
        "licence": tender_feeds.SOURCES.get(t.source, {}).get("licence", ""), "licence_url": tender_feeds.SOURCES.get(t.source, {}).get("licence_url", ""),
        "attribution": tender_feeds.SOURCES.get(t.source, {}).get("attribution", ""),
        "title": t.title, "buyer": t.buyer, "country": t.country, "region": t.region, "notice_type": t.notice_type,
        "value": t.value, "currency": t.currency, "published": _aware(t.published), "deadline": _aware(t.deadline), "url": t.url,
        "language": t.language, "categories": t.categories or [],
        "score": f.score if f else None, "band": d.get("band"), "status": f.status if f else "new", "deal_id": f.deal_id if f else "",
        "top_match": (d.get("matches") or [{}])[0].get("name", ""), "missing_standards": d.get("missing_standards", []),
    }
    if full:
        out.update({"description": t.description, "fit": {k: v for k, v in d.items() if k != "sig"}})
    else:
        out["summary"] = (t.description or "")[:260]
    return out


@router.get("/sources")
def sources(ctx: Ctx = Depends(current_ctx)):
    rows = {s.key: s for s in ctx.db.scalars(select(TenderSource))}
    counts = dict(ctx.db.execute(select(Tender.source, func.count()).group_by(Tender.source)).all())
    out = []
    for key, meta in tender_feeds.SOURCES.items():
        s = rows.get(key)
        on = key in tender_feeds.enabled_sources()
        out.append({"key": key, **meta, "enabled": on, "live": counts.get(key, 0),
                    "last_ok": _aware(s.last_ok) if s else None, "last_run": _aware(s.last_run) if s else None,
                    "error": (s.error if s else "") if on else ("Add a free SAM.gov API key (SAM_API_KEY) to include US federal opportunities."
                                                                if meta.get("needs_key") else "")})
    from ..models import Award
    from ..services import award_feeds
    acount = dict(ctx.db.execute(select(Award.source, func.count()).group_by(Award.source)).all())
    awards = []
    for key, meta in award_feeds.AWARD_SOURCES.items():
        s = rows.get(key)
        on = key in award_feeds.enabled()
        awards.append({"key": key, "name": meta["name"], "enabled": on, "stored": acount.get(meta["tender_source"], 0),
                       "history_from": (s.cursor if s else "") or None, "last_ok": _aware(s.last_ok) if s else None,
                       "error": (s.error if s else "") if on else ""})
    return {"sources": out, "awards": awards, "not_covered": tender_feeds.NOT_COVERED, "refresh": tender_feeds.status(),
            "total": sum(counts.values()), "regions": tender_feeds.REGIONS + ["Other"]}


@router.post("/refresh")
def refresh(ctx: Ctx = Depends(require_roles())):
    # The notices are shared by every company, so one company can't make the server re-read the sources every minute.
    from ..services import ai_settings
    last = ctx.db.scalar(select(func.max(TenderSource.last_run)))
    if last and not ai_settings.is_platform_admin(ctx.user.email):
        last = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        wait = 15 - (datetime.now(timezone.utc) - last).total_seconds() / 60
        if wait > 0:
            raise HTTPException(429, f"The sources were read {15 - int(wait)} minutes ago. Try again in {int(wait) + 1} minutes.")
    started = tender_feeds.refresh_in_background()
    return {"started": started, "message": "Reading the tender sources. This takes a few minutes." if started else "A refresh is already running."}


@router.get("")
def list_tenders(q: str = "", region: str = "", source: str = "", status: str = "", min_score: int = 0, due_days: int = 0,
                 sort: str = "score", limit: int = 50, offset: int = 0, ctx: Ctx = Depends(current_ctx)):
    from ..services.pipeline import load_kb
    radar.ensure_scored(ctx.db, ctx.tenant_id, load_kb)
    now = datetime.now(timezone.utc)
    stmt = (select(Tender, TenderFit).join(TenderFit, (TenderFit.tender_id == Tender.id) & (TenderFit.tenant_id == ctx.tenant_id))
            .where(or_(Tender.deadline.is_(None), Tender.deadline >= now)))
    if q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Tender.title.ilike(like), Tender.buyer.ilike(like), Tender.description.ilike(like), Tender.country.ilike(like)))
    if region:
        stmt = stmt.where(Tender.region == region)
    if source:
        stmt = stmt.where(Tender.source == source)
    if status == "active":
        stmt = stmt.where(TenderFit.status != "dismissed")
    elif status:
        stmt = stmt.where(TenderFit.status == status)
    if min_score:
        stmt = stmt.where(TenderFit.score >= min_score)
    if due_days:
        stmt = stmt.where(Tender.deadline.is_not(None), Tender.deadline <= now + timedelta(days=due_days))
    total = ctx.db.scalar(select(func.count()).select_from(stmt.subquery()))
    order = {"deadline": [Tender.deadline.asc().nulls_last()], "value": [Tender.value.desc().nulls_last()],
             "newest": [Tender.published.desc().nulls_last()]}.get(sort, [TenderFit.score.desc(), Tender.deadline.asc().nulls_last()])
    rows = ctx.db.execute(stmt.order_by(*order).limit(min(200, max(1, limit))).offset(max(0, offset))).all()
    bands = dict(ctx.db.execute(select(TenderFit.score >= 60, func.count()).join(Tender, Tender.id == TenderFit.tender_id)
                                .where(TenderFit.tenant_id == ctx.tenant_id, or_(Tender.deadline.is_(None), Tender.deadline >= now),
                                       TenderFit.status != "dismissed").group_by(TenderFit.score >= 60)).all())
    return {"total": total, "items": [tender_out(t, f) for t, f in rows], "strong": bands.get(True, 0),
            "live": sum(bands.values()), "scoring": radar.progress(ctx.tenant_id)}


@router.get("/{tender_id}")
def get_tender(tender_id: str, ctx: Ctx = Depends(current_ctx)):
    t = ctx.db.get(Tender, tender_id)
    if not t:
        raise HTTPException(404, "This tender is no longer listed.")
    f = ctx.db.scalar(select(TenderFit).where(TenderFit.tenant_id == ctx.tenant_id, TenderFit.tender_id == t.id))
    return tender_out(t, f, full=True)


@router.patch("/{tender_id}")
def set_status(tender_id: str, body: dict, ctx: Ctx = Depends(require_roles("presales", "architect", "finance", "delivery"))):
    st = body.get("status")
    if st not in ("new", "saved", "dismissed"):
        raise HTTPException(400, "Status must be new, saved or dismissed.")
    f = ctx.db.scalar(select(TenderFit).where(TenderFit.tenant_id == ctx.tenant_id, TenderFit.tender_id == tender_id))
    if not f:
        raise HTTPException(404, "This tender is no longer listed.")
    if f.status == "deal" and st != "deal":
        raise HTTPException(400, "A deal was already started from this tender.")
    f.status = st
    ctx.audit(f"radar.{st}", tender_id)
    ctx.db.commit()
    return {"ok": True, "status": st}


def _notice_text(t: Tender) -> str:
    cats = "; ".join(f"{c.get('code', '')} {c.get('label', '')}".strip() for c in t.categories or [])
    lines = [t.title, "", f"Buyer: {t.buyer}", f"Country: {t.country}", f"Notice: {t.notice_type}",
             f"Deadline: {t.deadline.strftime('%d %B %Y') if t.deadline else 'not stated'}",
             f"Estimated value: {t.currency} {t.value:,.0f}" if t.value else "Estimated value: not stated",
             f"Categories: {cats}", f"Source: {t.url}", "", "Scope of work (from the published notice)", "",
             t.description or "(The notice gives no description.)"]
    return "\n".join(lines)


@router.post("/{tender_id}/deal")
async def start_deal(tender_id: str, file: UploadFile | None = File(None), use_notice: bool = Form(False),
                     ctx: Ctx = Depends(require_roles("presales"))):
    """Start a deal from a tender: with the tender documents the user downloaded, or from the notice text alone."""
    from .library import save_upload
    t = ctx.db.get(Tender, tender_id)
    if not t:
        raise HTTPException(404, "This tender is no longer listed.")
    if file is not None and file.filename:
        doc, _ = await save_upload(ctx, file, "rfp")
    elif use_notice:
        data = _notice_text(t).encode("utf-8")
        doc = Document(tenant_id=ctx.tenant_id, kind="rfp", filename=f"{re.sub(r'[^A-Za-z0-9 -]+', '', t.title)[:80] or 'tender'} - notice.txt",
                       path="", size=len(data), uploaded_by=ctx.user.id)
        ctx.db.add(doc)
        ctx.db.flush()
        folder = UPLOAD_DIR / ctx.tenant_id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{doc.id}_notice.txt"
        path.write_bytes(data)
        doc.path = str(path)
    else:
        raise HTTPException(400, "Upload the tender documents, or choose to start from the notice summary.")
    d = Deal(tenant_id=ctx.tenant_id, name=t.title[:200], client_name=t.buyer[:200], client_alias="", confidential=False,
             region=t.country[:80], due_date=t.deadline.strftime("%d %B %Y") if t.deadline else "", currency=t.currency or "",
             owner_id=ctx.user.id, rfp_document_id=doc.id, status="processing",
             meta={"source_tender": {"id": t.id, "source": t.source, "url": t.url, "from_notice_only": file is None or not file.filename}},
             progress={"stage": "requirements", "pct": 0, "message": "Queued"})
    ctx.db.add(d)
    ctx.db.flush()
    f = ctx.db.scalar(select(TenderFit).where(TenderFit.tenant_id == ctx.tenant_id, TenderFit.tender_id == t.id))
    if f:
        f.status, f.deal_id = "deal", d.id
    ctx.audit("deal.create", d.name, tender=t.id)
    ctx.db.commit()
    pipeline.start(d.id, notify_user=ctx.user.id)
    return {"deal_id": d.id}
