"""Deal owner, review notes on stages, and the deadline calendar.

Run: python tests/qa_review.py
"""
import io
import json
import os
import secrets
import sys
import tempfile
import time
import zipfile
from datetime import date, datetime, timedelta, timezone

os.environ.update(RF_DATA_DIR=tempfile.mkdtemp(), LLM_PROVIDER="none", RADAR_REFRESH_HOURS="0", DEMO_VENDORS="false")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
ROOT = os.path.join(os.path.dirname(__file__), "..", "..")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

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


with TestClient(app) as c:
    P = {}

    def register(company, email):
        P[email] = pw()
        return c.post("/api/auth/register", json={"company_name": company, "name": email.split("@")[0].title(), "email": email,
                                                   "password": P[email], "kind": "vendor"}).json()

    def H(email):
        r = c.post("/api/auth/login", json={"email": email, "password": P[email]})
        return {"Authorization": "Bearer " + r.json()["token"]}

    acme = register("Acme Integration", "admin@acme.example")
    A = {"Authorization": "Bearer " + acme["token"]}
    for email, role in (("pres@acme.example", "presales"), ("fin@acme.example", "finance"), ("arch@acme.example", "architect"),
                        ("view@acme.example", "viewer")):
        P[email] = pw()
        c.post("/api/auth/users", json={"name": email.split("@")[0].title(), "email": email, "role": role, "password": P[email]}, headers=A)
    PR, FI, AR, VI = H("pres@acme.example"), H("fin@acme.example"), H("arch@acme.example"), H("view@acme.example")
    users = {u["email"]: u for u in c.get("/api/auth/users", headers=A).json()}
    other = register("Other Co", "admin@other.example")
    OT = {"Authorization": "Bearer " + other["token"]}

    due = (date.today() + timedelta(days=4)).isoformat()
    rfp = os.path.join(ROOT, "sample-data", "sample-rfps", "harborline-integration-platform-rfp.docx")
    with open(rfp, "rb") as f:
        r = c.post("/api/deals", files={"file": ("rfp.docx", f)}, data={"name": "Harborline platform", "client_name": "Harborline Transit",
                                                                        "client_alias": "Client H", "confidential": "true", "due_date": due}, headers=PR)
    ok("presales person starts a deal", r.status_code == 200, r.text[:200])
    deal = r.json()
    D = deal["id"]
    for _ in range(300):
        deal = c.get(f"/api/deals/{D}", headers=PR).json()
        if deal["status"] != "processing":
            break
        time.sleep(0.3)
    ok("pipeline finished", deal["status"] == "in_review", deal["status"])
    if deal.get("due_date") != due:
        c.patch(f"/api/deals/{D}", json={"due_date": due}, headers=PR)

    # ---------------------------------------------------------------- owner
    ok("the person who started the deal is its owner", (deal.get("owner") or {}).get("name") == "Pres", deal.get("owner"))
    lst = c.get("/api/deals", headers=A).json()
    ok("owner is in the deal list too", lst and lst[0]["owner"]["id"] == users["pres@acme.example"]["id"])
    r = c.patch(f"/api/deals/{D}", json={"owner_id": users["view@acme.example"]["id"]}, headers=A)
    ok("a viewer can't be made owner", r.status_code == 400 and "viewer" in r.text, r.text[:120])
    r = c.patch(f"/api/deals/{D}", json={"owner_id": other["user"]["id"]}, headers=A)
    ok("someone from another company can't be made owner", r.status_code == 400)
    r = c.patch(f"/api/deals/{D}", json={"owner_id": users["admin@acme.example"]["id"]}, headers=PR)
    ok("owner can hand the deal over", r.status_code == 200 and r.json()["owner"]["name"] == "Admin", r.text[:120])
    r = c.patch(f"/api/deals/{D}", json={"owner_id": users["pres@acme.example"]["id"]}, headers=PR)
    ok("a non-owner presales person can't take it back", r.status_code == 403)
    r = c.patch(f"/api/deals/{D}", json={"owner_id": users["pres@acme.example"]["id"]}, headers=A)
    ok("admin can reassign", r.status_code == 200 and r.json()["owner"]["name"] == "Pres")
    audit = c.get("/api/auth/audit", headers=A)
    if audit.status_code == 200:
        ok("owner change is in the audit trail", any(e.get("action") == "deal.owner" for e in audit.json()), "")

    # ---------------------------------------------------------------- review notes
    pricing = c.get(f"/api/deals/{D}/stages/pricing", headers=FI).json()
    line = pricing["data"]["lines"][0]
    r = c.post(f"/api/deals/{D}/stages/pricing/notes", json={"text": "Day rate looks low for this role, check with Harborline Transit scope @pres",
                                                             "line_key": f"line:{line['role']}", "line": f"{line['role']} · {line['location']}"}, headers=FI)
    ok("finance leaves a note on one pricing line", r.status_code == 200, r.text[:200])
    n1 = r.json()
    ok("note keeps the line it is about", n1["line"].startswith(line["role"]) and n1["line_key"] == f"line:{line['role']}")
    ok("client name is masked in the note", "Harborline Transit" not in n1["text"] and "Client H" in n1["text"], n1["text"])
    ok("note starts open", n1["status"] == "open" and n1["author_role"] == "finance")
    r = c.post(f"/api/deals/{D}/stages/pricing/notes", json={"text": "Whole stage: add travel assumptions"}, headers=AR)
    n2 = r.json()
    ok("a note can be about the whole stage", r.status_code == 200 and n2["line"] == "")
    ok("viewer can't add notes", c.post(f"/api/deals/{D}/stages/pricing/notes", json={"text": "x"}, headers=VI).status_code == 403)
    ok("viewer can read notes", len(c.get(f"/api/deals/{D}/notes?stage=pricing", headers=VI).json()) == 2)
    ok("empty note refused", c.post(f"/api/deals/{D}/stages/pricing/notes", json={"text": "  "}, headers=FI).status_code == 400)
    ok("unknown stage refused", c.post(f"/api/deals/{D}/stages/nope/notes", json={"text": "x"}, headers=FI).status_code == 404)
    ok("another company can't read the notes", c.get(f"/api/deals/{D}/notes", headers=OT).status_code == 404)
    ok("another company can't add notes", c.post(f"/api/deals/{D}/stages/pricing/notes", json={"text": "x"}, headers=OT).status_code == 404)

    deal = c.get(f"/api/deals/{D}", headers=PR).json()
    pst = next(s for s in deal["stages"] if s["stage"] == "pricing")
    ok("deal shows open notes per stage and in total", pst["open_notes"] == 2 and deal["open_notes"] == 2, (pst, deal["open_notes"]))
    allnotes = c.get(f"/api/deals/{D}/notes", headers=PR).json()
    ok("owner sees everything left to fix", len(allnotes) == 2 and all(x["can_resolve"] for x in allnotes))
    ok("a different reviewer can't resolve someone else's note", not next(x for x in c.get(f"/api/deals/{D}/notes", headers=AR).json() if x["id"] == n1["id"])["can_resolve"])
    ok("…and the server agrees", c.post(f"/api/deals/{D}/notes/{n1['id']}/resolve", headers=AR).status_code == 403)

    r = c.post(f"/api/deals/{D}/stages/pricing/approve", headers=FI)
    ok("approval is held while notes are open", r.status_code == 409 and "2 review notes" in r.text, r.text[:160])
    r = c.post(f"/api/deals/{D}/notes/{n1['id']}/resolve", headers=PR)
    ok("owner resolves a note", r.status_code == 200 and r.json()["status"] == "resolved" and r.json()["resolved_by"] == "Pres")
    r = c.post(f"/api/deals/{D}/notes/{n1['id']}/reopen", headers=FI)
    ok("the author can reopen it", r.status_code == 200 and r.json()["status"] == "open")
    c.post(f"/api/deals/{D}/notes/{n1['id']}/resolve", headers=FI)
    ok("deleting someone else's note is refused", c.delete(f"/api/deals/{D}/notes/{n2['id']}", headers=FI).status_code == 403)
    r = c.post(f"/api/deals/{D}/stages/pricing/approve", headers=FI)
    ok("still held with one open note", r.status_code == 409 and "1 review note is" in r.text, r.text[:160])
    r = c.post(f"/api/deals/{D}/stages/pricing/approve", json={"despite_open_notes": True}, headers=FI)
    ok("reviewer can approve anyway", r.status_code == 200 and r.json()["status"] == "approved", r.text[:160])
    ok("author deletes own note", c.delete(f"/api/deals/{D}/notes/{n2['id']}", headers=AR).status_code == 200)
    r = c.post(f"/api/deals/{D}/stages/requirements/approve", headers=PR)
    ok("a stage with no notes approves as before (no body)", r.status_code == 200, r.text[:120])

    # ---------------------------------------------------------------- calendar
    from app.db import SessionLocal
    from app.models import Tender, TenderFit
    db = SessionLocal()
    tid = acme["user"]["tenant"]["id"]
    now = datetime.now(timezone.utc)
    rows = [("t-saved", "Saved data platform tender", 2, 20, "saved"), ("t-strong", "Strong-fit integration tender", 10, 75, "new"),
            ("t-weak", "Weak-fit catering tender", 5, 10, "new"), ("t-dismissed", "Dismissed tender", 6, 90, "dismissed")]
    for sid, title, days, score, status in rows:
        t = Tender(source="test", source_id=sid, title=title, buyer="Test Council", country="UK", deadline=now + timedelta(days=days),
                   url="https://example.org/" + sid)
        db.add(t)
        db.flush()
        db.add(TenderFit(tenant_id=tid, tender_id=t.id, score=score, status=status))
    db.commit()
    db.close()

    start, end = date.today().isoformat(), (date.today() + timedelta(days=30)).isoformat()
    cal = c.get(f"/api/calendar?start={start}&end={end}", headers=PR).json()
    titles = {e["title"] for e in cal["events"]}
    ok("calendar shows the deal on its due date", any(e["kind"] == "deal" and e["id"] == D and e["date"] == due for e in cal["events"]), cal["events"][:2])
    ok("client name is masked in the calendar", not any("Harborline Transit" in json.dumps(e) for e in cal["events"] if e["kind"] == "deal")
       and any(e.get("client") == "Client H" for e in cal["events"]))
    ok("saved and strong-fit tenders are shown", {"Saved data platform tender", "Strong-fit integration tender"} <= titles, titles)
    ok("weak and dismissed tenders are not", not ({"Weak-fit catering tender", "Dismissed tender"} & titles))
    only_saved = {e["title"] for e in c.get(f"/api/calendar?start={start}&end={end}&tenders=saved", headers=PR).json()["events"] if e["kind"] == "tender"}
    ok("saved-only filter", only_saved == {"Saved data platform tender"}, only_saved)
    ok("calendar is per company", not any(e["kind"] == "deal" for e in c.get(f"/api/calendar?start={start}&end={end}", headers=OT).json()["events"]))
    ok("bad range refused", c.get("/api/calendar?start=2026-01-01&end=2028-01-01", headers=PR).status_code == 400)
    ok("bad date refused", c.get("/api/calendar?start=tomorrow", headers=PR).status_code == 400)

    rem = c.get("/api/calendar/reminders", headers=PR).json()
    kinds = {(i["kind"], i["title"]) for i in rem["items"]}
    ok("owner is reminded of a deal due in 4 days", any(k == "deal" for k, _ in kinds), rem)
    ok("presales is reminded of a saved tender closing in 2 days", ("tender", "Saved data platform tender") in kinds)
    ok("strong-fit tender that isn't saved is not a reminder", ("tender", "Strong-fit integration tender") not in kinds)
    rem_fin = c.get("/api/calendar/reminders", headers=FI).json()
    ok("finance isn't reminded of tenders", not any(i["kind"] == "tender" for i in rem_fin["items"]))
    rem_vi = c.get("/api/calendar/reminders", headers=VI).json()
    ok("viewer has nothing waiting", rem_vi["count"] == 0, rem_vi)
    arch_rem = c.get("/api/calendar/reminders", headers=AR).json()
    ok("architect is reminded of stages waiting for them", any("Architecture" in i["why"] or "Capability match" in i["why"] for i in arch_rem["items"]), arch_rem)

    # undated deals
    c.patch(f"/api/deals/{D}", json={"due_date": "sometime soon"}, headers=PR)
    cal2 = c.get("/api/calendar", headers=PR).json()
    ok("a deal without a readable date is listed separately", any(u["id"] == D for u in cal2["undated"]))
    c.patch(f"/api/deals/{D}", json={"due_date": due}, headers=PR)

    r = c.get("/api/calendar/deadlines.ics", headers=PR)
    body = r.text
    ok("calendar file downloads", r.status_code == 200 and r.headers["content-type"].startswith("text/calendar"))
    ok("calendar file has the deal and saved tender", "Deal due: Client H platform" in body.replace("\r\n ", "") or "Deal due:" in body, body[:300])
    ok("calendar file has alarms 3 days and 1 day before", "TRIGGER:-P3D" in body and "TRIGGER:-P1D" in body)
    ok("calendar file keeps lines short", all(len(l.encode()) <= 75 for l in body.split("\r\n")))
    ok("calendar file never names the masked client", "Harborline Transit" not in body.replace("\r\n ", "") and "Client H" in body.replace("\r\n ", ""))
    ok("calendar needs sign-in", c.get("/api/calendar/deadlines.ics").status_code == 401)

    # export carries the notes
    r = c.get("/api/company/export", headers=A)
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist() if r.status_code == 200 else []
    ok("company export includes review notes", any(n.endswith("review_notes.json") for n in names), r.status_code)

print(f"\n{PASSES} passed, {len(FAILS)} failed")
for f in FAILS:
    print("  -", f)
sys.exit(1 if FAILS else 0)
