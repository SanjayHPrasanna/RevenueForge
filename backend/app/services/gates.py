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


def _check_staff(text: str, kb) -> tuple[str, str]:
    certs = re.findall(r"\b([A-Z][A-Z0-9+]{2,8})\b", text)
    certs = [c for c in certs if c not in ("SOC", "IT", "OR", "AND", "L1", "L2", "L3")]
    yrs = re.search(r"(\d{1,2})\s*\+?\s*years", text)
    need_y = int(yrs.group(1)) if yrs else 0
    for e in getattr(kb, "employees", []):
        held = " ".join(str(c) for c in e.get("certifications", [])).upper()
        if certs and not any(c in held for c in certs):
            continue
        if need_y and float(e.get("years") or 0) < need_y:
            continue
        if certs or need_y:
            return "pass", f"{e.get('code')} ({e.get('role')}) meets it"
    return "fail", "Nobody in the skills register holds " + (" or ".join(certs) if certs else "this") + (f" with {need_y}+ years" if need_y else "")


def evaluate(profile: dict, kb, deal_industry: str, due_date: str, rfp_text: str, today: date | None = None) -> dict:
    today = today or date.today()
    due = _due(due_date)
    weeks_left = ((due - today).days / 7) if due else None
    consortium = bool(re.search(r"consorti|joint venture|joint bid|sub-?contract(?:ing|or)s? (?:is|are) (?:allowed|permitted)|lead bidder", rfp_text or "", re.I))
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
