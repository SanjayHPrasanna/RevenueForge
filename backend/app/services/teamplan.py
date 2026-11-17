"""Scope-to-roles team planning and constraint-based people matching (generalised pipeline).

The team comes from the RFP, not from a template per engagement type:
  - technical roles: one per specialism the delivery requirements need. A specialism is named by the company's own job titles
    when someone in the library holds the requirement's technologies ("Network Engineer" for FortiGate + BGP), by the role
    the RFP itself names ("Field engineers shall attend..."), and otherwise by the work area ("Security Engineer").
  - service roles: a named operations centre or desk the RFP asks the bidder to run ("Security Operations Centre",
    "Network Operations Centre") becomes analyst rows by tier (L1/L2/L3 when the RFP says so), sized by shift arithmetic
    for 24x7 (a seat = fte_per_24x7_seat FTE, a company setting) or by business hours.
  - staff conditions from the eligibility list ("The SOC lead shall hold CISSP and have 10 years...") become a role with
    hard constraints, or constraints on the role they name.
  - management and design authority stay: an engagement/project manager and an architect sized to the team.
An AI proposal, when available, is accepted only after the same checks (every delivery requirement served, 24x7 rows sized
by shifts, staff conditions kept); otherwise the rules plan is used.

People are matched by constraint and score: required certificates and years are hard filters; skill overlap (open vocabulary)
and title similarity score; free capacity = availability minus commitments on other deals minus what this deal already uses
in the same phase. Nobody is placed with no relevant skill or title, and a role nobody qualifies for stays open.
"""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict

from . import knowledge as K

SENIORITY_RE = re.compile(r"\b(senior|sr\.?|junior|jr\.?|principal|staff|associate|chief|trainee|graduate)\b\s*", re.I)
STANDARD_RE = re.compile(r"\b(ISO|IEC|SOC\s?[12]|CMMI|PCI|OWASP|WCAG|MITRE|NIST|CIS|ITIL|ASVS|GDPR|HIPAA|802\.1X|Cyber Essentials)\b", re.I)
ROLE_NOUNS = r"(engineers?|analysts?|technicians?|developers?|administrators?|architects?|consultants?|testers?|leads?|managers?|specialists?|officers?|operators?)"
# a role the RFP names as the one doing the work: "Field engineers shall attend...", "L3 analysts must hold..." (active voice,
# so "access for administrators shall be managed" is not read as a role)
TEXT_ROLE_RE = re.compile(r"\b((?:[A-Za-z0-9/&+-]+\s+){0,2})" + ROLE_NOUNS + r"\s+(?:shall|must|will|should|are to|need to)\s+(?!be\b|not\b)", re.I)
SERVICE_TEXT_RE = re.compile(r"\b(24\s?x\s?7|8\s?x\s?5|business hours|round[- ]the[- ]clock|on-call|incidents?|managed (?:[a-z]+ )?(?:operations|services)|"
                             r"operate|monitor(?:ing|ed)?|service desk|support (?:services?|desk|team|hours|window)|(?:l[123]|application|technical|production|post[- ]go[- ]live) support|"
                             r"faults?|break[- ]?fix|attend\w*|warranty)\b", re.I)
WARRANTY_RE = re.compile(r"\b(warranty|defects?|bug ?fix\w*|hypercare)\b", re.I)
OPS_NAME_RE = re.compile(r"\b([A-Za-z]+)\s+operations\b", re.I)
CONDITION_SUBS = {"Standards & Certifications", "Team & Experience", "Regulatory", "Information Security Policy", "Data Protection & Privacy"}
CENTRE_RE = re.compile(r"\b((?:[A-Z][A-Za-z&-]*\s+){0,3}(?:Operations\s+Cent(?:re|er)|Service\s+Desk|Help\s?desk|Command\s+Cent(?:re|er)|Control\s+Room))\b")
TIER_RE = re.compile(r"\bL([1-3])\b")
WORD_STOP = {"the", "a", "an", "and", "or", "of", "for", "all", "each", "our", "any", "bidder", "bidders", "client", "clients", "shall",
             "must", "will", "be", "with", "within", "who", "that", "its", "their", "dedicated", "named", "qualified", "experienced",
             "certified", "provide", "build", "deliver", "run", "operate", "supply", "install", "replace"}
MGMT = {"Engagement Manager", "Project Manager", "Programme Manager", "Program Manager", "Delivery Manager", "Service Delivery Manager"}
WS_AREA = {  # work area -> generic role when nobody in the library and nothing in the RFP names one
    "Integration engineering": "Integration Engineer", "Application engineering": "Software Engineer", "Data & reporting": "Data Engineer",
    "Quality engineering": "QA Engineer", "Platform & continuity": "Platform Engineer", "DevOps & release": "DevOps Engineer",
    "Security & compliance": "Security Engineer", "Service operations": "Operations Engineer", "Risk intelligence & analytics": "Data Scientist",
    "Architecture & advisory": "Solution Architect", "Transition & knowledge transfer": "Business Analyst", "Programme management": "Project Manager",
}
SERVICE_WS = "Service operations"


# --------------------------------------------------------------------------- small helpers
def _n(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _sing(w: str) -> str:
    if w.lower().endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.lower().endswith("s") and not w.lower().endswith("ss") and len(w) > 3:
        return w[:-1]
    return w


def clean_title(title: str) -> str:
    """'Senior Network Engineers' -> 'Network Engineer'; keeps acronyms as written."""
    t = SENIORITY_RE.sub("", title or "").strip(" -/")
    words = t.split()
    if not words:
        return ""
    words[-1] = _sing(words[-1])
    return " ".join(w if (w.isupper() or any(c.isdigit() for c in w)) else w[:1].upper() + w[1:] for w in words)


def _title_tokens(title: str) -> set[str]:
    return {_sing(w) for w in _n(clean_title(title)).split() if w not in WORD_STOP and len(w) > 1}


def _same(term: str, skill: str) -> bool:
    a, b = _n(term), _n(skill)
    if not a or not b:
        return False
    if a == b:
        return True
    a2 = re.sub(r"^(microsoft|apache|confluent|amazon|aws|google|the)\s+", "", a)
    b2 = re.sub(r"^(microsoft|apache|confluent|amazon|aws|google|the)\s+", "", b)
    if a2 == b2:
        return True
    if K.canonical_tech(term).lower() == K.canonical_tech(skill).lower():
        return True
    pat = lambda x: r"(?<![a-z0-9])" + re.escape(x) + r"(?![a-z0-9])"
    # a skill named inside the term counts ("Kubernetes" for "Azure Kubernetes Service"); a term inside a longer skill name
    # only when the term is itself specific (two words or more): "Azure" alone is not "Azure Data Factory"
    # (a vendor prefix stripped off leaves a generic word: "Microsoft Azure" -> "azure" doesn't make anyone an Azure Migrate expert)
    return (len(b2) > 3 and (b2 == b or " " in b2) and re.search(pat(b2), a) is not None) or \
        (len(a2) > 3 and " " in a2 and re.search(pat(a2), b) is not None)


def is_skill_term(t: str) -> bool:
    return bool(t) and t not in K.COMMODITY_TECH and not STANDARD_RE.search(t)


def person_skill_hits(e: dict, terms: list[str]) -> list[tuple[str, int]]:
    out = []
    for t in terms:
        lvl = max((s.get("level", 3) for s in e.get("skills", []) if _same(t, s.get("name", ""))), default=0)
        if lvl:
            out.append((t, lvl))
    return out


def _has_cert(e: dict, cert: str) -> bool:
    toks = {w for w in _n(cert).split() if len(w) > 2}
    for c in e.get("certifications", []):
        name = c if isinstance(c, str) else (c or {}).get("name", "")
        cn = _n(name)
        if _n(cert) in cn or (toks and toks <= set(cn.split())):
            return True
    return False


def _title_fit(person_title: str, role: str) -> int:
    """2 = the same job, 1 = a close one (shared title word or a known equivalent), 0 = unrelated."""
    pt, rt = clean_title(person_title), clean_title(role)
    if _n(pt) == _n(rt):
        return 2
    if K.normalize_role(pt) == K.normalize_role(rt) and K.normalize_role(rt) not in ("Software Engineer",):
        return 1
    if rt in MGMT and (pt in MGMT or "manager" in _n(pt)):
        return 1
    from .solution import ROLE_EQUIV
    if K.normalize_role(pt) in ROLE_EQUIV.get(K.normalize_role(rt), ()):
        return 1
    shared = (_title_tokens(pt) & _title_tokens(rt)) - {"engineer", "specialist", "consultant", "manager", "lead", "officer", "analyst"}
    return 1 if shared else 0


# --------------------------------------------------------------------------- commitments on other deals
def commitments(db, tenant_id: str, exclude_deal: str = "") -> dict[str, float]:
    """FTE each person already carries on other live deals: won deals count in full, deals still being bid count half (they
    may not be won). Lost, no-bid and cancelled deals free their people. Read from the Assignment table."""
    from sqlalchemy import select
    from ..models import Assignment, Deal
    weight = {"won": 1.0, "submitted": 0.5, "in_review": 0.5, "processing": 0.5, "draft": 0.5}
    out: dict[str, float] = defaultdict(float)
    rows = db.execute(select(Assignment, Deal.status).join(Deal, Deal.id == Assignment.deal_id)
                      .where(Assignment.tenant_id == tenant_id, Assignment.deal_id != exclude_deal)).all()
    peak: dict[tuple, float] = defaultdict(float)
    for a, status in rows:
        w = weight.get(status or "", 0.0)
        if w:
            peak[(a.deal_id, a.employee_code, a.phase)] += a.fte * w
    per_deal: dict[tuple, float] = defaultdict(float)
    for (deal_id, code, _phase), v in peak.items():
        per_deal[(deal_id, code)] = max(per_deal[(deal_id, code)], v)  # a deal's phases run one after another
    for (_d, code), v in per_deal.items():
        out[code] += v
    return dict(out)


def sync_assignments(db, deal, team: list[dict] | None = None) -> int:
    """Rewrite this deal's rows in the Assignment table from its team plan (who is booked, at what FTE, per phase).
    team: the estimation's team list; read from the stored estimation stage when not given."""
    from sqlalchemy import delete, select
    from ..models import Assignment, DealStage
    db.execute(delete(Assignment).where(Assignment.deal_id == deal.id))
    if team is None:
        st = db.scalar(select(DealStage).where(DealStage.deal_id == deal.id, DealStage.stage == "estimation"))
        team = (st.data or {}).get("team", []) if st else []
    n = 0
    for t in team:
        ppl = t.get("assigned", [])
        for p in ppl:
            fte = p.get("fte")
            if fte is None:
                fte = t.get("fte", 0) / max(1, len(ppl) + (t.get("unfilled") or 0))
            db.add(Assignment(tenant_id=deal.tenant_id, deal_id=deal.id, employee_code=p.get("code", ""), role=t.get("role", "")[:120],
                              phase=t.get("phase", "")[:40], fte=float(fte), months=int(t.get("months") or 0)))
            n += 1
    return n


def backfill_assignments(db, tenant_id: str) -> int:
    """Deals estimated before the Assignment table existed get their rows written once, so their people count as committed."""
    from sqlalchemy import select
    from ..models import Assignment, Deal, DealStage
    have = set(db.scalars(select(Assignment.deal_id).where(Assignment.tenant_id == tenant_id)).all())
    n = 0
    for deal, st in db.execute(select(Deal, DealStage).join(DealStage, DealStage.deal_id == Deal.id)
                               .where(Deal.tenant_id == tenant_id, DealStage.stage == "estimation")).all():
        if deal.id in have or not (st.data or {}).get("team"):
            continue
        n += sync_assignments(db, deal, st.data["team"])
    return n


# --------------------------------------------------------------------------- role planning (rules)
GENERIC_AREAS = {"Software Engineer", "Integration Engineer", "Platform Engineer"}


def _specialism(r: dict, kb, techs: list[str], titles: list[str], service: bool, domain: str = "") -> tuple[str, str]:
    """(role title, how it was named) for one delivery requirement, most specific source first."""
    best, best_score = None, 0
    for e in kb.employees:
        score = sum(l for _, l in person_skill_hits(e, techs))
        if score > best_score and clean_title(e.get("role", "")) not in MGMT and "architect" not in _n(e.get("role", "")):
            best, best_score = e, score
    if best is not None:  # someone in the company already does this work: their job title names it
        return clean_title(best.get("role", "")), "library"
    text = r.get("text", "")
    words = set(_n(text).split())
    for t in titles:  # the work names a specialism the team already has ("...network access control" -> Network Engineer)
        distinct = _title_tokens(t) - {"engineer", "analyst", "specialist", "consultant", "developer", "administrator", "technician", "lead"}
        if distinct and distinct <= words:
            return t, "library"
    m = TEXT_ROLE_RE.search(text)
    if m:
        qual = [w for w in m.group(1).split() if w.lower() not in WORD_STOP]
        noun = m.group(2)
        if noun.lower() not in ("lead", "leads", "manager", "managers") or qual:
            return clean_title(" ".join(qual + [noun])), "rfp"
    if service:
        o = OPS_NAME_RE.search(text)
        if o and o.group(1).lower() not in WORD_STOP | {"managed", "service", "it"}:
            return clean_title(f"{o.group(1)} Operations Engineer"), "rfp"
        return "Operations Engineer", "area"
    area = WS_AREA.get(r.get("workstream", ""), "Software Engineer")
    if area in MGMT or (area == "Business Analyst" and techs):
        area = "Software Engineer"  # unclassified technical work is engineering, not management
    if domain and area in GENERIC_AREAS:
        area = f"{domain} Engineer"  # the RFP's own subject ("Security Operations Centre" -> Security Engineer)
    return area, "area"


def _service_lines(reqs: list[dict], profile: dict) -> list[dict]:
    """Each operations centre or desk the bidder must run, with its coverage and tiers."""
    out: dict[str, dict] = {}
    cov_all = (profile.get("service") or {}).get("coverage") or ""
    for r in reqs:
        t = r.get("text", "")
        m = CENTRE_RE.search(t)
        if not m:
            continue
        name = re.sub(r"\s+", " ", m.group(1)).strip()
        name = re.sub(r"^(?:a|an|the|run|operate|provide)\s+", "", name, flags=re.I)
        key = _n(name)
        line = out.setdefault(key, {"name": name, "tiers": set(), "coverage": "", "refs": [], "techs": []})
        line["tiers"] |= {int(x) for x in TIER_RE.findall(t)}
        if re.search(r"24\s?x\s?7|24/7|round[- ]the[- ]clock", t, re.I):
            line["coverage"] = "24x7"
        line["refs"].append(r.get("source_ref") or r.get("code", ""))
        line["techs"] += [x for x in r.get("technologies", []) if is_skill_term(x)]
    for line in out.values():
        if not line["coverage"]:
            line["coverage"] = cov_all or "business hours"
    return list(out.values())


def _staff_conditions(profile: dict) -> list[dict]:
    out = []
    for g in profile.get("eligibility", []):
        if g.get("kind") != "staff":
            continue
        t = g.get("text", "")
        m = re.match(r"^\s*(?:the|all|each|any)?\s*((?:[A-Za-z0-9/&-]+\s){0,3}?" + ROLE_NOUNS + r")\b", t, re.I)
        role = clean_title(m.group(1)) if m else ""
        certs = [c.strip() for c in re.findall(r"\b([A-Z][A-Z0-9+]{2,}(?:\s?[A-Z0-9+]{2,})?)\b", t) if c not in ("SOC", "IT", "ISO", "AND", "OR")]
        yrs = re.search(r"(\d{1,2})\+?\s+years", t)
        any_of = bool(re.search(r"\b[A-Z]{3,}\s+or\s+[A-Z]{3,}", t))
        out.append({"ref": g.get("ref", ""), "role": role, "certs": certs, "any_cert": any_of, "min_years": int(yrs.group(1)) if yrs else 0,
                    "tiers": {int(x) for x in TIER_RE.findall(t)}, "mandatory": g.get("mandatory", True), "text": t})
    return out


def _round_q(x: float) -> float:
    return max(0.25, round(x * 4) / 4)


def plan_roles(reqs: list[dict], profile: dict, phases: list[tuple[str, float]], onsite_ratio: float, fte_per_seat: float,
               kb) -> tuple[list[dict], list[str]]:
    """phases: [(phase name, months)] in order, e.g. [("Transition", 3), ("Run", 36)] or [("Build", 9), ("Run", 12)].
    Returns role rows {role, fte, location, responsibility, phase, months, skills, certs, any_cert, min_years, serves} and notes."""
    notes: list[str] = []
    build = [p for p in phases if p[0] == "Build"]
    run = [p for p in phases if p[0] == "Run"]
    transition = [p for p in phases if p[0] == "Transition"]
    delivery = [r for r in reqs if r.get("workstream") not in ("Bid & contract", "", None)]
    services = _service_lines(delivery, profile)
    svc_refs = {ref for s in services for ref in s["refs"]}
    staff = _staff_conditions(profile)
    staff_refs = {s["ref"] for s in staff}

    gate_refs = {g.get("ref") for g in profile.get("eligibility", [])}
    titles = []
    for e in kb.employees:
        t = clean_title(e.get("role", ""))
        if t and t not in MGMT and "architect" not in _n(t) and t not in titles:
            titles.append(t)
    single_service = services[0] if len(services) == 1 else None
    domain = ""
    if services:
        w = services[0]["name"].split()[0]
        if w.lower() not in WORD_STOP | {"service", "help", "helpdesk", "operations", "command", "control", "it"}:
            domain = clean_title(w)
    groups: dict[str, dict] = {}
    for r in delivery:
        ref = r.get("source_ref") or r.get("code", "")
        if ref in svc_refs or ref in staff_refs or ref in gate_refs:
            continue  # a service line, a staff condition or an eligibility condition: handled on its own, not work for a role
        if r.get("subcategory") in CONDITION_SUBS and r.get("category") != "Functional":
            continue  # an obligation on the company (certification, policy, regulation), met by the plan, not a role
        is_service = r.get("workstream") == SERVICE_WS or (bool(SERVICE_TEXT_RE.search(r.get("text", ""))) and r.get("category") != "Compliance")
        if is_service and single_service is not None and not TEXT_ROLE_RE.search(r.get("text", "")) and \
                r.get("subcategory") in ("Service Levels", "Support & Incident Management", "Monitoring & Operations"):
            single_service["refs"].append(ref)  # a service level of the one centre the RFP asks for: that centre's team meets it
            continue
        techs = [t for t in r.get("technologies", []) if is_skill_term(t)]
        title, how = _specialism(r, kb, techs, titles, is_service, domain)
        g = groups.setdefault((title, is_service), {"title": title, "days": 0.0, "skills": [], "refs": [], "how": how, "service": is_service,
                                                     "warranty": False})
        g["days"] += float(r.get("effort_days") or 0)
        g["skills"] += [t for t in techs if t not in g["skills"]]
        g["refs"].append(ref)
        if is_service and WARRANTY_RE.search(r.get("text", "")):
            g["warranty"] = True

    rows: list[dict] = []
    # work the gap plan gives to a partner is not staffed in-house: it is kept as a "partner" row (the size of the work, for
    # pricing) and, for a partner-run service, one in-house manager oversees the partner
    partner_refs = {r.get("source_ref") or r.get("code", "") for r in reqs if (r.get("gap") or {}).get("recommended") == "Partner"}
    overseen: set[tuple] = set()

    def add(role, fte, loc, resp, phase, months, skills=(), refs=(), certs=(), any_cert=False, min_years=0):
        if fte <= 0:
            return
        refs_ = [x for x in refs if x][:20]
        partner = bool(refs_) and all(x in partner_refs for x in refs_) and not certs and not min_years
        rows.append({"role": role, "fte": round(fte, 2), "location": loc, "responsibility": resp[:160], "phase": phase, "months": months,
                     "skills": list(skills)[:12], "serves": refs_, "certs": list(certs), "any_cert": any_cert,
                     "min_years": min_years, "partner": partner})
        if partner and (phase, tuple(refs_)) not in overseen and fte >= 2:
            overseen.add((phase, tuple(refs_)))
            rows.append({"role": "Partner Service Manager", "fte": 0.5, "location": loc, "phase": phase, "months": months,
                         "responsibility": f"Oversees the partner delivering {', '.join(refs_[:4])}: SLAs, reporting, escalation"[:160],
                         "skills": [], "serves": refs_, "certs": [], "any_cert": False, "min_years": 0, "partner": False})

    def resp_for(g, title):
        what = ", ".join(g["skills"][:4])
        refs = ", ".join(g["refs"][:6])
        return f"{title} work{(' in ' + what) if what else ''} ({refs})"

    # build phase: technical specialisms sized by effort, plus PM, architect and QA overheads
    if build:
        bm = build[0][1] or 6
        fte_days = bm * 21
        total = sum(g["days"] for g in groups.values() if not g["service"])
        for _k, g in sorted(groups.items(), key=lambda kv: -kv[1]["days"]):
            title = g["title"]
            if g["service"] and run:
                continue
            fte = max(0.5, round(g["days"] / fte_days * 2) / 2)
            add(title, fte, "Offshore", resp_for(g, title), "Build", bm, g["skills"], g["refs"])
        pm_fte = 1.0  # a dedicated project manager and architect for the whole build
        on = _round_q(pm_fte * onsite_ratio) if onsite_ratio >= 0.25 else 0
        add("Project Manager", pm_fte - on, "Offshore", "Plan, risks, reporting and governance", "Build", bm)
        if on:
            add("Project Manager", on, "Onsite", "Client-facing lead", "Build", bm)
        add("Solution Architect", 1.0, "Offshore", "Design authority across the build", "Build", bm)
        if not any("test" in _n(g["title"]) or "qa" in _n(g["title"]).split() for g in groups.values()):
            add("QA Engineer", max(0.5, round(total * 0.22 / fte_days * 2) / 2), "Offshore", "Functional, performance and acceptance testing", "Build", bm)

    # transition: a small core team takes over the service before the run starts
    if transition:
        tm = transition[0][1]
        add("Engagement Manager", 1.0, "Onsite" if onsite_ratio >= 0.3 else "Offshore", "Transition lead: knowledge transfer, access and baselining", "Transition", tm)
        add("Solution Architect", 0.5, "Offshore", "Baseline the platform and the runbooks", "Transition", tm)
        for sv in services:  # the service team joins during transition to shadow and take over (a third of its run size)
            seats = len(sv["tiers"]) or 1
            run_fte = (fte_per_seat if sv["coverage"] == "24x7" else 1.25) * seats
            add(f"{sv['name']} Analyst", _round_q(run_fte / 3), "Offshore", f"{sv['name']}: shadowing and service take-over", "Transition", tm,
                sv["techs"], sv["refs"])

    # run phase: the services the RFP names, sized by coverage and tiers; technical specialisms for steady-state work
    if run:
        rm = run[0][1]
        for s in services:
            tiers = sorted(s["tiers"]) or [0]
            for tier in tiers:
                tname = f"{s['name']} Analyst" + (f" (L{tier})" if tier else "")
                is_247 = s["coverage"] == "24x7"
                top = tier and tier == max(tiers) and len(tiers) > 1
                if is_247 and not top:
                    fte, how = fte_per_seat, f"one 24x7 seat ({fte_per_seat:g} FTE by shift rota)"
                else:
                    fte, how = (1.0, "escalation tier, business hours with on-call") if top else (2.0 if not is_247 else fte_per_seat, "business-hours cover" if not is_247 else "24x7 seat")
                add(tname, fte, "Offshore", f"{s['name']}: {how}", "Run", rm, s["techs"], s["refs"])
        warranty_refs = []
        for _k, g in sorted(groups.items(), key=lambda kv: -kv[1]["days"]):
            title = g["title"]
            if build and not g["service"]:
                continue  # built in the build phase; steady-state changes ride the fix rows below
            if g["service"]:
                if build and g["warranty"] and g["how"] == "area":
                    warranty_refs += g["refs"]  # defect fixing after a build is done by the people who built it
                    continue
                fte = 1.0 if any(s["coverage"] == "24x7" for s in services) else 1.25  # one seat in business hours, plus cover
                add(title, fte, "Offshore", resp_for(g, title), "Run", rm, g["skills"], g["refs"])
            else:
                add(title, max(0.5, min(2.0, round(g["days"] / (rm * 21) * 4 * 2) / 2)), "Offshore", resp_for(g, title) + "; steady-state changes", "Run", rm,
                    g["skills"], g["refs"])
        if build:  # after a build, one engineer per built specialism keeps fixes and changes flowing (largest first, at most three)
            for _k, g in [kv for kv in sorted(groups.items(), key=lambda kv: -kv[1]["days"]) if not kv[1]["service"]][:3]:
                add(g["title"], 0.5, "Offshore", f"Fixes and enhancements for {', '.join(g['skills'][:3]) or g['title'].lower()}"
                    + (f"; covers {', '.join(warranty_refs[:4])}" if warranty_refs else ""), "Run", rm, g["skills"], g["refs"] + warranty_refs)
        team_fte = sum(r["fte"] for r in rows if r["phase"] == "Run" and not r.get("partner"))
        add("Engagement Manager", 1.0 if team_fte >= 6 else 0.5, "Onsite" if onsite_ratio >= 0.3 else "Offshore",
            "Service delivery manager: outcomes, SLAs and governance", "Run", rm)
        add("Solution Architect", 0.5 if team_fte >= 4 else 0.25, "Offshore", "Design authority, upgrades and capacity planning", "Run", rm)

    # staff conditions: constraints on the role they name, or a role of their own
    for s in staff:
        target_phase = "Run" if run else "Build" if build else (phases[0][0] if phases else "Delivery")
        months = next((m for p, m in phases if p == target_phase), 0)
        cand = [r for r in rows if s["role"] and (_title_tokens(s["role"]) & _title_tokens(r["role"])) - {"engineer", "analyst"} or
                (s["tiers"] and any(f"(L{t})" in r["role"] for t in s["tiers"]))]
        if s["tiers"]:
            cand = [r for r in rows if any(f"(L{t})" in r["role"] for t in s["tiers"])] or cand
        if cand:
            for r in cand:
                r["certs"] = sorted(set(r["certs"]) | set(s["certs"]))
                r["any_cert"] = s["any_cert"]
                r["min_years"] = max(r["min_years"], s["min_years"])
                r["responsibility"] = (r["responsibility"] + f"; must meet {s['ref']}")[:160]
        else:
            add(s["role"] or "Lead", 1.0, "Offshore", f"Required by {s['ref']}: {s['text'][:90]}", target_phase, months,
                certs=s["certs"], any_cert=s["any_cert"], min_years=s["min_years"], refs=[s["ref"]])
            notes.append(f"{s['ref']} asks for a named {s['role'] or 'lead'}: a dedicated role was added.")
    # split part of client-facing leadership onsite when the region expects it
    if onsite_ratio >= 0.3:
        for r in rows:
            if r["role"] in MGMT and r["location"] == "Offshore" and r["fte"] >= 1:
                r["location"] = "Onsite"
    return rows, notes


# --------------------------------------------------------------------------- AI proposal, checked
AI_SYSTEM = ("You are a delivery director sizing the team for an IT bid. From the RFP facts and requirements, propose the roles the "
             "work needs: role title, phase (from the phases given), FTE, location (Onsite/Offshore), required skills and certificates, "
             "minimum years, and the requirement refs each role serves. Size 24x7 services by shift rota (one 24x7 seat needs about "
             "{seat} FTE). Use titles a real team would use for this domain; do not add roles the scope doesn't need. Return JSON: "
             '{{"roles":[{{"role":"","phase":"","fte":0,"location":"Offshore","skills":[],"certs":[],"min_years":0,"serves":[],"why":""}}]}}')


def plan_key(reqs: list[dict]) -> str:
    import hashlib
    sig = "|".join(f"{r.get('source_ref') or r.get('code')}:{(r.get('text') or '')[:200]}" for r in reqs)
    return hashlib.sha1(sig.encode()).hexdigest()[:16]


def ai_roles(reqs: list[dict], profile: dict, phases: list[tuple[str, float]], fte_per_seat: float) -> dict | None:
    """The AI's raw team proposal (checked separately by check_ai_plan)."""
    from . import llm
    if not llm.is_enabled():
        return None
    lines = [f"{r.get('source_ref') or r.get('code')}: {r.get('text', '')[:220]}" for r in reqs if r.get("workstream") not in ("Bid & contract", "", None)][:60]
    facts = {"phases": [{"name": p, "months": m} for p, m in phases], "service": profile.get("service"), "scope_units": profile.get("scope_units", [])[:15],
             "staff_conditions": [g.get("text") for g in profile.get("eligibility", []) if g.get("kind") == "staff"]}
    prompt = "RFP facts:\n" + json.dumps(facts)[:3000] + "\n\nRequirements:\n" + "\n".join(lines)
    try:
        res = llm.complete_json(AI_SYSTEM.format(seat=fte_per_seat), prompt, max_tokens=4000)
    except Exception:
        return None
    return res if isinstance(res, dict) else None


def ai_plan(reqs: list[dict], profile: dict, phases: list[tuple[str, float]], fte_per_seat: float, rules_rows: list[dict]) -> list[dict] | None:
    raw = ai_roles(reqs, profile, phases, fte_per_seat)
    return check_ai_plan(raw, reqs, profile, phases, fte_per_seat, rules_rows) if raw else None


def check_ai_plan(res, reqs: list[dict], profile: dict, phases: list[tuple[str, float]], fte_per_seat: float, rules_rows: list[dict]) -> list[dict] | None:
    """Accept an AI team only when it holds up: known phases, sane FTE, every delivery requirement served, 24x7 services sized
    by shifts, staff conditions kept. Requirements it leaves out are covered by the matching rules rows."""
    roles = (res or {}).get("roles") if isinstance(res, dict) else None
    if not isinstance(roles, list) or not roles:
        return None
    months = dict(phases)
    out = []
    for x in roles[:40]:
        try:
            role = clean_title(str(x.get("role", "")).strip())[:80]
            ph = str(x.get("phase", "")).strip().title()
            fte = float(x.get("fte", 0))
        except Exception:
            continue
        if not role or ph not in months or not 0.1 <= fte <= 25:
            continue
        out.append({"role": role, "fte": round(_round_q(fte), 2), "location": "Onsite" if str(x.get("location", "")).lower().startswith("on") else "Offshore",
                    "responsibility": str(x.get("why", ""))[:160] or f"{role} work", "phase": ph, "months": months[ph],
                    "skills": [str(s)[:60] for s in (x.get("skills") or [])][:12], "certs": [str(s)[:40] for s in (x.get("certs") or [])][:6],
                    "any_cert": False, "min_years": int(x.get("min_years") or 0), "serves": [str(s) for s in (x.get("serves") or [])][:20]})
    if not out:
        return None
    served = {s for r in out for s in r["serves"]}
    for rr in rules_rows:  # coverage: whatever the AI left out keeps its rules role
        if rr["serves"] and not set(rr["serves"]) & served:
            out.append(dict(rr))
            served |= set(rr["serves"])
    need247: dict[tuple, float] = defaultdict(float)
    for rr in rules_rows:  # shifts and staff conditions are facts, not suggestions
        if "24x7 seat" in rr["responsibility"]:
            need247[(rr["phase"], tuple(sorted(rr["serves"])))] += rr["fte"]
        if rr["certs"] or rr["min_years"]:
            same = [r for r in out if r["phase"] == rr["phase"] and set(r["serves"]) & set(rr["serves"])]
            if not same:
                out.append(dict(rr))
                continue
            for r in same:
                r["certs"] = sorted(set(r["certs"]) | set(rr["certs"]))
                r["any_cert"] = r.get("any_cert") or rr.get("any_cert", False)
                r["min_years"] = max(r["min_years"], rr["min_years"])
    for (phase, serves), fte in need247.items():
        same = [r for r in out if r["phase"] == phase and set(r["serves"]) & set(serves)]
        have = sum(r["fte"] for r in same)
        if not same:
            out += [dict(rr) for rr in rules_rows if rr["phase"] == phase and tuple(sorted(rr["serves"])) == serves]
        elif have < fte - 0.01:
            same[0]["fte"] = round(same[0]["fte"] + fte - have, 2)
            same[0]["responsibility"] = (same[0]["responsibility"] + "; sized for 24x7 shifts")[:160]
    return out


# --------------------------------------------------------------------------- people matching
def assign(kb, rows: list[dict], committed: dict[str, float] | None = None) -> None:
    """Fills rows[i]["assigned"] (each person with the FTE they give this row and a fit score) and rows[i]["unfilled"] in place."""
    committed = committed or {}
    load: dict[tuple, float] = defaultdict(float)  # (phase, code) -> FTE used in this deal

    def free(e, phase):
        cap = (e.get("availability", 100) or 0) / 100 - committed.get(e["code"], 0)
        return max(0.0, round(cap - load[(phase, e["code"])], 2))

    order = sorted(range(len(rows)), key=lambda i: (bool(rows[i]["certs"] or rows[i]["min_years"]), rows[i]["role"] not in MGMT, len(rows[i]["skills"])), reverse=True)
    for i in order:
        row = rows[i]
        if row.get("partner"):
            row["assigned"], row["unfilled"], row["open_fte"], row["headcount"] = [], 0, 0.0, 0
            continue
        need = row["fte"]
        cands = []
        for e in kb.employees:
            if row["min_years"] and (e.get("years") or 0) < row["min_years"]:
                continue
            if row["certs"]:
                held = [c for c in row["certs"] if _has_cert(e, c)]
                if (row["any_cert"] and not held) or (not row["any_cert"] and len(held) < len(row["certs"])):
                    continue
            hits = person_skill_hits(e, row["skills"])
            tf = _title_fit(e.get("role", ""), row["role"])
            if not hits and tf == 0:
                continue  # no relevant skill and an unrelated job: never placed
            if row["skills"] and not hits and tf < 2:
                continue  # a close title alone doesn't carry a role that names technologies
            fit = sum(l for _, l in hits) + 2 * tf
            f = free(e, row["phase"])
            if f < 0.25:
                continue
            cands.append((fit, f, e.get("years", 0), e))
        cands.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        picked = []
        for fit, f, _, e in cands:
            if need <= 0.01:
                break
            give = round(min(f, need, 1.0), 2)
            if give < 0.25:
                continue
            load[(row["phase"], e["code"])] += give
            need -= give
            picked.append({"code": e["code"], "name": e.get("name", ""), "role": e.get("role", ""), "level": e.get("level", ""),
                           "location": e.get("location", ""), "availability": e.get("availability", 100), "fte": give, "fit": fit,
                           "status": "Available" if give >= 0.99 else f"Part-time: {give:g} FTE"})
        row["assigned"] = picked
        row["unfilled"] = max(0, math.ceil(round(need, 2) - 0.01)) if need > 0.01 else 0
        row["open_fte"] = round(max(0.0, need), 2)
        row["headcount"] = len(picked) + row["unfilled"]
