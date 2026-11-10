"""Platform console: access, privacy, controls and dashboards.

Run: python tests/qa_platform.py
"""
import json
import logging
import os
import secrets
import sys
import tempfile

os.environ.update(RF_DATA_DIR=tempfile.mkdtemp(), LLM_PROVIDER="none", RADAR_REFRESH_HOURS="0", DEMO_VENDORS="false",
                  PLATFORM_ADMINS="ops@platform.example")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

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


def pw():
    return "Qa-" + secrets.token_hex(8) + "!A1"


SECRET_WORDS = ["Harborline", "Client H", "INT-07", "fare collection", "HL7 Interface Factory", "Meridian Health Exchange"]

with TestClient(app) as c:
    P = {}  # passwords per email (generated, never printed)

    def register(company, email, kind="vendor"):
        P[email] = pw()
        r = c.post("/api/auth/register", json={"company_name": company, "name": email.split("@")[0], "email": email, "password": P[email], "kind": kind})
        return r.json()

    def login(email, password=None):
        return c.post("/api/auth/login", json={"email": email, "password": password or P[email]})

    ops = register("Operator Co", "ops@platform.example")
    O = {"Authorization": "Bearer " + ops["token"]}
    acme = register("Acme Integration", "admin@acme.example")
    A = {"Authorization": "Bearer " + acme["token"]}
    buyer = register("City Buyer", "buyer@city.example", kind="buyer")
    ok("platform admin flag is sent to the app", ops["user"]["platform_admin"] is True and acme["user"]["platform_admin"] is False)

    # Acme: two more people, a confidential deal and a library
    for email, role in (("pres@acme.example", "presales"), ("view@acme.example", "viewer")):
        P[email] = pw()
        c.post("/api/auth/users", json={"name": email, "email": email, "role": role, "password": P[email]}, headers=A)
    rfp = os.path.join(ROOT, "sample-data", "sample-rfps", "harborline-integration-platform-rfp.docx")
    with open(rfp, "rb") as f:
        d = c.post("/api/deals", files={"file": ("rfp.docx", f)}, data={"name": "Harborline platform", "client_name": "Harborline Regional Transit Authority",
                                                                        "client_alias": "Client H", "confidential": "true"}, headers=A)
    ok("deal created in Acme", d.status_code == 200, d.text[:200])
    import glob
    lib = sorted(glob.glob(os.path.join(ROOT, "sample-data", "meridian-integration-labs", "*")))
    b = c.post("/api/library/folder", files=[("files", (os.path.basename(x), open(x, "rb"))) for x in lib], headers=A).json()["batch"]
    import time as _t
    for _ in range(100):
        if not c.get(f"/api/library/folder/{b}", headers=A).json()["pending"]:
            break
        _t.sleep(0.2)
    c.post(f"/api/library/folder/{b}/import", json={}, headers=A)

    # AI usage for Acme and the website chat
    tok = llm._tenant.set(acme["user"]["tenant"]["id"])
    llm._record("azure", "gpt-4.1-mini", True, 1.2, 900)
    llm._record("azure", "gpt-4.1-mini", False, 20, 0)
    llm._tenant.reset(tok)
    llm._record("gemini", "gemini-3.8-flash", False, 13, 0)
    logging.getLogger("revenueforge.test").warning("Maahi chat failed for someone@acme.example with key=abcd1234efgh5678")

    # failed sign-ins: unknown email, wrong password, then a lockout
    login("nobody@nowhere.example", "wrong-wrong-wrong")
    for _ in range(6):
        login("view@acme.example", "definitely-not-it")

    # ---------------------------------------------------------------- access
    for path in ("/api/platform/overview", "/api/platform/companies", "/api/platform/ai", "/api/platform/health", "/api/platform/security"):
        ok(f"{path}: company admin is refused", c.get(path, headers=A).status_code == 403)
        ok(f"{path}: signed out is refused", c.get(path).status_code == 401)
        ok(f"{path}: platform admin gets it", c.get(path, headers=O).status_code == 200)

    # ---------------------------------------------------------------- privacy
    ov = c.get("/api/platform/overview", headers=O).json()
    cos = c.get("/api/platform/companies", headers=O).json()
    acme_id = acme["user"]["tenant"]["id"]
    det = c.get(f"/api/platform/companies/{acme_id}", headers=O).json()
    sec = c.get("/api/platform/security", headers=O).json()
    ai = c.get("/api/platform/ai", headers=O).json()
    hl = c.get("/api/platform/health", headers=O).json()
    blob = json.dumps([ov, cos, det, sec, ai, hl])
    leaked = [w for w in SECRET_WORDS if w.lower() in blob.lower()]
    ok("no deal, client, requirement or library content anywhere in the console", not leaked, str(leaked))
    ok("no password hashes or keys in the console", "pbkdf2" not in blob and "abcd1234efgh5678" not in blob)

    # ---------------------------------------------------------------- numbers
    ok("overview: 3 companies (2 sellers, 1 buyer)", ov["companies"]["total"] == 3 and ov["companies"]["buyers"] == 1, str(ov["companies"]))
    ok("overview: 5 people", ov["people"]["total"] == 5, str(ov["people"]))
    ok("overview: 1 deal", ov["deals"]["total"] == 1)
    ok("overview: AI calls and failures counted", ov["ai"]["calls"] == 3 and ov["ai"]["failures"] == 2, str(ov["ai"]))
    ok("overview: a day-by-day series", len(ov["series"]) == 30 and sum(s["deals"] for s in ov["series"]) == 1)
    a = next(x for x in cos if x["id"] == acme_id)
    ok("companies: Acme shows 3 people with their roles", a["people"] == 3 and a["roles"] == {"admin": 1, "presales": 1, "viewer": 1}, str(a["roles"]))
    ok("companies: library shown as counts only", a["library"]["capabilities"] > 0 and isinstance(a["library"]["capabilities"], int))
    ok("companies: deal count and AI usage", a["deals"] == 1 and a["ai"]["calls_30d"] == 2 and a["ai"]["failures_30d"] == 1, str(a["ai"]))
    ok("companies: storage measured", a["storage_bytes"] > 0)
    ok("company detail lists people with name, email and role",
       {p["email"]: p["role"] for p in det["people_list"]} == {"admin@acme.example": "admin", "pres@acme.example": "presales", "view@acme.example": "viewer"})
    ok("company detail: AI by model", det["ai_models"][0]["model"] == "gpt-4.1-mini" and det["ai_models"][0]["tokens"] == 900, str(det["ai_models"]))
    ok("AI page: website chat counted apart from companies", ai["website_chat"]["calls"] == 1 and ai["website_chat"]["failures"] == 1)

    # ---------------------------------------------------------------- security events
    labels = [e["label"] for e in sec["events"]]
    ok("failed sign-ins recorded", sec["summary"]["failed_sign_ins"] >= 6, str(sec["summary"]))
    ok("lockout recorded", sec["summary"]["lockouts"] >= 1, str(sec["summary"]))
    unk = [e for e in sec["events"] if e["action"] == "auth.sign_in_failed" and not e["company_id"]]
    ok("unknown email is masked", unk and unk[0]["user"] == "no***@nowhere.example", str(unk[:1]))
    ok("people added are security events", "Person added" in labels)

    # ---------------------------------------------------------------- health
    ok("health: database, deals, feeds, disk, services, AI", all(k in hl for k in ("database", "deals", "feeds", "disk", "services", "ai")))
    errs = [e["message"] for e in hl["recent_errors"]]
    ok("recent errors are captured", any("Maahi chat failed" in m for m in errs), str(errs[:3]))
    ok("recent errors mask emails and keys", any("so***@acme.example" in m and "[hidden]" in m for m in errs), str(errs[:2]))

    # ---------------------------------------------------------------- controls
    ok("can't pause your own company", c.post(f"/api/platform/companies/{ops['user']['tenant']['id']}/pause", json={}, headers=O).status_code == 400)
    r = c.post(f"/api/platform/companies/{acme_id}/pause", json={"reason": "Unpaid invoice"}, headers=A)
    ok("a company admin can't pause companies", r.status_code == 403)
    ok("pause Acme", c.post(f"/api/platform/companies/{acme_id}/pause", json={"reason": "Unpaid invoice"}, headers=O).status_code == 200)
    r = c.get("/api/deals", headers=A)
    ok("paused company: its people are stopped on every request, with the reason", r.status_code == 403 and "Unpaid invoice" in r.json()["detail"], r.text[:200])
    r = login("pres@acme.example")
    ok("paused company: sign-in refused", r.status_code == 403 and "paused" in r.json()["detail"], r.text[:200])
    ok("other companies unaffected", c.get("/api/deals", headers={"Authorization": "Bearer " + buyer["token"]}).status_code in (200, 403))
    ok("reactivate Acme", c.post(f"/api/platform/companies/{acme_id}/reactivate", headers=O).status_code == 200)
    ok("reactivated: works again", c.get("/api/deals", headers=A).status_code == 200)

    people = {p["email"]: p for p in c.get(f"/api/platform/companies/{acme_id}", headers=O).json()["people_list"]}
    admin_id, pres_id = people["admin@acme.example"]["id"], people["pres@acme.example"]["id"]
    r = c.post(f"/api/platform/users/{admin_id}/pause", headers=O)
    ok("can't pause a company's only admin", r.status_code == 400 and "only active admin" in r.json()["detail"], r.text[:200])
    ok("can't remove a company's only admin role", c.post(f"/api/platform/users/{admin_id}/role", json={"role": "viewer"}, headers=O).status_code == 400)
    pres_tok = login("pres@acme.example").json()["token"]
    PR = {"Authorization": "Bearer " + pres_tok}
    ok("pause a person", c.post(f"/api/platform/users/{pres_id}/pause", headers=O).status_code == 200)
    ok("paused person: stopped at once", c.get("/api/deals", headers=PR).status_code == 401)
    ok("reactivate the person", c.post(f"/api/platform/users/{pres_id}/reactivate", headers=O).status_code == 200)
    ok("change a role (presales to architect)", c.post(f"/api/platform/users/{pres_id}/role", json={"role": "architect"}, headers=O).status_code == 200)
    me = c.get("/api/auth/me", headers=PR).json()
    ok("role change applies at once", (me.get("user") or me).get("role") == "architect", str(me)[:200])
    ok("unknown role refused", c.post(f"/api/platform/users/{pres_id}/role", json={"role": "god"}, headers=O).status_code == 400)
    import time
    time.sleep(1.1)
    ok("sign a person out everywhere", c.post(f"/api/platform/users/{pres_id}/signout", headers=O).status_code == 200)
    ok("signed out: the old pass stops working", c.get("/api/deals", headers=PR).status_code == 401)
    time.sleep(1.1)
    new = login("pres@acme.example")
    ok("signed out: signing in again works", new.status_code == 200 and c.get("/api/deals", headers={"Authorization": "Bearer " + new.json()["token"]}).status_code == 200)
    ok("can't sign yourself out from the console", c.post(f"/api/platform/users/{ops['user']['id']}/signout", headers=O).status_code == 400)

    acts = {e["action"] for e in c.get(f"/api/platform/companies/{acme_id}", headers=O).json()["events"]}
    ok("every platform action is in the company's own trail",
       {"platform.company_suspend", "platform.company_reactivate", "platform.user_suspend", "platform.user_reactivate", "platform.user_role",
        "platform.user_signout"} <= acts, str(acts))
    sec2 = c.get("/api/platform/security", headers=O).json()
    ok("platform actions are counted", sec2["summary"]["platform_actions"] >= 6)
    ok("successful sign-ins listed with their method", any(e["detail"].get("method") == "password" and e["user"] == "pres@acme.example"
                                                          for e in sec2["sign_ins"]), str(sec2["sign_ins"][:2]))

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
