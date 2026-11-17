"""Generalised response pipeline: the parts that need an AI, exercised with a scripted AI, plus the guards around them.

No real AI key is used: llm.is_enabled / complete_json / complete are replaced by a script that answers like a careless
model would (copies an old healthcare answer, claims credentials, names evidence it doesn't have), so the checks that
must catch it are proven. Each phase of the generalised pipeline adds its section here.
"""
import os, sys, tempfile, time, json, re
os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import logging
logging.disable(logging.INFO)
from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import AnswerEntry, Deal, Requirement, Tenant, AuditLog
from app.services import llm, pipeline, validation, solution, features
from sqlalchemy import select
import domain_fixtures as F

PW = __import__("secrets").token_urlsafe(18)
FAILS, PASSES = [], 0


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, str(extra)[:300])


class ScriptedAI:
    """Answers the proposal-writing prompt; first attempt is careless, the retry (with feedback) is clean."""

    def __init__(self):
        self.calls = []

    def complete_json(self, system, prompt, **kw):
        self.calls.append(prompt)
        if "Write the response for each requirement" not in prompt:
            raise RuntimeError("not scripted")
        out = []
        for m in re.finditer(r"\[(\d+)\] REQUIREMENT: (.*?)\n(.*?)(?=\n\[\d+\] REQUIREMENT|\n\nWrite the response)", prompt, re.S):
            i, req, rest = int(m.group(1)), m.group(2), m.group(3)
            if "previous draft was rejected" in rest:
                out.append({"i": i, "response": f"We will meet this requirement with a named specialist team and a documented operating procedure agreed at mobilisation."})
            elif "earlier bid" in rest:  # copies the old answer word for word
                old = re.search(r"never copy it\): (.*)", rest).group(1)
                out.append({"i": i, "response": old})
            elif "CERT-In" in req:
                out.append({"i": i, "response": "We are a CERT-In empanelled auditing organisation with a dedicated assurance practice."})
            elif "SOAR" in req:
                out.append({"i": i, "response": "We will build a data platform consolidating data from the HIS and laboratory system using our Healthcare Interoperability capability."})
            else:
                out.append({"i": i, "response": f"We will deliver this as specified, with acceptance criteria agreed in the design phase and tracked in weekly reviews."})
        return out

    def complete(self, system, prompt, **kw):
        return "Kestrel proposes a managed security service. Our hospital and patient programmes give us deep insight. The team is ready."


with TestClient(app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/register", json={"company_name": "Kestrel Generalised QA", "name": "Asha Admin", "email": "admin@gen.example", "password": PW})
    h = {"Authorization": "Bearer " + r.json()["token"]}
    # ------------------------------------------------------------------ the switch
    comp = c.get("/api/company", headers=h).json()
    ok("switch is off by default", comp["settings"].get("generalised_response") in (None, False))
    r = c.put("/api/company", json={"settings": {"fte_per_24x7_seat": 9}}, headers=h)
    ok("24x7 seat setting is range-checked", r.status_code == 400, r.status_code)
    for kind, rows in (("capabilities", F.CAPABILITIES), ("skills", F.PEOPLE), ("certifications", F.CERTIFICATIONS),
                       ("case_studies", F.CASE_STUDIES), ("accelerators", F.ACCELERATORS), ("rates", F.RATES)):
        for row in rows:
            c.post(f"/api/library/{kind}", json=row, headers=h)
    with SessionLocal() as db:
        tid = db.scalar(select(Tenant.id).where(Tenant.name == "Kestrel Generalised QA"))
        for q, a in F.OLD_ANSWERS:
            db.add(AnswerEntry(tenant_id=tid, question=q, answer=a, category="Functional", origin="ai", approved_by="QA", outcome="won"))
        db.commit()

    def new_deal(dom):
        fname, data = F.rfp_bytes(dom)
        r = c.post("/api/deals", files={"file": (fname, data)}, data={"confidential": "true", "ai_ack": "true"}, headers=h)
        did = r.json()["id"]
        t0 = time.time()
        while time.time() - t0 < 120 and c.get(f"/api/deals/{did}", headers=h).json()["status"] == "processing":
            time.sleep(0.3)
        return did

    # ------------------------------------------------------------------ switch off: today's behaviour is untouched
    did_off = new_deal("cybersecurity")
    prop = c.get(f"/api/deals/{did_off}/stages/proposal", headers=h).json()["data"]
    ok("switch off: no validation report (old pipeline)", "validation" not in prop)

    r = c.put("/api/company", json={"settings": {"generalised_response": True}}, headers=h)
    ok("admin switches the generalised pipeline on", r.status_code == 200 and r.json()["settings"]["generalised_response"] is True)
    with SessionLocal() as db:
        ok("the switch is audited", db.scalar(select(AuditLog).where(AuditLog.tenant_id == tid, AuditLog.action == "feature.switch")) is not None)

    # ------------------------------------------------------------------ Phase 1: validated answers with a careless AI
    did = new_deal("cybersecurity")
    ai = ScriptedAI()
    real = (llm.is_enabled, llm.complete_json, llm.complete)
    llm.is_enabled, llm.complete_json, llm.complete = (lambda: True), ai.complete_json, ai.complete
    try:
        with SessionLocal() as db:
            deal = db.get(Deal, did)
            pipeline.run_stage(db, deal, "proposal")
    finally:
        llm.is_enabled, llm.complete_json, llm.complete = real
    reqs = {q["source_ref"]: q for q in c.get(f"/api/deals/{did}/requirements", headers=h).json()}
    ok("the AI was asked to adapt the matching library answer, not paste it", any("earlier bid" in p for p in ai.calls))
    ok("a second attempt was made with the reasons", any("previous draft was rejected" in p for p in ai.calls))
    soar = reqs["SOC-05"]["response"]
    ok("SOAR answer has no hospital wording", not re.search(r"\bHIS\b|laboratory|Healthcare Interoperability", soar), soar)
    ok("CERT-In answer makes no false claim", "CERT-In empanelled auditing organisation" not in reqs["CMP-02"]["response"], reqs["CMP-02"]["response"])
    texts = [q["response"] for q in reqs.values() if len(q.get("response") or "") > 80]
    ok("no paragraph answers two requirements", len(texts) == len(set(texts)), [t[:50] for t in texts if texts.count(t) > 1][:2])
    prop = c.get(f"/api/deals/{did}/stages/proposal", headers=h).json()["data"]
    ok("validation report stored with the proposal", isinstance(prop.get("validation"), dict) and "errors" in prop["validation"], prop.get("validation"))
    ok("no errors left after repair", not prop["validation"]["errors"], prop["validation"]["errors"][:2])
    ok("executive summary drops other-industry sentences", "hospital" not in (prop.get("executive_summary") or "").lower(), prop.get("executive_summary"))

    # ------------------------------------------------------------------ approval guard and the answer library
    for s in ("requirements", "matching", "gaps", "architecture", "estimation"):
        c.post(f"/api/deals/{did}/stages/{s}/approve", json={}, headers=h)
    c.post(f"/api/deals/{did}/stages/pricing/approve", json={"despite_over_budget": True}, headers=h)
    rid = reqs["CMP-02"]["id"]
    r = c.patch(f"/api/deals/{did}/requirements/{rid}", json={"response": "Kestrel is CERT-In empanelled and SOC 2 Type II certified."}, headers=h)
    ok("a person can edit an answer", r.status_code == 200, r.text[:200])
    r = c.post(f"/api/deals/{did}/stages/proposal/approve", json={}, headers=h)
    ok("approval refused while an answer claims credentials not held", r.status_code == 409 and "failed the proposal checks" in r.text, r.text[:200])
    with SessionLocal() as db:
        n0 = db.query(AnswerEntry).filter(AnswerEntry.tenant_id == tid).count()
    r = c.post(f"/api/deals/{did}/stages/proposal/approve", json={"despite_validation": True}, headers=h)
    ok("approve anyway works and is audited", r.status_code == 200, r.text[:200])
    with SessionLocal() as db:
        ok("override is in the audit log", db.scalar(select(AuditLog).where(AuditLog.tenant_id == tid, AuditLog.action == "proposal.validation_override")) is not None)
        bad = db.query(AnswerEntry).filter(AnswerEntry.tenant_id == tid, AnswerEntry.answer.like("%CERT-In empanelled%"), AnswerEntry.source_deal == did).count()
        ok("an answer that fails the checks is not saved to the library", bad == 0)

    # ------------------------------------------------------------------ 'company strength' needs library evidence
    class KB:
        employees, capabilities, case_studies, accelerators = F.PEOPLE, F.CAPABILITIES, F.CASE_STUDIES, F.ACCELERATORS
    arch = {"choices": [{"area": "SIEM", "choice": "Microsoft Sentinel", "basis": "Company strength"},
                        {"area": "IAM", "choice": "Microsoft Entra ID and CyberArk PAM", "basis": "Company strength"},
                        {"area": "Cloud", "choice": "Microsoft Azure with Terraform", "basis": "Company strength"},
                        {"area": "EDR", "choice": "CrowdStrike Falcon", "basis": "Company strength"}]}
    out = solution.verify_strength_claims(arch, KB, "Use Microsoft Entra ID and CyberArk PAM. Deploy CrowdStrike Falcon EDR.")
    b = {x["area"]: x["basis"] for x in out["choices"]}
    ok("Sentinel stays a strength (a person holds it)", b["SIEM"] == "Company strength", b)
    ok("Entra ID + CyberArk becomes 'Specified in the RFP'", b["IAM"] == "Specified in the RFP", b)
    ok("Azure + Terraform stays a strength", b["Cloud"] == "Company strength", b)
    ok("CrowdStrike becomes 'Specified in the RFP'", b["EDR"] == "Specified in the RFP", b)

    # ------------------------------------------------------------------ the checker on its own
    class KB2:
        capabilities, case_studies, accelerators, certifications, employees = F.CAPABILITIES, F.CASE_STUDIES, F.ACCELERATORS, F.CERTIFICATIONS, F.PEOPLE
    chk = validation.Checker(KB2, "BFSI", "Security operations centre for an insurer with Microsoft Sentinel.", "Kestrel")
    ok("foreign vocabulary comes from the library's other industries", {"hospital", "patient", "HIS"} <= chk.foreign | {t.lower() for t in chk.foreign}, sorted(chk.foreign))
    ok("generic IT words and technologies are never foreign", not ({"development", "snowflake", "public", "sector", "L2", "cloud-native", "platform"} & chk.foreign), sorted(chk.foreign))
    ok("an insurer's own words are not foreign", "insurer" not in chk.foreign and "Sentinel" not in chk.foreign)
    ok("held certificate is fine", not chk.check("We hold ISO/IEC 27001:2022 certification.", {"text": "x"}))
    ok("ISO 27001 short form matches the register", not chk.check("We are ISO 27001 certified.", {"text": "x"}))
    ok("missing certificate is caught", any(i["rule"] == "unsupported" for i in chk.check("We are SOC 2 Type II certified.", {"text": "x"})))
    ok("an honest 'not held' statement passes", not chk.check("We do not hold SOC 2 today; our partner holds it.", {"text": "x"}))
    ok("internal wording is caught", any(i["rule"] == "internal" for i in chk.check("We will add a reference project to our final response.", {"text": "x"})))
    ok("naming evidence that isn't this requirement's is caught",
       any(i["rule"] == "unsupported" for i in chk.check("Delivered through our Healthcare Interoperability capability.", {"text": "x", "match": {"evidence": []}})))
    ok("naming this requirement's own evidence is fine",
       not chk.check("Delivered through our Cloud Operations & DevOps capability.", {"text": "x", "match": {"evidence": [{"type": "Capability", "name": "Cloud Operations & DevOps"}]}}))
    ok("topic overlap ignores bid boilerplate", validation.topic_overlap("The bidder shall build SOAR playbooks for phishing", "The bidder shall build a patient portal") < 0.25)

# ---------------------------------------------------------------------- Phase 2: the RFP Profile
from app.services import profile as P
from app.models import TechTerm
with TestClient(app, raise_server_exceptions=False) as c:
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@gen.example", "password": PW}).json()["token"]}
    did = new_deal("cloud")
    d = c.get(f"/api/deals/{did}", headers=h).json()
    prof = d["meta"].get("profile") or {}
    ok("profile stored on the deal", prof.get("source") in ("rules", "ai+rules"), list(d["meta"].keys())[:12])
    ok("term read from prose: 10 + 24 months", (prof.get("term") or {}).get("build_months") == 10 and prof["term"].get("run_months") == 24, prof.get("term"))
    ok("engagement follows the stated phases", d["engagement_type"] == "build_run", d["engagement_type"])
    ok("weights read from a sentence add to 100", sorted(e["weight"] for e in prof.get("evaluation", [])) == [20, 30, 50], prof.get("evaluation"))
    ok("eligibility kinds", {e["kind"] for e in prof.get("eligibility", [])} >= {"partner_status", "certification"}, prof.get("eligibility"))
    ok("scope units", any(u["quantity"] == 220 and "virtual machines" in u["unit"] for u in prof.get("scope_units", [])), prof.get("scope_units"))
    ok("client-paid consumption noticed", any("Azure consumption" in x for x in prof["commercial"].get("client_supplied", [])), prof.get("commercial"))
    reqs = c.get(f"/api/deals/{did}/requirements", headers=h).json()
    tags = {t for q in reqs for t in q.get("technologies", [])}
    ok("named technologies tagged on requirements", {"Azure Migrate", "Terraform", "Azure Site Recovery"} <= tags, sorted(tags))
    with SessionLocal() as db:
        keys = {t.key for t in db.scalars(select(TechTerm).where(TechTerm.tenant_id == tid))}
    ok("technology registry grows from the RFP", "azure migrate" in keys and "servicenow" in keys, sorted(keys)[:15])
    est = c.get(f"/api/deals/{did}/stages/estimation", headers=h).json()["data"]
    ok("estimation covers build + run", est.get("duration_months") == 34, est.get("duration_months"))
    d_off = c.get(f"/api/deals/{did_off}", headers=h).json()
    ok("switch off: no profile on the old deal", "profile" not in (d_off.get("meta") or {}))

# AI merge rules: a value is used only when its quote is really in the RFP
text = "Contract period: 3 months transition followed by 36 months of managed security services. Technical 45%, Team 25%, Commercial 30%."
rules = {"term": {"transition_months": 3, "build_months": 0, "run_months": 36, "total_months": 39}, "evaluation": [], "eligibility": [],
         "scope_units": [], "service": {}, "commercial": {}, "technologies": []}
m = P.merge(rules, {"term": {"transition_months": 0, "run_months": 60, "quote": "a five year managed service"}}, text)
ok("an AI term without a real quote is ignored", m["term"]["total_months"] == 39, m["term"])
m = P.merge(rules, {"term": {"transition_months": 3, "run_months": 36, "quote": "3 months transition followed by 36 months of managed security services"},
                    "evaluation": [{"criterion": "Technical", "weight": 45, "quote": "Technical 45%"}, {"criterion": "Team", "weight": 25, "quote": "Team 25%"},
                                   {"criterion": "Commercial", "weight": 30, "quote": "Commercial 30%"}],
                    "technologies": [{"name": "Microsoft Sentinel"}, {"name": "QRadar"}]}, text + " Logs go to Microsoft Sentinel.")
ok("a quoted AI term is used", m["term"]["run_months"] == 36 and m["source"] == "ai+rules", m["term"])
ok("quoted weights are used when they add to 100", [e["weight"] for e in m["evaluation"]] == [45, 25, 30], m["evaluation"])
ok("an AI technology not in the text is dropped", [t["name"] for t in m["technologies"]] == ["Microsoft Sentinel"], m["technologies"])
m = P.merge({**rules, "term": {"total_months": 24, "run_months": 24}}, {"term": {"run_months": 36, "quote": "36 months of managed security services"}}, text)
ok("disagreement is recorded for a person to confirm", any(x["field"] == "term" for x in m["conflicts"]), m["conflicts"])
# open-vocabulary names by shape
nt = P.named_terms("Routing shall use BGP between sites and OSPF within campuses, monitored in SolarWinds with NetFlow.", "routing sites campuses", set())
ok("protocols and products found by shape", {"BGP", "OSPF", "SolarWinds", "NetFlow"} <= set(nt), nt)
nt = P.named_terms("The Network Operations Centre shall be staffed 24x7 by L1 and L2 engineers in India.", "the network operations centre shall be staffed", set())
ok("title-case ordinary words, shift notation, levels and places are not technologies", not nt, nt)
ok("term: years in words", P.parse_term("The contract term is three (3) years of managed services.").get("run_months") == 36)
ok("term: build then support", P.parse_term("Delivery: 9 months development followed by 12 months of warranty support.") .get("build_months") == 9)

# ---------------------------------------------------------------------- Phase 3: eligibility gates and evidence-tagged answers
from app.services import gates as G
from datetime import date
class KB3:
    certifications, case_studies, employees = F.CERTIFICATIONS, F.CASE_STUDIES, F.PEOPLE
def gate(text, kind, due="22 December 2026", rfp="", today=date(2026, 11, 16)):
    return G.evaluate({"eligibility": [{"ref": "X", "text": text, "kind": kind, "mandatory": True}]}, KB3, "BFSI", due, rfp, today=today)
ok("held ISO certificate passes", gate("Bidders must hold ISO 9001 certification.", "certification")["gates"][0]["status"] == "pass")
ok("partner tier in the register passes", gate("Bidders must be a Microsoft Solutions Partner for Infrastructure (Azure).", "partner_status")["gates"][0]["status"] == "pass")
ok("partner tier not held fails", gate("Bidders must hold Fortinet Expert Partner status.", "partner_status")["gates"][0]["status"] == "fail")
ok("accreditation not held fails", gate("The bidder shall be a CERT-In empanelled information security auditing organisation.", "accreditation")["gates"][0]["status"] == "fail")
g = gate("Bidders must have operated managed SOC services for at least three BFSI clients in the last five years.", "experience")
ok("references tied to an industry need that industry and topic", g["gates"][0]["status"] == "fail" and g["verdict"] == "No bid", g)
g = gate("Bidders must have delivered at least two citizen- or customer-facing web portals in the last five years.", "experience")
ok("references counted by topic across industries", g["gates"][0]["status"] == "pass" and len(g["gates"][0]["evidence"]) >= 2, g["gates"][0])
g = gate("Bidders must have delivered at least one cloud data platform in the last one years.", "experience")
ok("references outside the time window don't count", g["gates"][0]["status"] == "fail", g["gates"][0])
g = gate("The SOC lead shall hold CISSP and have at least 10 years of experience.", "staff", due="30 March 2027")
ok("a staff gap with time to hire is curable", g["gates"][0]["status"] == "curable" and g["verdict"] is None, g["gates"][0])
g = gate("The SOC lead shall hold CISSP and have at least 10 years of experience.", "staff", due="30 November 2026")
ok("a staff gap with no time left fails", g["gates"][0]["status"] == "fail", g["gates"][0])
g = gate("Bidders must have operated managed SOC services for at least three BFSI clients.", "experience", rfp="Consortium bids are allowed; the lead bidder is accountable.")
ok("with consortia allowed, a reference gap means bid as subcontractor or partner", g["verdict"] == "Bid in a consortium" and g["gates"][0]["status"] == "curable", g)
g = gate("Bidders must have an annual turnover of USD 10 million.", "financial")
ok("what the library can't show is 'unknown', not pass", g["gates"][0]["status"] == "unknown" and g["verdict"] is None)

with TestClient(app, raise_server_exceptions=False) as c:
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@gen.example", "password": PW}).json()["token"]}
    did = new_deal("network")
    gp = c.get(f"/api/deals/{did}/stages/gaps", headers=h).json()["data"]
    ok("failed mandatory gates decide the verdict", gp.get("verdict") == "No bid" and set(gp.get("gates_failed", [])) >= {"EL-01", "EL-02"}, (gp.get("verdict"), gp.get("gates_failed")))
    ok("the readiness verdict before the gates is kept for reference", gp.get("verdict_before_gates") not in (None, ""), gp.get("verdict_before_gates"))
    rq = {q["source_ref"]: q for q in c.get(f"/api/deals/{did}/requirements", headers=h).json()}
    ok("a failed gate is High risk on its requirement", rq["EL-01"]["gap"].get("risk") == "High" and rq["EL-01"]["gap"].get("gate", {}).get("status") == "fail", rq["EL-01"]["gap"])
    ok("products the company lacks are partner-led", any(t["recommendation"] == "Partner" for t in gp.get("top_missing", []) if "Forti" in t["technology"]), gp.get("top_missing"))
    with SessionLocal() as db:
        olds = db.query(AnswerEntry).filter(AnswerEntry.tenant_id == tid, AnswerEntry.source_deal == "").all()
        ok("older answers were tagged when considered for reuse", any(e.technologies is not None for e in olds))
        e = next(e for e in olds if "HIS" in e.answer)
        ok("the tag records the evidence an old answer names", "Healthcare Interoperability" in (e.evidence_refs or []), e.evidence_refs)
        new_e = db.query(AnswerEntry).filter(AnswerEntry.tenant_id == tid, AnswerEntry.source_deal != "").first()
        ok("answers saved on approval carry their evidence and technologies", new_e is not None and new_e.evidence_refs is not None and new_e.technologies is not None)

# ---------------------------------------------------------------------- Phase 4: team planner and people matching
from app.services import teamplan as TP
class KB4:
    employees = F.PEOPLE
prof4 = {"service": {"coverage": "24x7"}, "eligibility": [
    {"ref": "STF-01", "kind": "staff", "mandatory": True, "text": "The SOC lead shall hold CISSP and have at least 10 years of security operations experience."},
    {"ref": "STF-02", "kind": "staff", "mandatory": False, "text": "L2 analysts shall hold OSCP or GCIH certification."}]}
reqs4 = [
    {"code": "REQ-1", "source_ref": "S-1", "text": "The bidder shall operate a 24x7 Security Operations Centre with L1 and L2 analysts.", "workstream": "Service operations",
     "subcategory": "Monitoring & Operations", "category": "Functional", "technologies": [], "effort_days": 8},
    {"code": "REQ-2", "source_ref": "S-2", "text": "Events shall be correlated in Microsoft Sentinel.", "workstream": "Security & compliance", "subcategory": "Security",
     "category": "Functional", "technologies": ["Microsoft Sentinel"], "effort_days": 8},
    {"code": "REQ-3", "source_ref": "S-3", "text": "The bidder shall deploy Fortinet FortiGate firewalls at 20 sites.", "workstream": "Platform & continuity",
     "subcategory": "Security", "category": "Functional", "technologies": ["Fortinet FortiGate"], "effort_days": 18},
    {"code": "REQ-4", "source_ref": "S-4", "text": "Field engineers shall attend site faults within 4 hours.", "workstream": "Service operations",
     "subcategory": "Service Levels", "category": "Non-functional", "technologies": [], "effort_days": 3},
    {"code": "REQ-5", "source_ref": "S-5", "text": "The bidder shall hold ISO 9001 certification.", "workstream": "Security & compliance",
     "subcategory": "Standards & Certifications", "category": "Compliance", "technologies": ["ISO 9001"], "effort_days": 3}]
rows4, notes4 = TP.plan_roles(reqs4, prof4, [("Transition", 2), ("Run", 24)], 0.2, 4.8, KB4)
by = {(r["phase"], r["role"]): r for r in rows4}
ok("named service line becomes analyst tiers", ("Run", "Security Operations Centre Analyst (L1)") in by and ("Run", "Security Operations Centre Analyst (L2)") in by, list(by))
ok("24x7 seats sized by the shift rota setting", by[("Run", "Security Operations Centre Analyst (L1)")]["fte"] == 4.8)
ok("a library job title names a specialism", ("Run", "Network Engineer") in by and "Fortinet FortiGate" in by[("Run", "Network Engineer")]["skills"], list(by))
ok("a role the RFP names doing the work is used", any(r["role"] == "Field Engineer" for r in rows4), list(by))
ok("company conditions get no role", not any("S-5" in r["serves"] for r in rows4))
lead = next((r for r in rows4 if r["role"] == "SOC Lead"), None)
ok("a staff condition becomes a role with hard constraints", lead is not None and lead["certs"] == ["CISSP"] and lead["min_years"] == 10, lead)
l2 = by[("Run", "Security Operations Centre Analyst (L2)")]
ok("a tier condition constrains that tier", set(l2["certs"]) == {"OSCP", "GCIH"} and l2["any_cert"], l2)
ok("the service team joins during transition", any(r["phase"] == "Transition" and "take-over" in r["responsibility"] for r in rows4))
TP.assign(KB4, rows4, {"KD012": 0.7})
ok("committed capacity is deducted (KD012 80% available, 70% committed)", not any(p["code"] == "KD012" for r in rows4 for p in r["assigned"]))
ok("a role nobody qualifies for stays open", lead["assigned"] == [] and lead["unfilled"] == 1)
ok("nobody is placed without a relevant skill or title", all(p["fit"] > 0 for r in rows4 for p in r["assigned"]))
load4 = {}
for r in rows4:
    for p in r["assigned"]:
        load4[(r["phase"], p["code"])] = load4.get((r["phase"], p["code"]), 0) + p["fte"]
avail4 = {p["code"]: p["availability"] / 100 for p in F.PEOPLE}
ok("nobody is booked past capacity within a phase", all(v <= avail4[k[1]] + 1e-6 for k, v in load4.items()), load4)
ok("a person on a role naming technologies holds one of them", all(TP.person_skill_hits(next(e for e in F.PEOPLE if e["code"] == p["code"]), r["skills"]) or
                                                               TP.clean_title(p["role"]) == TP.clean_title(r["role"]) for r in rows4 if r["skills"] for p in r["assigned"]))
ok("skill match is not fooled by a shared vendor word", not TP.person_skill_hits(next(e for e in F.PEOPLE if e["code"] == "KD010"), ["Azure Migrate"]))
ai4 = TP.check_ai_plan({"roles": [{"role": "SOC Analyst", "phase": "Run", "fte": 2, "serves": ["S-1"]}]}, reqs4, prof4, [("Transition", 2), ("Run", 24)], 4.8, rows4)
need = sum(r["fte"] for r in rows4 if r["phase"] == "Run" and "24x7 seat" in r["responsibility"])
ok("AI team: a 24x7 service under-sized by the AI is raised to shift sizing", ai4 and need >= 4.8 and
   sum(r["fte"] for r in ai4 if "S-1" in r["serves"] and r["phase"] == "Run") >= need - 0.01, ai4)
ok("AI team: work the AI left out keeps its rules role", ai4 and any("S-3" in r["serves"] for r in ai4))
ok("AI team: staff conditions are kept", ai4 and any(r["certs"] == ["CISSP"] for r in ai4))
ok("AI team: unknown phases and silly sizes are rejected", TP.check_ai_plan({"roles": [{"role": "X", "phase": "Moon", "fte": 3}, {"role": "Y", "phase": "Run", "fte": 400}]},
                                                                            reqs4, prof4, [("Run", 24)], 4.8, rows4) is None)

with TestClient(app, raise_server_exceptions=False) as c:
    h = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "admin@gen.example", "password": PW}).json()["token"]}
    from app.models import Assignment
    did4 = new_deal("network")
    est4 = c.get(f"/api/deals/{did4}/stages/estimation", headers=h).json()["data"]
    ok("the generalised team plan is used", est4.get("team_engine") in ("rules", "ai") and any("Operations Centre" in t["role"] for t in est4["team"]), est4.get("team_engine"))
    ok("every assigned person carries the FTE they give", all(p.get("fte") for t in est4["team"] for p in t["assigned"]))
    with SessionLocal() as db:
        n4 = db.query(Assignment).filter(Assignment.deal_id == did4).count()
        booked = sum(len(t["assigned"]) for t in est4["team"])
        ok("the plan is written to the assignment table", n4 == booked and n4 > 0, (n4, booked))
        com = TP.commitments(db, tid, "")
        ok("deals still being bid count at half", all(v > 0 for v in com.values()) and com, com)
    c.delete(f"/api/deals/{did4}", headers=h)
    with SessionLocal() as db:
        ok("deleting a deal frees its people", db.query(Assignment).filter(Assignment.deal_id == did4).count() == 0)

print(f"\n{PASSES} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
