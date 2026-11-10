from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, settings
from .db import init_db
from .routers import assistant, auth, company_data, deals, insights, learning, library, network, platform, radar, trust
from .services import company_ai, llm  # noqa: F401  (company_ai registers the per-company AI settings)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

# The API reference (/docs, /openapi.json) is only published when API_DOCS=true (e.g. on a developer's machine).
_docs = settings.api_docs
app = FastAPI(title="RevenueForge API", version="1.0.0", description="AI deal & proposal intelligence",
              docs_url="/docs" if _docs else None, redoc_url=None, openapi_url="/openapi.json" if _docs else None)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# Text files (the app's JavaScript and CSS, JSON) go out compressed: about a third of the size.
app.add_middleware(GZipMiddleware, minimum_size=1024)

_SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=(self)",
    # Only page-framing and plugin rules: scripts from Google/Microsoft sign-in keep working.
    "Content-Security-Policy": "frame-ancestors 'self'; object-src 'none'; base-uri 'self'",
}


@app.middleware("http")
async def _no_nul(request: Request, call_next):
    """A NUL character has no business in a URL; PostgreSQL can't even store one. Refuse it up front."""
    if "%00" in request.url.query or "\x00" in request.url.query or "%00" in request.url.path:
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "Invalid character in the address."}, status_code=400)
    return await call_next(request)


@app.middleware("http")
async def _headers(request: Request, call_next):
    """Security headers on every response, and browser caching for the built web app."""
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    path = request.url.path
    if path.startswith("/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # file names change on every build
    elif path.startswith(("/brand/", "/hero/", "/favicon")):
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif not path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache"  # index.html: always check for a new version
    return response


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
    llm.start_usage_flusher()  # AI call counts for the platform console, saved every minute
    from .services import errlog
    errlog.install()  # recent warnings and errors, for the platform console's health view
    from .services import notify
    notify.start_deadline_watch()  # "due in 3 days / tomorrow" reminder emails
    from .services import tender_feeds
    tender_feeds.start_schedule()  # opportunity radar: read public tender sources every few hours
    from .services import demo_vendors
    demo_vendors.ensure()  # fictional suppliers for the supplier-network demo (DEMO_VENDORS=false leaves them out)
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
    """Public liveness check. AI usage and errors are shown to signed-in admins in Settings, not here."""
    from .db import DB_STATE
    return {"status": "ok"} if DB_STATE["ok"] else {"status": "degraded", "database": "damaged - see DEPLOY.md, 'Repairing the database'"}


@app.get("/robots.txt", include_in_schema=False)
def robots():
    return PlainTextResponse("User-agent: *\nAllow: /$\nDisallow: /app\nDisallow: /api/\n")


app.include_router(auth.router)
app.include_router(platform.router)
app.include_router(library.router)
app.include_router(deals.router)
app.include_router(insights.router)
app.include_router(learning.router)
app.include_router(assistant.router)
app.include_router(radar.router)
app.include_router(network.router)
app.include_router(trust.router)
app.include_router(company_data.router)

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
