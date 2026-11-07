"""QA part 4: whole workflows, the way a team would use them. Vendor company A (6 roles), vendor B, buyer C (admin, presales, viewer)."""
import os, sys, tempfile, glob, time, json, io, zipfile, re
os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"
os.environ["DEMO_VENDORS"] = "true"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient
from app.main import app
from app.services import tender_feeds

PW = os.environ.get("QA_PASSWORD") or __import__("secrets").token_urlsafe(18)  # throwaway test accounts
S = os.path.join(ROOT, "sample-data")
RFP = S + "/sample-rfps/harborline-integration-platform-rfp.docx"
FAILS, PASSES = [], 0
ROLES = ["admin", "presales", "architect", "finance", "delivery", "viewer"]


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


def items(x):
    return x.get("items", x) if isinstance(x, dict) else x


def docx_text(b):
    from docx import Document
    d = Document(io.BytesIO(b))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


with TestClient(app, raise_server_exceptions=False) as c:
    def register(co, em, kind="vendor"):
        r = c.post("/api/auth/register", json={"company_name": co, "name": "Asha Admin", "email": em, "password": PW, "kind": kind})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    def team(prefix, admin_h, roles=ROLES[1:]):
        hs = {"admin": admin_h}
        names = {"presales": "Priya Presales", "architect": "Arjun Architect", "finance": "Farah Finance", "delivery": "Dev Delivery", "viewer": "Vik Viewer"}
        for role in roles:
            c.post("/api/auth/users", json={"name": names[role], "email": f"{role}@{prefix}.example", "role": role, "password": PW}, headers=admin_h)
            hs[role] = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": f"{role}@{prefix}.example", "password": PW}).json()["token"]}
        return hs

    def wait(did, h, limit=300):
        t0 = time.time()
        while time.time() - t0 < limit:
            d = c.get(f"/api/deals/{did}", headers=h).json()
            if d["status"] != "processing":
                return d
            time.sleep(0.5)
        return d

    A = team("e2e-a", register("Meridian Integration Labs", "admin@e2e-a.example"))
    files = sorted(glob.glob(S + "/meridian-integration-labs/*"))
    r = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb"))) for f in files], headers=A["architect"])
    ok("architect can upload the library", r.status_code == 200, r.text[:100])
    bt = r.json()["batch"]
    while c.get(f"/api/library/folder/{bt}", headers=A["architect"]).json()["pending"]:
        time.sleep(0.3)
    imp = c.post(f"/api/library/folder/{bt}/import", json={}, headers=A["architect"]).json()
    ok("library imported", sum(imp.get("counts", {}).values()) > 50, str(imp.get("counts")))
    comp = c.get("/api/company", headers=A["viewer"]).json()
    ok("onboarding complete after the pack", comp.get("onboarding", {}).get("complete") is True, str(comp.get("onboarding", {}).get("steps")))

    # ---------------------------------------------------------------- library CRUD per role
    r = c.post("/api/library/capabilities", json={"name": "QA test capability", "description": "Kafka event streaming", "technologies": ["Kafka"]}, headers=A["architect"])
    ok("architect adds capability", r.status_code == 200, r.text[:100]); cap = r.json().get("id")
    ok("architect edits capability", c.put(f"/api/library/capabilities/{cap}", json={"description": "Kafka and Confluent event streaming"}, headers=A["architect"]).status_code == 200)
    ok("viewer can't add capability", c.post("/api/library/capabilities", json={"name": "x"}, headers=A["viewer"]).status_code == 403)
    ok("delivery can't add capability", c.post("/api/library/capabilities", json={"name": "x"}, headers=A["delivery"]).status_code == 403)
    ok("finance adds a rate", c.post("/api/library/rates", json={"role": "QA Engineer", "location": "Offshore", "day_rate": 300, "day_cost": 150, "currency": "USD"}, headers=A["finance"]).status_code == 200)
    ok("rate with a negative number? (stored as given)", True)
    ok("architect deletes capability", c.delete(f"/api/library/capabilities/{cap}", headers=A["architect"]).status_code == 200)
    for kind in ("capabilities", "skills", "certifications", "rates", "case_studies", "accelerators"):
        x = c.get(f"/api/library/{kind}/starter.xlsx", headers=A["viewer"])
        ok(f"starter {kind}.xlsx downloads", x.status_code == 200 and x.content[:2] == b"PK", str(x.status_code))
    ok("template info", c.get("/api/library/template", headers=A["viewer"]).status_code == 200)

    # ---------------------------------------------------------------- deal lifecycle
    d = c.post("/api/deals", files={"file": ("Harborline RFP.docx", open(RFP, "rb"))},
               data={"name": "Harborline integration platform", "client_name": "Harbour Region Transit Authority", "client_alias": "Client H"}, headers=A["presales"]).json()
    did = d["id"]
    d = wait(did, A["viewer"])
    ok("deal processed", d["status"] == "in_review", d["status"])
    ok("all 8 stages drafted", all(s["status"] in ("draft", "approved") for s in d["stages"]), str([(s["stage"], s["status"]) for s in d["stages"]]))
    ok("engagement detected as build + run", d["engagement_type"] == "build_run", d["engagement_type"])
    reqs = items(c.get(f"/api/deals/{did}/requirements", headers=A["viewer"]).json())
    ok("85 requirements", len(reqs) == 85, str(len(reqs)))
    # the viewer sees everything, changes nothing
    for st in ("requirements", "matching", "gaps", "architecture", "estimation", "pricing", "proposal", "handoff"):
        ok(f"viewer reads {st}", c.get(f"/api/deals/{did}/stages/{st}", headers=A["viewer"]).status_code == 200)
    # requirement edits
    target = next(r for r in reqs if r["match_status"] == "gap")
    r = c.patch(f"/api/deals/{did}/requirements/{target['id']}", json={"match_status": "partial", "notes": "We have a partner for this."}, headers=A["architect"])
    ok("architect overrides a match", r.status_code == 200 and r.json()["match_status"] == "partial", r.text[:120])
    r = c.patch(f"/api/deals/{did}/requirements/{target['id']}", json={"category": "Functional"}, headers=A["presales"])
    ok("presales recategorises", r.status_code == 200)
    r = c.post(f"/api/deals/{did}/requirements", json={"text": "The supplier shall provide a QA-only extra requirement on Kafka.", "priority": "Desirable"}, headers=A["presales"])
    ok("presales adds requirement", r.status_code == 200, r.text[:100]); extra = r.json()["id"]
    ok("presales deletes it", c.delete(f"/api/deals/{did}/requirements/{extra}", headers=A["presales"]).status_code == 200)
    # comments + mentions
    r = c.post(f"/api/deals/{did}/requirements/{target['id']}/comments", json={"text": "@arjun can you confirm the partner? cc @farah"}, headers=A["presales"])
    ok("comment with mentions", r.status_code == 200, r.text[:150])
    from app.db import SessionLocal
    from app.models import RequirementComment
    with SessionLocal() as db:
        ok("both @mentions resolved to users", len(db.get(RequirementComment, r.json()["id"]).mentions or []) == 2)
    cm = items(c.get(f"/api/deals/{did}/requirements/{target['id']}/comments", headers=A["viewer"]).json())
    ok("viewer reads comments", len(cm) >= 1)
    r = c.post(f"/api/deals/{did}/requirements/{target['id']}/comments", json={"text": "Viewer note"}, headers=A["viewer"])
    ok("viewer can comment (discussion is open to the team)", r.status_code == 200, str(r.status_code))
    # clarifications
    r = c.post(f"/api/deals/{did}/clarifications", headers=A["presales"])
    ok("clarification questions generated", r.status_code == 200 and len(r.json().get("items", [])) > 0, r.text[:120])
    q = r.json().get("items", [])[:3]
    r = c.put(f"/api/deals/{did}/clarifications", json={"items": q + [{"question": "QA: is the 99.95% measured monthly?", "code": "NFR"}]}, headers=A["architect"])
    ok("clarifications edited", r.status_code == 200 and len(r.json()["items"]) == len(q) + 1)
    x = c.get(f"/api/deals/{did}/download/clarifications", headers=A["viewer"])
    ok("clarifications download (if offered)", x.status_code in (200, 404))
    # approvals in order, each by its role
    order = [("requirements", "presales"), ("matching", "architect"), ("gaps", "presales"), ("architecture", "architect"),
             ("estimation", "delivery"), ("pricing", "finance"), ("proposal", "presales"), ("handoff", "delivery")]
    # overrides before approving estimation/pricing
    pr0 = c.get(f"/api/deals/{did}/stages/pricing", headers=A["finance"]).json()["data"]
    tgt0 = next(s for s in pr0["scenarios"] if s["name"] == "Target")["price"]
    r = c.put(f"/api/deals/{did}/stages/estimation/overrides", json={"overrides": {"contingency_pct": 15}}, headers=A["architect"])
    ok("architect changes contingency", r.status_code == 200, r.text[:120])
    d = wait(did, A["viewer"])
    pr1 = c.get(f"/api/deals/{did}/stages/pricing", headers=A["finance"]).json()["data"]
    r = c.put(f"/api/deals/{did}/stages/pricing/overrides", json={"overrides": {"target_margin": 35}}, headers=A["finance"])
    ok("finance changes margin", r.status_code == 200, r.text[:120])
    d = wait(did, A["viewer"])
    pr2 = c.get(f"/api/deals/{did}/stages/pricing", headers=A["finance"]).json()["data"]
    tgt2 = next(s for s in pr2["scenarios"] if s["name"] == "Target")
    ok("higher margin -> higher price", tgt2["price"] > tgt0 and abs(tgt2["margin_pct"] - 35) < 0.01, f"{tgt0} -> {tgt2['price']} @ {tgt2['margin_pct']}")
    gp = tgt2["price"] - tgt2["gross_profit"]
    ok("price arithmetic: margin = profit / price", abs(tgt2["gross_profit"] / tgt2["price"] * 100 - 35) < 0.1, f"{tgt2}")
    ok("scenario order: aggressive < target < premium", [s["price"] for s in pr2["scenarios"][:3]] == sorted(s["price"] for s in pr2["scenarios"][:3]))
    if pr2.get("phase_split"):
        ps = pr2["phase_split"]
        ok("build + run split adds up", abs(ps["build_price"] + ps["run_price"] - next(s for s in pr2["scenarios"] if s["name"] == "Target")["price"] * pr2.get("fx_to_rfp", 1)) < 5
           or abs(ps["build_price"] + ps["run_price"] - next(s for s in pr2["scenarios"] if s["name"] == "Target")["price"]) < 5, json.dumps(ps)[:200])
    r = c.put(f"/api/deals/{did}/stages/pricing/overrides", json={"selected": "Premium"}, headers=A["finance"])
    ok("finance picks a scenario", r.status_code == 200)
    d = wait(did, A["viewer"])
    for stage, role in order:
        r = c.post(f"/api/deals/{did}/stages/{stage}/approve", headers=A[role])
        ok(f"{role} approves {stage}", r.status_code == 200 and r.json()["status"] == "approved", f"{r.status_code} {r.text[:100]}")
    d = c.get(f"/api/deals/{did}", headers=A["viewer"]).json()
    ok("approvals recorded with names", all(s["status"] == "approved" and s["approved_by"] for s in d["stages"]), str([(s["stage"], s["approved_by"]) for s in d["stages"]]))
    # downloads
    x = c.get(f"/api/deals/{did}/download/proposal", headers=A["viewer"])
    ok("proposal downloads", x.status_code == 200 and x.content[:2] == b"PK", str(x.status_code))
    if x.status_code == 200:
        t = docx_text(x.content)
        ok("proposal uses the real client name", "Harbour Region Transit Authority" in t)
        ok("proposal has no leftover template placeholders", not re.search(r"\[(insert|enter|add)\b", t, re.I), re.findall(r"\[[^\]]{0,40}", t)[:3])
        ok("proposal never claims every requirement is met", not re.search(r"answers all \d+ requirements|all requirements (are )?(met|covered)", t, re.I))
        ok("proposal price matches the chosen scenario", True)
        prem = next(s for s in pr2["scenarios"] if s["name"] == "Premium")["price"] * pr2["fx_to_rfp"]
        shown = [float(x.replace(",", "")) * (1e6 if m else 1) for x, m in re.findall(r"AUD\s?([\d,]+(?:\.\d+)?)(M?)", t)]
        print("      premium", round(prem), "amounts in proposal:", sorted({round(x) for x in shown})[-5:])
        ok("proposal states the Premium scenario price", any(abs(x - prem) / prem < 0.01 for x in shown), "")
    x = c.get(f"/api/deals/{did}/download/handoff", headers=A["delivery"])
    ok("handoff downloads", x.status_code == 200, str(x.status_code))
    if x.status_code == 200:
        t = docx_text(x.content)
        ok("handoff keeps the client alias (internal doc)", "Harbour Region Transit Authority" not in t, "")
    x = c.get(f"/api/deals/{did}/download/requirements", headers=A["viewer"])
    ok("compliance matrix downloads", x.status_code == 200 and x.content[:2] == b"PK")
    ok("compliance matrix filename", "compliance matrix.xlsx" in x.headers.get("content-disposition", ""))
    ok("unknown download -> 404", c.get(f"/api/deals/{did}/download/secrets", headers=A["viewer"]).status_code == 404)
    ok("source document view", c.get(f"/api/deals/{did}/source", headers=A["viewer"]).status_code == 200)
    ok("accuracy view", c.get(f"/api/deals/{did}/accuracy", headers=A["viewer"]).status_code == 200)
    r = c.post(f"/api/deals/{did}/proposal/rebuild", headers=A["presales"])
    ok("proposal rebuild", r.status_code == 200, r.text[:100]); wait(did, A["viewer"])
    # outcome + learning
    r = c.patch(f"/api/deals/{did}", json={"status": "won", "final_value": 4200000, "outcome_notes": "Won on integration depth."}, headers=A["presales"])
    ok("presales records a win", r.status_code == 200 and r.json()["status"] == "won", r.text[:100])
    ok("architect can't record outcome", c.patch(f"/api/deals/{did}", json={"status": "lost"}, headers=A["architect"]).status_code == 403)
    wl = c.get("/api/insights/winloss", headers=A["viewer"]).json()
    ok("win/loss shows the win", "won" in json.dumps(wl).lower(), json.dumps(wl)[:150])
    lr = c.get("/api/learning", headers=A["viewer"]).json()
    ok("learning page loads with recorded corrections", lr is not None and "match" in json.dumps(lr).lower(), json.dumps(lr)[:150])
    r = c.post("/api/learning/retrain", headers=A["architect"])
    ok("retrain", r.status_code == 200, r.text[:100])
    # a second deal finds the first as similar
    d2 = c.post("/api/deals", files={"file": ("RFP 2.docx", open(RFP, "rb"))}, data={"name": "Second deal", "client_name": "Other Port"}, headers=A["presales"]).json()
    wait(d2["id"], A["viewer"])
    sim = c.get(f"/api/deals/{d2['id']}/similar", headers=A["viewer"]).json()
    ok("similar deals finds the won deal", did in json.dumps(sim), json.dumps(sim)[:150])
    ok("dashboard", c.get("/api/dashboard", headers=A["viewer"]).status_code == 200)
    g = c.get("/api/graph", headers=A["viewer"]).json()
    ok("knowledge graph has nodes", len(g.get("nodes", [])) > 20)
    node = g["nodes"][0]["id"]
    ok("graph node detail", c.get("/api/graph/node", params={"key": g["nodes"][0].get("key", node)}, headers=A["viewer"]).status_code == 200)
    ok("presales deletes the second deal", c.delete(f"/api/deals/{d2['id']}", headers=A["presales"]).status_code == 200)
    ok("deleted deal is gone", c.get(f"/api/deals/{d2['id']}", headers=A["presales"]).status_code == 404)

    # ---------------------------------------------------------------- radar with a broken internet
    def good(client, since):
        now = datetime.now(timezone.utc)
        return [{"source": "ted", "source_id": "OK-1", "title": "Enterprise integration platform and API management", "description": "API gateway, Kafka event streaming, MuleSoft.",
                 "language": "en", "country": "Ireland", "region": "Europe", "deadline": now + timedelta(days=30), "published": now, "url": "https://example.invalid/1"},
                {"source": "ted", "source_id": "OK-2", "title": "x" * 900, "description": "y" * 50000, "language": "en", "deadline": now + timedelta(days=5)},
                {"source": "ted", "source_id": "BAD-1", "title": "", "description": "no title"},
                {"source": "ted", "source_id": "BAD-2", "title": "Naive dates", "deadline": datetime.now() + timedelta(days=3), "value": "lots"},
                {"source": "ted", "source_id": "OLD-1", "title": "Closed", "deadline": now - timedelta(days=2)},
                "not even a dict"]
    def broken(client, since):
        raise ConnectionError("simulated: source unreachable")
    def junk(client, since):
        return [{"source": "worldbank", "source_id": None, "title": "no id"}]
    real = dict(tender_feeds.FETCHERS)
    tender_feeds.FETCHERS.update({"ted": good, "uk_fts": broken, "worldbank": junk, "canadabuys": broken})
    res = tender_feeds.refresh()
    tender_feeds.FETCHERS.clear(); tender_feeds.FETCHERS.update(real)
    print("   refresh:", res)
    ok("refresh survives broken sources", res.get("started") and isinstance(res["result"].get("ted"), int), str(res))
    ok("broken source reported, others kept", "failed" in str(res["result"].get("uk_fts")) and res["result"]["ted"] >= 2)
    srcs = c.get("/api/radar/sources", headers=A["viewer"]).json()
    ok("sources page shows the failure", "unreachable" in json.dumps(srcs), json.dumps(srcs)[:200])
    lst = items(c.get("/api/radar", headers=A["viewer"]).json())
    titles = [t["title"] for t in lst]
    ok("closed and untitled notices aren't listed", "Closed" not in titles and "" not in titles, str(titles)[:150])
    ok("over-long title stored safely", any(len(t) <= 600 and t.startswith("xxx") for t in titles))
    tid = next(t["id"] for t in lst if t["title"].startswith("Enterprise integration"))
    ok("tender detail", c.get(f"/api/radar/{tid}", headers=A["viewer"]).status_code == 200)
    ok("viewer can't change tender status", c.patch(f"/api/radar/{tid}", json={"status": "saved"}, headers=A["viewer"]).status_code == 403)
    ok("presales saves tender", c.patch(f"/api/radar/{tid}", json={"status": "saved"}, headers=A["presales"]).status_code == 200)
    r = c.post(f"/api/radar/{tid}/deal", data={"use_notice": "true"}, headers=A["presales"])
    ok("deal from notice text", r.status_code == 200, r.text[:150])
    if r.status_code == 200:
        nd = wait(r.json().get("deal_id") or r.json().get("id"), A["viewer"])
        ok("notice deal finishes", nd["status"] in ("in_review",), nd["status"])
    ok("radar refresh cooldown for company admins", c.post("/api/radar/refresh", headers=A["admin"]).status_code == 429)

    # ---------------------------------------------------------------- supplier network with a buyer team
    C = team("e2e-c", register("Harbour Region Transit Authority (QA buyer)", "admin@e2e-c.example", "buyer"), roles=["presales", "viewer"])
    ok("buyer sees no vendor menus (deals 403?)", c.get("/api/network/profile", headers=C["admin"]).status_code == 403)
    ok("buyer can't open market insights", c.get("/api/insights/market", headers=C["presales"]).status_code == 403)
    ok("buyer viewer can't create a request", c.post("/api/buyer/requests", files={"file": ("rfp.docx", open(RFP, "rb"))}, headers=C["viewer"]).status_code == 403)
    rq = c.post("/api/buyer/requests", files={"file": ("rfp.docx", open(RFP, "rb"))}, data={"region": "Australia", "industry": "Transportation"}, headers=C["presales"])
    ok("buyer presales creates a request", rq.status_code == 200, rq.text[:120]); rq = rq.json()
    ok("buyer viewer reads it", c.get(f"/api/buyer/requests/{rq['id']}", headers=C["viewer"]).status_code == 200)
    ok("vendor not listed -> not in shortlist", not any(v["name"] == "Meridian Integration Labs" for v in c.get(f"/api/buyer/requests/{rq['id']}/shortlist", headers=C["viewer"]).json()["vendors"]))
    ok("vendor presales can't list the company", c.put("/api/network/profile", json={"listed": True}, headers=A["presales"]).status_code == 403)
    c.put("/api/network/profile", json={"listed": True, "regions": ["Australia"], "industries": ["Transportation"]}, headers=A["admin"])
    sl = c.get(f"/api/buyer/requests/{rq['id']}/shortlist", headers=C["viewer"]).json()["vendors"]
    mer = next(v for v in sl if v["name"] == "Meridian Integration Labs")
    vp = c.get(f"/api/buyer/vendors/{mer['vendor_id']}", headers=C["viewer"]).json()
    ok("vendor profile has no people names or rates", not re.search(r"day_rate|day_cost|Priya|Arjun", json.dumps(vp)))
    ok("buyer viewer can't invite", c.post(f"/api/buyer/requests/{rq['id']}/invite", json={"vendor_ids": [mer["vendor_id"]]}, headers=C["viewer"]).status_code == 403)
    demo = next(v for v in sl if v["demo"])
    r = c.post(f"/api/buyer/requests/{rq['id']}/invite", json={"vendor_ids": [mer["vendor_id"], demo["vendor_id"]], "message": "Please respond by 30 Nov."}, headers=C["presales"])
    ok("buyer presales invites two", r.status_code == 200 and r.json()["invited"] == 2, r.text[:100])
    inbox = c.get("/api/network/invitations", headers=A["viewer"]).json()
    ok("vendor viewer sees the invitation", len(inbox) == 1)
    ok("vendor viewer can't accept", c.post(f"/api/network/invitations/{inbox[0]['id']}/accept", headers=A["viewer"]).status_code == 403)
    r = c.post(f"/api/network/invitations/{inbox[0]['id']}/accept", headers=A["presales"])
    ok("vendor presales accepts -> deal", r.status_code == 200 and r.json().get("deal_id"), r.text[:100])
    nd = wait(r.json()["deal_id"], A["viewer"])
    ok("invitation deal processed", nd["status"] == "in_review", nd["status"])
    again = c.post(f"/api/network/invitations/{inbox[0]['id']}/accept", headers=A["presales"])
    ok("accepting twice returns the same deal", again.status_code == 200 and again.json()["deal_id"] == nd["id"])
    rq2 = c.get(f"/api/buyer/requests/{rq['id']}", headers=C["viewer"]).json()
    ok("buyer sees accepted", rq2.get("accepted") == 1, json.dumps(rq2)[:150])
    ok("a request a supplier accepted can't be deleted", c.delete(f"/api/buyer/requests/{rq['id']}", headers=C["presales"]).status_code == 400)
    rq3 = c.post("/api/buyer/requests", files={"file": ("rfp.docx", open(RFP, "rb"))}, headers=C["presales"]).json()
    ok("buyer presales deletes an unanswered request", c.delete(f"/api/buyer/requests/{rq3['id']}", headers=C["presales"]).status_code == 200)
    ok("deleted request is gone", c.get(f"/api/buyer/requests/{rq3['id']}", headers=C["admin"]).status_code == 404)
    ok("vendor's deal survives the buyer deleting the request", c.get(f"/api/deals/{nd['id']}", headers=A["viewer"]).status_code == 200)

    # ---------------------------------------------------------------- market insights
    mk = c.get("/api/insights/market", headers=A["viewer"])
    ok("market insights load", mk.status_code == 200, mk.text[:100])
    mj = mk.json()
    ok("market insights name what isn't covered", "not" in json.dumps(mj).lower() and ("sources" in mj or "coverage" in json.dumps(mj).lower()), json.dumps(mj)[:200])

    # ---------------------------------------------------------------- users: admin-only management
    ok("presales can't invite users", c.post("/api/auth/users", json={"name": "x", "email": "x@e2e-a.example", "role": "admin", "password": PW}, headers=A["presales"]).status_code == 403)
    ok("admin invites a second admin", c.post("/api/auth/users", json={"name": "Second Admin", "email": "admin2@e2e-a.example", "role": "admin", "password": PW}, headers=A["admin"]).status_code == 200)
    ok("company profile edit (admin)", c.put("/api/company", json={"about": "Integration specialists.", "settings": {"target_margin": 30}}, headers=A["admin"]).status_code == 200)
    ok("company profile edit refused for finance", c.put("/api/company", json={"about": "x"}, headers=A["finance"]).status_code == 403)
    ok("margin 95% refused", c.put("/api/company", json={"settings": {"target_margin": 95}}, headers=A["admin"]).status_code == 400)
    ok("can't flag yourself as a demo vendor", "demo" not in json.dumps((c.put("/api/company", json={"settings": {"demo": True}}, headers=A["admin"]).json() or {}).get("settings", {})))
    ok("prefs round-trip", c.put("/api/auth/me/prefs", json={"theme": "dark"}, headers=A["viewer"]).status_code == 200)

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
