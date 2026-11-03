"""Supplier network API: buyers' requests, shortlists and invitations; vendors' listing and invitation inbox."""
from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select

from ..config import UPLOAD_DIR
from ..models import Deal, Document, NetworkInvite, NetworkRequest, Tenant
from ..security import Ctx, current_ctx, require_roles
from ..services import extraction, network, pipeline
from ..services.tender_feeds import REGIONS

router = APIRouter(prefix="/api", tags=["network"])


def vendor_ctx(ctx: Ctx = Depends(current_ctx)) -> Ctx:
    if (ctx.tenant.kind or "vendor") == "buyer":
        raise HTTPException(403, "This is for supplier workspaces.")
    return ctx


def buyer_ctx(ctx: Ctx = Depends(current_ctx)) -> Ctx:
    if (ctx.tenant.kind or "vendor") != "buyer":
        raise HTTPException(403, "This is for buyer workspaces.")
    return ctx


def vendor_admin(ctx: Ctx = Depends(require_roles())) -> Ctx:
    return vendor_ctx(ctx)


def vendor_bidder(ctx: Ctx = Depends(require_roles("presales"))) -> Ctx:
    return vendor_ctx(ctx)


# =========================================================================== vendor side
@router.get("/network/profile")
def my_listing(ctx: Ctx = Depends(vendor_ctx)):
    return {"settings": network.network_settings(ctx.tenant), "regions": REGIONS,
            "preview": network.vendor_profile(ctx.db, ctx.tenant)}


@router.put("/network/profile")
def save_listing(body: dict, ctx: Ctx = Depends(vendor_admin)):
    n = network.network_settings(ctx.tenant)
    if "listed" in body:
        n["listed"] = bool(body["listed"])
    if isinstance(body.get("regions"), list):
        n["regions"] = [r for r in body["regions"] if r in REGIONS][:12]
    if isinstance(body.get("industries"), list):
        n["industries"] = [str(x).strip()[:60] for x in body["industries"] if str(x).strip()][:12]
    if "summary" in body:
        n["summary"] = str(body["summary"] or "")[:800]
    s = dict(ctx.tenant.settings or {})
    s["network"] = n
    ctx.tenant.settings = s
    ctx.audit("network.listing", "listed" if n["listed"] else "unlisted")
    ctx.db.commit()
    return my_listing(ctx)


def invite_out(db, inv: NetworkInvite, for_vendor: bool) -> dict:
    req = db.get(NetworkRequest, inv.request_id)
    other = db.get(Tenant, inv.buyer_tenant_id if for_vendor else inv.vendor_tenant_id)
    reqs = (req.requirements if req else []) or []
    return {"id": inv.id, "status": inv.status, "message": inv.message, "fit": inv.fit, "deal_id": inv.deal_id if for_vendor else "",
            "created_at": inv.created_at, "responded_at": inv.responded_at,
            "request": {"id": req.id if req else "", "title": req.title if req else "", "region": req.region if req else "",
                        "industry": req.industry if req else "", "due_date": req.due_date if req else "", "requirements": len(reqs),
                        "mandatory": sum(1 for r in reqs if r.get("priority") == "Mandatory")},
            ("buyer" if for_vendor else "vendor"): {"id": other.id if other else "", "name": other.name if other else "",
                                                    "demo": network.is_demo(other) if other else False}}


@router.get("/network/invitations")
def my_invitations(ctx: Ctx = Depends(vendor_ctx)):
    rows = ctx.db.scalars(select(NetworkInvite).where(NetworkInvite.vendor_tenant_id == ctx.tenant_id)
                          .order_by(NetworkInvite.created_at.desc())).all()
    return [invite_out(ctx.db, i, True) for i in rows]


def _vendor_invite(ctx: Ctx, inv_id: str) -> NetworkInvite:
    inv = ctx.db.get(NetworkInvite, inv_id)
    if not inv or inv.vendor_tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Invitation not found.")
    return inv


@router.post("/network/invitations/{inv_id}/accept")
def accept(inv_id: str, ctx: Ctx = Depends(vendor_bidder)):
    """Accepting starts a deal in this workspace from the buyer's RFP document."""
    inv = _vendor_invite(ctx, inv_id)
    if inv.status == "accepted" and inv.deal_id:
        return {"deal_id": inv.deal_id}
    req = ctx.db.get(NetworkRequest, inv.request_id)
    src = ctx.db.get(Document, req.document_id) if req else None
    if not req or not src or not Path(src.path).exists():
        raise HTTPException(410, "The buyer's document is no longer available.")
    buyer = ctx.db.get(Tenant, inv.buyer_tenant_id)
    doc = Document(tenant_id=ctx.tenant_id, kind="rfp", filename=src.filename, path="", size=src.size, uploaded_by=ctx.user.id)
    ctx.db.add(doc)
    ctx.db.flush()
    folder = UPLOAD_DIR / ctx.tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{doc.id}_{Path(src.path).name.split('_', 1)[-1]}"
    shutil.copyfile(src.path, dest)
    doc.path = str(dest)
    d = Deal(tenant_id=ctx.tenant_id, name=req.title[:200], client_name=buyer.name if buyer else "", client_alias="",
             confidential=False, due_date=req.due_date, industry=req.industry, owner_id=ctx.user.id, rfp_document_id=doc.id,
             status="processing", meta={"network_invite": inv.id}, progress={"stage": "requirements", "pct": 0, "message": "Queued"})
    ctx.db.add(d)
    ctx.db.flush()
    inv.status, inv.deal_id, inv.responded_at = "accepted", d.id, datetime.now(timezone.utc)
    ctx.audit("network.accept", inv.id, deal=d.id)
    ctx.db.commit()
    pipeline.start(d.id, notify_user=ctx.user.id)
    return {"deal_id": d.id}


@router.post("/network/invitations/{inv_id}/decline")
def decline(inv_id: str, ctx: Ctx = Depends(vendor_bidder)):
    inv = _vendor_invite(ctx, inv_id)
    if inv.status == "accepted":
        raise HTTPException(400, "You've already accepted this invitation and started a deal.")
    inv.status, inv.responded_at = "declined", datetime.now(timezone.utc)
    ctx.audit("network.decline", inv.id)
    ctx.db.commit()
    return {"ok": True}


# =========================================================================== buyer side
def _request(ctx: Ctx, rid: str) -> NetworkRequest:
    r = ctx.db.get(NetworkRequest, rid)
    if not r or r.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Request not found.")
    return r


def request_out(ctx: Ctx, r: NetworkRequest, full: bool = False) -> dict:
    reqs = r.requirements or []
    invites = ctx.db.scalars(select(NetworkInvite).where(NetworkInvite.request_id == r.id).order_by(NetworkInvite.created_at)).all()
    out = {"id": r.id, "title": r.title, "region": r.region, "industry": r.industry, "due_date": r.due_date, "created_at": r.created_at,
           "requirements": len(reqs), "mandatory": sum(1 for x in reqs if x.get("priority") == "Mandatory"),
           "invited": len(invites), "accepted": sum(1 for i in invites if i.status == "accepted"),
           "declined": sum(1 for i in invites if i.status == "declined")}
    if full:
        doc = ctx.db.get(Document, r.document_id)
        by_cat: dict[str, int] = {}
        for x in reqs:
            by_cat[x["category"]] = by_cat.get(x["category"], 0) + 1
        out.update({"by_category": by_cat, "filename": doc.filename if doc else "",
                    "sample": [{"text": x["text"][:240], "category": x["category"], "priority": x.get("priority", ""), "ref": x.get("source_ref", "")}
                               for x in reqs[:200]],
                    "invites": [invite_out(ctx.db, i, False) for i in invites]})
    return out


@router.get("/buyer/requests")
def list_requests(ctx: Ctx = Depends(buyer_ctx)):
    rows = ctx.db.scalars(select(NetworkRequest).where(NetworkRequest.tenant_id == ctx.tenant_id).order_by(NetworkRequest.created_at.desc())).all()
    return [request_out(ctx, r) for r in rows]


@router.post("/buyer/requests")
async def create_request(file: UploadFile = File(...), title: str = Form(""), region: str = Form(""), industry: str = Form(""),
                         due_date: str = Form(""), ctx: Ctx = Depends(buyer_ctx)):
    from .library import save_upload
    doc, _ = await save_upload(ctx, file, "buyer_rfp")
    parsed = pipeline.get_parsed(ctx.db, doc)
    reqs, meta, engine = extraction.extract_requirements(parsed, use_llm=False)  # the rules engine: fast, and no AI quota used
    keep = ["text", "category", "subcategory", "priority", "page", "section", "source_ref", "technologies"]
    r = NetworkRequest(tenant_id=ctx.tenant_id, title=(title.strip() or meta.get("title") or Path(file.filename or "Request").stem)[:300],
                       region=region if region in REGIONS else "", industry=(industry or meta.get("industry") or "")[:120],
                       due_date=(due_date or meta.get("due_date") or "")[:30], document_id=doc.id,
                       requirements=[{k: x.get(k) for k in keep} for x in reqs],
                       meta={"engine": engine, "pages": parsed.pages}, created_by=ctx.user.id)
    ctx.db.add(r)
    ctx.audit("buyer.request", r.title)
    ctx.db.commit()
    return request_out(ctx, r, full=True)


@router.get("/buyer/requests/{rid}")
def get_request(rid: str, ctx: Ctx = Depends(buyer_ctx)):
    return request_out(ctx, _request(ctx, rid), full=True)


@router.delete("/buyer/requests/{rid}")
def delete_request(rid: str, ctx: Ctx = Depends(buyer_ctx)):
    r = _request(ctx, rid)
    if ctx.db.scalar(select(NetworkInvite).where(NetworkInvite.request_id == r.id, NetworkInvite.status == "accepted")):
        raise HTTPException(400, "A supplier has accepted an invitation for this request, so it can't be deleted.")
    for i in ctx.db.scalars(select(NetworkInvite).where(NetworkInvite.request_id == r.id)):
        ctx.db.delete(i)
    ctx.db.delete(r)
    ctx.db.commit()
    return {"ok": True}


@router.get("/buyer/requests/{rid}/shortlist")
def get_shortlist(rid: str, ctx: Ctx = Depends(buyer_ctx)):
    r = _request(ctx, rid)
    rows = network.shortlist(ctx.db, r.requirements or [], r.region, r.industry, exclude_tenant=ctx.tenant_id)
    invited = {i.vendor_tenant_id: i.status for i in ctx.db.scalars(select(NetworkInvite).where(NetworkInvite.request_id == r.id))}
    for x in rows:
        x["invite_status"] = invited.get(x["vendor_id"], "")
    return {"vendors": rows, "listed": len(rows),
            "method": "Each listed supplier's own library is compared with your requirements the same way: no AI, no paid placement. "
                      "Mandatory requirements count; strong matches count fully and partial ones 60%."}


@router.get("/buyer/vendors/{vid}")
def vendor(vid: str, ctx: Ctx = Depends(buyer_ctx)):
    t = ctx.db.get(Tenant, vid)
    if not t or t.kind == "buyer" or not network.network_settings(t)["listed"]:
        raise HTTPException(404, "This supplier isn't listed in the network.")
    return network.vendor_profile(ctx.db, t)


@router.post("/buyer/requests/{rid}/invite")
def invite(rid: str, body: dict, ctx: Ctx = Depends(buyer_ctx)):
    r = _request(ctx, rid)
    ids = list(dict.fromkeys(str(x) for x in (body.get("vendor_ids") or [])))[:30]
    if not ids:
        raise HTTPException(400, "Choose at least one supplier.")
    fits = {x["vendor_id"]: x["score"] for x in network.shortlist(ctx.db, r.requirements or [], r.region, r.industry, ctx.tenant_id)}
    made = 0
    for vid in ids:
        if vid not in fits:
            continue  # not listed (or no longer listed)
        if ctx.db.scalar(select(NetworkInvite).where(NetworkInvite.request_id == r.id, NetworkInvite.vendor_tenant_id == vid)):
            continue
        ctx.db.add(NetworkInvite(request_id=r.id, buyer_tenant_id=ctx.tenant_id, vendor_tenant_id=vid, fit=fits[vid],
                                 message=str(body.get("message") or "")[:2000]))
        made += 1
    ctx.audit("buyer.invite", r.id, count=made)
    ctx.db.commit()
    return {"invited": made, "request": request_out(ctx, r, full=True)}
