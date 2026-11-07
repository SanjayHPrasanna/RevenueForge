from __future__ import annotations

import base64
import hashlib
import hmac
import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db
from .models import AuditLog, Tenant, User

_ITER = 260_000
bearer = HTTPBearer(auto_error=False)


def hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, _ITER)
    return f"pbkdf2${_ITER}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(pw: str, stored: str) -> bool:
    try:
        _, it, salt, dk = stored.split("$")
        calc = hashlib.pbkdf2_hmac("sha256", pw.encode(), base64.b64decode(salt), int(it))
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except Exception:
        return False


def create_token(user: User) -> str:
    payload = {
        "sub": user.id,
        "tid": user.tenant_id,
        "role": user.role,
        "exp": datetime.now(timezone.utc) + timedelta(hours=settings.jwt_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


class Ctx:
    """Request context: the signed-in user and their tenant. All data access goes through ctx.tenant_id."""

    def __init__(self, user: User, tenant: Tenant, db: Session):
        self.user = user
        self.tenant = tenant
        self.db = db

    @property
    def tenant_id(self) -> str:
        return self.tenant.id

    def audit(self, action: str, target: str = "", **detail):
        self.db.add(AuditLog(tenant_id=self.tenant_id, user=self.user.email, action=action, target=target, detail=detail))


def current_ctx(creds: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> Ctx:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    try:
        payload = jwt.decode(creds.credentials, settings.jwt_secret, algorithms=["HS256"], options={"require": ["exp", "sub", "tid"]})
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Your session expired. Sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session. Sign in again.")
    user = db.get(User, payload["sub"])
    if not user or not user.is_active or user.tenant_id != payload.get("tid"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account not found or disabled.")
    tenant = db.get(Tenant, user.tenant_id)
    return Ctx(user, tenant, db)


def require_roles(*roles: str):
    def dep(ctx: Ctx = Depends(current_ctx)) -> Ctx:
        if ctx.user.role != "admin" and ctx.user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"This action needs one of these roles: {', '.join(('admin',) + roles)}.")
        return ctx

    return dep


def client_ip(request) -> str:
    """The caller's address for rate limits. Azure's front end appends the real address as the LAST X-Forwarded-For entry
    (sometimes with a port); anything to its left was sent by the caller and can be made up, so it isn't trusted."""
    xff = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",") if p.strip()]
    ip = xff[-1] if xff else (request.client.host if request.client else "")
    if ip.count(":") == 1:  # "1.2.3.4:5678"
        ip = ip.split(":")[0]
    return ip.strip("[]") or "unknown"
