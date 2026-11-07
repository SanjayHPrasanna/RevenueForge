"""Company profile, onboarding uploads and the knowledge library (capabilities, people, certifications,
rate card, case studies, accelerators, proposal template)."""
from __future__ import annotations

import io
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, func, select

from ..config import UPLOAD_DIR, settings
from ..models import Accelerator, CaseStudy, Capability, Certification, Document, Employee, RateCard, Tenant
from ..security import Ctx, current_ctx, require_roles
from ..services import drive_sync, folder_import, graph, llm
from ..services.onboarding import FIELDS, KINDS, analyze, missing_fields, records_from_table
from ..services.parsing import parse_document

router = APIRouter(prefix="/api", tags=["library"])

MODEL = {"capabilities": Capability, "skills": Employee, "certifications": Certification, "rates": RateCard,
         "case_studies": CaseStudy, "accelerators": Accelerator}
ONBOARDING_STEPS = ["profile", "capabilities", "skills", "certifications", "rates", "case_studies", "template"]
ALLOWED = {".pdf", ".docx", ".xlsx", ".xlsm", ".csv", ".pptx", ".txt", ".md"}


def _row_dict(kind: str, r) -> dict:
    cols = [c.name for c in MODEL[kind].__table__.columns if c.name not in ("tenant_id",)]
    return {c: getattr(r, c) for c in cols}


async def save_upload(ctx: Ctx, file: UploadFile, kind: str) -> tuple[Document, bytes]:
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"{ext or 'This file type'} isn't supported. Upload PDF, Word, Excel, CSV, PowerPoint or text.")
    data = await file.read()
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {settings.max_upload_mb} MB.")
    if not data:
        raise HTTPException(400, "The file is empty.")
    doc = Document(tenant_id=ctx.tenant_id, kind=kind, filename=file.filename, path="", size=len(data), uploaded_by=ctx.user.id)
    ctx.db.add(doc)
    ctx.db.flush()
    folder = UPLOAD_DIR / ctx.tenant_id
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", file.filename)[-120:]
    path = folder / f"{doc.id}_{safe}"
    path.write_bytes(data)
    doc.path = str(path)
    return doc, data


def _onboarding_status(ctx: Ctx) -> dict:
    t = ctx.tenant
    counts = {k: ctx.db.scalar(select(func.count()).select_from(m).where(m.tenant_id == ctx.tenant_id)) for k, m in MODEL.items()}
    has_template = bool(ctx.db.scalar(select(func.count()).select_from(Document).where(
        Document.tenant_id == ctx.tenant_id, Document.kind == "template", Document.status == "imported")))
    steps = {
        "profile": bool(t.about and t.industry),
        "capabilities": counts["capabilities"] > 0, "skills": counts["skills"] > 0, "certifications": counts["certifications"] > 0,
        "rates": counts["rates"] > 0, "case_studies": counts["case_studies"] > 0, "template": has_template,
    }
    required = ["capabilities", "skills", "rates", "template"]
    return {"steps": steps, "counts": counts, "complete": all(steps[s] for s in required), "required": required,
            "pct": round(sum(1 for s in ONBOARDING_STEPS if steps[s]) / len(ONBOARDING_STEPS) * 100)}


@router.get("/company")
def get_company(ctx: Ctx = Depends(current_ctx)):
    t = ctx.tenant
    return {"id": t.id, "name": t.name, "slug": t.slug, "industry": t.industry, "website": t.website, "about": t.about,
            "headquarters": t.headquarters, "headcount": t.headcount, "founded": t.founded, "currency": t.currency,
            "settings": {k: v for k, v in (t.settings or {}).items() if k != "ai"}, "onboarding": _onboarding_status(ctx),
            "llm": _llm_status(ctx), "notice": llm.notice()}


def _llm_status(ctx: Ctx) -> dict:
    """Call counts and errors are shown for the company's own key, or to platform admins for the shared server key."""
    from ..services import ai_settings
    own = llm.current_profile().source == "company"
    return llm.status(usage=own or ai_settings.is_platform_admin(ctx.user.email))


# --------------------------------------------------------------------------- the company's own AI provider and key
@router.get("/company/ai")
def get_company_ai(ctx: Ctx = Depends(current_ctx)):
    from ..services import company_ai
    return company_ai.view(ctx.tenant)


@router.put("/company/ai")
def save_company_ai(body: dict, ctx: Ctx = Depends(require_roles())):
    """Company admins only: every RFP the company processes afterwards is sent to this provider."""
    from ..services import company_ai
    try:
        company_ai.save(ctx.db, ctx.tenant, body, ctx.user.email)
    except ValueError as e:
        raise HTTPException(400, str(e))
    ctx.audit("company.ai.update", str(body.get("provider", "")))
    ctx.db.commit()
    return company_ai.view(ctx.tenant)


@router.post("/company/ai/test")
def test_company_ai(ctx: Ctx = Depends(require_roles())):
    from ..services import company_ai
    return company_ai.test(ctx.tenant_id)


@router.put("/company")
def update_company(body: dict, ctx: Ctx = Depends(require_roles())):
    t = ctx.tenant
    for f in ("name", "industry", "website", "about", "headquarters", "founded", "currency"):
        if f in body and body[f] is not None:
            setattr(t, f, str(body[f])[:2000])
    if "headcount" in body:
        try:
            hc = int(float(body["headcount"] or 0))
        except (TypeError, ValueError, OverflowError):
            raise HTTPException(400, "Headcount must be a number.")
        if not 0 <= hc <= 5_000_000:
            raise HTTPException(400, "Headcount must be between 0 and 5,000,000.")
        t.headcount = hc
    if isinstance(body.get("settings"), dict):
        s = dict(t.settings or {})
        for k, v in body["settings"].items():
            # Only the commercial policy is set here. The AI key (/company/ai), the network listing (/network/profile), the
            # demo flag and learned history are system-managed, so they can't be overwritten through this route.
            if k not in ("target_margin", "min_margin", "travel_pct", "hide_employee_names"):
                continue
            if k == "hide_employee_names":
                s[k] = bool(v)
                continue
            if k in ("target_margin", "min_margin", "travel_pct"):
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{k.replace('_', ' ')} must be a number.")
                hi = 100 if k == "travel_pct" else 80
                if not 0 <= v <= hi:
                    raise HTTPException(400, f"{k.replace('_', ' ')} must be between 0 and {hi}.")
            s[k] = v
        t.settings = s
    ctx.audit("company.update", t.id)
    ctx.db.commit()
    return get_company(ctx)


# --------------------------------------------------------------------------- uploads & mapping review
@router.post("/library/{kind}/upload")
async def upload(kind: str, file: UploadFile = File(...), ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    if kind not in KINDS and kind != "template":
        raise HTTPException(404, "Unknown library section.")
    doc, data = await save_upload(ctx, file, kind)
    if kind == "template":
        if Path(file.filename).suffix.lower() != ".docx":
            raise HTTPException(400, "Proposal templates must be Word (.docx) files.")
        from docx import Document as Docx
        try:
            d = Docx(io.BytesIO(data))
        except Exception:
            raise HTTPException(400, "This Word file couldn't be opened. Save it again as .docx and retry.")
        text = "\n".join(p.text for p in d.paragraphs)
        hdr = "\n".join(p.text for s in d.sections for p in s.header.paragraphs)
        found = sorted(set(re.findall(r"\{\{([A-Z_]+)\}\}", text + hdr)))
        styles = [s.name for s in d.styles if s.type == 1 and s.name.startswith(("Heading", "Title", "Normal", "List"))][:12]
        # older templates become the history; newest wins
        for old in ctx.db.scalars(select(Document).where(Document.tenant_id == ctx.tenant_id, Document.kind == "template", Document.status == "imported")):
            old.status = "replaced"
        doc.status = "imported"
        from ..services.docgen import PLACEHOLDER_RE, template_mode
        sections = [p.text.strip() for p in d.paragraphs if PLACEHOLDER_RE.match(p.text or "")]
        mode = template_mode(d)
        how = {"marker": "The proposal is written where {{CONTENT}} sits.",
               "sections": f"Your template's own sections are kept: {len(sections)} placeholders are filled with the matching content, and its sample tables are left out.",
               "styles": "Only the look is used (styles, header, footer, logo); the proposal content replaces the body."}[mode]
        doc.parsed = {"placeholders": found, "styles": styles, "has_content_marker": "CONTENT" in found, "mode": mode,
                      "section_placeholders": sections[:40], "how": how}
        ctx.audit("template.upload", file.filename)
        ctx.db.commit()
        return {"id": doc.id, "kind": kind, "filename": doc.filename, "status": doc.status, "analysis": doc.parsed}
    try:
        parsed = parse_document(data, file.filename)
    except Exception as e:
        doc.status, doc.error = "failed", str(e)
        ctx.db.commit()
        raise HTTPException(400, f"Couldn't read this file: {e}")
    a = analyze(kind, parsed)
    stored = {k: v for k, v in a.items() if k != "records"}
    stored["records_preview"] = a["records"][:200]
    stored["record_count"] = len(a["records"])
    if parsed.tables:
        stored["rows"] = max(parsed.tables, key=len)[:2000]
    doc.parsed = stored
    doc.pages = parsed.pages
    doc.status = "review"
    ctx.db.commit()
    return {"id": doc.id, "kind": kind, "filename": doc.filename, "status": doc.status, "analysis": {**stored, "rows": None}}


@router.post("/library/uploads/{doc_id}/remap")
def remap(doc_id: str, body: dict, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    doc = ctx.db.get(Document, doc_id)
    if not doc or doc.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Upload not found.")
    p = dict(doc.parsed or {})
    if p.get("format") != "table":
        raise HTTPException(400, "Column mapping only applies to spreadsheets.")
    mapping = {k: int(v) for k, v in (body.get("mapping") or {}).items() if v is not None and str(v) != ""}
    p["mapping"] = mapping
    if "wide_skill_columns" in body:
        p["wide_skill_columns"] = [int(x) for x in body["wide_skill_columns"]]
    recs = records_from_table(doc.kind, p["rows"], p)
    p["missing"] = missing_fields(doc.kind, p)
    p["records_preview"] = recs[:200]
    p["record_count"] = len(recs)
    doc.parsed = p
    ctx.db.commit()
    return {"analysis": {**p, "rows": None}}


def _import_doc(ctx: Ctx, doc: Document, mode: str = "replace", records: list | None = None) -> int:
    """Turn one reviewed upload into library records. The caller rebuilds the graph and commits."""
    kind = doc.kind
    p = doc.parsed or {}
    if p.get("format") == "table":
        recs = records_from_table(kind, p["rows"], p)
    else:
        recs = records or p.get("records_preview", [])
    if not recs:
        raise HTTPException(400, "Nothing to import. Check the column mapping.")
    M = MODEL[kind]
    if mode == "replace":
        ctx.db.execute(delete(M).where(M.tenant_id == ctx.tenant_id))
    cols = {c.name for c in M.__table__.columns}
    n = 0
    added = []
    for r in recs:
        clean = {k: v for k, v in r.items() if k in cols and k not in ("id", "tenant_id")}
        if kind == "skills" and not clean.get("code"):
            clean["code"] = f"EMP-{n + 1:04d}"
        if kind == "skills" and (ctx.tenant.settings or {}).get("hide_employee_names", True):
            clean["name"] = ""
        if kind == "rates" and not clean.get("currency"):
            clean["currency"] = ctx.tenant.currency
        obj = M(tenant_id=ctx.tenant_id, source_doc=doc.id, **clean)
        ctx.db.add(obj)
        added.append(obj)
        n += 1
    # fingerprints of what was imported, so a later Drive refresh can say which records were edited in the app since
    doc.parsed = {**(doc.parsed or {}), "sigs": [drive_sync.record_sig(M, o) for o in added]}
    doc.status = "imported"
    ob = dict(ctx.tenant.onboarding or {})
    ob[kind] = True
    ctx.tenant.onboarding = ob
    return n


@router.post("/library/uploads/{doc_id}/import")
def import_upload(doc_id: str, body: dict | None = None, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    body = body or {}
    doc = ctx.db.get(Document, doc_id)
    if not doc or doc.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Upload not found.")
    if doc.kind not in MODEL:
        raise HTTPException(400, "Pick what kind of file this is first.")
    n = _import_doc(ctx, doc, body.get("mode", "replace"), body.get("records"))
    ctx.db.flush()
    stats = graph.rebuild_company_graph(ctx.db, ctx.tenant_id)
    ctx.audit("library.import", doc.kind, records=n, file=doc.filename)
    ctx.db.commit()
    return {"imported": n, "kind": doc.kind, "graph": stats, "onboarding": _onboarding_status(ctx)}


# --------------------------------------------------------------------------- whole-folder import
SKIP_NAME = re.compile(r"^(~\$|\.|thumbs\.db$|desktop\.ini$)", re.I)
MAX_FOLDER_FILES = 300


def _batch_docs(ctx: Ctx, batch: str) -> list[Document]:
    rows = ctx.db.scalars(select(Document).where(Document.tenant_id == ctx.tenant_id, Document.kind != "rfp")
                          .order_by(Document.created_at)).all()
    return [d for d in rows if (d.parsed or {}).get("batch") == batch]


def _folder_row(d: Document) -> dict:
    p = d.parsed or {}
    return {"id": d.id, "path": p.get("path") or d.filename, "filename": d.filename, "size": d.size, "status": d.status,
            "type": d.kind if d.kind in folder_import.TYPES else None, "detected": p.get("detected"),
            "confidence": p.get("confidence"), "reason": p.get("reason", ""), "records": p.get("record_count", 0),
            "format": p.get("format"), "missing": p.get("missing", []), "error": d.error, "how": p.get("how"), "ai": p.get("ai"),
            "drive_change": (p.get("drive") or {}).get("change")}


@router.post("/library/folder")
async def folder_upload(files: list[UploadFile] = File(...), paths: list[str] = Form(default=[]), batch: str = Form(default=""),
                        drive: list[str] = Form(default=[]), drive_folder: str = Form(default=""),
                        ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    """Receive some (or all) files of a folder. Large folders arrive in several calls with the same batch id.
    Files from Google Drive also carry `drive` (one JSON object per file: id, modified, version, change) and the batch
    carries `drive_folder` ({"id", "name"}), so the folder can stay connected and be refreshed later."""
    import json as _json
    folder_meta = None
    if drive_folder:
        try:
            fm = _json.loads(drive_folder)
            if isinstance(fm, dict) and fm.get("id"):
                folder_meta = {"id": str(fm["id"])[:128], "name": str(fm.get("name") or "Google Drive folder")[:200]}
        except ValueError:
            raise HTTPException(400, "drive_folder must be JSON.")
    batch = re.sub(r"[^a-z0-9]", "", batch.lower())[:32] or secrets.token_hex(8)
    existing = _batch_docs(ctx, batch)
    if len(existing) + len(files) > MAX_FOLDER_FILES:
        raise HTTPException(400, f"That's more than {MAX_FOLDER_FILES} files. Pick the folder that holds just the company knowledge files.")
    seen = {(d.filename, d.size) for d in existing}
    accepted, skipped = [], []
    for i, f in enumerate(files):
        rel = (paths[i] if i < len(paths) else "") or f.filename or "file"
        name = Path(rel).name
        ext = Path(name).suffix.lower()
        if SKIP_NAME.search(name):
            continue
        if ext not in ALLOWED:
            skipped.append({"path": rel, "reason": f"{ext or 'This type'} isn't a supported file"})
            continue
        data = await f.read()
        if not data:
            skipped.append({"path": rel, "reason": "Empty file"})
            continue
        if len(data) > settings.max_upload_mb * 1024 * 1024:
            skipped.append({"path": rel, "reason": f"Larger than {settings.max_upload_mb} MB"})
            continue
        if (name, len(data)) in seen:
            skipped.append({"path": rel, "reason": "Same file appears twice in the folder"})
            continue
        seen.add((name, len(data)))
        parsed = {"batch": batch, "path": rel}
        if folder_meta and i < len(drive):
            try:
                dm = _json.loads(drive[i])
            except ValueError:
                dm = None
            if isinstance(dm, dict) and dm.get("id"):
                parsed["drive"] = {"id": str(dm["id"])[:128], "modified": str(dm.get("modified") or "")[:40],
                                   "version": str(dm.get("version") or "")[:40],
                                   "change": dm.get("change") if dm.get("change") in ("new", "changed") else "new"}
                parsed["drive_folder"] = folder_meta
        doc = Document(tenant_id=ctx.tenant_id, kind="unsorted", filename=name, path="", size=len(data), uploaded_by=ctx.user.id,
                       status="analyzing", parsed=parsed)
        ctx.db.add(doc)
        ctx.db.flush()
        folder = UPLOAD_DIR / ctx.tenant_id
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f"{doc.id}_{re.sub(r'[^A-Za-z0-9._ -]+', '_', name)[-120:]}"
        dest.write_bytes(data)
        doc.path = str(dest)
        accepted.append(doc.id)
    ctx.audit("library.folder_upload", batch, files=len(accepted))
    ctx.db.commit()
    folder_import.start(accepted)
    return {"batch": batch, "accepted": len(accepted), "skipped": skipped}


@router.get("/library/folder/{batch}")
def folder_status(batch: str, ctx: Ctx = Depends(current_ctx)):
    docs = _batch_docs(ctx, batch)
    if not docs:
        raise HTTPException(404, "Upload not found.")
    rows = [_folder_row(d) for d in docs]
    return {"batch": batch, "files": rows, "pending": sum(1 for r in rows if r["status"] == "analyzing"),
            "imported": sum(1 for r in rows if r["status"] == "imported")}


@router.post("/library/folder/{batch}/{doc_id}/type")
def folder_set_type(batch: str, doc_id: str, body: dict, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    doc = ctx.db.get(Document, doc_id)
    if not doc or doc.tenant_id != ctx.tenant_id or (doc.parsed or {}).get("batch") != batch:
        raise HTTPException(404, "File not found.")
    if doc.status in ("analyzing", "imported"):
        raise HTTPException(409, "This file is still being read." if doc.status == "analyzing" else "This file is already imported.")
    kind = body.get("type") or None
    if kind is not None and kind not in folder_import.TYPES:
        raise HTTPException(400, "Unknown file type.")
    try:
        folder_import.analyse_as(doc, kind, Path(doc.path).read_bytes(), None)
    except Exception as e:
        doc.status, doc.error = "failed", str(e)[:500]
    ctx.db.commit()
    if (doc.parsed or {}).get("ai") == "pending":
        folder_import.queue_ai(doc.id)
    return _folder_row(doc)


@router.post("/library/folder/{batch}/import")
def folder_import_all(batch: str, body: dict | None = None, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    body = body or {}
    if not _batch_docs(ctx, batch):
        raise HTTPException(404, "Upload not found.")
    if not isinstance(body, dict):
        body = {}
    skip = {str(x) for x in body.get("skip")} if isinstance(body.get("skip"), list) else set()
    replace = bool(body.get("replace", True))
    all_docs = _batch_docs(ctx, batch)
    drive_docs = [d for d in all_docs if (d.parsed or {}).get("drive")]
    conn = drive_sync.connection(ctx.tenant)
    sync = bool(body.get("sync")) and conn is not None and bool(drive_docs)
    if sync and any((d.parsed or {}).get("drive_folder", {}).get("id") != conn["folder"]["id"] for d in drive_docs):
        raise HTTPException(409, "These files come from a different Drive folder than the connected one.")
    if sync:
        replace = False  # a refresh only touches the files that changed; everything else stays as it is
    docs = [d for d in all_docs if d.status == "review"]
    if any(d.status == "analyzing" for d in _batch_docs(ctx, batch)):
        raise HTTPException(409, "Some files are still being read. Wait a moment and try again.")
    counts: dict[str, int] = {}
    files, problems = 0, []
    started: set[str] = set()
    template_done = False
    for d in docs:
        if d.id in skip or d.kind not in folder_import.TYPES:
            d.status = "skipped"
            continue
        if d.kind == "template":
            if template_done or d.error:
                d.status = "skipped"
                continue
            for old in ctx.db.scalars(select(Document).where(Document.tenant_id == ctx.tenant_id, Document.kind == "template",
                                                             Document.status == "imported")):
                old.status = "replaced"
            d.status, template_done = "imported", True
            counts["template"] = 1
            files += 1
            continue
        mode = "replace" if replace and d.kind not in started else "append"
        try:
            n = _import_doc(ctx, d, mode)
        except HTTPException as e:
            problems.append({"path": (d.parsed or {}).get("path") or d.filename, "reason": e.detail})
            continue
        if sync:  # the new version is in; now take out what the previous version of the same Drive file put there
            old = conn["files"].get(d.parsed["drive"]["id"]) or {}
            if old.get("doc_id") and old.get("kind") in MODEL:
                OM = MODEL[old["kind"]]
                ctx.db.execute(delete(OM).where(OM.tenant_id == ctx.tenant_id, OM.source_doc == old["doc_id"]))
                prev = ctx.db.get(Document, old["doc_id"])
                if prev and prev.tenant_id == ctx.tenant_id:
                    prev.status = "replaced"
        started.add(d.kind)
        counts[d.kind] = counts.get(d.kind, 0) + n
        files += 1
    removed = []
    if drive_docs:
        if sync:
            removed = _drive_remove(ctx, conn, body.get("remove"))
        else:  # first import from Drive: this folder is now connected
            first = drive_docs[0].parsed["drive_folder"]
            conn = {"folder": first, "connected_by": ctx.user.name, "connected_at": drive_sync.now_iso(), "files": {}}
        for d in drive_docs:
            dm = d.parsed["drive"]
            if d.status == "imported":
                conn["files"][dm["id"]] = {"path": d.parsed.get("path") or d.filename, "modified": dm["modified"], "version": dm["version"],
                                           "doc_id": d.id, "kind": d.kind}
            elif not sync:
                # left out on purpose at connect time: remember it, so a refresh only raises it again if it changes
                conn["files"][dm["id"]] = {"path": d.parsed.get("path") or d.filename, "modified": dm["modified"], "version": dm["version"],
                                           "doc_id": "", "kind": ""}
        conn["last_refresh"] = drive_sync.now_iso()
        drive_sync.save_connection(ctx.tenant, conn)
    ctx.db.flush()
    stats = graph.rebuild_company_graph(ctx.db, ctx.tenant_id)
    ctx.audit("library.folder_import", batch, files=files, drive="refresh" if sync else ("connect" if drive_docs else ""), removed=len(removed), **counts)
    ctx.db.commit()
    return {"files": files, "counts": counts, "problems": problems, "graph": stats, "onboarding": _onboarding_status(ctx),
            "removed": removed}


# --------------------------------------------------------------------------- connected Google Drive folder
def _drive_out(ctx: Ctx, conn: dict | None) -> dict:
    if not conn:
        return {"connected": False}
    return {"connected": True, "folder": conn["folder"], "connected_by": conn.get("connected_by", ""), "connected_at": conn.get("connected_at"),
            "last_refresh": conn.get("last_refresh"), "last_checked": conn.get("last_checked"),
            "files": sum(1 for f in conn.get("files", {}).values() if f.get("doc_id")),
            "left_out": sum(1 for f in conn.get("files", {}).values() if not f.get("doc_id"))}


def _drive_remove(ctx: Ctx, conn: dict, ids) -> list[str]:
    """Take out what the given Drive files put in the library (only files the person ticked)."""
    out = []
    for fid in [str(x) for x in ids] if isinstance(ids, list) else []:
        f = conn["files"].get(fid)
        if not f:
            continue
        if f.get("doc_id") and f.get("kind") in MODEL:
            M = MODEL[f["kind"]]
            ctx.db.execute(delete(M).where(M.tenant_id == ctx.tenant_id, M.source_doc == f["doc_id"]))
        if f.get("doc_id"):
            doc = ctx.db.get(Document, f["doc_id"])
            if doc and doc.tenant_id == ctx.tenant_id:
                doc.status = "removed"
        conn["files"].pop(fid, None)
        out.append(f.get("path") or fid)
    return out


@router.get("/library/drive")
def drive_status(ctx: Ctx = Depends(current_ctx)):
    return _drive_out(ctx, drive_sync.connection(ctx.tenant))


@router.post("/library/drive/plan")
def drive_plan(body: dict, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    """Compare the folder as the browser sees it now with what was imported last time. Nothing is changed here."""
    conn = drive_sync.connection(ctx.tenant)
    if not conn:
        raise HTTPException(404, "No Google Drive folder is connected.")
    if not isinstance(body, dict) or str(body.get("folder_id") or "") != conn["folder"]["id"]:
        raise HTTPException(409, "That isn't the connected folder.")
    listing = drive_sync.clean_listing(body.get("files"))
    known = conn.get("files", {})
    new, chg, unchanged = [], [], 0
    for f in listing:
        old = known.get(f["id"])
        if old is None:
            new.append({"id": f["id"], "path": f["path"]})
        elif drive_sync.changed(old, f):
            item = {"id": f["id"], "path": f["path"], "kind": old.get("kind") or None, "imported": bool(old.get("doc_id"))}
            if old.get("doc_id") and old.get("kind") in MODEL:
                doc = ctx.db.get(Document, old["doc_id"])
                M = MODEL[old["kind"]]
                item["records"] = len(drive_sync.doc_records(ctx.db, M, ctx.tenant_id, old["doc_id"]))
                item["edited_in_app"] = drive_sync.edited_count(ctx.db, M, ctx.tenant_id, doc) if doc else None
            chg.append(item)
        else:
            unchanged += 1
            if old.get("path") != f["path"]:
                old["path"] = f["path"]  # renamed or moved inside the folder: same file
    seen = {f["id"] for f in listing}
    gone = []
    for fid, old in list(known.items()):
        if fid in seen:
            continue
        if not old.get("doc_id"):
            known.pop(fid)  # nothing was imported from it, so there's nothing to decide
            continue
        item = {"id": fid, "path": old.get("path", ""), "kind": old.get("kind") or None, "imported": bool(old.get("doc_id")), "records": 0}
        if old.get("doc_id") and old.get("kind") in MODEL:
            item["records"] = len(drive_sync.doc_records(ctx.db, MODEL[old["kind"]], ctx.tenant_id, old["doc_id"]))
        gone.append(item)
    conn["last_checked"] = drive_sync.now_iso()
    if not new and not chg and not gone:
        conn["last_refresh"] = conn["last_checked"]
    drive_sync.save_connection(ctx.tenant, conn)
    ctx.audit("library.drive_check", conn["folder"]["id"], new=len(new), changed=len(chg), removed=len(gone))
    ctx.db.commit()
    return {"new": new, "changed": chg, "removed": gone, "unchanged": unchanged, "up_to_date": not new and not chg and not gone}


@router.post("/library/drive/remove")
def drive_remove(body: dict, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    """For a refresh where files were only deleted from Drive: take out what the ticked files put in the library."""
    conn = drive_sync.connection(ctx.tenant)
    if not conn:
        raise HTTPException(404, "No Google Drive folder is connected.")
    removed = _drive_remove(ctx, conn, (body or {}).get("ids") if isinstance(body, dict) else None)
    conn["last_refresh"] = drive_sync.now_iso()
    drive_sync.save_connection(ctx.tenant, conn)
    ctx.db.flush()
    stats = graph.rebuild_company_graph(ctx.db, ctx.tenant_id)
    ctx.audit("library.drive_remove", conn["folder"]["id"], removed=len(removed))
    ctx.db.commit()
    return {"removed": removed, "graph": stats}


@router.delete("/library/drive")
def drive_disconnect(ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    """Forget the folder. Everything already imported stays in the library."""
    conn = drive_sync.connection(ctx.tenant)
    if not conn:
        raise HTTPException(404, "No Google Drive folder is connected.")
    drive_sync.save_connection(ctx.tenant, None)
    ctx.audit("library.drive_disconnect", conn["folder"]["id"])
    ctx.db.commit()
    return {"connected": False}


@router.get("/library/uploads")
def list_uploads(ctx: Ctx = Depends(current_ctx)):
    rows = ctx.db.scalars(select(Document).where(Document.tenant_id == ctx.tenant_id, Document.kind.notin_(("rfp", "unsorted", "story_video")),
                                                 Document.status.notin_(("analyzing", "skipped"))).order_by(Document.created_at.desc())).all()
    return [{"id": d.id, "kind": d.kind, "filename": d.filename, "status": d.status, "size": d.size, "created_at": d.created_at,
             "records": (d.parsed or {}).get("record_count")} for d in rows]


@router.get("/library/uploads/{doc_id}")
def get_upload(doc_id: str, ctx: Ctx = Depends(current_ctx)):
    doc = ctx.db.get(Document, doc_id)
    if not doc or doc.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Upload not found.")
    return {"id": doc.id, "kind": doc.kind, "filename": doc.filename, "status": doc.status, "analysis": {**(doc.parsed or {}), "rows": None}}


@router.get("/library/template")
def get_template(ctx: Ctx = Depends(current_ctx)):
    doc = ctx.db.scalar(select(Document).where(Document.tenant_id == ctx.tenant_id, Document.kind == "template", Document.status == "imported")
                        .order_by(Document.created_at.desc()))
    if not doc:
        return None
    return {"id": doc.id, "filename": doc.filename, "created_at": doc.created_at, "analysis": doc.parsed}


@router.get("/library/template/download")
def download_template(ctx: Ctx = Depends(current_ctx)):
    doc = ctx.db.scalar(select(Document).where(Document.tenant_id == ctx.tenant_id, Document.kind == "template", Document.status == "imported")
                        .order_by(Document.created_at.desc()))
    if not doc:
        raise HTTPException(404, "No template uploaded yet.")
    return StreamingResponse(open(doc.path, "rb"), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                             headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'})


@router.get("/library/{kind}/starter.xlsx")
def starter(kind: str, ctx: Ctx = Depends(current_ctx)):
    """A blank, well-labelled spreadsheet for companies that want a clean start."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill

    if kind not in FIELDS:
        raise HTTPException(404, "Unknown library section.")
    headers = {
        "capabilities": ["Service Line", "Capability", "Description", "Technologies", "Industries", "Maturity"],
        "skills": ["Emp ID", "Designation", "Grade", "Total Exp (yrs)", "Base Location", "Practice", "Primary Skills (rating 1-5)", "Certifications", "Available %"],
        "certifications": ["Certification", "Type", "Issued By", "No. of Certified Employees", "Valid Until"],
        "rates": ["Role", "Level", "Delivery Location", "Day Rate", "Day Cost", "Currency"],
        "case_studies": ["Project Name", "Client", "Industry", "Region", "Year", "Summary", "Technologies", "Outcomes"],
        "accelerators": ["Accelerator", "Description", "Technologies", "Effort Saving %"],
    }[kind]
    example = {
        "capabilities": ["Integration Services", "API Management", "Design and run secure API platforms", "Apigee, MuleSoft", "BFSI; Healthcare", "Core"],
        "skills": ["E-001", "Senior Integration Engineer", "L4", 9, "Bengaluru", "Integration", "MuleSoft (5), Kafka (4), Java (4)", "MuleSoft Certified Developer", "100%"],
        "certifications": ["ISO/IEC 27001:2022", "Company", "BSI", "", "2027-06-30"],
        "rates": ["Integration Engineer", "L4", "Offshore", 380, 175, "USD"],
        "case_studies": ["API platform for a retail bank", "Retail bank", "BFSI", "UAE", 2025, "What we did and how", "MuleSoft, Kafka", "65 APIs live; 4x faster partner onboarding"],
        "accelerators": ["Interface Factory", "Reusable templates for common flows", "MuleSoft", 20],
    }[kind]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = KINDS[kind][:30]
    ws.append(headers)
    ws.append(example)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="125C7E")
    for i in range(1, len(headers) + 1):
        ws.column_dimensions[openpyxl.utils.get_column_letter(i)].width = 26
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="revenueforge-{kind}-starter.xlsx"'})


# --------------------------------------------------------------------------- library CRUD
@router.get("/library/{kind}")
def list_kind(kind: str, q: str = "", ctx: Ctx = Depends(current_ctx)):
    if kind not in MODEL:
        raise HTTPException(404, "Unknown library section.")
    M = MODEL[kind]
    rows = ctx.db.scalars(select(M).where(M.tenant_id == ctx.tenant_id)).all()
    out = [_row_dict(kind, r) for r in rows]
    if q:
        ql = q.lower()
        out = [o for o in out if ql in str(o).lower()]
    hide = (ctx.tenant.settings or {}).get("hide_employee_names", True)
    if kind == "skills" and hide:
        for o in out:
            o["name"] = ""
    return out


def _clean_fields(M, body: dict, creating: bool) -> dict:
    """Only real columns, with the right shape: lists stay lists, text stays text, required fields aren't empty."""
    from sqlalchemy import JSON, Float, Integer, String, Text
    if not isinstance(body, dict):
        raise HTTPException(400, "Send the fields as a JSON object.")
    out = {}
    for col in M.__table__.columns:
        k = col.name
        if k in ("id", "tenant_id") or k not in body:
            continue
        v = body[k]
        t = col.type
        if isinstance(t, JSON):
            if v is None:
                v = []
            if isinstance(v, str):
                v = [x.strip() for x in v.split(",") if x.strip()]
            if not isinstance(v, (list, dict)):
                raise HTTPException(400, f"{k} must be a list.")
        elif isinstance(t, (Integer, Float)):
            if v in (None, ""):
                v = None
            else:
                try:
                    v = int(v) if isinstance(t, Integer) else float(v)
                except (TypeError, ValueError):
                    raise HTTPException(400, f"{k} must be a number.")
        elif isinstance(t, (String, Text)):
            if v is None:
                v = ""
            if not isinstance(v, (str, int, float)):
                raise HTTPException(400, f"{k} must be text.")
            v = str(v)
            if getattr(t, "length", None) and len(v) > t.length:
                raise HTTPException(400, f"{k} is too long (at most {t.length} characters).")
        out[k] = v
    required = [col.name for col in M.__table__.columns if not col.nullable and col.default is None and not col.primary_key
                and col.name not in ("tenant_id",)]
    for k in required:
        if (creating and k not in out) or (k in out and (out[k] is None or (isinstance(out[k], str) and not out[k].strip()))):
            raise HTTPException(400, f"{k.replace('_', ' ').capitalize()} is required.")
    return out


@router.post("/library/{kind}")
def create_item(kind: str, body: dict, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    if kind not in MODEL:
        raise HTTPException(404, "Unknown library section.")
    M = MODEL[kind]
    obj = M(tenant_id=ctx.tenant_id, **_clean_fields(M, body, creating=True))
    ctx.db.add(obj)
    ctx.db.flush()
    graph.rebuild_company_graph(ctx.db, ctx.tenant_id)
    ctx.db.commit()
    return _row_dict(kind, obj)


@router.put("/library/{kind}/{item_id}")
def update_item(kind: str, item_id: str, body: dict, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    if kind not in MODEL:
        raise HTTPException(404, "Unknown library section.")
    obj = ctx.db.get(MODEL[kind], item_id)
    if not obj or obj.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Item not found.")
    for k, v in _clean_fields(MODEL[kind], body, creating=False).items():
        setattr(obj, k, v)
    ctx.db.flush()
    graph.rebuild_company_graph(ctx.db, ctx.tenant_id)
    ctx.db.commit()
    return _row_dict(kind, obj)


@router.delete("/library/{kind}/{item_id}")
def delete_item(kind: str, item_id: str, ctx: Ctx = Depends(require_roles("presales", "architect", "finance"))):
    if kind not in MODEL:
        raise HTTPException(404, "Unknown library section.")
    obj = ctx.db.get(MODEL[kind], item_id)
    if not obj or obj.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "Item not found.")
    ctx.db.delete(obj)
    ctx.db.flush()
    graph.rebuild_company_graph(ctx.db, ctx.tenant_id)
    ctx.db.commit()
    return {"ok": True}
