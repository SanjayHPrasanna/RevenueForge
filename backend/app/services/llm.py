"""AI layer: one interface over Gemini, Claude, OpenAI and Azure OpenAI, plus embeddings.

Every AI step in RevenueForge calls `complete_json` / `embed`. Calls are throttled to the configured
requests-per-minute (free Gemini keys are rate-limited), retried on rate-limit errors, and every
caller has a rules-engine fallback so a failed AI call never stops a deal.

Which provider and key a call uses depends on the company it is made for: a company can bring its own
provider and key (Settings → Your company's AI); otherwise the server's default applies. The company is
taken from the request's sign-in token (see main.py) or set explicitly by background jobs with
`use_tenant()`. Rate limits and error status are kept per key.
"""
from __future__ import annotations

import contextlib
import contextvars
import hashlib
import json
import logging
import math
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, replace

import httpx

from ..config import settings

log = logging.getLogger("revenueforge.llm")


class LLMUnavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------- profiles (who pays for this call)
@dataclass(frozen=True)
class Profile:
    provider: str = "none"
    gemini_api_key: str = ""
    gemini_model: str = ""
    gemini_embed_model: str = "gemini-embedding-001"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    azure_endpoint: str = ""
    azure_api_key: str = ""
    azure_deployment: str = ""
    azure_api_version: str = "2024-06-01"
    rpm: int = 8
    paid: bool = False
    source: str = "server"  # "server" (the server's default) or "company" (the company's own key)

    @property
    def key(self) -> str:
        secret = {"gemini": self.gemini_api_key, "anthropic": self.anthropic_api_key, "openai": self.openai_api_key,
                  "azure": self.azure_api_key}.get(self.provider, "")
        return hashlib.sha256(f"{self.provider}|{secret}".encode()).hexdigest()[:16]


def server_profile() -> Profile:
    s = settings
    return Profile(provider=s.llm_provider, gemini_api_key=s.gemini_api_key, gemini_model=s.gemini_model,
                   gemini_embed_model=s.gemini_embed_model, anthropic_api_key=s.anthropic_api_key, anthropic_model=s.anthropic_model,
                   openai_api_key=s.openai_api_key, openai_model=s.openai_model, azure_endpoint=s.azure_endpoint,
                   azure_api_key=s.azure_api_key, azure_deployment=s.azure_deployment, azure_api_version=s.azure_api_version,
                   rpm=max(1, s.llm_rpm), paid=s.llm_paid, source="server")


_tenant: contextvars.ContextVar[str | None] = contextvars.ContextVar("rf_tenant", default=None)
_tenant_loader = None  # set by services.company_ai: tenant id -> Profile | None
_tenant_cache: dict[str, tuple[float, Profile | None]] = {}
_cache_lock = threading.Lock()


def set_tenant_loader(fn) -> None:
    global _tenant_loader
    _tenant_loader = fn


def set_tenant(tid: str | None):
    return _tenant.set(tid)


def reset_tenant(token) -> None:
    _tenant.reset(token)


@contextlib.contextmanager
def use_tenant(tid: str | None):
    """AI calls inside this block use that company's own AI settings (if it has any)."""
    token = _tenant.set(tid)
    try:
        yield
    finally:
        _tenant.reset(token)


def invalidate_tenant(tid: str) -> None:
    with _cache_lock:
        _tenant_cache.pop(tid, None)


def current_profile() -> Profile:
    tid = _tenant.get()
    if tid and _tenant_loader:
        with _cache_lock:
            hit = _tenant_cache.get(tid)
        if not hit or time.time() - hit[0] > 60:
            try:
                prof = _tenant_loader(tid)
            except Exception as e:  # never let a settings problem stop a deal: fall back to the server default
                log.warning("Couldn't load company AI settings for %s: %s", tid, e)
                prof = None
            hit = (time.time(), prof)
            with _cache_lock:
                _tenant_cache[tid] = hit
        if hit[1] is not None:
            return hit[1]
    return server_profile()


def _usable(p: Profile) -> str:
    if p.provider == "gemini" and p.gemini_api_key:
        return "gemini"
    if p.provider == "anthropic" and p.anthropic_api_key:
        return "anthropic"
    if p.provider == "openai" and p.openai_api_key:
        return "openai"
    if p.provider == "azure" and p.azure_api_key and p.azure_endpoint and p.azure_deployment:
        return "azure"
    return "none"


# --------------------------------------------------------------------------- status (per key)
_states: dict[str, dict] = {}
_state_lock = threading.Lock()


def _st(p: Profile) -> dict:
    with _state_lock:
        return _states.setdefault(p.key, {"gemini_model": None, "disabled_reason": "", "calls": 0, "failures": 0, "last_error": "",
                                          "embed_ok": None})


def provider_name() -> str:
    return _usable(current_profile())


def is_enabled() -> bool:
    p = current_profile()
    return _usable(p) != "none" and not _st(p)["disabled_reason"]


def status() -> dict:
    p = current_profile()
    st = _st(p)
    name = _usable(p)
    model = {"gemini": st["gemini_model"] or p.gemini_model or "auto (newest Flash)", "anthropic": p.anthropic_model,
             "openai": p.openai_model, "azure": p.azure_deployment}.get(name, "")
    return {"provider": name, "model": model, "enabled": is_enabled(), "configured_provider": p.provider, "source": p.source,
            "paid": p.paid, "rpm": p.rpm, "calls": st["calls"], "failures": st["failures"], "last_error": st["last_error"][:300],
            "disabled_reason": st["disabled_reason"], "embeddings": name in ("gemini", "openai") and st["embed_ok"] is not False}


def notice() -> str:
    """The banner text for the current company (or the server default when nobody is signed in)."""
    n = settings.public_notice
    if n.lower() in ("off", "none", "false", "0"):
        return ""
    if n:
        return n
    p = current_profile()
    if _usable(p) == "gemini" and not p.paid:
        return ("Test version: use sample or dummy documents only. The AI runs on a free Google key, "
                "so please don't upload confidential client RFPs or company data.")
    return ""


def reset_state(all_keys: bool = True) -> None:
    """Forget cached model choice and key errors, e.g. after the AI settings change."""
    with _state_lock:
        if all_keys:
            for st in _states.values():
                st.update({"gemini_model": None, "disabled_reason": "", "embed_ok": None, "last_error": ""})
        else:
            _states.pop(current_profile().key, None)


# --------------------------------------------------------------------------- throttle (per key)
_lock = threading.Lock()
_stamps: dict[str, deque] = {}


def _throttle(p: Profile):
    rpm = max(1, p.rpm)
    while True:
        with _lock:
            q = _stamps.setdefault(p.key, deque())
            now = time.time()
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) < rpm:
                q.append(now)
                return
            wait = 60 - (now - q[0]) + 0.2
        time.sleep(max(0.2, wait))


# --------------------------------------------------------------------------- gemini (REST)
def _gemini_headers(p: Profile):
    return {"x-goog-api-key": p.gemini_api_key, "Content-Type": "application/json"}


def _gemini_pick_model(client: httpx.Client, p: Profile) -> str:
    st = _st(p)
    if p.gemini_model:
        return p.gemini_model
    if st["gemini_model"]:
        return st["gemini_model"]
    try:
        r = client.get(f"{settings.gemini_base_url}/models", headers=_gemini_headers(p), params={"pageSize": 200})
        r.raise_for_status()
        names = []
        for m in r.json().get("models", []):
            name = m.get("name", "").split("/")[-1]
            methods = m.get("supportedGenerationMethods", [])
            if "generateContent" not in methods or "flash" not in name:
                continue
            if re.search(r"lite|image|tts|live|audio|preview|exp|thinking|native|8b|latest|robotics|computer", name):
                continue
            ver = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
            names.append((float(ver.group(1)) if ver else 0, name))
        if names:
            names.sort(reverse=True)
            st["gemini_model"] = names[0][1]
            log.info("Gemini model selected: %s", names[0][1])
            return names[0][1]
    except Exception as e:  # listing failed: fall back to the rolling alias
        log.warning("Could not list Gemini models: %s", e)
    st["gemini_model"] = "gemini-flash-latest"
    return st["gemini_model"]


def _gemini_complete(p: Profile, system: str, prompt: str, max_tokens: int, temperature: float, want_json: bool) -> str:
    with httpx.Client(timeout=180) as client:
        model = _gemini_pick_model(client, p)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max(max_tokens, 8192)},
        }
        if want_json:
            body["generationConfig"]["responseMimeType"] = "application/json"
        r = client.post(f"{settings.gemini_base_url}/models/{model}:generateContent", headers=_gemini_headers(p), json=body)
        if r.status_code == 404 and not p.gemini_model:
            _st(p)["gemini_model"] = None
        if r.status_code >= 400:
            raise _HttpError(r.status_code, r.text, r.headers.get("retry-after"))
        data = r.json()
        cands = data.get("candidates") or []
        if not cands:
            raise LLMUnavailable(f"Gemini returned no answer ({data.get('promptFeedback', {}).get('blockReason', 'unknown reason')})")
        parts = cands[0].get("content", {}).get("parts", [])
        text = "".join(x.get("text", "") for x in parts if not x.get("thought"))
        if not text.strip():
            raise LLMUnavailable(f"Gemini returned an empty answer (finish reason {cands[0].get('finishReason')})")
        return text


def _gemini_embed(p: Profile, texts: list[str], task: str) -> list[list[float]]:
    out: list[list[float]] = []
    model = p.gemini_embed_model
    with httpx.Client(timeout=120) as client:
        for start in range(0, len(texts), 100):
            chunk = texts[start:start + 100]
            body = {"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": t[:6000] or " "}]}, "taskType": task,
                                  "outputDimensionality": 768} for t in chunk]}
            _throttle(p)
            r = client.post(f"{settings.gemini_base_url}/models/{model}:batchEmbedContents", headers=_gemini_headers(p), json=body)
            if r.status_code >= 400:
                raise _HttpError(r.status_code, r.text, r.headers.get("retry-after"))
            for e in r.json().get("embeddings", []):
                out.append(_normalize(e.get("values", [])))
    return out


# --------------------------------------------------------------------------- other providers
def _other_complete(p: Profile, name: str, system: str, prompt: str, max_tokens: int, temperature: float, want_json: bool) -> str:
    if name == "anthropic":
        import anthropic

        client = anthropic.Anthropic(api_key=p.anthropic_api_key)
        msg = client.messages.create(model=p.anthropic_model, max_tokens=max_tokens, temperature=temperature,
                                     system=system, messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if name == "openai":
        from openai import OpenAI

        client, model = OpenAI(api_key=p.openai_api_key), p.openai_model
    else:
        from openai import AzureOpenAI

        client = AzureOpenAI(api_key=p.azure_api_key, azure_endpoint=p.azure_endpoint, api_version=p.azure_api_version)
        model = p.azure_deployment
    kw = {"response_format": {"type": "json_object"}} if want_json else {}
    r = client.chat.completions.create(model=model, max_tokens=max_tokens, temperature=temperature,
                                       messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}], **kw)
    return r.choices[0].message.content or ""


class _HttpError(Exception):
    def __init__(self, status: int, body: str, retry_after: str | None):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status, self.body, self.retry_after = status, body, retry_after


# --------------------------------------------------------------------------- public API
def complete(system: str, prompt: str, max_tokens: int = 4000, temperature: float = 0.2, want_json: bool = False,
             api_key: str | None = None, attempts: int = 4) -> str:
    """`api_key` sends this one call to Gemini with a separate key (e.g. the video narration key), so it neither uses
    nor can switch off the company's main AI key."""
    base = current_profile()
    p = replace(server_profile(), provider="gemini", gemini_api_key=api_key, gemini_model="", source="override") if api_key else base
    name = _usable(p)
    st = _st(p)
    if name == "none":
        raise LLMUnavailable("No AI provider configured")
    if st["disabled_reason"] and not api_key:
        raise LLMUnavailable(st["disabled_reason"])
    last = None
    for attempt in range(max(1, attempts)):
        _throttle(p)
        try:
            st["calls"] += 1
            if name == "gemini":
                return _gemini_complete(p, system, prompt, max_tokens, temperature, want_json)
            return _other_complete(p, name, system, prompt, max_tokens, temperature, want_json)
        except _HttpError as e:
            last = e
            if e.status in (401, 403) or (e.status == 400 and "API key" in e.body):
                if not api_key:
                    st["disabled_reason"] = ("The AI key was rejected. Update it in Settings → AI engine." if p.source == "company" else
                                             "The AI key was rejected. Update it in Settings → AI engine, or in the server settings.")
                break
            wait = 15 * (attempt + 1)
            m = re.search(r'"retryDelay":\s*"(\d+)', e.body)
            if m:
                wait = int(m.group(1)) + 1
            elif e.retry_after and e.retry_after.isdigit():
                wait = int(e.retry_after) + 1
            if e.status in (429, 500, 502, 503, 504):
                if attempt + 1 >= attempts:
                    break
                log.warning("AI call failed (%s); retrying in %ss", e.status, wait)
                time.sleep(min(wait, 65))
                continue
            break
        except Exception as e:
            last = e
            log.warning("AI call failed (attempt %s): %s", attempt + 1, e)
            if attempt + 1 < attempts:
                time.sleep(3 * (attempt + 1))
    st["failures"] += 1
    st["last_error"] = str(last)
    raise LLMUnavailable(f"AI call failed: {last}")


def complete_json(system: str, prompt: str, max_tokens: int = 8000, api_key: str | None = None):
    raw = complete(system + "\nRespond with valid JSON only. No prose, no code fences.", prompt, max_tokens=max_tokens, want_json=True,
                   api_key=api_key)
    return parse_json(raw)


def parse_json(raw: str):
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", raw, re.S)
        if m:
            return json.loads(m.group(1))
        raise


def embeddings_enabled() -> bool:
    p = current_profile()
    return is_enabled() and _usable(p) in ("gemini", "openai") and _st(p)["embed_ok"] is not False


def embed_id() -> str:
    """Which embedding model vectors come from. Vectors from different models can't be compared, so caches key on this."""
    p = current_profile()
    name = _usable(p)
    return f"gemini:{p.gemini_embed_model}" if name == "gemini" else "openai:text-embedding-3-small" if name == "openai" else "none"


def embed(texts: list[str], task: str = "SEMANTIC_SIMILARITY") -> list[list[float]]:
    """Unit-normalised embedding vectors. Raises LLMUnavailable when embeddings aren't available."""
    if not texts:
        return []
    if not embeddings_enabled():
        raise LLMUnavailable("Embeddings not available")
    p = current_profile()
    name = _usable(p)
    st = _st(p)
    for attempt in range(3):
        try:
            if name == "gemini":
                vecs = _gemini_embed(p, texts, task)
            else:
                from openai import OpenAI

                client = OpenAI(api_key=p.openai_api_key)
                vecs = []
                for start in range(0, len(texts), 500):
                    _throttle(p)
                    r = client.embeddings.create(model="text-embedding-3-small", input=[t[:6000] or " " for t in texts[start:start + 500]])
                    vecs += [_normalize(d.embedding) for d in r.data]
            st["embed_ok"] = True
            return vecs
        except _HttpError as e:
            if e.status == 429:
                time.sleep(20 * (attempt + 1))
                continue
            if e.status in (400, 404):
                st["embed_ok"] = False  # model not available for this key: use text matching instead
            raise LLMUnavailable(str(e))
        except Exception as e:
            raise LLMUnavailable(str(e))
    raise LLMUnavailable("Embedding rate limit")


def _normalize(v: list[float]) -> list[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
