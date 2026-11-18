"""AI privacy: what actually leaves for the AI provider, read off the wire.

A whole deal runs with the AI switched on against a fake Gemini endpoint (httpx MockTransport inside the real llm module),
so every request body the app would send -- generation prompts and embedding inputs alike -- is captured exactly as it
would go over the network. Nothing reaches a real provider; the key is a dummy.

Checks:
  - confidential deal, empty answer library (Tarangini General Insurance Ltd / TGIL): no generation or embedding request
    body contains the client's name or alias; the AI team planner's prompt is masked yet still carries the technical scope
    needed to size a team; the executive summary prompt carries the alias, the summary the app stores keeps the alias,
    and only the Word proposal names the client
  - library storage: answers harvested from a confidential deal keep neither its name nor its alias in the stored
    question or answer; manual entries are neutralised the same way
  - confidential deal, populated library (including an entry saved before questions were neutralised): the library
    search really embeds both sides, nothing leaks, and the library still supplies a matching answer
  - non-confidential deal, populated library: the name is allowed through (proves the capture would have caught a
    leak) and library matching works
  - correction memory, across clients: a reviewer corrects answers on the confidential RFP; the stored correction keeps
    its technical and reviewer guidance but not the name; a different client's different RFP then uses it as guidance,
    and no Gemini or embedding request body carries the first client's name or alias (an example stored before masking
    included)
  - clean-up of old library entries and correction examples: backup first, IDs and metadata kept, no confidential name
    left, matching and guidance still work
  - an RFP that numbers its requirements with the client's acronym ("TGIL-01"): the extraction prompt carries the
    masked ID, and the requirement keeps the document's own ID internally
  - the in-app assistant (Maahi): a confidential deal's outcome notes reach the AI masked; a non-confidential deal's
    notes go through as written
  - the planner refuses to build a prompt without the deal's masker
"""
import os, sys, tempfile, time, json, re, hashlib

os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["RADAR_REFRESH_HOURS"] = "0"
os.environ["LLM_PROVIDER"] = "gemini"; os.environ["GEMINI_API_KEY"] = "dummy-key-not-real"; os.environ["LLM_RPM"] = "100000"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
import logging
logging.disable(logging.WARNING)
import httpx
from fastapi.testclient import TestClient
from app.main import app
from app.services import llm, teamplan
import domain_fixtures as F

PW = __import__("secrets").token_urlsafe(18)
FAILS, PASSES = [], 0
CLIENT, ALIAS = "Tarangini General Insurance Ltd", "TGIL"


def ok(name, cond, extra=""):
    global PASSES
    if cond:
        PASSES += 1
    else:
        FAILS.append(name)
        print("FAIL", name, str(extra)[:400])


# ---------------------------------------------------------------------- fake Gemini on the wire
WIRE: list[dict] = []  # {"kind": "generate"|"embed", "system": str, "text": str}
EXTRACT_ECHO = False  # when set, the fake answers the extraction prompt with one requirement per block, echoing the ID it was shown
TEAM_REPLY = {"roles": [
    {"role": "SOC Analyst (L1)", "phase": "Run", "fte": 2, "location": "Offshore", "skills": ["Microsoft Sentinel"], "certs": [],
     "min_years": 1, "serves": ["SOC-01"], "why": "24x7 monitoring"},
    {"role": "Identity Engineer", "phase": "Run", "fte": 1, "location": "Offshore", "skills": ["Microsoft Entra ID"], "certs": [],
     "min_years": 4, "serves": ["IAM-01"], "why": "identity migration"}]}


def _vec(t: str) -> list[float]:
    """Bag of hashed words: the same wording gives the same vector, so library matching can be checked end to end."""
    v = [0.0] * 128
    for w in re.findall(r"[a-z0-9]+", t.lower()):
        v[int(hashlib.sha256(w.encode()).hexdigest(), 16) % 128] += 1
    return v if any(v) else [1.0] + [0.0] * 127


def handler(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if request.method == "GET":
        return httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]}]})
    body = json.loads(request.content or b"{}")
    if "batchEmbedContents" in url:
        texts = [r["content"]["parts"][0]["text"] for r in body.get("requests", [])]
        WIRE.append({"kind": "embed", "system": "", "text": "\n".join(texts)})
        return httpx.Response(200, json={"embeddings": [{"values": _vec(t)} for t in texts]})
    system = " ".join(p.get("text", "") for p in (body.get("systemInstruction") or {}).get("parts", []))
    text = " ".join(p.get("text", "") for c in body.get("contents", []) for p in c.get("parts", []))
    WIRE.append({"kind": "generate", "system": system, "text": text})
    if EXTRACT_ECHO and "Blocks from an RFP" in text:
        reply = json.dumps([{"block": int(m.group(1)), "text": m.group(3).strip(), "category": "Functional", "priority": "Mandatory",
                             "ref": m.group(2).strip(), "confidence": 0.9}
                            for m in re.finditer(r"\[(\d+)\] \(p\d+; [^)]*\) ([^:\n]+): ([^\n]+)", text)])
    elif "delivery director sizing the team" in system:
        reply = json.dumps(TEAM_REPLY)
    elif "executive summaries" in system:
        m = re.search(r"'client': '([^']*)'", text)  # echo the client it was given, so the Word document can be checked
        reply = f"{m.group(1) if m else 'The client'} needs a 24x7 security operations centre. We propose a managed SOC."
    elif (body.get("generationConfig") or {}).get("responseMimeType") == "application/json":
        reply = "null"  # nothing usable: every other stage falls back to its rules, as it does when the AI misbehaves
    else:
        reply = "Not available."
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": reply}]}}], "usageMetadata": {"totalTokenCount": 1}})


_RealClient = httpx.Client


class _WireClient(_RealClient):
    def __init__(self, *a, **k):
        k.pop("transport", None)
        super().__init__(*a, transport=httpx.MockTransport(handler), **k)


llm.httpx.Client = _WireClient  # only the llm module's client: the real request-building code runs unchanged

# ---------------------------------------------------------------------- unit: the planner never builds an unmasked prompt
ok("the planner sends nothing without the deal's masker", teamplan.ai_roles([{"source_ref": "X-1", "text": f"Operate a SOC for {CLIENT}",
                                                                             "workstream": "Service operations"}], {}, [("Run", 12)], 4.8) is None)
n0 = len(WIRE)
from app.services.masking import mask_obj
masker = lambda x: mask_obj(x, CLIENT, [ALIAS], "Client C")
teamplan.ai_roles([{"source_ref": "SOC-01", "text": f"Operate a 24x7 SOC for {CLIENT} ({ALIAS}) on 3,500 endpoints", "workstream": "Service operations"}],
                  {"eligibility": [{"kind": "staff", "text": f"The {ALIAS} SOC lead shall hold CISSP"}]}, [("Run", 36)], 4.8, mask=masker)
sent = [w for w in WIRE[n0:] if w["kind"] == "generate"]
ok("an unmasked caller is still masked on the way out (second line of defence)", sent and CLIENT not in sent[0]["text"] and
   not re.search(r"\bTGIL\b", sent[0]["text"]) and "Client C" in sent[0]["text"] and "3,500 endpoints" in sent[0]["text"], sent[0]["text"][:300] if sent else "")

def _leaks(wire):
    return [(w["kind"], re.search(r".{0,60}(Tarangini|TGIL).{0,40}", w["system"] + w["text"], re.I).group(0)) for w in wire
            if re.search(r"tarangini|\bTGIL\b", w["system"] + w["text"], re.I)]


# ---------------------------------------------------------------------- unit: requirement IDs that carry the client's acronym
from app.services import extraction
from app.services.parsing import Block, ParsedDocument
EXTRACT_ECHO = True
n0 = len(WIRE)
_doc = ParsedDocument(filename="ids.pdf", pages=1, blocks=[
    Block(0, 1, "table_row", "The bidder shall operate a 24x7 SOC on Microsoft Sentinel.", f"{ALIAS} security scope", "TGIL-01"),
    Block(1, 1, "table_row", "The bidder shall manage CrowdStrike Falcon EDR on 3,500 endpoints.", "Scope", "TGIL-02"),
    Block(2, 1, "table_row", "The bidder shall migrate identities to Microsoft Entra ID.", "Scope", "IAM-01")])
_got = extraction.llm_extract(_doc, mask_fn=lambda x: mask_obj(x, CLIENT, [ALIAS], "Client A"))
EXTRACT_ECHO = False
_sent = [w for w in WIRE[n0:] if w["kind"] == "generate"]
ok("requirement IDs: the extraction prompt was sent", bool(_sent))
ok("requirement IDs: no extraction request carries the client's acronym", not _leaks(WIRE[n0:]), _leaks(WIRE[n0:]))
ok("requirement IDs: the prompt carries the masked ID and the technical text", _sent and "Client A-01: The bidder shall operate a 24x7 SOC on Microsoft Sentinel" in _sent[0]["text"]
   and "IAM-01: " in _sent[0]["text"], _sent[0]["text"][:300] if _sent else "")
ok("requirement IDs: the document's own IDs are kept internally", [r["source_ref"] for r in _got] == ["TGIL-01", "TGIL-02", "IAM-01"], [r.get("source_ref") for r in _got])

# ---------------------------------------------------------------------- whole deals, on the wire
from app.db import SessionLocal
from app.models import AnswerEntry, Deal, DealStage, Requirement
from app.services import learning
from sqlalchemy import select


def leaks_in(wire: list[dict]) -> list:
    out = []
    for i, w in enumerate(wire):
        blob = w["system"] + "\n" + w["text"]
        if "tarangini" in blob.lower() or re.search(r"\bTGIL\b", blob):
            m = re.search(r".{0,60}(Tarangini|TGIL).{0,40}", blob, re.I)
            out.append((i, w["kind"], w["system"][:50], m.group(0) if m else ""))
    return out


def stored_names(text: str) -> bool:
    return bool(text) and ("tarangini" in text.lower() or bool(re.search(r"\bTGIL\b", text)))


SOC03 = "The bidder shall deploy and manage CrowdStrike Falcon EDR on 3,500 endpoints and 400 servers."
LEGACY_Q = f"The bidder shall operate a 24x7x365 Security Operations Centre monitoring all {CLIENT} ({ALIAS}) endpoints."

with TestClient(app, raise_server_exceptions=False) as c:
    r = c.post("/api/auth/register", json={"company_name": "Kestrel Privacy QA", "name": "Asha Admin", "email": "admin@privacy.example", "password": PW})
    assert r.status_code == 200, r.text
    h = {"Authorization": "Bearer " + r.json()["token"]}
    r = c.put("/api/company", json={"about": "IT services company, 140 people, Hyderabad.", "headcount": 140,
                                    "settings": {"generalised_response": True}}, headers=h)
    assert r.status_code == 200, r.text
    for kind, rows in (("capabilities", F.CAPABILITIES), ("skills", F.PEOPLE), ("certifications", F.CERTIFICATIONS),
                       ("case_studies", F.CASE_STUDIES), ("accelerators", F.ACCELERATORS), ("rates", F.RATES)):
        for row in rows:
            assert c.post(f"/api/library/{kind}", json=row, headers=h).status_code == 200
    fname, data = F.rfp_bytes("cybersecurity")

    def run_deal(confidential: bool, rfp=None, client=CLIENT, aliases=ALIAS):
        start = len(WIRE)
        form = {"confidential": "true" if confidential else "false", "ai_ack": "true", "client_name": client, "client_aliases": aliases}
        r = c.post("/api/deals", files={"file": rfp or (fname, data)}, data=form, headers=h)
        assert r.status_code == 200, r.text[:300]
        did = r.json()["id"]
        t0 = time.time()
        while time.time() - t0 < 600 and c.get(f"/api/deals/{did}", headers=h).json()["status"] == "processing":
            time.sleep(0.4)
        return did, WIRE[start:]

    def wire_counts(wire):
        return {k: sum(1 for w in wire if w["kind"] == k) for k in ("generate", "embed")}

    # ================================================= 1. confidential deal, empty answer library
    with SessionLocal() as db:
        ok("scenario 1 starts with an empty answer library", db.query(AnswerEntry).count() == 0)
    did, wire = run_deal(True)
    d = c.get(f"/api/deals/{did}", headers=h).json()
    est = c.get(f"/api/deals/{did}/stages/estimation", headers=h).json()["data"]
    ok("[1] confidential deal completes with the AI on", d["status"] in ("in_review", "ready"), d["status"])
    ok("[1] the AI was really called (generation and embeddings)", all(wire_counts(wire).values()), wire_counts(wire))
    ok("[1] no generation or embedding request body contains the client's name or alias", not leaks_in(wire), leaks_in(wire)[:6])
    team_prompts = [w for w in wire if "delivery director sizing the team" in w["system"]]
    ok("[1] the AI team planner was called for this deal", len(team_prompts) == 1, len(team_prompts))
    ok("[1] the AI team proposal was used (after its checks)", est.get("team_engine") == "ai", est.get("team_engine"))
    ok("[1] team sizing is there: roles with FTE", est.get("headcount", 0) > 0 and any(t.get("fte") for t in est.get("team", [])), est.get("headcount"))
    tp = team_prompts[0]["text"] if team_prompts else ""
    ok("[1] team planner prompt: the client appears only as its alias", "Client" in tp and "tarangini" not in tp.lower(), tp[:300])
    for term in ("Microsoft Sentinel", "CrowdStrike Falcon EDR", "CyberArk", "Microsoft Entra ID", "24x7", "3,500 endpoints", "CISSP", "SOC-01", "IAM-01"):
        ok(f"[1] team planner prompt keeps the technical scope: {term}", term in tp)
    ok("[1] team planner prompt carries the contract phases", '"Transition"' in tp and '"Run"' in tp, tp[:200])
    open(os.path.join(os.environ["RF_DATA_DIR"], "team_prompt_confidential.txt"), "w").write(tp)
    print("---- team planner prompt (confidential deal), as sent ----\n" + tp[:1800] + "\n----")
    with SessionLocal() as db:
        alias = db.get(Deal, did).client_alias
    es = [w for w in wire if "executive summaries" in w["system"]]
    ok("[1] executive summary: the AI was asked, with the alias as the client", es and f"'client': '{alias}'" in es[0]["text"], es[0]["text"][:200] if es else "none")
    prop_st = c.get(f"/api/deals/{did}/stages/proposal", headers=h).json()
    prop = prop_st.get("data") or {}
    summ = prop.get("executive_summary", "")
    ok("[1] the summary the app stores and shows keeps the alias", alias in summ and not stored_names(summ), summ[:200])
    from docx import Document as _Docx
    import io as _io
    dl = c.get(f"/api/deals/{did}/download/proposal", headers=h)
    ok("[1] the Word proposal downloads", dl.status_code == 200, dl.status_code)
    _doc = _Docx(_io.BytesIO(dl.content)) if dl.status_code == 200 else None
    doc_text = "\n".join([p.text for p in _doc.paragraphs] + [cell.text for t in _doc.tables for row in t.rows for cell in row.cells]) if _doc else ""
    ok("[1] the Word proposal names the client (real name put in only at document build)", f"{CLIENT} needs a 24x7 security operations centre" in doc_text,
       doc_text[:300])
    ok("[1] the Word proposal does not show the alias in the summary", f"{alias} needs a 24x7" not in doc_text)
    ok("[1] proposal content: requirement answers are present", sum(1 for x in doc_text.split("\n") if len(x) > 60) > 20)

    # ================================================= library storage
    with SessionLocal() as db:
        deal1 = db.get(Deal, did)
        reqs = db.scalars(select(Requirement).where(Requirement.deal_id == did)).all()
        named = [r for r in reqs if stored_names(r.text)]
        ok("storage: the confidential deal has requirement text naming the client (the case to protect)", bool(named), len(named))
        for r in named[:2]:
            r.response, r.response_source = f"We will run this for {CLIENT} ({ALIAS}) from our Hyderabad SOC, staffed 24x7.", "human"
        db.commit()
        added = learning.harvest_answers(db, deal1, "QA approver")
        db.commit()
        entries = db.scalars(select(AnswerEntry).where(AnswerEntry.source_deal == did)).all()
        ok("storage: approved answers were harvested into the library", added > 0 and entries, added)
        ok("storage: no stored question names the client", not any(stored_names(e.question) for e in entries),
           [e.question[:90] for e in entries if stored_names(e.question)][:3])
        ok("storage: no stored answer names the client", not any(stored_names(e.answer) for e in entries),
           [e.answer[:90] for e in entries if stored_names(e.answer)][:3])
        ok("storage: no stored label names the client", not any(stored_names(e.source_label) for e in entries))
        ok("storage: the alias is not stored either (questions and answers use the client placeholder)",
           not any(alias in (e.question + e.answer) for e in entries) and any(learning.CLIENT_TOKEN in e.question for e in entries))
        ok("storage: the technical meaning of a question is kept",
           any("24x7x365 Security Operations Centre" in e.question and learning.CLIENT_TOKEN + " endpoints" in e.question for e in entries),
           [e.question[:120] for e in entries][:3])
        # an entry saved the old way, before questions were neutralised
        legacy = AnswerEntry(tenant_id=deal1.tenant_id, question=LEGACY_Q, answer="We run a tiered 24x7 SOC from Hyderabad.", category="Functional",
                             origin="human", approved_by="QA approver", source_label="Added manually", source_deal=did, uses=3,
                             technologies=["Microsoft Sentinel"], industry="Insurance")
        db.add(legacy)
        db.commit()
        legacy_id, legacy_created = legacy.id, legacy.created_at
    r = c.post("/api/learning/answers", json={"question": SOC03, "answer": "We deploy and run CrowdStrike Falcon on every endpoint and server, with a "
                                              "24x7 analyst watching the console."}, headers=h)
    ok("storage: a manual library answer is accepted", r.status_code == 200, r.text[:200])
    manual_id = r.json().get("id")
    r = c.post("/api/learning/answers", json={"question": f"Provide monthly SOC reports to {CLIENT} leadership", "answer": f"Monthly reports for {ALIAS}."}, headers=h)
    with SessionLocal() as db:
        e = db.get(AnswerEntry, r.json()["id"])
        ok("storage: a manual entry naming a confidential client is neutralised on save", not stored_names(e.question + e.answer), (e.question, e.answer))
        db.delete(e)
        db.commit()

    # ================================================= 2. confidential deal, populated library (incl. the old-style entry)
    did2, wire2 = run_deal(True)
    ok("[2] confidential deal with a populated library completes", c.get(f"/api/deals/{did2}", headers=h).json()["status"] in ("in_review", "ready"))
    ok("[2] the AI was really called (generation and embeddings)", all(wire_counts(wire2).values()), wire_counts(wire2))
    ok("[2] no generation or embedding request body contains the client's name or alias", not leaks_in(wire2), leaks_in(wire2)[:6])
    embeds = "\n".join(w["text"] for w in wire2 if w["kind"] == "embed")
    ok("[2] the library search really embedded the stored questions (old entry included, neutralised)",
       "monitoring all " + learning.CLIENT_TOKEN in embeds or learning.CLIENT_TOKEN + " (" + learning.CLIENT_TOKEN + ") endpoints" in embeds, embeds[:300])
    ok("[2] the library search really embedded this deal's requirements", "CrowdStrike Falcon EDR on 3,500 endpoints" in embeds)
    with SessionLocal() as db:
        soc3 = next((r for r in db.scalars(select(Requirement).where(Requirement.deal_id == did2)) if "Falcon EDR on 3,500" in r.text), None)
        ok("[2] library matching still works: the approved answer is reused for SOC-03", soc3 is not None and soc3.response_ref == manual_id,
           (soc3.response_ref, soc3.response_source) if soc3 else None)
    tp2 = next((w["text"] for w in wire2 if "delivery director sizing the team" in w["system"]), "")
    ok("[2] the planner still gets the technical scope", all(t in tp2 for t in ("Microsoft Sentinel", "CrowdStrike Falcon EDR", "3,500 endpoints")))

    # ================================================= 3. non-confidential deal, populated library
    did3, wire3 = run_deal(False)
    tp3 = next((w["text"] for w in wire3 if "delivery director sizing the team" in w["system"]), "")
    ok("[3] non-confidential deal: the planner still runs", bool(tp3))
    ok("[3] non-confidential deal: the client's name is not masked (the capture would have caught a leak)", "Tarangini" in tp3 or "TGIL" in tp3, tp3[:300])
    ok("[3] non-confidential deal: the same technical scope is sent", all(t in tp3 for t in ("Microsoft Sentinel", "CrowdStrike Falcon EDR", "3,500 endpoints")))
    embeds3 = [w["text"] for w in wire3 if w["kind"] == "embed"]
    ok("[3] the library search never sends a stored question with a confidential client's name",
       not any(LEGACY_Q.split(" monitoring")[0] in t and "tarangini" in t.lower() for t in embeds3))
    with SessionLocal() as db:
        soc3 = next((r for r in db.scalars(select(Requirement).where(Requirement.deal_id == did3)) if "Falcon EDR on 3,500" in r.text), None)
        ok("[3] library matching works for a non-confidential deal too", soc3 is not None and soc3.response_ref == manual_id,
           (soc3.response_ref, soc3.response_source) if soc3 else None)

    # ================================================= 4. correction memory, across clients
    from app.models import LearningExample
    rq = c.get(f"/api/deals/{did}/requirements", headers=h).json()
    rq = rq if isinstance(rq, list) else (rq.get("items") or rq.get("requirements") or [])
    soc1 = next(x for x in rq if "24x7x365 Security Operations Centre" in x.get("text", ""))
    iam1 = next(x for x in rq if "Microsoft Entra ID" in x.get("text", ""))
    FIX_TEXT = "Our 24x7 SOC runs Microsoft Sentinel with tiered L1-L3 analysts; P1 alerts are triaged inside 15 minutes."
    r1 = c.patch(f"/api/deals/{did}/requirements/{soc1['id']}", json={"response": FIX_TEXT + f" {CLIENT} ({ALIAS}) gets a named service manager."}, headers=h)
    new_cat = "Non-functional" if iam1.get("category") != "Non-functional" else "Functional"
    r2 = c.patch(f"/api/deals/{did}/requirements/{iam1['id']}", json={"category": new_cat}, headers=h)
    ok("[4] a reviewer can correct an answer and a category on the confidential RFP", r1.status_code == 200 and r2.status_code == 200, (r1.text[:150], r2.text[:150]))
    with SessionLocal() as db:
        ex = db.scalars(select(LearningExample).where(LearningExample.deal_id == did)).all()
        resp = [x for x in ex if x.kind == "response"]
        cat = [x for x in ex if x.kind == "category"]
        ok("[4] the corrections are stored", resp and cat, [(x.kind, x.input_text[:60]) for x in ex])
        ok("[4] no stored correction carries the client's name or alias",
           not any(stored_names(x.input_text) or stored_names(x.ai_value) or stored_names(x.human_value) or stored_names(json.dumps(x.context)) for x in ex),
           [(x.kind, x.input_text[:90], x.human_value[:90]) for x in ex if stored_names(x.input_text + x.human_value)][:3])
        alias1 = db.get(Deal, did).client_alias
        ok("[4] nor the app alias", not any(alias1 in (x.input_text + x.ai_value + x.human_value) for x in ex))
        ok("[4] the technical and reviewer guidance is kept", resp and "24x7x365 Security Operations Centre" in resp[0].input_text and
           FIX_TEXT in resp[0].human_value and cat and "Microsoft Entra ID" in cat[0].input_text and cat[0].human_value == new_cat,
           (resp[0].input_text[:120], resp[0].human_value[:160]) if resp else None)
        # a correction stored the old way, before corrections were masked
        old_ex = LearningExample(tenant_id=db.get(Deal, did).tenant_id, kind="response", deal_id=did, user="Asha Admin",
                                 input_text=f"Quarterly VAPT across {CLIENT} internet-facing applications",
                                 ai_value="We will test the applications.", human_value=f"Our CREST-certified testers assess all 60 {ALIAS} applications every quarter.",
                                 context={"section": f"{ALIAS} security scope", "code": "VM-01"})
        db.add(old_ex)
        db.commit()
        old_ex_id, old_ex_created = old_ex.id, old_ex.created_at
    cloud_name, cloud_data = F.rfp_bytes("cloud")
    ok("[4] the second RFP is a different client's and does not name the first client",
       b"Tarangini" not in cloud_data and b"TGIL" not in cloud_data)
    did4, wire4 = run_deal(False, rfp=(cloud_name, cloud_data), client="Second Client Pvt Ltd", aliases="")
    ok("[4] the different client's deal completes", c.get(f"/api/deals/{did4}", headers=h).json()["status"] in ("in_review", "ready"))
    ok("[4] the AI was really called (generation and embeddings)", all(wire_counts(wire4).values()), wire_counts(wire4))
    guided = [w for w in wire4 if "reviewers rewrote" in w["text"]]
    ok("[4] the stored correction is used as guidance in the other client's prompts", guided and FIX_TEXT in guided[0]["text"],
       guided[0]["text"][-600:] if guided else "no guidance prompt")
    ok("[4] the correction stored before masking is used too, masked", guided and "CREST-certified testers assess all 60 " + learning.CLIENT_TOKEN in guided[0]["text"])
    cat_guided = [w for w in wire4 if "reviewers corrected earlier AI output" in w["text"]]
    ok("[4] the category correction guides the other client's requirement extraction", cat_guided and "Microsoft Entra ID" in cat_guided[0]["text"])
    ok("[4] no Gemini or embedding request body for the other client carries the first client's name or alias", not leaks_in(wire4), leaks_in(wire4)[:6])
    ok("[4] nor the first client's app alias", not any(re.search(rf"(?<![A-Za-z]){re.escape(alias1)}(?![A-Za-z0-9])", w["system"] + w["text"]) for w in wire4))
    n0 = len(WIRE)
    did5, wire5 = run_deal(True)
    ok("[4] a later confidential deal also gets the guidance without the name", any("reviewers rewrote" in w["text"] for w in wire5) and not leaks_in(wire5),
       leaks_in(wire5)[:4])

    # ================================================= 5. the in-app assistant (Maahi) and outcome notes
    r1 = c.patch(f"/api/deals/{did}", json={"outcome_notes": f"Lost: {ALIAS} chose a cheaper bidder; {CLIENT} wanted a local SOC."}, headers=h)
    r3 = c.patch(f"/api/deals/{did4}", json={"outcome_notes": "Won: Second Client Pvt Ltd liked our landing zone."}, headers=h)
    ok("[5] outcome notes can be saved", r1.status_code == 200 and r3.status_code == 200, (r1.text[:150], r3.text[:150]))
    n0 = len(WIRE)
    r = c.post("/api/assistant/workspace", json={"messages": [{"role": "user", "content": "Why did we lose or win our recent deals?"}]}, headers=h)
    ok("[5] the assistant answers", r.status_code == 200, r.text[:200])
    mw = [w for w in WIRE[n0:] if w["kind"] == "generate"]
    ok("[5] the assistant's request was captured", len(mw) == 1, len(mw))
    body5 = mw[0]["text"] if mw else ""
    # this workspace also holds a NON-confidential deal for the same client (scenario 3), whose line may name it; every
    # line naming the client must be that deal's own line, and no confidential deal's line may
    with SessionLocal() as db:
        conf_aliases = {d.client_alias for d in db.scalars(select(Deal).where(Deal.confidential.is_(True)))}
    named = [ln for ln in (mw[0]["system"] + "\n" + body5).split("\n") if re.search(r"tarangini|\bTGIL\b", ln, re.I)]
    ok("[5] no assistant request line about a confidential deal carries the client's name or alias",
       all(f"| client: {CLIENT} |" in ln and not any(f"client: {a} " in ln for a in conf_aliases) for ln in named), named[:4])
    ok("[5] the confidential deals are listed by alias only", all(f"client: {a} " in body5 for a in conf_aliases), conf_aliases)
    ok("[5] the confidential deal's outcome notes are there, masked", f"Lost: {alias1} chose a cheaper bidder; {alias1} wanted a local SOC" in body5,
       re.search(r"outcome: Lost.{0,120}", body5).group(0) if re.search(r"outcome: Lost.{0,120}", body5) else body5[:300])
    ok("[5] a non-confidential deal's outcome notes go through as written (the capture would see a leak)",
       "Won: Second Client Pvt Ltd liked our landing zone" in body5)

    # ================================================= clean-up of entries saved before questions were neutralised
    with SessionLocal() as db:
        before = {e.id: (e.source_deal, e.origin, e.approved_by, e.uses, e.source_label, e.category, list(e.technologies or []), e.industry, e.created_at)
                  for e in db.scalars(select(AnswerEntry))}
        n_before = len(before)
        plan = learning.clean_library(db, apply=False)
        ok("clean-up: the dry run finds the old entry and changes nothing", [b["id"] for b in plan["backup"]] == [legacy_id] and
           db.get(AnswerEntry, legacy_id).question == LEGACY_Q, [b["id"] for b in plan["backup"]])
        ok("clean-up: the backup holds the entry exactly as it was", plan["backup"] and plan["backup"][0]["question"] == LEGACY_Q)
        cplan = learning.clean_corrections(db, apply=False)
        ok("clean-up: the dry run finds the old correction example only, and changes nothing", [b["id"] for b in cplan["backup"]] == [old_ex_id] and
           CLIENT in db.get(LearningExample, old_ex_id).input_text, [b["id"] for b in cplan["backup"]])
        ex_before = {x.id: (x.kind, x.deal_id, x.user, x.created_at, x.tenant_id) for x in db.scalars(select(LearningExample))}
    env = dict(os.environ)
    import subprocess
    out = subprocess.run([sys.executable, os.path.join(os.path.dirname(HERE), "scripts", "clean_library.py"), "--apply"], env=env,
                         capture_output=True, text=True, timeout=300)
    print(out.stdout.strip())
    ok("clean-up script: backup written, entries cleaned, nothing left", out.returncode == 0 and "backup written" in out.stdout and
       "confidential names left: 0" in out.stdout, out.stdout + out.stderr[-600:])
    bk = [f for f in os.listdir(os.environ["RF_DATA_DIR"]) if f.startswith("library_backup_")]
    ok("clean-up script: the backup file holds the original question", bk and
       json.load(open(os.path.join(os.environ["RF_DATA_DIR"], bk[0])))["library"][0]["question"] == LEGACY_Q)
    with SessionLocal() as db:
        after = {e.id: (e.source_deal, e.origin, e.approved_by, e.uses, e.source_label, e.category, list(e.technologies or []), e.industry, e.created_at)
                 for e in db.scalars(select(AnswerEntry))}
        ok("clean-up: IDs, relationships and metadata are unchanged", after == before and len(after) == n_before)
        ex_after = {x.id: (x.kind, x.deal_id, x.user, x.created_at, x.tenant_id) for x in db.scalars(select(LearningExample))}
        ok("clean-up: correction IDs, deals, users and dates are unchanged", ex_after == ex_before)
        ox = db.get(LearningExample, old_ex_id)
        ok("clean-up: the old correction no longer names the client and keeps its guidance",
           not stored_names(ox.input_text + ox.human_value + json.dumps(ox.context)) and "Quarterly VAPT" in ox.input_text and
           "CREST-certified testers assess all 60" in ox.human_value and ox.context.get("code") == "VM-01", (ox.input_text, ox.human_value, ox.context))
        bkj = json.load(open(os.path.join(os.environ["RF_DATA_DIR"], bk[0])))
        ok("clean-up: the backup holds the correction exactly as it was", any(b["id"] == old_ex_id and CLIENT in b["input_text"] for b in bkj["corrections"]))
        ok("clean-up: correction memory still guides prompts afterwards",
           any(FIX_TEXT in e["human"] for e in learning.few_shot(db, ox.tenant_id, ["response"], ["Operate a SOC with Microsoft Sentinel"], k=8)))
        le = db.get(AnswerEntry, legacy_id)
        ok("clean-up: the old question no longer names the client, and keeps its meaning",
           not stored_names(le.question) and "24x7x365 Security Operations Centre" in le.question, le.question)
        ok("clean-up: no stored question in the library names a confidential client",
           not any(stored_names(e.question) for e in db.scalars(select(AnswerEntry))))
        tid = le.tenant_id
        nf = learning.library_neutraliser(db, tid)
        ok("neutraliser: whole-word aliases only ('client application' is left alone)",
           nf("The client application and Client Approval flow") == "The client application and Client Approval flow")
        hits = learning.library_matches(db, tid, [{"id": "q1", "text": SOC03}, {"id": "q2", "text": LEGACY_Q}])
        ok("clean-up: library matching still works afterwards", hits.get("q1", (None,))[0] is not None and hits["q1"][0].id == manual_id, hits)
        ok("clean-up: the cleaned entry still matches its own requirement", "q2" in hits and hits["q2"][0].id == legacy_id, hits.get("q2"))
        n0 = len(WIRE)
        learning.library_matches(db, tid, [{"id": "q3", "text": f"Operate the SOC for {CLIENT}"}])
        ok("clean-up: a later library search sends no confidential name", not leaks_in(WIRE[n0:]), leaks_in(WIRE[n0:]))

print(f"\n{PASSES} passed, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
