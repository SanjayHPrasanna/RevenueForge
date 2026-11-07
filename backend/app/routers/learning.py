"""The AI learning page: what RevenueForge has learned from this company, and the answer library."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..models import AnswerEntry
from ..security import Ctx, current_ctx, require_roles
from ..services import learning

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("")
def get_learning(ctx: Ctx = Depends(current_ctx)):
    data = learning.stats(ctx.db, ctx.tenant_id)
    ctx.db.commit()
    return data


@router.post("/retrain")
def retrain(ctx: Ctx = Depends(require_roles("presales", "architect"))):
    meta = learning.train_classifier(ctx.db, ctx.tenant_id)
    ctx.audit("learning.retrain", "classifier", examples=meta.get("examples"))
    ctx.db.commit()
    return meta


def _entry(ctx: Ctx, eid: str) -> AnswerEntry:
    e = ctx.db.get(AnswerEntry, eid)
    if not e or e.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Answer not found.")
    return e


@router.post("/answers")
def add_answer(body: dict, ctx: Ctx = Depends(require_roles("presales"))):
    q, a = str(body.get("question") or "").strip()[:4000], str(body.get("answer") or "").strip()[:20000]
    if len(q) < 5 or len(a) < 5:
        raise HTTPException(400, "Write both the requirement and the approved answer.")
    e = AnswerEntry(tenant_id=ctx.tenant_id, question=q, answer=a, category=str(body.get("category") or "")[:60], origin="human",
                    approved_by=ctx.user.name, source_label="Added manually")
    ctx.db.add(e)
    ctx.db.commit()
    return {"id": e.id}


@router.put("/answers/{eid}")
def edit_answer(eid: str, body: dict, ctx: Ctx = Depends(require_roles("presales"))):
    e = _entry(ctx, eid)
    for f in ("answer", "question"):
        if f in body and len(str(body[f] or "").strip()) < 5:
            raise HTTPException(400, f"The {f} needs at least a few words.")
    if "answer" in body:
        e.answer, e.origin, e.approved_by = str(body["answer"]).strip()[:20000], "human", ctx.user.name
    if "question" in body:
        e.question, e.embedding = str(body["question"]).strip()[:4000], None
    ctx.db.commit()
    return {"ok": True}


@router.delete("/answers/{eid}")
def delete_answer(eid: str, ctx: Ctx = Depends(require_roles("presales"))):
    ctx.db.delete(_entry(ctx, eid))
    ctx.db.commit()
    return {"ok": True}
