"""Regression tests for the 20 Nov 2026 demo dry-run findings.

1. An RFP that names a technology twice in different spellings ("Azure" and "Microsoft Azure") crashed the analysis with
   the generalised pipeline on: the registry row added for the first spelling had no `seen` count yet.
2. The knowledge graph linked a role to its skills and rates but not to the certifications its people hold
   (Project Manager -> Certified ScrumMaster).
3. Masking matched only the exact client name, so "Konkan Harbour Freight" (no "Ltd") reached AI prompts and screens.

Run: python tests/qa_demo_fixes.py
"""
import io
import os
import sys
import tempfile
import time

os.environ.update(RF_DATA_DIR=tempfile.mkdtemp(), LLM_PROVIDER="none", RADAR_REFRESH_HOURS="0", DEMO_VENDORS="false", LLM_RPM="1000")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.services.masking import mask, short_names  # noqa: E402

PASSES, FAILS = 0, []
PW = "Demo-fixes-QA-2026!"


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
        print("ok  ", name)
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


CLIENT = "Konkan Harbour Freight Ltd"


def rfp_pdf() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Table
    st = getSampleStyleSheet()
    body = [Paragraph("Request for Proposal: Customer Portal and Tracking APIs", st["Title"]),
            Paragraph(f"{CLIENT} (KHFL)", st["Normal"]),
            Paragraph("Konkan Harbour Freight wants a self-service portal for its customers. Estimated contract value "
                      "INR 2.0 - 3.0 crore excluding GST. Bids are due on 15 December 2026.", st["Normal"]),
            Table([["ID", "Requirement"],
                   ["FR-01", "The bidder shall build a responsive customer portal with React for shipment tracking."],
                   ["FR-02", "The bidder shall provide REST APIs through an API gateway."],
                   ["NFR-01", "The solution shall be hosted on Microsoft Azure in Central India."],
                   ["STF-01", "The project manager shall hold PMP; the architect shall have 10 years of Azure experience."]])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build(body)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------- 3. masking (unit)
ok("short name drops the legal form", short_names(CLIENT) == ["Konkan Harbour Freight"], short_names(CLIENT))
ok("Pvt Ltd is dropped too", short_names("Aranya Digital Labs Pvt Ltd") == ["Aranya Digital Labs"], short_names("Aranya Digital Labs Pvt Ltd"))
ok("a generic leftover is not used", short_names("The Global Ltd") == [] and short_names("Acme Co. Ltd") == [])
ok("a name without a legal form has no short form", short_names("State Bank of India") == [])
m = mask("Konkan Harbour Freight Ltd (KHFL). Konkan Harbour Freight wants a portal; konkan harbour freight staff use it.",
         CLIENT, ["KHFL"], "Client A")
ok("full name, short name and acronym are all masked", "Konkan" not in m and "konkan" not in m and "KHFL" not in m, m)
m2 = mask("Global freight volumes rose.", "The Global Ltd", [], "Client B")
ok("a generic word in the client's name isn't masked on its own", m2 == "Global freight volumes rose.", m2)

with TestClient(app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/register", json={"company_name": "Vintara Demo QA", "name": "Asha Admin", "email": "admin@demofix.example", "password": PW})
    h = {"Authorization": "Bearer " + r.json()["token"]}

    # ------------------------------------------------------------------------------------------- 2. graph
    for kind, row in (("certifications", {"name": "Certified ScrumMaster", "kind": "individual", "issuer": "Scrum Alliance"}),
                      ("certifications", {"name": "PMP", "kind": "individual", "issuer": "PMI"}),
                      ("skills", {"code": "VT-001", "role": "Project Manager", "level": "Senior", "years": 12,
                                  "skills": [{"name": "Agile", "level": 5}], "certifications": ["PMP", "Certified ScrumMaster"]}),
                      ("skills", {"code": "VT-002", "role": "Project Manager", "level": "Mid", "years": 8,
                                  "skills": [{"name": "Agile", "level": 4}], "certifications": ["Certified ScrumMaster"]}),
                      ("skills", {"code": "VT-003", "role": "Solution Architect", "level": "Senior", "years": 14,
                                  "skills": [{"name": "Microsoft Azure", "level": 5}, {"name": "React", "level": 4}],
                                  "certifications": ["Microsoft Certified: Azure Solutions Architect Expert"]}),
                      ("capabilities", {"name": "Customer portals", "description": "Portals and APIs", "technologies": ["React", "Microsoft Azure"]})):
        r = c.post(f"/api/library/{kind}", json=row, headers=h)
        ok(f"library row added ({kind})", r.status_code in (200, 201), r.text[:160])
    g = c.get("/api/graph", headers=h).json()
    pm = [n for n in g["nodes"] if n["type"] == "Resource" and "project manager" in n["label"].lower()]
    ok("Project Manager role is in the graph", bool(pm), [n["label"] for n in g["nodes"] if n["type"] == "Resource"])
    if pm:
        det = c.get("/api/graph/node", params={"key": pm[0]["id"]}, headers=h).json()
        held = {l["label"] for l in det["links"] if l["rel"] == "holds"}
        ok("Project Manager holds Certified ScrumMaster", "Certified ScrumMaster" in held, held)
        ok("Project Manager holds PMP", "PMP" in held, held)
        w = next((l for l in det["links"] if l["rel"] == "holds" and l["label"] == "Certified ScrumMaster"), None)
        ok("the link is a link to the library's certification, not a copy", w and w["type"] == "Certification", w)
    certs = [n for n in g["nodes"] if n["type"] == "Certification"]
    ok("a certification only people list still appears once", sum(1 for n in certs if "Solutions Architect Expert" in n["label"]) == 1,
       [n["label"] for n in certs])
    ok("library certifications aren't duplicated", sum(1 for n in certs if n["label"] == "Certified ScrumMaster") == 1)

    # ------------------------------------------------------------------------------------------- 1. crash + 3. masking end to end
    r = c.put("/api/company", json={"settings": {"generalised_response": True}}, headers=h)
    ok("generalised pipeline switched on for this test workspace", r.status_code == 200 and r.json()["settings"].get("generalised_response") is True)
    r = c.post("/api/deals", files={"file": ("khfl_rfp.pdf", rfp_pdf())},
               data={"confidential": "true", "ai_ack": "true", "client_name": CLIENT, "client_aliases": "KHFL", "client_alias": "Client A"}, headers=h)
    ok("deal created", r.status_code in (200, 201), r.text[:200])
    did = r.json().get("id")
    t0 = time.time()
    while time.time() - t0 < 120 and c.get(f"/api/deals/{did}", headers=h).json()["status"] == "processing":
        time.sleep(0.3)
    d = c.get(f"/api/deals/{did}", headers=h).json()
    ok("an RFP naming both 'Azure' and 'Microsoft Azure' finishes the analysis", d["status"] not in ("processing", "error", "failed"),
       f"{d['status']} {d.get('error') or d.get('status_detail') or ''}"[:300])
    reqs = c.get(f"/api/deals/{did}/requirements", headers=h).json()
    ok("requirements were extracted", len(reqs) >= 3, len(reqs))
    shown = " ".join(str(q) for q in reqs) + str(c.get(f"/api/deals/{did}/stages/requirements", headers=h).json())
    ok("the short client name isn't shown on screen", "Konkan Harbour Freight" not in shown and "konkan" not in shown.lower(),
       shown[shown.lower().find("konkan") - 60: shown.lower().find("konkan") + 60] if "konkan" in shown.lower() else "")
    r = c.post(f"/api/deals/{did}/rerun", json={"from_stage": "requirements"}, headers=h)
    ok("re-run from the start accepted", r.status_code == 200, r.text[:160])
    time.sleep(0.5)
    t0 = time.time()
    while time.time() - t0 < 120 and c.get(f"/api/deals/{did}", headers=h).json()["status"] == "processing":
        time.sleep(0.3)
    ok("a second run of the same RFP also finishes (registry already has the terms)",
       c.get(f"/api/deals/{did}", headers=h).json()["status"] not in ("processing", "error", "failed"))

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for x in FAILS:
    print("  -", x)
sys.exit(1 if FAILS else 0)
