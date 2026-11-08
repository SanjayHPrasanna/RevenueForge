"""QA: "Find customers". Award parsers on real notice shapes (TED, UK Find a Tender, CanadaBuys), storage and pruning, the
honest matcher (no single-keyword matches, title-only notices capped, stuffing doesn't help), renewals window, customer
grouping, region filter, permissions and the Excel export."""
import os, sys, tempfile, glob, time, json, io
os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"; os.environ["DEMO_VENDORS"] = "false"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.services import award_feeds as AF

PW = os.environ.get("QA_PASSWORD") or __import__("secrets").token_urlsafe(18)
S = os.path.join(ROOT, "sample-data")
FX = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "awards_samples.json"), encoding="utf-8"))
FAILS, PASSES = [], 0


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


# ------------------------------------------------------------------ parsers on real notice shapes
a = AF.parse_ted_award(FX["ted"][0])
ok("TED: English award parsed", a and a["suppliers"] == ["aScan AS"] and a["value"] == 1800000 and a["currency"] == "NOK", str(a)[:200])
ok("TED: lead buyer, country, region", a["buyer"] == "Innherred Anskaffelser" and a["country"] == "Norway" and a["region"] == "Europe", str((a["buyer"], a["country"], a["region"])))
ok("TED: published contract end used", a["contract_end"].date().isoformat() == "2030-10-09" and a["end_basis"] == "published end date")
ok("TED: awarded = contract conclusion", a["awarded"].date().isoformat() == "2026-10-16")
b = AF.parse_ted_award(FX["ted"][1])
ok("TED: Greek award keeps both winners", b and len(b["suppliers"]) == 2, str(b and b["suppliers"]))
ok("TED: end = start + 12 months when only a duration is given", b["end_basis"] == "start + duration" and b["contract_end"].date().isoformat()[:7] == "2027-10", str(b["contract_end"]))
ok("TED: non-English marked", b["language"] == "el" and b["categories"][0]["label"] == "Software package suites")
ok("TED: a notice without a winner is skipped", AF.parse_ted_award(FX["ted"][2]) is None)
u = AF.parse_ocds_award(FX["uk"][0])
ok("UK: IT award parsed", u and u["suppliers"] == ["TOTALMOBILE LIMITED"] and round(u["value"]) == 406606 and u["currency"] == "GBP", str(u)[:200])
ok("UK: no end date invented", u["contract_end"] is None and u["end_basis"] == "")
ok("UK: non-IT award (health services) skipped", AF.parse_ocds_award(FX["uk"][1]) is None)
row = {"title-titre-eng": "Enterprise integration platform support", "referenceNumber-numeroReference": "PW-24-0001", "amendmentNumber-numeroModification": "000",
       "contractAwardDate-dateAttributionContrat": "2025-05-01", "contractEndDate-dateFinContrat": "2027-04-30", "totalContractValue-valeurTotaleContrat": "1250000.00",
       "contractCurrency-contratMonnaie": "CAD", "awardStatus-attributionStatut-eng": "Active", "gsin-nibs": "*D302A", "gsinDescription-nibsDescription-eng": "*Systems Development Services",
       "supplierLegalName-nomLegalFournisseur-eng": "Northern Systems Inc.", "contractingEntityName-nomEntitContractante-eng": "Shared Services Canada",
       "awardDescription-descriptionAttribution-eng": "Support for the MuleSoft integration platform.", "contactInfoEmail-informationsContactCourriel": "person@example.gc.ca",
       "contactInfoName-informationsContactNom": "Jane Person"}
c = AF.parse_canada_award(row)
ok("Canada: IT award parsed with end date", c and c["contract_end"].date().isoformat() == "2027-04-30" and c["suppliers"] == ["Northern Systems Inc."], str(c)[:200])
ok("Canada: no personal contact kept", "person@example" not in json.dumps(c, default=str) and "Jane Person" not in json.dumps(c, default=str))
ok("Canada: non-IT award skipped", AF.parse_canada_award({**row, "gsin-nibs": "*SRV", "unspsc": ""}) is None)
ok("duration in years", AF._add_duration(datetime(2026, 1, 1, tzinfo=timezone.utc), ["2"], ["YEAR"]).year == 2028)
ok("nonsense duration ignored", AF._add_duration(datetime(2026, 1, 1, tzinfo=timezone.utc), ["9999"], ["MONTH"]) is None)

# ------------------------------------------------------------------ app-level
now = datetime.now(timezone.utc)
with TestClient(app, raise_server_exceptions=False) as cl:
    def reg(co, em, kind="vendor"):
        return {"Authorization": "Bearer " + cl.post("/api/auth/register", json={"company_name": co, "name": "QA", "email": em, "password": PW, "kind": kind}).json()["token"]}
    A = reg("Meridian Integration Labs", "a@cust.example")
    B = reg("Other Vendor", "b@cust.example")
    C = reg("Buyer Org", "c@cust.example", "buyer")
    cl.post("/api/auth/users", json={"name": "Vee", "email": "v@cust.example", "role": "viewer", "password": PW}, headers=A)
    V = {"Authorization": "Bearer " + cl.post("/api/auth/login", json={"email": "v@cust.example", "password": PW}).json()["token"]}
    files = sorted(glob.glob(S + "/meridian-integration-labs/*"))
    bt = cl.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb"))) for f in files], headers=A).json()["batch"]
    while cl.get(f"/api/library/folder/{bt}", headers=A).json()["pending"]:
        time.sleep(0.3)
    cl.post(f"/api/library/folder/{bt}/import", json={}, headers=A)
    accs = cl.get("/api/library/accelerators", headers=A).json()
    hl7 = next(x for x in accs if x["name"] == "HL7 Interface Factory")

    from app.db import SessionLocal
    from app.models import Award, Tender
    D = lambda days: now + timedelta(days=days)
    with SessionLocal() as db:
        T = lambda sid, title, desc, lang="en", buyer="NHS Trust A", country="United Kingdom", region="United Kingdom", **kw: Tender(
            source="uk_fts" if region == "United Kingdom" else "ted", source_id=sid, title=title, description=desc, language=lang, buyer=buyer,
            country=country, region=region, deadline=D(20), published=D(-3), **kw)
        db.add_all([
            T("T1", "Integration engine and HL7 interfaces for hospital EPR", "The trust requires a supplier to build and support HL7 v2 and FHIR interfaces "
              "between the EPR, laboratory (LIS) and radiology (RIS/PACS) systems on its Rhapsody integration engine, with route templates, mappers and test packs.",
              buyer="Northshire Hospitals NHS Trust"),
            T("T2", "Azure cloud hosting for hospital estates system", "Hosting of the hospital estates and facilities management system on Microsoft Azure.",
              buyer="Westshire NHS Trust"),
            T("T3", "HL7-Schnittstellen, FHIR-Integration und Rhapsody-Betrieb für Klinikum", "Aufbau von HL7- und FHIR-Schnittstellen zwischen KIS, LIS und RIS.",
              lang="de", buyer="Klinikum Nord", country="Germany", region="Europe"),
            T("T5", "FHIR-Server für Klinikum", "Beschaffung eines FHIR-Servers.", lang="de", buyer="Klinikum Süd", country="Germany", region="Europe"),
            T("T4", "Catering services for hospital staff", "Provision of catering and vending for staff restaurants.", buyer="Northshire Hospitals NHS Trust"),
        ])
        Aw = lambda sid, title, desc, buyer, end, sup="Incumbent Health IT Ltd", region="United Kingdom", country="United Kingdom", src="ted", awarded=-400: Award(
            source=src, source_id=sid, title=title, description=desc, language="en", buyer=buyer, country=country, region=region,
            suppliers=[sup], value=850000, currency="GBP", awarded=D(awarded), contract_end=end, end_basis="published end date" if end else "")
        db.add_all([
            Aw("A1", "HL7 integration services for the hospital network", "Build and run HL7 v2 and FHIR interfaces between the EPR, LIS and PACS on Rhapsody, "
               "including interface templates and regression test packs.", "Northshire Hospitals NHS Trust", D(300)),
            Aw("A2", "Clinical interface engine support", "Support of HL7 interfaces and FHIR APIs on the Rhapsody integration engine for the hospital.",
               "Eastshire NHS Trust", D(90)),
            Aw("A3", "HL7 interface development framework", "HL7 v2 and FHIR interface development with mappers and test packs for hospital systems.",
               "Southshire NHS Trust", None),
            Aw("A4", "Hospital car park management", "Car park barriers, ANPR cameras and payment machines for the hospital.", "Northshire Hospitals NHS Trust", D(300)),
            Aw("A5", "HL7 FHIR integration for regional health records", "FHIR and HL7 v2 interfaces between hospital EPR, LIS and RIS via an integration engine.",
               "Region Nord Health", D(400), region="Europe", country="Norway"),
        ])
        db.commit()

    r = cl.post("/api/insights/customers", json={"item_id": hl7["id"]}, headers=V)
    ok("viewer can search", r.status_code == 200, r.text[:200])
    res = r.json()
    print("   key terms:", res["key_terms"])
    titles = lambda lst: [x["title"][:40] for x in lst]
    print("   buying now:", [(x["score"], x["title"][:40]) for x in res["buying_now"]])
    print("   bought before:", [(x["score"], x["title"][:40]) for x in res["bought_before"]])
    ok("buying now: the HL7 tender is a strong match", res["buying_now"] and res["buying_now"][0]["title"].startswith("Integration engine and HL7")
       and res["buying_now"][0]["score"] >= 60, str(res["buying_now"][:1]))
    ok("buying now: Azure hosting (shares only 'hospital') isn't listed", not any(x["title"].startswith("Azure cloud") for x in res["buying_now"]))
    ok("buying now: catering isn't listed", not any("Catering" in x["title"] for x in res["buying_now"]))
    de = [x for x in res["buying_now"] if x["title"].startswith("HL7-Schnittstellen")]
    ok("German notice listed but capped (title only)", de and de[0]["score"] <= 55 and any("title only" in n for n in de[0]["notes"]), str(de))
    ok("German notice sharing a single technology isn't listed", not any(x["title"].startswith("FHIR-Server") for x in res["buying_now"]))
    ok("each result says why", all(x["why"] for x in res["buying_now"] + res["bought_before"]))
    ok("bought before: HL7 awards found, car park not", {"HL7 integration services for the hospi", "Clinical interface engine support", "HL7 interface development fra"}
       <= {x["title"][:38] for x in res["bought_before"]} | {x["title"][:32] for x in res["bought_before"]} | {x["title"][:29] for x in res["bought_before"]}
       and not any("car park" in x["title"].lower() for x in res["bought_before"]), str(titles(res["bought_before"])))
    ok("renewals: only contracts ending in 6-18 months", [x["title"][:20] for x in res["renewals"]] == ["HL7 integration serv", "HL7 FHIR integration"],
       str([(x["title"][:20], x["contract_end"][:10]) for x in res["renewals"]]))
    ok("renewal window reports the ones ending sooner and without dates", res["renewal_window"]["ending_sooner"] == 1 and res["renewal_window"]["no_end_date"] == 1,
       str(res["renewal_window"]))
    cust = {c["buyer"]: c for c in res["customers"]}
    nh = cust.get("Northshire Hospitals NHS Trust")
    ok("customer grouping: open tender + past award for the same buyer", nh and nh["open_tenders"] == 1 and nh["past_awards"] == 1
       and nh["suppliers"] == ["Incumbent Health IT Ltd"], str(nh)[:200])
    ok("customer with an open tender listed first", res["customers"][0]["buyer"] == "Northshire Hospitals NHS Trust")
    r2 = cl.post("/api/insights/customers", json={"item_id": hl7["id"], "regions": ["Europe"]}, headers=A).json()
    ok("region filter", all(x["region"] == "Europe" for x in r2["buying_now"] + r2["bought_before"]) and r2["bought_before"], str(titles(r2["bought_before"])))
    # described product (planned)
    r3 = cl.post("/api/insights/customers", json={"name": "FHIR consent manager", "description": "A planned product that manages patient consent for "
                                                                                                "sharing records through HL7 FHIR APIs between hospitals and regional health record systems."}, headers=A).json()
    ok("a typed description works (planned product)", r3["product"]["kind"] == "Described product" and r3["bought_before"], str(r3.get("key_terms")))
    r4 = cl.post("/api/insights/customers", json={"description": "Azure Azure Azure Azure Azure Azure"}, headers=A).json()
    ok("keyword-only description finds nothing and says why", not r4["buying_now"] and not r4["bought_before"] and r4["warning"], str(r4.get("warning")))
    stuffed = cl.post("/api/insights/customers", json={"description": "HL7 HL7 HL7 HL7 HL7 HL7 FHIR FHIR FHIR interfaces interfaces interfaces hospital hospital"}, headers=A).json()
    honest = cl.post("/api/insights/customers", json={"description": "HL7 FHIR interfaces hospital"}, headers=A).json()  # the same words, once
    top = lambda x: max([i["score"] for i in x["buying_now"]] or [0])
    ok("repeating words doesn't raise scores", top(stuffed) <= top(honest) + 2, f"{top(stuffed)} vs {top(honest)}")
    ok("too-short description refused", cl.post("/api/insights/customers", json={"description": "HL7"}, headers=A).status_code == 400)
    ok("another company's library item refused", cl.post("/api/insights/customers", json={"item_id": hl7["id"]}, headers=B).status_code == 404)
    ok("buyer workspaces can't use it", cl.post("/api/insights/customers", json={"description": "x" * 40}, headers=C).status_code == 403)
    ok("signed out refused", cl.post("/api/insights/customers", json={"description": "x" * 40}).status_code == 401)
    ok("malformed body handled", cl.post("/api/insights/customers", json=["x"], headers=A).status_code in (400, 422))
    x = cl.post("/api/insights/customers/export", json={"item_id": hl7["id"]}, headers=V)
    ok("Excel export", x.status_code == 200 and x.content[:2] == b"PK", str(x.status_code))
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(x.content))
    ok("export sheets", wb.sheetnames == ["Summary", "Buying now", "Bought before", "Renewals", "Customers"], str(wb.sheetnames))
    ok("export rows match", wb["Buying now"].max_row - 1 == len(res["buying_now"]) and wb["Customers"].max_row - 1 == len(res["customers"]))
    ok("no formulas in export", not any(c.data_type == "f" for ws in wb for row in ws.iter_rows() for c in row))
    # storing and pruning
    with SessionLocal() as db:
        n = AF.store(db, [AF.parse_ted_award(FX["ted"][0]), AF.parse_ted_award(FX["ted"][0]), AF.parse_ocds_award(FX["uk"][0]), {"bad": 1}, "x"])
        ok("store: duplicates merged, junk skipped", n == 3 and db.query(Award).filter(Award.source_id == "723751-2026").count() == 1)
        db.add(Award(source="ted", source_id="OLD", title="Old", buyer="x", awarded=now - timedelta(days=365 * 4), contract_end=now - timedelta(days=10)))
        db.add(Award(source="ted", source_id="OLD-RUNNING", title="Old but running", buyer="x", awarded=now - timedelta(days=365 * 4), contract_end=now + timedelta(days=100)))
        db.commit()
        AF.prune(db)
        ok("prune: old finished contracts removed, running ones kept", not db.query(Award).filter(Award.source_id == "OLD").count()
           and db.query(Award).filter(Award.source_id == "OLD-RUNNING").count() == 1)
    src = cl.get("/api/radar/sources", headers=A).json()
    ok("sources panel lists award sources", len(src.get("awards", [])) == 3, str(src.get("awards"))[:200])

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
