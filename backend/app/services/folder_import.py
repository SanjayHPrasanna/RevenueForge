"""Import a whole folder of company files at once.

The browser sends every file in the folder the pre-sales person picked. Each file is saved straight
away, then a background thread works through them one by one: read it, work out what it is (skills
matrix, rate card, case study, proposal template ...) and prepare the same preview a single upload
would get. The person then reviews one screen, fixes any type that was guessed wrong, and imports
everything in one go.

Type detection is deliberately rule-based (file name + column headers + wording), so it is instant,
free and never sends a file to the AI just to sort it. Turning documents into records still uses the
same extraction as a single upload."""
from __future__ import annotations

import io
import logging
import queue
import re
import threading
from pathlib import Path

from sqlalchemy import select

from ..db import SessionLocal
from ..models import Document
from . import llm
from .onboarding import KINDS, REQUIRED, analyze, llm_records, suggest_mapping, _header_row, _wide_skill_columns
from .parsing import ParsedDocument, parse_document

log = logging.getLogger(__name__)

TYPES = list(KINDS) + ["template"]

NAME_HINTS: dict[str, str] = {
    "skills": r"skill|matrix|resource|employee|staff|people|talent|bench|competenc|roster|headcount",
    "rates": r"rate.?card|rates|pricing|price|tariff|billing|cost.?sheet|commercial",
    "certifications": r"cert|iso|cmmi|accredit|partner.?(tier|status|level)|compliance",
    "case_studies": r"case.?stud|success.?stor|reference|customer.?stor|client.?stor|project.?(list|history|portfolio)",
    "accelerators": r"accelerat|\bip\b|framework|reusable|asset|toolkit",
    "capabilities": r"capabilit|service|offering|portfolio|solution|company.?(profile|overview)|brochure|corporate",
    "template": r"template|proposal.?format|boilerplate",
}

# how much each mapped column says "this table is that kind"
DISTINCT: dict[str, dict[str, float]] = {
    "skills": {"skills": 3, "skill": 2, "proficiency": 2, "years": 2, "code": 1.5, "availability": 1.5, "secondary_skills": 2, "role": 1},
    "rates": {"day_rate": 4, "day_cost": 3, "currency": 1, "role": 1, "level": 0.5, "location": 0.5},
    "certifications": {"issuer": 3, "valid_until": 3, "holders": 2, "kind": 0.5, "name": 0.5},
    "case_studies": {"client": 3, "outcomes": 3, "summary": 1, "year": 1, "region": 0.5, "industry": 0.5, "title": 1},
    "capabilities": {"service_line": 2.5, "industries": 2, "maturity": 2, "technologies": 1, "description": 1, "name": 0.5},
    "accelerators": {"effort_saving_pct": 4, "description": 0.5, "technologies": 0.5, "name": 0.5},
}

HEADER_WORDS = {
    "capabilities": r"capabilit|service line|offering", "skills": r"skill|proficien|employee", "certifications": r"certif|accredit|expiry",
    "rates": r"\brate\b|day rate|hourly|cost", "case_studies": r"case stud|client|outcome", "accelerators": r"accelerat|effort sav",
}

RFP_RE = re.compile(r"request\s+for\s+(proposal|quotation|information)|\bRF[PQI]\b|the\s+bidder\s+(shall|must)|tender\s+(document|no)", re.I)
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}|\[\s*insert[^\]]{2,80}\]", re.I)
CASE_RE = re.compile(r"\b(the\s+client|challenge|the\s+solution|outcomes?|results?|business\s+impact|we\s+delivered)\b", re.I)
CERT_RE = re.compile(r"\b(iso\s?\d{4,5}|cmmi|soc\s?2|pci[\s-]?dss|certified|certification)\b", re.I)
ACCEL_RE = re.compile(r"\b(accelerator|reusable|framework|pre-?built|connector|toolkit)\b", re.I)


def _name_scores(path: str) -> dict[str, float]:
    stem = re.sub(r"[_\-.]+", " ", Path(path).stem.lower())
    folder = " ".join(Path(path).parts[:-1]).lower()
    out: dict[str, float] = {}
    for k, rx in NAME_HINTS.items():
        if re.search(rx, stem):
            out[k] = out.get(k, 0) + 5
        elif folder and re.search(rx, folder):
            out[k] = out.get(k, 0) + 2
    return out


def _table_scores(rows: list[list[str]]) -> dict[str, float]:
    h = _header_row(rows)
    header = [str(c).strip() for c in rows[h]]
    data = [r for r in rows[h + 1:] if any(str(c).strip() for c in r)]
    out: dict[str, float] = {}
    for k in KINDS:
        m = suggest_mapping(k, header)
        s = sum(DISTINCT[k].get(f, 0.3) for f in m)
        if all(f in m for f in REQUIRED[k]):
            s += 1
        if k == "skills" and _wide_skill_columns(k, header, data, m):
            s += 5
        if k == "skills" and not any(f in m for f in ("role", "code", "level", "years")):
            s -= 5  # a skills matrix is about people; without a role/ID/grade column it isn't one
        if k == "rates" and "day_rate" not in m:
            s -= 4
        if any(re.search(HEADER_WORDS[k], h, re.I) for h in header):
            s += 3
        out[k] = s
    return out


def classify(path: str, data: bytes, parsed: ParsedDocument) -> tuple[str | None, str, str]:
    """Returns (type or None, confidence high|medium|low, a short reason a person can read)."""
    ext = Path(path).suffix.lower()
    text = parsed.text[:40000]
    names = _name_scores(path)

    if ext == ".docx":
        if PLACEHOLDER_RE.search(text) or names.get("template", 0) >= 5:
            return "template", "high" if PLACEHOLDER_RE.search(text) else "medium", "Word file with fill-in placeholders" if PLACEHOLDER_RE.search(text) else "Named like a proposal template"
    if RFP_RE.search(text[:6000]) and not names:
        return None, "low", "Looks like a client RFP. Add it as a deal instead of to the library."

    scores: dict[str, float] = {k: names.get(k, 0) for k in KINDS}
    why = "from the file name" if names else ""
    if parsed.tables:
        rows = max(parsed.tables, key=len)
        for k, v in _table_scores(rows).items():
            scores[k] += v
        why = "from its columns" + (" and file name" if names else "")
    else:
        n_case, n_cert, n_acc = len(CASE_RE.findall(text)), len(CERT_RE.findall(text)), len(ACCEL_RE.findall(text))
        scores["case_studies"] += min(n_case, 8) * 0.8
        scores["certifications"] += min(n_cert, 8) * 0.7
        scores["accelerators"] += min(n_acc, 8) * 0.5
        scores["capabilities"] += 2  # decks and brochures are usually about capabilities
        for k in ("skills", "rates"):
            scores[k] -= 3  # these need a spreadsheet
        why = "from its wording" + (" and file name" if names else "")

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, top), (_, second) = ranked[0], ranked[1]
    if top < 2.5:
        return None, "low", "Couldn't tell what this file is. Pick a type or skip it."
    gap = top - second
    conf = "high" if top >= 7 and gap >= 3 else "medium" if gap >= 1.5 else "low"
    return best, conf, f"{KINDS[best]}, {why}".strip(", ")


def template_analysis(data: bytes) -> dict:
    from docx import Document as Docx
    from .docgen import PLACEHOLDER_RE as SECTION_RE, template_mode

    d = Docx(io.BytesIO(data))
    text = "\n".join(p.text for p in d.paragraphs)
    hdr = "\n".join(p.text for s in d.sections for p in s.header.paragraphs)
    found = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", text + hdr)))
    styles = [s.name for s in d.styles if s.type == 1 and s.name.startswith(("Heading", "Title", "Normal", "List"))][:12]
    sections = [p.text.strip() for p in d.paragraphs if SECTION_RE.match(p.text or "")]
    mode = template_mode(d)
    how = {"marker": "The proposal is written where {{CONTENT}} sits.",
           "sections": f"Your template's own sections are kept: {len(sections)} placeholders are filled with the matching content, and its sample tables are left out.",
           "styles": "Only the look is used (styles, header, footer, logo); the proposal content replaces the body."}[mode]
    return {"placeholders": found, "styles": styles, "has_content_marker": "CONTENT" in found, "mode": mode,
            "section_placeholders": sections[:40], "how": how}


def analyse_as(doc: Document, kind: str | None, data: bytes, parsed: ParsedDocument | None) -> None:
    """Fill doc.parsed with the preview for the chosen type (keeps the folder-import bookkeeping)."""
    keep = {k: v for k, v in (doc.parsed or {}).items() if k in ("batch", "path", "detected", "confidence", "reason")}
    keep.pop("ai", None)
    doc.kind = kind or "unsorted"
    doc.error = ""
    if kind is None:
        doc.parsed, doc.status = {**keep, "record_count": 0}, "review"
        return
    if kind == "template":
        if Path(doc.filename).suffix.lower() != ".docx":
            doc.parsed, doc.status, doc.error = {**keep, "record_count": 0}, "review", "Proposal templates must be Word (.docx) files."
            return
        doc.parsed, doc.status = {**keep, **template_analysis(data), "record_count": 1}, "review"
        return
    parsed = parsed or parse_document(data, doc.filename)
    a = analyze(kind, parsed, use_ai=False)  # instant, rules only; the AI pass runs afterwards and never blocks the review
    stored = {k: v for k, v in a.items() if k != "records"}
    stored["records_preview"] = a["records"][:200]
    stored["record_count"] = len(a["records"])
    if parsed.tables:
        stored["rows"] = max(parsed.tables, key=len)[:2000]
    if not parsed.tables and llm.is_enabled():
        stored["ai"] = "pending"
    doc.parsed, doc.pages, doc.status = {**keep, **stored}, parsed.pages, "review"


_queue: "queue.Queue[str]" = queue.Queue()
_ai_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None
_ai_worker: threading.Thread | None = None
_lock = threading.Lock()


def _process_one(did: str) -> None:
    db = SessionLocal()
    try:
        doc = db.get(Document, did)
        if not doc or doc.status != "analyzing":
            return
        llm.set_tenant(doc.tenant_id)  # the company's own AI settings, if it has any
        try:
            data = Path(doc.path).read_bytes()
            parsed = parse_document(data, doc.filename)
            kind, conf, reason = classify((doc.parsed or {}).get("path") or doc.filename, data, parsed)
            doc.parsed = {**(doc.parsed or {}), "detected": kind, "confidence": conf, "reason": reason}
            analyse_as(doc, kind, data, parsed)
        except Exception as e:  # one bad file must not stop the rest
            log.warning("Folder import: couldn't read %s: %s", doc.filename, e)
            doc.parsed = {**(doc.parsed or {}), "detected": None, "confidence": "low", "reason": "Couldn't read this file.", "record_count": 0}
            doc.kind, doc.status, doc.error = "unsorted", "failed", str(e)[:500]
        db.commit()
        if (doc.parsed or {}).get("ai") == "pending":
            _ai_queue.put(doc.id)  # only after the commit, so the AI worker sees the finished first pass
    finally:
        db.close()


def _ai_one(did: str) -> None:
    """Second pass for Word/PDF/PowerPoint: ask the AI for fuller records. If the file was already imported,
    retyped, or the AI fails, the rules-based preview simply stays."""
    db = SessionLocal()
    try:
        doc = db.get(Document, did)
        if not doc or doc.status != "review" or doc.kind not in KINDS or (doc.parsed or {}).get("ai") != "pending":
            return
        kind, path, name = doc.kind, doc.path, doc.filename
        llm.set_tenant(doc.tenant_id)
        db.close()
        recs: list = []
        try:
            recs = llm_records(kind, parse_document(Path(path).read_bytes(), name))
        except Exception as e:
            log.info("Folder import: AI pass skipped for %s: %s", name, e)
        db = SessionLocal()
        doc = db.get(Document, did)
        if not doc or doc.status != "review" or doc.kind != kind or (doc.parsed or {}).get("ai") != "pending":
            return  # imported or retyped meanwhile
        p = dict(doc.parsed or {})
        if recs and len(recs) >= len(p.get("records_preview") or []):
            p["records_preview"], p["record_count"], p["missing"] = recs[:200], len(recs), []
            p["ai"] = "done"
        else:
            p["ai"] = "kept"
        doc.parsed = p
        db.commit()
    finally:
        db.close()


def _run_ai() -> None:
    while True:
        did = _ai_queue.get()
        try:
            _ai_one(did)
        except Exception:
            log.exception("Folder import AI worker error")
        finally:
            _ai_queue.task_done()


def _run() -> None:
    # one worker, one file at a time: keeps AI calls within the free-tier rate limit
    while True:
        did = _queue.get()
        try:
            _process_one(did)
        except Exception:
            log.exception("Folder import worker error")
        finally:
            _queue.task_done()


def _ensure_workers() -> None:
    global _worker, _ai_worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, daemon=True, name="folder-import")
            _worker.start()
        if _ai_worker is None or not _ai_worker.is_alive():
            _ai_worker = threading.Thread(target=_run_ai, daemon=True, name="folder-import-ai")
            _ai_worker.start()


def start(doc_ids: list[str]) -> None:
    for d in doc_ids:
        _queue.put(d)
    _ensure_workers()


def queue_ai(doc_id: str) -> None:
    _ai_queue.put(doc_id)
    _ensure_workers()


def resume_unfinished() -> None:
    """After a restart, carry on with files that were still waiting to be read."""
    db = SessionLocal()
    try:
        ids = list(db.scalars(select(Document.id).where(Document.status == "analyzing").order_by(Document.created_at)))
        ai = [d.id for d in db.scalars(select(Document).where(Document.status == "review")) if (d.parsed or {}).get("ai") == "pending"]
    finally:
        db.close()
    if ids:
        start(ids)
    for d in ai:
        queue_ai(d)
