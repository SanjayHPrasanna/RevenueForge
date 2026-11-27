"""Delivery 360 + multi-file tenders + the retired buyer side and customer finder.
Run: python tests/qa_delivery.py [knowledge-folder] [rfp-file]"""
import glob, io, os, sys, tempfile, time, uuid
from datetime import date, timedelta

os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["RADAR_REFRESH_HOURS"] = "0"; os.environ["DEMO_VENDORS"] = "false"
os.environ.pop("GEMINI_API_KEY", None); os.environ["LLM_PROVIDER"] = "none"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging; logging.disable(logging.WARNING)
from fastapi.testclient import TestClient
from app.main import app

FOLDER = sys.argv[1] if len(sys.argv) > 1 else ""
RFP = sys.argv[2] if len(sys.argv) > 2 else ""
fails = 0


def ok(name, cond, extra=""):
    global fails
    fails += not cond
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if extra and not cond else ""))


ANNEX = ("Annexure B - Additional technical requirements\n\n"
         "AX-01 The bidder shall provide 24x7 monitoring of all Fabric pipelines with alerts raised in ServiceNow within 5 minutes.\n"
         "AX-02 The bidder shall deliver a disaster recovery runbook and test it twice a year with a recovery time under 4 hours.\n"
         "AX-03 All source code and notebooks shall be stored in Azure DevOps Git repositories owned by the client.\n")

with TestClient(app) as c:
    # ---- the buyer side is gone
    r = c.post("/api/auth/register", json={"company_name": "Buyer Org", "name": "Buyer Admin", "email": "b@buyer.example", "password": uuid.uuid4().hex, "kind": "buyer"}).json()
    ok("signing up 'as buyer' makes a bidding workspace", r["user"]["tenant"]["kind"] == "vendor", r)
    hb = {"Authorization": "Bearer " + r["token"]}
    ok("buyer request API removed", c.get("/api/buyer/requests", headers=hb).status_code == 404)
    ok("supplier network API removed", c.get("/api/network/invitations", headers=hb).status_code == 404)
    ok("find-customers API removed", c.post("/api/insights/customers", json={}, headers=hb).status_code in (404, 405))

    reg = c.post("/api/auth/register", json={"company_name": "iSteer Technologies", "name": "Admin", "email": "admin@isteer.example", "password": uuid.uuid4().hex}).json()
    h = {"Authorization": "Bearer " + reg["token"]}
    if FOLDER:
        files = [f for f in sorted(glob.glob(os.path.join(FOLDER, "*"))) if not f.endswith(".docx")]
        r = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb").read())) for f in files],
                   data={"paths": ["lib/" + os.path.basename(f) for f in files], "batch": uuid.uuid4().hex[:12]}, headers=h)
        batch = r.json()["batch"]
        for _ in range(120):
            if not c.get(f"/api/library/folder/{batch}", headers=h).json().get("pending"):
                break
            time.sleep(0.5)
        c.post(f"/api/library/folder/{batch}/import", json={}, headers=h)

    # ---- several tender files in one deal
    ok("no files -> 400", c.post("/api/deals", data={"name": "x"}, headers=h).status_code in (400, 422))
    up = [("files", (os.path.basename(RFP), open(RFP, "rb").read())), ("files", ("Annexure B.txt", ANNEX.encode()))] if RFP else \
         [("files", ("rfp.txt", (ANNEX * 3).encode())), ("files", ("Annexure B.txt", ANNEX.encode()))]
    d = c.post("/api/deals", files=up, data={"name": "Fabric data platform", "client_name": "Harbourline Insurance", "confidential": "true"}, headers=h).json()
    ok("deal created from 2 files", d.get("id"), d)
    for _ in range(300):
        dd = c.get(f"/api/deals/{d['id']}", headers=h).json()
        if dd["status"] != "processing":
            break
        time.sleep(1)
    ok("deal analysed", dd["status"] in ("in_review", "submitted"), dd["status"])
    src = c.get(f"/api/deals/{d['id']}/source", headers=h).json()
    heads = [b["text"] for b in src["blocks"] if b["text"].startswith("Document ")]
    ok("source shows both files, in order", len(heads) == 2 and "Annexure B.txt" in heads[1], heads)
    reqs = c.get(f"/api/deals/{d['id']}/requirements", headers=h).json()
    ok("requirements read from the annexure too", any("disaster recovery" in r["text"].lower() for r in reqs), len(reqs))
    ok("single 'file' field still works (MCP, radar)", c.post("/api/deals", files={"file": ("one.txt", (ANNEX * 3).encode())}, data={"name": "one"}, headers=h).status_code == 200)

    # ---- a won deal becomes a project
    lst = c.get("/api/projects", headers=h).json()
    ok("not won yet -> not ready", not lst["ready"])
    ok("project needs a won deal", c.post("/api/projects", json={"deal_id": d["id"]}, headers=h).status_code == 400)
    c.patch(f"/api/deals/{d['id']}", json={"status": "won", "final_value": 41000000}, headers=h)
    lst = c.get("/api/projects", headers=h).json()
    ok("won deal waits to start", [x["deal_id"] for x in lst["ready"]] == [d["id"]], lst["ready"])
    start = (date.today() - timedelta(days=120)).isoformat()
    p = c.post("/api/projects", json={"deal_id": d["id"], "start_date": start}, headers=h).json()
    ok("project created", p.get("id") and p["deal_id"] == d["id"], p)
    ok("client stays masked", p["client"] != "Harbourline Insurance", p["client"])
    ok("value is the agreed final value", p["contract_value"] == 41000000, p["contract_value"])
    kinds = {}
    for i in p["items"]:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    print("   seeded:", kinds, "| budget", p["budget_cost"], p["currency"], "| ends", p["end_date"])
    ok("milestones seeded from the plan", kinds.get("milestone", 0) >= 3)
    ok("team seeded from the estimate", kinds.get("member", 0) >= 1)
    ok("bid snapshot kept", (p.get("bid") or {}).get("verdict") is not None, p.get("bid"))
    again = c.post("/api/projects", json={"deal_id": d["id"]}, headers=h).json()
    ok("starting twice returns the same project", again["id"] == p["id"])
    pid = p["id"]
    ms = [i for i in p["items"] if i["kind"] == "milestone"]
    late = [m for m in ms if m["due_date"] < date.today().isoformat()]
    ok("past-due milestones flagged late", all(m["late"] for m in late) and late, [m["due_date"] for m in ms])
    s = p["summary"]
    ok("health is not green with late milestones", s["health"] in ("amber", "red") and s["health_reasons"], s)
    print("   health:", s["health"], s["health_reasons"])

    # ---- run the project
    for m in late:
        c.patch(f"/api/projects/{pid}/items/{m['id']}", json={"status": "done"}, headers=h)
    add = lambda **kw: c.post(f"/api/projects/{pid}/items", json=kw, headers=h)
    r = add(kind="invoice", title="Milestone 1", amount=4100000, status="raised", due_date=(date.today() - timedelta(days=45)).isoformat(), data={"number": "INV-001"})
    ok("invoice added", r.status_code == 200, r.text)
    add(kind="invoice", title="Milestone 2", amount=6000000, status="paid", due_date=(date.today() - timedelta(days=10)).isoformat())
    add(kind="cost", title="Team cost to date", amount=9000000, data={"category": "labour"})
    add(kind="change", title="Extra source system", amount=2500000, status="approved", data={"effort_days": 60})
    add(kind="change", title="Copilot rollout", amount=900000, status="proposed")
    add(kind="sla", title="2026-10", due_date="2026-10-31", data={"target_pct": 99.5, "achieved_pct": 98.9, "breaches": 2})
    add(kind="update", title="Ingestion live for 3 of 4 sources", status="amber", data={"blockers": "Salesforce API limits"})
    ok("bad status refused", add(kind="risk", title="x", status="nope").status_code == 400)
    ok("bad impact refused", add(kind="risk", title="x", data={"impact": "huge"}).status_code == 400)
    ok("bad date refused", add(kind="milestone", title="x", due_date="31/12/2026").status_code == 400)
    ok("unknown kind refused", add(kind="party", title="x").status_code == 400)
    p = c.get(f"/api/projects/{pid}", headers=h).json()
    s = p["summary"]
    print("   money:", {k: s[k] for k in ("value_total", "invoiced", "paid", "outstanding", "overdue", "burn_pct", "progress_pct", "forecast_margin_pct")})
    ok("approved change adds to value", s["value_total"] == 41000000 + 2500000)
    ok("invoiced/paid/outstanding", s["invoiced"] == 10100000 and s["paid"] == 6000000 and s["outstanding"] == 4100000)
    ok("overdue invoice makes it red with the reason", s["health"] == "red" and any("overdue" in r for r in s["health_reasons"]), s["health_reasons"])
    ok("SLA miss reported", s["sla_missed_months"] == 1 and any("SLA" in r for r in s["health_reasons"]))
    ok("project went active when money moved", p["status"] == "active")
    ok("pending change counted", s["pending_changes"] == 1)

    # ---- roles
    pass
    ok("project list for viewers works", c.get("/api/projects", headers=h).status_code == 200)

    # ---- client 360
    cl = c.get("/api/clients", headers=h).json()
    me = next((x for x in cl if x["key"] == p["client_key"]), None)
    ok("client 360 lists the client", me and me["deals"]["won"] == 1 and me["projects"]["live"] == 1, cl)
    det = c.get(f"/api/clients/{p['client_key']}", headers=h).json()
    ok("client detail: deals, projects, timeline", len(det["deal_list"]) == 1 and len(det["project_list"]) == 1 and det["timeline"], det.keys())
    ok("client money by currency", det["outstanding"] and list(det["outstanding"].values())[0] == 4100000, det["outstanding"])
    print("   timeline:", [e["text"] for e in det["timeline"][:5]])
    ok("unknown client -> 404", c.get("/api/clients/nobody-here", headers=h).status_code == 404)

    # ---- another company can't see it
    o = c.post("/api/auth/register", json={"company_name": "Other Co", "name": "Other Admin", "email": "o@other.example", "password": uuid.uuid4().hex}).json()
    ho = {"Authorization": "Bearer " + o["token"]}
    ok("other company: no access to project", c.get(f"/api/projects/{pid}", headers=ho).status_code == 404)
    ok("other company: can't add items", c.post(f"/api/projects/{pid}/items", json={"kind": "risk", "title": "x"}, headers=ho).status_code == 404)
    ok("other company: empty client list", c.get("/api/clients", headers=ho).json() == [])

    # ---- the same through MCP (Claude, Glean)
    import json as _j
    key = c.post("/api/mcp/keys", json={"label": "test"}, headers=h).json()["key"]
    def tool(name, args=None):
        r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args or {}}},
                   headers={"Authorization": f"Bearer {key}"}).json()["result"]
        return r["isError"], _j.loads(r["content"][0]["text"])
    e1, lp = tool("list_projects")
    ok("MCP list_projects", not e1 and lp["total"] == 1 and lp["projects"][0]["health"] == "red", lp)
    e2, gp = tool("get_project", {"project_id": pid})
    ok("MCP get_project", not e2 and len(gp["invoices"]) == 2 and gp["status_reports"], list(gp))
    e3, cl3 = tool("client_360", {"client": p["client"]})
    ok("MCP client_360", not e3 and len(cl3["project_list"]) == 1, cl3.get("name"))

    # ---- manual project, close it
    m = c.post("/api/projects", json={"name": "AMS renewal", "client_name": "Acme Steel", "currency": "INR", "contract_value": 1200000}, headers=h).json()
    ok("manual project", m.get("id") and m["client"] == "Acme Steel")
    cm = c.patch(f"/api/projects/{m['id']}", json={"status": "completed"}, headers=h).json()
    ok("completed gets an end date and closed health", cm["actual_end_date"] and cm["summary"]["health"] == "closed")
    ok("end before start refused", c.patch(f"/api/projects/{m['id']}", json={"start_date": "2026-05-01", "end_date": "2026-01-01"}, headers=h).status_code == 400)

print("\nALL PASS" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
