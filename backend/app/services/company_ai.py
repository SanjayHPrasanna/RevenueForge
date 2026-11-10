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
    return _profile(c)


def _profile(c: dict) -> llm.Profile | None:
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
    return replace(base, provider=p, azure_api_key=key, azure_deployment=model, azure_endpoint=c.get("azure_endpoint", ""),
                   azure_embed_deployment=c.get("embed_deployment", ""), azure_embed_endpoint=c.get("embed_endpoint", ""),
                   azure_embed_api_key=_dec((c.get("keys") or {}).get("azure_embed", "")) if c.get("embed_endpoint") else "")


llm.set_tenant_loader(profile_for)


def _hint(k: str) -> str:
    return f"…{k[-4:]}" if len(k) >= 8 else ("set" if k else "")


def view(t: Tenant) -> dict:
    c = _cfg(t)
    keys = c.get("keys") or {}
    sp = llm.server_profile()
    return {"provider": c.get("provider") if c.get("provider") in PROVIDERS else "default", "model": c.get("model", ""),
            "rpm": int(c.get("rpm") or 8), "paid": bool(c.get("paid")), "azure_endpoint": c.get("azure_endpoint", ""),
            "embed_deployment": c.get("embed_deployment", ""), "embed_endpoint": c.get("embed_endpoint", ""),
            "embed_key_hint": _hint(_dec(keys.get("azure_embed", ""))),
            "key_hint": {p: _hint(_dec(keys.get(p, ""))) for p in PROVIDERS},
            "updated_by": c.get("updated_by", ""), "updated_at": c.get("updated_at", ""),
            "server_default": {"provider": llm._usable(sp), "paid": sp.paid}}


def save(db, t: Tenant, body: dict, by: str) -> None:
    c = _build(t, body)
    c["updated_by"], c["updated_at"] = by, datetime.now(timezone.utc).isoformat()
    t.settings = {**(t.settings or {}), "ai": c}
    db.commit()
    llm.invalidate_tenant(t.id)
    with llm.use_tenant(t.id):
        llm.reset_state(all_keys=False)


def _build(t: Tenant, body: dict) -> dict:
    """The settings the form describes, checked, without saving them. A blank key means "keep the saved one"."""
    if not isinstance(body, dict):
        raise ValueError("Send the settings to check.")
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
            c["embed_deployment"] = str(body.get("embed_deployment") or "").strip()[:120]
            eep = str(body.get("embed_endpoint") or "").strip()[:300]
            if eep and not eep.startswith("https://"):
                raise ValueError("Enter the embedding endpoint (https://…), or leave it empty to use the endpoint above.")
            c["embed_endpoint"] = eep
            ekey = str(body.get("embed_api_key") or "").strip()
            if ekey:
                keys["azure_embed"] = _enc(ekey[:400])
    else:
        raise ValueError("Unknown AI provider.")
    return c


def test(t: Tenant, body: dict | None = None) -> dict:
    """Check the settings in the form (or, with no body, the saved ones) with one tiny AI call. Nothing is saved."""
    import time

    if body:
        try:
            c = _build(t, body)
        except ValueError as e:
            return {"ok": False, "message": str(e)}
        prof = _profile(c) if c.get("provider") in PROVIDERS else llm.server_profile()
        if prof is None:
            return {"ok": False, "message": "Enter an API key for this provider."}
    else:
        with llm.use_tenant(t.id):
            prof = llm.current_profile()
    if llm._usable(prof) == "none":
        return {"ok": False, "message": "AI is off (rules engine only)." if prof.source != "company" else "Some settings are missing."}
    llm._st(prof).update({"disabled_reason": "", "last_error": ""})  # a test always really tries, even after an earlier rejection
    t0 = time.time()
    with llm.use_profile(prof):
        try:
            out = llm.complete("You are a connection test.", "Reply with the single word OK.", max_tokens=20, attempts=1)
        except Exception as e:
            return {"ok": False, "message": _explain(str(e))}
    emb = ""
    if prof.provider == "azure" and prof.azure_embed_deployment:
        with llm.use_profile(prof):
            try:
                llm._st(prof)["embed_ok"] = None
                llm.embed(["connection test"])
                emb = f" Smart matching ({prof.azure_embed_deployment}) works too."
            except Exception as e:
                return {"ok": False, "message": "The chat model works, but the smart matching model doesn't. " + _explain(str(e)).replace("The deployment name", "Its deployment name")}
    src = "this key" if prof.source == "company" else "the server's default AI"
    saved = " Press Save to start using it." if body and prof.source == "company" else ""
    return {"ok": True, "message": f"Connected using {src} in {time.time() - t0:.1f}s (reply: {out.strip()[:20]}).{emb}{saved}"}


def _explain(err: str) -> str:
    """The provider's own error, with a plain-words reason in front when it's a common one."""
    e = err.lower()
    why = ("The key was not accepted. Check it was copied in full." if any(x in e for x in ("http 401", "http 403", "invalid api key", "access denied"))
           else "The deployment name wasn't found on that endpoint. Use the name from the Deployments page." if "deploymentnotfound" in e or "http 404" in e
           else "The provider says the quota or allowance is used up." if "http 429" in e or "quota" in e
           else "The provider is busy. Try again in a minute." if any(x in e for x in ("http 503", "http 500", "overloaded", "high demand"))
           else "The provider didn't answer in time." if "timed out" in e
           else "")
    return (why + " Details: " if why else "") + err[:350]
