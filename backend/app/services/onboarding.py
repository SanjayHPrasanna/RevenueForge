"""Company onboarding: turn whatever a company uploads (spreadsheets in any layout, Word/PDF/PPT
documents) into RevenueForge's standard records, with a column mapping the admin can review and fix
before importing."""
from __future__ import annotations

import re
from collections import defaultdict

from . import knowledge as K
from . import llm
from .parsing import ParsedDocument

KINDS = {
    "capabilities": "Capabilities & services",
    "skills": "Employee skills matrix",
    "certifications": "Certifications",
    "rates": "Rate card",
    "case_studies": "Case studies",
    "accelerators": "Accelerators & IP",
}

FIELDS: dict[str, dict[str, list[str]]] = {
    "capabilities": {
        "name": ["capability", "service", "offering", "solution", "capability name", "service name", "name"],
        "service_line": ["service line", "practice", "category", "pillar", "domain", "tower", "group"],
        "description": ["description", "details", "summary", "scope", "what we do", "overview"],
        "technologies": ["technologies", "technology", "tools", "platforms", "tech stack", "products", "partners"],
        "industries": ["industries", "industry", "verticals", "sectors", "domains served"],
        "maturity": ["maturity", "level", "strength", "status"],
    },
    "skills": {
        "code": ["employee id", "emp id", "emp code", "employee code", "staff id", "id", "emp no", "employee number", "resource id"],
        "name": ["employee name", "name", "full name", "resource name", "resource", "employee"],
        "role": ["role", "designation", "title", "job title", "position", "job role"],
        "level": ["level", "grade", "band", "seniority", "career level"],
        "years": ["experience", "years", "yrs", "total experience", "exp", "years of experience", "total exp"],
        "location": ["location", "city", "country", "base location", "work location", "onsite/offshore", "delivery location"],
        "practice": ["practice", "department", "team", "service line", "bu", "business unit", "competency"],
        "skills": ["skills", "primary skills", "skill set", "skillset", "technologies", "tech stack", "competencies", "key skills"],
        "secondary_skills": ["secondary skills", "other skills", "additional skills"],
        "skill": ["skill", "skill name", "technology"],
        "proficiency": ["proficiency", "rating", "skill level", "expertise", "score"],
        "certifications": ["certifications", "certification", "certs", "certificates"],
        "availability": ["availability", "available", "allocation", "bench", "utilization", "utilisation", "available %"],
    },
    "certifications": {
        "name": ["certification", "certificate", "name", "certification name", "standard", "accreditation"],
        "kind": ["type", "category", "kind"],
        "issuer": ["issuer", "issued by", "body", "authority", "vendor", "partner", "certifying body"],
        "holders": ["holders", "count", "no of certified", "certified employees", "number", "people"],
        "valid_until": ["valid until", "expiry", "expiry date", "valid till", "expires", "validity"],
    },
    "rates": {
        "role": ["role", "designation", "resource", "position", "title", "skill"],
        "level": ["level", "grade", "band", "seniority", "experience"],
        "location": ["location", "delivery model", "onsite/offshore", "shore", "geo", "region"],
        "day_rate": ["day rate", "daily rate", "rate", "sell rate", "billing rate", "price", "bill rate", "rate per day", "hourly rate", "monthly rate"],
        "day_cost": ["cost", "day cost", "daily cost", "cost rate", "internal cost", "ctc", "cost per day", "hourly cost", "monthly cost"],
        "currency": ["currency", "ccy"],
    },
    "case_studies": {
        "title": ["title", "project", "case study", "name", "project name"],
        "client": ["client", "customer", "account"],
        "industry": ["industry", "vertical", "sector", "domain"],
        "region": ["region", "country", "geography", "location"],
        "year": ["year", "date", "period"],
        "summary": ["summary", "description", "challenge", "solution", "overview", "scope"],
        "technologies": ["technologies", "technology", "tools", "platforms", "tech stack"],
        "outcomes": ["outcomes", "results", "benefits", "impact", "value delivered"],
    },
    "accelerators": {
        "name": ["accelerator", "name", "asset", "ip", "framework", "tool"],
        "description": ["description", "details", "summary"],
        "technologies": ["technologies", "technology", "platforms"],
        "effort_saving_pct": ["effort saving", "saving", "savings %", "effort reduction", "acceleration"],
    },
}

REQUIRED = {"capabilities": ["name"], "skills": ["role"], "certifications": ["name"], "rates": ["role", "day_rate"],
            "case_studies": ["title"], "accelerators": ["name"]}

LEVEL_WORDS = {"novice": 1, "beginner": 1, "basic": 2, "elementary": 2, "working": 3, "intermediate": 3, "competent": 3, "proficient": 4,
               "advanced": 4, "strong": 4, "expert": 5, "master": 5, "y": 3, "yes": 3, "x": 3, "✓": 3}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%/]+", " ", str(s).lower()).strip()


def _split_list(v: str) -> list[str]:
    if not v:
        return []
    # Split on list separators only. "CI/CD", "Retail & Distribution" and "Android and iOS release" stay whole.
    parts = re.split(r"[,;|\n•]+|\s+/\s+", str(v))
    return [p.strip(" .-•") for p in parts if p and p.strip(" .-•")]


def _dedupe(names: list[str]) -> list[str]:
    """Names as uploaded, without exact repeats (ignoring case)."""
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def _holders(v) -> int:
    """How many people hold a certificate. The column may hold a number ("3") or the holders themselves
    ("Lakshmi Varma (KD002)", "KD008", "Asha, Ravi"): count the people, never read digits out of an employee code."""
    t = str(v or "").strip()
    if not t or re.fullmatch(r"[-–—]+|n/?a|none|nil", t, re.I):
        return 0
    if re.fullmatch(r"\d+(?:\.0+)?", t):
        return int(float(t))
    return len([p for p in re.split(r"[,;\n/|]+|\s+and\s+|\s+&\s+", t) if re.search(r"[A-Za-z]", p)])


def _num(v) -> float | None:
    if v is None or v == "":
        return None
    m = re.search(r"-?\d[\d,]*\.?\d*", str(v))
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def _level(v) -> int | None:
    if v is None or str(v).strip() == "":
        return None
    n = _num(v)
    if n is not None:
        if n <= 5:
            return max(0, int(round(n)))
        if n <= 10:
            return max(1, int(round(n / 2)))
        if n <= 100:
            return max(1, int(round(n / 20)))
    return LEVEL_WORDS.get(str(v).strip().lower())


# --------------------------------------------------------------------------- table mapping
def _header_row(rows: list[list[str]]) -> int:
    best, best_score = 0, -1
    for i, r in enumerate(rows[:15]):
        cells = [c for c in r if str(c).strip()]
        if len(cells) < 2:
            continue
        texty = sum(1 for c in cells if not re.fullmatch(r"[\d.,%\s-]+", str(c)))
        score = texty * 2 - (len(r) - len(cells)) * 0.2
        if score > best_score:
            best, best_score = i, score
    return best


def suggest_mapping(kind: str, header: list[str]) -> dict[str, int]:
    mapping: dict[str, int] = {}
    used: set[int] = set()
    norm_h = [_norm(h) for h in header]
    for field, syns in FIELDS[kind].items():
        best, best_score = None, 0.0
        for i, h in enumerate(norm_h):
            if i in used or not h:
                continue
            for s in syns:
                if h == s:
                    sc = 3.0
                elif re.search(rf"\b{re.escape(s)}\b", h):
                    sc = 2.0 + len(s) / 40
                else:
                    continue
                if sc > best_score:
                    best, best_score = i, sc
        if best is not None:
            mapping[field] = best
            used.add(best)
    # rates: a column mentioning cost should not be the sell rate
    if kind == "rates" and "day_rate" in mapping and "cost" in norm_h[mapping["day_rate"]]:
        mapping.pop("day_rate")
    return mapping


def _wide_skill_columns(kind: str, header: list[str], data: list[list[str]], mapping: dict[str, int]) -> list[int]:
    if kind != "skills":
        return []
    cols = []
    mapped = set(mapping.values())
    for i, h in enumerate(header):
        if i in mapped or not str(h).strip():
            continue
        vals = [r[i] for r in data if i < len(r) and str(r[i]).strip()]
        if len(vals) < max(2, len(data) * 0.15):
            continue
        ok = sum(1 for v in vals if _level(v) is not None)
        if ok / len(vals) >= 0.7:
            cols.append(i)
    return cols if len(cols) >= 2 else []


def analyze_table(kind: str, rows: list[list[str]]) -> dict:
    h = _header_row(rows)
    header = [str(c).strip() for c in rows[h]]
    data = [r for r in rows[h + 1:] if any(str(c).strip() for c in r)]
    mapping = suggest_mapping(kind, header)
    wide = _wide_skill_columns(kind, header, data, mapping)
    return {"format": "table", "header_row": h, "columns": header, "mapping": mapping, "wide_skill_columns": wide,
            "row_count": len(data)}


def _cell(r: list[str], mapping: dict, field: str) -> str:
    i = mapping.get(field)
    if i is None or i >= len(r):
        return ""
    return str(r[i]).strip()


def records_from_table(kind: str, rows: list[list[str]], analysis: dict) -> list[dict]:
    h = analysis["header_row"]
    header = analysis["columns"]
    mapping = {k: int(v) for k, v in analysis["mapping"].items() if v is not None and str(v) != ""}
    wide = analysis.get("wide_skill_columns") or []
    data = [r for r in rows[h + 1:] if any(str(c).strip() for c in r)]
    recs: list[dict] = []

    if kind == "capabilities":
        for r in data:
            name = _cell(r, mapping, "name")
            if not name:
                continue
            desc = _cell(r, mapping, "description")
            techs = _dedupe(_split_list(_cell(r, mapping, "technologies")))
            techs = list(dict.fromkeys(techs + K.find_technologies(f"{name} {desc}")))
            recs.append({"name": name, "service_line": _cell(r, mapping, "service_line"), "description": desc,
                         "technologies": techs, "industries": _split_list(_cell(r, mapping, "industries")),
                         "maturity": _cell(r, mapping, "maturity")})

    elif kind == "skills":
        pair_mode = "skill" in mapping and "skills" not in mapping and not wide
        people: dict[str, dict] = {}
        for idx, r in enumerate(data):
            code = _cell(r, mapping, "code") or _cell(r, mapping, "name") or f"EMP-{idx + 1:04d}"
            p = people.get(code)
            if p is None:
                p = {"code": code, "name": _cell(r, mapping, "name"), "role": _cell(r, mapping, "role"),
                     "level": _cell(r, mapping, "level"), "years": _num(_cell(r, mapping, "years")) or 0,
                     "location": _cell(r, mapping, "location"), "practice": _cell(r, mapping, "practice"),
                     "skills": [], "certifications": _split_list(_cell(r, mapping, "certifications")),
                     "availability": _num(_cell(r, mapping, "availability"))}
                av_raw = _cell(r, mapping, "availability")
                av = p["availability"]
                if av is not None and av <= 1:
                    av = av * 100
                av_hdr = header[mapping["availability"]].lower() if "availability" in mapping else ""
                if re.search(r"allocat|utili[sz]", av_hdr) and av is not None:
                    av = 100 - av  # header describes how busy someone is
                if av is None:
                    av = 100.0 if (not av_raw or re.search(r"bench|free|available", av_raw, re.I)) else 0.0
                p["availability"] = max(0.0, min(100.0, av))
                people[code] = p
            if pair_mode:
                s = _cell(r, mapping, "skill")
                if s:
                    p["skills"].append({"name": s.strip(), "level": _level(_cell(r, mapping, "proficiency")) or 3})
            for col in ("skills", "secondary_skills"):
                for s in _split_list(_cell(r, mapping, col)):
                    m = re.match(r"(.+?)\s*[\(\[:-]\s*(\d|beginner|intermediate|advanced|expert)\s*[\)\]]?$", s, re.I)
                    name, lvl = (m.group(1), _level(m.group(2))) if m else (s, 4 if col == "skills" else 3)
                    p["skills"].append({"name": name.strip(), "level": lvl or 3})
            for i in wide:
                if i < len(r):
                    lvl = _level(r[i])
                    if lvl:
                        p["skills"].append({"name": header[i].strip(), "level": lvl})
        for p in people.values():
            seen = {}
            for s in p["skills"]:
                if s["name"] and (s["name"] not in seen or s["level"] > seen[s["name"]]):
                    seen[s["name"]] = s["level"]
            p["skills"] = [{"name": k, "level": v} for k, v in seen.items()]
            if not p["role"]:
                p["role"] = "Consultant"
            recs.append(p)

    elif kind == "certifications":
        for r in data:
            name = _cell(r, mapping, "name")
            if not name:
                continue
            kind_v = _cell(r, mapping, "kind").lower()
            if not kind_v:
                kind_v = "company" if re.search(r"\biso|cmmi|soc ?2|pci", name, re.I) else "partner" if re.search(r"partner", name, re.I) else "individual"
            recs.append({"name": name, "kind": kind_v, "issuer": _cell(r, mapping, "issuer"),
                         "holders": _holders(_cell(r, mapping, "holders")), "valid_until": _cell(r, mapping, "valid_until")})

    elif kind == "rates":
        rate_hdr = header[mapping["day_rate"]].lower() if "day_rate" in mapping else ""
        cost_hdr = header[mapping["day_cost"]].lower() if "day_cost" in mapping else ""

        def per_day(v, hdr):
            n = _num(v)
            if n is None:
                return 0.0
            if re.search(r"hour|hr|/h\b", hdr):
                return n * 8
            if re.search(r"month|/m\b", hdr):
                return n / 21
            return n

        for r in data:
            role = _cell(r, mapping, "role")
            if not role:
                continue
            ccy = _cell(r, mapping, "currency") or next((c for c in ("USD", "INR", "AED", "KWD", "EUR", "GBP", "SAR") if c.lower() in (rate_hdr + " " + cost_hdr)), "")
            loc = _cell(r, mapping, "location") or "Offshore"
            recs.append({"role": role, "level": _cell(r, mapping, "level"), "location": loc.title(),
                         "day_rate": round(per_day(_cell(r, mapping, "day_rate"), rate_hdr), 2),
                         "day_cost": round(per_day(_cell(r, mapping, "day_cost"), cost_hdr), 2), "currency": ccy.upper() or "USD"})

    elif kind == "case_studies":
        for r in data:
            title = _cell(r, mapping, "title")
            if not title:
                continue
            summary = _cell(r, mapping, "summary")
            techs = _dedupe(_split_list(_cell(r, mapping, "technologies")))
            recs.append({"title": title, "client": _cell(r, mapping, "client"), "industry": _cell(r, mapping, "industry"),
                         "region": _cell(r, mapping, "region"), "year": _cell(r, mapping, "year"), "summary": summary,
                         "technologies": list(dict.fromkeys(techs + K.find_technologies(f"{title} {summary}"))),
                         "outcomes": [o for o in re.split(r"[;\n]+", _cell(r, mapping, "outcomes")) if o.strip()]})

    elif kind == "accelerators":
        for r in data:
            name = _cell(r, mapping, "name")
            if not name:
                continue
            desc = _cell(r, mapping, "description")
            techs = _dedupe(_split_list(_cell(r, mapping, "technologies")))
            recs.append({"name": name, "description": desc, "technologies": list(dict.fromkeys(techs + K.find_technologies(f'{name} {desc}'))),
                         "effort_saving_pct": _num(_cell(r, mapping, "effort_saving_pct")) or 0})
    return recs


# --------------------------------------------------------------------------- documents
OUTCOME_RE = re.compile(r"(\d+\s?%|\d+x\b|reduc|improv|increas|saved|faster|uptime|zero|accelerat|cut\b)", re.I)


def records_from_document(kind: str, doc: ParsedDocument, use_ai: bool = True) -> list[dict]:
    if use_ai and llm.is_enabled():
        try:
            recs = llm_records(kind, doc)
            if recs:
                return recs
        except Exception:
            pass
    blocks = doc.blocks
    if kind in ("capabilities", "accelerators"):
        recs, cur = [], None
        for b in blocks:
            if b.kind == "heading" and 2 < len(b.text) < 90:
                if cur and (cur["description"] or cur["bullets"]):
                    recs.append(cur)
                cur = {"name": b.text.rstrip(":"), "description": "", "bullets": []}
            elif cur is not None:
                if b.kind == "bullet":
                    cur["bullets"].append(b.text)
                else:
                    cur["description"] = (cur["description"] + " " + b.text).strip()
        if cur and (cur["description"] or cur["bullets"]):
            recs.append(cur)
        out = []
        for c in recs:
            desc = (c["description"] + (" " if c["description"] else "") + "; ".join(c["bullets"]))[:1500]
            techs = K.find_technologies(f"{c['name']} {desc}")
            if kind == "capabilities":
                out.append({"name": c["name"], "service_line": "", "description": desc, "technologies": techs,
                            "industries": [], "maturity": ""})
            else:
                out.append({"name": c["name"], "description": desc, "technologies": techs, "effort_saving_pct": 0})
        return out
    if kind == "case_studies":
        text = doc.text
        title = next((b.text for b in blocks if b.kind == "heading"), blocks[0].text if blocks else doc.filename)
        client = ""
        m = re.search(r"client\s*[:\-]\s*([^\n.]{2,80})", text, re.I)
        if m:
            client = m.group(1).strip()
        industry = ""
        m = re.search(r"industry\s*[:\-]\s*([^\n.]{2,60})", text, re.I)
        if m:
            industry = m.group(1).strip()
        outcomes = [b.text for b in blocks if b.kind in ("bullet", "para") and OUTCOME_RE.search(b.text) and len(b.text) < 240][:6]
        summary = " ".join(b.text for b in blocks if b.kind == "para")[:1200]
        return [{"title": title[:200], "client": client, "industry": industry, "region": "", "year": "",
                 "summary": summary, "technologies": K.find_technologies(text), "outcomes": outcomes}]
    if kind == "certifications":
        out = []
        for b in blocks:
            for line in re.split(r"[\n;]", b.text):
                l = line.strip(" -•")
                if re.search(r"\biso\s?\d|cmmi|soc ?2|pci|certified|certification|partner", l, re.I) and 3 < len(l) < 120:
                    out.append({"name": l, "kind": "company" if re.search(r"iso|cmmi|soc|pci", l, re.I) else "partner",
                                "issuer": "", "holders": 0, "valid_until": ""})
        return out
    return []


def llm_records(kind: str, doc: ParsedDocument) -> list[dict]:
    schema = {
        "capabilities": '{"name","service_line","description","technologies":[...],"industries":[...]}',
        "case_studies": '{"title","client","industry","region","year","summary","technologies":[...],"outcomes":[...]}',
        "certifications": '{"name","kind":"company|partner|individual","issuer","holders":int,"valid_until"}',
        "accelerators": '{"name","description","technologies":[...],"effort_saving_pct":number}',
        "skills": '{"code","name","role","level","years":number,"location","skills":[{"name","level":1-5}],"certifications":[...],"availability":number}',
        "rates": '{"role","level","location":"Onsite|Offshore|Nearshore","day_rate":number,"day_cost":number,"currency"}',
    }[kind]
    text = doc.text[:24000]
    items = llm.complete_json("You convert company documents into structured records for a bid-management system. Only use facts present in the text.",
                              f"Extract {KINDS[kind]} from this document as a JSON array of objects shaped like {schema}.\n\n{text}")
    return items if isinstance(items, list) else []


def missing_fields(kind: str, a: dict) -> list[str]:
    missing = [f for f in REQUIRED[kind] if f not in a["mapping"]]
    if kind == "skills" and not a.get("wide_skill_columns") and not any(f in a["mapping"] for f in ("skills", "skill")):
        missing.append("skills")
    return missing


def analyze(kind: str, doc: ParsedDocument, use_ai: bool = True) -> dict:
    """Returns an analysis with a suggested mapping (tables) and preview records."""
    if doc.tables:
        rows = max(doc.tables, key=len)
        a = analyze_table(kind, rows)
        a["records"] = records_from_table(kind, rows, a)
        a["missing"] = missing_fields(kind, a)
        a["fields"] = list(FIELDS[kind].keys())
        return a
    recs = records_from_document(kind, doc, use_ai)
    return {"format": "document", "records": recs, "missing": [] if recs else ["records"], "fields": list(FIELDS[kind].keys())}
