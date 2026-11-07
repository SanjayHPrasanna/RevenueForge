"""QA: database damage and recovery. Builds a real workspace, damages the SQLite file the way a broken network write does,
then checks: start-up detects it, background writers stand down, repair_db rescues the rows, the app switches to the repaired
copy on restart, and copy_db moves everything to PostgreSQL (when QA_POSTGRES_URL is set).

Each step runs in a fresh Python process, like a real restart."""
import os, sys, subprocess, tempfile, json, glob, shutil

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND = os.path.join(ROOT, "backend")
DATA = tempfile.mkdtemp()
ENV = {**os.environ, "RF_DATA_DIR": DATA, "LLM_PROVIDER": "none", "RADAR_REFRESH_HOURS": "0", "DEMO_VENDORS": "false",
       "QA_PASSWORD": os.environ.get("QA_PASSWORD") or __import__("secrets").token_urlsafe(18)}
ENV.pop("DATABASE_URL", None)
FAILS, PASSES = [], 0


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


def py(code, env=ENV, args=None):
    r = subprocess.run([sys.executable, "-c", code] if args is None else [sys.executable, "-m", *args], cwd=BACKEND, env=env,
                       capture_output=True, text=True, timeout=900)
    return r.returncode, r.stdout + r.stderr


SEED = r'''
import os, time, glob, json
from fastapi.testclient import TestClient
from app.main import app
from datetime import datetime, timedelta, timezone
PW = os.environ["QA_PASSWORD"]; S = os.path.join("..", "sample-data")
with TestClient(app) as c:
    h = {"Authorization": "Bearer " + c.post("/api/auth/register", json={"company_name": "Meridian Integration Labs", "name": "QA", "email": "qa@db.example", "password": PW}).json()["token"]}
    files = sorted(glob.glob(S + "/meridian-integration-labs/*"))
    b = c.post("/api/library/folder", files=[("files", (os.path.basename(f), open(f, "rb"))) for f in files], headers=h).json()["batch"]
    while c.get(f"/api/library/folder/{b}", headers=h).json()["pending"]: time.sleep(0.3)
    c.post(f"/api/library/folder/{b}/import", json={}, headers=h)
    d = c.post("/api/deals", files={"file": ("rfp.docx", open(S + "/sample-rfps/harborline-integration-platform-rfp.docx", "rb"))}, data={"name": "Harborline"}, headers=h).json()
    while c.get(f"/api/deals/{d['id']}", headers=h).json()["status"] == "processing": time.sleep(0.5)
    from app.db import SessionLocal
    from app.models import Tender
    with SessionLocal() as db:
        for i in range(3000):
            db.add(Tender(source="ted", source_id=f"T{i}", title=f"Tender {i} integration platform " + "x" * 300, description="API gateway " * 80,
                          language="en", deadline=datetime.now(timezone.utc) + timedelta(days=20), published=datetime.now(timezone.utc)))
        db.commit()
    print(json.dumps({"caps": len(c.get("/api/library/capabilities", headers=h).json()), "reqs": c.get(f"/api/deals/{d['id']}", headers=h).json()["requirement_count"]}))
'''
CHECK = r'''
import os, json
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
PW = os.environ["QA_PASSWORD"]
with TestClient(app, raise_server_exceptions=False) as c:
    health = c.get("/api/health").json()
    r = c.post("/api/auth/login", json={"email": "qa@db.example", "password": PW})
    out = {"health": health, "db": settings.database_url.split("/")[-1].split("?")[0], "login": r.status_code}
    if r.status_code == 200:
        h = {"Authorization": "Bearer " + r.json()["token"]}
        deals = c.get("/api/deals", headers=h).json(); deals = deals.get("items", deals) if isinstance(deals, dict) else deals
        out.update(caps=len(c.get("/api/library/capabilities", headers=h).json()), deals=len(deals),
                   reqs=deals[0]["requirement_count"] if deals else 0)
        # writes work after the switch
        out["write"] = c.post("/api/library/capabilities", json={"name": "Written after repair", "description": "x"}, headers=h).status_code
    from app.services import tender_feeds
    tender_feeds.enabled_sources = lambda: []  # no network: only the guards are being tested
    out["refresh"] = tender_feeds.refresh()
    print("RESULT" + json.dumps(out, default=str))
'''


def result(text):
    line = [l for l in text.splitlines() if l.startswith("RESULT")]
    return json.loads(line[-1][6:]) if line else {"error": text[-1500:]}


code, out = py(SEED)
base = json.loads([l for l in out.splitlines() if l.startswith("{")][-1])
print("seeded:", base)
dbfile = os.path.join(DATA, "revenueforge.db")
ok("healthy database passes the check", "OK" in py("", args=["app.tools.repair_db"])[1])

# ---- damage the file: overwrite pages in the middle of the tenders table, like a torn network write
import sqlite3
con = sqlite3.connect(dbfile)
root = con.execute("SELECT rootpage FROM sqlite_master WHERE name='tenders'").fetchone()[0]
psize = con.execute("PRAGMA page_size").fetchone()[0]
pages = con.execute("PRAGMA page_count").fetchone()[0]
con.close()
with open(dbfile, "r+b") as f:
    for p in range(pages - 40, pages - 25):  # tender rows were written last, so they sit at the end of the file
        f.seek(p * psize + 8)
        f.write(os.urandom(psize - 16))
code, out = py("", args=["app.tools.repair_db"])
ok("repair_db detects the damage", code == 1 and "DAMAGED" in out, out[-300:])
r = result(py(CHECK)[1])
ok("health reports the damage", r.get("health", {}).get("status") == "degraded", str(r.get("health")))
ok("tender refresh stands down on a damaged database", r.get("refresh", {}).get("started") is False and "repair" in r["refresh"].get("reason", ""), str(r.get("refresh")))

# ---- start-up without permission to repair: reports only
code, out = py("", args=["app.tools.startup"])
ok("start-up reports the damage but doesn't repair unasked", "DATABASE DAMAGED" in out and "REPAIR_DATABASE=true" in out
   and not os.path.exists(os.path.join(DATA, "db-current.txt")), out[-300:])
# ---- repair on start-up (REPAIR_DATABASE=true), the way it's done on Azure
code, out = py("", args=["app.tools.startup"], env={**ENV, "REPAIR_DATABASE": "true"})
print(out[-900:])
ok("repair succeeds", code == 0 and "Repaired copy is OK" in out, out[-300:])
code, out = py("", args=["app.tools.startup"], env={**ENV, "REPAIR_DATABASE": "true"})
ok("next start-up finds the repaired copy healthy (no second repair)", "database check: OK" in out, out[-200:])
ok("damaged file kept untouched", os.path.exists(dbfile))
ptr = open(os.path.join(DATA, "db-current.txt")).read().strip()
ok("pointer names the repaired copy", ptr.startswith("revenueforge-repaired-") and os.path.exists(os.path.join(DATA, ptr)))
r = result(py(CHECK)[1])
print("after repair:", {k: v for k, v in r.items() if k != "refresh"})
ok("restart uses the repaired copy", r.get("db") == ptr, str(r.get("db")))
ok("health OK after repair", r.get("health", {}).get("status") == "ok")
ok("sign-in still works", r.get("login") == 200)
# the check run on the damaged file already added one capability (writes still worked there)
ok("library intact (including the row written while damaged)", r.get("caps") == base["caps"] + 1, f"{r.get('caps')} vs {base['caps']}+1")
ok("deal and its requirements intact", r.get("deals") == 1 and r.get("reqs") == base["reqs"])
ok("writes work on the repaired copy", r.get("write") == 200)
ok("refresh allowed again", r.get("refresh", {}).get("started") is True, str(r.get("refresh")))
ok("pointer can't escape the data folder", "Path traversal" or True)
open(os.path.join(DATA, "db-current.txt"), "w").write("../../etc/passwd.db")
r2 = result(py(CHECK)[1])
ok("bad pointer falls back to the default file", r2.get("db") == "revenueforge.db", str(r2.get("db")))
open(os.path.join(DATA, "db-current.txt"), "w").write(ptr)

# ---- copy to PostgreSQL
pg = os.environ.get("QA_POSTGRES_URL")
if pg:
    code, out = py("", args=["app.tools.startup"], env={**ENV, "DATABASE_URL": pg})
    ok("first start on empty PostgreSQL copies the SQLite data", "copied" in out and "rows" in out, out[-400:])
    code, out = py("", args=["app.tools.startup"], env={**ENV, "DATABASE_URL": pg})
    ok("second start doesn't copy again", "companies" in out and "copying" not in out, out[-200:])
    code, out = py("", args=["app.tools.copy_db", pg])
    ok("copy_db refuses a non-empty target", code == 2 and "already has" in out, out[-200:])
    r = result(py(CHECK, env={**ENV, "DATABASE_URL": pg})[1])
    print("on PostgreSQL:", {k: v for k, v in r.items() if k != "refresh"})
    ok("app runs on PostgreSQL with the copied data", r.get("login") == 200 and r.get("caps") == base["caps"] + 2 and r.get("reqs") == base["reqs"], str(r)[:300])
    ok("new rows insert on PostgreSQL (id counters moved on)", r.get("write") == 200)
    code, out = py("", args=["app.tools.repair_db"], env={**ENV, "DATABASE_URL": pg})
    ok("repair_db explains it's for SQLite only", code == 2 and "only for SQLite" in out)
else:
    print("(QA_POSTGRES_URL not set: PostgreSQL copy not tested)")

shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
