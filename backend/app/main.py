from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .db import init_db
from .routers import assistant, auth, deals, insights, learning, library
from .services import company_ai, llm  # noqa: F401  (company_ai registers the per-company AI settings)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(title="RevenueForge API", version="1.0.0", description="AI deal & proposal intelligence")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _company_ai_context(request: Request, call_next):
    """AI calls made while handling this request use the signed-in company's own AI settings (if it has any)."""
    tid = None
    auth = request.headers.get("authorization", "")
    if auth[:7].lower() == "bearer ":
        try:
            import jwt
            tid = jwt.decode(auth[7:], settings.jwt_secret, algorithms=["HS256"]).get("tid")
        except Exception:
            tid = None
    token = llm.set_tenant(tid)
    try:
        return await call_next(request)
    finally:
        llm.reset_tenant(token)


@app.on_event("startup")
def _startup():
    init_db()
    from .services import ai_settings
    ai_settings.apply_saved()  # AI engine settings saved from Settings → AI engine
    # Any deal left mid-run by a restart is marked so the user can re-run it.
    from sqlalchemy import select
    from .db import SessionLocal
    from .models import Deal
    db = SessionLocal()
    try:
        for d in db.scalars(select(Deal).where(Deal.status == "processing")):
            d.status = "failed"
            d.progress = {**(d.progress or {}), "message": "Processing was interrupted by a restart. Run it again."}
        db.commit()
    finally:
        db.close()
    # files from a folder import that were still waiting to be read carry on
    from .services import folder_import, story
    folder_import.resume_unfinished()
    story.mark_interrupted()


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    logging.getLogger("revenueforge").exception("Unhandled error on %s", request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Something went wrong on the server. The error has been logged."})


@app.get("/api/health")
def health():
    return {"status": "ok", "llm": llm.status()}


app.include_router(auth.router)
app.include_router(library.router)
app.include_router(deals.router)
app.include_router(insights.router)
app.include_router(learning.router)
app.include_router(assistant.router)

# Serve the built frontend (frontend/dist) when present, so one process runs everything.
DIST = BASE_DIR.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        root = DIST.resolve()
        f = (DIST / full_path).resolve()
        if full_path and f.is_file() and f.is_relative_to(root):
            return FileResponse(f)
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found."})
        return FileResponse(DIST / "index.html")
