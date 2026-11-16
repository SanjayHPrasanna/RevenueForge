"""Proposal validation: every client-facing sentence is checked before the documents are written, whatever wrote it
(the answer library, the AI, the rules engine or a person).

Rules are generic, driven by the company's own library and this RFP, never by a list of domains:
  unsupported  names a capability, case study, accelerator or certificate that is not this requirement's evidence
               (certificates: not in the register)
  foreign      uses words that only belong to the company's work in *other* industries (taken from its industry-tagged
               library items) and that this RFP never uses: "hospital" in an insurer's SOC bid
  internal     reads like our own to-do or notes ("add a reference project", employee codes, REQ ids)
  duplicate    the same paragraph answers different requirements
Errors (unsupported, internal; foreign in a person's answer) block approval of the proposal until fixed or overridden;
a foreign or duplicate answer from the library/AI/rules is rewritten or trimmed automatically before it gets that far.
"""
from __future__ import annotations

import re
from collections import Counter

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#&'-]*")
SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[(])")

# Words any IT bid uses whatever the industry (domain-neutral; never a list of industries or technologies).
GENERIC = set("""
about above after again against also among answer applic approach based been before being below between both build built
business capability capabilities case cases certified client clients cloud company completed consolidating consolidation
contract cost costs customer customers data delivered deliver delivering delivery deploy deployed design designed
detail details different digital during each engagement ensure every evidence experience expertise first from full
group have high including integration into itself large layer leveraging leverage managed management model monitoring
more most multi needs only operations other over part partner people platform platforms portal portals process programme
project projects proven provide provided provides quality real reference references regional reporting reports requirement
requirements response same scale secure security service services shall should since single solution solutions specific
standard standards strong support system systems team teams technical technology than that their them then there these
they this those through time tools under unified using very well were what when where which while will with within work
year years your users user access across apps application applications mobile online self web replaced point links governed
api apis rest analytics dashboard dashboards assistant pilot drafting summaries summary summarise local india south north
east west middle confidential chain
kpi kpis sla slas api uat sso mfa ui ux bi etl elt crm erp faq sme poc rpo rto itil itsm sdk cli gui dr ha qa ci cd
""".split())

INTERNAL_RE = re.compile(
    r"\b(we (?:plan|intend|will need) to add (?:a )?(?:reference|demo|named expert)|reference project, demo|named expert to (?:our|the) "
    r"(?:response|bid)|to (?:our|the) (?:final )?response\b|\(\+\d+ to hire\)|to be hired|knowledge library|evidence is thin|thin evidence|"
    r"add (?:a )?reference project|internal review|remove before sending|\[internal|REQ-\d{2,4}|KD\d{3}\b)", re.I)

CERT_CLAIM_RE = re.compile(r"\b(?:ISO(?:/IEC)?\s?\d{4,5}(?::\d{4})?|SOC\s?[12](?:\s+Type\s+I{1,2})?|CMMI(?:\s+(?:Level|ML)\s?\d)?|PCI[ -]DSS|"
                           r"CERT-In[- ]empanell?ed|Cyber Essentials(?: Plus)?)", re.I)
NOT_HELD_RE = re.compile(r"\b(do(?:es)? not|don't|doesn't|not (?:yet|currently)|no current|without|pursuing|will (?:obtain|achieve|pursue)|"
                         r"working towards|plan to (?:obtain|achieve)|partner(?:s|ing)? (?:with|that holds?)|via (?:our|a) partner|through (?:our|a) partner)\b", re.I)

INDUSTRY_GROUPS = [
    {"healthcare", "health", "hospital", "pharma", "life sciences", "medical", "clinical", "patient"},
    {"bfsi", "banking", "bank", "insurance", "insurer", "financial", "finance", "lending", "nbfc", "capital markets", "fintech"},
    {"retail", "distribution", "fmcg", "consumer", "e-commerce", "ecommerce"},
    {"transportation", "logistics", "transport", "rail", "aviation", "shipping", "freight"},
    {"government", "public sector", "public", "municipal", "ministry", "citizen"},
    {"telecom", "telecommunications"},
    {"energy & utilities", "energy", "utilities", "utility", "oil and gas", "power"},
    {"manufacturing", "industrial", "factory"},
    {"education", "university", "school"},
]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def tokens(text: str) -> set[str]:
    out = set()
    for w in WORD_RE.findall(text or ""):
        if len(w) >= 2 and w.isupper() and len(w) <= 6:
            out.add(w)  # acronyms keep their case: "HIS" is not "his"
        elif len(w) >= 4:
            out.add(w.lower().strip("'-"))
    return out


def _group(industry: str) -> int | None:
    l = (industry or "").lower()
    for i, g in enumerate(INDUSTRY_GROUPS):
        if any(k in l for k in g):
            return i
    return None


def same_industry(a: str, b: str) -> bool:
    ga, gb = _group(a), _group(b)
    return ga is not None and ga == gb


def _industry_of_text(text: str) -> int | None:
    l = " " + (text or "").lower() + " "
    for i, g in enumerate(INDUSTRY_GROUPS):
        if any(re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", l) for k in g if len(k) > 3):
            return i
    return None


def foreign_vocabulary(kb, deal_industry: str, rfp_text: str) -> set[str]:
    """Words that mark the company's work in other industries and that this RFP never uses.

    Domain-marked items: case studies (a client project has an industry) and capabilities or accelerators whose own name or
    description names an industry ("Healthcare KPI Dashboard Pack: dashboards for hospital KPIs"). Plain IT practices are
    neutral. A title counts double, a description once; a word needs a weight of 2 (an acronym 1). Excluded: words in any
    neutral or same-industry item, words used by two or more other industries (generic), technology names (the company's
    tech vocabulary is never "foreign") and anything this RFP itself says."""
    rfp = {t.lower() for t in tokens(rfp_text)} | set(tokens(rfp_text))
    deal_g = _group(deal_industry)
    inside: set[str] = set()
    weight: Counter = Counter()
    groups_of: dict[str, set] = {}
    tech: set[str] = set()
    items = []
    for c in getattr(kb, "capabilities", []):
        txt = c.get("name", "") + " " + c.get("description", "")
        items.append((_industry_of_text(txt), c.get("name", ""), c.get("description", "")))
        tech |= {w.lower() for t in c.get("technologies", []) for w in tokens(t)}
    for a in getattr(kb, "accelerators", []):
        txt = a.get("name", "") + " " + a.get("description", "")
        items.append((_industry_of_text(txt), a.get("name", ""), a.get("description", "")))
        tech |= {w.lower() for t in a.get("technologies", []) for w in tokens(t)}
    for cs in getattr(kb, "case_studies", []):
        g = _group(cs.get("industry", "")) if cs.get("industry") else _industry_of_text(cs.get("title", "") + " " + cs.get("summary", ""))
        items.append((g, cs.get("title", ""), " ".join([cs.get("summary", "")] + list(cs.get("outcomes") or []))))
        tech |= {w.lower() for t in cs.get("technologies", []) for w in tokens(t)}
    for e in getattr(kb, "employees", []):
        tech |= {w.lower() for s in e.get("skills", []) for w in tokens(s.get("name", "") if isinstance(s, dict) else str(s))}
    for g, title, body in items:
        allt = tokens(title + " " + body)
        if g is None or g == deal_g:
            inside |= {t.lower() for t in allt} | allt
            continue
        tt, bt = tokens(title), tokens(body)
        for t in tt:
            weight[t] += 2
        for t in bt - tt:
            weight[t] += 1
        for t in allt:
            groups_of.setdefault(t, set()).add(g)
    out = set()
    for t, w in weight.items():
        acronym = t.isupper()
        lt = t.lower()
        if (w >= 2 or acronym) and t not in inside and lt not in inside and lt not in GENERIC and lt not in tech \
                and t not in rfp and lt not in rfp and not t.isdigit() and len(groups_of.get(t, ())) < 2 \
                and not re.fullmatch(r"[A-Z]\d", t) and (acronym or len(t) >= 5):
            out.add(t)
    return out


def _mentions(text_n: str, name: str) -> bool:
    n = _norm(name)
    if not n or len(n) < 6:
        return False
    return re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", text_n) is not None


class Checker:
    """Holds what one deal's checks need: the library's named entities, the held certificates and the foreign words."""

    def __init__(self, kb, deal_industry: str, rfp_text: str, company: str = ""):
        self.company = company
        self.foreign = foreign_vocabulary(kb, deal_industry, rfp_text)
        self.rfp_n = _norm(rfp_text)
        self.entities = []  # (type, name)
        for c in getattr(kb, "capabilities", []):
            self.entities.append(("Capability", c.get("name", "")))
        for cs in getattr(kb, "case_studies", []):
            self.entities.append(("Case study", cs.get("title", "")))
        for a in getattr(kb, "accelerators", []):
            self.entities.append(("Accelerator", a.get("name", "")))
        self.held = set()
        for c in getattr(kb, "certifications", []):
            self.held.add(_norm(c.get("name", "")))

    def check(self, text: str, req: dict | None = None, human: bool = False) -> list[dict]:
        issues = []
        if not text:
            return issues
        tn = _norm(text)
        allowed = {_norm(e.get("name", "")) for e in ((req or {}).get("match") or {}).get("evidence", [])}
        req_n = _norm((req or {}).get("text", ""))
        for typ, name in self.entities:
            if _mentions(tn, name) and _norm(name) not in allowed and not _mentions(req_n, name):
                issues.append({"rule": "unsupported", "severity": "error", "detail": f"names {typ.lower()} \"{name}\", which is not evidence for this requirement",
                               "term": name})
        for m in CERT_CLAIM_RE.finditer(text):
            if self._holds(m.group(0)):
                continue
            sent = next((s for s in SENT_RE.split(text) if m.group(0) in s), text)
            if NOT_HELD_RE.search(sent):
                continue  # "we do not hold SOC 2 today; we will..." is an honest statement, not a claim
            issues.append({"rule": "unsupported", "severity": "error", "detail": f"claims \"{m.group(0).strip()}\", which is not in the certificate register",
                           "term": m.group(0).strip()})
        # names of this requirement's own evidence are facts, not borrowed wording ("our Patient & Customer Portals capability")
        bare = text
        for e in ((req or {}).get("match") or {}).get("evidence", []):
            if e.get("name"):
                bare = re.sub(re.escape(e["name"]), " ", bare, flags=re.I)
        found = sorted({t for t in tokens(bare) if t in self.foreign or (t.lower() in self.foreign and not t.isupper())})
        if found:
            issues.append({"rule": "foreign", "severity": "error" if human else "warning",
                           "detail": "uses wording from the company's work in other industries: " + ", ".join(found[:6]), "terms": found})
        for m in INTERNAL_RE.finditer(text):
            issues.append({"rule": "internal", "severity": "error", "detail": f"internal wording: \"{m.group(0)}\"", "term": m.group(0)})
        return issues

    def _holds(self, claim: str) -> bool:
        c = _norm(claim)
        num = re.search(r"\d{4,5}", c)
        if num:  # ISO 27001 / ISO/IEC 27001:2022: the standard number decides
            return any(num.group(0) in h for h in self.held)
        key = re.sub(r"\b(empanell?ed|empanelment|certified|certification|type|report)\b", " ", c).split()
        return any(all(k in h.split() for k in key) for h in self.held) if key else True

    def clean(self, text: str, issues: list[dict]) -> str:
        """Drop the sentences that carry an issue; what's left must still read as an answer."""
        bad_terms = []
        for i in issues:
            if i.get("terms"):
                bad_terms += i["terms"]
            elif i.get("term"):
                bad_terms.append(i["term"])
        keep = []
        for s in SENT_RE.split(text.strip()):
            sn = _norm(s)
            hit = any((_norm(t) and re.search(r"(?<![a-z0-9])" + re.escape(_norm(t)) + r"(?![a-z0-9])", sn)) for t in bad_terms)
            if not hit and not INTERNAL_RE.search(s):
                keep.append(s)
        out = " ".join(keep).strip()
        return out if len(out) >= 40 else ""


def honest_fallback(req: dict, company: str) -> str:
    """When nothing else survives the checks: an answer that states the position without claiming anything."""
    opt = ((req.get("gap") or {}).get("options") or [{}])[0].get("type") if req.get("match_status") in ("gap", "partial") else None
    return {
        "Partner": f"We will meet this through a specialist partner that holds the required capability and credentials, with {company} as prime contractor.",
        "Hire": "We will appoint a specialist who meets this requirement before mobilisation and name them in the delivery plan.",
        "Certify": f"{company} does not hold this today and is working towards it; please confirm whether it is mandatory at award.",
        "Upskill": "Our team will complete the training and certification this requires ahead of mobilisation.",
    }.get(opt or "", f"{company} does not fully meet this requirement today; our mitigation is set out in the risks and mitigations section of this proposal.")


def topic_overlap(a: str, b: str) -> float:
    """Share of content words two texts have in common (bid boilerplate and generic IT words don't count)."""
    ta = {t.lower() for t in tokens(a)} - GENERIC - {"bidder", "bidders", "tenderer", "vendor", "supplier"}
    tb = {t.lower() for t in tokens(b)} - GENERIC - {"bidder", "bidders", "tenderer", "vendor", "supplier"}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def validate_answers(rows: list[dict], checker: Checker) -> dict:
    """Report over the final answers: rows are requirement dicts with "response" and "response_source"."""
    errors, warnings = [], []
    seen: dict[str, str] = {}
    for r in rows:
        txt = (r.get("response") or "").strip()
        if not txt or r.get("category") == "Commercial":
            continue
        ref = r.get("source_ref") or r.get("code")
        human = r.get("response_source") == "human"
        for i in checker.check(txt, r, human=human):
            (errors if i["severity"] == "error" else warnings).append({"ref": ref, "code": r.get("code"), **i})
        key = _norm(txt)
        if len(key) > 80:
            if key in seen and _norm(r.get("text", ""))[:80] != seen[key]:
                warnings.append({"ref": ref, "code": r.get("code"), "rule": "duplicate", "severity": "warning",
                                 "detail": "the same answer is used for another requirement"})
            seen.setdefault(key, _norm(r.get("text", ""))[:80])
    return {"errors": errors, "warnings": warnings, "checked": sum(1 for r in rows if (r.get("response") or "").strip())}


def clean_prose(text: str, checker: Checker, keep_tech: set[str] | None = None) -> str:
    """Executive summary and architecture summary: drop sentences with foreign or internal wording."""
    if not text:
        return text
    out = []
    for para in text.split("\n"):
        sents = []
        for s in SENT_RE.split(para):
            iss = [i for i in checker.check(s) if i["rule"] in ("foreign", "internal")]
            if not iss:
                sents.append(s)
        out.append(" ".join(sents))
    res = "\n".join(p for p in out)
    return res if res.strip() else text
