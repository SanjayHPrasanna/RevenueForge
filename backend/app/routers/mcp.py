"""RevenueForge for AI assistants: a remote MCP server at /mcp, with its own OAuth sign-in.

Claude (claude.ai, Desktop, mobile, Claude Code) and Glean connect by URL: <app>/mcp. They discover the OAuth endpoints
below, register themselves, and send the person to /connect in the app to press Allow. Tools that only take a fixed key
(Glean "API key", or request headers) use a personal key made in Settings > AI assistants.

Every tool runs through the app's own API as the connected person, so roles, client-name masking and company boundaries
are exactly the same as in the web app.
"""
from __future__ import annotations

import base64
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..config import settings
from ..db import get_db
from ..models import McpToken, OAuthClient, OAuthCode, User
from ..security import Ctx, create_token, current_ctx
from ..services import mcp_auth as A

log = logging.getLogger("revenueforge.mcp")
router = APIRouter(tags=["mcp"])

PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "RevenueForge", "title": "RevenueForge", "version": "1.0.0"}
INSTRUCTIONS = (
    "RevenueForge is the person's bid and proposal workspace. Use it to look up their deals (RFPs being bid), the bid verdict "
    "and readiness for each, requirement gaps, and their company knowledge library (people and skills, capabilities, "
    "certifications, case studies, accelerators). Verdicts and readiness are the app's own honest assessment: report them as "
    "they are and do not round a 'No bid' or a gap up into something better. Client names may be masked as aliases such as "
    "'Client A' on confidential deals; keep them that way. Link the person to the deal page (app_url) for proposal documents."
)


# =========================================================================== OAuth discovery
def _prm(request: Request) -> dict:
    o = A.origin(request)
    return {"resource": o + "/mcp", "authorization_servers": [o], "scopes_supported": ["revenueforge"],
            "bearer_methods_supported": ["header"], "resource_name": "RevenueForge"}


@router.get("/.well-known/oauth-protected-resource", include_in_schema=False)
@router.get("/.well-known/oauth-protected-resource/mcp", include_in_schema=False)
def protected_resource(request: Request):
    return JSONResponse(_prm(request), headers={"Access-Control-Allow-Origin": "*"})


@router.get("/.well-known/oauth-authorization-server", include_in_schema=False)
@router.get("/.well-known/oauth-authorization-server/mcp", include_in_schema=False)
@router.get("/.well-known/openid-configuration", include_in_schema=False)
def authorization_server(request: Request):
    o = A.origin(request)
    return JSONResponse({
        "issuer": o,
        "authorization_endpoint": o + "/oauth/authorize",
        "token_endpoint": o + "/oauth/token",
        "registration_endpoint": o + "/oauth/register",
        "revocation_endpoint": o + "/oauth/revoke",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_post", "client_secret_basic"],
        "scopes_supported": ["revenueforge", "offline_access"],
        "service_documentation": o + "/app/settings",
    }, headers={"Access-Control-Allow-Origin": "*"})


# =========================================================================== OAuth: registration, authorize, token
def _redirect_ok(uri: str) -> bool:
    try:
        u = urlparse(uri)
    except ValueError:
        return False
    if u.fragment or not u.netloc:
        return False
    if u.scheme == "https":
        return True
    return u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1")  # native apps (Claude Code) on a loopback port


def _redirect_matches(uri: str, registered: list[str]) -> bool:
    if uri in registered:
        return True
    u = urlparse(uri)
    if u.scheme == "http" and u.hostname in ("localhost", "127.0.0.1", "::1"):  # RFC 8252: any port on loopback
        for r in registered:
            ru = urlparse(r)
            if ru.scheme == "http" and ru.hostname in ("localhost", "127.0.0.1", "::1") and ru.path == u.path:
                return True
    return False


@router.post("/oauth/register", include_in_schema=False)
async def register_client(request: Request, db=Depends(get_db)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_client_metadata", "error_description": "Send the registration as JSON."}, 400)
    uris = body.get("redirect_uris") or []
    if not isinstance(uris, list) or not uris or len(uris) > 10 or not all(isinstance(u, str) and len(u) <= 500 and _redirect_ok(u) for u in uris):
        return JSONResponse({"error": "invalid_redirect_uri", "error_description": "redirect_uris must be https (or http on localhost)."}, 400)
    method = body.get("token_endpoint_auth_method") or "none"
    if method not in ("none", "client_secret_post", "client_secret_basic"):
        method = "none"
    name = str(body.get("client_name") or "AI assistant")[:200]
    cid = "rfc_" + secrets.token_urlsafe(18)
    secret = "rfs_" + secrets.token_urlsafe(32) if method != "none" else ""
    db.add(OAuthClient(id=cid, name=name, redirect_uris=uris, secret_hash=A.digest(secret) if secret else ""))
    db.commit()
    out = {"client_id": cid, "client_id_issued_at": int(A.now().timestamp()), "client_name": name, "redirect_uris": uris,
           "grant_types": ["authorization_code", "refresh_token"], "response_types": ["code"], "token_endpoint_auth_method": method,
           "scope": "revenueforge"}
    if secret:
        out.update(client_secret=secret, client_secret_expires_at=0)
    return JSONResponse(out, status_code=201)


def _consent_token(params: dict) -> str:
    return jwt.encode({**params, "typ": "mcp_consent", "exp": datetime.now(timezone.utc) + timedelta(minutes=15)},
                      settings.jwt_secret, algorithm="HS256")


def _read_consent(token: str) -> dict:
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(400, "This connection request has expired. Start connecting again from your AI assistant.")
    if p.get("typ") != "mcp_consent":
        raise HTTPException(400, "Not a connection request.")
    return p


@router.get("/oauth/authorize", include_in_schema=False)
def authorize(request: Request, db=Depends(get_db)):
    q = request.query_params
    client = db.get(OAuthClient, q.get("client_id", ""))
    redirect_uri = q.get("redirect_uri", "")
    if not client:
        return JSONResponse({"error": "invalid_client", "error_description": "Unknown client. Remove and add the connector again."}, 400)
    if not redirect_uri and len(client.redirect_uris or []) == 1:
        redirect_uri = client.redirect_uris[0]
    if not _redirect_matches(redirect_uri, client.redirect_uris or []):
        return JSONResponse({"error": "invalid_request", "error_description": "redirect_uri is not registered for this client."}, 400)
    state = q.get("state", "")

    def fail(err: str, desc: str):
        sep = "&" if "?" in redirect_uri else "?"
        return RedirectResponse(redirect_uri + sep + urlencode({"error": err, "error_description": desc, "state": state}), 302)

    if q.get("response_type") != "code":
        return fail("unsupported_response_type", "Only response_type=code is supported.")
    if not q.get("code_challenge") or q.get("code_challenge_method", "plain") != "S256":
        return fail("invalid_request", "PKCE with S256 is required.")
    res = q.get("resource", "")
    if res and res.rstrip("/") != A.resource(request):
        return fail("invalid_target", "This server only issues tokens for its own /mcp endpoint.")
    req = _consent_token({"cid": client.id, "ru": redirect_uri, "st": state, "cc": q["code_challenge"],
                          "sc": q.get("scope", "revenueforge")[:200], "rs": res})
    return RedirectResponse(A.origin(request) + "/connect?" + urlencode({"request": req}), 302)


def _token_error(err: str, desc: str, status: int = 400):
    return JSONResponse({"error": err, "error_description": desc}, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/oauth/token", include_in_schema=False)
async def token(request: Request, db=Depends(get_db)):
    form = await request.form()
    f = {k: str(v) for k, v in form.items()}
    cid, secret = f.get("client_id", ""), f.get("client_secret", "")
    auth = request.headers.get("authorization", "")
    if auth[:6].lower() == "basic ":
        try:
            from urllib.parse import unquote
            u, _, p = base64.b64decode(auth[6:]).decode().partition(":")
            cid, secret = unquote(u), unquote(p)
        except Exception:
            return _token_error("invalid_client", "Bad client credentials.", 401)
    client = db.get(OAuthClient, cid)
    if not client:
        return _token_error("invalid_client", "Unknown client.", 401)
    if client.secret_hash and not secrets.compare_digest(client.secret_hash, A.digest(secret)):
        return _token_error("invalid_client", "Bad client credentials.", 401)
    grant = f.get("grant_type")

    if grant == "authorization_code":
        code = db.get(OAuthCode, A.digest(f.get("code", "")))
        if not code or code.client_id != client.id:
            return _token_error("invalid_grant", "The code is not valid.")
        db.delete(code)  # one use only
        db.commit()
        if A.utc(code.expires_at) < A.now():
            return _token_error("invalid_grant", "The code has expired.")
        if f.get("redirect_uri") and f["redirect_uri"] != code.redirect_uri:
            return _token_error("invalid_grant", "redirect_uri does not match.")
        if not A.pkce_ok(f.get("code_verifier", ""), code.code_challenge):
            return _token_error("invalid_grant", "PKCE check failed.")
        user = db.get(User, code.user_id)
        if not user or not user.is_active:
            return _token_error("invalid_grant", "The account is disabled.")
        out = A.issue_pair(db, user, client.id, client.name, grant_id=secrets.token_hex(16))
        db.commit()
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    if grant == "refresh_token":
        old = A.find(db, f.get("refresh_token", ""), ("refresh",))
        if not old or old.client_id != client.id:
            return _token_error("invalid_grant", "The refresh token is not valid. Connect again.")
        user = db.get(User, old.user_id)
        if not user or not user.is_active or (user.tokens_after and A.utc(old.created_at) < A.utc(user.tokens_after)):
            return _token_error("invalid_grant", "Sign in again to reconnect.")
        old.revoked_at = A.now()  # refresh tokens rotate: the old one stops working now
        out = A.issue_pair(db, user, client.id, client.name, grant_id=old.grant_id)
        db.commit()
        return JSONResponse(out, headers={"Cache-Control": "no-store"})

    return _token_error("unsupported_grant_type", "Use authorization_code or refresh_token.")


@router.post("/oauth/revoke", include_in_schema=False)
async def revoke(request: Request, db=Depends(get_db)):
    form = await request.form()
    t = A.find(db, str(form.get("token", "")), ("access", "refresh"))
    if t:
        A.revoke_grant(db, t.grant_id)
        db.commit()
    return Response(status_code=200)


# =========================================================================== consent screen (the app's /connect page calls these)
class ConsentBody(BaseModel):
    request: str = Field(max_length=4000)
    allow: bool


@router.get("/api/mcp/consent")
def consent_info(request: str, ctx: Ctx = Depends(current_ctx)):
    p = _read_consent(request)
    client = ctx.db.get(OAuthClient, p["cid"])
    if not client:
        raise HTTPException(400, "Unknown assistant. Start connecting again.")
    host = urlparse(p["ru"]).hostname or ""
    return {"client_name": client.name, "redirect_host": host, "loopback": host in ("localhost", "127.0.0.1", "::1"),
            "company": ctx.tenant.name, "user": ctx.user.name or ctx.user.email, "role": ctx.user.role}


@router.post("/api/mcp/consent")
def consent_decide(body: ConsentBody, ctx: Ctx = Depends(current_ctx)):
    p = _read_consent(body.request)
    client = ctx.db.get(OAuthClient, p["cid"])
    if not client or not _redirect_matches(p["ru"], client.redirect_uris or []):
        raise HTTPException(400, "Unknown assistant. Start connecting again.")
    sep = "&" if "?" in p["ru"] else "?"
    if not body.allow:
        return {"redirect": p["ru"] + sep + urlencode({"error": "access_denied", "error_description": "The person declined.", "state": p["st"]})}
    code = secrets.token_urlsafe(32)
    ctx.db.add(OAuthCode(id=A.digest(code), client_id=client.id, user_id=ctx.user.id, tenant_id=ctx.tenant_id, redirect_uri=p["ru"],
                         code_challenge=p["cc"], scope=p["sc"], resource=p.get("rs", ""), expires_at=A.now() + A.CODE_TTL))
    ctx.audit("mcp.connect", client.name)
    ctx.db.commit()
    return {"redirect": p["ru"] + sep + urlencode({"code": code, "state": p["st"]})}


# =========================================================================== Settings: connections and API keys
class KeyBody(BaseModel):
    label: str = Field(default="API key", max_length=80)


@router.get("/api/mcp/connections")
def connections(request: Request, ctx: Ctx = Depends(current_ctx)):
    rows = ctx.db.scalars(select(McpToken).where(McpToken.user_id == ctx.user.id, McpToken.revoked_at.is_(None))
                          .order_by(McpToken.created_at.desc())).all()
    grants: dict[str, dict] = {}
    keys = []
    for t in rows:
        if t.kind == "api_key":
            keys.append({"id": t.id, "label": t.client_name, "hint": t.hint, "created_at": t.created_at, "last_used_at": t.last_used_at})
        elif t.kind == "refresh" and (not t.expires_at or A.utc(t.expires_at) > A.now()):
            g = grants.setdefault(t.grant_id, {"id": t.grant_id, "client": t.client_name, "connected_at": t.created_at, "last_used_at": None})
            g["connected_at"] = min(g["connected_at"], t.created_at, key=lambda d: A.utc(d))
        elif t.kind == "access" and t.grant_id in grants and t.last_used_at:
            g = grants[t.grant_id]
            if not g["last_used_at"] or A.utc(t.last_used_at) > A.utc(g["last_used_at"]):
                g["last_used_at"] = t.last_used_at
    return {"url": A.resource(request), "connections": list(grants.values()), "keys": keys}


@router.post("/api/mcp/keys")
def create_key(body: KeyBody, ctx: Ctx = Depends(current_ctx)):
    n = ctx.db.query(McpToken).filter(McpToken.user_id == ctx.user.id, McpToken.kind == "api_key", McpToken.revoked_at.is_(None)).count()
    if n >= 10:
        raise HTTPException(400, "You have 10 keys already. Revoke one you no longer use.")
    key = A.issue(ctx.db, "api_key", ctx.user, client_name=body.label.strip() or "API key")
    ctx.audit("mcp.key_create", body.label)
    ctx.db.commit()
    return {"key": key}


@router.delete("/api/mcp/connections/{item_id}")
def disconnect(item_id: str, ctx: Ctx = Depends(current_ctx)):
    key = ctx.db.scalar(select(McpToken).where(McpToken.id == item_id, McpToken.user_id == ctx.user.id, McpToken.kind == "api_key"))
    if key:
        key.revoked_at = A.now()
        ctx.audit("mcp.key_revoke", key.client_name)
    else:
        mine = ctx.db.scalar(select(McpToken).where(McpToken.grant_id == item_id, McpToken.user_id == ctx.user.id))
        if not mine or not item_id:
            raise HTTPException(404, "Not found.")
        A.revoke_grant(ctx.db, item_id)
        ctx.audit("mcp.disconnect", mine.client_name)
    ctx.db.commit()
    return {"ok": True}


# =========================================================================== the MCP endpoint (Streamable HTTP, JSON responses)
def _unauthorized(request: Request, desc: str = "Connect RevenueForge to use this server.") -> Response:
    meta = A.origin(request) + "/.well-known/oauth-protected-resource/mcp"
    return JSONResponse({"error": "invalid_token", "error_description": desc}, status_code=401,
                        headers={"WWW-Authenticate": f'Bearer resource_metadata="{meta}", scope="revenueforge"'})


@router.get("/mcp", include_in_schema=False)
@router.delete("/mcp", include_in_schema=False)
def mcp_get():
    # No server-initiated stream and no sessions: every call is a plain POST.
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post("/mcp", include_in_schema=False)
async def mcp_post(request: Request, db=Depends(get_db)):
    auth = request.headers.get("authorization", "")
    bearer = auth[7:].strip() if auth[:7].lower() == "bearer " else (request.headers.get("x-api-key") or "").strip()
    who = A.authenticate(db, bearer) if bearer else None
    if not who:
        return _unauthorized(request, "The access token is missing, expired or revoked." if bearer else "Connect RevenueForge to use this server.")
    user, tenant, tok = who
    try:
        msg = await request.json()
    except Exception:
        return JSONResponse(_err(None, -32700, "Parse error"), status_code=400)
    session = Session(request, user, tenant, tok)
    if isinstance(msg, list):  # older clients may batch
        out = [r for r in [await _handle(session, m) for m in msg] if r is not None]
        return JSONResponse(out) if out else Response(status_code=202)
    res = await _handle(session, msg)
    return JSONResponse(res) if res is not None else Response(status_code=202)


def _err(mid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


async def _handle(s: "Session", m: Any) -> dict | None:
    if not isinstance(m, dict) or m.get("jsonrpc") != "2.0" or not isinstance(m.get("method"), str):
        return _err(m.get("id") if isinstance(m, dict) else None, -32600, "Invalid request")
    mid, method, params = m.get("id"), m["method"], m.get("params") or {}
    if "id" not in m:  # a notification (initialized, cancelled, ...): nothing to answer
        return None
    if method == "initialize":
        want = params.get("protocolVersion")
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "protocolVersion": want if want in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[1],
            "capabilities": {"tools": {"listChanged": False}}, "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": mid, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": [t["spec"] for t in TOOLS.values()]}}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        tool = TOOLS.get(name)
        if not tool:
            return _err(mid, -32602, f"Unknown tool: {name}")
        if not isinstance(args, dict):
            return _err(mid, -32602, "arguments must be an object")
        try:
            data = await tool["fn"](s, args)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": _text(data)}], "isError": False}}
        except ToolError as e:
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": str(e)}], "isError": True}}
        except Exception:
            log.exception("MCP tool %s failed", name)
            return {"jsonrpc": "2.0", "id": mid, "result": {"content": [{"type": "text", "text": "RevenueForge hit an error running this tool. Try again, or open the app."}], "isError": True}}
    if method in ("resources/list", "prompts/list", "resources/templates/list"):
        return {"jsonrpc": "2.0", "id": mid, "result": {method.split("/")[0] if "templates" not in method else "resourceTemplates": []}}
    return _err(mid, -32601, f"Method not found: {method}")


def _text(data: Any) -> str:
    return data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str, indent=1)


# =========================================================================== tools
class ToolError(Exception):
    pass


class Session:
    """One MCP call: the connected person, and a way to call the app's own API as them."""

    def __init__(self, request: Request, user: User, tenant, tok: McpToken):
        self.request, self.user, self.tenant, self.tok = request, user, tenant, tok
        self.origin = A.origin(request)

    async def api(self, method: str, path: str, **kw) -> Any:
        from ..main import app  # the same FastAPI app, called in-process: same checks as the web app
        headers = {"authorization": f"Bearer {create_token(self.user)}", "user-agent": f"RevenueForge-MCP ({self.tok.client_name})"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://internal", timeout=120) as c:
            r = await c.request(method, path, headers=headers, **kw)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:
                detail = None
            raise ToolError(detail if isinstance(detail, str) else f"RevenueForge returned an error ({r.status_code}).")
        return r.json()

    def link(self, path: str) -> str:
        return self.origin + path


TOOLS: dict[str, dict] = {}


def tool(name: str, title: str, description: str, props: dict, required: list[str] | None = None, read_only: bool = True):
    def deco(fn):
        TOOLS[name] = {"fn": fn, "spec": {
            "name": name, "title": title, "description": description,
            "inputSchema": {"type": "object", "properties": props, "required": required or [], "additionalProperties": False},
            "annotations": {"title": title, "readOnlyHint": read_only, "destructiveHint": False, "idempotentHint": read_only,
                            "openWorldHint": False}}}
        return fn
    return deco


def _int(v, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def _short(s: Any, n: int = 400) -> str:
    s = str(s or "")
    return s if len(s) <= n else s[: n - 1] + "…"


def _deal_row(s: Session, d: dict) -> dict:
    return {"deal_id": d["id"], "name": d["name"], "client": d["client"], "status": d["status"], "verdict": d.get("verdict"),
            "readiness_today": d.get("readiness"), "readiness_with_plan": d.get("mitigated_readiness"), "coverage_pct": d.get("coverage_pct"),
            "due_date": d.get("due_date"), "value": d.get("value"), "currency": d.get("value_currency") or d.get("currency"),
            "margin_pct": d.get("margin_pct"), "owner": (d.get("owner") or {}).get("name"), "requirements": d.get("requirement_count"),
            "app_url": s.link(f"/app/deals/{d['id']}")}


@tool("list_deals", "List deals",
      "List the bids (deals) in the person's RevenueForge workspace with status, bid verdict, readiness, due date and value. "
      "Filter by status (processing, in_review, submitted, won, lost, failed) or a word in the deal or client name.",
      {"status": {"type": "string", "description": "Only deals with this status."},
       "search": {"type": "string", "description": "Word to look for in the deal or client name."},
       "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25}})
async def list_deals(s: Session, a: dict):
    rows = await s.api("GET", "/api/deals")
    if a.get("status"):
        rows = [d for d in rows if d["status"] == a["status"]]
    if a.get("search"):
        q = str(a["search"]).lower()
        rows = [d for d in rows if q in (d["name"] or "").lower() or q in (d["client"] or "").lower()]
    lim = _int(a.get("limit"), 25, 1, 100)
    return {"total": len(rows), "deals": [_deal_row(s, d) for d in rows[:lim]]}


@tool("get_deal", "Get deal assessment",
      "Full assessment of one deal: bid verdict and why, readiness today and with a mitigation plan, requirement match counts, "
      "the biggest missing technologies with the recommended fix (hire, partner, certify, upskill), estimated team and price.",
      {"deal_id": {"type": "string", "description": "From list_deals."}}, ["deal_id"])
async def get_deal(s: Session, a: dict):
    did = str(a.get("deal_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", did):
        raise ToolError("Give a deal_id from list_deals.")
    d = await s.api("GET", f"/api/deals/{did}")
    out = _deal_row(s, d)
    out.update(industry=d.get("industry"), region=d.get("region"), engagement_type=d.get("engagement_type"), verdict_reason=d.get("verdict_reason"),
               stages={st["stage"]: st["status"] for st in d.get("stages", [])}, open_notes=d.get("open_notes"))
    if d["status"] == "processing":
        out["note"] = f"Still being analysed ({(d.get('progress') or {}).get('message', '')}). Check again in a minute."
        return out
    gaps = (await s.api("GET", f"/api/deals/{did}/stages/gaps")).get("data") or {}
    out["match_counts"] = gaps.get("counts")
    out["high_risk_gaps"] = gaps.get("high_risk")
    out["risk_counts"] = gaps.get("risk_counts")
    out["top_missing"] = [{k: t.get(k) for k in ("technology", "requirements", "recommendation")} for t in (gaps.get("top_missing") or [])[:10]]
    e = (await s.api("GET", f"/api/deals/{did}/stages/estimation")).get("data") or {}
    if e:
        out["team"] = {k: e.get(k) for k in ("headcount", "fte", "duration_months", "build_months", "run_months", "total_person_days", "unfilled_roles")
                       if e.get(k) is not None}
        out["team"]["roles"] = [{k: t.get(k) for k in ("role", "headcount", "location", "phase") if t.get(k) not in (None, "")}
                                for t in (e.get("team") or [])[:25]]
    pr = (await s.api("GET", f"/api/deals/{did}/stages/pricing")).get("data") or {}
    fx = pr.get("fx_to_rfp") or 1
    if pr.get("scenarios"):
        out["price_scenarios"] = [{"name": x.get("name"), "price": round((x.get("price") or 0) * fx, 2), "margin_pct": x.get("margin_pct")}
                                  for x in pr["scenarios"]]
        out["price_currency"] = pr.get("rfp_currency") or pr.get("currency")
        out["selected_scenario"] = pr.get("selected", "Target")
    return out


@tool("get_requirements", "Get deal requirements",
      "The requirements read from a deal's RFP and how well the company's library meets each one (strong, partial, gap, confirm). "
      "Use show='gaps' for only the unmet ones.",
      {"deal_id": {"type": "string"},
       "show": {"type": "string", "enum": ["all", "gaps", "mandatory_gaps"], "default": "gaps"},
       "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50}}, ["deal_id"])
async def get_requirements(s: Session, a: dict):
    did = str(a.get("deal_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", did):
        raise ToolError("Give a deal_id from list_deals.")
    rows = await s.api("GET", f"/api/deals/{did}/requirements")
    show = a.get("show") or "gaps"
    if show != "all":
        rows = [r for r in rows if r.get("match_status") in ("gap", "partial")]
    if show == "mandatory_gaps":
        rows = [r for r in rows if str(r.get("priority", "")).lower() in ("mandatory", "must", "high", "critical")]
    lim = _int(a.get("limit"), 50, 1, 200)
    return {"total": len(rows), "requirements": [{
        "code": r.get("source_ref") or r.get("code"), "text": _short(r.get("text"), 350), "category": r.get("category"),
        "priority": r.get("priority"), "match": r.get("match_status"), "technologies": r.get("technologies"),
        "gap_risk": (r.get("gap") or {}).get("risk"), "recommended_fix": (r.get("gap") or {}).get("recommended"),
        "response": _short(r.get("response"), 300) or None} for r in rows[:lim]]}


SECTIONS = {"skills": "people", "capabilities": "capabilities", "certifications": "certifications",
            "case_studies": "case studies", "accelerators": "accelerators", "rates": "rate card"}


def _score(row: dict, words: list[str]) -> int:
    hay = json.dumps(row, default=str).lower()
    return sum(1 for w in words if w in hay)


def _slim(kind: str, r: dict) -> dict:
    drop = {"id", "name", "day_cost", "created_at", "updated_at", "source_doc", "document_id", "embedding", "meta"}
    out = {k: v for k, v in r.items() if k not in drop and v not in (None, "", [], {})}
    if kind == "skills":
        out.pop("name", None)  # people are shown by employee code, as in the app
    return out


@tool("search_knowledge", "Search company knowledge",
      "Search the company's knowledge library: people and their skills (by employee code, with availability), capabilities, "
      "certifications, case studies, accelerators and the rate card. Matches any of the words given.",
      {"query": {"type": "string", "description": "Words to look for, e.g. 'Microsoft Fabric DP-600' or 'TIBCO BW6 upgrade'."},
       "section": {"type": "string", "enum": list(SECTIONS), "description": "Only this part of the library."},
       "available_only": {"type": "boolean", "description": "People only: at least 50% available.", "default": False},
       "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10}}, ["query"])
async def search_knowledge(s: Session, a: dict):
    words = [w for w in re.findall(r"[\w.+#-]{2,}", str(a.get("query", "")).lower()) if w not in {"and", "or", "the", "with", "for"}]
    if not words:
        raise ToolError("Give a few words to search for.")
    kinds = [a["section"]] if a.get("section") in SECTIONS else list(SECTIONS)
    lim = _int(a.get("limit"), 10, 1, 50)
    out = {}
    for k in kinds:
        rows = await s.api("GET", f"/api/library/{k}")
        if k == "skills" and a.get("available_only"):
            rows = [r for r in rows if (r.get("availability") or 0) >= 50]
        hits = sorted(((sc, r) for r in rows if (sc := _score(r, words))), key=lambda x: -x[0])
        if hits:
            out[SECTIONS[k]] = {"matches": len(hits), "top": [_slim(k, r) for _, r in hits[:lim]]}
    return out or {"matches": 0, "note": "Nothing in the library matches. The library may be missing this, which is worth saying plainly."}


@tool("company_overview", "Company overview",
      "The connected company's profile and what its knowledge library holds (counts per section and whether setup is complete).",
      {})
async def company_overview(s: Session, a: dict):
    c = await s.api("GET", "/api/company")
    ob = c.get("onboarding") or {}
    return {"company": c.get("name"), "industry": c.get("industry"), "headquarters": c.get("headquarters"), "about": _short(c.get("about"), 800),
            "currency": c.get("currency"), "library_counts": ob.get("counts"), "setup_complete": ob.get("complete"),
            "connected_as": {"name": s.user.name, "role": s.user.role}, "app_url": s.link("/app")}


@tool("pipeline_summary", "Pipeline summary",
      "Headline numbers for the bid pipeline: deal counts by status, pipeline and weighted value, average readiness, win rate, "
      "people and bench, and the technologies most often missing across deals.",
      {})
async def pipeline_summary(s: Session, a: dict):
    d = await s.api("GET", "/api/dashboard")
    return {"kpis": d.get("kpis"), "status_counts": d.get("status_counts"), "most_missing_skills": d.get("skill_gaps"),
            "most_requested_capabilities": d.get("capability_demand")}


@tool("find_opportunities", "Find tender opportunities",
      "Open public tenders from the opportunity radar, scored for fit against the company's library.",
      {"search": {"type": "string"}, "min_score": {"type": "integer", "minimum": 0, "maximum": 100, "default": 50},
       "due_within_days": {"type": "integer", "minimum": 0, "maximum": 365},
       "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 15}})
async def find_opportunities(s: Session, a: dict):
    params = {"q": a.get("search") or "", "min_score": _int(a.get("min_score"), 50, 0, 100), "status": "active",
              "limit": _int(a.get("limit"), 15, 1, 50)}
    if a.get("due_within_days"):
        params["due_days"] = _int(a["due_within_days"], 0, 0, 365)
    r = await s.api("GET", "/api/radar", params=params)
    items = [{k: t.get(k) for k in ("id", "title", "buyer", "country", "deadline", "value", "currency", "score", "band", "top_match",
                                    "missing_standards", "summary", "url", "source_name") if t.get(k) not in (None, "", [])}
             for t in r.get("items", [])]
    return {"total": r.get("total"), "opportunities": items, "app_url": s.link("/app/opportunities")}


@tool("ask_workspace", "Ask about the workspace",
      "Ask RevenueForge's own assistant (Maahi) a question answered only from this company's deals and library, "
      "e.g. 'which deals are blocked on Apigee skills?'. Uses the company's configured AI.",
      {"question": {"type": "string", "maxLength": 4000}}, ["question"])
async def ask_workspace(s: Session, a: dict):
    q = str(a.get("question", "")).strip()
    if not q:
        raise ToolError("Ask a question.")
    r = await s.api("POST", "/api/assistant/workspace", json={"messages": [{"role": "user", "content": q[:4000]}]})
    return r.get("answer", "")


ENGAGEMENTS = ["managed_services", "build_run", "implementation", "product", "consulting"]


@tool("create_deal", "Create a deal from an RFP",
      "Start a new deal by giving RevenueForge an RFP. Pass the RFP's full text (rfp_text), or a file as base64 (file_base64 with "
      "file_name: PDF, Word, Excel, PowerPoint, CSV or text). Analysis runs in the background for a few minutes; check it with "
      "get_deal. Needs the Presales or Admin role. Client names are masked by default.",
      {"name": {"type": "string", "description": "Deal name, e.g. 'Fabric data platform - Harbourline'.", "maxLength": 200},
       "client_name": {"type": "string", "maxLength": 200},
       "rfp_text": {"type": "string", "description": "The RFP's text.", "maxLength": 400000},
       "file_base64": {"type": "string", "description": "The RFP file, base64-encoded (at most about 15 MB)."},
       "file_name": {"type": "string", "description": "File name with extension, when file_base64 is used."},
       "confidential": {"type": "boolean", "default": True, "description": "Mask the client's name as an alias in the app and in documents."},
       "engagement_type": {"type": "string", "enum": ENGAGEMENTS},
       "acknowledge_shared_ai": {"type": "boolean", "default": False,
                                 "description": "Only set true after the person agrees: on servers using a free AI tier, the RFP text may be used by that AI provider."}},
      ["name"], read_only=False)
async def create_deal(s: Session, a: dict):
    if a.get("file_base64"):
        fname = re.sub(r"[^\w .()-]", "_", str(a.get("file_name") or ""))[:120]
        if not re.search(r"\.(pdf|docx|xlsx|xlsm|csv|pptx|txt|md)$", fname, re.I):
            raise ToolError("file_name must end in .pdf, .docx, .xlsx, .csv, .pptx, .txt or .md.")
        try:
            data = base64.b64decode(str(a["file_base64"]), validate=False)
        except Exception:
            raise ToolError("file_base64 is not valid base64.")
        if len(data) > 15 * 1024 * 1024:
            raise ToolError("The file is over 15 MB. Upload it in the app instead.")
    elif (a.get("rfp_text") or "").strip():
        if len(a["rfp_text"].strip()) < 200:
            raise ToolError("That is too short to be an RFP. Pass the full text.")
        data, fname = a["rfp_text"].encode("utf-8"), "rfp.txt"
    else:
        raise ToolError("Pass rfp_text or file_base64.")
    form = {"name": str(a.get("name") or "")[:200], "client_name": str(a.get("client_name") or "")[:200],
            "confidential": "true" if a.get("confidential", True) else "false",
            "engagement_type": a.get("engagement_type") if a.get("engagement_type") in ENGAGEMENTS else "",
            "ai_ack": "true" if a.get("acknowledge_shared_ai") else "false"}
    try:
        d = await s.api("POST", "/api/deals", data=form, files={"file": (fname, data)})
    except ToolError as e:
        if "free" in str(e).lower() or "tier" in str(e).lower():
            raise ToolError(f"{e} Ask the person whether that is OK; if they agree, call again with acknowledge_shared_ai=true.")
        raise
    return {"deal_id": d["id"], "name": d["name"], "status": d["status"], "app_url": s.link(f"/app/deals/{d['id']}"),
            "next": "Analysis is running. Call get_deal with this deal_id in a minute or two for the verdict."}


@tool("list_projects", "List delivery projects",
      "Projects being delivered after a win: status, health (with the reasons), milestones done and late, contract value, "
      "invoiced, paid and overdue amounts, and the next milestone.",
      {"status": {"type": "string", "enum": ["planning", "active", "on_hold", "completed", "cancelled"]},
       "health": {"type": "string", "enum": ["green", "amber", "red", "closed"]}})
async def list_projects(s: Session, a: dict):
    r = await s.api("GET", "/api/projects")
    rows = r.get("projects", [])
    if a.get("status"):
        rows = [p for p in rows if p["status"] == a["status"]]
    if a.get("health"):
        rows = [p for p in rows if p["summary"]["health"] == a["health"]]
    out = [{"project_id": p["id"], "name": p["name"], "client": p["client"], "status": p["status"], "health": p["summary"]["health"],
            "health_reasons": p["summary"]["health_reasons"], "milestones": p["summary"]["milestones"], "next_milestone": p["summary"]["next_milestone"],
            "currency": p["currency"], **{k: p["summary"][k] for k in ("value_total", "invoiced", "paid", "outstanding", "overdue", "burn_pct")},
            "app_url": s.link(f"/app/projects/{p['id']}")} for p in rows]
    return {"total": len(out), "projects": out,
            "won_deals_not_started": [{"deal_id": x["deal_id"], "name": x["name"], "client": x["client"]} for x in r.get("ready", [])]}


@tool("get_project", "Get a delivery project",
      "Everything about one project: health and why, milestones, team, invoices, costs, change requests, risks, issues, SLA months "
      "and the latest status reports, plus what the bid promised.",
      {"project_id": {"type": "string", "description": "From list_projects."}}, ["project_id"])
async def get_project(s: Session, a: dict):
    pid = str(a.get("project_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", pid):
        raise ToolError("Give a project_id from list_projects.")
    p = await s.api("GET", f"/api/projects/{pid}")
    groups: dict[str, list] = {}
    for i in p.get("items", []):
        row = {k: i[k] for k in ("title", "status", "owner", "due_date", "done_date", "amount", "late") if i.get(k) not in (None, "", 0, False)}
        row.update({k: v for k, v in (i.get("data") or {}).items() if v not in (None, "")})
        groups.setdefault(i["kind"], []).append(row)
    updates = sorted(groups.pop("update", []), key=lambda u: u.get("due_date", ""), reverse=True)
    return {"name": p["name"], "client": p["client"], "status": p["status"], "currency": p["currency"], "start": p["start_date"], "end": p["end_date"],
            "manager": (p.get("manager") or {}).get("name"), "summary": p["summary"], "from_the_bid": p.get("bid"),
            "milestones": groups.get("milestone", []), "team": groups.get("member", [])[:40], "invoices": groups.get("invoice", []),
            "costs": groups.get("cost", [])[:40], "change_requests": groups.get("change", []), "risks": groups.get("risk", []),
            "issues": groups.get("issue", []), "sla_months": groups.get("sla", [])[-12:], "status_reports": updates[:5],
            "app_url": s.link(f"/app/projects/{pid}")}


@tool("client_360", "Client 360",
      "One client across bids and delivery: bids won, lost and open, win rate, projects and their health, contracted, paid, "
      "outstanding and overdue amounts, and a timeline. Without a client, lists every client with the headline numbers.",
      {"client": {"type": "string", "description": "Client name (or alias, for confidential deals). Leave out to list all clients."}})
async def client_360(s: Session, a: dict):
    rows = await s.api("GET", "/api/clients")
    q = str(a.get("client") or "").strip().lower()
    if not q:
        return {"clients": [{k: c[k] for k in ("name", "deals", "win_rate", "projects", "contracted", "outstanding", "overdue", "health")} for c in rows]}
    hit = next((c for c in rows if c["name"].lower() == q), None) or next((c for c in rows if q in c["name"].lower()), None)
    if not hit:
        raise ToolError("No client by that name. Call client_360 without a client to see the list.")
    c = await s.api("GET", f"/api/clients/{hit['key']}")
    c.pop("key", None)
    c["timeline"] = [{"at": e["at"], "what": e["text"]} for e in c.get("timeline", [])[:25]]
    c["app_url"] = s.link(f"/app/clients/{hit['key']}")
    return c
