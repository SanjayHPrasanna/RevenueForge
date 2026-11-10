"""A company's right to its data: download everything, or delete everything. Company admins only.

Export: one zip with the company profile, people with access, the knowledge library, every deal (requirements, stage
outputs, comments), the AI answer library, tender fits, network requests and invitations, the audit log, and the original
uploaded and generated files. Secrets (password hashes, AI keys, sign-in ids) are never included.

Delete: permanent. Every row that belongs to the company and every file in its folders is removed. One line is kept in the
platform log (no names or emails) so the deletion itself can be shown to have happened.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import delete, or_, select
from starlette.background import BackgroundTask

from ..config import OUTPUT_DIR, UPLOAD_DIR
from ..models import (Accelerator, AnswerEntry, AuditLog, CaseStudy, Capability, Certification, Deal, DealStage, Document,
                      EmbeddingCache, Employee, GraphEdge, GraphNode, LearningExample, ModelState, NetworkInvite, NetworkRequest,
                      RateCard, Requirement, RequirementComment, StageComment, Tenant, TenderFit, User)
from ..security import Ctx, require_roles, verify_password

router = APIRouter(prefix="/api/company", tags=["company-data"])

# every table with a tenant_id column, children before parents
OWNED = [StageComment, RequirementComment, Requirement, DealStage, Deal, Capability, Employee, Certification, CaseStudy, Accelerator, RateCard,
         GraphEdge, GraphNode, LearningExample, AnswerEntry, EmbeddingCache, ModelState, TenderFit, Document, AuditLog, NetworkRequest]
SECRET_COLS = {"password_hash", "google_sub", "ms_oid", "embedding", "vector", "blob", "state"}


def _rows(db, M, where) -> list[dict]:
    out = []
    for r in db.scalars(select(M).where(where)):
        out.append({c.name: getattr(r, c.name) for c in M.__table__.columns if c.name not in SECRET_COLS})
    return out


def _clean_settings(s: dict) -> dict:
    s = json.loads(json.dumps(s or {}, default=str))
    ai = s.get("ai")
    if isinstance(ai, dict):  # the company's AI key stays secret even in its own export
        for k in list(ai):
            if "key" in k.lower():
                ai[k] = "(hidden)"
    return s


@router.get("/export")
def export(ctx: Ctx = Depends(require_roles())):
    t = ctx.tenant
    tid = t.id
    tmp = Path(tempfile.mkdtemp(prefix="rf-export-"))
    zpath = tmp / "export.zip"
    dump = lambda o: json.dumps(o, indent=2, default=str, ensure_ascii=False)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("README.txt", (
            f"Data export for {t.name}, made {datetime.now(timezone.utc).isoformat()} by {ctx.user.email}.\n\n"
            "company.json      company profile and settings (AI keys hidden)\n"
            "users.json        people with access (no passwords)\n"
            "library/          capabilities, people & skills, certifications, rate card, case studies, accelerators\n"
            "deals/            one folder per deal: the deal, its requirements, stage outputs and comments\n"
            "answers.json      the reusable answer library; learning.json: corrections the app learned from\n"
            "radar.json        your saved/dismissed tenders and their fit scores\n"
            "network.json      supplier-network requests and invitations involving your company\n"
            "audit_log.json    who did what, when\n"
            "files/uploads/    every file uploaded; files/outputs/: every document the app generated\n"))
        z.writestr("company.json", dump({c.name: getattr(t, c.name) for c in Tenant.__table__.columns if c.name != "settings"}
                                        | {"settings": _clean_settings(t.settings)}))
        z.writestr("users.json", dump(_rows(ctx.db, User, User.tenant_id == tid)))
        for name, M in (("capabilities", Capability), ("skills", Employee), ("certifications", Certification), ("rates", RateCard),
                        ("case_studies", CaseStudy), ("accelerators", Accelerator)):
            z.writestr(f"library/{name}.json", dump(_rows(ctx.db, M, M.tenant_id == tid)))
        for d in ctx.db.scalars(select(Deal).where(Deal.tenant_id == tid)):
            base = f"deals/{d.id}"
            z.writestr(f"{base}/deal.json", dump({c.name: getattr(d, c.name) for c in Deal.__table__.columns}))
            z.writestr(f"{base}/requirements.json", dump(_rows(ctx.db, Requirement, Requirement.deal_id == d.id)))
            z.writestr(f"{base}/stages.json", dump(_rows(ctx.db, DealStage, DealStage.deal_id == d.id)))
            z.writestr(f"{base}/comments.json", dump(_rows(ctx.db, RequirementComment, RequirementComment.deal_id == d.id)))
            z.writestr(f"{base}/review_notes.json", dump(_rows(ctx.db, StageComment, StageComment.deal_id == d.id)))
        z.writestr("answers.json", dump(_rows(ctx.db, AnswerEntry, AnswerEntry.tenant_id == tid)))
        z.writestr("learning.json", dump(_rows(ctx.db, LearningExample, LearningExample.tenant_id == tid)))
        z.writestr("radar.json", dump(_rows(ctx.db, TenderFit, TenderFit.tenant_id == tid)))
        z.writestr("network.json", dump({
            "requests": _rows(ctx.db, NetworkRequest, NetworkRequest.tenant_id == tid),
            "invitations": _rows(ctx.db, NetworkInvite, or_(NetworkInvite.buyer_tenant_id == tid, NetworkInvite.vendor_tenant_id == tid))}))
        z.writestr("documents.json", dump(_rows(ctx.db, Document, Document.tenant_id == tid)))
        z.writestr("audit_log.json", dump(_rows(ctx.db, AuditLog, AuditLog.tenant_id == tid)))
        for label, root in (("uploads", UPLOAD_DIR / tid), ("outputs", OUTPUT_DIR / tid)):
            if root.is_dir():
                for f in root.rglob("*"):
                    if f.is_file() and not f.is_symlink():
                        z.write(f, f"files/{label}/{f.relative_to(root).as_posix()}")
    ctx.audit("company.export", tid)
    ctx.db.commit()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    safe = "".join(ch for ch in t.name if ch.isalnum() or ch in " -_").strip()[:60] or "company"
    return FileResponse(zpath, media_type="application/zip", filename=f"{safe} - RevenueForge export {stamp}.zip",
                        background=BackgroundTask(shutil.rmtree, tmp, ignore_errors=True))


@router.post("/delete")
def delete_company(body: dict, ctx: Ctx = Depends(require_roles())):
    """Permanently delete the company. The admin types the company name, and their password unless they sign in with Google/Microsoft."""
    if not isinstance(body, dict):
        raise HTTPException(400, "Send the confirmation.")
    t = ctx.tenant
    if str(body.get("confirm_name") or "").strip() != t.name.strip():
        raise HTTPException(400, "Type the company name exactly as shown to confirm.")
    sso = bool(ctx.user.google_sub or ctx.user.ms_oid)
    pw = str(body.get("password") or "")
    if (pw or not sso) and not verify_password(pw, ctx.user.password_hash):
        raise HTTPException(403, "That password isn't right.")
    if ctx.db.scalar(select(Deal.id).where(Deal.tenant_id == t.id, Deal.status == "processing").limit(1)):
        raise HTTPException(409, "A deal is still being processed. Wait until it finishes, then delete.")
    tid, counts = t.id, {}
    db = ctx.db
    for M in OWNED:
        counts[M.__tablename__] = db.execute(delete(M).where(M.tenant_id == tid)).rowcount or 0
    counts["network_invites"] = db.execute(delete(NetworkInvite).where(
        or_(NetworkInvite.buyer_tenant_id == tid, NetworkInvite.vendor_tenant_id == tid))).rowcount or 0
    counts["users"] = db.execute(delete(User).where(User.tenant_id == tid)).rowcount or 0
    db.execute(delete(Tenant).where(Tenant.id == tid))
    # the only trace kept: that a company was deleted, when, and how much (no names, no emails)
    db.add(AuditLog(tenant_id="", user="", action="company.deleted", target=tid,
                    detail={"kind": t.kind, "rows": sum(counts.values())}))
    db.commit()
    for root in (UPLOAD_DIR / tid, OUTPUT_DIR / tid):
        shutil.rmtree(root, ignore_errors=True)
    return {"deleted": True, "rows": counts}
