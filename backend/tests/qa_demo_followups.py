"""Regression tests for the 20 Nov 2026 live walkthrough (Vintara Technologies, KHFL customer-portal RFP, generalised pipeline on).

Each block is one finding from that run:
  T1  "STF-01: The project manager shall hold PMP or PRINCE2 ...; the solution architect shall have 10 years ..." added a phantom
      "Lead" role needing a certificate called "STF", and the PM role needed both PMP and PRINCE2, so it stayed empty.
  T2  Team roles named slightly differently from the rate card ("Full Stack Developer" / "Full-stack Developer") were priced
      at benchmark rates, with a note telling the user to add rows they already have.
  T3  The bank guarantee was costed twice: once as a commitment, once as a "licence" that blocked pricing until quoted.
  T4  "API", "APIs", "ETA", "RPO 1", "RTO 4", "INR 10" were listed as technologies the company lacks ("Hire: API").
  T5  PMP / PRINCE2 were "missing" next to evidence that the company holds them.
  T6  The AI's citations only counted on an exact match, so real evidence was "not named" and strong ratings were capped.
  T7  "Consortium bids are not allowed" was read as allowing consortia.
  T8  The turnover condition was "unknown" though the company profile states the turnover.
  T9  The client proposal carried internal notes (rate sources, contingency, hires, quotes), talked about a migration the RFP
      doesn't ask for, listed fully-met / partial / gap counts, and left service levels "to be agreed".

Run: python tests/qa_demo_followups.py
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
from app.services import commercial, docgen, gates, profile, teamplan  # noqa: E402
from app.services.matching import CompanyKB, _cited  # noqa: E402
from app.services.solution import _rate_for  # noqa: E402

PASSES, FAILS = 0, []
PW = "Demo-followups-QA-2026!"


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
        print("ok  ", name)
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


STF = ("STF-01: The project manager shall hold PMP or PRINCE2 and have at least 8 years of experience; the solution architect shall "
       "have at least 10 years of Microsoft Azure experience.")
PEOPLE = [
    {"code": "VT-001", "role": "Delivery Head", "years": 20, "skills": [{"name": "Programme Management", "level": 5}], "certifications": ["PMP"], "availability": 50},
    {"code": "VT-002", "role": "Project Manager", "years": 12, "skills": [{"name": "Agile", "level": 5}, {"name": "Project Management", "level": 5}],
     "certifications": ["PMP", "Certified ScrumMaster"], "availability": 100},
    {"code": "VT-004", "role": "Solution Architect", "years": 14, "skills": [{"name": "Microsoft Azure", "level": 5}, {"name": "System Architecture", "level": 5}],
     "certifications": ["Microsoft Certified: Azure Solutions Architect Expert"], "availability": 100},
    {"code": "VT-006", "role": "Full-stack Developer", "years": 6, "skills": [{"name": "React", "level": 5}], "certifications": [], "availability": 100},
    {"code": "VT-007", "role": "Full-stack Developer", "years": 5, "skills": [{"name": "React", "level": 4}], "certifications": [], "availability": 100},
    {"code": "VT-025", "role": "Support Engineer", "years": 5, "skills": [{"name": "Application Support", "level": 4}], "certifications": [], "availability": 100},
]
RATES = [{"role": r, "location": "Offshore", "day_rate": dr, "day_cost": dc, "currency": "INR"} for r, dr, dc in
         (("Project Manager", 20238, 11905), ("Solution Architect", 26984, 15873), ("Full-stack Developer", 12143, 7143),
          ("Backend & API Engineer", 13493, 7937), ("QA Engineer", 9445, 5556), ("Support Engineer", 8095, 4762), ("DevOps Engineer", 14166, 8333))]
ABOUT = "Vintara Technologies is a Bengaluru IT services firm. Average annual turnover INR 14 crore (FY2023-24 to FY2025-26)."
KB = CompanyKB("Vintara Technologies", employees=PEOPLE, rates=RATES, about=ABOUT,
               certifications=[{"name": "ISO/IEC 27001:2022 Information Security", "kind": "company", "valid_until": "2027-08-31"}])

# ------------------------------------------------------------------------------------------- T1 staffing conditions
cl = gates.staff_clauses(STF)
ok("T1 a two-part staffing condition is read as two conditions", len(cl) == 2, cl)
ok("T1 the first is the project manager, PMP or PRINCE2, 8 years",
   cl and cl[0]["role"] == "Project Manager" and cl[0]["certs"] == ["PMP", "PRINCE2"] and cl[0]["any_cert"] and cl[0]["min_years"] == 8, cl[:1])
ok("T1 the second is the solution architect, 10 years of Azure",
   len(cl) > 1 and cl[1]["role"] == "Solution Architect" and cl[1]["min_years"] == 10 and "Azure" in cl[1]["tech"], cl[1:])
ok("T1 the requirement id is not a certificate", not any("STF" in c for x in cl for c in x["certs"]), cl)
ok("T1 'CISSP and CISM' needs both", gates.staff_clauses("All L3 analysts must hold CISSP and CISM.")[0]["any_cert"] is False)
st, why = gates._check_staff(STF, KB)
ok("T1 the eligibility check names a person for each role, by job title first", st == "pass" and "VT-002" in why and "VT-004" in why, why)
kb_no_arch = CompanyKB("X", employees=[p for p in PEOPLE if p["code"] != "VT-004"])
st, why = gates._check_staff(STF, kb_no_arch)
ok("T1 the architect clause is checked too (no 10-year Azure architect: fail)", st == "fail" and "Solution Architect" in why, why)

prof = {"eligibility": [{"ref": "STF-01", "text": STF, "kind": "staff", "mandatory": True}]}
reqs = [{"code": "REQ-017", "source_ref": "STF-01", "text": STF, "category": "Compliance", "subcategory": "Team & Experience",
         "workstream": "Programme management", "technologies": []},
        {"code": "REQ-002", "source_ref": "FR-01", "text": "The bidder shall build a responsive customer portal with React.", "category": "Functional",
         "subcategory": "Application Development", "workstream": "Application engineering", "technologies": ["React"], "effort_days": 20}]
ph = [("Build", 5), ("Run", 12)]
rules, notes = teamplan.plan_roles(reqs, prof, ph, 0.0, 4.8, KB)
ai = {"roles": [  # the AI's answer from the live run
    {"role": "Project Manager", "phase": "Build", "fte": 1, "location": "Offshore", "skills": ["Project Management", "Agile"], "certs": ["PMP", "PRINCE2"],
     "min_years": 8, "serves": ["STF-01", "DEL-01"], "why": "Mandated by STF-01"},
    {"role": "Solution Architect", "phase": "Build", "fte": 1, "location": "Offshore", "skills": ["Microsoft Azure"],
     "certs": ["Microsoft Certified: Azure Solutions Architect Expert"], "min_years": 10, "serves": ["STF-01", "FR-01"], "why": "Mandated by STF-01"},
    {"role": "Full Stack Developer", "phase": "Build", "fte": 2, "location": "Offshore", "skills": ["React"], "certs": [], "min_years": 3, "serves": ["FR-01"], "why": "portal"}]}
rows = teamplan.check_ai_plan(ai, reqs, prof, ph, 4.8, rules)
teamplan.assign(KB, rows, {})
ok("T1 no phantom 'Lead' role", not any(r["role"] == "Lead" for r in rows), [r["role"] for r in rows])
ok("T1 no role asks for an 'STF' certificate", not any("STF" in c for r in rows for c in r["certs"]), [r["certs"] for r in rows])
pm = next((r for r in rows if r["role"] == "Project Manager"), None)
ok("T1 the project manager is filled from the company's own PMs (PMP or PRINCE2)", pm and pm["assigned"] and pm["assigned"][0]["code"] == "VT-002" and not pm["unfilled"],
   pm and (pm["assigned"], pm["unfilled"], pm["any_cert"]))
ok("T1 no note about a dedicated role was added", not any("dedicated role" in n for n in notes), notes)

# ------------------------------------------------------------------------------------------- T2 rate card names
for role, want in (("Full Stack Developer", 12143), ("Full-stack Developer", 12143), ("Support Engineer L2/L3", 8095),
                   ("QA And Performance Engineer", 9445), ("Backend & API Engineer", 13493), ("Platform Engineer", 14166)):
    rate, cost, ccy, src = _rate_for(KB, role, "Offshore", {})
    ok(f"T2 '{role}' is priced from the company's rate card", src == "Rate card" and rate == want and ccy == "INR", (rate, src))
rate, cost, ccy, src = _rate_for(KB, "Backend & API Engineer", "Offshore", {})
ok("T2 a row with the same wording beats a row with the same standard role", rate == 13493, rate)

# ------------------------------------------------------------------------------------------- T3 bank guarantee once
rfp_text = "The successful bidder shall furnish a performance bank guarantee of 3% of the contract value."
lab = [{"role": "Project Manager", "person_days": 100, "cost": 1_000_000, "phase": "Build", "day_cost": 10000}]
lines = commercial.build_lines({"team": [], "duration_months": 17, "run_months": 12}, lab, [],
                               {"commercial": {"bidder_supplied": [{"ref": "REQ-023", "text": rfp_text}]}}, rfp_text)
ok("T3 the guarantee is one commitment line", sum(1 for l in lines if "guarantee" in l["label"].lower()) == 1, [l["label"] for l in lines])
ok("T3 it isn't a licence waiting for a quote", not any(l["kind"] == "licence" for l in lines), [(l["kind"], l["label"][:40]) for l in lines])
lines = commercial.build_lines({"team": [], "duration_months": 12}, lab, [], {"commercial": {"bidder_supplied": [{"ref": "C-2", "text": "The bidder shall supply Microsoft 365 E5 licences for 300 users."}]}}, "")
ok("T3 a real licence still needs a quote", any(l["kind"] == "licence" and l["needs_quote"] for l in lines))

# ------------------------------------------------------------------------------------------- T4 technology names
corpus = ("The bidder shall provide secure REST APIs for tracking, ETA and documents through an API gateway. RPO 1 hour, RTO 4 hours. "
          "Turnover of at least INR 10 crore. Customers shall receive email and SMS notifications. Integrate with SAP S/4HANA using OData.")
for text in ("The bidder shall provide secure REST APIs for tracking, ETA and documents through an API gateway with keys and a developer portal.",
             "Disaster recovery in South India (RPO 1 hour, RTO 4 hours).",
             "The bidder shall have an average annual turnover of at least INR 10 crore.",
             "Customers shall receive email and SMS notifications on shipment milestones."):
    found = profile.named_terms(text, corpus)
    junk = {"API", "APIs", "ETA", "RPO 1", "RTO 4", "INR 10", "SMS"} & set(found)
    ok(f"T4 no generic words or figures read as technologies: {text[:40]}...", not junk, found)
ok("T4 real product names are still found", "SAP S/4HANA" in profile.named_terms("Integrate with SAP S/4HANA using OData services.", corpus))

# ------------------------------------------------------------------------------------------- T6 citations
allowed = {"Shipment tracking portal for a freight terminal operator", "Cloud-native Application Development", "PMP"}
got = _cited(["Case study: Shipment Tracking Portal for a Freight Terminal Operator", "cloud-native application development", "PMP"], allowed)
ok("T6 citations count with a prefix or different case", len(got) == 3, got)
ok("T6 a name outside the candidate evidence still doesn't count", _cited(["Some other project"], allowed) == [])
ok("T6 an ambiguous short name doesn't count", _cited(["portal"], allowed) == [])

# ------------------------------------------------------------------------------------------- T7 consortium
ok("T7 'Consortium bids are not allowed' is not an allowance",
   gates.consortium_allowed("Consortium bids are not allowed. The penetration test may be subcontracted to an independent firm.") is False)
ok("T7 'No consortium or joint venture bids' is not an allowance", gates.consortium_allowed("No consortium or joint venture bids will be accepted.") is False)
ok("T7 'Bids from a consortium are accepted' is", gates.consortium_allowed("Bids from a consortium led by a lead bidder are accepted.") is True)
ok("T7 subcontracting allowed still counts", gates.consortium_allowed("Subcontracting is permitted for up to 30% of the work.") is True)

# ------------------------------------------------------------------------------------------- T8 turnover
st, why = gates._check_financial("The bidder shall have an average annual turnover of at least INR 10 crore over the last three years.", KB)
ok("T8 turnover above the threshold passes from the company profile", st == "pass" and "14 crore" in why, why)
st, why = gates._check_financial("Minimum average annual turnover of INR 20 crore.", KB)
ok("T8 below the threshold fails", st == "fail", why)
st, why = gates._check_financial("Minimum annual revenue of USD 5 million.", KB)
ok("T8 another currency is left for a person to confirm", st == "unknown", why)
st, why = gates._check_financial("Turnover of at least INR 10 crore.", CompanyKB("Y"))
ok("T8 no figure in the profile: unknown", st == "unknown", why)
ok("T8 lakh and crore compare correctly", gates._check_financial("Turnover of at least INR 90 lakh.", KB)[0] == "pass")

# ------------------------------------------------------------------------------------------- T9 client wording (unit)
est = {"assumptions": ["Build over 5 months as required by the RFP, from 177 person-days of requirement-level effort plus project management, architecture and testing.",
                       "Managed service for 12 months after go-live as stated in the RFP.",
                       "STF-01 names a Project Manager role: it is part of the team.",
                       "Availability allows for people already committed to won deals (in full) and deals still being bid (at half).",
                       "Client provides environments, test data and SME availability per plan."]}
ca = docgen.client_assumptions(est)
ok("T9 the client sees the term and the dependencies", "Build over 5 months as required by the RFP." in ca and any("Client provides" in a for a in ca), ca)
ok("T9 but not effort counts, role notes or availability rules", not any(x in " ".join(ca) for x in ("person-days", "role", "committed")), ca)
ok("T9 migration only when the RFP asks for one", not docgen._migrates(reqs) and docgen._migrates([{"text": "Migrate 4 TB of data from the legacy system."}]))

# ------------------------------------------------------------------------------------------- end to end
CLIENT = "Konkan Harbour Freight Ltd"


def rfp_pdf() -> bytes:
    # the fictional RFP used in the live walkthrough (reference KHFL/IT/2026/014)
    return open(os.path.join(os.path.dirname(__file__), "fixtures", "khfl_portal_rfp.pdf"), "rb").read()


with TestClient(app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/register", json={"company_name": "Vintara Followups QA", "name": "Asha Admin", "email": "admin@followups.example", "password": PW})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    c.put("/api/company", json={"about": ABOUT, "currency": "INR", "settings": {"generalised_response": True}}, headers=h)
    for p in PEOPLE:
        c.post("/api/library/skills", json={**p, "level": "Senior", "location": "Bengaluru"}, headers=h)
    for rr in RATES:
        c.post("/api/library/rates", json=rr, headers=h)
    c.post("/api/library/certifications", json={"name": "ISO/IEC 27001:2022 Information Security", "kind": "company", "issuer": "BV", "valid_until": "2028-08-31"}, headers=h)
    c.post("/api/library/capabilities", json={"name": "Cloud-native Application Development", "description": "Customer portals and APIs on Azure",
                                               "technologies": ["React", "Microsoft Azure", "Azure API Management"]}, headers=h)
    r = c.post("/api/deals", files={"file": ("khfl.pdf", rfp_pdf())},
               data={"confidential": "true", "name": "Customer Portal and Tracking APIs", "client_name": CLIENT, "client_aliases": "KHFL", "engagement_type": "build_run"}, headers=h)
    did = r.json().get("id")
    t0 = time.time()
    while time.time() - t0 < 180 and c.get(f"/api/deals/{did}", headers=h).json()["status"] == "processing":
        time.sleep(0.3)
    d = c.get(f"/api/deals/{did}", headers=h).json()
    ok("E2E the analysis finishes", d["status"] == "in_review", d["status"])
    gp = c.get(f"/api/deals/{did}/stages/gaps", headers=h).json()["data"]
    g = {x["ref"]: x for x in gp.get("gates", [])}
    ok("E2E STF-01 passes with a PM and an architect", g.get("STF-01", {}).get("status") == "pass" and "VT-002" in g["STF-01"]["reason"], g.get("STF-01"))
    ok("E2E ELG-01 passes from the stated turnover", g.get("ELG-01", {}).get("status") == "pass", g.get("ELG-01"))
    ok("E2E the consortium ban isn't read as an allowance", gp.get("consortium_allowed") is False, gp.get("consortium_allowed"))
    junk = {"API", "APIs", "ETA", "RPO 1", "RTO 4", "INR 10", "PMP", "PRINCE2", "STF"} & {m["technology"] for m in gp.get("top_missing", [])}
    ok("E2E 'technologies you don't have' has no generic words, figures or held certificates", not junk, gp.get("top_missing"))
    rq = {q["source_ref"]: q for q in c.get(f"/api/deals/{did}/requirements", headers=h).json()}
    for ref in ("STF-01", "ELG-01"):
        q = rq.get(ref, {})
        ok(f"E2E {ref} agrees with its passed eligibility check", q.get("match_status") == "strong" and not (q.get("match") or {}).get("technologies_missing"),
           (q.get("match_status"), (q.get("match") or {}).get("technologies_missing")))
    est = c.get(f"/api/deals/{did}/stages/estimation", headers=h).json()["data"]
    ok("E2E no phantom Lead in the team", not any(t["role"] == "Lead" for t in est["team"]), [t["role"] for t in est["team"]])
    pm = [t for t in est["team"] if t["role"] == "Project Manager"]
    ok("E2E the project manager is a named person", pm and pm[0]["assigned"] and not pm[0]["unfilled"], pm[:1])
    pr = c.get(f"/api/deals/{did}/stages/pricing", headers=h).json()["data"]
    ok("E2E the guarantee appears once and nothing asks for a quote for it",
       sum(1 for l in pr["other_lines"] if "guarantee" in l["label"].lower()) == 1 and not any(l["kind"] == "licence" for l in pr["other_lines"]),
       [(l["kind"], l["label"][:50]) for l in pr["other_lines"]])
    bench = [l["role"] for l in pr["lines"] if l["rate_source"].startswith("Benchmark")]
    ok("E2E roles the rate card has are priced from it", not {"Project Manager", "Solution Architect", "Support Engineer", "Software Engineer"} & set(bench), bench)
    dl = c.get(f"/api/deals/{did}/download/proposal", headers=h)
    ok("E2E proposal downloads", dl.status_code == 200, dl.status_code)
    from docx import Document
    doc = Document(io.BytesIO(dl.content))
    text = "\n".join([p.text for p in doc.paragraphs] + [cell.text for t in doc.tables for row in t.rows for cell in row.cells])
    for bad in ("migrat", "person-days of requirement", "rate card", "Contingency", "need a quote", "hiring for open roles", "dedicated role",
                "fully met", "with an approach", "to be agreed", "Lead\n"):
        ok(f"E2E the client proposal doesn't say '{bad.strip()}'", bad.lower() not in text.lower(),
           text[max(0, text.lower().find(bad.lower()) - 80): text.lower().find(bad.lower()) + 80])
    ho = c.get(f"/api/deals/{did}/download/handoff", headers=h)
    htext = "\n".join(p.text for p in Document(io.BytesIO(ho.content)).paragraphs) + "\n".join(
        cell.text for t in Document(io.BytesIO(ho.content)).tables for row in t.rows for cell in row.cells)
    ok("E2E the internal handoff keeps the pricing notes", "rate card" in htext.lower(), htext[:200])
    ok("E2E the handoff still hides the client", "konkan" not in htext.lower() and "khfl" not in htext.lower())

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for x in FAILS:
    print("  -", x)
sys.exit(1 if FAILS else 0)
