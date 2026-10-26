"""A company's own AI provider and key (Settings → Your company's AI).

Anyone in the company can choose a provider and paste a key; it then applies to that company only (its deals,
imports, videos and learning). Companies that don't set one use the server's default AI. Keys are stored
encrypted in the company's record and are never sent back to the browser (only the last four characters).
The "free key" banner follows the company's own key: it shows until they tick "Paid / billed key"."""
from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import datetime, timezone

from ..config import settings
from ..db import SessionLocal
from ..models import Tenant
from . import llm

PROVIDERS = ("gemini", "anthropic", "openai", "azure")
DEFAULT_MODEL = {"anthropic": "claude-sonnet-4-5", "openai": "gpt-4o"}


def _fernet():
    from cryptography.fernet import Fernet

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"revenueforge-company-ai|" + settings.jwt_secret.encode()).digest()))


def _enc(v: str) -> str:
    return _fernet().encrypt(v.encode()).decode() if v else ""


def _dec(v: str) -> str:
    if not v:
        return ""
    try:
        return _fernet().decrypt(v.encode()).decode()
    except Exception:
        return ""  # e.g. the server's secret changed: the key has to be entered again


def _cfg(t: Tenant) -> dict:
    return dict((t.settings or {}).get("ai") or {})


def profile_for(tid: str) -> llm.Profile | None:
    db = SessionLocal()
    try:
        t = db.get(Tenant, tid)
        c = _cfg(t) if t else {}
    finally:
        db.close()
    p = c.get("provider")
    if p not in PROVIDERS:
        return None
    key = _dec((c.get("keys") or {}).get(p, ""))
    if not key:
        return None
    base = llm.Profile(rpm=max(1, int(c.get("rpm") or 8)), paid=bool(c.get("paid")), source="company",
                       gemini_embed_model=settings.gemini_embed_model, azure_api_version=settings.azure_api_version)
    model = (c.get("model") or "").strip()
    if p == "gemini":
        return replace(base, provider=p, gemini_api_key=key, gemini_model=model)
    if p == "anthropic":
        return replace(base, provider=p, anthropic_api_key=key, anthropic_model=model or DEFAULT_MODEL[p])
    if p == "openai":
        return replace(base, provider=p, openai_api_key=key, openai_model=model or DEFAULT_MODEL[p])
    return replace(base, provider=p, azure_api_key=key, azure_deployment=model, azure_endpoint=c.get("azure_endpoint", ""))


llm.set_tenant_loader(profile_for)


def _hint(k: str) -> str:
    return f"…{k[-4:]}" if len(k) >= 8 else ("set" if k else "")


def view(t: Tenant) -> dict:
    c = _cfg(t)
    keys = c.get("keys") or {}
    sp = llm.server_profile()
    return {"provider": c.get("provider") if c.get("provider") in PROVIDERS else "default", "model": c.get("model", ""),
            "rpm": int(c.get("rpm") or 8), "paid": bool(c.get("paid")), "azure_endpoint": c.get("azure_endpoint", ""),
            "key_hint": {p: _hint(_dec(keys.get(p, ""))) for p in PROVIDERS},
            "updated_by": c.get("updated_by", ""), "updated_at": c.get("updated_at", ""),
            "server_default": {"provider": llm._usable(sp), "paid": sp.paid}}


def save(db, t: Tenant, body: dict, by: str) -> None:
    p = str(body.get("provider") or "default").lower()
    c = _cfg(t)
    keys = dict(c.get("keys") or {})
    if p == "default":
        c = {"provider": "default", "keys": keys}  # keys are kept so switching back doesn't mean pasting them again
    elif p in PROVIDERS:
        key = str(body.get("api_key") or "").strip()
        if key:
            keys[p] = _enc(key[:400])
        elif not _dec(keys.get(p, "")):
            raise ValueError("Enter an API key for this provider.")
        try:
            rpm = max(1, min(1000, int(body.get("rpm") or 8)))
        except (TypeError, ValueError):
            raise ValueError("Requests per minute must be a number.")
        model = str(body.get("model") or "").strip()[:120]
        c = {"provider": p, "keys": keys, "model": model, "rpm": rpm, "paid": bool(body.get("paid")) if p == "gemini" else True}
        if p == "azure":
            ep = str(body.get("azure_endpoint") or "").strip()[:300]
            if not ep.startswith("https://"):
                raise ValueError("Enter the Azure OpenAI endpoint (https://…).")
            if not model:
                raise ValueError("Enter the Azure OpenAI deployment name.")
            c["azure_endpoint"] = ep
    else:
        raise ValueError("Unknown AI provider.")
    c["updated_by"], c["updated_at"] = by, datetime.now(timezone.utc).isoformat()
    t.settings = {**(t.settings or {}), "ai": c}
    db.commit()
    llm.invalidate_tenant(t.id)
    with llm.use_tenant(t.id):
        llm.reset_state(all_keys=False)


def test(tid: str) -> dict:
    import time

    with llm.use_tenant(tid):
        if llm.provider_name() == "none":
            return {"ok": False, "message": "AI is off (rules engine only)."}
        t0 = time.time()
        try:
            out = llm.complete("You are a connection test.", "Reply with the single word OK.", max_tokens=20, attempts=1)
            src = "your company's key" if llm.current_profile().source == "company" else "the server's default AI"
            return {"ok": True, "message": f"Connected using {src} in {time.time() - t0:.1f}s. Reply: {out.strip()[:40]}"}
        except Exception as e:
            return {"ok": False, "message": str(e)[:400]}
