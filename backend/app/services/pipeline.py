"""Runs the 8-stage deal pipeline in the background, stage by stage, saving each stage's output as a
draft for human review. Re-running from a stage (after edits) refreshes everything downstream."""
from __future__ import annotations

import logging
from collections import Counter
import threading
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import OUTPUT_DIR
from ..db import SessionLocal
from ..models import (STAGES, Accelerator, CaseStudy, Capability, Certification, Deal, DealStage, Document, Employee, RateCard,
                      Requirement, Tenant)
from . import docgen, extraction, graph, learning, llm
from . import knowledge as K
from .masking import deal_masker
from .matching import CompanyKB, ai_mitigations, analyze_gaps, match_requirements
from .parsing import Block, ParsedDocument, parse_document
from .solution import ai_architecture, build_architecture, estimate, price

log = logging.getLogger("revenueforge.pipeline")
_locks: dict[str, threading.Lock] = {}

STAGE_LABEL = {"requirements": "Reading the RFP and extracting requirements", "matching": "Matching requirements to capabilities",
               "gaps": "Analysing gaps and risks", "architecture": "Drafting the solution architecture",
               "estimation": "Estimating effort and planning the team", "pricing": "Pricing scenarios and margin",
               "proposal": "Writing the proposal in your template", "handoff": "Preparing the delivery handoff"}


def load_kb(db: Session, tid: str) -> CompanyKB:
    t = db.get(Tenant, tid)
    kb = CompanyKB(t.name)
    kb.capabilities = [{"id": c.id, "name": c.name, "service_line": c.service_line, "description": c.description, "technologies": c.technologies or [],
                        "industries": c.industries or []} for c in db.scalars(select(Capability).where(Capability.tenant_id == tid))]
    kb.case_studies = [{"id": c.id, "title": c.title, "client": c.client, "industry": c.industry, "region": c.region, "year": c.year,
                        "summary": c.summary, "technologies": c.technologies or [], "outcomes": c.outcomes or []}
                       for c in db.scalars(select(CaseStudy).where(CaseStudy.tenant_id == tid))]
    kb.accelerators = [{"id": a.id, "name": a.name, "description": a.description, "technologies": a.technologies or [], "effort_saving_pct": a.effort_saving_pct}
                       for a in db.scalars(select(Accelerator).where(Accelerator.tenant_id == tid))]
    kb.certifications = [{"id": c.id, "name": c.name, "kind": c.kind, "issuer": c.issuer, "holders": c.holders, "valid_until": c.valid_until}
                         for c in db.scalars(select(Certification).where(Certification.tenant_id == tid))]
    kb.employees = [{"id": e.id, "code": e.code, "name": e.name, "role": e.role, "level": e.level, "years": e.years, "location": e.location,
                     "skills": e.skills or [], "certifications": e.certifications or [], "availability": e.availability}
                    for e in db.scalars(select(Employee).where(Employee.tenant_id == tid))]
    kb.rates = [{"role": r.role, "level": r.level, "location": r.location, "day_rate": r.day_rate, "day_cost": r.day_cost, "currency": r.currency}
                for r in db.scalars(select(RateCard).where(RateCard.tenant_id == tid))]
    # learning loop: capabilities cited in won deals
    won = db.scalars(select(Deal.id).where(Deal.tenant_id == tid, Deal.status == "won")).all()
    if won:
        for r in db.scalars(select(Requirement).where(Requirement.deal_id.in_(won))):
            for e in (r.match or {}).get("evidence", []):
                if e.get("type") == "Capability" and e.get("id"):
                    kb.won_capabilities[e["id"]] = kb.won_capabilities.get(e["id"], 0) + 1
    return kb


def _req_dicts(db: Session, deal_id: str) -> list[dict]:
    rows = db.scalars(select(Requirement).where(Requirement.deal_id == deal_id).order_by(Requirement.seq)).all()
    return [{"id": r.id, "seq": r.seq, "code": r.code, "source_ref": r.source_ref, "text": r.text, "category": r.category, "subcategory": r.subcategory,
             "priority": r.priority, "page": r.page, "section": r.section, "block_idx": r.block_idx, "class_confidence": r.class_confidence,
             "technologies": r.technologies or [], "match_status": r.match_status, "match_score": r.match_score, "match": r.match or {},
             "gap": r.gap or {}, "workstream": r.workstream, "complexity": r.complexity, "effort_days": r.effort_days,
             "response": r.response, "response_source": r.response_source, "classified_by": r.classified_by} for r in rows]


def _save_reqs(db: Session, deal_id: str, reqs: list[dict], fields: list[str]):
    rows = {r.id: r for r in db.scalars(select(Requirement).where(Requirement.deal_id == deal_id))}
    for d in reqs:
        row = rows.get(d["id"])
        if row:
            for f in fields:
                setattr(row, f, d.get(f))


def get_parsed(db: Session, doc: Document) -> ParsedDocument:
    p = doc.parsed or {}
    if p.get("blocks"):
        return ParsedDocument(doc.filename, p.get("pages", 1), [Block(**b) for b in p["blocks"]])
    data = Path(doc.path).read_bytes()
    parsed = parse_document(data, doc.filename)
    doc.parsed = {"pages": parsed.pages, "blocks": [b.to_dict() for b in parsed.blocks]}
    doc.pages = parsed.pages
    doc.status = "parsed"
    return parsed


def _stage(db: Session, deal: Deal, name: str) -> DealStage:
    st = db.scalar(select(DealStage).where(DealStage.deal_id == deal.id, DealStage.stage == name))
    if not st:
        st = DealStage(tenant_id=deal.tenant_id, deal_id=deal.id, stage=name, status="pending", data={})
        db.add(st)
        db.flush()
    return st


def _progress(db: Session, deal: Deal, stage: str, pct: int, msg: str):
    deal.progress = {"stage": stage, "pct": pct, "message": msg, "at": datetime.now(timezone.utc).isoformat()}
    db.commit()


def context(db: Session, deal: Deal) -> dict:
    tenant = db.get(Tenant, deal.tenant_id)
    stages = {s.stage: s for s in db.scalars(select(DealStage).where(DealStage.deal_id == deal.id))}
    mask = deal_masker(deal)
    reqs = _req_dicts(db, deal.id)
    kb = load_kb(db, deal.tenant_id)
    cited = []
    for r in reqs:
        for e in r.get("match", {}).get("evidence", []):
            if e["type"] == "Case study" and e["name"] not in cited:
                cited.append(e["name"])
    cases = sorted(kb.case_studies, key=lambda c: (c["title"] not in cited, cited.index(c["title"]) if c["title"] in cited else 99))
    return {
        "deal": {"id": deal.id, "name": mask(deal.name), "client_display": (deal.client_alias or "the Client") if deal.confidential else (deal.client_name or "the Client"),
                 "engagement_type": deal.engagement_type, "doc_type": deal.doc_type, "industry": deal.industry, "region": deal.region},
        "company": {"name": tenant.name, "about": tenant.about},
        "meta": mask(deal.meta or {}),
        "requirements": mask(reqs),
        "gaps": stages["gaps"].data if "gaps" in stages else {},
        "architecture": mask(stages["architecture"].data) if "architecture" in stages else {},
        "estimation": stages["estimation"].data if "estimation" in stages else {},
        "pricing": stages["pricing"].data if "pricing" in stages else {},
        "scenario": (stages["pricing"].data or {}).get("selected", "Target") if "pricing" in stages else "Target",
        "case_studies": cases[:4],
        "certifications": [c for c in kb.certifications if c.get("kind") in ("company", "partner")],
        "kb": kb,
    }


def _template_bytes(db: Session, tid: str) -> bytes | None:
    doc = db.scalar(select(Document).where(Document.tenant_id == tid, Document.kind == "template", Document.status == "imported")
                    .order_by(Document.created_at.desc()))
    if doc and Path(doc.path).exists():
        return Path(doc.path).read_bytes()
    return None


def run_stage(db: Session, deal: Deal, name: str) -> dict:
    tid = deal.tenant_id
    st = _stage(db, deal, name)
    t0 = time.time()
    st.status = "running"
    db.commit()
    mask = deal_masker(deal)
    tenant = db.get(Tenant, tid)

    def prog(msg: str):
        p = dict(deal.progress or {})
        p["message"] = msg
        deal.progress = p
        db.commit()

    if name == "requirements":
        doc = db.get(Document, deal.rfp_document_id)
        parsed = get_parsed(db, doc)
        guidance = learning.few_shot_block(learning.few_shot(db, tid, ["category", "subcategory", "priority", "removed", "added"],
                                                             [parsed.text[:4000]], k=10))
        reqs, meta, engine = extraction.extract_requirements(parsed, use_llm=True, mask_fn=mask, guidance=guidance, progress=prog)
        # The company's own trained classifier: confident predictions override generic judgement.
        preds = learning.classify_with_company_model(db, tid, reqs)
        overridden = 0
        if preds:
            for r, (cat, p) in zip(reqs, preds):
                if cat != r["category"] and (p >= 0.9 or (engine == "rules" and p >= 0.6)):
                    r["category"], r["subcategory"] = cat, K.best_subcategory(r["text"], r["section"], cat)
                    r["class_confidence"], r["classified_by"] = round(p, 2), "company_model"
                    overridden += 1
        db.execute(delete(Requirement).where(Requirement.deal_id == deal.id))
        for i, r in enumerate(reqs, start=1):
            db.add(Requirement(tenant_id=tid, deal_id=deal.id, seq=i, code=f"REQ-{i:03d}", source_ref=r.get("source_ref", ""), text=r["text"],
                               category=r["category"], subcategory=r["subcategory"], priority=r["priority"], page=r["page"], section=r["section"],
                               block_idx=r["block_idx"], class_confidence=r["class_confidence"], technologies=r.get("technologies", []),
                               original_category=r["category"], classified_by=r.get("classified_by", engine)))
        keep = dict(deal.meta or {})
        keep.update(meta)
        deal.meta = keep
        for f in ("doc_type", "engagement_type", "currency", "due_date", "industry", "region", "sector"):
            if not getattr(deal, f) and meta.get(f):
                setattr(deal, f, meta[f])
        if deal.name in ("", "Untitled deal") and meta.get("title"):
            deal.name = meta["title"]
        m2 = dict(deal.meta or {})
        m2["engine"] = engine
        deal.meta = m2
        st.data = {"engine": engine, "company_model_overrides": overridden, "learned_examples": guidance.count("\n- "),
                   "count": len(reqs), "by_category": dict(Counter(r["category"] for r in reqs)),
                   "by_priority": dict(Counter(r["priority"] for r in reqs)), "pages": parsed.pages,
                   "avg_confidence": round(sum(r["class_confidence"] for r in reqs) / max(1, len(reqs)), 3)}

    elif name == "matching":
        kb = load_kb(db, tid)
        reqs = mask(_req_dicts(db, deal.id))
        guidance = learning.few_shot_block(learning.few_shot(db, tid, ["match"], [r["text"] for r in reqs[:80]], k=8))
        match_requirements(reqs, kb, deal.engagement_type, deal.industry,
                           similarity=lambda q, d: learning.similarity_matrix(db, tid, q, d), guidance=guidance, progress=prog)
        _save_reqs(db, deal.id, reqs, ["match_status", "match_score", "match"])
        st.data = {"counts": dict(Counter(r["match_status"] for r in reqs)), "kb_size": {"capabilities": len(kb.capabilities), "people": len(kb.employees),
                   "case_studies": len(kb.case_studies), "certifications": len(kb.certifications)},
                   "engine": "ai" if any(r["match"].get("judged_by") == "ai" for r in reqs) else "rules",
                   "retrieval": reqs[0]["match"].get("retrieval", "tfidf") if reqs else "tfidf"}

    elif name == "gaps":
        kb = load_kb(db, tid)
        reqs = mask(_req_dicts(db, deal.id))
        ai_opts = ai_mitigations(reqs, kb, deal.engagement_type, progress=prog) if llm.is_enabled() else {}
        summary = analyze_gaps(reqs, kb, deal.engagement_type, ai_opts)
        summary["engine"] = "ai" if ai_opts else "rules"
        _save_reqs(db, deal.id, reqs, ["gap"])
        st.data = summary
        m = dict(deal.meta or {})
        m["top_missing"] = summary["top_missing"]
        deal.meta = m

    elif name == "architecture":
        kb = load_kb(db, tid)
        reqs = mask(_req_dicts(db, deal.id))
        meta_a = {**(deal.meta or {}), "engagement_type": deal.engagement_type, "industry": deal.industry, "region": deal.region}
        draft = build_architecture(reqs, kb, meta_a)
        draft["engine"] = "rules"
        if llm.is_enabled():
            prog("AI designing the solution architecture")
        st.data = ai_architecture(draft, reqs, kb, meta_a) or draft

    elif name == "estimation":
        kb = load_kb(db, tid)
        reqs = _req_dicts(db, deal.id)
        arch = _stage(db, deal, "architecture").data or {}
        overrides = (st.data or {}).get("overrides", {})
        est = estimate(reqs, kb, {**(deal.meta or {}), "engagement_type": deal.engagement_type, "region": deal.region}, arch,
                       {**overrides, "_calibration": learning.calibration(tenant)})
        est["overrides"] = overrides
        _save_reqs(db, deal.id, reqs, ["workstream", "complexity", "effort_days"])
        st.data = est

    elif name == "pricing":
        kb = load_kb(db, tid)
        est = _stage(db, deal, "estimation").data or {}
        prev = st.data or {}
        overrides = prev.get("overrides", {})
        pr = price(est, kb, {**(deal.meta or {}), "currency": deal.currency}, tenant.settings or {}, overrides)
        pr["overrides"] = overrides
        pr["selected"] = prev.get("selected", "Target")
        pr["insight"] = learning.pricing_insight(db, tid)
        st.data = pr

    elif name == "proposal":
        draft_responses(db, deal, prog)
        ctx = context(db, deal)
        data, info = docgen.build_proposal(ctx, _template_bytes(db, tid))
        out = OUTPUT_DIR / tid / deal.id
        out.mkdir(parents=True, exist_ok=True)
        path = out / "proposal.docx"
        path.write_bytes(data)
        rows = db.scalars(select(Requirement).where(Requirement.deal_id == deal.id)).all()
        src = Counter(r.response_source for r in rows if r.response)
        st.data = {**info, "file": str(path), "generated_at": datetime.now(timezone.utc).isoformat(),
                   "engine": "ai" if llm.is_enabled() else "rules", "response_sources": dict(src)}

    elif name == "handoff":
        ctx = context(db, deal)
        hd = docgen.build_handoff_data(ctx)
        data = docgen.build_handoff_docx(ctx, hd, _template_bytes(db, tid))
        out = OUTPUT_DIR / tid / deal.id
        out.mkdir(parents=True, exist_ok=True)
        path = out / "handoff.docx"
        path.write_bytes(data)
        st.data = {**hd, "file": str(path)}
        graph.add_deal_to_graph(db, deal)

    st.status = "draft"
    st.approved_by = ""
    st.approved_at = None
    st.duration_ms = int((time.time() - t0) * 1000)
    db.commit()
    return st.data


def draft_responses(db: Session, deal: Deal, prog=lambda m: None) -> None:
    """Fill each requirement's proposal response: answer library first, then AI, then rules. Human edits are never overwritten."""
    tid = deal.tenant_id
    rows = db.scalars(select(Requirement).where(Requirement.deal_id == deal.id).order_by(Requirement.seq)).all()
    mask = deal_masker(deal)
    client = (deal.client_alias or "the Client") if deal.confidential else (deal.client_name or "the Client")
    open_rows = [r for r in rows if r.response_source != "human" and r.category != "Commercial" and r.match_status != "confirm"]
    for r in rows:
        if r.response_source != "human" and (r.category == "Commercial" or r.match_status == "confirm"):
            r.response, r.response_source = "", ""
    if not open_rows:
        return
    prog("Reusing approved answers from your library")
    hits = learning.library_matches(db, tid, [{"id": r.id, "text": r.text} for r in open_rows])
    for r in open_rows:
        if r.id in hits:
            e, sim = hits[r.id]
            r.response, r.response_source, r.response_ref = e.answer.replace(learning.CLIENT_TOKEN, client), "library", e.id
            e.uses += 1
    remaining = [r for r in open_rows if r.id not in hits]
    reqs = {d["id"]: d for d in mask(_req_dicts(db, deal.id))}
    tenant = db.get(Tenant, tid)
    drafted = {}
    if llm.is_enabled() and remaining:
        guidance = learning.few_shot_block(learning.few_shot(db, tid, ["response"], [r.text for r in remaining[:60]], k=6),
                                           "How this company's reviewers rewrote earlier answers. Match their tone and level of detail")
        drafted = docgen.ai_responses([reqs[r.id] for r in remaining], {"name": tenant.name, "about": tenant.about}, client, guidance, prog)
    for r in remaining:
        if r.id in drafted:
            r.response, r.response_source = drafted[r.id], "ai"
        else:
            r.response, r.response_source = docgen.response_text(reqs[r.id], tenant.name), "rules"
        r.response_ref = ""
    db.commit()


def run_pipeline(deal_id: str, from_stage: str = "requirements", until: str | None = None, notify_user: str | None = None) -> None:
    lock = _locks.setdefault(deal_id, threading.Lock())
    if not lock.acquire(blocking=False):
        return
    db = SessionLocal()
    try:
        deal = db.get(Deal, deal_id)
        if not deal:
            return
        llm.set_tenant(deal.tenant_id)  # this thread's AI calls use the deal's company's AI settings
        start = STAGES.index(from_stage)
        end = STAGES.index(until) + 1 if until else len(STAGES)
        for s in STAGES[start:end]:
            st = _stage(db, deal, s)
            st.status = "pending"
        deal.status = "processing"
        timings = dict((deal.meta or {}).get("timings", {}))
        t_all = time.time()
        db.commit()
        for i, s in enumerate(STAGES[start:end]):
            pct = int((start + i) / len(STAGES) * 100)
            _progress(db, deal, s, pct, STAGE_LABEL[s])
            t = time.time()
            run_stage(db, deal, s)
            timings[s] = round(time.time() - t, 2)
        deal.status = "in_review"
        m = dict(deal.meta or {})
        m["timings"] = timings
        if start == 0:
            m["first_draft_seconds"] = round(time.time() - t_all, 1)
        deal.meta = m
        deal.progress = {"stage": "done", "pct": 100, "message": "Deal package ready for review"}
        db.commit()
        if notify_user:
            from . import notify
            notify.deal_finished(db, deal_id, notify_user, ok=True)
    except Exception as e:
        log.error("pipeline failed: %s\n%s", e, traceback.format_exc())
        db.rollback()
        deal = db.get(Deal, deal_id)
        if deal:
            deal.status = "failed"
            deal.progress = {"stage": (deal.progress or {}).get("stage", ""), "pct": (deal.progress or {}).get("pct", 0),
                             "message": f"Processing stopped: {e}"}
            for st in db.scalars(select(DealStage).where(DealStage.deal_id == deal_id, DealStage.status == "running")):
                st.status = "failed"
            db.commit()
            if notify_user:
                from . import notify
                notify.deal_finished(db, deal_id, notify_user, ok=False, error=str(e))
    finally:
        db.close()
        lock.release()


def start(deal_id: str, from_stage: str = "requirements", until: str | None = None, notify_user: str | None = None) -> None:
    """`notify_user`: the user to email when the deal is ready for review (or couldn't finish)."""
    threading.Thread(target=run_pipeline, args=(deal_id, from_stage, until, notify_user), daemon=True).start()
