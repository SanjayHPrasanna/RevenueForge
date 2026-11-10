"""AI engine resilience against a simulated Gemini (no network, no real key).

Run: python tests/qa_ai_fallback.py
Covers: quick replies ask Gemini 3+ for minimal thinking (older models: thinking off); a model Google calls overloaded is
skipped for 10 minutes and the next model is used; timeouts name the model; Maahi's error messages say what went wrong.
"""
import json
import os
import sys
import tempfile
import time

os.environ.update(LLM_PROVIDER="gemini", GEMINI_API_KEY="test-key-not-real", RF_DATA_DIR=tempfile.mkdtemp(), LLM_RPM="1000",
                  RADAR_REFRESH_HOURS="0", DEMO_VENDORS="false")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.services import llm  # noqa: E402
from app.routers.assistant import _unavailable  # noqa: E402

PASSES, FAILS = 0, []


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
        print("ok  ", name)
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


llm.time.sleep = lambda s: None
_real = httpx.Client
calls: list[tuple[str, dict | None]] = []


def serve(models, handler):
    def h(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]} for m in models]})
        model = req.url.path.split("/")[-1].split(":")[0]
        tc = json.loads(req.content)["generationConfig"].get("thinkingConfig")
        calls.append((model, tc))
        return handler(model, tc)
    llm.httpx.Client = lambda timeout=None: _real(transport=httpx.MockTransport(h), timeout=timeout)
    llm.reset_state()
    calls.clear()


def answer(text="Hello"):
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


# ---------------------------------------------------------------- thinking settings for quick replies
def g3(model, tc):
    if tc and "thinkingBudget" in tc:
        return httpx.Response(400, json={"error": {"message": "thinking_budget is not supported"}})
    if tc is None:
        raise httpx.ReadTimeout("full thinking is slow")
    return answer()


serve(["gemini-3.8-flash", "gemini-3.7-flash"], g3)
out = llm.complete("s", "hi", fast=True, attempts=2, timeout=5, max_wait=0)
ok("Gemini 3 quick reply asks for minimal thinking", out == "Hello" and calls[0] == ("gemini-3.8-flash", {"thinkingLevel": "minimal"}), str(calls))

serve(["gemini-3.8-flash"], lambda m, tc: httpx.Response(400, json={}) if tc == {"thinkingLevel": "minimal"} else answer())
llm.complete("s", "hi", fast=True, attempts=1, timeout=5)
ok("minimal refused: low is tried next", [c[1] for c in calls] == [{"thinkingLevel": "minimal"}, {"thinkingLevel": "low"}], str(calls))

serve(["gemini-2.5-flash"], lambda m, tc: answer())
llm.complete("s", "hi", fast=True, attempts=1, timeout=5)
ok("older model: thinking switched off the old way", calls[0][1] == {"thinkingBudget": 0}, str(calls))

# ---------------------------------------------------------------- overloaded newest model
busy = lambda m, tc: httpx.Response(503, json={"error": {"code": 503, "message": "This model is currently experiencing high demand.",
                                                          "status": "UNAVAILABLE"}}) if m == "gemini-3.8-flash" else answer('{"ok": true}')
serve(["gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.8-flash-lite"], busy)
res = llm.complete_json("s", "x")
ok("deal step: overloaded newest model falls back to the previous Flash", res == {"ok": True} and [c[0] for c in calls] == ["gemini-3.8-flash", "gemini-3.7-flash"], str(calls))
calls.clear()
llm.complete("s", "x")
ok("the overloaded model is skipped on the next call", [c[0] for c in calls] == ["gemini-3.7-flash"], str(calls))
calls.clear()
llm.complete("s", "x", fast=True, attempts=2, timeout=5, max_wait=1)
ok("chat also skips it", [c[0] for c in calls] == ["gemini-3.7-flash"], str(calls))
st = llm._st(llm.current_profile())
for m in list(st["cooling"]):
    st["cooling"][m] = time.time() - 1
calls.clear()
llm.complete("s", "x")
ok("after the cool-down the newest model is tried again", calls[0][0] == "gemini-3.8-flash", str(calls))

# ---------------------------------------------------------------- timeouts and messages
serve(["gemini-3.8-flash"], lambda m, tc: (_ for _ in ()).throw(httpx.ReadTimeout("slow")))
try:
    llm.complete("s", "x", fast=True, attempts=1, timeout=5)
    ok("timeout raises", False)
except llm.LLMUnavailable as e:
    ok("timeout message names the model", "gemini-3.8-flash timed out after 5s" in str(e), str(e))

cases = {
    "AI call failed: gemini-3.8-flash timed out after 20s": "taking too long",
    "AI call failed: HTTP 429: gemini-3.8-flash: RESOURCE_EXHAUSTED": "allowance",
    "AI call failed: HTTP 403: PERMISSION_DENIED": "key isn't accepted",
    "AI call failed: HTTP 400: gemini-3.8-flash: Invalid JSON payload": "refused the request",
    "AI call failed: HTTP 503: gemini-3.8-flash: experiencing high demand": "busy",
}
for msg, want in cases.items():
    ok(f"Maahi error for '{msg[16:50]}…' says '{want}'", want in _unavailable(Exception(msg)).detail, _unavailable(Exception(msg)).detail)

# ---------------------------------------------------------------- long conversations never block the next question
from app.routers.assistant import ChatRequest  # noqa: E402

req = ChatRequest(messages=[{"role": "user", "content": "List our people"}, {"role": "assistant", "content": "x" * 5000},
                            {"role": "user", "content": "Is anyone available for a new Power BI project?"}])
ok("a long earlier answer is shortened, not rejected", len(req.messages) == 3 and len(req.messages[1].content) <= 1502, str([len(m.content) for m in req.messages]))
req = ChatRequest(messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a" * 1400}] * 12 + [{"role": "user", "content": "last"}])
ok("a long conversation keeps the newest turns within the limit",
   req.messages[-1].content == "last" and sum(len(m.content) for m in req.messages) <= 6000 and len(req.messages) <= 10, str(len(req.messages)))
try:
    ChatRequest(messages=[{"role": "user", "content": "y" * 1300}])
    ok("an over-long question is refused", False)
except Exception as e:
    ok("an over-long question is refused with a plain reason", "keep your question under 1,200 characters" in str(e), str(e)[:200])

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
