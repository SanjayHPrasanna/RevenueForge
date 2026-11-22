"""The bid verdict says what the company can show, not what a plan promises (22 Nov 2026).

A workspace with an empty knowledge library uploaded an RFP and was told "Bid with mitigations, 73%": every requirement was a
gap, but each gap had a suggested fix and each fix earned up to 85% credit. These checks pin the honest behaviour:
  * an empty library is "Can't assess", with readiness 0 and no "with mitigations" figure above it
  * a thin library is "No bid", whatever the plan says
  * a plan adds at most PLAN_CAP points, and "Bid with mitigations" needs a real base today
  * every verdict comes with its reason, and the dashboard and deal list use today's readiness

Run: python tests/qa_honest_verdict.py
"""
import json
import os
import sys
import tempfile
import time

os.environ.update(RF_DATA_DIR=tempfile.mkdtemp(), LLM_PROVIDER="none", RADAR_REFRESH_HOURS="0", DEMO_VENDORS="false", LLM_RPM="1000")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.matching import PLAN_CAP, CompanyKB, analyze_gaps  # noqa: E402

PASSES, FAILS = 0, []
PW = "Honest-verdict-QA-2026!"
RFP = open(os.path.join(os.path.dirname(__file__), "fixtures", "khfl_portal_rfp.pdf"), "rb").read()


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
        print("ok  ", name)
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


def req(code, status, rec="", sub="Application Development"):
    return {"code": code, "text": f"The bidder shall do {code}.", "priority": "Mandatory", "category": "Functional", "subcategory": sub,
            "technologies": [], "match_status": status, "match": {"technologies_missing": []}, "gap": {"recommended": rec}}


# ------------------------------------------------------------------------------------------- unit: the scoring rules
some = CompanyKB("X", capabilities=[{"id": "c1", "name": "Portals", "technologies": ["React"]}])
all_gap = [req(f"R{i}", "gap") for i in range(10)]
ai_fix = {r["code"]: {"type": "Define method", "detail": "write it down", "effort": "", "cost": ""} for r in all_gap}
g = analyze_gaps([dict(r) for r in all_gap], CompanyKB("Empty"), "build_run", ai_fix)
ok("empty library: Can't assess", g["verdict"] == "Can't assess" and g["library_empty"], g["verdict"])
ok("empty library: nothing above today's 0%", g["readiness"] == 0 and g["mitigated_readiness"] == 0, (g["readiness"], g["mitigated_readiness"]))
ok("empty library: the reason says so", "empty" in g["verdict_reason"].lower(), g["verdict_reason"])
g = analyze_gaps([dict(r) for r in all_gap], some, "build_run", ai_fix)
ok("every requirement a gap with a 'fix' for each: No bid, not Bid with mitigations", g["verdict"] == "No bid", (g["verdict"], g["readiness"], g["mitigated_readiness"]))
ok("a plan adds at most PLAN_CAP points", g["mitigated_readiness"] <= g["readiness"] + PLAN_CAP, (g["readiness"], g["mitigated_readiness"]))
ok("the No bid reason gives today's figure", f"{g['readiness']}%" in g["verdict_reason"], g["verdict_reason"])
half = [req(f"S{i}", "strong") for i in range(6)] + [req(f"P{i}", "partial") for i in range(2)] + [req(f"G{i}", "gap") for i in range(2)]
g = analyze_gaps([dict(r) for r in half], some, "build_run", {})
ok("a strong base today can be a bid", g["verdict"] in ("Bid", "Bid with mitigations", "Bid with partners"), (g["verdict"], g["readiness"], g["mitigated_readiness"]))
mid = [req(f"S{i}", "strong") for i in range(3)] + [req(f"P{i}", "partial") for i in range(4)] + [req(f"G{i}", "gap") for i in range(3)]
g = analyze_gaps([dict(r) for r in mid], some, "build_run", {})
ok("'with mitigations' only from a real base (>= 50% today)", g["verdict"] not in ("Bid with mitigations", "Bid with partners") or g["readiness"] >= 50, (g["verdict"], g["readiness"]))
ok("every verdict has a reason", bool(g.get("verdict_reason")), g)

# ------------------------------------------------------------------------------------------- end to end
def run(c, h, gen):
    c.put("/api/company", json={"settings": {"generalised_response": gen}}, headers=h)
    did = c.post("/api/deals", files={"file": ("khfl.pdf", RFP)}, data={"name": "Portal and tracking APIs", "client_name": "Konkan Harbour Freight Ltd",
                                                                       "confidential": "true", "engagement_type": "build_run"}, headers=h).json()["id"]
    t0 = time.time()
    while time.time() - t0 < 180 and c.get(f"/api/deals/{did}", headers=h).json()["status"] == "processing":
        time.sleep(0.3)
    return did, c.get(f"/api/deals/{did}", headers=h).json()


with TestClient(app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/register", json={"company_name": "Empty Library Co", "name": "Eve Admin", "email": "eve@empty.example", "password": PW})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    for gen in (False, True):
        did, d = run(c, h, gen)
        mode = "new mode" if gen else "old mode"
        ok(f"E2E empty library, {mode}: the analysis finishes", d["status"] == "in_review", d["status"])
        ok(f"E2E empty library, {mode}: verdict is Can't assess, not a bid", d["verdict"] == "Can't assess", (d["verdict"], d["readiness"], d["mitigated_readiness"]))
        ok(f"E2E empty library, {mode}: readiness 0 with nothing promised on top", d["readiness"] == 0 and d["mitigated_readiness"] == 0, (d["readiness"], d["mitigated_readiness"]))
        ok(f"E2E empty library, {mode}: the deal carries the reason", "empty" in (d.get("verdict_reason") or "").lower(), d.get("verdict_reason"))
    dash = c.get("/api/dashboard", headers=h).json()
    ok("E2E the dashboard average is today's readiness", dash["kpis"]["avg_readiness"] == 0, dash["kpis"])
    ok("E2E the deal list shows today's readiness", all(x["readiness"] == 0 for x in dash.get("deals", [])), [x.get("readiness") for x in dash.get("deals", [])])

    # one capability in an unrelated field: a thin library is a No bid, whatever the plan says
    c.post("/api/library/capabilities", json={"name": "Payroll processing", "description": "Monthly payroll for SMEs", "technologies": ["Excel"]}, headers=h)
    c.post("/api/library/skills", json={"code": "E-1", "role": "Payroll Analyst", "level": "Mid", "years": 4, "skills": [{"name": "Excel", "level": 4}]}, headers=h)
    did, d = run(c, h, True)
    ok("E2E thin, unrelated library: No bid", d["verdict"] == "No bid", (d["verdict"], d["readiness"], d["mitigated_readiness"]))
    ok("E2E thin library: the plan adds at most PLAN_CAP points", d["mitigated_readiness"] <= d["readiness"] + PLAN_CAP, (d["readiness"], d["mitigated_readiness"]))

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for x in FAILS:
    print("  -", x)
sys.exit(1 if FAILS else 0)
