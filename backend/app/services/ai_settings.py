"""AI provider settings changed from the app (Settings → AI engine).

The server's own settings (backend/.env locally, App Service settings on Azure) are the baseline. Anything a
platform admin saves in the app is stored in the data folder (ai-settings.json, which survives restarts and
redeploys) and applied on top. "Use server settings" deletes the file and goes back to the baseline.

The AI set-up is shared by every company on the server, so only the people listed in PLATFORM_ADMINS can change
it. Keys are never sent back to the browser; only their last four characters are shown."""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone

from ..config import DATA_DIR, settings
from . import llm

log = logging.getLogger("revenueforge.ai_settings")
FILE = DATA_DIR / "ai-settings.json"
PROVIDERS = ("gemini", "anthropic", "openai", "azure", "none")
KEY_ATTR = {"gemini": "gemini_api_key", "anthropic": "anthropic_api_key", "openai": "openai_api_key", "azure": "azure_api_key"}
MODEL_ATTR = {"gemini": "gemini_model", "anthropic": "anthropic_model", "openai": "openai_model", "azure": "azure_deployment"}
FIELDS = ["llm_provider", "llm_rpm", "llm_paid", "azure_endpoint", *KEY_ATTR.values(), *MODEL_ATTR.values()]
_BASE = {f: getattr(settings, f) for f in FIELDS}  # the server's own settings, captured before anything is applied
_lock = threading.Lock()


def is_platform_admin(email: str | None) -> bool:
    return bool(email) and email.lower() in settings.platform_admins


def _saved() -> dict:
    try:
        return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except Exception as e:
        log.warning("Ignoring unreadable %s: %s", FILE.name, e)
        return {}


def _apply(values: dict) -> None:
    for f in FIELDS:
        setattr(settings, f, values.get(f, _BASE[f]))
    llm.reset_state()


def apply_saved() -> None:
    """Called at start-up."""
    saved = _saved()
    if saved:
        _apply({**_BASE, **{k: v for k, v in saved.items() if k in FIELDS}})
        log.info("AI settings saved in the app are in use (provider: %s)", settings.llm_provider)


def _hint(key: str) -> str:
    return f"…{key[-4:]}" if key and len(key) >= 8 else ("set" if key else "")


def view(can_edit: bool) -> dict:
    p = settings.llm_provider if settings.llm_provider in PROVIDERS else "none"
    saved = _saved()
    out = {"can_edit": can_edit, "provider": p, "model": getattr(settings, MODEL_ATTR[p]) if p in MODEL_ATTR else "",
           "rpm": settings.llm_rpm, "paid": settings.llm_paid, "saved_in_app": bool(saved),
           "saved_at": saved.get("_saved_at"), "admins_configured": bool(settings.platform_admins)}
    if can_edit:  # never the key itself
        out["key_hint"] = {k: _hint(getattr(settings, a)) for k, a in KEY_ATTR.items()}
        out["azure_endpoint"] = settings.azure_endpoint
    return out


def save(body: dict, by: str) -> None:
    p = str(body.get("provider") or "none").lower()
    if p not in PROVIDERS:
        raise ValueError("Unknown AI provider.")
    with _lock:
        saved = {k: v for k, v in _saved().items() if k in FIELDS}
        cur = {f: getattr(settings, f) for f in FIELDS}
        saved["llm_provider"] = p
        try:
            saved["llm_rpm"] = max(1, min(1000, int(body.get("rpm") or cur["llm_rpm"])))
        except (TypeError, ValueError):
            raise ValueError("Requests per minute must be a number.")
        saved["llm_paid"] = bool(body.get("paid"))
        if p in KEY_ATTR:
            key = str(body.get("api_key") or "").strip()
            if key:  # an empty box keeps the key already in use
                saved[KEY_ATTR[p]] = key[:400]
            elif not cur[KEY_ATTR[p]]:
                raise ValueError("Enter an API key for this provider.")
            saved[MODEL_ATTR[p]] = str(body.get("model") or "").strip()[:120] or (_BASE[MODEL_ATTR[p]] if p != "gemini" else "")
            if p == "azure":
                ep = str(body.get("azure_endpoint") or cur["azure_endpoint"] or "").strip()[:300]
                if not ep.startswith("https://"):
                    raise ValueError("Enter the Azure OpenAI endpoint (https://…).")
                saved["azure_endpoint"] = ep
                if not saved[MODEL_ATTR[p]]:
                    raise ValueError("Enter the Azure OpenAI deployment name.")
        saved["_saved_at"] = datetime.now(timezone.utc).isoformat()
        saved["_saved_by"] = by
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(saved, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, FILE)
        _apply({**_BASE, **{k: v for k, v in saved.items() if k in FIELDS}})


def reset() -> None:
    with _lock:
        FILE.unlink(missing_ok=True)
        _apply(_BASE)


def test() -> dict:
    """One quick call to confirm the current provider, key and model work."""
    import time

    if llm.provider_name() == "none":
        return {"ok": False, "message": "AI is off (rules engine only)."}
    t0 = time.time()
    try:
        out = llm.complete("You are a connection test.", "Reply with the single word OK.", max_tokens=20, attempts=1)
        return {"ok": True, "message": f"Connected in {time.time() - t0:.1f}s. Reply: {out.strip()[:40]}", "model": llm.status()["model"]}
    except Exception as e:
        return {"ok": False, "message": str(e)[:400]}
