"""Five-domain IT acceptance pack: does the pipeline produce a correct bid for any IT RFP, not just the ones it was tuned on?

For each of five RFPs (software, cybersecurity, cloud migration, networking + 24x7 NOC, data platform + managed operations)
it runs the whole deal against one supplier library and scores what came out, not whether the steps finished:

  understanding  due date, budget, evaluation weights, contract phases, named technologies
  bid decision   failed mandatory eligibility makes the verdict "No bid" / "Bid in a consortium"
  team           the roles the scope needs exist; nobody is placed without the skills; nobody is booked past capacity
  proposal       no wording from other domains, no internal notes, no answer reused for different requirements,
                 no "company strength" without library evidence
  commercial     priced over the whole contract; partner and licence lines where the RFP needs them

Usage (from backend/):  python tests/qa_domains.py [--mode off|on|both] [--json out.json] [--strict]
  off  = the workspace switch "generalised_response" off (today's pipeline), on = switched on, both = run each.
  --strict exits non-zero unless every check passes in "on" mode. Without it the pack only reports (a scorecard).
Runs offline with no AI key (deterministic fallbacks); a throwaway database, never real data.
"""
import os, sys, tempfile, time, json, io, re, argparse

os.environ["RF_DATA_DIR"] = tempfile.mkdtemp(); os.environ["LLM_PROVIDER"] = "none"; os.environ["RADAR_REFRESH_HOURS"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE)); sys.path.insert(0, HERE)
from fastapi.testclient import TestClient
from app.main import app
import domain_fixtures as F

PW = __import__("secrets").token_urlsafe(18)


def docx_text(b: bytes) -> str:
    from docx import Document
    d = Document(io.BytesIO(b))
    parts = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            parts += [c.text for c in row.cells]
    return "\n".join(parts)


def rfp_text(name: str, data: bytes) -> str:
    if name.endswith(".docx"):
        return docx_text(data)
    import fitz
    return "\n".join(p.get_text() for p in fitz.open(stream=data, filetype="pdf"))


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def library_terms() -> set[str]:
    terms = set()
    for c in F.CAPABILITIES:
        terms.update(norm(t) for t in c["technologies"])
    for p in F.PEOPLE:
        terms.update(norm(s["name"]) for s in p["skills"])
    for cs in F.CASE_STUDIES:
        terms.update(norm(t) for t in cs["technologies"])
    return {t for t in terms if t}


def score_domain(c, h, dom: str, did: str) -> list[tuple[str, str, bool, str]]:
    """(group, check, passed, detail) for one finished deal."""
    exp = F.DOMAINS[dom]["expect"]
    fname, data = F.rfp_bytes(dom)
    src = rfp_text(fname, data)
    d = c.get(f"/api/deals/{did}", headers=h).json()
    meta = d.get("meta") or {}
    prof = meta.get("profile") or {}
    reqs = c.get(f"/api/deals/{did}/requirements", headers=h).json()
    reqs = reqs.get("items", reqs) if isinstance(reqs, dict) else reqs
    st = {s: (c.get(f"/api/deals/{did}/stages/{s}", headers=h).json().get("data") or {}) for s in
          ("gaps", "architecture", "estimation", "pricing", "proposal")}
    out = []

    def add(g, name, cond, detail=""):
        out.append((g, name, bool(cond), str(detail)[:200]))

    # ---- understanding
    add("understanding", "due date", norm(exp["due"]) in norm(d.get("due_date", "")), d.get("due_date"))
    b = (prof.get("commercial") or {}).get("budget") or meta.get("budget") or {}
    add("understanding", "budget ceiling", b and abs(float(b.get("high") or 0) - exp["budget_high"]) <= exp["budget_high"] * 0.01 and
        (b.get("currency") or "") == exp["currency"], b)
    ev = prof.get("evaluation") or [{"weight": e.get("weight")} for e in meta.get("evaluation_criteria", [])]
    weights = sorted(int(e["weight"]) for e in ev if e.get("weight"))
    add("understanding", "evaluation weights", weights == sorted(exp["weights"]), weights)
    est, pr = st["estimation"], st["pricing"]
    term = prof.get("term") or {}
    total = exp["build_months"] + exp["transition_months"] + exp["run_months"]
    add("understanding", "run period (months)", (est.get("run_months") or 0) == exp["run_months"] or
        (exp["run_months"] == 0 and not est.get("run_months")), f"run={est.get('run_months')} want {exp['run_months']}")
    add("understanding", "whole contract (months)", (est.get("duration_months") or 0) == total, f"{est.get('duration_months')} want {total}")
    if exp["transition_months"]:
        tw = next((p.get("weeks", 0) for p in est.get("phases", []) if "transition" in p.get("name", "").lower()), 0)
        add("understanding", "transition period", abs(tw - exp["transition_months"] * 4.33) <= 1.5, f"{tw} weeks want {exp['transition_months']} months")
    tagged = {norm(t) for r in reqs for t in (r.get("technologies") or [])}
    tagged |= {norm(t.get("name", "")) for t in prof.get("technologies", []) if isinstance(t, dict)}
    hit = [t for t in exp["techs"] if any(norm(t) in x or x in norm(t) for x in tagged if len(x) > 2)]
    add("understanding", "named technologies tagged", len(hit) >= 0.8 * len(exp["techs"]), f"{len(hit)}/{len(exp['techs'])}: missing {sorted(set(exp['techs']) - set(hit))}")

    # ---- bid decision
    gaps = st["gaps"]
    add("decision", "verdict", gaps.get("verdict") in exp["verdict_ok"], f"{gaps.get('verdict')} want one of {sorted(exp['verdict_ok'])}")
    if exp["gates_fail"]:
        gates = {g.get("ref"): g.get("status") for g in gaps.get("gates", [])}
        add("decision", "failed mandatory gates named", all(gates.get(g) == "fail" for g in exp["gates_fail"]), gates)

    # ---- team
    team = est.get("team", [])
    roles = " | ".join(f"{t.get('role', '')} {t.get('responsibility', '')}".lower() for t in team)
    for fam in exp["role_families"]:
        add("team", f"role for /{fam}/", re.search(fam, roles), [t.get("role") for t in team])
    zero = [(t["role"], p["code"]) for t in team for p in t.get("assigned", []) if (p.get("fit") or 0) <= 0]
    add("team", "nobody placed without the skills", not zero, zero)
    avail = {p["code"]: p["availability"] / 100 for p in F.PEOPLE}
    load: dict = {}
    for t in team:
        ppl = t.get("assigned", [])
        for p in ppl:
            per = p.get("fte") if p.get("fte") is not None else t["fte"] / max(1, len(ppl) + (t.get("unfilled") or 0))
            k = (t.get("phase"), p["code"])
            load[k] = load.get(k, 0) + per
    over = {f"{k[1]}@{k[0]}": round(v, 2) for k, v in load.items() if v > avail.get(k[1], 1) + 0.01}
    add("team", "nobody booked past capacity", not over, over)

    # ---- proposal
    r = c.get(f"/api/deals/{did}/download/proposal", headers=h)
    prop = docx_text(r.content) if r.status_code == 200 else ""
    add("proposal", "proposal produced", len(prop) > 500, r.status_code)
    # Relevant Experience lists real projects by their real names, and an answer may name its own evidence: both are
    # checked separately below. Everything else must not borrow another domain's wording.
    body = re.sub(r"\n\d+\.\s*Relevant Experience\n.*?(?=\n\d+\.\s+[A-Z])", "\n", prop, flags=re.S | re.I)
    for name in [x["name"] for x in F.CAPABILITIES] + [x["title"] for x in F.CASE_STUDIES] + [x["name"] for x in F.ACCELERATORS]:
        body = body.replace(name, " ")
    foreign = [w for w in F.FOREIGN_TERMS if re.search((r"\b" + re.escape(w) + r"\b"), body, 0 if w.isupper() else re.I)
               and not re.search(re.escape(w), src, re.I)]
    add("proposal", "no wording from other domains", not foreign, foreign)
    names = {x["name"]: "Capability" for x in F.CAPABILITIES} | {x["title"]: "Case study" for x in F.CASE_STUDIES} | {x["name"]: "Accelerator" for x in F.ACCELERATORS}
    unsupported = []
    for q in reqs:
        txt = q.get("response") or ""
        ev = {e.get("name") for e in (q.get("match") or {}).get("evidence", [])}
        unsupported += [f"{q.get('source_ref')}: {n}" for n in names if n.lower() in txt.lower() and n not in ev]
    add("proposal", "answers cite only their own evidence", not unsupported, unsupported[:4])
    shown = re.search(r"\n\d+\.\s*Relevant Experience\n(.*?)(?=\n\d+\.\s+[A-Z])", prop, flags=re.S | re.I)
    rel_bad = []
    if shown:
        exp_t = {norm(t) for t in exp["techs"]}
        for cs in F.CASE_STUDIES:
            if cs["title"] in shown.group(1):
                from app.services.validation import same_industry
                if not ({norm(t) for t in cs["technologies"]} & exp_t or any(norm(t) in norm(src) for t in cs["technologies"])
                        or same_industry(cs["industry"], d.get("industry") or "")):
                    rel_bad.append(cs["title"])
    add("proposal", "case studies shown are relevant", not rel_bad, rel_bad)
    neg = re.compile(r"\b(not|no|without|partner|pursu|obtain|working towards)\w*", re.I)
    claims = []
    for q in reqs:
        for sent in re.split(r"(?<=[.!?])\s+", q.get("response") or ""):
            for cl in exp.get("not_held", []):
                if cl.lower() in sent.lower() and not neg.search(sent):
                    claims.append(f"{q.get('source_ref')}: {cl}")
    add("proposal", "no claim to credentials the company lacks", not claims, claims)
    internal = [p for p in F.INTERNAL_PHRASES if p.lower() in prop.lower()]
    add("proposal", "no internal notes", not internal, internal)
    by_text: dict = {}
    for q in reqs:
        txt = (q.get("response") or "").strip()
        if len(txt) > 80:
            by_text.setdefault(txt, set()).add(norm(q.get("text"))[:80])
    dup = [t[:60] for t, qs in by_text.items() if len(qs) > 1]
    add("proposal", "no answer reused for different requirements", not dup, dup)
    have = library_terms()
    bad = [ch.get("choice") for ch in st["architecture"].get("choices", []) if ch.get("basis") == "Company strength"
           and not any(t in norm(ch.get("choice")) for t in have if len(t) > 3)]
    add("proposal", "'company strength' only with evidence", not bad, bad)

    # ---- commercial
    add("commercial", "priced over the whole contract", (pr.get("contract_months") or est.get("duration_months") or 0) == total,
        f"{pr.get('contract_months') or est.get('duration_months')} want {total}")
    lines = pr.get("lines", []) + pr.get("other_lines", [])
    kinds = {(l.get("kind") or "labour") for l in lines}
    if exp["licences"]:
        add("commercial", "licence / product line", kinds & {"licence", "product"}, sorted(kinds))
    if exp["partner"]:
        add("commercial", "partner line", "partner" in kinds, sorted(kinds))
    return out


def run(mode: str) -> dict:
    os.environ.pop("RF_GENERALISED_DEFAULT", None)
    results = {}
    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.post("/api/auth/register", json={"company_name": f"Kestrel Test Works {mode}", "name": "Asha Admin",
                                                "email": f"admin-{mode}@domains.example", "password": PW})
        assert r.status_code == 200, r.text
        h = {"Authorization": "Bearer " + r.json()["token"]}
        r = c.put("/api/company", json={"about": "IT services company, 140 people, Hyderabad.", "headcount": 140,
                                        "settings": {"generalised_response": mode == "on"}}, headers=h)
        assert r.status_code == 200, r.text
        for kind, rows in (("capabilities", F.CAPABILITIES), ("skills", F.PEOPLE), ("certifications", F.CERTIFICATIONS),
                           ("case_studies", F.CASE_STUDIES), ("accelerators", F.ACCELERATORS), ("rates", F.RATES)):
            for row in rows:
                rr = c.post(f"/api/library/{kind}", json=row, headers=h)
                assert rr.status_code == 200, (kind, rr.text[:200])
        # approved answers from earlier deals, as the library holds them after a few proposals
        from app.db import SessionLocal
        from app.models import AnswerEntry, Tenant
        with SessionLocal() as db:
            tid = db.query(Tenant).filter(Tenant.name == f"Kestrel Test Works {mode}").one().id
            for q, a in F.OLD_ANSWERS:
                db.add(AnswerEntry(tenant_id=tid, question=q, answer=a, category="Functional", origin="ai", approved_by="QA", outcome="won"))
            db.commit()
        for dom in F.DOMAINS:
            fname, data = F.rfp_bytes(dom)
            t0 = time.time()
            r = c.post("/api/deals", files={"file": (fname, data)}, data={"confidential": "false", "ai_ack": "true"}, headers=h)
            assert r.status_code == 200, r.text[:300]
            did = r.json()["id"]
            while time.time() - t0 < 300:
                d = c.get(f"/api/deals/{did}", headers=h).json()
                if d["status"] != "processing":
                    break
                time.sleep(0.4)
            checks = score_domain(c, h, dom, did)
            results[dom] = {"seconds": round(time.time() - t0, 1), "status": d["status"], "checks": checks,
                            "score": round(100 * sum(1 for x in checks if x[2]) / max(1, len(checks)))}
    return results


def report(mode: str, res: dict) -> None:
    print(f"\n==== mode: switch {mode}")
    for dom, r in res.items():
        print(f"-- {dom}: {r['score']}%  ({sum(1 for x in r['checks'] if x[2])}/{len(r['checks'])} checks, {r['seconds']}s, {r['status']})")
        for g, name, ok_, detail in r["checks"]:
            if not ok_:
                print(f"   FAIL [{g}] {name}: {detail}")
    allc = [x for r in res.values() for x in r["checks"]]
    print(f"== overall ({mode}): {round(100 * sum(1 for x in allc if x[2]) / max(1, len(allc)))}% — "
          f"{sum(1 for x in allc if x[2])} passed, {sum(1 for x in allc if not x[2])} failed")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="both", choices=["off", "on", "both"])
    ap.add_argument("--json", default="")
    ap.add_argument("--strict", action="store_true")
    a = ap.parse_args()
    out = {}
    for m in (["off", "on"] if a.mode == "both" else [a.mode]):
        out[m] = run(m)
        report(m, out[m])
    if a.json:
        with open(a.json, "w") as f:
            json.dump(out, f, indent=1, default=str)
    if a.strict:
        bad = [x for r in out.get("on", out.get("off", {})).values() for x in r["checks"] if not x[2]]
        sys.exit(1 if bad else 0)
