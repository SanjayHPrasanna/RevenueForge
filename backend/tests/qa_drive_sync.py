"""QA: a connected Google Drive folder. Connect, check (nothing changed), then a file changes, one is added, one is deleted,
and someone edited an item in the app. Google itself isn't called: the browser's listing and downloads are simulated."""
import os, sys, tempfile, glob, time, json, io
os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"; os.environ["DEMO_VENDORS"] = "false"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "backend"))
import openpyxl
from fastapi.testclient import TestClient
from app.main import app

PW = os.environ.get("QA_PASSWORD") or __import__("secrets").token_urlsafe(18)
PACK = os.path.join(ROOT, "sample-data", "meridian-integration-labs")
FAILS, PASSES = [], 0


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(f"{name} {extra}")
        print("FAIL", name, extra)


FOLDER = {"id": "drive-folder-1", "name": "Meridian knowledge"}
files = {f"g-{i}": {"name": os.path.basename(p), "data": open(p, "rb").read(), "version": "1", "modified": "2026-11-01T10:00:00Z"}
         for i, p in enumerate(sorted(glob.glob(PACK + "/*")))}
ID = {v["name"]: k for k, v in files.items()}


def listing():
    return [{"id": k, "path": f"Knowledge/{v['name']}", "modified": v["modified"], "version": v["version"]} for k, v in files.items()]


with TestClient(app, raise_server_exceptions=False) as c:
    def reg(co, em):
        return {"Authorization": "Bearer " + c.post("/api/auth/register", json={"company_name": co, "name": "QA", "email": em, "password": PW}).json()["token"]}
    A = reg("Meridian Integration Labs", "admin@drive.example")
    B = reg("Other Co", "admin@other.example")
    c.post("/api/auth/users", json={"name": "V", "email": "viewer@drive.example", "role": "viewer", "password": PW}, headers=A)
    V = {"Authorization": "Bearer " + c.post("/api/auth/login", json={"email": "viewer@drive.example", "password": PW}).json()["token"]}

    def upload(ids, change=None):
        form = [("files", (files[i]["name"], files[i]["data"])) for i in ids]
        data = {"paths": [f"Knowledge/{files[i]['name']}" for i in ids], "drive_folder": json.dumps(FOLDER),
                "drive": [json.dumps({"id": i, "modified": files[i]["modified"], "version": files[i]["version"], "change": (change or {}).get(i, "new")}) for i in ids]}
        r = c.post("/api/library/folder", files=form, data=data, headers=A)
        assert r.status_code == 200, r.text
        b = r.json()["batch"]
        while c.get(f"/api/library/folder/{b}", headers=A).json()["pending"]:
            time.sleep(0.3)
        return b

    def count(kind, h=A):
        return len(c.get(f"/api/library/{kind}", headers=h).json())

    ok("not connected at first", c.get("/api/library/drive", headers=A).json() == {"connected": False})
    # ---- connect
    b = upload(list(files))
    r = c.post(f"/api/library/folder/{b}/import", json={}, headers=A).json()
    ok("first import from Drive", r["files"] >= 7, str(r.get("counts")))
    st = c.get("/api/library/drive", headers=V).json()
    ok("folder connected", st["connected"] and st["folder"]["name"] == "Meridian knowledge" and st["files"] >= 7, json.dumps(st))
    ok("other company doesn't see the connection", c.get("/api/library/drive", headers=B).json() == {"connected": False})
    caps0, rates0 = count("capabilities"), count("rates")
    # ---- nothing changed
    p = c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": listing()}, headers=A).json()
    ok("unchanged folder is up to date", p["up_to_date"] and p["unchanged"] == len(files), json.dumps(p)[:200])
    ok("viewer can't refresh", c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": listing()}, headers=V).status_code == 403)
    ok("wrong folder refused", c.post("/api/library/drive/plan", json={"folder_id": "other", "files": listing()}, headers=A).status_code == 409)
    ok("company without a connection gets 404", c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": []}, headers=B).status_code == 404)
    ok("PUT /company can't overwrite the connection", "drive" not in json.dumps(c.put("/api/company", json={"settings": {"drive": {"folder": {"id": "x"}}}}, headers=A).json().get("settings", {}))
       or c.get("/api/library/drive", headers=A).json()["folder"]["id"] == FOLDER["id"])
    # ---- someone edits a capability in the app, and adds one by hand
    capid = ID["01_capabilities.xlsx"]
    items = c.get("/api/library/capabilities", headers=A).json()
    c.put(f"/api/library/capabilities/{items[0]['id']}", json={"description": "Edited in the app"}, headers=A)
    c.post("/api/library/capabilities", json={"name": "Added by hand in the app", "description": "Manual"}, headers=A)
    # ---- Drive changes: capabilities file gets a new row, a new case study file appears, the rate card is deleted
    wb = openpyxl.load_workbook(io.BytesIO(files[capid]["data"]))
    ws = wb.active
    hdr = [x.value for x in ws[1]]
    row = [""] * len(hdr)
    for i, h in enumerate(hdr):
        hl = str(h or "").lower()
        if "capab" in hl: row[i] = "Drive-added capability: event mesh"
        elif "descr" in hl: row[i] = "Solace event mesh design and operations"
        elif "service" in hl: row[i] = "Integration"
    ws.append(row)
    buf = io.BytesIO(); wb.save(buf)
    files[capid].update(data=buf.getvalue(), version="2", modified="2026-11-06T09:00:00Z")
    files["g-new"] = {"name": "09_case_study_port.docx", "data": files[ID["07_case_study_public_health.docx"]]["data"].replace(b"x", b"x"), "version": "1", "modified": "2026-11-06T09:00:00Z"}
    rate_id = ID["04_rate_card.xlsx"]
    rate = files.pop(rate_id)
    acc_id = ID["06_accelerators.xlsx"]
    acc = files.pop(acc_id)  # also deleted in Drive, but we'll choose to keep its items
    p = c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": listing()}, headers=A).json()
    ok("plan: 1 new", [x["id"] for x in p["new"]] == ["g-new"], json.dumps(p["new"]))
    ok("plan: 1 changed", [x["id"] for x in p["changed"]] == [capid], json.dumps(p["changed"]))
    ok("plan: says 1 item was edited in the app", p["changed"][0].get("edited_in_app") == 1, json.dumps(p["changed"][0]))
    ok("plan: 2 deleted from Drive, with item counts", {x["id"] for x in p["removed"]} == {rate_id, acc_id} and all(x["records"] > 0 for x in p["removed"]), json.dumps(p["removed"]))
    ok("plan changed nothing yet", count("capabilities") == caps0 + 1 and count("rates") == rates0)
    # ---- apply: only new + changed are uploaded; remove the rate card's items, keep the accelerators'
    b2 = upload(["g-new", capid], change={"g-new": "new", capid: "changed"})
    rows = c.get(f"/api/library/folder/{b2}", headers=A).json()["files"]
    ok("review screen marks new/changed", sorted(r["drive_change"] for r in rows) == ["changed", "new"], str([r["drive_change"] for r in rows]))
    acc0 = count("accelerators")
    r = c.post(f"/api/library/folder/{b2}/import", json={"sync": True, "remove": [rate_id]}, headers=A).json()
    ok("refresh imported 2 files", r["files"] == 2, json.dumps(r)[:200])
    caps = c.get("/api/library/capabilities", headers=A).json()
    names = [x["name"] for x in caps]
    ok("changed file replaced its own items (no duplicates)", len(names) == len(set(names)), str(len(names)))
    ok("new row from Drive is in", any("event mesh" in n for n in names))
    ok("item added by hand in the app is kept", "Added by hand in the app" in names)
    ok("capability count = new file + hand-added", len(caps) == caps0 + 2, f"{len(caps)} vs {caps0}+2")
    ok("rate card items removed as chosen", count("rates") == 0)
    ok("accelerator items kept (not ticked)", count("accelerators") == acc0)
    ok("case studies from the new file added", count("case_studies") > 0)
    # ---- check again: the unticked deletion is raised again, nothing else
    p = c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": listing()}, headers=A).json()
    ok("after refresh only the kept deletion is still asked about", not p["new"] and not p["changed"] and [x["id"] for x in p["removed"]] == [acc_id], json.dumps(p)[:300])
    ok("other company can't remove", c.post("/api/library/drive/remove", json={"ids": [acc_id]}, headers=B).status_code == 404)
    r = c.post("/api/library/drive/remove", json={"ids": [acc_id]}, headers=A)
    ok("removal-only refresh", r.status_code == 200 and count("accelerators") == 0, r.text[:150])
    p = c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": listing()}, headers=A).json()
    ok("now fully up to date", p["up_to_date"], json.dumps(p)[:200])
    # rename inside the folder isn't a change
    lst = listing(); lst[0]["path"] = "Knowledge/renamed/" + lst[0]["path"].split("/")[-1]
    ok("renamed/moved file isn't a change", c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": lst}, headers=A).json()["up_to_date"])
    # malformed listing
    r = c.post("/api/library/drive/plan", json={"folder_id": FOLDER["id"], "files": "nope"}, headers=A)
    ok("malformed listing handled (everything looks deleted, nothing changed)", r.status_code == 200 and count("capabilities") == caps0 + 2)
    # ---- disconnect keeps the library
    ok("viewer can't disconnect", c.delete("/api/library/drive", headers=V).status_code == 403)
    ok("disconnect", c.delete("/api/library/drive", headers=A).status_code == 200 and not c.get("/api/library/drive", headers=A).json()["connected"])
    ok("library kept after disconnect", count("capabilities") == caps0 + 2)
    # plain folder import (not Drive) doesn't create a connection
    form = [("files", (os.path.basename(x), open(x, "rb").read())) for x in sorted(glob.glob(PACK + "/0[1-3]*"))]
    b3 = c.post("/api/library/folder", files=form, headers=A).json()["batch"]
    while c.get(f"/api/library/folder/{b3}", headers=A).json()["pending"]:
        time.sleep(0.3)
    c.post(f"/api/library/folder/{b3}/import", json={}, headers=A)
    ok("ordinary folder import doesn't connect anything", not c.get("/api/library/drive", headers=A).json()["connected"])

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
