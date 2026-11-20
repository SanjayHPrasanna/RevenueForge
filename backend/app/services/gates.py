"""Eligibility gates: the RFP's pass/fail conditions on the bidder, checked against what the library can prove.

Each eligibility item from the RFP Profile becomes a gate with a status:
    pass     the library proves it (a certificate in the register, enough matching case studies, a named person)
    fail     it doesn't, and nothing can fix it before the bid is due
    curable  it doesn't, but a fix (hire, consortium partner) lands before the due date
    unknown  the library can't tell (turnover, local office...): a person must confirm
A failed mandatory gate decides the bid: "No bid", or "Bid in a consortium" when the RFP allows consortia or
subcontracting (and a reference gap a consortium partner can fill does the same). Readiness percentages are still shown, but they can no longer outvote a failed gate.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

from . import validation

GATE_STOP = set(ENGLISH_STOP_WORDS) | set("""bidder bidders tenderer tenderers supplier suppliers vendor vendors contractor must shall
should hold holds have has possess maintain demonstrate provide proof evidence status certification certified certificate
organisation organization least last years year months delivered operated implemented experience higher above equivalent
required minimum current valid attach submit technical bid within services service solutions""".split())
NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
CURE_WEEKS = {"staff": 8, "experience": 3}  # hire a qualified person; sign a consortium/partner agreement


def _toks(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9+]*", text or ""):
        lw = w.lower()
        if len(lw) > 4 and lw.endswith("s") and not lw.endswith("ss"):
            lw = lw[:-1]  # portals -> portal
        if lw in GATE_STOP or len(lw) < 2:
            continue
        out.add(lw)
    return out


CLIENT_NOUNS = r"(?:clients?|customers?|organi[sz]ations?|institutions?|companies|enterprises|banks?|insurers?|hospitals?|retailers?|operators?|utilities|agencies|departments|sector|industry)"


def _required_industry(text: str) -> int | None:
    """An industry only counts when the condition ties the references to it: "BFSI clients", "clients in retail"."""
    for i, g in enumerate(validation.INDUSTRY_GROUPS):
        for k in g:
            k_ = re.escape(k)
            if re.search(rf"\b{k_}\w*\s+(?:[a-z-]+\s)?{CLIENT_NOUNS}\b", text, re.I) or re.search(rf"{CLIENT_NOUNS}\s+(?:in|from|within)\s+(?:the\s+)?{k_}", text, re.I):
                return i
    return None


def _count_needed(text: str) -> int:
    m = re.search(r"\b(?:at least|minimum of|min\.?|a minimum of)?\s*(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
                  r"(?:[a-z-]+\s){0,6}?(?:clients?|customers?|projects?|implementations?|references?|platforms?|portals?|deployments?|contracts?|engagements?|sites?)\b", text, re.I)
    if not m:
        return 1
    n = m.group(1).lower()
    return int(n) if n.isdigit() else NUM_WORDS.get(n, 1)


def _years_window(text: str) -> int | None:
    m = re.search(r"(?:last|past|previous)\s+(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)\s+years", text, re.I)
    if not m:
        return None
    n = m.group(1).lower()
    return int(n) if n.isdigit() else NUM_WORDS.get(n)


def _due(due_text: str) -> date | None:
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(re.sub(r"(\d)(st|nd|rd|th)", r"\1", (due_text or "").strip()), fmt).date()
        except ValueError:
            continue
    return None


def _check_register(text: str, kb) -> tuple[str, str]:
    """Certificate, accreditation or partner status: a register entry carrying the condition's distinctive words."""
    need = _toks(re.sub(r"\(|\)", " ", text))
    need -= {"partner", "solutions", "solution"} if re.search(r"\bpartner\b", text, re.I) else set()
    std = re.search(r"(?:iso(?:/iec)?\s?)(\d{4,5})", text, re.I)
    best, best_name = 0.0, ""
    for c in getattr(kb, "certifications", []):
        if c.get("kind") == "individual":
            continue
        name = c.get("name", "")
        if std and std.group(1) in name:
            return "pass", f"In the register: {name}"
        have = _toks(name)
        if not need:
            continue
        score = len(need & have) / len(need)
        if score > best:
            best, best_name = score, name
    if best >= 0.75:
        return "pass", f"In the register: {best_name}"
    return "fail", "No matching entry in the certificate register" + (f" (closest: {best_name})" if best_name and best >= 0.3 else "")


def _check_experience(text: str, kb, deal_industry: str) -> tuple[str, str, list[str]]:
    need_n = _count_needed(text)
    window = _years_window(text)
    this_year = date.today().year
    ind = _required_industry(text)
    topic = _toks(text) - {"clients", "client", "customers", "customer", "projects", "project", "references", "reference"}
    if ind is not None:  # the industry words themselves are checked by the industry test, not the topic test
        topic = {t for t in topic if validation._group(t) != ind}
    hits = []
    for cs in getattr(kb, "case_studies", []):
        if window and cs.get("year") and int(cs["year"]) < this_year - window:
            continue
        if ind is not None and validation._group(cs.get("industry", "")) != ind:
            continue
        body = " ".join([cs.get("title", ""), cs.get("summary", ""), " ".join(cs.get("technologies", []))])
        have = _toks(body)
        if not topic or (len(topic & have) >= max(1, round(len(topic) * 0.34))):
            hits.append(cs.get("title", ""))
    if len(hits) >= need_n:
        return "pass", f"{len(hits)} matching case stud{'y' if len(hits) == 1 else 'ies'} (needs {need_n})", hits
    return "fail", f"{len(hits)} matching case stud{'y' if len(hits) == 1 else 'ies'}; the RFP asks for {need_n}", hits


REF_PREFIX_RE = re.compile(r"^\s*[A-Z]{1,8}[-/ ]?\d{1,4}[A-Za-z]?\s*[:.)\-\u2013]\s*")
STAFF_ROLE_RE = re.compile(r"\b((?:[A-Za-z0-9/&+-]+\s+){0,2}?(?:engineers?|analysts?|technicians?|developers?|administrators?|architects?|"
                           r"consultants?|testers?|leads?|managers?|specialists?|officers?|operators?|directors?|heads?|owners?|masters?))\b", re.I)
NOT_CERT = {"SOC", "IT", "OR", "AND", "THE", "L1", "L2", "L3", "ISO", "IEC", "RFP", "SLA", "INR", "USD", "API", "APIS", "UAT", "SIT"}
ARTICLES = {"the", "a", "an", "all", "each", "any", "every", "our", "your", "its", "their", "named", "proposed", "bidder's"}


def staff_clauses(text: str) -> list[dict]:
    """A staffing condition read clause by clause: "STF-01: The project manager shall hold PMP or PRINCE2 and have 8 years;
    the solution architect shall have 10 years of Microsoft Azure experience" is two conditions, one per role. The leading
    reference is not a certificate, and "PMP or PRINCE2" means either one."""
    body = REF_PREFIX_RE.sub("", text or "")
    out = []
    for clause in re.split(r";|\.\s+(?=[A-Z])", body):
        clause = clause.strip()
        if not clause:
            continue
        m = STAFF_ROLE_RE.search(clause)
        role = ""
        if m:
            role = " ".join(w for w in m.group(1).split() if w.lower() not in ARTICLES)
            role = role[:1].upper() + role[1:] if role else ""
            role = " ".join(w if w.isupper() else w.capitalize() for w in role.split())
        certs = [c for c in re.findall(r"(?<![-/])\b([A-Z][A-Z0-9+]{2,8})\b(?![-/]?\d)", clause) if c not in NOT_CERT]
        yrs = re.search(r"(\d{1,2})\s*\+?\s*years", clause)
        tech = re.search(r"years?\s+of\s+(?:hands-on\s+)?([A-Z][\w./+& -]{1,40}?)\s+(?:experience|expertise)", clause)
        if not (certs or yrs or tech):
            continue
        out.append({"role": role, "certs": certs, "any_cert": len(certs) < 2 or bool(re.search(r"\bor\b|either|any of|one of", clause, re.I)),
                    "min_years": int(yrs.group(1)) if yrs else 0, "tech": tech.group(1).strip() if tech else "", "text": clause})
    return out


def _check_staff(text: str, kb) -> tuple[str, str]:
    clauses = staff_clauses(text)
    if not clauses:
        return "unknown", "The library can't show this: confirm it before bidding"
    found, missing = [], []
    for cl in clauses:
        who = None
        role_words = set(re.findall(r"[a-z]+", cl["role"].lower())) - {"the", "and", "of"}
        people = sorted(getattr(kb, "employees", []),  # someone with the job title the condition names comes first
                        key=lambda e: -len(role_words & set(re.findall(r"[a-z]+", str(e.get("role", "")).lower()))))
        for e in people:
            held = " ".join(str(c) for c in e.get("certifications", [])).upper()
            have = [c for c in cl["certs"] if c in held]
            if cl["certs"] and (not have if cl["any_cert"] else len(have) < len(cl["certs"])):
                continue
            if cl["min_years"] and float(e.get("years") or 0) < cl["min_years"]:
                continue
            if cl["tech"]:
                skills = " ".join((s.get("name", "") if isinstance(s, dict) else str(s)) for s in e.get("skills", [])).lower()
                core = re.sub(r"^microsoft\s+", "", cl["tech"].lower())
                if core not in skills:
                    continue
            who = e
            break
        label = cl["role"] or "a named person"
        if who:
            found.append(f"{label}: {who.get('code')} ({who.get('role')})")
        else:
            need = (" or ".join(cl["certs"]) if cl["any_cert"] else " and ".join(cl["certs"])) if cl["certs"] else ""
            bits = [x for x in (need, f"{cl['min_years']}+ years" if cl["min_years"] else "", cl["tech"]) if x]
            missing.append(f"{label} ({', '.join(bits)})")
    if missing:
        return "fail", "Nobody in the skills register meets: " + "; ".join(missing)
    return "pass", "; ".join(found)


NEG_CONSORTIUM_RE = re.compile(r"(consorti\w*|joint ventures?|joint bids?)[^.;]{0,40}?\b(not|never)\s+(be\s+)?(allowed|permitted|accepted|considered)|"
                               r"\b(no|not)\b[^.;]{0,15}(consorti\w*|joint ventures?|joint bids?)", re.I)
POS_CONSORTIUM_RE = re.compile(r"consorti|joint venture|joint bid|lead bidder", re.I)
BID_FORM_RE = re.compile(r"consorti|joint venture|joint bid|sub-?contract", re.I)


def consortium_allowed(rfp_text: str) -> bool:
    """Consortium or joint bids allowed. "Consortium bids are not allowed" says the opposite of what the word alone suggests,
    and a clause allowing one task to be subcontracted (a penetration test) doesn't open the bid to a consortium."""
    t = rfp_text or ""
    if NEG_CONSORTIUM_RE.search(t):
        return False
    return bool(POS_CONSORTIUM_RE.search(t) or re.search(r"sub-?contract(?:ing|ors?)? (?:is|are) (?:allowed|permitted)", t, re.I))


UNITS = {"crore": 1e7, "crores": 1e7, "cr": 1e7, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "million": 1e6, "mn": 1e6, "m": 1e6,
         "billion": 1e9, "bn": 1e9, "thousand": 1e3, "k": 1e3}
MONEY_RE = re.compile(r"(INR|USD|EUR|GBP|AED|SAR|Rs\.?|₹|\$|€|£)\s?([\d,]+(?:\.\d+)?)\s*(crores?|cr|lakhs?|lac|million|mn|billion|bn|thousand|k|m)?\b", re.I)
CCY = {"rs": "INR", "rs.": "INR", "₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}


def _money(m) -> tuple[str, float]:
    c = m.group(1)
    ccy = CCY.get(c.lower(), c.upper())
    return ccy, float(m.group(2).replace(",", "")) * UNITS.get((m.group(3) or "").lower(), 1)


def _check_financial(text: str, kb) -> tuple[str, str]:
    """Turnover / revenue conditions, checked against the figure the company profile states."""
    need = MONEY_RE.search(text)
    about = getattr(kb, "about", "") or ""
    have = None
    for sent in re.split(r"(?<=[.;])\s+|\n", about):
        if re.search(r"turnover|revenue", sent, re.I):
            have = MONEY_RE.search(sent)
            if have:
                break
    if not need or not have or not re.search(r"turnover|revenue", text, re.I):
        return "unknown", "The library can't show this: confirm it before bidding"
    (nc, nv), (hc, hv) = _money(need), _money(have)
    if nc != hc:
        return "unknown", f"The company profile states {have.group(0)}, in another currency: confirm it before bidding"
    if hv >= nv:
        return "pass", f"The company profile states {have.group(0).strip()} (needs {need.group(0).strip()})"
    return "fail", f"The company profile states {have.group(0).strip()}, below the {need.group(0).strip()} required"


def evaluate(profile: dict, kb, deal_industry: str, due_date: str, rfp_text: str, today: date | None = None) -> dict:
    today = today or date.today()
    due = _due(due_date)
    weeks_left = ((due - today).days / 7) if due else None
    consortium = consortium_allowed(rfp_text or "")
    gates = []
    for e in profile.get("eligibility", []):
        kind, text = e.get("kind", "other"), e.get("text", "")
        evidence = []
        if kind in ("certification", "accreditation", "partner_status"):
            status, reason = _check_register(text, kb)
        elif kind == "experience":
            status, reason, evidence = _check_experience(text, kb, deal_industry)
        elif kind == "staff":
            status, reason = _check_staff(text, kb)
        elif kind == "financial":
            status, reason = _check_financial(text, kb)
        elif BID_FORM_RE.search(text) and not re.search(r"\b(certif|accredit|turnover|revenue|experience|years|office|presence)", text, re.I):
            status, reason = "pass", "A rule on how to bid, not a capability: bid as a single company" + (
                "; subcontract only what the RFP allows" if re.search(r"sub-?contract", text, re.I) else "")
        else:
            status, reason = "unknown", "The library can't show this: confirm it before bidding"
        cure, cure_weeks = "", None
        if status == "fail":
            if kind == "staff":
                cure, cure_weeks = "Hire or contract a person who holds it", CURE_WEEKS["staff"]
            elif kind == "experience" and consortium:
                cure, cure_weeks = "Bid with a consortium partner that has these references", CURE_WEEKS["experience"]
            if cure_weeks is not None:
                in_time = weeks_left is None or weeks_left >= cure_weeks
                status = "curable" if in_time else "fail"
                if not in_time:
                    reason += f"; the fix takes about {cure_weeks} weeks and the bid is due in {max(0, round(weeks_left))}"
        gates.append({"ref": e.get("ref") or e.get("code") or "", "code": e.get("code", ""), "text": text[:300], "kind": kind,
                      "mandatory": bool(e.get("mandatory", True)), "status": status, "reason": reason, "evidence": evidence[:5],
                      "cure": cure, "cure_weeks": cure_weeks})
    failed = [g for g in gates if g["mandatory"] and g["status"] == "fail"]
    verdict = None
    via_partner = [g for g in gates if g["mandatory"] and g["status"] == "curable" and g["kind"] == "experience"]
    if failed:
        # with consortia or subcontracting allowed, the company can still take part alongside a prime that holds what's missing
        verdict = "Bid in a consortium" if consortium else "No bid"
    elif via_partner:
        verdict = "Bid in a consortium"
    return {"gates": gates, "failed": [g["ref"] for g in failed], "verdict": verdict, "consortium_allowed": consortium,
            "weeks_to_due": round(weeks_left, 1) if weeks_left is not None else None}
