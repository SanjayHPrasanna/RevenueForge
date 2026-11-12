"""Stages 2 & 3 - Capability Matching and Gap Analysis.

Each requirement is scored against the company's own knowledge: capabilities, case studies,
accelerators, certifications and the skills of its people. Every match carries the evidence it
was based on, so proposals can cite real assets rather than invent them.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from . import knowledge as K
from . import llm


@dataclass
class CompanyKB:
    name: str
    capabilities: list[dict] = field(default_factory=list)
    case_studies: list[dict] = field(default_factory=list)
    accelerators: list[dict] = field(default_factory=list)
    certifications: list[dict] = field(default_factory=list)
    employees: list[dict] = field(default_factory=list)
    rates: list[dict] = field(default_factory=list)
    won_capabilities: dict[str, int] = field(default_factory=dict)  # capability id -> wins (learning loop)

    def tech_inventory(self) -> dict[str, dict]:
        """tech -> {people, avg_level, capabilities, case_studies}"""
        inv: dict[str, dict] = defaultdict(lambda: {"people": 0, "levels": [], "capabilities": [], "case_studies": [], "available": 0})
        for e in self.employees:
            held: dict[str, int] = {}
            for s in e.get("skills", []):
                for t in K.techs_in(s["name"]):
                    held[t] = max(held.get(t, 0), s.get("level", 0))
            for t, lvl in held.items():  # once per person, even if two of their skills name the same technology
                if lvl >= 2:
                    inv[t]["people"] += 1
                    inv[t]["levels"].append(lvl)
                    if e.get("availability", 100) >= 50:
                        inv[t]["available"] += 1
        for c in self.capabilities:
            for t in {x for name in c.get("technologies", []) for x in K.techs_in(name)}:
                inv[t]["capabilities"].append(c["name"])
        for cs in self.case_studies:
            for t in {x for name in cs.get("technologies", []) for x in K.techs_in(name)}:
                inv[t]["case_studies"].append(cs["title"])
        out = {}
        for t, v in inv.items():
            out[t] = {"people": v["people"], "available": v["available"],
                      "avg_level": round(sum(v["levels"]) / len(v["levels"]), 1) if v["levels"] else 0,
                      "capabilities": sorted(set(v["capabilities"])), "case_studies": sorted(set(v["case_studies"]))}
        return out


def _cap_text(c):
    return f"{c['name']} {c.get('service_line', '')} {c.get('description', '')} {' '.join(c.get('technologies', []))} {' '.join(c.get('industries', []))}"


def _cs_text(c):
    return f"{c['title']} {c.get('summary', '')} {' '.join(c.get('technologies', []))} {' '.join(c.get('outcomes', []))} {c.get('industry', '')}"


def _acc_text(a):
    return f"{a['name']} {a.get('description', '')} {' '.join(a.get('technologies', []))}"


# Requirement-type context added to the query so short operational requirements find the right capability.
SUBCAT_CONTEXT = {
    "Service Levels": "sla service levels managed services incident support operations 24x7 response resolution",
    "Monitoring & Operations": "monitoring operations managed services alerts queues health checks support platform",
    "Maintainability & Quality": "devops release management version control change management documentation runbooks",
    "Availability & Continuity": "disaster recovery business continuity high availability failover backup resilience",
    "Performance & Scalability": "performance tuning capacity planning scalability platform engineering",
    "Transition & Knowledge Transfer": "transition knowledge transfer onboarding incumbent baselining runbooks governance",
    "Project Management": "delivery governance project management agile sprint reporting service review",
    "Testing & QA": "testing validation quality assurance test evidence go-live",
    "Support & Incident Management": "incident problem management rca support managed services troubleshooting",
    "Security": "security encryption access control audit logging iam",
    "Integration & APIs": "integration interfaces apis middleware messaging",
    "Architecture & Advisory": "architecture assessment roadmap advisory target state",
    "Data & Analytics": "data analytics reporting dashboards",
    "Fraud & Risk Analytics": "fraud risk analytics detection scoring",
    "Application Development": "application development engineering build configure",
}
# Tender-process obligations (how to respond), not delivery work. "The bidder shall provide X" is delivery work, so the
# words bidder/tenderer alone don't count.
PROCESS_RE = re.compile(r"\b(tender documents?|proposals?|offer|rfp|rfi|submission|responses?|in their response|notification|addend\w*|"
                        r"clarification|site visit|visit|examine|alteration|value-added|complimentary|methods? statement|aggregates)\b", re.I)

ISO_RE = re.compile(r"iso\s*/?\s*(?:iec\s*)?(\d{4,5})", re.I)
# Named standards and attestations checked against the company's certificate register (not by text similarity).
STANDARDS = [
    ("SOC 2", re.compile(r"\bsoc\s*-?\s*2\b|\bsoc\s*ii\b", re.I)),
    ("SOC 1", re.compile(r"\bsoc\s*-?\s*1\b", re.I)),
    ("PCI DSS", re.compile(r"\bpci(?:[\s-]*dss)?\b", re.I)),
    ("HITRUST", re.compile(r"\bhitrust\b", re.I)),
    ("HIPAA", re.compile(r"\bhipaa\b", re.I)),
    ("CMMI", re.compile(r"\bcmmi\b", re.I)),
    ("Cyber Essentials", re.compile(r"\bcyber\s+essentials\b", re.I)),
    ("FedRAMP", re.compile(r"\bfedramp\b", re.I)),
    ("IRAP", re.compile(r"\birap\b", re.I)),
    ("CSA STAR", re.compile(r"\bcsa\s+star\b", re.I)),
    ("TISAX", re.compile(r"\btisax\b", re.I)),
    ("Essential Eight", re.compile(r"\bessential\s+eight\b", re.I)),
]
# Wording that asks the bidder itself to hold a certificate (rather than build a solution that follows a standard).
HOLD_RE = re.compile(r"\b(hold|holds|held|certif\w*|attest\w*|accredit\w*|authori[sz]ed|authori[sz]ation|audit(?:ed)?\s+report|registered|maintain\s+(?:a\s+)?current)\b", re.I)


def standards_in(text: str) -> set[str]:
    """Named standards in a text: 'ISO 27001', 'SOC 2', 'PCI DSS', ..."""
    found = {f"ISO {m}" for m in ISO_RE.findall(text or "")}
    found |= {name for name, rx in STANDARDS if rx.search(text or "")}
    return found


def relevant_accelerators(kb: CompanyKB, reqs: list[dict]) -> list[dict]:
    """Accelerators whose technologies (or purpose) actually appear in this RFP. An accelerator named after a technology
    the RFP never mentions (an "FHIR Starter Kit" for a transit bid) is never applied."""
    text_all = " ".join(r["text"] for r in reqs).lower()
    req_tech = {K.canonical_tech(t) for r in reqs for t in r.get("technologies", [])}
    out = []
    for a in kb.accelerators:
        if not a.get("effort_saving_pct"):
            continue
        techs = [K.canonical_tech(t) for t in a.get("technologies", []) if t]
        def present(t):
            return t in req_tech or t.lower() in text_all
        core = [t for t in techs if any(w in a["name"].lower() for w in re.findall(r"[a-z0-9]{3,}", t.lower()))]
        if any(not present(t) for t in core):
            continue
        hits = [t for t in techs if present(t) and t not in K.COMMODITY_TECH]
        words = {w for w in re.findall(r"[a-z][a-z0-9]{5,}", (a.get("description", "") + " " + a["name"]).lower())}
        purpose = sum(1 for w in words if w in text_all)
        if (techs and len(hits) >= max(1, math.ceil(len(techs) / 2))) or (hits and purpose >= 3):
            out.append({"name": a["name"], "saving_pct": a["effort_saving_pct"], "matched": hits})
    return out


def _blend_embeddings(tfidf, emb) -> list[list[float]]:
    """Put embedding cosines on the TF-IDF scale the scorer expects.

    Embedding models give almost any two business texts a high cosine (Gemini: about 0.6-0.9), so a fixed offset
    over-scores everything. Instead each cosine is placed relative to all pairs in this deal: only pairs in the top
    quarter count at all, and only the very closest reach the full TF-IDF-equivalent score. The result is averaged with
    TF-IDF (shared words) rather than taking the higher of the two, so one generous signal can't carry a match alone.
    """
    flat = sorted(e for row in emb for e in row)
    if not flat:
        return tfidf
    def pct(q):
        return flat[min(len(flat) - 1, int(q * (len(flat) - 1)))]
    lo, hi = pct(0.75), pct(0.995)
    span = max(1e-6, hi - lo)
    out = []
    for trow, erow in zip(tfidf, emb):
        out.append([0.5 * t + 0.5 * max(0.0, min(1.0, (e - lo) / span)) * 0.34 for t, e in zip(trow, erow)])
    return out
CONFIRM_SUBS = {"Pricing & Payment", "Bonds & Guarantees", "Insurance & Liability", "Contract Terms", "Evaluation & Award", "Submission"}


_STOP = {"this", "that", "with", "from", "shall", "should", "must", "will", "their", "which", "where", "within", "across"}


def _stem(w: str) -> str:
    """A light English stemmer, so "portals"/"portal" and "migrating"/"migration"/"migrate" meet."""
    if len(w) <= 4 or w in _STOP:
        return w
    for suf, rep in (("ations", "ate"), ("ation", "ate"), ("ities", "ity"), ("ies", "y"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)] + rep
            break
    return w[:-1] if w.endswith("e") and len(w) > 5 else w


def _stem_text(text: str) -> str:
    return " ".join(_stem(w) for w in re.findall(r"[a-z0-9]+(?:[./][a-z0-9]+)*", text.lower()))


_STEMMED_STOP = sorted({_stem(w) for w in ENGLISH_STOP_WORDS} | {_stem(_stem(w)) for w in ENGLISH_STOP_WORDS} | set(ENGLISH_STOP_WORDS))

_STEMMED_STOP_SET = set(_STEMMED_STOP)

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def cert_expiry(c: dict):
    """The date a certificate stops being valid, or None when the register doesn't say (or says it in a way we can't read)."""
    import calendar
    from datetime import date
    v = str(c.get("valid_until") or "").strip().lower()
    if not v:
        return None
    try:
        m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", v)
        if m:
            return date(int(m[1]), int(m[2]), int(m[3]))
        m = re.search(r"(\d{1,2})[/.](\d{1,2})[/.](\d{4})", v)
        if m:  # day/month/year, the usual order outside the US
            return date(int(m[3]), int(m[2]), int(m[1]))
        m = re.search(r"(\d{4})-(\d{1,2})\b", v) or re.search(r"\b(\d{1,2})/(\d{4})\b", v)
        if m:
            y, mo = (int(m[1]), int(m[2])) if len(m[1]) == 4 else (int(m[2]), int(m[1]))
            return date(y, mo, calendar.monthrange(y, mo)[1])
        m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{4})\b", v)
        if m:
            y, mo = int(m[2]), _MONTHS[m[1]]
            return date(y, mo, calendar.monthrange(y, mo)[1])
        m = re.fullmatch(r"(\d{4})", v)
        if m:
            return date(int(m[1]), 12, 31)
    except ValueError:
        return None
    return None


def current_certs(certs: list[dict]) -> list[dict]:
    """Certificates that are valid today. One whose 'valid until' date has passed is not evidence of anything."""
    from datetime import date
    today = date.today()
    return [c for c in certs if not ((d := cert_expiry(c)) and d < today)]


def squash_repeats(text: str, keep: int = 2) -> str:
    """Saying a word ten times adds nothing, so only its first couple of uses count ("Azure Azure Azure ..." -> "Azure Azure")."""
    seen: dict[str, int] = defaultdict(int)
    out = []
    for tok in re.findall(r"\S+", text or ""):
        key = re.sub(r"[^a-z0-9+#]", "", tok.lower())
        if key:
            seen[key] += 1
            if seen[key] > keep:
                continue
        out.append(tok)
    return " ".join(out)


# Words every requirement uses ("the supplier shall provide ..."). They say nothing about WHAT is asked, so they never count
# as evidence that the company covers it.
_GENERIC = {_stem(w) for w in """supplier suppliers contractor contractors bidder bidders vendor vendors provider providers tenderer tenderers
respondent respondents proposer solution solutions service services system systems shall must should will may provide provides providing
deliver delivers delivered design designs designed build builds built implement implements implemented implementation maintain
maintains support supports supported ensure ensures include includes including use uses using used based able ability capable capability
capabilities required require requires requirement requirements also new existing current following within across per etc via
host hosted hosting company client authority customer buyer offer offers proposed propose relevant appropriate suitable full fully
""".split()}


def _vocab(kb: "CompanyKB") -> set[str]:
    """Every (stemmed) word the company's library uses: capabilities, case studies, accelerators, skills, roles, certificates."""
    parts = [_cap_text(c) for c in kb.capabilities] + [_cs_text(c) for c in kb.case_studies] + [_acc_text(a) for a in kb.accelerators]
    for e in kb.employees:
        parts.append(f"{e.get('role', '')} {e.get('practice', '')} " + " ".join(sk.get("name", "") for sk in e.get("skills", [])))
    parts += [c.get("name", "") for c in kb.certifications]
    return set(_stem_text(K.expand(" ".join(parts))).split())


def _domain_terms(text: str, techs: list[str]) -> dict[str, str]:
    """What the requirement is about, beyond product names and boilerplate: distinct content words (stem -> word as written)."""
    tech_words = set()
    for t in techs:
        for alias in [t] + list(K.TECHNOLOGIES.get(t, [])):
            tech_words |= set(re.findall(r"[a-z0-9]+", str(alias).lower()))
    out: dict[str, str] = {}
    for w in re.findall(r"[a-z][a-z0-9]+", text.lower()):
        if len(w) < 3 or w in tech_words or w in ENGLISH_STOP_WORDS:
            continue
        st = _stem(w)
        if st in _GENERIC or st in _STEMMED_STOP_SET or st in out:
            continue
        out[st] = w
    return out


def _covered(term: str, vocab: set[str]) -> bool:
    if term in vocab:
        return True
    syn = K.SYNONYMS.get(term)
    return bool(syn and any(_stem(x) in vocab for x in syn.split()))


def match_requirements(reqs: list[dict], kb: CompanyKB, engagement_type: str = "", industry: str = "", similarity=None,
                       guidance: str = "", progress=None, use_ai: bool = True) -> list[dict]:
    """Adds match_status, match_score and match evidence to each requirement dict (in place) and returns them.

    similarity: optional callable(queries, docs) -> (matrix, method) supplying semantic (embedding) similarity.
    """
    if not reqs:
        return reqs
    inv = kb.tech_inventory()
    company_techs = {t for t, v in inv.items() if v["people"] or v["capabilities"]}
    caps, css = kb.capabilities, kb.case_studies
    useful = {a["name"] for a in relevant_accelerators(kb, reqs)}
    accs = [a for a in kb.accelerators if a["name"] in useful]  # never cite an accelerator built for another domain
    docs = [K.expand(squash_repeats(_cap_text(c))) for c in caps] + [K.expand(squash_repeats(_cs_text(c))) for c in css] + \
        [K.expand(squash_repeats(_acc_text(a))) for a in accs]
    qtexts = [K.expand(f"{squash_repeats(r['text'])} {r.get('section', '')} {' '.join(r.get('technologies', []))} "
                       f"{SUBCAT_CONTEXT.get(r.get('subcategory', ''), '')}") for r in reqs]
    if not docs:
        docs = ["empty"]
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words=_STEMMED_STOP, min_df=1, preprocessor=_stem_text)
    vec.fit(docs + qtexts)
    D = vec.transform(docs)
    Q = vec.transform(qtexts)
    sims = cosine_similarity(Q, D) if len(reqs) else []
    method = "tfidf"
    if similarity is not None and len(reqs) and docs != ["empty"]:
        raw_docs = [_cap_text(c) for c in caps] + [_cs_text(c) for c in css] + [_acc_text(a) for a in accs]
        raw_q = [f"{r['text']} ({r.get('section', '')})" for r in reqs]
        emb, method = similarity(raw_q, raw_docs)
        if method == "embeddings":
            sims = _blend_embeddings(sims, emb)
    nc, ncs = len(caps), len(css)
    vocab = _vocab(kb)
    held_std: dict[str, list[str]] = defaultdict(list)  # standard -> certificate names that evidence it
    expired_std: dict[str, str] = {}  # standard -> "SOC 2 Type II (expired 2019-01-01)"
    live = current_certs(kb.certifications)
    for c in kb.certifications:
        if c not in live:
            for sname in standards_in(c["name"]):
                expired_std[sname] = f"{c['name']} (expired {cert_expiry(c).isoformat()})"
    for c in live:
        for sname in standards_in(f"{c['name']} {c.get('description', '')}"):
            held_std[sname].append(c["name"])

    for i, r in enumerate(reqs):
        row = sims[i] if len(reqs) else []
        cap_scores = sorted(((row[j], j) for j in range(nc)), reverse=True)[:3]
        cs_scores = sorted(((row[nc + j], j) for j in range(ncs)), reverse=True)[:2]
        acc_scores = sorted(((row[nc + ncs + j], j) for j in range(len(accs))), reverse=True)[:1]

        def norm(s, scale=0.32):
            return max(0.0, min(1.0, s / scale))

        best_cap = cap_scores[0] if cap_scores else (0, None)
        cap_s = norm(best_cap[0])
        if best_cap[1] is not None and caps[best_cap[1]].get("id") in kb.won_capabilities:
            cap_s = min(1.0, cap_s + 0.05)  # learning loop: capabilities that helped win before get a small boost
        cs_s = norm(cs_scores[0][0], 0.28) if cs_scores else 0
        req_techs = [t for t in r.get("technologies", []) if t not in K.COMMODITY_TECH]
        have = [t for t in req_techs if t in company_techs]
        missing = [t for t in req_techs if t not in company_techs]
        tech_cov = (len(have) / len(req_techs)) if req_techs else None
        people = sorted({e["code"] for e in kb.employees for s in e.get("skills", [])
                         if s.get("level", 0) >= 3 and K.techs_in(s["name"]) & set(have)})

        industry_bonus = 0.04 if industry and any(industry.lower() in " ".join(c.get("industries", [])).lower() for c in caps) else 0
        if tech_cov is None:
            score = 0.72 * cap_s + 0.28 * cs_s + industry_bonus
        else:
            score = 0.45 * cap_s + 0.15 * cs_s + 0.40 * tech_cov
        score = round(min(0.99, score + (0.05 if people else 0)), 2)

        evidence = []
        for s, j in cap_scores:
            if s > 0.06:
                evidence.append({"type": "Capability", "id": caps[j].get("id", ""), "name": caps[j]["name"], "score": round(norm(s), 2)})
        for s, j in cs_scores:
            if s > 0.06:
                evidence.append({"type": "Case study", "id": css[j].get("id", ""), "name": css[j]["title"], "score": round(norm(s, 0.28), 2)})
        for s, j in acc_scores:
            if s > 0.08:
                evidence.append({"type": "Accelerator", "id": accs[j].get("id", ""), "name": accs[j]["name"], "score": round(norm(s), 2),
                                 "saving": accs[j].get("effort_saving_pct", 0)})

        status = "strong" if score >= 0.62 else "partial" if score >= 0.35 else "gap"
        if missing and status == "strong":
            status = "partial"
        rationale = []

        sub = r.get("subcategory", "")
        # Certification / standards requirements are checked against the certificate register, never by text similarity.
        stds = standards_in(r["text"])
        if stds:
            held = sorted(s_ for s_ in stds if s_ in held_std)
            lacking = sorted(stds - set(held))
            certs = sorted({n for s_ in held for n in held_std[s_]})
            evidence = [{"type": "Certification", "name": c, "score": 1.0} for c in certs] + [e for e in evidence if e["type"] != "Certification"][:1]
            if lacking:
                must_hold = bool(HOLD_RE.search(r["text"]))
                if held:
                    status, score = "partial", 0.5
                elif must_hold:
                    status, score = "gap", 0.1
                else:  # build the solution to the standard: possible, but there's no certificate to prove experience
                    status, score = "partial", 0.4
                missing = missing + lacking
                rationale.append(f"Certificate register: holds {', '.join(held) or 'none'} of the named standards; "
                                 f"no {', '.join(lacking)} {'certificate' if must_hold else 'certificate or audited evidence'}.")
                gone = [expired_std[x] for x in lacking if x in expired_std]
                if gone:
                    rationale.append(f"The register lists {', '.join(gone)}, which no longer counts.")
            else:
                status, score = "strong", 0.95
                rationale.append(f"Certified: {', '.join(certs)}.")
        elif sub in CONFIRM_SUBS or (r.get("category") == "Commercial"):
            status = "confirm"
            rationale.append("Commercial or submission condition: confirm acceptance with finance/legal; no capability gap.")
            if sub == "Evaluation & Award":
                rationale[-1] = "Evaluation criterion: shape win themes and evidence around it."
        elif r.get("category") == "Compliance" and sub in ("Regulatory", "Data Protection & Privacy", "Information Security Policy",
                                                          "Accessibility & Sustainability"):
            if status == "gap":
                status = "confirm"
                rationale.append("Policy or regulatory obligation: confirm compliance position with legal/security.")
        if r.get("category") == "Functional" and sub == "Team & Experience":
            same_ind = [c for c in css if industry and industry.lower() in (c.get("industry", "") + " " + c.get("summary", "")).lower()]
            evidence = [{"type": "Case study", "id": c.get("id", ""), "name": c["title"], "score": 0.9} for c in (same_ind or css)[:3]] + \
                       [e for e in evidence if e["type"] != "Case study"]
            status, score = ("strong", 0.85) if len(same_ind) >= 2 else ("partial", 0.55) if css else ("gap", 0.1)
            rationale.append(f"{len(same_ind)} reference projects in {industry or 'this industry'} and {len(kb.employees)} people in the skills register.")
        elif r["text"].startswith("Deliverable:"):
            status = "confirm"
            rationale.append("Contractual deliverable: committed in the delivery plan.")
        elif status == "gap" and not req_techs and not stds and PROCESS_RE.search(r["text"]) and r.get("category") != "Non-functional":
            status = "confirm"
            rationale.append("Response or tender-process obligation: answer in the proposal; no capability needed.")

        coverage_note, coverage = "", None
        if status in ("strong", "partial") and not rationale:
            # A shared product name is not a match. Check that the library also covers what the requirement is about;
            # otherwise "Azure" in a satellite-station requirement would score like an Azure migration.
            terms = _domain_terms(r["text"], r.get("technologies", []))
            hit = [t for t in terms if _covered(t, vocab)]
            cov = len(hit) / len(terms) if terms else 0.0
            if len(terms) < 2 and req_techs:
                if status == "strong" or score > 0.45:
                    status, score = "partial", min(score, 0.45)
                coverage_note = "The requirement names little beyond a technology, so there's not enough to call it fully covered. Read what's actually asked."
            elif tech_cov and len(terms) >= 3 and ((cap_s < 0.3 and cov < 0.25) or (cap_s < 0.5 and cov < 0.2)):
                # The score came from a shared technology name, not from anything the library says about this work.
                status, score = "gap", min(score, 0.3)
                missed = [terms[t] for t in terms if t not in hit][:4]
                coverage_note = f"Only the technology name matches: nothing in the library covers {', '.join(missed)}."
            coverage = round(cov, 2)
            if status == "gap":
                evidence = evidence[:2]
        if status in ("strong", "partial") and not rationale:
            top = evidence[0]["name"] if evidence else "related capabilities"
            bits = [f"Best match: {top}"]
            if people:
                bits.append(f"{len(people)} people with {', '.join(have[:3])} skills")
            if missing:
                bits.append(f"not covered: {', '.join(missing)}")
            rationale.append("; ".join(bits) + ".")
        elif status == "gap" and not rationale and not coverage_note:
            rationale.append(f"No capability or skill covers {', '.join(missing) if missing else 'this requirement'}." )
        if coverage_note:
            rationale.append(coverage_note)

        r["match_status"] = status
        r["match_score"] = score if status != "confirm" else 0.0
        r["match"] = {"evidence": evidence[:5], "people": people[:12], "people_count": len(people),
                      "technologies_have": have, "technologies_missing": missing, "rationale": " ".join(rationale),
                      "retrieval": method, "judged_by": "register" if stds else "rules",
                      **({"term_coverage": coverage} if coverage is not None else {})}
        if stds:
            held_c = [c for c in live if c.get("kind") == "company" and standards_in(c["name"])]
            held_c.sort(key=lambda c: not re.search(r"27001|soc|pci", c["name"], re.I))  # security certificates first
            r["match"]["held_certificates"] = [{"name": c["name"]} for c in held_c][:2]
    if use_ai and llm.is_enabled():
        ai_judge(reqs, kb, inv, guidance, progress)
        # Anything the AI was meant to check but couldn't (quota, timeouts) is flagged so reviewers see it, and a
        # similarity-only "strong" is held at "partial" until a person or the AI confirms it.
        for r in reqs:
            m = r["match"]
            if m.get("judged_by") == "rules" and r["match_status"] in ("strong", "partial", "gap"):
                m["unverified"] = True
                if r["match_status"] == "strong":
                    r["match_status"] = "partial"
                    r["match_score"] = min(r["match_score"], 0.6)
                    m["rationale"] = (m.get("rationale", "") + " AI check didn't run: shown as partial until reviewed.").strip()
    return reqs


JUDGE_SYSTEM = ("You are the bid director of an IT services company deciding, requirement by requirement, whether the company can deliver. "
                "Judge ONLY from the evidence listed for each requirement (the company's capabilities, case studies, accelerators, certifications "
                "and people, each with what it covers). Never assume a capability, product or certification that is not listed. "
                "'strong' = the listed evidence covers what the requirement asks (the named technology or practice appears in a capability, "
                "case study or accelerator, or skilled people hold it). 'partial' = related evidence that covers only part of it. "
                "'gap' = nothing listed covers it. Do not mark a requirement down only because the evidence is worded differently.")


def ai_judge(reqs: list[dict], kb: CompanyKB, inv: dict, guidance: str = "", progress=None) -> None:
    """AI decides strong / partial / gap for every technical and compliance requirement, citing evidence."""
    todo = [r for r in reqs if r["category"] != "Commercial" and r.get("subcategory") not in CONFIRM_SUBS and r["match_status"] != "confirm"
            and r["match"].get("judged_by") != "register"]  # certificate checks are facts, not judgement
    certs = [c["name"] for c in kb.certifications]
    # What each piece of evidence covers, so the judge isn't deciding from a capability's name alone.
    covers: dict[str, str] = {}
    for c in kb.capabilities:
        covers[c["name"]] = "; ".join(x for x in (", ".join(c.get("technologies", [])[:8]), (c.get("description") or "")[:140]) if x)
    for c in kb.case_studies:
        covers[c["title"]] = "; ".join(x for x in (", ".join(c.get("technologies", [])[:6]), c.get("industry", ""), (c.get("summary") or "")[:120]) if x)
    for a in kb.accelerators:
        covers[a["name"]] = "; ".join(x for x in (", ".join(a.get("technologies", [])[:6]), (a.get("description") or "")[:120]) if x)
    batches = [todo[i:i + 18] for i in range(0, len(todo), 18)]
    for n, chunk in enumerate(batches, start=1):
        if progress:
            progress(f"AI judging capability fit: batch {n} of {len(batches)}")
        lines, allowed = [], []
        for k, r in enumerate(chunk):
            ev = [e["name"] for e in r["match"]["evidence"][:4]]
            allowed.append(set(ev) | set(certs))
            ev_text = " | ".join(f"{e} ({covers[e]})" if covers.get(e) else e for e in ev)
            ppl = "; ".join(f"{t}: {inv[t]['people']} people (avg level {inv[t]['avg_level']})" for t in r.get("technologies", []) if t in inv) or "none listed"
            lines.append(f"[{k}] {r['text'][:420]}\n  candidate evidence: {ev_text or 'none'}\n  people with named technologies: {ppl}\n"
                         f"  technologies not in company inventory: {', '.join(r['match']['technologies_missing']) or 'none'}")
        prompt = (f"Company certifications: {', '.join(certs) or 'none'}\n\nRequirements:\n" + "\n".join(lines) +
                  '\n\nReturn a JSON array, one object per requirement: {"i": index, "status": "strong|partial|gap", "score": 0-100, '
                  '"evidence": ["<names copied exactly from that requirement\'s candidate evidence or the certifications>"], '
                  '"rationale": "<one sentence, citing the evidence>"}' + guidance)
        res = None
        for _ in range(2):  # one retry per batch; a failed batch no longer stops the batches after it
            try:
                res = llm.complete_json(JUDGE_SYSTEM, prompt, max_tokens=8000)
                break
            except Exception:
                res = None
        if res is None:
            continue
        if isinstance(res, dict):
            res = next((v for v in res.values() if isinstance(v, list)), [])
        for it in res if isinstance(res, list) else []:
            try:
                k = int(it["i"])
                r = chunk[k]
            except Exception:
                continue
            st = it.get("status")
            if st not in ("strong", "partial", "gap"):
                continue
            cited = [e for e in (it.get("evidence") or []) if isinstance(e, str) and e in allowed[k]]
            # The AI's opinion never outranks the facts: "strong" needs evidence it can name from the library, and a
            # technology the company doesn't have can't be strong (the same rule the scorer follows).
            caps_note = ""
            if st == "strong" and not cited:
                st, caps_note = "partial", " (Kept at partial: the AI named no library evidence.)"
            elif st == "strong" and r["match"].get("technologies_missing"):
                st, caps_note = "partial", f" (Kept at partial: no {', '.join(r['match']['technologies_missing'][:3])} in the library.)"
            r["match_status"] = st
            try:
                sc = max(0, min(100, float(it.get("score", 50)))) / 100
            except (TypeError, ValueError):
                sc = r.get("match_score") or 0.5
            lo, hi = {"strong": (0.62, 0.99), "partial": (0.35, 0.61), "gap": (0.0, 0.34)}[st]
            r["match_score"] = round(min(hi, max(lo, sc)), 2)  # the score always agrees with the label
            if cited:
                order = {name: i for i, name in enumerate(cited)}
                ev = sorted(r["match"]["evidence"], key=lambda e: order.get(e["name"], 99))
                for c in cited:
                    if c in certs and not any(e["name"] == c for e in ev):
                        ev.insert(0, {"type": "Certification", "name": c, "score": 1.0})
                r["match"]["evidence"] = ev[:5]
            r["match"]["rationale"] = (str(it.get("rationale") or r["match"]["rationale"])[:400] + caps_note).strip()
            r["match"]["judged_by"] = "ai"


# --------------------------------------------------------------------------- gaps
METHOD_SUBS = {"Project Management", "Maintainability & Quality", "Monitoring & Operations", "Service Levels", "Transition & Knowledge Transfer",
               "Support & Incident Management", "General Scope", "Testing & QA", "Team & Experience", "Performance & Scalability", "Availability & Continuity"}
def ai_mitigations(reqs: list[dict], kb: CompanyKB, engagement_type: str = "", guidance: str = "", progress=None) -> dict[str, dict]:
    """AI proposes the best mitigation for each gap/partial requirement, grounded in what the company has."""
    todo = [r for r in reqs if r["match_status"] in ("gap", "partial") and r["category"] != "Commercial"]
    todo.sort(key=lambda r: (r["match_status"] != "gap", r.get("priority") != "Mandatory"))
    todo = todo[:54]
    if not todo:
        return {}
    inv = kb.tech_inventory()
    partners = [c["name"] for c in kb.certifications if c.get("kind") == "partner"]
    families = defaultdict(list)
    for t, v in inv.items():
        if v["people"]:
            families[K.TECH_FAMILY.get(t, "Other")].append(f"{t} ({v['people']})")
    profile = (f"Capabilities: {', '.join(c['name'] for c in kb.capabilities)}\nPartnerships: {', '.join(partners) or 'none'}\n"
               f"Company certifications: {', '.join(c['name'] for c in kb.certifications if c.get('kind') == 'company') or 'none'}\n"
               "Skills by family (people): " + "; ".join(f"{f}: {', '.join(v[:8])}" for f, v in families.items()))
    out: dict[str, dict] = {}
    batches = [todo[i:i + 18] for i in range(0, len(todo), 18)]
    for n, chunk in enumerate(batches, start=1):
        if progress:
            progress(f"AI planning mitigations: batch {n} of {len(batches)}")
        lines = [f"[{k}] ({r['match_status']}, {r.get('priority')}) {r['text'][:380]} | missing: {', '.join(r['match'].get('technologies_missing', [])) or 'n/a'}"
                 for k, r in enumerate(chunk)]
        prompt = (f"Company profile:\n{profile}\nEngagement type: {engagement_type}\n\nGaps:\n" + "\n".join(lines) +
                  '\n\nFor each gap return the single best way to close it for THIS company. JSON array: [{"i": index, '
                  '"type": "Partner|Upskill|Hire|Certify|Build|Define method", "detail": "<specific action naming the company\'s own adjacent '
                  'skills, partners or capabilities where relevant; one or two sentences>", "effort": "<duration>", "cost": "Low|Medium|High"}]' + guidance)
        res = None
        try:
            res = llm.complete_json("You are a delivery director planning how an IT services firm closes capability gaps before bidding. "
                                    "Prefer realistic, specific actions. Never invent partners or certifications the company does not have; "
                                    "if a partner is needed and none is listed, say what kind of partner to find.", prompt, max_tokens=8000)
        except Exception:
            continue  # the rules engine's options stay for this batch
        if isinstance(res, dict):
            res = next((v for v in res.values() if isinstance(v, list)), [])
        for it in res if isinstance(res, list) else []:
            try:
                r = chunk[int(it["i"])]
            except Exception:
                continue
            if it.get("type") in ("Partner", "Upskill", "Hire", "Certify", "Build", "Define method") and it.get("detail"):
                out[r["code"]] = {"type": it["type"], "detail": str(it["detail"])[:500], "effort": str(it.get("effort", ""))[:40],
                                  "cost": it.get("cost") if it.get("cost") in ("Low", "Medium", "High") else "Medium", "ai": True}
    return out


_STD_NAMES = {n for n, _ in STANDARDS}


def _is_standard(t: str) -> bool:
    return t.startswith("ISO ") or t in _STD_NAMES


def analyze_gaps(reqs: list[dict], kb: CompanyKB, engagement_type: str = "", ai_options: dict | None = None) -> dict:
    inv = kb.tech_inventory()
    company_techs = set(inv)
    families_have = defaultdict(list)
    for t in company_techs:
        if t in K.TECH_FAMILY:
            families_have[K.TECH_FAMILY[t]].append(t)

    gap_items = []
    missing_counter: dict[str, list[str]] = defaultdict(list)
    for r in reqs:
        if r["match_status"] not in ("gap", "partial"):
            r["gap"] = {}
            continue
        missing = r["match"].get("technologies_missing", [])
        options = []
        for t in missing:
            missing_counter[t].append(r["code"])
        for t in missing[:3]:
            fam = K.TECH_FAMILY.get(t)
            if _is_standard(t):
                options.append({"type": "Certify", "detail": f"Start {t} certification or audit (typically 6–9 months); in the meantime, propose a partner that holds it or confirm with the client whether it is mandatory for award.",
                                "effort": "6–9 months", "cost": "Medium"})
            elif t in K.PARTNER_PRODUCTS or engagement_type == "product" and fam == "Fraud & identity intelligence":
                options.append({"type": "Partner", "detail": f"Partner with a specialist {t} product vendor and lead integration, deployment and support as the system integrator.",
                                "effort": "2–4 weeks to agree terms", "cost": "Revenue share / resale margin"})
            elif fam and families_have.get(fam):
                near = ", ".join(sorted(families_have[fam])[:3])
                options.append({"type": "Upskill", "detail": f"Cross-train engineers already skilled in {near} on {t}; add a short certification sprint.",
                                "effort": "3–6 weeks", "cost": "Low"})
            else:
                options.append({"type": "Hire", "detail": f"Hire or contract specialists in {t} for the delivery window.",
                                "effort": "4–8 weeks", "cost": "Medium"})
        method_like = r.get("subcategory") in METHOD_SUBS
        if not missing and method_like and r["match_status"] == "gap":
            options.append({"type": "Define method", "detail": "Nothing in the library evidences this yet: write the delivery method (owner, tooling, cadence) "
                            "into the response, and add it to your capability library so future bids match it.", "effort": "1–2 days", "cost": "Low"})
        elif not missing:
            if r["match_status"] == "gap":
                options.append({"type": "Build", "detail": "No direct capability: design a solution component and validate it with an architect before committing.",
                                "effort": "Depends on scope", "cost": "Medium"})
            else:
                options.append({"type": "Strengthen evidence", "detail": "Capability exists but evidence is thin: add a reference project, demo or named expert to the response.",
                                "effort": "Days", "cost": "Low"})
        if ai_options and r["code"] in ai_options:
            ao = ai_options[r["code"]]
            options = [ao] + [o for o in options if o["type"] != ao["type"]][:2]
        risk = "Medium" if (method_like and not missing and r["match_status"] == "gap") else \
            "High" if r["match_status"] == "gap" and r.get("priority") == "Mandatory" else "Medium" if r["match_status"] == "gap" or r.get("priority") == "Mandatory" else "Low"
        r["gap"] = {"risk": risk, "options": options, "recommended": options[0]["type"] if options else ""}
        gap_items.append(r)

    mand = [r for r in reqs if r.get("priority") == "Mandatory" and r["match_status"] in ("strong", "partial", "gap")]
    if mand:
        coverage = sum(1.0 if r["match_status"] == "strong" else 0.7 if r["match_status"] == "partial" else 0 for r in mand) / len(mand)
    else:
        coverage = 0.0
    high = sum(1 for r in gap_items if r["gap"]["risk"] == "High")
    readiness = round(coverage * 100 - min(15, high * 1.5))
    # Readiness once the recommended mitigations (partner, upskill, hire, certify) are in place.
    credit = {"Partner": 0.75, "Upskill": 0.7, "Strengthen evidence": 0.9, "Define method": 0.85, "Hire": 0.55, "Build": 0.5, "Certify": 0.4}
    if mand:
        mitigated = sum(1.0 if r["match_status"] == "strong" else max(0.7, credit.get(r["gap"].get("recommended", ""), 0.5)) if r["match_status"] == "partial"
                        else credit.get(r["gap"].get("recommended", ""), 0.3) for r in mand) / len(mand)
    else:
        mitigated = 0.0
    mitigated_readiness = round(mitigated * 100)
    partner_led = sum(1 for r in gap_items if r["gap"].get("recommended") == "Partner")
    if readiness >= 70:
        verdict = "Bid"
    elif mitigated_readiness >= 70:
        verdict = "Bid with partners" if partner_led >= 3 else "Bid with mitigations"
    elif mitigated_readiness >= 55:
        verdict = "Qualify carefully"
    else:
        verdict = "No bid"
    top_missing = sorted(({"technology": t, "requirements": len(v), "codes": v[:8],
                           "recommendation": ("Partner" if t in K.PARTNER_PRODUCTS else "Certify" if _is_standard(t)
                                              else "Upskill" if families_have.get(K.TECH_FAMILY.get(t, "")) else "Hire")}
                          for t, v in missing_counter.items()), key=lambda x: -x["requirements"])
    counts = defaultdict(int)
    for r in reqs:
        counts[r["match_status"]] += 1
    return {"coverage_pct": round(coverage * 100), "readiness": max(0, readiness), "mitigated_readiness": mitigated_readiness,
            "verdict": verdict, "partner_led": partner_led, "counts": dict(counts),
            "high_risk": high, "top_missing": top_missing[:12],
            "risk_counts": {k: sum(1 for r in gap_items if r["gap"]["risk"] == k) for k in ("High", "Medium", "Low")}}
