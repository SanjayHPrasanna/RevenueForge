"""QA: the compliance features. Public trust facts, tender licences, the free-tier AI confirmation, company export and delete."""
import os, sys, tempfile, glob, time, json, io, zipfile
os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"; os.environ["DEMO_VENDORS"] = "false"
os.environ["OPERATOR_NAME"] = "QA Operator Pvt Ltd"; os.environ["CONTACT_EMAIL"] = "privacy@qa.example"; os.environ["DATA_LOCATION"] = "Microsoft Azure, Central India"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.config import OUTPUT_DIR, UPLOAD_DIR
from app.services import llm

PW = os.environ.get("QA_PASSWORD") or __import__("secrets").token_urlsafe(18)
S = os.path.join(ROOT, "sample-data")
RFP = S + "/sample-rfps/harborline-integration-platform-rfp.docx"
FAILS, PASSES = [], 0


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


with TestClient(app, raise_server_exceptions=False) as c:
    def reg(co, em, kind="vendor"):
        r = c.post("/api/auth/register", json={"company_name": co, "name": "QA Admin", "email": em, "password": PW, "kind": kind})
        return {"Authorization": "Bearer " + r.json()["token"]}

    def wait(did, h):
        while c.get(f"/api/deals/{did}", headers=h).json()["status"] == "processing":
            time.sleep(0.5)

    # ------------------------------------------------------------------ trust facts
    t = c.get("/api/trust")
    ok("trust page is public", t.status_code == 200)
    t = t.json()
    ok("operator, contact and location come from config", t["operator"] == "QA Operator Pvt Ltd" and t["contact"] == "privacy@qa.example"
       and t["data_location"] == "Microsoft Azure, Central India")
    ok("AI off is stated plainly", t["ai"]["enabled"] is False and "rules engine" in t["ai"]["summary"])
    ok("hosting listed as a sub-processor", t["subprocessors"][0]["name"] == "Microsoft Azure")
    ok("every tender source has a licence and attribution", all(s["licence"] and s["licence_url"] and s["attribution"] for s in t["sources"]))
    ok("'not yet' list is honest about certification and MFA", any("certification" in x for x in t["not_yet"]) and any("MFA" in x for x in t["not_yet"]))
    blob = json.dumps(t).lower()
    ok("no secrets in trust facts", not any(x in blob for x in ("api_key", "jwt", "password_hash", "secret")))
    # free-tier wording when Gemini free is the platform default
    real = llm.server_profile
    llm.server_profile = lambda: llm.Profile(provider="gemini", gemini_api_key="x", paid=False)
    t2 = c.get("/api/trust").json()
    ok("free Gemini tier: says Google may use the content", "free-tier" in t2["ai"]["training"] and "improve" in t2["ai"]["training"])
    llm.server_profile = lambda: llm.Profile(provider="gemini", gemini_api_key="x", paid=True)
    ok("paid Gemini: says it isn't used to improve products", "aren't used" in c.get("/api/trust").json()["ai"]["training"])
    llm.server_profile = real

    # ------------------------------------------------------------------ fixtures
    A = reg("Meridian Integration Labs", "admin@comp-a.example")
    c.post("/api/auth/users", json={"name": "Priya", "email": "presales@comp-a.example", "role": "presales", "password": PW}, headers=A)
    AP = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "presales@comp-a.example", "password": PW}).json()["token"]}
    B = reg("Cobalt Ridge Technologies", "admin@comp-b.example")
    files = sorted(glob.glob(S + "/meridian-integration-labs/*"))
    for h in (A, B):
        b = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb"))) for f in files], headers=h).json()["batch"]
        while c.get(f"/api/library/folder/{b}", headers=h).json()["pending"]:
            time.sleep(0.3)
        c.post(f"/api/library/folder/{b}/import", json={}, headers=h)

    # ------------------------------------------------------------------ tender licence on each tender
    from app.db import SessionLocal
    from app.models import Tender, AuditLog, Tenant, User, Deal
    with SessionLocal() as db:
        db.add(Tender(source="uk_fts", source_id="LIC-1", title="Integration platform", description="API gateway", language="en",
                      deadline=datetime.now(timezone.utc) + timedelta(days=9), published=datetime.now(timezone.utc)))
        db.commit()
    items = c.get("/api/radar", headers=A).json()
    items = items.get("items", items) if isinstance(items, dict) else items
    tt = next(x for x in items if x["title"] == "Integration platform")
    ok("tender carries its licence", tt["licence"] == "Open Government Licence v3.0" and "Open Government Licence" in tt["attribution"])

    # ------------------------------------------------------------------ free-tier confirmation
    real_ft = llm.free_tier
    llm.free_tier = lambda: True
    r = c.post("/api/deals", files={"file": ("rfp.docx", open(RFP, "rb"))}, data={"name": "No ack"}, headers=AP)
    ok("free tier: RFP refused without confirmation (428)", r.status_code == 428 and "free Google Gemini key" in r.json()["detail"], str(r.status_code))
    ok("free tier: nothing was stored", not any(d["name"] == "No ack" for d in (c.get("/api/deals", headers=A).json().get("items", c.get("/api/deals", headers=A).json())
                                                                               if isinstance(c.get("/api/deals", headers=A).json(), dict) else c.get("/api/deals", headers=A).json())))
    llm.free_tier = real_ft  # keep the run itself off the AI
    llm_ack = True
    llm.free_tier = lambda: True
    r = c.post("/api/deals", files={"file": ("rfp.docx", open(RFP, "rb"))}, data={"name": "Harborline", "client_name": "Harbour Region Transit Authority", "ai_ack": "true"}, headers=AP)
    ok("free tier: accepted with confirmation", r.status_code == 200, r.text[:120])
    llm.free_tier = real_ft
    did = r.json()["id"]
    wait(did, A)
    llm.free_tier = lambda: False
    r = c.post("/api/deals", files={"file": ("rfp.docx", open(RFP, "rb"))}, data={"name": "Paid"}, headers=AP)
    ok("paid/no AI: no confirmation needed", r.status_code == 200)
    llm.free_tier = real_ft
    wait(r.json()["id"], A)
    # invitation accept
    C = reg("QA Buyer Authority", "admin@comp-c.example", "buyer")
    c.put("/api/network/profile", json={"listed": True}, headers=A)
    c.put("/api/network/profile", json={"listed": True}, headers=B)
    rq = c.post("/api/buyer/requests", files={"file": ("rfp.docx", open(RFP, "rb"))}, headers=C).json()
    sl = c.get(f"/api/buyer/requests/{rq['id']}/shortlist", headers=C).json()["vendors"]
    ids = [v["vendor_id"] for v in sl if v["name"] in ("Meridian Integration Labs", "Cobalt Ridge Technologies")]
    c.post(f"/api/buyer/requests/{rq['id']}/invite", json={"vendor_ids": ids}, headers=C)
    inv_a = c.get("/api/network/invitations", headers=A).json()[0]["id"]
    inv_b = c.get("/api/network/invitations", headers=B).json()[0]["id"]
    llm.free_tier = lambda: True
    ok("free tier: accepting an invitation needs confirmation", c.post(f"/api/network/invitations/{inv_b}/accept", json={}, headers=B).status_code == 428)
    r = c.post(f"/api/network/invitations/{inv_b}/accept", json={"ai_ack": True}, headers=B)
    ok("free tier: accepted with confirmation", r.status_code == 200, r.text[:100])
    llm.free_tier = real_ft
    deal_b_from_c = r.json()["deal_id"]
    wait(deal_b_from_c, B)

    # ------------------------------------------------------------------ export
    with SessionLocal() as db:
        ta = db.scalar(__import__("sqlalchemy").select(Tenant).where(Tenant.name == "Meridian Integration Labs"))
        ta.settings = {**(ta.settings or {}), "ai": {"provider": "gemini", "keys": {"gemini": "SECRETKEY-QA-123"}, "api_key": "SECRETKEY-QA-456"}}
        db.commit(); tid_a = ta.id
    ok("presales can't export", c.get("/api/company/export", headers=AP).status_code == 403)
    x = c.get("/api/company/export", headers=A)
    ok("admin export downloads a zip", x.status_code == 200 and x.content[:2] == b"PK", str(x.status_code))
    z = zipfile.ZipFile(io.BytesIO(x.content))
    names = z.namelist()
    ok("export has profile, users, library, deals, audit log", all(any(n.startswith(p) for n in names) for p in ("company.json", "users.json", "library/capabilities.json", f"deals/{did}/requirements.json", "audit_log.json")))
    ok("export includes uploaded files", any(n.startswith("files/uploads/") for n in names))
    ok("export includes generated documents", any(n.startswith("files/outputs/") for n in names), str([n for n in names if n.startswith("files/")][:3]))
    every = b"".join(z.read(n) for n in names if n.endswith(".json"))
    ok("no password hashes in export", b"pbkdf2$" not in every)
    ok("no AI keys in export", b"SECRETKEY-QA" not in every)
    ok("no other company's data in export", b"Cobalt Ridge" not in z.read("company.json") and b"admin@comp-b.example" not in every)
    caps = json.loads(z.read("library/capabilities.json"))
    ok("library export complete", len(caps) == len(c.get("/api/library/capabilities", headers=A).json()))

    # ------------------------------------------------------------------ delete
    ok("presales can't delete the company", c.post("/api/company/delete", json={"confirm_name": "Meridian Integration Labs", "password": PW}, headers=AP).status_code == 403)
    ok("wrong name refused", c.post("/api/company/delete", json={"confirm_name": "meridian", "password": PW}, headers=A).status_code == 400)
    ok("wrong password refused", c.post("/api/company/delete", json={"confirm_name": "Meridian Integration Labs", "password": "wrong-password"}, headers=A).status_code == 403)
    ok("company still there after refusals", c.get("/api/auth/me", headers=A).status_code == 200)
    c.post(f"/api/network/invitations/{inv_a}/decline", headers=A)
    r = c.post("/api/company/delete", json={"confirm_name": "Meridian Integration Labs", "password": PW}, headers=A)
    ok("admin deletes the company", r.status_code == 200 and r.json()["deleted"], r.text[:200])
    ok("admin's token stops working", c.get("/api/auth/me", headers=A).status_code == 401)
    ok("presales' token stops working", c.get("/api/auth/me", headers=AP).status_code == 401)
    ok("can't sign in any more", c.post("/api/auth/login", json={"email": "admin@comp-a.example", "password": PW}).status_code == 401)
    from sqlalchemy import inspect as sa_inspect, select, text
    from app.db import engine
    with SessionLocal() as db:
        left = 0
        insp = sa_inspect(engine)
        for tbl in insp.get_table_names():
            cols = [col["name"] for col in insp.get_columns(tbl)]
            for col in ("tenant_id", "buyer_tenant_id", "vendor_tenant_id"):
                if col in cols:
                    left += db.execute(text(f"SELECT count(*) FROM {tbl} WHERE {col} = :t"), {"t": tid_a}).scalar()
        ok("no rows left for the deleted company (except the anonymous deletion record)", left == 0, f"{left} rows")
        rec = db.scalars(select(AuditLog).where(AuditLog.action == "company.deleted")).all()
        ok("one anonymous deletion record kept", len(rec) == 1 and rec[0].user == "" and rec[0].target == tid_a and "Meridian" not in json.dumps(rec[0].detail))
        ok("deleted company not in tenants", db.get(Tenant, tid_a) is None)
    ok("uploaded files deleted", not (UPLOAD_DIR / tid_a).exists())
    ok("generated files deleted", not (OUTPUT_DIR / tid_a).exists())
    ok("other company untouched", c.get("/api/library/capabilities", headers=B).status_code == 200 and len(c.get("/api/library/capabilities", headers=B).json()) > 0)
    ok("deleted vendor gone from the buyer's shortlist", not any(v["name"] == "Meridian Integration Labs" for v in c.get(f"/api/buyer/requests/{rq['id']}/shortlist", headers=C).json()["vendors"]))
    # buyer deletes: the supplier keeps the deal it accepted
    r = c.post("/api/company/delete", json={"confirm_name": "QA Buyer Authority", "password": PW}, headers=C)
    ok("buyer deletes its company", r.status_code == 200, r.text[:150])
    ok("supplier keeps the deal it already accepted", c.get(f"/api/deals/{deal_b_from_c}", headers=B).status_code == 200)
    ok("supplier's invitation list no longer shows the deleted buyer", c.get("/api/network/invitations", headers=B).json() == [])

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
