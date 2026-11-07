"""QA part 1: every endpoint x every role x three companies (vendor A, vendor B, buyer C) + unauthenticated.

Rules checked:
  * no endpoint ever returns 5xx
  * unauthenticated -> 401 on every protected route
  * a role the route doesn't allow -> 403
  * company B (and buyer C) using company A's ids -> 403/404, never 2xx
"""
import os, sys, tempfile, glob, time, json, io, re
os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"
os.environ["DEMO_VENDORS"] = "true"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from fastapi.testclient import TestClient
from app.main import app
from app.routers import assistant, auth, company_data, deals, insights, learning, library, network, radar, trust

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


ROLES = ["admin", "presales", "architect", "finance", "delivery", "viewer"]

with TestClient(app, raise_server_exceptions=False) as c:
    def register(co, em, kind="vendor"):
        r = c.post("/api/auth/register", json={"company_name": co, "name": "QA Admin", "email": em, "password": PW, "kind": kind})
        assert r.status_code == 200, r.text
        return {"Authorization": "Bearer " + r.json()["token"]}

    def login(em):
        r = c.post("/api/auth/login", json={"email": em, "password": PW})
        assert r.status_code == 200, (em, r.text)
        return {"Authorization": "Bearer " + r.json()["token"]}

    def team(prefix, admin_h):
        hs = {"admin": admin_h}
        for role in ROLES[1:]:
            r = c.post("/api/auth/users", json={"name": f"QA {role}", "email": f"{role}@{prefix}.example", "role": role, "password": PW}, headers=admin_h)
            assert r.status_code == 200, r.text
            hs[role] = login(f"{role}@{prefix}.example")
        return hs

    A = team("a", register("Meridian Integration Labs", "admin@a.example"))
    B = team("b", register("Cobalt Ridge Technologies", "admin@b.example"))
    C = team("c", register("Harbour Region Transit Authority (QA buyer)", "admin@c.example", "buyer"))

    # ---- fixtures for company A
    files = sorted(glob.glob(S + "/meridian-integration-labs/*"))
    bt = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb"))) for f in files], headers=A["presales"]).json()["batch"]
    while c.get(f"/api/library/folder/{bt}", headers=A["presales"]).json()["pending"]:
        time.sleep(0.3)
    ok("A library import", c.post(f"/api/library/folder/{bt}/import", json={}, headers=A["presales"]).status_code == 200)
    files = sorted(glob.glob(S + "/cobalt-ridge-technologies/*"))
    bt2 = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb"))) for f in files], headers=B["admin"]).json()["batch"]
    while c.get(f"/api/library/folder/{bt2}", headers=B["admin"]).json()["pending"]:
        time.sleep(0.3)
    c.post(f"/api/library/folder/{bt2}/import", json={}, headers=B["admin"])
    rfp = S + "/sample-rfps/harborline-integration-platform-rfp.docx"
    d = c.post("/api/deals", files={"file": ("rfp.docx", open(rfp, "rb"))}, data={"name": "Harborline QA", "client_name": "Harborline Port"}, headers=A["presales"]).json()
    did = d["id"]
    t0 = time.time()
    while c.get(f"/api/deals/{did}", headers=A["admin"]).json()["status"] == "processing":
        time.sleep(1)
    deal = c.get(f"/api/deals/{did}", headers=A["admin"]).json()
    print(f"deal ran in {time.time()-t0:.0f}s: {deal['status']}, {deal['requirement_count']} reqs")
    ok("deal finished", deal["status"] == "in_review")
    reqs = c.get(f"/api/deals/{did}/requirements", headers=A["admin"]).json()
    reqs = reqs.get("items", reqs) if isinstance(reqs, dict) else reqs
    rid = reqs[0]["id"]
    com = c.post(f"/api/deals/{did}/requirements/{rid}/comments", json={"text": "QA comment by presales"}, headers=A["presales"])
    ok("comment add", com.status_code == 200, com.text[:200])
    cid = com.json().get("id", "x")
    lib = c.get("/api/library/capabilities", headers=A["admin"]).json()
    lib = lib.get("items", lib) if isinstance(lib, dict) else lib
    cap_id = lib[0]["id"]
    ups = c.get("/api/library/uploads", headers=A["admin"]).json()
    ups = ups.get("items", ups) if isinstance(ups, dict) else ups
    doc_id = ups[0]["id"]
    learn = c.post("/api/learning/answers", json={"question": "QA question?", "answer": "QA answer."}, headers=A["presales"])
    eid = (learn.json() or {}).get("id", "x") if learn.status_code == 200 else "x"
    users_a = c.get("/api/auth/users", headers=A["admin"]).json()
    users_a = users_a.get("items", users_a) if isinstance(users_a, dict) else users_a
    uid = next(u["id"] for u in users_a if u["role"] == "viewer")

    # radar tender (inserted directly)
    from app.db import SessionLocal
    from app.models import Tender
    from datetime import datetime, timedelta, timezone
    with SessionLocal() as db:
        t = Tender(source="ted", source_id="QA-1", published=datetime.now(timezone.utc), title="Integration platform for a port authority", description="API gateway, event streaming and integration services.",
                   buyer="QA Port", country="Netherlands", region="Europe & Central Asia", language="en", url="https://example.invalid/qa",
                   deadline=datetime.now(timezone.utc) + timedelta(days=20), categories=[], fetched_at=datetime.now(timezone.utc))
        db.add(t); db.commit(); tender_id = t.id
    # buyer request
    rq = c.post("/api/buyer/requests", files={"file": ("rfp.docx", open(rfp, "rb"))}, data={"region": "Europe & Central Asia"}, headers=C["admin"])
    ok("buyer request", rq.status_code == 200, rq.text[:200])
    breq = rq.json()["id"]
    c.put("/api/network/profile", json={"listed": True}, headers=A["admin"])
    sl = c.get(f"/api/buyer/requests/{breq}/shortlist", headers=C["admin"]).json()
    vid = next(v["vendor_id"] for v in sl["vendors"] if v["name"] == "Meridian Integration Labs")
    inv = c.post(f"/api/buyer/requests/{breq}/invite", json={"vendor_ids": [vid]}, headers=C["admin"])
    inbox = c.get("/api/network/invitations", headers=A["admin"]).json()
    inv_id = inbox[0]["id"] if inbox else "x"

    IDS = {"deal_id": did, "req_id": rid, "comment_id": cid, "stage": "matching", "what": "matrix", "kind": "capabilities", "item_id": cap_id,
           "doc_id": doc_id, "batch": bt, "eid": eid, "uid": uid, "tender_id": tender_id, "rid": breq, "vid": vid, "inv_id": inv_id}

    # ---- the matrix
    def roles_of(route):
        """None = any signed-in role. A tuple = roles allowed (admin always passes)."""
        def walk(dep):
            for x in dep.dependencies:
                n = getattr(x.call, "__name__", "")
                if n == "dep":
                    cl = x.call.__closure__
                    yield ("roles", cl[0].cell_contents if cl else ())
                elif n in ("buyer_ctx", "vendor_ctx"):
                    yield (n, None)
                elif n == "buyer_editor":
                    yield ("roles", ("presales", "architect", "finance", "delivery"))
                yield from walk(x)
        return list(walk(route.dependant))

    # Routes skipped for *allowed* callers only (they'd destroy fixtures or start long jobs); denials are still checked.
    DESTRUCTIVE = {("DELETE", "/api/deals/{deal_id}"), ("POST", "/api/deals/{deal_id}/rerun"), ("PUT", "/api/deals/{deal_id}/stages/{stage}/overrides"),
                   ("DELETE", "/api/library/{kind}/{item_id}"), ("DELETE", "/api/buyer/requests/{rid}"), ("POST", "/api/network/invitations/{inv_id}/accept"),
                   ("POST", "/api/network/invitations/{inv_id}/decline"), ("PATCH", "/api/auth/users/{uid}"), ("POST", "/api/radar/refresh"),
                   ("DELETE", "/api/deals/{deal_id}/requirements/{req_id}"), ("POST", "/api/deals/{deal_id}/story"), ("POST", "/api/deals/{deal_id}/proposal/rebuild"),
                   ("POST", "/api/library/uploads/{doc_id}/import"), ("POST", "/api/library/uploads/{doc_id}/remap"), ("DELETE", "/api/learning/answers/{eid}"),
                   ("DELETE", "/api/deals/{deal_id}/comments/{comment_id}"), ("POST", "/api/learning/retrain"), ("DELETE", "/api/auth/ai-config"),
                   ("PUT", "/api/auth/ai-config"), ("POST", "/api/auth/ai-config/test"), ("PUT", "/api/company/ai"), ("POST", "/api/company/ai/test"),
                   ("POST", "/api/library/folder/{batch}/import"), ("POST", "/api/deals/{deal_id}/clarifications"), ("POST", "/api/company/delete"), ("DELETE", "/api/library/drive")}
    PUBLIC = {"/api/trust", "/api/auth/register", "/api/auth/login", "/api/auth/config", "/api/auth/microsoft", "/api/auth/google", "/api/assistant/chat"}

    def call(method, path, h):
        url = path
        for k, v in IDS.items():
            url = url.replace("{" + k + "}", str(v))
        kw = {}
        if method in ("POST", "PUT", "PATCH"):
            kw["json"] = {}
        return c.request(method, url, headers=h or {}, **kw)

    n_routes = 0
    for m in (assistant, auth, company_data, deals, insights, learning, library, network, radar, trust):
        for r in m.router.routes:
            for method in r.methods:
                n_routes += 1
                key = (method, r.path)
                if r.path in PUBLIC:
                    continue
                deps = roles_of(r)
                allowed = None
                kind_need = None
                for typ, val in deps:
                    if typ == "roles":
                        allowed = val if allowed is None else tuple(set(allowed) & set(val)) or val
                    else:
                        kind_need = "buyer" if typ == "buyer_ctx" else "vendor"
                if r.path.endswith("/approve"):
                    allowed = deals.STAGE_ROLES["matching"]
                # unauthenticated
                res = call(method, r.path, None)
                ok(f"anon {method} {r.path} -> 401", res.status_code == 401, str(res.status_code))
                # each role of the owner company
                owner = C if kind_need == "buyer" else A
                for role in ROLES:
                    may = allowed is None or role == "admin" or role in allowed
                    if may and key in DESTRUCTIVE:
                        continue
                    res = call(method, r.path, owner[role])
                    ok(f"{role} {method} {r.path} no 5xx", res.status_code < 500, f"{res.status_code} {res.text[:160]}")
                    if not may:
                        ok(f"{role} {method} {r.path} denied", res.status_code == 403, f"{res.status_code} {res.text[:120]}")
                    else:
                        ok(f"{role} {method} {r.path} not denied", res.status_code not in (401, 403), f"{res.status_code} {res.text[:120]}")
                # wrong company kind, and cross-tenant with ids from A/C
                has_ids = "{" in r.path and not r.path.endswith("{kind}") and r.path not in ("/api/deals/{deal_id}/stages/{stage}",)
                others = [B, A] if kind_need == "buyer" else ([C] if kind_need == "vendor" else [B, C])
                for other in others:
                    if key in DESTRUCTIVE and not has_ids:
                        continue
                    res = call(method, r.path, other["admin"])
                    ok(f"other-co {method} {r.path} no 5xx", res.status_code < 500, f"{res.status_code} {res.text[:160]}")
                    if has_ids or kind_need:
                        if r.path in ("/api/radar/{tender_id}",) and other is B and method == "GET":
                            ok("radar tender is public data", res.status_code in (200, 403)); continue
                        if r.path.startswith("/api/library/{kind}") or r.path == "/api/library/template":
                            continue
                        ok(f"other-co {method} {r.path} blocked", res.status_code in (403, 404, 400, 422) or (method == "GET" and r.path.startswith("/api/radar")),
                           f"{res.status_code} {res.text[:160]}")
    print(f"{n_routes} routes walked")

    # ---- item-level cross tenant: B tries to read/modify A's specific objects
    Bh = B["admin"]
    for path in [f"/api/deals/{did}", f"/api/deals/{did}/requirements", f"/api/deals/{did}/stages/proposal", f"/api/deals/{did}/download/proposal",
                 f"/api/deals/{did}/download/matrix", f"/api/deals/{did}/source", f"/api/library/uploads/{doc_id}", f"/api/deals/{did}/similar",
                 f"/api/deals/{did}/requirements/{rid}/comments", f"/api/library/folder/{bt}"]:
        r = c.get(path, headers=Bh)
        ok(f"B cannot read A {path}", r.status_code in (403, 404), str(r.status_code))
    r = c.put(f"/api/library/capabilities/{cap_id}", json={"name": "hijacked"}, headers=Bh)
    ok("B cannot edit A capability", r.status_code in (403, 404), str(r.status_code))
    r = c.delete(f"/api/library/capabilities/{cap_id}", headers=Bh)
    ok("B cannot delete A capability", r.status_code in (403, 404), str(r.status_code))
    r = c.patch(f"/api/auth/users/{uid}", json={"role": "admin"}, headers=Bh)
    ok("B cannot promote A user", r.status_code in (403, 404), str(r.status_code))
    r = c.delete(f"/api/deals/{did}", headers=Bh)
    ok("B cannot delete A deal", r.status_code in (403, 404), str(r.status_code))
    r = c.post(f"/api/network/invitations/{inv_id}/accept", headers=B["presales"])
    ok("B cannot accept A's invitation", r.status_code in (403, 404), str(r.status_code))
    r = c.get(f"/api/buyer/requests/{breq}", headers=register("Other Buyer Co", "admin@d.example", "buyer"))
    ok("buyer D cannot see buyer C's request", r.status_code in (403, 404), str(r.status_code))
    # lists don't leak
    lst = json.dumps(c.get("/api/deals", headers=Bh).json())
    ok("B deal list has no A deal", did not in lst)
    lst = json.dumps(c.get("/api/library/capabilities", headers=Bh).json())
    ok("B library has no A item", cap_id not in lst)
    ok("B users list has no A user", uid not in json.dumps(c.get("/api/auth/users", headers=Bh).json()))
    ok("B dashboard has no A deal", "Harborline QA" not in json.dumps(c.get("/api/dashboard", headers=Bh).json()))
    ok("B graph has no A deal", "Harborline QA" not in json.dumps(c.get("/api/graph", headers=Bh).json()))
    ok("B learning has no A answers", "QA answer." not in json.dumps(c.get("/api/learning", headers=Bh).json()))
    ok("B invitations empty", c.get("/api/network/invitations", headers=Bh).json() == [])
    # a comment by presales can't be deleted by architect
    r = c.delete(f"/api/deals/{did}/comments/{cid}", headers=A["architect"])
    ok("architect can't delete presales' comment", r.status_code == 403, str(r.status_code))
    # last admin guard
    me = c.get("/api/auth/me", headers=A["admin"]).json()
    r = c.patch(f"/api/auth/users/{me['id']}", json={"role": "viewer"}, headers=A["admin"])
    ok("last admin can't demote self", r.status_code in (400, 409), str(r.status_code))
    # role change takes effect immediately (no stale token role)
    c.patch(f"/api/auth/users/{uid}", json={"role": "presales"}, headers=A["admin"])
    r = c.patch(f"/api/deals/{did}", json={"name": "Harborline QA"}, headers=A["viewer"])
    ok("promoted viewer gets presales rights at once", r.status_code == 200, str(r.status_code))
    c.patch(f"/api/auth/users/{uid}", json={"role": "viewer"}, headers=A["admin"])
    r = c.patch(f"/api/deals/{did}", json={"name": "Harborline QA"}, headers=A["viewer"])
    ok("demoted viewer loses rights at once", r.status_code == 403, str(r.status_code))
    c.patch(f"/api/auth/users/{uid}", json={"active": False}, headers=A["admin"])
    ok("deactivated user's token stops working", c.get("/api/auth/me", headers=A["viewer"]).status_code == 401)
    ok("deactivated user can't log in", c.post("/api/auth/login", json={"email": "viewer@a.example", "password": PW}).status_code in (401, 403))
    c.patch(f"/api/auth/users/{uid}", json={"active": True}, headers=A["admin"])


print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
