from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import apply_ai_settings, settings
from ..db import get_db
from ..models import Tenant, User
from ..security import Ctx, create_token, current_ctx, hash_password, require_roles, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

ROLES = ["admin", "presales", "architect", "finance", "delivery", "viewer"]
DEFAULT_SETTINGS = {"target_margin": 28, "min_margin": 18, "travel_pct": 6, "hide_employee_names": True, "default_confidential": True}


class RegisterIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    industry: str = ""
    website: str = ""
    headquarters: str = ""
    name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class InviteIn(BaseModel):
    name: str
    email: EmailStr
    role: str = "presales"
    password: str = ""  # empty: the person signs in with Google only


class AIConfigIn(BaseModel):
    provider: str = "none"
    api_key: str = ""
    model: str = ""
    embed_model: str = "gemini-embedding-001"
    rpm: int = 8
    paid: bool = False


class GoogleIn(BaseModel):
    credential: str = Field(min_length=20)
    company_name: str = ""
    industry: str = ""
    headquarters: str = ""


def user_out(u: User, t: Tenant) -> dict:
    return {"id": u.id, "name": u.name, "email": u.email, "role": u.role,
            "tenant": {"id": t.id, "name": t.name, "slug": t.slug, "onboarding": t.onboarding or {}}}


def _slug(db: Session, name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "company"
    slug, i = base, 1
    while db.scalar(select(func.count()).select_from(Tenant).where(Tenant.slug == slug)):
        i += 1
        slug = f"{base}-{i}"
    return slug


def _unusable_password() -> str:
    """For accounts that only sign in with Google: a hash no typed password can ever match."""
    return hash_password(secrets.token_urlsafe(48))


def create_tenant(db: Session, data: RegisterIn) -> tuple[Tenant, User]:
    if db.scalar(select(User).where(func.lower(User.email) == data.email.lower())):
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")
    t = Tenant(name=data.company_name.strip(), slug=_slug(db, data.company_name), industry=data.industry, website=data.website,
               headquarters=data.headquarters, settings=dict(DEFAULT_SETTINGS), onboarding={})
    db.add(t)
    db.flush()
    u = User(tenant_id=t.id, email=data.email.lower(), name=data.name.strip(), role="admin", password_hash=hash_password(data.password))
    db.add(u)
    db.commit()
    return t, u


@router.post("/register")
def register(data: RegisterIn, db: Session = Depends(get_db)):
    t, u = create_tenant(db, data)
    return {"token": create_token(u), "user": user_out(u, t)}


@router.post("/login")
def login(data: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(func.lower(User.email) == data.email.lower()))
    if not u or not verify_password(data.password, u.password_hash):
        raise HTTPException(401, "Email or password is incorrect.")
    if not u.is_active:
        raise HTTPException(403, "This account is disabled. Ask your company admin to re-enable it.")
    return {"token": create_token(u), "user": user_out(u, db.get(Tenant, u.tenant_id))}


@router.get("/config")
def auth_config():
    """What the sign-in page offers. The client ID is public by design (it is embedded in every Google button)."""
    from ..services import llm
    notice = settings.public_notice
    if notice.lower() in ("off", "none", "false", "0"):
        notice = ""
    elif not notice and llm.provider_name() == "gemini" and not settings.llm_paid:
        notice = ("Test version: use sample or dummy documents only. The AI runs on a free Google key, "
                  "so please don't upload confidential client RFPs or company data.")
    return {"google_client_id": settings.google_client_id or None, "google_domains": settings.google_allowed_domains, "notice": notice}


@router.get("/ai-config")
def get_ai_config():
    from ..services import llm
    provider = llm.provider_name()
    keys = {
        "gemini": settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "azure": settings.azure_api_key,
    }
    api_key = keys.get(provider, "")
    return {
        "provider": provider,
        "api_key_present": bool(api_key),
        "model": {
            "gemini": settings.gemini_model or "auto (newest Flash)",
            "anthropic": settings.anthropic_model,
            "openai": settings.openai_model,
            "azure": settings.azure_deployment,
        }.get(provider, ""),
        "embed_model": settings.gemini_embed_model,
        "rpm": settings.llm_rpm,
        "paid": settings.llm_paid,
    }


@router.put("/ai-config")
def save_ai_config(data: AIConfigIn, ctx: Ctx = Depends(require_roles())):
    res = apply_ai_settings(data.model_dump())
    ctx.audit("ai.config.update", data.provider)
    return res


def verify_google(credential: str) -> dict:
    if not settings.google_client_id:
        raise HTTPException(400, "Google sign-in isn't set up on this server. Add GOOGLE_CLIENT_ID to backend/.env.")
    try:
        from google.auth.transport import requests as grequests
        from google.oauth2 import id_token
        info = id_token.verify_oauth2_token(credential, grequests.Request(), settings.google_client_id, clock_skew_in_seconds=10)
    except ValueError:
        raise HTTPException(401, "Google sign-in couldn't be verified. Try again.")
    except Exception:
        raise HTTPException(503, "Couldn't reach Google to verify the sign-in. Check the internet connection and try again.")
    if info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise HTTPException(401, "Google sign-in couldn't be verified. Try again.")
    if not info.get("email") or not info.get("email_verified"):
        raise HTTPException(401, "This Google account has no verified email address.")
    email = info["email"].lower()
    if settings.google_allowed_domains and email.split("@")[-1] not in settings.google_allowed_domains:
        raise HTTPException(403, f"Sign in with your {' or '.join('@' + d for d in settings.google_allowed_domains)} Google account.")
    return {"sub": info["sub"], "email": email, "name": info.get("name") or email.split("@")[0]}


@router.post("/google")
def google_sign_in(data: GoogleIn, db: Session = Depends(get_db)):
    """Sign in with a Google ID token. Existing accounts match on Google id, then on verified email.
    A new person gets {needs_company: true} back, and is asked for a company name to create a workspace."""
    g = verify_google(data.credential)
    u = db.scalar(select(User).where(User.google_sub == g["sub"])) or db.scalar(select(User).where(func.lower(User.email) == g["email"]))
    if u:
        if not u.is_active:
            raise HTTPException(403, "This account is disabled. Ask your company admin to re-enable it.")
        if not u.google_sub:
            u.google_sub = g["sub"]
            db.commit()
        return {"token": create_token(u), "user": user_out(u, db.get(Tenant, u.tenant_id))}
    if not data.company_name.strip():
        return {"needs_company": True, "email": g["email"], "name": g["name"]}
    reg = RegisterIn(company_name=data.company_name, industry=data.industry, headquarters=data.headquarters, name=g["name"], email=g["email"],
                     password="x" * 8)
    t, u = create_tenant(db, reg)
    u.password_hash, u.google_sub = _unusable_password(), g["sub"]
    db.commit()
    return {"token": create_token(u), "user": user_out(u, t)}


@router.get("/me")
def me(ctx: Ctx = Depends(current_ctx)):
    return user_out(ctx.user, ctx.tenant)


@router.get("/users")
def list_users(ctx: Ctx = Depends(current_ctx)):
    rows = ctx.db.scalars(select(User).where(User.tenant_id == ctx.tenant_id).order_by(User.created_at)).all()
    return [{"id": u.id, "name": u.name, "email": u.email, "role": u.role, "active": u.is_active} for u in rows]


@router.post("/users")
def invite(data: InviteIn, ctx: Ctx = Depends(require_roles())):
    if data.role not in ROLES:
        raise HTTPException(400, f"Role must be one of: {', '.join(ROLES)}.")
    if ctx.db.scalar(select(User).where(func.lower(User.email) == data.email.lower())):
        raise HTTPException(409, "A user with this email already exists.")
    if data.password and len(data.password) < 8:
        raise HTTPException(400, "Passwords need at least 8 characters. Leave it empty if they'll sign in with Google.")
    u = User(tenant_id=ctx.tenant_id, email=data.email.lower(), name=data.name, role=data.role,
             password_hash=hash_password(data.password) if data.password else _unusable_password())
    ctx.db.add(u)
    ctx.audit("user.invite", data.email, role=data.role)
    ctx.db.commit()
    return {"id": u.id}


@router.patch("/users/{uid}")
def update_user(uid: str, body: dict, ctx: Ctx = Depends(require_roles())):
    u = ctx.db.get(User, uid)
    if not u or u.tenant_id != ctx.tenant_id:
        raise HTTPException(404, "User not found.")
    if "role" in body:
        if body["role"] not in ROLES:
            raise HTTPException(400, "Unknown role.")
        u.role = body["role"]
    if "active" in body:
        if u.id == ctx.user.id:
            raise HTTPException(400, "You can't disable your own account.")
        u.is_active = bool(body["active"])
    ctx.db.commit()
    return {"ok": True}
