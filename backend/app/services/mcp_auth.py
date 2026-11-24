"""Tokens for AI assistants (Claude, Glean, ...) that reach a workspace through the MCP endpoint.

Two ways in, both ending in the same opaque bearer token checked on every /mcp call:
  * OAuth 2.1 (authorization code + PKCE S256, dynamic client registration): the person signs in to RevenueForge and presses
    Allow. Access tokens live an hour; refresh tokens rotate on every use and live 60 days.
  * Personal API keys, made in Settings and pasted into a tool that takes a fixed key (Glean "API key", Claude Code headers).
Only SHA-256 hashes are stored. A token always acts as the person who created it, with that person's role, so the
assistant can see and do exactly what that person can in the app and nothing more.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import McpToken, Tenant, User

ACCESS_TTL = timedelta(hours=1)
REFRESH_TTL = timedelta(days=60)
CODE_TTL = timedelta(minutes=5)
PREFIX = {"access": "rfa_", "refresh": "rfr_", "api_key": "rfk_"}


def now() -> datetime:
    return datetime.now(timezone.utc)


def utc(d: datetime | None) -> datetime | None:
    return None if d is None else (d if d.tzinfo else d.replace(tzinfo=timezone.utc))


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def origin(request: Request) -> str:
    """The public address of this server, as the assistant sees it (behind Azure's front end the app itself sees http)."""
    url = (settings.app_url or "").rstrip("/")
    if url and not url.startswith(("http://localhost", "http://127.0.0.1")):
        return url
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    if not host.startswith(("localhost", "127.0.0.1")):
        proto = "https"  # anything public is served over HTTPS; the hop from the front end to the app is not
    return f"{proto}://{host}"


def resource(request: Request) -> str:
    return origin(request) + "/mcp"


def pkce_ok(verifier: str, challenge: str) -> bool:
    if not verifier or not 43 <= len(verifier) <= 128:
        return False
    calc = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(calc, challenge)


def issue(db: Session, kind: str, user: User, *, client_id: str = "", client_name: str = "", grant_id: str = "",
          ttl: timedelta | None = None) -> str:
    token = PREFIX[kind] + secrets.token_urlsafe(32)
    db.add(McpToken(token_hash=digest(token), kind=kind, user_id=user.id, tenant_id=user.tenant_id, client_id=client_id,
                    client_name=client_name[:200], grant_id=grant_id, hint=token[-4:],
                    expires_at=(now() + ttl) if ttl else None))
    return token


def issue_pair(db: Session, user: User, client_id: str, client_name: str, grant_id: str) -> dict:
    access = issue(db, "access", user, client_id=client_id, client_name=client_name, grant_id=grant_id, ttl=ACCESS_TTL)
    refresh = issue(db, "refresh", user, client_id=client_id, client_name=client_name, grant_id=grant_id, ttl=REFRESH_TTL)
    return {"access_token": access, "token_type": "Bearer", "expires_in": int(ACCESS_TTL.total_seconds()),
            "refresh_token": refresh, "scope": "revenueforge"}


def find(db: Session, token: str, kinds: tuple[str, ...]) -> McpToken | None:
    if not token or len(token) > 200:
        return None
    t = db.scalar(select(McpToken).where(McpToken.token_hash == digest(token)))
    if not t or t.kind not in kinds or t.revoked_at is not None:
        return None
    if t.expires_at and utc(t.expires_at) < now():
        return None
    return t


def revoke_grant(db: Session, grant_id: str) -> None:
    if grant_id:
        db.execute(update(McpToken).where(McpToken.grant_id == grant_id, McpToken.revoked_at.is_(None)).values(revoked_at=now()))


def authenticate(db: Session, bearer: str) -> tuple[User, Tenant, McpToken] | None:
    """The person behind an access token or API key, if it is valid and their account and company are open."""
    t = find(db, bearer, ("access", "api_key"))
    if not t:
        return None
    user = db.get(User, t.user_id)
    tenant = db.get(Tenant, t.tenant_id)
    if not user or not user.is_active or user.tenant_id != t.tenant_id or not tenant or tenant.suspended_at:
        return None
    if user.tokens_after and utc(t.created_at) < utc(user.tokens_after):
        return None  # "sign out everywhere" also ends assistant connections made before it
    if not t.last_used_at or (now() - utc(t.last_used_at)).total_seconds() > 300:
        t.last_used_at = now()
        db.commit()
    return user, tenant, t
