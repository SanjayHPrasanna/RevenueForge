"""Azure OpenAI and "Test connection" against a simulated Azure (no network, no real key).

Run: python tests/qa_azure.py
Covers: the v1 route and the classic dated route, a Foundry ".services.ai.azure.com" address, reasoning models that reject
max_tokens/temperature, plain-words errors for a wrong key and an unknown deployment, and testing the form's settings
without saving them (and without leaking keys).
"""
import json
import os
import re
import secrets
import sys
import tempfile

os.environ.update(LLM_PROVIDER="none", RF_DATA_DIR=tempfile.mkdtemp(), RADAR_REFRESH_HOURS="0", DEMO_VENDORS="false", LLM_RPM="1000")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402
import openai  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services import llm  # noqa: E402

PASSES, FAILS = 0, []


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
        print("ok  ", name)
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


GOOD_KEY = "az-" + secrets.token_hex(16)
seen: list[dict] = []
MODE = {"v1": True, "reasoning": False, "deployment": "revenueforge"}


EMB = {"deployment": "text-embedding-3-small"}
emb_calls: list[dict] = []


def embedding_for(text: str) -> list[float]:
    # A toy "meaning" space: integration words and data-exchange words land in the same direction.
    t = text.lower()
    integ = sum(w in t for w in ("integration", "exchange data", "interfaces", "connect", "applications talk"))
    food = sum(w in t for w in ("catering", "meals", "food"))
    return [1.0 + integ * 3, 0.1 + food * 3, 0.2]


def handler(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    body = json.loads(req.content or b"{}")
    if url.split("?")[0].endswith("/embeddings"):
        key = req.headers.get("api-key") or (req.headers.get("authorization") or "").replace("Bearer ", "")
        route = "v1" if "/openai/v1/" in url else "classic"
        model = body.get("model") or url.split("/deployments/")[-1].split("/")[0]
        emb_calls.append({"route": route, "model": model, "n": len(body.get("input", []))})
        if key != GOOD_KEY:
            return httpx.Response(401, json={"error": {"code": "401", "message": "Access denied"}})
        if route == "v1" and not MODE["v1"]:
            return httpx.Response(404, json={"error": {"code": "404", "message": "Resource not found"}})
        if model != EMB["deployment"]:
            return httpx.Response(404, json={"error": {"code": "DeploymentNotFound", "message": "The API deployment for this resource does not exist."}})
        return httpx.Response(200, json={"object": "list", "model": model, "usage": {"prompt_tokens": 1, "total_tokens": 1},
                                         "data": [{"object": "embedding", "index": i, "embedding": embedding_for(t)} for i, t in enumerate(body["input"])]})
    key = req.headers.get("api-key") or (req.headers.get("authorization") or "").replace("Bearer ", "")
    route = "v1" if "/openai/v1/" in url else "classic"
    seen.append({"host": req.url.host, "route": route, "model": body.get("model") or url.split("/deployments/")[-1].split("/")[0],
                 "args": sorted(k for k in body if k in ("max_tokens", "max_completion_tokens", "temperature"))})
    if key != GOOD_KEY:
        return httpx.Response(401, json={"error": {"code": "401", "message": "Access denied due to invalid subscription key or wrong API endpoint."}})
    if route == "v1" and not MODE["v1"]:
        return httpx.Response(404, json={"error": {"code": "404", "message": "Resource not found"}})
    model = seen[-1]["model"]
    if model != MODE["deployment"]:
        return httpx.Response(404, json={"error": {"code": "DeploymentNotFound", "message": "The API deployment for this resource does not exist."}})
    if MODE["reasoning"] and ("max_tokens" in body or "temperature" in body):
        return httpx.Response(400, json={"error": {"code": "unsupported_parameter", "message": "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."}})
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 0, "model": model,
                                     "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "OK"}}]})


_transport = httpx.MockTransport(handler)
_RealOpenAI, _RealAzure = openai.OpenAI, openai.AzureOpenAI
openai.OpenAI = lambda **kw: _RealOpenAI(http_client=httpx.Client(transport=_transport), max_retries=0, **kw)
openai.AzureOpenAI = lambda **kw: _RealAzure(http_client=httpx.Client(transport=_transport), max_retries=0, **kw)


def prof(endpoint="https://revenueforge.services.ai.azure.com/", key=GOOD_KEY, dep="revenueforge"):
    return llm.Profile(provider="azure", azure_api_key=key, azure_endpoint=endpoint, azure_deployment=dep, rpm=1000, source="company")


def run(p):
    for k in ("azure_route", "reasoning_model"):
        llm._st(p).pop(k, None)
    seen.clear()
    with llm.use_profile(p):
        return llm.complete("s", "Reply OK", max_tokens=20, attempts=1)


# ---------------------------------------------------------------- routes and addresses
ok("v1 route works", run(prof()) == "OK" and seen[0]["route"] == "v1", str(seen))
ok("Foundry .services.ai.azure.com address is sent to the resource's .openai.azure.com address",
   seen[0]["host"] == "revenueforge.openai.azure.com", str(seen))
MODE["v1"] = False
ok("resource without v1: classic dated route is used", run(prof()) == "OK" and [s["route"] for s in seen] == ["v1", "classic"], str(seen))
MODE["v1"] = True

# ---------------------------------------------------------------- reasoning models
MODE["reasoning"] = True
out = run(prof())
ok("reasoning model: asked again with max_completion_tokens and no temperature",
   out == "OK" and seen[-1]["args"] == ["max_completion_tokens"] and seen[0]["args"] == ["max_tokens", "temperature"], str(seen))
seen.clear()
with llm.use_profile(prof()):
    llm.complete("s", "again", max_tokens=20, attempts=1)
ok("reasoning model remembered: the next call goes straight to its settings", [s["args"] for s in seen] == [["max_completion_tokens"]], str(seen))
MODE["reasoning"] = False

# ---------------------------------------------------------------- errors
try:
    run(prof(key="wrong-" + secrets.token_hex(8)))
    ok("wrong key fails", False)
except llm.LLMUnavailable as e:
    ok("wrong key: reported as 401, not retried on the classic route", "HTTP 401" in str(e) and len(seen) == 1, f"{e} {seen}")
try:
    run(prof(dep="does-not-exist"))
    ok("unknown deployment fails", False)
except llm.LLMUnavailable as e:
    ok("unknown deployment: the provider's DeploymentNotFound is reported", "DeploymentNotFound" in str(e) or "does not exist" in str(e), str(e))

# ---------------------------------------------------------------- embeddings
from dataclasses import replace as _replace  # noqa: E402

ep = _replace(prof(), azure_embed_deployment="text-embedding-3-small")
with llm.use_profile(prof()):
    ok("no embedding deployment: embeddings off, word matching used", not llm.embeddings_enabled())
with llm.use_profile(ep):
    ok("embedding deployment set: embeddings on", llm.embeddings_enabled() and llm.embed_id().startswith("azure:https://revenueforge.openai.azure.com:"), llm.embed_id())
    emb_calls.clear()
    vecs = llm.embed(["Integration of the fare collection system", "Exchange data between the ticketing and finance applications",
                      "Catering and meals for staff"] * 30)
    ok("embeddings come back, one per text, normalised", len(vecs) == 90 and abs(sum(x * x for x in vecs[0]) - 1) < 1e-6)
    ok("sent in small batches (trial-friendly)", [c["n"] for c in emb_calls] == [64, 26], str(emb_calls))
    ok("similar meaning scores closer than shared words alone would",
       llm.cosine(vecs[0], vecs[1]) > 0.95 and llm.cosine(vecs[0], vecs[2]) < 0.6, f"{llm.cosine(vecs[0], vecs[1]):.2f} {llm.cosine(vecs[0], vecs[2]):.2f}")
MODE["v1"] = False
e2 = _replace(prof(endpoint="https://revenueforge2.openai.azure.com/"), azure_embed_deployment="text-embedding-3-small")
with llm.use_profile(e2):
    emb_calls.clear()
    llm.embed(["x"])
    ok("embeddings fall back to the classic route", [c["route"] for c in emb_calls] == ["v1", "classic"], str(emb_calls))
MODE["v1"] = True
bad = _replace(prof(endpoint="https://revenueforge3.openai.azure.com/"), azure_embed_deployment="wrong-name")
with llm.use_profile(bad):
    try:
        llm.embed(["x"])
        ok("wrong embedding deployment fails", False)
    except llm.LLMUnavailable:
        ok("wrong embedding deployment: embeddings switch off for this key (word matching continues)", not llm.embeddings_enabled())

# ---------------------------------------------------------------- Test connection before saving (API)
with TestClient(app) as c:
    pw = "Qa-" + secrets.token_hex(8) + "!A1"
    tok = c.post("/api/auth/register", json={"company_name": "Azure Test Co", "name": "QA", "email": "az@qa.example", "password": pw}).json()["token"]
    H = {"Authorization": "Bearer " + tok}
    form = {"provider": "azure", "api_key": GOOD_KEY, "model": "revenueforge", "rpm": 60, "azure_endpoint": "https://revenueforge.services.ai.azure.com/"}
    r = c.post("/api/company/ai/test", json=form, headers=H).json()
    ok("test connection checks the form before saving", r["ok"] and "Press Save" in r["message"], str(r))
    saved = c.get("/api/company/ai", headers=H).json()
    ok("testing saved nothing", saved["provider"] == "default" and not saved["key_hint"]["azure"], str(saved))
    r = c.post("/api/company/ai/test", json={**form, "api_key": "wrong-" + secrets.token_hex(8)}, headers=H).json()
    ok("wrong key in the form: plain-words reason", not r["ok"] and r["message"].startswith("The key was not accepted"), str(r))
    ok("the key is never echoed back", GOOD_KEY not in json.dumps(r) and not re.search(r"wrong-[0-9a-f]{16}", json.dumps(r)), str(r))
    r = c.post("/api/company/ai/test", json={**form, "model": "nope"}, headers=H).json()
    ok("wrong deployment in the form: plain-words reason", not r["ok"] and "deployment name wasn't found" in r["message"], str(r))
    r = c.post("/api/company/ai/test", json={**form, "azure_endpoint": "revenueforge"}, headers=H).json()
    ok("bad endpoint caught before any call", not r["ok"] and "endpoint" in r["message"], str(r))
    r = c.post("/api/company/ai/test", json={**form, "embed_deployment": "text-embedding-3-small"}, headers=H).json()
    ok("test connection also checks the embedding deployment", r["ok"] and "Embeddings (text-embedding-3-small) work too" in r["message"], str(r))
    r = c.post("/api/company/ai/test", json={**form, "embed_deployment": "nope-embed"}, headers=H).json()
    ok("wrong embedding deployment: chat works, embeddings named as the problem", not r["ok"] and r["message"].startswith("Chat works, but the embedding"), str(r))
    ok("save works after a good test", c.put("/api/company/ai", json={**form, "embed_deployment": "text-embedding-3-small"}, headers=H).status_code == 200)
    ok("the embedding deployment is saved and shown", c.get("/api/company/ai", headers=H).json().get("embed_deployment") == "text-embedding-3-small")
    r = c.post("/api/company/ai/test", json={**form, "api_key": ""}, headers=H).json()
    ok("empty key in the form tests the saved key", r["ok"], str(r))
    r = c.post("/api/company/ai/test", headers=H).json()
    ok("no form sent: the saved settings are tested", r["ok"], str(r))
    V = {"Authorization": "Bearer " + c.post("/api/auth/users", json={"name": "V", "email": "v@qa.example", "role": "viewer",
                                                                        "password": "Qa-" + secrets.token_hex(8) + "!B2"}, headers=H).json().get("token", "x")}
    ok("non-admins can't run the test", c.post("/api/company/ai/test", json=form, headers=V).status_code in (401, 403))

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
