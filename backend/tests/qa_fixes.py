"""Regression tests for the QA report of 12 Nov 2026 (findings D1–D26).

Rebuilds the tester's scenario: a PDF RFP made with ReportLab (wrapped title, key-facts table, budget, a Kafka requirement,
an ID repeated in the eligibility section), a company library that says "Apache Kafka", then runs a deal end to end.

Run: python tests/qa_fixes.py
"""
import io
import json
import os
import re
import secrets
import sys
import tempfile
import time

os.environ.update(RF_DATA_DIR=tempfile.mkdtemp(), LLM_PROVIDER="none", RADAR_REFRESH_HOURS="0", DEMO_VENDORS="false", LLM_RPM="1000")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASSES, FAILS = 0, []


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
        print("ok  ", name)
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


def docx_text(b):
    from docx import Document
    d = Document(io.BytesIO(b))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def rfp_pdf() -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    st = getSampleStyleSheet()
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.black)])

    def table(rows, widths=None):
        t = Table(rows, colWidths=widths)
        t.setStyle(grid)
        return t
    reqs = [["ID", "Requirement", "Priority"],
            ["FR-01", "The platform shall provide a patient portal for appointment booking and reminders.", "Mandatory"],
            ["FR-02", "The bidder shall integrate the portal with the hospital information system using HL7 FHIR APIs.", "Mandatory"],
            ["FR-03", "The solution shall expose all services through an API gateway with OAuth 2.0 security.", "Mandatory"],
            ["FR-04", "The bidder shall deliver Android and iOS mobile apps for patients.", "Mandatory"],
            ["FR-05", "The platform shall send SMS and email notifications for appointments.", "Desirable"],
            ["FR-06", "Event streaming between clinical systems shall use Apache Kafka.", "Mandatory"],
            ["SEC-01", "All patient data shall be encrypted at rest and in transit.", "Mandatory"],
            ["SEC-02", "The solution shall enforce role-based access control with multi-factor authentication.", "Mandatory"],
            ["NFR-01", "The portal shall support 5,000 concurrent users with page loads under 2 seconds.", "Mandatory"],
            ["NFR-02", "The platform shall be available 99.9% of the time, measured monthly.", "Mandatory"]]
    story = [Paragraph("Request for Proposal", st["Heading2"]),
             Paragraph("Digital Patient Engagement and Integration Platform for Hospitals", st["Title"]),
             Paragraph("Sahyadri Health Network", st["Heading3"]), Spacer(1, 12),
             Paragraph("1. Key facts", st["Heading2"]),
             table([["Item", "Detail"], ["RFP reference", "SHN/IT/2026/014"], ["Date of issue", "16 November 2026"],
                    ["Proposal due date", "11 December 2026"], ["Contract period", "9 months build + 24 months support"],
                    ["Indicative budget", "INR 3.5 – 4.5 crore"], ["Licensing", "SHN has an enterprise agreement for Microsoft Azure"]]),
             Spacer(1, 12), Paragraph("2. Background", st["Heading2"]),
             Paragraph("Sahyadri Health Network runs 14 hospitals in Maharashtra and wants one digital front door for its patients.", st["Normal"]),
             PageBreak(), Paragraph("3. Requirements", st["Heading2"]), table(reqs, [50, 360, 70]),
             Spacer(1, 12), Paragraph("4. Eligibility", st["Heading2"]),
             table([["ID", "Condition"], ["SEC-01", "Bidders must confirm SEC-01 compliance in the declaration form."]], [50, 430]),
             Paragraph("5. Evaluation", st["Heading2"]),
             Paragraph("Proposals will be evaluated on technical merit and price.", st["Normal"])]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4).build(story)
    return buf.getvalue()


def csv(rows):
    return "\n".join(",".join(f'"{c}"' for c in r) for r in rows).encode()


def pw():
    return "Qa-" + secrets.token_hex(8) + "!A1"


# ------------------------------------------------------------------------------------------- unit checks (no server)
from app.services import knowledge as K  # noqa: E402
from app.services.extraction import _tidy, find_budget  # noqa: E402
from app.services.masking import mask  # noqa: E402
from app.services.onboarding import _holders, _split_list  # noqa: E402
from app.services.tender_feeds import _clean  # noqa: E402

ok("D1 acronym masked when text lost its spaces", mask("SHNhasanenterpriseagreement", "Sahyadri Health Network", ["SHN"], "Client A").startswith("Client A"))
ok("D1 longer capitalised word left alone", mask("FASHN and SHNX", "Sahyadri Health Network", ["SHN"], "Client A") == "FASHN and SHNX")
ok("D4 budget range in crore", (find_budget("Indicative budget | INR 3.5 – 4.5 crore") or {}).get("high") == 45_000_000)
ok("D4 budget in lakhs to crore", (find_budget("Budget: Rs. 80 lakhs to 1.2 crore") or {}).get("low") == 8_000_000)
ok("D4 a year near 'budget' isn't a budget", find_budget("budget approval expected in 2026") is None)
ok("D5 Apache Kafka and Kafka are one technology", K.canonical_tech("Apache Kafka") == K.canonical_tech("kafka") == "Kafka")
ok("D9 holders: a name with an employee code is one person", _holders("Lakshmi Varma (KD002)") == 1 and _holders("KD008") == 1 and _holders("4") == 4)
ok("D12 duplicate RFP ID keeps the first row", len(_tidy([{"text": "Encrypt all data at rest", "source_ref": "SEC-01", "section": "3", "block_idx": 1},
                                                        {"text": "Confirm SEC-01 in the form", "source_ref": "SEC-01", "section": "4", "block_idx": 2}])) == 1)
ok("D12 sentence fragment dropped", _tidy([{"text": "must explain why", "source_ref": "", "section": "", "block_idx": 1}]) == [])
ok("D12 short real requirement kept", len(_tidy([{"text": "Provide 24x7 support", "source_ref": "", "section": "", "block_idx": 1}])) == 1)
ok("D17 CPV codes survive the phone scrubber", "72262000-9" in _clean("(CPV: 72262000-9 Software development services)"))
ok("D17 real phone numbers still removed", "[phone removed]" in _clean("Call +30 210 123 4567"))
ok("D21 names kept as uploaded", _split_list("Android and iOS release, CI/CD; Retail & Distribution") == ["Android and iOS release", "CI/CD", "Retail & Distribution"])

# ------------------------------------------------------------------------------------------- the QA scenario, end to end
with TestClient(app) as c:
    P = pw()
    reg = c.post("/api/auth/register", json={"company_name": "Kestrel Test Works", "name": "Test Admin", "email": "admin@kestrel.example",
                                             "password": P, "kind": "vendor"}).json()
    A = {"Authorization": "Bearer " + reg["token"]}
    c.put("/api/company", json={"about": "Integration and digital health engineering.", "industry": "IT services", "currency": "INR"}, headers=A)

    # D11 margin floor above target
    r = c.put("/api/company", json={"settings": {"min_margin": 40}}, headers=A)
    ok("D11 margin floor above target refused", r.status_code == 400 and "can't be above" in r.text, r.text[:160])
    ok("D11 a sensible floor saves", c.put("/api/company", json={"settings": {"min_margin": 18, "target_margin": 28}}, headers=A).status_code == 200)

    def upload(kind, name, data):
        r = c.post(f"/api/library/{kind}/upload", files={"file": (name, data)}, headers=A)
        assert r.status_code == 200, r.text
        r2 = c.post(f"/api/library/uploads/{r.json()['id']}/import", json={}, headers=A)
        assert r2.status_code == 200, r2.text

    upload("capabilities", "caps.csv", csv([["Capability", "Description", "Technologies", "Industries"],
                                            ["Integration Platform Engineering", "Event-driven integration, APIs and gateways for hospitals",
                                             "Apache Kafka; Azure API Management; HL7 FHIR; OAuth 2.0", "Healthcare; Retail & Distribution"],
                                            ["Mobile Apps", "Patient apps", "Android and iOS release; React", "Healthcare"],
                                            ["DevSecOps", "Secure delivery pipelines, encryption and access control", "Azure DevOps; MFA; IAM", "Healthcare"]]))
    upload("skills", "skills.csv", csv([["Employee Code", "Name", "Role", "Skills", "Proficiency", "Availability"],
                                        ["KD001", "Asha Rao", "Engagement Manager", "PMP; Agile", "4", "100"],
                                        ["KD002", "Lakshmi Varma", "Integration Engineer", "Apache Kafka; Azure API Management; HL7 FHIR", "4", "100"],
                                        ["KD003", "Ravi Kumar", "Integration Engineer", "Kafka; MuleSoft", "3", "100"],
                                        ["KD004", "Meera Shah", "Solution Architect", "Azure API Management; Kafka", "4", "100"],
                                        ["KD005", "Arjun Nair", "QA Engineer", "JMeter; Selenium", "3", "100"]]))
    upload("certifications", "certs.csv", csv([["Certification", "Type", "Issuer", "Holders"],
                                               ["ISO 27001", "company", "BSI", "—"], ["Azure Solutions Architect", "individual", "Microsoft", "Lakshmi Varma (KD002)"],
                                               ["Confluent Kafka Developer", "individual", "Confluent", "KD003"]]))
    upload("rates", "rates.csv", csv([["Role", "Location", "Day rate", "Day cost", "Currency"],
                                      ["Engagement Manager", "Offshore", "40000", "21000", "INR"], ["Integration Engineer", "Offshore", "22000", "12000", "INR"],
                                      ["Solution Architect", "Offshore", "38000", "20000", "INR"], ["QA Engineer", "Offshore", "16000", "8500", "INR"],
                                      ["Support Engineer", "Offshore", "14000", "7500", "INR"]]))
    c.post("/api/library/case_studies", json={"title": "Hospital event streaming backbone", "industry": "Healthcare", "region": "India",
                                              "summary": "Kafka-based integration across 9 hospitals", "technologies": ["Apache Kafka", "HL7 FHIR"],
                                              "outcomes": ["40% faster lab results"]}, headers=A)

    lib = c.get("/api/library/certifications", headers=A).json()
    holders = {x["name"]: x["holders"] for x in lib}
    ok("D9 'Lakshmi Varma (KD002)' counts as 1 holder", holders.get("Azure Solutions Architect") == 1, holders)
    ok("D9 'KD003' counts as 1 holder", holders.get("Confluent Kafka Developer") == 1, holders)
    caps = {x["name"]: x for x in c.get("/api/library/capabilities", headers=A).json()}
    ok("D21 'Azure DevOps' kept as uploaded", "Azure DevOps" in caps["DevSecOps"]["technologies"], caps["DevSecOps"]["technologies"])
    ok("D21 'Android and iOS release' kept whole", "Android and iOS release" in caps["Mobile Apps"]["technologies"], caps["Mobile Apps"]["technologies"])
    ok("D21 'Retail & Distribution' kept whole", "Retail & Distribution" in caps["Integration Platform Engineering"]["industries"])
    people = {x["code"]: x for x in c.get("/api/library/skills", headers=A).json()}
    ok("D21 skill names kept as uploaded", any(s["name"] == "Apache Kafka" for s in people["KD002"]["skills"]))

    ob = c.get("/api/company", headers=A).json().get("onboarding", {})
    ok("D22 onboarding has an Accelerators step", "accelerators" in ob.get("steps", {}), list(ob.get("steps", {})))

    # ---- the deal
    r = c.post("/api/deals", files={"file": ("SHN_RFP.pdf", rfp_pdf())},
               data={"client_name": "Sahyadri Health Network", "client_alias": "Client A", "confidential": "true",
                     "client_aliases": "SHN, Sahyadri, sahyadri-health.example"}, headers=A)
    ok("deal created", r.status_code == 200, r.text[:200])
    D = r.json()["id"]
    for _ in range(600):
        deal = c.get(f"/api/deals/{D}", headers=A).json()
        if deal["status"] != "processing":
            break
        time.sleep(0.3)
    ok("pipeline finished", deal["status"] == "in_review", deal["status"])
    if not deal.get("client_aliases") or "SHN" not in (deal.get("client_aliases") or []):
        c.patch(f"/api/deals/{D}", json={"client_aliases": ["SHN", "Sahyadri", "sahyadri-health.example"]}, headers=A)
        deal = c.get(f"/api/deals/{D}", headers=A).json()
    meta = deal.get("meta") or {}

    ok("D20 full title read from a 2-line cover title", "Integration Platform" in (deal["name"] or ""), deal["name"])
    ok("D3 due date read from the key-facts table", "11 December 2026" in (deal.get("due_date") or ""), deal.get("due_date"))
    ok("D3 support term 24 months", meta.get("contract_term_months") == 24, meta.get("contract_term_months"))
    ok("D3 build 9 months", meta.get("build_months") == 9, meta.get("build_months"))
    ok("D4 budget read", (meta.get("budget") or {}).get("high") == 45_000_000, meta.get("budget"))

    src = c.get(f"/api/deals/{D}/source", headers=A).text
    ok("D2 table text keeps its spaces", "9 months build + 24 months support" in src and "Contractperiod" not in src, re.findall(r"Contract[^|\"]{0,40}", src)[:2])
    ok("D1 'SHN' masked in the source view", not re.search(r"(?<![A-Z])SHN(?![A-Z])", src) and "Sahyadri" not in src, re.findall(r".{20}SHN.{20}", src)[:2])

    reqs = c.get(f"/api/deals/{D}/requirements", headers=A).json()
    by = {}
    for x in reqs:
        by.setdefault(x.get("source_ref") or x["code"], []).append(x)
    ok("D12 SEC-01 appears once", len(by.get("SEC-01", [])) == 1, [x["text"][:50] for x in by.get("SEC-01", [])])
    fr6 = (by.get("FR-06") or [{}])[0]
    ok("D5 Kafka requirement isn't a gap", fr6.get("match_status") in ("strong", "partial"), fr6.get("match_status"))
    ok("D5 Kafka not listed as missing", "Kafka" not in (fr6.get("match") or {}).get("technologies_missing", []), (fr6.get("match") or {}).get("technologies_missing"))
    ok("D5 Kafka people found", (fr6.get("match") or {}).get("people_count", 0) >= 2, (fr6.get("match") or {}).get("people_count"))

    arch = c.get(f"/api/deals/{D}/stages/architecture", headers=A).json()["data"]
    choices = {x["area"]: x for x in arch.get("choices", [])}
    ok("D14 API gateway is the one with the most evidence", (choices.get("API management") or {}).get("choice") == "Azure API Management",
       choices.get("API management"))
    ok("D5 architecture doesn't claim no Kafka skills", "No in-house Kafka" not in json.dumps(arch))

    est = c.get(f"/api/deals/{D}/stages/estimation", headers=A).json()["data"]
    ok("D3 estimate uses 9-month build", est.get("build_months") == 9, est.get("build_months"))
    ok("D3 estimate uses 24-month run", est.get("run_months") == 24, est.get("run_months"))
    pm = [t for t in est["team"] if t["role"] == "Project Manager"]
    ok("D13 Project Manager covered by the Engagement Manager", not pm or all(t["assigned"] for t in pm), [(t["phase"], t["fte"], t["assigned"], t["unfilled"]) for t in pm])

    pr = c.get(f"/api/deals/{D}/stages/pricing", headers=A).json()["data"]
    ok("D4 pricing compares with the budget", (pr.get("budget") or {}).get("high") and all("vs_budget_pct" in s for s in pr["scenarios"]), pr.get("budget"))
    bench = [l for l in pr["lines"] if l["rate_source"].startswith("Benchmark")]
    ok("D13 missing roles use benchmarks scaled to the rate card", all(l["rate_source"] == "Benchmark scaled to your rate card" for l in bench), {l["role"]: l["rate_source"] for l in bench})
    pm_line = next((l for l in pr["lines"] if l["role"] == "Project Manager"), None)
    if pm_line:
        ok("D13 Project Manager day rate in line with the rate card", pm_line["day_rate"] < 80000, pm_line["day_rate"])

    # ---- approvals: in order, and an over-budget price needs confirming
    r = c.post(f"/api/deals/{D}/stages/gaps/approve", headers=A)
    ok("D15 a stage can't be approved before the ones it's built from", r.status_code == 400 and "first" in r.text, r.text[:120])
    reviewed_before = c.get("/api/dashboard", headers=A).json()["kpis"]["reviewed"]
    for stg in ("requirements", "matching", "gaps", "architecture", "estimation"):
        r = c.post(f"/api/deals/{D}/stages/{stg}/approve", headers=A)
        ok(f"approve {stg} in order", r.status_code == 200, r.text[:120])
    reviewed_after = c.get("/api/dashboard", headers=A).json()["kpis"]["reviewed"]
    ok("D8 approving requirements doesn't mark them reviewed", reviewed_after == reviewed_before, (reviewed_before, reviewed_after))
    first = reqs[0]
    c.patch(f"/api/deals/{D}/requirements/{first['id']}", json={"verified": True}, headers=A)
    ok("D8 a row a person checks does count", c.get("/api/dashboard", headers=A).json()["kpis"]["reviewed"] == reviewed_after + 1)

    pr = c.get(f"/api/deals/{D}/stages/pricing", headers=A).json()["data"]
    sel = next(s for s in pr["scenarios"] if s["name"] == pr.get("selected", "Target"))
    r = c.post(f"/api/deals/{D}/stages/pricing/approve", headers=A)
    if sel["price"] > pr["budget"]["high"]:
        ok("D4 over-budget price needs confirming", r.status_code == 409 and "above the budget" in r.text, r.text[:160])
        r = c.post(f"/api/deals/{D}/stages/pricing/approve", json={"despite_over_budget": True, "despite_open_notes": True}, headers=A)
    ok("pricing approved", r.status_code == 200, r.text[:120])
    r = c.post(f"/api/deals/{D}/stages/proposal/approve", headers=A)
    ok("proposal approved", r.status_code == 200, r.text[:120])

    x = c.get(f"/api/deals/{D}/download/proposal", headers=A)
    t = docx_text(x.content) if x.status_code == 200 else ""
    ok("proposal downloads", x.status_code == 200 and t, x.status_code)
    ok("D7 no hiring status in the proposal", "to hire" not in t.lower(), re.findall(r".{30}to hire.{10}", t, re.I)[:2])
    ok("D7 no employee codes in the proposal", not re.search(r"\bKD\d{3}\b", t), re.findall(r".{20}KD\d{3}.{10}", t)[:2])
    ok("D7 no internal REQ codes in the proposal", not re.search(r"\bREQ-\d{3}\b", t), re.findall(r"REQ-\d{3}", t)[:3])
    ok("D7 no internal evidence notes in the proposal", not re.search(r"reference project, demo|named expert to (?:our|the) response", t, re.I))
    ok("D20 proposal cover has the full title", "Integration Platform" in t)
    ok("D22 no '1 engineers'", not re.search(r"\b1 engineers\b", t))

    # ---- outcome and win/loss
    r = c.patch(f"/api/deals/{D}", json={"status": "won", "final_value": -5000}, headers=A)
    ok("D24 negative value refused", r.status_code == 400, r.status_code)
    r = c.patch(f"/api/deals/{D}", json={"status": "won", "final_value": 42_000_000}, headers=A)
    ok("mark as won", r.status_code == 200, r.text[:120])
    wl = c.get("/api/insights/winloss", headers=A).json()
    ok("D10 won value is the recorded contract value", abs(wl["totals"]["won_value"] - 42_000_000) < 2, wl["totals"])
    dash = c.get("/api/dashboard", headers=A).json()
    ok("D10 won deal left the pipeline", dash["kpis"]["pipeline_value"] == 0, dash["kpis"].get("pipeline_value"))

    # ---- public pages
    sm = c.get("/sitemap.xml")
    ok("D25 sitemap lists the public pages", sm.status_code == 200 and "/trust</loc>" in sm.text and "/app" not in sm.text, sm.text[:200])
    ok("D25 robots.txt points at the sitemap", "Sitemap:" in c.get("/robots.txt").text)

# ------------------------------------------------------------------------------------------- tender ranking
from app.services.radar import score_all  # noqa: E402
from app.services.matching import CompanyKB  # noqa: E402


class _T:
    def __init__(self, title, description="", language="en"):
        self.title, self.description, self.language, self.categories = title, description, language, []
        self.region, self.country = "", ""


kb = CompanyKB(name="Kestrel", capabilities=[{"name": "Application Managed Services", "description": "24x7 managed services and support for business applications",
                                              "technologies": ["ServiceNow"], "industries": []}], case_studies=[], accelerators=[], certifications=[], employees=[], rates=[])
f = score_all(kb, [_T("Rahmenvertrag managed print services", language="de"), _T("Managed print services for 40 offices")])
ok("D16 a print contract isn't ranked as a fit for application managed services", all(x["score"] < 35 for x in f), [x["score"] for x in f])
f2 = score_all(kb, [_T("Application managed services", language="de")])
ok("D16 title-only notices capped below full notices", f2[0]["score"] <= 45, f2[0]["score"])

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for x in FAILS:
    print("  -", x)
sys.exit(1 if FAILS else 0)
