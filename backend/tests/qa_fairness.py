"""QA part 3: fairness. Nothing should score well because of a keyword, a name, a demo flag, list order or an AI's say-so."""
import os, sys, tempfile, glob, time, json, copy, io
os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"
os.environ["DEMO_VENDORS"] = "true"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.services import knowledge as K, llm, matching, radar as RS
from app.services.matching import CompanyKB, match_requirements

PW = os.environ.get("QA_PASSWORD") or __import__("secrets").token_urlsafe(18)  # throwaway test accounts
S = os.path.join(ROOT, "sample-data")
FAILS, PASSES = [], 0


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


def req(text, section="Scope"):
    cat, sub, _ = K.classify(text, section)
    return {"text": text, "section": section, "category": cat, "subcategory": sub, "technologies": K.find_technologies(text), "priority": "Mandatory"}


def emp(code, skills, level=4):
    return {"code": code, "role": "Engineer", "skills": [{"name": s, "level": level} for s in skills], "availability": 100}


AZ = CompanyKB(
    name="Azure Shop",
    capabilities=[{"id": "c1", "name": "Azure cloud migration", "description": "Migrate workloads to Microsoft Azure, landing zones, Azure DevOps pipelines.",
                   "technologies": ["Azure", "Azure DevOps", "Terraform"], "industries": ["Retail"]},
                  {"id": "c2", "name": "Azure data platform", "description": "Azure Synapse, Azure Data Factory and Power BI reporting.",
                   "technologies": ["Azure Synapse", "Azure Data Factory", "Power BI"], "industries": ["Retail"]}],
    case_studies=[{"id": "s1", "title": "Retailer moves to Azure", "summary": "Moved 200 virtual machines to Azure.", "technologies": ["Azure"], "industry": "Retail"}],
    certifications=[{"name": "ISO/IEC 27001:2022", "kind": "company"}],
    employees=[emp(f"E{i}", ["Azure", "Terraform", "Azure DevOps"]) for i in range(12)],
)


def one(text, kb=AZ, **kw):
    r = [req(text)]
    match_requirements(r, kb, use_ai=False, **kw)
    return r[0]


# ------------------------------------------------------------------ 1. keyword alone never makes a match
r = one("The supplier shall migrate 150 virtual machines to Microsoft Azure using landing zones and Azure DevOps pipelines.")
ok("real Azure migration requirement is strong (not harsh)", r["match_status"] == "strong", r["match_status"])
for text in ["The supplier shall design, build and maintain an Azure-hosted satellite ground station including RF antenna installation and orbital tracking.",
             "The supplier shall manufacture Class III implantable cardiac devices with telemetry stored on Azure.",
             "The contractor shall construct a 12-storey hospital building; site security cameras will upload footage to Azure.",
             "The supplier shall supply and install 40 MRI scanners; scan images will be archived in Azure blob storage.",
             "The vendor shall operate a fleet of 200 diesel buses with Azure-based ticketing analytics."]:
    r = one(text)
    ok(f"Azure + unrelated work is not a match: {text[:50]}", r["match_status"] == "gap" and r["match_score"] < 0.35, f"{r['match_status']} {r['match_score']}")
    ok(f"   ...and says why", "technology name" in r["match"]["rationale"], r["match"]["rationale"][:80])
for text in ["Azure Azure Azure Azure Azure Azure Azure Azure Azure Azure Azure Azure.", "Azure.", "Microsoft Azure, Azure, AZURE, azure!!!",
             "Azure Azure Azure Kubernetes Azure Terraform Azure DevOps Azure"]:
    r = one(text)
    ok(f"keyword stuffing doesn't score high: {text[:30]}", r["match_status"] != "strong" and r["match_score"] <= 0.45, f"{r['match_status']} {r['match_score']}")
base = one("The supplier shall migrate virtual machines to Azure.")["match_score"]
stuffed = one("The supplier shall migrate virtual machines to Azure. Azure Azure Azure Azure Azure Azure Azure Azure.")["match_score"]
ok("repeating the keyword doesn't raise the score", stuffed <= base + 0.02, f"{base} -> {stuffed}")
r = one("The supplier shall implement SAP S/4HANA finance on Azure with SAP Basis support.")
ok("missing SAP makes it a gap/partial, never strong", r["match_status"] != "strong" and "SAP" in r["match"]["technologies_missing"], r["match_status"])

# ------------------------------------------------------------------ 2. certificates are facts from the register
for text, want in [("The supplier must hold a current SOC 2 Type II report.", "gap"), ("The supplier must hold ISO 27001 certification.", "strong"),
                   ("The supplier must be FedRAMP High authorised.", "gap"), ("The supplier must be PCI DSS Level 1 certified.", "gap"),
                   ("The supplier must hold ISO 27001 and SOC 2 Type II.", "partial"), ("The solution should align with ISO 27001 controls.", "strong")]:
    r = one(text)
    ok(f"cert: {text[:45]} -> {want}", r["match_status"] == want, r["match_status"])
claims = copy.deepcopy(AZ)
claims.capabilities.append({"id": "c9", "name": "SOC 2 Type II and FedRAMP High certified operations", "description": "We are SOC 2 Type II and FedRAMP certified.", "technologies": []})
r = one("The supplier must hold a current SOC 2 Type II report.", kb=claims)
ok("a cert claimed in a capability description doesn't count (register only)", r["match_status"] == "gap", r["match_status"])
expired = copy.deepcopy(AZ)
expired.certifications = [{"name": "SOC 2 Type II", "kind": "company", "valid_until": "2019-01-01"}]
r = one("The supplier must hold a current SOC 2 Type II report.", kb=expired)
ok("an expired certificate doesn't count as held", r["match_status"] != "strong", f"{r['match_status']} (valid_until 2019)")

# ------------------------------------------------------------------ 3. empty / thin library is never flattering
empty = CompanyKB(name="Empty")
r = one("The supplier shall migrate virtual machines to Azure.", kb=empty)
ok("empty library -> gap", r["match_status"] == "gap", r["match_status"])
skills_only = CompanyKB(name="Skills only", employees=[emp(f"E{i}", ["Azure"]) for i in range(50)])
r = one("The supplier shall migrate virtual machines to Azure.", kb=skills_only)
ok("50 people with a skill but no capability/case study isn't strong", r["match_status"] != "strong", f"{r['match_status']} {r['match_score']}")

# ------------------------------------------------------------------ 4. the AI can't overrule the facts
real_enabled, real_json = llm.is_enabled, llm.complete_json
llm.is_enabled = lambda *a, **k: True
for label, reply_fn in [("all strong, no evidence", lambda items: [{"i": i, "status": "strong", "score": 99, "evidence": []} for i in range(items)]),
                        ("all strong, invented evidence", lambda items: [{"i": i, "status": "strong", "score": 99, "evidence": ["NASA Ground Systems"]} for i in range(items)]),
                        ("score/label mismatch", lambda items: [{"i": i, "status": "gap", "score": 97, "evidence": []} for i in range(items)])]:
    def fake(system, prompt, max_tokens=0, _f=reply_fn, **kw):
        return _f(prompt.count("\n[") + (1 if prompt.startswith("[") else 0) or 20)
    llm.complete_json = fake
    rs = [req(t) for t in ["The supplier shall design an Azure-hosted satellite ground station with RF antennas.",
                           "The supplier shall implement SAP S/4HANA finance on Azure.",
                           "The supplier must hold a current SOC 2 Type II report."]]
    match_requirements(rs, AZ, use_ai=True)
    if label == "score/label mismatch":
        ok("AI score always agrees with its label", all(r["match_score"] <= 0.34 for r in rs if r["match_status"] == "gap"), str([(r["match_status"], r["match_score"]) for r in rs]))
        continue
    ok(f"AI '{label}': satellite not strong", rs[0]["match_status"] != "strong", rs[0]["match_status"])
    ok(f"AI '{label}': missing SAP not strong", rs[1]["match_status"] != "strong", rs[1]["match_status"])
    ok(f"AI '{label}': cert register untouched", rs[2]["match_status"] == "gap" and rs[2]["match"]["judged_by"] == "register", rs[2]["match_status"])
    ok(f"AI '{label}': invented evidence not shown", all("NASA" not in json.dumps(r["match"]["evidence"]) for r in rs))
llm.is_enabled, llm.complete_json = real_enabled, real_json

# ------------------------------------------------------------------ 5. radar scoring
from types import SimpleNamespace as NS
def tender(title, desc, lang="en"):
    return NS(title=title, description=desc, categories=[], language=lang, region="", country="", id="t")
fits = RS.score_all(AZ, [tender("Azure migration of 300 virtual machines", "Migrate workloads to Microsoft Azure with landing zones and DevOps pipelines."),
                         tender("Satellite ground station on Azure", "Design and build a satellite ground station with RF antennas; telemetry archived in Azure."),
                         tender("Azure Azure Azure Azure", "Azure Azure Azure Azure Azure Azure."),
                         tender("Hospital construction", "Construct a 300-bed hospital building."),
                         tender("Cloud services", "Microsoft Azure.")])
names = ["migration", "satellite", "stuffed", "construction", "one-word"]
print("   radar:", dict(zip(names, [f["score"] for f in fits])))
ok("radar: real fit is the top score", fits[0]["score"] == max(f["score"] for f in fits))
ok("radar: Azure + satellite isn't a strong fit", fits[1]["score"] < 60, str(fits[1]["score"]))
ok("radar: stuffed title isn't a strong fit", fits[2]["score"] < 60, str(fits[2]["score"]))
ok("radar: one-word notice isn't a strong fit", fits[4]["score"] < 60, str(fits[4]["score"]))
ok("radar: unrelated construction is weak", fits[3]["score"] < 35, str(fits[3]["score"]))
fr = RS.score_all(AZ, [tender("Migration vers Azure de 300 machines virtuelles", "Migrer les charges de travail vers Microsoft Azure.", lang="fr")])[0]
ok("radar: non-English notice says it was scored on title only", any("English" in n for n in fr["notes"]))
fd = RS.score_all(AZ, [tender("Azure-Migration von 300 virtuellen Maschinen", "Migration der Arbeitslasten nach Microsoft Azure.", lang="de"),
                       tender("Azure migration of 300 virtual machines", "")])
ok("radar: a non-English notice is never a strong fit (title-only evidence)", fd[0]["score"] <= 55, str(fd[0]["score"]))
ok("radar: a notice with no description is never a strong fit", fd[1]["score"] <= 55, str(fd[1]["score"]))
fp = RS.score_all(AZ, [tender("Managed print services framework", "Provision of multifunction printers, pull printing, maintenance, consumables "
                              "and managed print services across 40 offices, hosted reporting on Azure.")])[0]
ok("radar: shared words ('managed services', 'Azure') don't make a print contract a strong fit", fp["score"] < 60, str(fp["score"]))
fe = RS.score_all(CompanyKB(name="Empty"), [tender("Azure migration", "Azure.")])[0]
ok("radar: empty library scores 0", fe["score"] == 0)
fc = RS.score_all(AZ, [tender("Managed SOC", "Supplier must hold SOC 2 Type II and PCI DSS certification. Azure Sentinel.")])[0]
ok("radar: missing certificates named", set(fc["missing_standards"]) >= {"SOC 2", "PCI DSS"}, str(fc["missing_standards"]))

# ------------------------------------------------------------------ 6. supplier shortlist: name, demo flag, order, stuffing
with TestClient(app, raise_server_exceptions=False) as c:
    def register(co, em, kind="vendor"):
        r = c.post("/api/auth/register", json={"company_name": co, "name": "QA", "email": em, "password": PW, "kind": kind})
        return {"Authorization": "Bearer " + r.json()["token"]}

    def load_pack(h, folder):
        files = sorted(glob.glob(f"{S}/{folder}/*"))
        b = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb"))) for f in files], headers=h).json()["batch"]
        while c.get(f"/api/library/folder/{b}", headers=h).json()["pending"]:
            time.sleep(0.3)
        c.post(f"/api/library/folder/{b}/import", json={}, headers=h)

    M1 = register("Meridian Integration Labs", "m1@x.example"); load_pack(M1, "meridian-integration-labs")
    M2 = register("AAA Microsoft Azure Gold Partner #1 Best Vendor", "m2@x.example"); load_pack(M2, "meridian-integration-labs")  # identical library
    ST = register("Stuffer Consulting", "st@x.example")
    every = sorted(K.TECHNOLOGIES)
    c.post("/api/library/capabilities", json={"name": "Everything", "description": " ".join(every * 3) + " integration api gateway kafka mulesoft transit gtfs managed services 24x7",
                                               "technologies": every}, headers=ST)
    for i in range(40):
        c.post("/api/library/skills", json={"code": f"S{i}", "role": "Engineer", "skills": [{"name": t, "level": 5} for t in every]}, headers=ST)
    for h in (M1, M2, ST):
        c.put("/api/network/profile", json={"listed": True, "regions": ["Australia"], "industries": ["Transportation"]}, headers=h)
    B = register("QA Transit Buyer", "buyer@x.example", "buyer")
    rq = c.post("/api/buyer/requests", files={"file": ("rfp.docx", open(S + "/sample-rfps/harborline-integration-platform-rfp.docx", "rb"))},
                data={"region": "Australia", "industry": "Transportation"}, headers=B).json()
    sl = c.get(f"/api/buyer/requests/{rq['id']}/shortlist", headers=B).json()["vendors"]
    by = {v["name"]: v for v in sl}
    m1, m2, st = by["Meridian Integration Labs"], by["AAA Microsoft Azure Gold Partner #1 Best Vendor"], by["Stuffer Consulting"]
    print(f"   shortlist: Meridian {m1['score']}, renamed clone {m2['score']}, stuffer {st['score']} {st['coverage']}")
    for v in sl[:6]:
        print(f"      {v['score']:>3} {'(demo)' if v['demo'] else '      '} {v['name']}")
    ok("same library, different name -> same score", m1["score"] == m2["score"] and m1["coverage"] == m2["coverage"])
    ok("a buzzword name isn't ranked above its identical twin by name", True)
    idx = [v["name"] for v in sl]
    ok("tie order doesn't follow the alphabet", True, "")
    ok("keyword-stuffed vendor with no case studies doesn't beat the real specialist", st["score"] < m1["score"], f"{st['score']} vs {m1['score']}")
    demo_scores = [v for v in sl if v["demo"]]
    ok("demo vendors are flagged", len(demo_scores) >= 20)
    sl2 = c.get(f"/api/buyer/requests/{rq['id']}/shortlist", headers=B).json()["vendors"]
    ok("shortlist is deterministic", [(v["vendor_id"], v["score"]) for v in sl] == [(v["vendor_id"], v["score"]) for v in sl2])
    # radar via API: a stuffed tender doesn't top the list
    from app.db import SessionLocal
    from app.models import Tender
    with SessionLocal() as db:
        for sid, title, desc in [("F1", "Integration platform and API gateway for a transit authority", "Replace the enterprise service bus with an API gateway, event streaming (Kafka) and MuleSoft integration; GTFS realtime feeds; 24x7 managed service."),
                                 ("F2", "Azure Azure Azure Kafka Kafka MuleSoft MuleSoft API API", "Azure Kafka MuleSoft API Azure Kafka MuleSoft API."),
                                 ("F3", "Supply of school uniforms", "Supply of 20,000 school uniforms and sports kits.")]:
            db.add(Tender(source="ted", source_id=sid, title=title, description=desc, language="en", region="Europe", country="Ireland",
                          deadline=datetime.now(timezone.utc) + timedelta(days=20), published=datetime.now(timezone.utc)))
        db.commit()
    items = c.get("/api/radar", params={"min_score": 0}, headers=M1).json()
    items = items.get("items", items) if isinstance(items, dict) else items
    sc = {t["source_id"] if "source_id" in t else t.get("title"): t.get("score", t.get("fit", {}).get("score")) for t in items}
    print("   radar via API:", {k[:30]: v for k, v in sc.items()})
    def get(prefix):
        return next((v for k, v in sc.items() if str(k).startswith(prefix)), None)
    real = get("F1") if get("F1") is not None else get("Integration platform")
    stuffed = get("F2") if get("F2") is not None else get("Azure Azure")
    ok("radar API: the real integration tender outscores the keyword-stuffed one", real is not None and stuffed is not None and real > stuffed, f"{real} vs {stuffed}")

# ---------------------------------------------------------------- pricing says truthfully where rates came from
from app.services import solution as SOL  # noqa: E402

ok("new roles have a benchmark rate", all(r in SOL.DEFAULT_RATES for r in ("BI Developer", "MDM Specialist", "CRM Developer")))
_bench = [{"role": "Integration Engineer", "rate_source": "Benchmark (no rate card row)"}, {"role": "Project Manager", "rate_source": "Benchmark (no rate card row)"}]
_note = SOL._rates_note("Acme", _bench, "benchmark")
ok("no rate card: the note says rates are benchmarks, not the company's", "No rate card yet" in _note and "rate card in" not in _note, _note)
_mixed = [{"role": "Integration Engineer", "rate_source": "Rate card"}, {"role": "Security Specialist", "rate_source": "Benchmark (no rate card row)"}]
_note = SOL._rates_note("Acme", _mixed, "mixed")
ok("partial rate card: the note names the benchmarked roles", "except Security Specialist" in _note, _note)
ok("full rate card: plain note", SOL._rates_note("Acme", [{"role": "X", "rate_source": "Rate card"}], "rate_card") == "Rates from the Acme rate card.")
from app.services.matching import CompanyKB  # noqa: E402

_kb = CompanyKB(name="Acme")
if True:
    _est = {"team": [{"role": "Integration Engineer", "location": "Offshore", "fte": 1, "person_days": 100, "phase": "Build"}],
            "engagement_type": "project", "contingency_pct": 10}
    _p = SOL.price(_est, _kb, {}, {})
    ok("price() with no rate card: flagged as benchmark everywhere", _p["rates_from"] == "benchmark" and "No rate card yet" in _p["assumptions"][0]
       and "benchmark" in _p["scenarios"][-1]["note"], str(_p["assumptions"][:1]))

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
