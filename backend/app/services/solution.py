"""Stages 4-6 - Solution Architecture, Effort & Resource Estimation, Pricing & Margin.

Everything here is explainable: each architecture component cites the requirements that drove it,
each workstream lists the requirements it covers, and each price line shows rate, cost and days.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from . import knowledge as K
from .matching import CompanyKB, relevant_accelerators

# =========================================================================== architecture
LAYER_ORDER = ["Channels & consumers", "Experience & APIs", "Integration & orchestration", "Intelligence & decisioning",
               "Core systems & data", "Security & identity", "Operations & service management", "Platform, hosting & continuity"]
EA_DOMAINS = ["Business architecture", "Application architecture", "Data architecture", "Integration architecture",
              "Technology & infrastructure", "Security architecture", "Governance & roadmap"]

TECH_LAYER = {
    "Integration platforms": "Integration & orchestration", "Healthcare standards": "Integration & orchestration",
    "Cloud & infrastructure": "Platform, hosting & continuity", "Fraud & identity intelligence": "Intelligence & decisioning",
    "Security": "Security & identity", "Data & AI": "Core systems & data", "Operations": "Operations & service management",
    "Engineering": "Experience & APIs", "Architecture": "Operations & service management",
}
CORE_SYSTEMS = {"HIS", "LIS", "RIS", "PACS", "EHR/EMR", "SAP", "Salesforce", "Microsoft Dynamics"}
CHANNEL_TECH = {"iOS", "Android", "React", "Angular"}

SUBCAT_COMPONENT = {
    "Monitoring & Operations": ("Operations & service management", "Real-time monitoring, alerting & dashboards"),
    "Service Levels": ("Operations & service management", "SLA-driven incident, problem & change management"),
    "Support & Incident Management": ("Operations & service management", "Service desk & incident response (ITIL)"),
    "Availability & Continuity": ("Platform, hosting & continuity", "High availability, DR & backup validation"),
    "Performance & Scalability": ("Platform, hosting & continuity", "Capacity planning & performance tuning"),
    "Maintainability & Quality": ("Operations & service management", "Version control, CI/CD & release governance"),
    "Security": ("Security & identity", "Encryption, access control & audit logging"),
    "Testing & QA": ("Operations & service management", "Automated interface & regression testing"),
    "Data & Analytics": ("Core systems & data", "Reporting & analytics"),
    "Fraud & Risk Analytics": ("Intelligence & decisioning", "Risk scoring & decision engine"),
    "Transition & Knowledge Transfer": ("Operations & service management", "Transition & knowledge management"),
    "Integration & APIs": ("Integration & orchestration", "Interface routing, mapping & transformation"),
    "Data Protection & Privacy": ("Security & identity", "Privacy controls & data residency"),
}


def build_architecture(reqs: list[dict], kb: CompanyKB, meta: dict) -> dict:
    eng = meta.get("engagement_type", "implementation")
    inv = kb.tech_inventory()
    text_all = " ".join(r["text"] for r in reqs).lower()
    layers: dict[str, dict[str, dict]] = defaultdict(dict)

    def add(layer, name, source, codes, detail=""):
        comp = layers[layer].setdefault(name, {"name": name, "source": source, "requirements": [], "detail": detail})
        comp["requirements"] = sorted(set(comp["requirements"]) | set(codes))[:12]
        if source == "RFP-mandated":
            comp["source"] = source

    tech_reqs = defaultdict(list)
    for r in reqs:
        for t in r.get("technologies", []):
            tech_reqs[t].append(r["code"])

    for t, codes in tech_reqs.items():
        if t in K.COMMODITY_TECH and t not in CORE_SYSTEMS and t not in CHANNEL_TECH:
            continue
        if t in CORE_SYSTEMS:
            add("Core systems & data", t, "Client-owned", codes)
            continue
        if t in CHANNEL_TECH:
            add("Channels & consumers", f"{t} channel", "Client-owned", codes)
            continue
        fam = K.TECH_FAMILY.get(t)
        layer = TECH_LAYER.get(fam, "Integration & orchestration")
        if t in K.PARTNER_PRODUCTS and t not in inv:
            src = "Partner product"
        elif len(codes) >= 2 or re.search(re.escape(t.lower()), text_all):
            src = "RFP-mandated"
        else:
            src = "Proposed"
        add(layer, t, src, codes)

    for r in reqs:
        sc = SUBCAT_COMPONENT.get(r.get("subcategory", ""))
        if sc and r.get("category") in ("Functional", "Non-functional", "Compliance"):
            add(sc[0], sc[1], "Proposed", [r["code"]])

    # Pick the company's own tooling where the RFP leaves the choice open.
    choices = []

    def best_in_family(fam: str, exclude=()):
        cands = [(v["people"] + 3 * len(v["capabilities"]), t) for t, v in inv.items() if K.TECH_FAMILY.get(t) == fam and t not in exclude]
        cands.sort(reverse=True)
        return [t for _, t in cands]

    mandated_integration = [t for t in tech_reqs if K.TECH_FAMILY.get(t) == "Integration platforms"]
    if mandated_integration:
        t = mandated_integration[0]
        v = inv.get(t, {})
        choices.append({"area": "Integration engine", "choice": t, "basis": "Specified in the RFP",
                        "rationale": f"{v.get('people', 0)} engineers with {t} skills" if v.get("people") else f"No in-house {t} skills yet: upskill/hire plan required",
                        "requirements": tech_reqs[t][:8]})
    elif any(r.get("subcategory") == "Integration & APIs" for r in reqs):
        own = best_in_family("Integration platforms")
        if own:
            choices.append({"area": "Integration engine", "choice": own[0], "basis": "Company strength",
                            "rationale": f"{inv[own[0]]['people']} engineers; used in {len(inv[own[0]]['case_studies'])} reference projects",
                            "requirements": [r["code"] for r in reqs if r.get("subcategory") == "Integration & APIs"][:8]})
            add("Integration & orchestration", own[0], "Proposed", [])

    std = [t for t in tech_reqs if K.TECH_FAMILY.get(t) == "Healthcare standards" and t not in CORE_SYSTEMS]
    if std:
        choices.append({"area": "Messaging & interoperability standards", "choice": ", ".join(std), "basis": "Specified in the RFP",
                        "rationale": "Standards-based interfaces across clinical systems", "requirements": sum((tech_reqs[t][:3] for t in std), [])})

    if re.search(r"\bapi", text_all):
        api = [t for t in ("Apigee", "MuleSoft", "Kong", "Azure Integration Services") if t in inv]
        if api:
            choices.append({"area": "API management", "choice": api[0], "basis": "Company strength",
                            "rationale": "Secure, governed exposure of services with OAuth 2.0", "requirements": []})
            add("Experience & APIs", f"{api[0]} API gateway", "Proposed", [])

    ops = [t for t in best_in_family("Operations") if t not in ("ITIL", "Confluence", "Jira")][:2]
    if any(r.get("subcategory") in ("Monitoring & Operations", "Service Levels", "Support & Incident Management") for r in reqs):
        choices.append({"area": "Monitoring & ITSM", "choice": ", ".join(ops) if ops else "Client ITSM + agreed monitoring stack",
                        "basis": "Company strength" if ops else "To confirm",
                        "rationale": "Proactive queue/alert monitoring with SLA reporting and ITIL processes",
                        "requirements": [r["code"] for r in reqs if r.get("subcategory") in ("Monitoring & Operations", "Service Levels")][:8]})
        for t in ops:
            add("Operations & service management", t, "Proposed", [])

    hosting = "On-premises (client data centre)" if re.search(r"on[- ]prem", text_all) else ""
    if re.search(r"\bcloud\b", text_all):
        hosting = (hosting + " or " if hosting else "") + "Managed cloud in an approved region"
    if hosting:
        choices.append({"area": "Hosting", "choice": hosting, "basis": "Per RFP deployment options", "rationale": "Data residency and regulator approval respected", "requirements": []})

    fraud = [t for t in tech_reqs if K.TECH_FAMILY.get(t) == "Fraud & identity intelligence"]
    if fraud:
        own = [t for t in fraud if t in inv]
        partner = [t for t in fraud if t not in inv and t in K.PARTNER_PRODUCTS]
        choices.append({"area": "Risk intelligence engine", "choice": "Partner product + in-house integration" if partner else ", ".join(own),
                        "basis": "Partner" if partner else "Company strength",
                        "rationale": (f"Partner covers {', '.join(partner)}; we deliver integration, analytics and operations" if partner
                                      else "Built on in-house analytics capability"),
                        "requirements": sum((tech_reqs[t][:3] for t in fraud), [])})

    sec = [t for t in ("PKI/TLS", "IAM", "SIEM", "MFA", "OAuth 2.0") if t in tech_reqs or (t in inv and re.search(r"secur|encrypt|access control", text_all))]
    if sec:
        choices.append({"area": "Security controls", "choice": ", ".join(sec), "basis": "RFP + company practice",
                        "rationale": "Encryption in transit, least-privilege access and tamper-evident audit trails", "requirements": []})

    if eng == "consulting":
        domains = {d: [] for d in EA_DOMAINS}
        for r in reqs:
            t = r["text"].lower()
            d = ("Business architecture" if re.search(r"business|process|service", t) else
                 "Data architecture" if re.search(r"data|analytic|warehous", t) else
                 "Integration architecture" if re.search(r"integrat|api|middleware|interop", t) else
                 "Security architecture" if re.search(r"secur|identity|access", t) else
                 "Technology & infrastructure" if re.search(r"infra|cloud|network|virtual|container", t) else
                 "Application architecture" if re.search(r"application|portfolio|system", t) else "Governance & roadmap")
            domains[d].append(r["code"])
        layers_out = [{"layer": d, "components": [{"name": d, "source": "Assessment scope", "requirements": codes[:10], "detail": ""}]}
                      for d, codes in domains.items() if codes]
        style = "ea-domains"
    else:
        layers_out = [{"layer": l, "components": sorted(layers[l].values(), key=lambda c: (-len(c["requirements"]), c["name"]))[:7]}
                      for l in LAYER_ORDER if layers.get(l)]
        style = "layered"

    eng_label = {"managed_services": "outcome-based managed service", "build_run": "platform build followed by a managed service",
                 "product": "product-led solution with system integration",
                 "consulting": "architecture advisory engagement", "implementation": "design-and-build implementation"}.get(eng, eng)
    mandated = [c["name"] for l in layers_out for c in l["components"] if c["source"] == "RFP-mandated"]
    partners = [c["name"] for l in layers_out for c in l["components"] if c["source"] == "Partner product"]
    art = "An" if eng_label[:1].lower() in "aeiou" else "A"
    summary = (f"{art} {eng_label} for {meta.get('industry', 'the client')}. "
               + (f"The solution is anchored on {', '.join(mandated[:4])} as specified in the RFP. " if mandated else "")
               + (f"{', '.join(partners)} come from a partner product, integrated and operated by {kb.name}. " if partners else "")
               + f"{len(choices)} technology decisions are traced back to the requirements that drove them.")
    for c in choices:
        c["requirements"] = list(dict.fromkeys(c.get("requirements", [])))
    return {"style": style, "engagement_type": eng, "summary": summary, "layers": layers_out, "choices": choices}


def ai_architecture(draft: dict, reqs: list[dict], kb: CompanyKB, meta: dict, guidance: str = "") -> dict | None:
    """AI refines the rules-based draft: better grouping, missing components, sharper rationale; every item traced to requirements."""
    from . import llm

    if not llm.is_enabled():
        return None
    tech = [r for r in reqs if r["category"] in ("Functional", "Non-functional")][:110]
    codes = {r["code"] for r in reqs}
    inv = kb.tech_inventory()
    company = ", ".join(sorted(t for t, v in inv.items() if v["people"] >= 2))[:1500]
    req_lines = "\n".join(f"{r['code']}: {r['text'][:200]}" for r in tech)
    prompt = (f"Engagement: {meta.get('engagement_type')} for {meta.get('industry')} ({meta.get('region')}).\n"
              f"Technologies this company has people for: {company}\n\nDraft architecture (JSON):\n"
              f"{__import__('json').dumps({k: draft[k] for k in ('layers', 'choices')})[:9000]}\n\nRequirements:\n{req_lines}\n\n"
              "Improve the draft into a credible solution architecture. Keep technologies the RFP mandates; prefer the company's own technologies "
              "where the RFP leaves the choice open; mark packaged products the company lacks as 'Partner product'. Every component and choice must "
              "list the requirement codes that drive it (codes from the list only). Return JSON: "
              '{"summary": "<3 sentences>", "layers": [{"layer": "<name>", "components": [{"name": "...", "source": "RFP-mandated|Proposed|Client-owned|Partner product", '
              '"requirements": ["REQ-001"], "detail": "<short>"}]}], "choices": [{"area": "...", "choice": "...", "basis": "Specified in the RFP|Company strength|Partner|To confirm", '
              '"rationale": "<one sentence>", "requirements": ["REQ-001"]}]}' + guidance)
    try:
        out = llm.complete_json("You are a principal solution architect writing the architecture section of a bid. Be concrete and grounded.", prompt, max_tokens=10000)
    except Exception:
        return None
    if not isinstance(out, dict) or not isinstance(out.get("layers"), list) or not out["layers"]:
        return None
    layers = []
    for l in out["layers"][:10]:
        comps = []
        for c in (l.get("components") or [])[:9]:
            if not isinstance(c, dict) or not c.get("name"):
                continue
            src = c.get("source") if c.get("source") in ("RFP-mandated", "Proposed", "Client-owned", "Partner product") else "Proposed"
            comps.append({"name": str(c["name"])[:80], "source": src, "requirements": [x for x in (c.get("requirements") or []) if x in codes][:12],
                          "detail": str(c.get("detail", ""))[:200]})
        if comps:
            layers.append({"layer": str(l.get("layer", "Layer"))[:60], "components": comps})
    choices = []
    for c in (out.get("choices") or [])[:12]:
        if isinstance(c, dict) and c.get("area") and c.get("choice"):
            choices.append({"area": str(c["area"])[:60], "choice": str(c["choice"])[:160], "basis": str(c.get("basis", "Proposed"))[:40],
                            "rationale": str(c.get("rationale", ""))[:300], "requirements": [x for x in (c.get("requirements") or []) if x in codes][:10]})
    if not layers:
        return None
    res = {**draft, "summary": str(out.get("summary") or draft["summary"])[:900], "layers": layers, "choices": choices or draft["choices"], "engine": "ai"}
    return check_against_library(res, reqs, kb)


def check_against_library(arch: dict, reqs: list[dict], kb: CompanyKB) -> dict:
    """Flag technology choices the company has no evidence for (no people, capability or case study) and the RFP doesn't
    name: the proposal shows them as "to be validated" and the Architecture stage lists them for the architect."""
    inv = kb.tech_inventory()
    have = {t for t, v in inv.items() if v["people"] or v["capabilities"] or v["case_studies"]}
    rfp_text = " ".join(r["text"] for r in reqs)
    in_rfp = set(K.find_technologies(rfp_text))
    unbacked = []
    for c in arch.get("choices", []):
        techs = [t for t in K.find_technologies(f"{c.get('choice', '')}") if t not in K.COMMODITY_TECH]
        missing = [t for t in techs if t not in have and t not in in_rfp]
        if missing and c.get("basis") != "Partner":
            c["basis"] = "To validate"
            c["not_in_library"] = missing
            unbacked.extend(missing)
    for l in arch.get("layers", []):
        for comp in l.get("components", []):
            techs = [t for t in K.find_technologies(comp.get("name", "") + " " + comp.get("detail", "")) if t not in K.COMMODITY_TECH]
            missing = [t for t in techs if t not in have and t not in in_rfp]
            if missing and comp.get("source") == "Proposed":
                comp["not_in_library"] = missing
                unbacked.extend(missing)
    arch["not_in_library"] = sorted(set(unbacked))
    return arch


# =========================================================================== estimation
WORKSTREAM = {
    "Integration & APIs": "Integration engineering", "Application Development": "Application engineering",
    "Fraud & Risk Analytics": "Risk intelligence & analytics", "Data & Analytics": "Data & reporting",
    "Testing & QA": "Quality engineering", "Transition & Knowledge Transfer": "Transition & knowledge transfer",
    "Support & Incident Management": "Service operations", "Monitoring & Operations": "Service operations",
    "Service Levels": "Service operations", "Availability & Continuity": "Platform & continuity",
    "Performance & Scalability": "Platform & continuity", "Maintainability & Quality": "DevOps & release",
    "Security": "Security & compliance", "Data Protection & Privacy": "Security & compliance",
    "Information Security Policy": "Security & compliance", "Standards & Certifications": "Security & compliance",
    "Regulatory": "Security & compliance", "Accessibility & Sustainability": "Security & compliance",
    "Architecture & Advisory": "Architecture & advisory", "Project Management": "Programme management",
    "Team & Experience": "Programme management", "General Scope": "Programme management",
}
WS_ROLE = {
    "Integration engineering": "Integration Engineer", "Application engineering": "Software Engineer",
    "Risk intelligence & analytics": "Data Scientist", "Data & reporting": "Data Engineer", "Quality engineering": "QA Engineer",
    "Transition & knowledge transfer": "Business Analyst", "Service operations": "Support Engineer",
    "Platform & continuity": "DevOps Engineer", "DevOps & release": "DevOps Engineer", "Security & compliance": "Security Specialist",
    "Architecture & advisory": "Solution Architect", "Programme management": "Project Manager",
}
HIGH_RE = re.compile(r"(real[- ]time|high[- ]availability|migrat|machine learning|model|correlat|graph|all new|end[- ]to[- ]end|multiple|cluster|"
                     r"failover|disaster|cryptograph|sdk|explainable|simulation|champion)", re.I)
LOW_RE = re.compile(r"(document|report|meeting|participat|provide details|state |describe|list|template|review)", re.I)
DAYS = {"Low": 3, "Medium": 8, "High": 18}


def _complexity(r: dict) -> str:
    score = 1.0
    t = r["text"]
    if HIGH_RE.search(t):
        score += 1
    if len(r.get("technologies", [])) >= 3 or len(t) > 260:
        score += 0.7
    if LOW_RE.search(t) and not HIGH_RE.search(t):
        score -= 0.8
    if r.get("match_status") == "gap":
        score += 0.6
    elif r.get("match_status") == "partial":
        score += 0.3
    return "High" if score >= 2 else "Medium" if score >= 1 else "Low"


def _assign_people(kb: CompanyKB, role: str, n: int, skills: list[str], used: set[str]) -> tuple[list[dict], int]:
    cand = []
    for e in kb.employees:
        if e["code"] in used:
            continue
        nr = K.normalize_role(e.get("role", ""))
        role_ok = nr == role or (role == "Support Engineer" and nr in ("Integration Engineer",)) or \
            (role == "Software Engineer" and nr in ("Integration Engineer",)) or (role == "Solution Architect" and "architect" in e.get("role", "").lower())
        if not role_ok:
            continue
        sk = {s["name"]: s.get("level", 3) for s in e.get("skills", [])}
        fit = sum(sk.get(s, 0) for s in skills)
        cand.append((e.get("availability", 100) >= 50, fit, e.get("years", 0), e))
    cand.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    picked = []
    for avail, fit, _, e in cand[:n]:
        used.add(e["code"])
        picked.append({"code": e["code"], "name": e.get("name", ""), "role": e.get("role", ""), "level": e.get("level", ""),
                       "location": e.get("location", ""), "availability": e.get("availability", 100), "fit": fit,
                       "status": "Available" if avail else "Needs release from current project"})
    return picked, max(0, n - len(picked))


VOLUME_RE = re.compile(r"\b(\d{2,4})\s+(?:existing\s+|in-scope\s+|legacy\s+)?(interfaces|integrations|apis|flows|connectors|reports)\b", re.I)
DAYS_PER_UNIT = {"interfaces": 3.5, "integrations": 3.5, "flows": 3.0, "apis": 4.0, "connectors": 6.0, "reports": 2.0}


def _req_days(r: dict, eng: str) -> tuple[str, float]:
    """Complexity and person-days for one requirement. Volume work ("migrate all 186 interfaces") is sized per unit."""
    cx = _complexity(r)
    days = DAYS[cx] * (0.5 if eng == "product" and r.get("gap", {}).get("recommended") == "Partner" else 1.0)
    m = VOLUME_RE.search(r["text"])
    if m and re.search(r"migrat|build|deliver|develop|implement|re-?platform|rebuild|convert", r["text"], re.I):
        n = int(m.group(1))
        if 10 <= n <= 2000:
            days = max(days, n * DAYS_PER_UNIT[m.group(2).lower()])
            cx = "High"
    return cx, float(days)


def _run_roles(text_all: str, ws_reqs: dict, onsite_ratio: float, after_build: bool) -> tuple[list, bool, bool, int]:
    is_247 = bool(re.search(r"24\s?x\s?7|24/7|round[- ]the[- ]clock", text_all))
    p1_fast = bool(re.search(r"p1[^.]{0,60}(15|30)\s?min", text_all))
    enh = re.search(r"(\d{1,3})\s+(?:minor\s+)?(?:enhancements|changes|change requests)\s+per\s+(quarter|month|year)", text_all)
    if after_build:  # the platform was just built by the same team: the change squad sizes to the enhancement volume
        per_q = 0
        if enh:
            per_q = int(enh.group(1)) * {"quarter": 1, "month": 3, "year": 0.25}[enh.group(2)]
        change_engineers = 2 if per_q <= 25 else 3 if per_q <= 45 else 4
    else:
        change_reqs = sum(len(ws_reqs.get(w, [])) for w in ("Integration engineering", "Application engineering"))
        change_engineers = 2 if change_reqs < 8 else 3 if change_reqs < 15 else 4
    ops_fte = 5.0 if is_247 else 2.0
    roles = [
        ("Engagement Manager", 1.0, "Onsite" if onsite_ratio >= 0.3 else "Offshore",
         "Named service delivery manager: outcomes, SLAs and governance" if after_build else "Accountable for outcomes, SLAs and governance"),
        ("Solution Architect", 0.5, "Offshore", "Platform design authority, upgrades and capacity planning"),
        ("Support Engineer", ops_fte, "Offshore", f"{'24x7 shift-based' if is_247 else 'Business-hours'} monitoring, L2 incident & request handling"),
        ("Integration Engineer", float(change_engineers), "Offshore", "Change & enhancement squad: new and modified interfaces"),
        ("Integration Engineer", 1.0, "Onsite", "Onsite L3 lead: change board (CAB), escalations and business stakeholder liaison"),
        ("QA Engineer", 1.0 if change_engineers <= 3 else 1.5, "Offshore", "Interface validation, regression and release evidence"),
        ("DevOps Engineer", 0.5, "Offshore", "Release automation, version control and rollback"),
        ("Business Analyst", 0.5, "Onsite", "Requirements, data-mapping specifications and documentation"),
        ("Security Specialist", 0.25, "Offshore", "Security compliance, audits and DR drills"),
    ]
    return roles, is_247, p1_fast, change_engineers


def _build_roles(workstreams: list[dict], ws_reqs: dict, eng: str, onsite_ratio: float, months_fixed: int | None) -> tuple[list, int, float]:
    build = sum(w["effort_days"] for w in workstreams)
    pm = build * 0.10
    arch_d = build * 0.08
    qa = build * 0.22 if "Quality engineering" not in ws_reqs else 0
    total = build + pm + arch_d + qa
    target_fte = max(4.0, min(16.0, math.sqrt(total) / 3))
    months = int(months_fixed or max(3, min(18, math.ceil(total / (21 * target_fte)))))
    fte_days = months * 21
    role_days = defaultdict(float)
    for w in workstreams:
        role_days[w["lead_role"]] += w["effort_days"]
    role_days["Project Manager"] += pm
    role_days["Solution Architect"] += arch_d
    role_days["QA Engineer"] += qa
    roles = []
    for role, dd in sorted(role_days.items(), key=lambda kv: -kv[1]):
        fte = max(0.5, round(dd / fte_days * 2) / 2)
        if role in ("Project Manager", "Solution Architect"):
            fte = max(fte, 1.0)  # a dedicated PM and architect for the whole build
        on = round(fte * onsite_ratio * 4) / 4 if role in ("Project Manager", "Solution Architect", "Business Analyst") else 0
        if on:
            roles.append((role, on, "Onsite", "Client-facing lead"))
        if fte - on > 0:
            roles.append((role, fte - on, "Offshore", f"Delivers {', '.join(w['name'] for w in workstreams if w['lead_role'] == role)[:90] or 'programme support'}"))
    if eng == "product":
        roles.insert(0, ("Engagement Manager", 0.5, "Onsite", "Single point of accountability across partner and integration teams"))
    return roles, months, build


def _build_phases(months: int, offset_weeks: float = 0) -> list[dict]:
    w = months * 4.33
    return [{"name": "Mobilise", "weeks": 2, "detail": "Team on-boarding, environments, plan baseline"},
            {"name": "Design", "weeks": max(2, w * 0.18), "detail": "Solution and integration design"},
            {"name": "Build & configure", "weeks": max(4, w * 0.45), "detail": "Sprint-based delivery"},
            {"name": "Test & accept", "weeks": max(2, w * 0.2), "detail": "SIT, UAT, performance and security testing"},
            {"name": "Deploy & hypercare", "weeks": max(2, w * 0.12), "detail": "Go-live and stabilisation"}]


def estimate(reqs: list[dict], kb: CompanyKB, meta: dict, arch: dict, overrides: dict | None = None) -> dict:
    ov = overrides or {}
    eng = meta.get("engagement_type", "implementation") or "implementation"
    region = meta.get("region", "")
    text_all = " ".join(r["text"] for r in reqs).lower()
    savings = relevant_accelerators(kb, reqs)

    ws_reqs: dict[str, list[dict]] = defaultdict(list)
    for r in reqs:
        if r.get("category") == "Commercial" or r.get("subcategory") in ("Submission", "Evaluation & Award") or r.get("match_status") == "confirm" and r.get("category") != "Non-functional":
            r["workstream"], r["complexity"], r["effort_days"] = "Bid & contract", "", 0
            continue
        ws = WORKSTREAM.get(r.get("subcategory", ""), "Programme management")
        cx, days = _req_days(r, eng)
        r["workstream"], r["complexity"], r["effort_days"] = ws, cx, days
        ws_reqs[ws].append(r)

    accel_factor = 1 - min(0.3, sum(s["saving_pct"] for s in savings) / 100 * 0.5)
    onsite_ratio = float(ov.get("onsite_ratio", 0.35 if region in ("UAE", "Kuwait", "Saudi Arabia", "Qatar") else 0.2))
    term = int(ov.get("contract_months") or meta.get("contract_term_months") or (36 if eng in ("managed_services", "build_run") else 0))
    team: list[dict] = []
    phases: list[dict] = []
    workstreams = []

    for ws, rs in sorted(ws_reqs.items(), key=lambda kv: -sum(r["effort_days"] for r in kv[1])):
        d = sum(r["effort_days"] for r in rs) * accel_factor
        workstreams.append({"name": ws, "requirements": len(rs), "codes": [r["code"] for r in rs][:30], "effort_days": round(d, 1),
                            "complexity": dict(Counter(r["complexity"] for r in rs)), "lead_role": WS_ROLE.get(ws, "Software Engineer")})

    plan: list[tuple] = []  # (role, fte, location, responsibility, phase, months)
    build_months = None
    if eng == "managed_services":
        roles, is_247, p1_fast, _ = _run_roles(text_all, ws_reqs, onsite_ratio, after_build=False)
        transition_weeks = 6 if re.search(r"4\s?[–-]\s?6 weeks|6 weeks", text_all) else 4
        phases = [
            {"name": "Transition & onboarding", "weeks": transition_weeks, "detail": "Knowledge transfer, access, baselining, governance set-up"},
            {"name": "Steady-state operations", "weeks": max(4, term * 4.33 - transition_weeks), "detail": "SLA-based run services" + (" 24x7" if is_247 else "")},
            {"name": "Change & enhancement delivery", "weeks": max(4, term * 4.33 - transition_weeks), "detail": "Sprint-based interface delivery", "parallel": True},
            {"name": "Lifecycle & continuous improvement", "weeks": max(4, term * 4.33 - transition_weeks), "detail": "Quarterly upgrade, patch and improvement cycles", "parallel": True},
        ]
        months = term
        plan = [(*r, "Run", term) for r in roles]
        assumptions_extra = [f"Contract term of {term} months{' (assumed: not stated in the RFP)' if not meta.get('contract_term_months') else ' as stated in the RFP'}.",
                             f"{'24x7' if is_247 else 'Business-hours'} coverage{' with P1 response within 15–30 minutes' if p1_fast else ''}.",
                             "Volume of change requests is absorbed by the change squad; surges beyond 20% trigger a capacity review."]
    elif eng == "build_run":
        build_months = int(ov.get("duration_months") or meta.get("build_months") or 0) or None
        b_roles, build_months, build = _build_roles(workstreams, ws_reqs, eng, onsite_ratio, build_months)
        r_roles, is_247, p1_fast, squad = _run_roles(text_all, ws_reqs, onsite_ratio, after_build=True)
        plan = [(*r, "Build", build_months) for r in b_roles] + [(*r, "Run", term) for r in r_roles]
        phases = _build_phases(build_months) + [
            {"name": "Service transition", "weeks": 4, "detail": "Runbooks, monitoring and support handed from the build team to the run team", "parallel": True},
            {"name": "Managed service (run)", "weeks": term * 4.33, "detail": "SLA-based run services" + (" 24x7" if is_247 else "") + ", enhancements and continuous improvement"},
        ]
        months = build_months + term
        assumptions_extra = [
            f"Build and migration over {build_months} months{' as required by the RFP' if meta.get('build_months') and not ov.get('duration_months') else ''}, "
            f"from {round(build)} person-days of requirement-level effort plus project management, architecture and testing.",
            f"Managed service for {term} months after go-live{' as stated in the RFP' if meta.get('contract_term_months') else ' (assumed: not stated in the RFP)'}.",
            f"{'24x7' if is_247 else 'Business-hours'} coverage{' with P1 response within 15–30 minutes' if p1_fast else ''}; a {squad}-engineer change squad covers routine enhancements.",
            "Client provides environments, test data and SME availability per plan."]
    elif eng == "consulting":
        n_deliv = len(meta.get("deliverables", [])) or 6
        weeks = min(36, 8 + n_deliv * 2)
        months = max(3, round(weeks / 4.33))
        domains = [l["layer"] for l in arch.get("layers", [])]
        roles = [("Engagement Manager", 0.5, "Onsite", "Engagement lead and steering-committee interface"),
                 ("Solution Architect", 1.0, "Onsite", "Lead enterprise architect")]
        for d in domains:
            if d != "Governance & roadmap":
                roles.append(("Solution Architect", 1.0 if d in ("Application architecture", "Integration architecture", "Data architecture") else 0.5,
                              "Onsite", f"{d} lead"))
        roles += [("Business Analyst", 1.0, "Onsite", "Current-state discovery and stakeholder interviews"),
                  ("Business Analyst", 1.0, "Offshore", "Portfolio analysis and documentation"), ("Project Manager", 0.5, "Offshore", "Planning, reporting and PMO")]
        plan = [(*r, "Delivery", months) for r in roles]
        phases = [{"name": "Mobilise & discovery", "weeks": 3, "detail": "Stakeholder interviews, document review"},
                  {"name": "Current-state assessment", "weeks": max(4, weeks * 0.35), "detail": "Business, application, data, technology baselines"},
                  {"name": "Target & interim state", "weeks": max(3, weeks * 0.25), "detail": "Future-state architecture and strategies"},
                  {"name": "Roadmap & standards", "weeks": max(3, weeks * 0.2), "detail": "Transformation roadmap, architecture standards"},
                  {"name": "Operationalise & handover", "weeks": max(2, weeks * 0.1), "detail": "Governance, training, knowledge transfer"}]
        assumptions_extra = ["Onsite presence in the client's city for the architecture team, as requested.",
                             "Access to stakeholders and system documentation within the first two weeks."]
    else:
        fixed = int(ov.get("duration_months") or meta.get("build_months") or 0) or None
        roles, months, build = _build_roles(workstreams, ws_reqs, eng, onsite_ratio, fixed)
        plan = [(*r, "Build", months) for r in roles]
        phases = _build_phases(months)
        assumptions_extra = [f"Build effort of {round(build)} person-days from {sum(w['requirements'] for w in workstreams)} scoped requirements, plus PM, architecture and QA overheads.",
                             "Client provides environments, test data and SME availability per plan."]

    # role-wise team plan with named (anonymised) people from the skills register
    used: set[str] = set()
    req_skills = [t for r in reqs for t in r.get("technologies", []) if t not in K.COMMODITY_TECH]
    top_skills = [t for t, _ in Counter(req_skills).most_common(6)]
    by_phase: dict[str, set[str]] = defaultdict(set)
    for role, fte, loc, resp, phase, m in plan:
        n_people = max(1, math.ceil(fte - 0.01))
        # nobody holds two roles in the same phase; in a build + run deal the build team can stay on for the run
        pool = by_phase[phase] if eng == "build_run" else used
        people, unfilled = _assign_people(kb, role, n_people, top_skills, pool)
        by_phase[phase].update(p["code"] for p in people)
        used.update(p["code"] for p in people)
        team.append({"role": role, "fte": round(fte, 2), "headcount": n_people, "location": loc, "responsibility": resp, "phase": phase,
                     "months": m, "person_days": round(fte * m * 21, 1), "assigned": people, "unfilled": unfilled})
    cal = ov.get("_calibration") or {"factor": 1.0, "deals": 0}
    if cal.get("deals") and abs(cal["factor"] - 1.0) > 0.01 and eng not in ("managed_services",):
        for t in team:
            if t["phase"] == "Run":
                continue
            t["person_days"] = round(t["person_days"] * cal["factor"], 1)
            t["fte"] = round(t["fte"] * cal["factor"], 2)
        assumptions_extra.append(f"Effort calibrated ×{cal['factor']} from actuals on {cal['deals']} delivered deal(s).")
    people_codes = {p["code"] for t in team for p in t["assigned"]}
    headcount = len(people_codes) + sum(t["unfilled"] for t in team)
    total_pd = round(sum(t["person_days"] for t in team), 1)
    risk_items = sum(1 for r in reqs if r.get("gap", {}).get("risk") == "High")
    unfilled = sum(t["unfilled"] for t in team)
    contingency = float(ov.get("contingency_pct", 8 + min(12, risk_items * 0.8)))
    def fte_of(ph):
        return round(sum(t["fte"] for t in team if t["phase"] == ph), 2)
    peak_fte = max([fte_of(ph) for ph in {t["phase"] for t in team}] or [0])
    onsite_fte = sum(t["fte"] for t in team if t["location"] == "Onsite")
    all_fte = sum(t["fte"] for t in team) or 1
    req_days = round(sum(w["effort_days"] for w in workstreams), 1)
    return {"engagement_type": eng, "duration_months": months, "contract_months": (term if eng == "managed_services" else months) or months,
            "build_months": build_months if eng == "build_run" else (months if eng not in ("managed_services", "consulting") else None),
            "run_months": term if eng in ("managed_services", "build_run") else None,
            "headcount": headcount, "total_person_days": total_pd, "fte": peak_fte,
            "fte_by_phase": {ph: fte_of(ph) for ph in dict.fromkeys(t["phase"] for t in team)},
            "onsite_ratio": onsite_ratio, "onsite_share": round(onsite_fte / all_fte, 3),
            "requirement_effort_days": req_days,
            "workstreams": workstreams, "team": team, "phases": phases, "accelerators": savings,
            "accelerator_saving_pct": round((1 - accel_factor) * 100, 1), "contingency_pct": round(contingency, 1),
            "contingency_basis": {"high_risk_gaps": risk_items, "unfilled_roles": unfilled},
            "unfilled_roles": unfilled, "assumptions": assumptions_extra, "calibration": cal,
            "staffing_skills": top_skills}


# =========================================================================== pricing
# Indicative rates only (finance confirms the rate at submission). Override any of them with FX_RATES="AUD=1.52,EUR=0.92" in .env.
FX_PER_USD = {"USD": 1.0, "AED": 3.6725, "KWD": 0.307, "SAR": 3.75, "QAR": 3.64, "INR": 83.5, "EUR": 0.92, "GBP": 0.79,
              "AUD": 1.52, "SGD": 1.34, "CAD": 1.37}
import os as _os
for _pair in filter(None, _os.getenv("FX_RATES", "").split(",")):
    try:
        _k, _v = _pair.split("=")
        FX_PER_USD[_k.strip().upper()] = float(_v)
    except ValueError:
        pass
DEFAULT_RATES = {"Engagement Manager": (900, 480), "Project Manager": (700, 360), "Solution Architect": (950, 500), "Integration Engineer": (450, 210),
                 "Software Engineer": (420, 190), "Data Scientist": (520, 250), "Data Engineer": (420, 190), "QA Engineer": (300, 135),
                 "DevOps Engineer": (420, 190), "Support Engineer": (320, 140), "Security Specialist": (520, 250), "Business Analyst": (520, 260),
                 "Technical Writer": (220, 100), "BI Developer": (420, 190), "MDM Specialist": (480, 220), "CRM Developer": (450, 210)}


def _rate_for(kb: CompanyKB, role: str, location: str, overrides: dict) -> tuple[float, float, str, str]:
    key = f"{role}|{location}"
    if key in overrides:
        o = overrides[key]
        return float(o.get("day_rate", 0)), float(o.get("day_cost", 0)), o.get("currency", "USD"), "Override"
    rows = [r for r in kb.rates if K.normalize_role(r["role"]) == role]
    exact = [r for r in rows if r.get("location", "").lower().startswith(location.lower()[:4])]
    pick = exact or rows
    if pick:
        r = max(pick, key=lambda x: x.get("day_rate", 0))
        cost = r.get("day_cost") or r.get("day_rate", 0) * 0.5
        rate, cost = r.get("day_rate", 0), cost
        if not exact and location == "Onsite":
            rate, cost = rate * 2.1, cost * 2.0
        return float(rate), float(cost), r.get("currency", "USD") or "USD", "Rate card" if exact else "Rate card (location adjusted)"
    rate, cost = DEFAULT_RATES.get(role, (450, 220))
    if location == "Onsite":
        rate, cost = rate * 2.1, cost * 2.0
    return float(rate), float(cost), "USD", "Benchmark (no rate card row)"


def _rates_note(company: str, lines: list[dict], rates_from: str) -> str:
    """Says truthfully where the day rates came from, so nobody sends a client a price built on guesses without knowing."""
    if rates_from == "benchmark":
        return (f"No rate card yet: every day rate is a generic market benchmark, not {company}'s own rates. Add your rate card "
                "(Knowledge library) before using this price.")
    bench = sorted({l["role"] for l in lines if l["rate_source"].startswith("Benchmark")})
    if bench:
        return (f"Rates from the {company} rate card, except {', '.join(bench)}: no rate card row, so a generic market benchmark is used "
                "for these. Add them to your rate card for real figures.")
    return f"Rates from the {company} rate card."


def _contingency_note(pct: float, est: dict) -> str:
    b = est.get("contingency_basis") or {}
    risks, unfilled = b.get("high_risk_gaps", 0), b.get("unfilled_roles", est.get("unfilled_roles", 0))
    why = [x for x in (f"{risks} high-risk gap{'s' if risks != 1 else ''}" if risks else "",
                       f"{unfilled} unfilled role{'s' if unfilled != 1 else ''}" if unfilled else "") if x]
    return f"Contingency of {pct:g}%: " + (f"8% base plus an allowance for {' and '.join(why)}." if why else "the standard 8% delivery allowance (no high-risk gaps or unfilled roles).")


def price(est: dict, kb: CompanyKB, meta: dict, tenant_settings: dict, overrides: dict | None = None) -> dict:
    ov = overrides or {}
    rate_ov = ov.get("rates", {})
    target = float(ov.get("target_margin", tenant_settings.get("target_margin", 28)))
    floor = float(tenant_settings.get("min_margin", 18))
    contingency = float(ov.get("contingency_pct", est.get("contingency_pct", 10)))
    travel_pct = float(ov.get("travel_pct", tenant_settings.get("travel_pct", 6)))
    lines = []
    base_ccy = kb.rates[0].get("currency", "USD") if kb.rates else "USD"
    for t in est["team"]:
        rate, cost, ccy, src = _rate_for(kb, t["role"], t["location"], rate_ov)
        fx = FX_PER_USD.get(base_ccy, 1) / FX_PER_USD.get(ccy or "USD", 1)
        rate, cost = rate * fx, cost * fx
        days = t["person_days"]
        lines.append({"role": t["role"], "location": t["location"], "fte": t["fte"], "person_days": days, "day_rate": round(rate, 2),
                      "day_cost": round(cost, 2), "cost": round(days * cost, 2), "list_price": round(days * rate, 2), "rate_source": src,
                      "phase": t.get("phase", "")})
    labour_cost = sum(l["cost"] for l in lines)
    list_price = sum(l["list_price"] for l in lines)
    onsite_cost = sum(l["cost"] for l in lines if l["location"] == "Onsite")
    travel = onsite_cost * travel_pct / 100
    cont = labour_cost * contingency / 100
    total_cost = labour_cost + travel + cont

    def scen(name, margin, note):
        p = total_cost / (1 - margin / 100)
        return {"name": name, "margin_pct": round(margin, 1), "price": round(p, 2), "gross_profit": round(p - total_cost, 2),
                "vs_list_pct": round((p / list_price - 1) * 100, 1) if list_price else 0, "note": note}

    bench = {l["role"] for l in lines if l["rate_source"].startswith("Benchmark")}
    rates_from = "benchmark" if bench and len(bench) == len({l["role"] for l in lines}) else "mixed" if bench else "rate_card"
    implied = (1 - total_cost / list_price) * 100 if list_price else 0
    scenarios = [scen("Aggressive", max(floor, target - 8), "Price to win; at or near the margin floor"),
                 scen("Target", target, "Company target margin"),
                 scen("Premium", target + 8, "Value-based price for a strong fit"),
                 {**scen("Rate card", implied, "Straight rate-card pricing" if rates_from == "rate_card" else
                         "Straight list price at generic benchmark rates: add your rate card for real figures" if rates_from == "benchmark" else
                         "Straight list price: your rate card, with benchmark rates where it has no row"), "price": round(list_price, 2)}]
    rfp_ccy = meta.get("currency") or base_ccy
    fx_to_rfp = FX_PER_USD.get(rfp_ccy, 1) / FX_PER_USD.get(base_ccy, 1)
    eng = est.get("engagement_type")
    target_price = next(s["price"] for s in scenarios if s["name"] == "Target")
    phase_split = None
    if eng == "build_run":
        # Price follows the RFP's instructions: the build as fixed price by milestone, the run as a fixed monthly fee.
        build_cost = sum(l["cost"] for l in lines if l["phase"] == "Build")
        run_cost = sum(l["cost"] for l in lines if l["phase"] == "Run")
        build_share = build_cost / max(1e-9, build_cost + run_cost)
        run_months = est.get("run_months") or 36
        rfp_ms = [m for m in (meta.get("rfp_milestones") or []) if m.get("name")]
        if rfp_ms:
            n = len(rfp_ms)
            w = [1.0] * n
            w[-1] = 2.0  # final acceptance carries the largest payment
            names = [f"{m['name']} (month {m['month']})" for m in rfp_ms]
        else:
            w = [1, 2, 3, 2, 1.5, 0.5]
            names = ["Mobilisation", "Design sign-off", "Build complete", "UAT sign-off", "Go-live", "Hypercare exit"]
        tw = sum(w)
        milestones = [{"name": f"Build: {nm}", "pct": round(build_share * 100 * x / tw, 1), "phase": "Build"} for nm, x in zip(names, w)]
        milestones.append({"name": f"Managed service: monthly fee × {run_months}", "pct": round((1 - build_share) * 100, 1), "phase": "Run",
                           "monthly": round(target_price * (1 - build_share) / run_months, 2)})
        phase_split = {"build_pct": round(build_share * 100, 1), "build_price": round(target_price * build_share, 2),
                       "run_price": round(target_price * (1 - build_share), 2), "run_months": run_months,
                       "monthly_fee": round(target_price * (1 - build_share) / run_months, 2), "build_months": est.get("build_months")}
    elif eng == "managed_services":
        trans_share = 0.08
        months = est.get("contract_months") or 36
        milestones = [{"name": "Transition & onboarding complete", "pct": round(trans_share * 100, 1)},
                      {"name": f"Monthly service charge × {months}", "pct": round((1 - trans_share) * 100, 1),
                       "monthly": round(target_price * (1 - trans_share) / months, 2)}]
    elif eng == "consulting":
        milestones = [{"name": "Current-state assessment accepted", "pct": 30}, {"name": "Target-state architecture accepted", "pct": 30},
                      {"name": "Roadmap & standards accepted", "pct": 30}, {"name": "Handover & training", "pct": 10}]
    else:
        milestones = [{"name": "Mobilisation", "pct": 10}, {"name": "Design sign-off", "pct": 20}, {"name": "Build complete", "pct": 30},
                      {"name": "UAT sign-off", "pct": 20}, {"name": "Go-live", "pct": 15}, {"name": "Hypercare exit", "pct": 5}]
    adv = re.search(r"advance payment[^.]*?(\d{1,2})\s?%", " ".join(meta.get("payment_terms", [])) or "", re.I)
    partner_note = "Partner product licences are quoted separately by the partner and excluded from this price." if any(
        t.get("recommendation") == "Partner" for t in meta.get("top_missing", [])) else ""
    return {"currency": base_ccy, "rfp_currency": rfp_ccy, "fx_to_rfp": round(fx_to_rfp, 4), "lines": lines,
            "labour_cost": round(labour_cost, 2), "travel": round(travel, 2), "travel_pct": travel_pct, "contingency": round(cont, 2),
            "contingency_pct": contingency, "total_cost": round(total_cost, 2), "list_price": round(list_price, 2),
            "implied_rate_card_margin": round(implied, 1), "target_margin": target, "min_margin": floor, "scenarios": scenarios,
            "recommended": "Target", "milestones": milestones, "phase_split": phase_split, "partner_note": partner_note,
            "rates_from": rates_from,
            "assumptions": [_rates_note(kb.name, lines, rates_from) + (f" Converted to {rfp_ccy} at an indicative {round(fx_to_rfp, 4)} (confirm the rate with finance)."
                                                                        if rfp_ccy != base_ccy else ""),
                            _contingency_note(contingency, est),
                            f"Travel and living at {travel_pct}% of onsite cost."]}
