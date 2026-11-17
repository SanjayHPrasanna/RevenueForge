"""The RFP Profile: one structured reading of the RFP that every later stage uses, instead of each stage re-reading the text.

    term            transition, build and run months (each with the sentence it came from)
    evaluation      every scoring criterion and its weight; flagged when the weights don't add up to 100
    eligibility     pass/fail conditions on the bidder (certification, accreditation, references, staff, partner status...)
    scope_units     countable work ("3,500 endpoints", "60 internet-facing applications", "85 sites")
    service         coverage window (24x7 / business hours), P1 response and resolution targets
    commercial      budget, what the bidder must supply (licences, hardware), what the client pays for
    technologies    named products, platforms, protocols and standards, open vocabulary
    domains         the IT work areas the RFP spans, free text (AI only)

Built twice when AI is available: deterministic readers (always) and one AI call over the masked text. An AI value is kept
only when the sentence it quotes is really in the RFP; where the two readings disagree the field is marked "to confirm"
rather than silently picked. Nothing here is specific to an IT domain or an industry.
"""
from __future__ import annotations

import json
import re

from . import knowledge as K
from . import llm

NUM_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
             "eleven": 11, "twelve": 12, "eighteen": 18, "twenty-four": 24, "thirty-six": 36, "forty-eight": 48}
NUM = r"(\d{1,3}|" + "|".join(sorted(NUM_WORDS, key=len, reverse=True)) + r")(?:\s*\(\d{1,3}\))?"
PHASE_KIND = [
    ("transition", r"transition|onboarding|knowledge transfer|mobili[sz]ation|handover|take[- ]?over"),
    ("build", r"implementation|development|build|migration|rollout|roll[- ]out|deployment|design|delivery|transformation|setup|set[- ]up|programme|project"),
    ("run", r"support|managed|operations|maintenance|warranty|run\b|service|hypercare|ams\b|steady[- ]state|monitoring"),
]
SPAN_RE = re.compile(NUM + r"[- ]?(year|month|week)s?\b((?:(?!\s\d|\s(?:one|two|three|four|five|six|twelve)\b)[^.;\n]){0,60})", re.I)


def _num(s: str) -> int:
    s = s.lower().strip()
    return int(s) if s.isdigit() else NUM_WORDS.get(s, 0)


def _months(n: int, unit: str) -> float:
    u = unit.lower()
    return n * 12 if u.startswith("year") else n if u.startswith("month") else round(n / 4.33, 1)


def _phase_of(words: str) -> str | None:
    for kind, pat in PHASE_KIND:
        if re.search(pat, words, re.I):
            return kind
    return None


def parse_term(text: str) -> dict:
    """Contract phases from sentences such as "3 months transition followed by 36 months of managed security services",
    "9 months development followed by 12 months of warranty support", "a term of three (3) years"."""
    best = None
    cands = []
    for line in re.split(r"(?<=[.;])\s+|\n", text):
        if not re.search(r"\b(month|year|week)s?\b", line, re.I):
            continue
        spans = []
        for m in SPAN_RE.finditer(line):
            n = _num(m.group(1))
            if not n:
                continue
            after = m.group(3) or ""
            before = line[max(0, m.start() - 50):m.start()]
            kind = _phase_of(after.split(" followed")[0].split(" then")[0].split(" and ")[0]) or _phase_of(before[-40:])
            spans.append({"kind": kind, "months": _months(n, m.group(2)), "quote": line.strip()[:240]})
        if not spans:
            continue
        label = re.search(r"\b(contract (?:period|term|duration)|term of (?:the )?contract|duration|engagement period|period of (?:performance|contract))\b", line, re.I)
        score = (3 if label else 0) + (2 if len(spans) > 1 else 0) + sum(1 for s in spans if s["kind"])
        cands.append((score, spans, line))
    if not cands:
        return {}
    cands.sort(key=lambda c: -c[0])
    score, spans, line = cands[0]
    if score < 2:
        return {}
    out = {"transition_months": 0.0, "build_months": 0.0, "run_months": 0.0, "quote": line.strip()[:240]}
    for s in spans:
        k = s["kind"] or ("run" if len(spans) == 1 and re.search(r"contract|term|period", line, re.I) else None)
        if k:
            out[f"{k}_months"] = out[f"{k}_months"] + s["months"]
    if not any(out[f"{k}_months"] for k in ("transition", "build", "run")):
        return {}
    out["total_months"] = out["transition_months"] + out["build_months"] + out["run_months"]
    return out


EVAL_SEC_RE = re.compile(r"evaluat|criteri|scoring|award|weight", re.I)
PAIR_RE = re.compile(r"([A-Za-z][A-Za-z ,&/\-]{2,90}?)\s*[:(|–—-]?\s*(\d{1,3}(?:\.\d)?)\s?%\)?")


def parse_weights(blocks) -> list[dict]:
    """Every "criterion ... N%" in the evaluation section, from tables and prose alike; kept only as a set that adds to 100."""
    sets = []
    cur = []
    for b in blocks:
        if not EVAL_SEC_RE.search((b.section or "") + " " + (b.text if b.kind == "heading" else "")):
            continue
        if b.kind == "heading":
            continue
        txt = b.text.replace("|", " : ")
        for m in PAIR_RE.finditer(txt):
            name = re.sub(r"^(?:.*\b(?:on|for|of|by)\s+)?(?:and\s+)?", "", m.group(1).strip(" ,:-"), flags=re.I) if len(m.group(1)) > 40 else m.group(1).strip(" ,:-")
            name = re.sub(r"^(and|the)\s+", "", name.strip(), flags=re.I)
            if re.fullmatch(r"(weight|total|weighting|criterion|criteria)", name, re.I):
                continue
            cur.append({"criterion": name[:120], "weight": float(m.group(2)), "quote": b.text.strip()[:200]})
    seen = set()
    uniq = []
    for c in cur:
        k = (c["criterion"].lower(), c["weight"])
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    total = sum(c["weight"] for c in uniq)
    if uniq and abs(total - 100) <= 1:
        return [{**c, "weight": int(c["weight"]) if c["weight"].is_integer() else c["weight"]} for c in uniq]
    # several sets in one section (main criteria plus sub-criteria): take the first run of rows that adds to 100
    for i in range(len(uniq)):
        s = 0
        for j in range(i, len(uniq)):
            s += uniq[j]["weight"]
            if abs(s - 100) <= 1 and j > i:
                return [{**c, "weight": int(c["weight"]) if float(c["weight"]).is_integer() else c["weight"]} for c in uniq[i:j + 1]]
    return [{**c, "weight": int(c["weight"]) if float(c["weight"]).is_integer() else c["weight"], "unbalanced": True} for c in uniq]


ELIG_SEC_RE = re.compile(r"eligib|qualif|pre-?qualif|minimum (?:criteria|requirements)|mandatory criteria|who can bid", re.I)
BIDDER_ATTR_RE = re.compile(r"\b(bidders?|tenderers?|suppliers?|vendors?|the bidder|contractor)\b[^.]{0,40}\b(must|shall|should|are required to|is required to)\s+"
                            r"(be|hold|have|possess|maintain|demonstrate|provide (?:proof|evidence))\b", re.I)
STAFF_RE = re.compile(r"\b(lead|manager|analysts?|engineers?|architect|consultants?|staff|personnel|team members?)\b[^.]{0,60}\b(shall|must|should)\s+(hold|have|possess)\b", re.I)


def eligibility_kind(text: str) -> str:
    t = text.lower()
    if STAFF_RE.search(text):
        return "staff"
    if re.search(r"solutions? partner|certified partner|partner (?:for|program|programme|network)|partner (?:status|tier|level)|\bpartner\b.*\b(select|gold|expert|premier|platinum|advanced|elite)\b|(select|gold|expert|premier|platinum|advanced|elite) partner", t):
        return "partner_status"
    if re.search(r"empanel|accredit|licen[cs]ed|registered|authori[sz]ed", t):
        return "accreditation"
    if re.search(r"iso\s*/?\s*(iec\s*)?\d{4,5}|soc\s?[12]|certif|cmmi|pci|cyber essentials", t):
        return "certification"
    if re.search(r"delivered|operated|implemented|experience|references?|clients?\b|projects?\b|in the last \w+ years", t):
        return "experience"
    if re.search(r"turnover|revenue|net worth|financial", t):
        return "financial"
    if re.search(r"office|presence|registered in|local", t):
        return "presence"
    return "other"


def parse_eligibility(reqs: list[dict]) -> list[dict]:
    out = []
    for r in reqs:
        txt = r.get("text", "")
        in_sec = bool(ELIG_SEC_RE.search(r.get("section", "") or ""))
        attr = bool(BIDDER_ATTR_RE.search(txt)) or bool(STAFF_RE.search(txt))
        if not (in_sec or attr):
            continue
        if re.search(r"\battach|submit|include (?:a )?cop", txt, re.I) and not attr:
            continue  # "attach proof of X": a submission instruction about another condition
        out.append({"ref": r.get("source_ref") or r.get("code") or "", "code": r.get("code", ""), "text": txt[:300],
                    "kind": eligibility_kind(txt), "mandatory": (r.get("priority") or "Mandatory") == "Mandatory"})
    return out


UNIT_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})+|\d{2,7})\s+((?:[a-z][a-z-]+\s){0,2}?(endpoints?|servers?|identities|users?|sites?|switches|routers|"
                     r"firewalls?|appliances|access points|applications?|apps|virtual machines|vms|workloads|databases|interfaces|integrations|apis|"
                     r"reports|dashboards|source systems|systems|stores|branches|locations|devices|mailboxes|tickets|incidents|"
                     r"concurrent users|pipelines|data sources|tables|microservices|screens|modules|warehouses|hospitals|schools|offices|employees))\b", re.I)
FREQ_RE = re.compile(r"\b(quarterly|monthly|weekly|daily|annual(?:ly)?|per (?:month|quarter|year))\b", re.I)


def parse_scope_units(reqs: list[dict]) -> list[dict]:
    out, seen = [], set()
    for r in reqs:
        for m in UNIT_RE.finditer(r.get("text", "")):
            qty = int(m.group(1).replace(",", ""))
            unit = m.group(3).lower()
            k = (qty, unit)
            if k in seen or qty < 2:
                continue
            seen.add(k)
            f = FREQ_RE.search(r["text"])
            out.append({"quantity": qty, "unit": unit, "phrase": m.group(0), "frequency": f.group(1).lower() if f else "",
                        "ref": r.get("source_ref") or r.get("code", "")})
    return out


def parse_service(text: str) -> dict:
    t = text.lower()
    cov = "24x7" if re.search(r"24\s?x\s?7|24/7|round[- ]the[- ]clock|24x7x365", t) else \
        "extended" if re.search(r"\b(12|16)\s?x\s?[57]\b", t) else \
        "business hours" if re.search(r"business hours|8\s?x\s?5|office hours|working hours", t) else ""
    p1r = re.search(r"\bp1\b[^.]{0,80}?(?:triag\w*|respon\w*|acknowledg\w*|attend\w*)[^.]{0,20}?within\s+(\d{1,3})\s*(minutes?|mins?|hours?)", t) or \
        re.search(r"(?:critical|p1)[^.]{0,60}?within\s+(\d{1,3})\s*(minutes?|mins?|hours?)", t)
    p1x = re.search(r"\bp1\b[^.]{0,80}?(?:resol\w*|contain\w*|fix\w*|restor\w*)[^.]{0,20}?within\s+(\d{1,3})\s*(minutes?|mins?|hours?|business hours)", t) or \
        re.search(r"(?:contained|resolved|fixed|restored)\s+within\s+(\d{1,3})\s*(minutes?|mins?|hours?)", t)
    on_site = re.search(r"attend[^.]{0,40}within\s+(\d{1,2})\s*hours?", t)

    def mins(m):
        if not m:
            return None
        n = int(m.group(1))
        return n if m.group(2).startswith("min") else n * 60
    return {"coverage": cov, "p1_response_minutes": mins(p1r), "p1_resolution_minutes": mins(p1x),
            "field_attendance_hours": int(on_site.group(1)) if on_site else None}


SUPPLY_RE = re.compile(r"([^.\n]{0,160}?\b(?:licen[cs]es?|subscriptions?|hardware|appliances?|devices?|equipment|credits|software)\b[^.\n]{0,160})", re.I)


def parse_commercial(text: str, reqs: list[dict]) -> dict:
    from .extraction import find_budget
    bidder, client = [], []
    for r in reqs:
        t = r.get("text", "")
        if re.search(r"\b(supplied|provided|procured|purchased|paid)\s+by\s+the\s+(bidder|supplier|contractor|vendor)|\b(bidder|supplier|contractor)\s+shall\s+(supply|provide and install|procure|purchase|furnish)|supply and install", t, re.I):
            bidder.append({"ref": r.get("source_ref") or r.get("code", ""), "text": t[:240]})
    for line in re.split(r"\n|(?<=[.])\s+", text):
        if re.search(r"\b(paid|procured|purchased|provided|supplied)\s+(directly\s+)?by\s+(the\s+)?(client|customer|authority|corporation|company|bank|purchaser|buyer)|"
                     r"(client|customer|authority|corporation|bank)\s+(provides|will provide|holds)|procured by [A-Z]|paid directly by [A-Z]|provides its", line, re.I) and \
                SUPPLY_RE.search(line + " software") and len(line) < 300:
            client.append(line.strip()[:240])
    return {"budget": find_budget(text), "bidder_supplied": bidder, "client_supplied": client}


# --------------------------------------------------------------------------- named technologies (open vocabulary)
_STOP_CAPS = set("""The A An All Any Each Every Our Your Their This These That Those Where When While If For With Within Without From Into
Onto Over Under After Before Between During And Or But Not No Yes It Its We You They He She Mandatory Desirable Optional Bidder Bidders
Tenderer Supplier Vendor Client Contractor Customer Requirement Requirements Proposal Proposals Section Appendix Annex Table Page Item
Detail Critical High Medium Low Phase Stage Month Months Year Years Week Weeks Day Days January February March April May June July August
September October November December Monday Tuesday Wednesday Thursday Friday Saturday Sunday Background Scope Evaluation Eligibility
Key Facts Contract Estimated Hosting Environment Sites Licences Cloud Priority Request Technical Commercial Price Social Value
Quality Delivery Team Approach""".split())
_PLACES = set("""India Pune Mumbai Delhi Bengaluru Bangalore Hyderabad Chennai Kolkata UK England London Scotland Wales Ireland USA America
Canada Australia Singapore Dubai UAE Emirates Qatar Doha Kuwait Saudi Arabia Riyadh Europe Germany France Spain Italy Netherlands Belgium
Sweden Norway Denmark Finland Poland Greece Portugal Switzerland Austria Japan China Africa Asia Pacific Middle East Central South North
West East""".split())
_ORG_TAIL = {"centre", "center", "team", "office", "department", "services", "service", "corporation", "group", "ltd", "limited", "plc",
             "inc", "authority", "ministry", "council", "board", "committee", "bank", "society", "company", "parks", "park"}
_GENERIC_ACRONYMS = {"RPO", "RTO", "BFSI", "SME", "SMEs", "IT", "SLA", "SLAS", "KPI", "UAT", "RFP", "RFI", "RFQ", "SOW", "TBD", "NA", "N/A", "FAQ", "GST", "VAT", "USD", "INR",
                     "EUR", "GBP", "AED", "AUD", "SGD", "CAD", "SAR", "QAR", "KWD", "PDF", "ID", "UK", "US", "USA", "UAE", "EU", "EEA", "CV", "CVS",
                     "OK", "AM", "PM", "IST", "GMT", "UTC", "HQ", "MD", "CEO", "CFO", "CIO", "CTO", "CISO", "HR"}
TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+#&/'-]*[A-Za-z0-9+#]|[A-Za-z0-9]")


def _product_like(w: str) -> bool:
    if re.fullmatch(r"[A-Z]\d{1,2}", w) or re.fullmatch(r"\d+(\.\d+)?", w):
        return False  # L2, P1; plain numbers
    if w.upper() == w and w.isalpha() and 2 <= len(w) <= 7:
        return w.upper() not in _GENERIC_ACRONYMS
    if re.search(r"[a-z][A-Z]", w) or re.match(r"^[a-z]+[A-Z]", w):
        return True  # FortiGate, PostgreSQL, iOS, SonarQube
    if re.search(r"[A-Za-z][.+#][A-Za-z0-9]|\d[A-Za-z]|[A-Za-z]\d|&[A-Z]", w):
        return True  # Node.js, C#, 802.1X, ATT&CK, S/4HANA
    if re.fullmatch(r"[A-Z]{2,}-[A-Za-z]+", w):
        return True  # CERT-In, SD-WAN
    return False


VENDOR_GENERIC = {"corporation", "company", "client", "bank", "authority", "council", "ministry", "group", "ltd", "limited", "plc", "inc",
                  "based", "enabled", "compliant", "certified", "level", "partner", "status", "programme", "program", "framework",
                  "methodology", "model", "guidelines", "guideline", "standard", "standards", "principles", "policy", "act", "regulation",
                  "regulations", "directions", "requirements", "practice", "practices"}


def is_vendor_product(name: str, kind: str = "") -> bool:
    """A named commercial product a partner could supply or run (CrowdStrike Falcon EDR, CyberArk PAM, Amazon EKS, SonarQube):
    not a standard, an accreditation, a practice acronym (SOC, MFA, VAPT), a qualification (OSCP) or a phrase from the
    client's own wording. Decided from the shape of the name, never from a product list."""
    if kind:
        return kind == "product"
    if re.search(r"\b(ISO|IEC|SOC|CMMI|PCI|OWASP|WCAG|MITRE|NIST|CIS|ITIL|ASVS|GDPR|HIPAA|802\.1X)\b", name):
        return False
    words = [w for w in name.split() if "-" not in w]  # "OTP-based", "CERT-In" are not product names; "FortiGate SD-WAN" keeps "FortiGate"
    if not words:
        return False
    if any(w.lower() in VENDOR_GENERIC for w in words):
        return False
    if len(words) == 1:
        w = words[0]
        return bool(re.search(r"[a-z][A-Z]", w)) and not w.isupper()  # SonarQube, CyberArk, FortiSwitch (not SOC, VAPT, OSCP)
    caps = [w for w in words if w[:1].isupper()]
    return len(caps) >= 2 and not all(w.isupper() for w in words)  # CrowdStrike Falcon EDR, Amazon EKS, Microsoft Sentinel


def named_terms(text: str, corpus: str, exclude: set[str] | None = None) -> list[str]:
    """Product, platform, protocol and standard names in a requirement, found by their shape rather than a list:
    CamelCase, versioned or dotted names, acronyms, and capitalised words the RFP never writes in lower case."""
    exclude = {e.lower() for e in (exclude or set())}
    low_corpus = set(re.findall(r"(?<![A-Za-z])([a-z][a-z-]+)", corpus))
    out = []
    for sent in re.split(r"(?<=[.;:!?])\s+|\n", text):
        toks = list(TOKEN_RE.finditer(sent))
        i = 0
        while i < len(toks):
            w = re.sub(r"'s$", "", toks[i].group(0)).strip("'")
            starts = i == 0
            if re.fullmatch(r"[A-Z]\d{1,2}|\d+x\d+(x\d+)?|[\d.,%]+", w, re.I) or w in _PLACES:
                i += 1
                continue
            cap = w[:1].isupper() or _product_like(w)
            if not cap or (w in _STOP_CAPS and not _product_like(w)):
                i += 1
                continue
            j, phrase = i, []
            while j < len(toks):
                t = re.sub(r"'s$", "", toks[j].group(0)).strip("'")
                if re.fullmatch(r"[A-Z]\d{1,2}|\d+x\d+(x\d+)?|\d+(\.\d+)?%?", t, re.I) and not (phrase and t[:1].isdigit() and "." in t):
                    if phrase and t[:1].isdigit() and not re.fullmatch(r"\d+x\d+(x\d+)?", t, re.I):
                        phrase.append(t)  # a version or level after a name: "WCAG 2.1", "OWASP Top 10", "Level 2"
                        j += 1
                        continue
                    break
                if t[:1].isupper() or _product_like(t) or (t[:1].isdigit() and phrase):
                    if t in _STOP_CAPS and not _product_like(t) and phrase:
                        break
                    phrase.append(t)
                    j += 1
                elif t.lower() in ("for", "of") and phrase and j + 1 < len(toks) and toks[j + 1].group(0)[:1].isupper() \
                        and toks[j + 1].group(0) not in _STOP_CAPS:
                    phrase.append(t)
                    j += 1
                else:
                    break
            i = max(j, i + 1)
            if not phrase:
                continue
            while phrase and (phrase[0] in _STOP_CAPS and not _product_like(phrase[0])):
                phrase = phrase[1:]
            while phrase and phrase[-1].lower() in ("for", "of"):
                phrase = phrase[:-1]
            if not phrase:
                continue
            words = [p for p in phrase if p.lower() not in ("for", "of")]
            productish = any(_product_like(p) for p in words)
            unusual = [p for p in words if p.lower() not in low_corpus and p not in _STOP_CAPS]
            if starts and not productish and len(words) == 1:
                continue  # an ordinary word that starts a sentence
            if not productish and len(unusual) * 2 < len(words):
                continue  # mostly ordinary words in title case ("Network Operations Centre")
            if words[-1].lower() in _ORG_TAIL and not productish:
                continue
            if all(p in _PLACES for p in words) or (len(words) == 1 and words[0].upper() in _GENERIC_ACRONYMS):
                continue
            while phrase and phrase[0].lower() in exclude:
                phrase = phrase[1:]
            while phrase and phrase[-1].lower() in exclude:
                phrase = phrase[:-1]
            words = [p for p in phrase if p.lower() not in ("for", "of")]
            if not words:
                continue
            name = " ".join(phrase)
            if name.lower() in exclude or any(w.lower() in exclude for w in words if len(words) == 1):
                continue
            if len(name) < 2 or name.lower() in ("i", "a"):
                continue
            out.append(name)
    seen, res = set(), []
    for n in out:
        if n.lower() not in seen:
            seen.add(n.lower())
            res.append(n)
    return res


def technologies_for(req_text: str, corpus: str, library_terms: dict[str, str], exclude: set[str]) -> list[str]:
    """Names as the RFP writes them (found by shape, or the company's own technology names found in the text), plus dictionary
    hits for anything those didn't already cover (the dictionary also knows aliases: "EKS" is Kubernetes)."""
    literal = []
    low = req_text.lower()
    for norm_name, name in library_terms.items():
        if len(norm_name) >= 2 and re.search(r"(?<![a-z0-9])" + re.escape(norm_name) + r"(?![a-z0-9])", low):
            m = re.search(re.escape(norm_name), req_text, re.I)
            literal.append(req_text[m.start():m.end()] if m else name)
    literal += named_terms(req_text, corpus, exclude)
    out, seen, canon = [], set(), set()
    for t in literal:
        if t.lower() not in seen:
            seen.add(t.lower())
            canon.add(K.canonical_tech(t).lower())
            canon |= {K.canonical_tech(x).lower() for x in K.find_technologies(t)}
            out.append(t)
    for t in K.find_technologies(req_text):
        if K.canonical_tech(t).lower() not in canon and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    # keep the longest form: "CrowdStrike Falcon EDR" over "EDR" when both came from the same words
    return [t for t in out if not any(t != o and re.search(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", o) for o in out)]


def library_tech_terms(kb) -> dict[str, str]:
    """The company's own technology vocabulary (normalised -> as written), for spotting the same names in an RFP.
    Only product-like names: "Risk management" or "Python" style ordinary words are left to the dictionary."""
    names = []
    for c in getattr(kb, "capabilities", []):
        names += c.get("technologies", [])
    for c in getattr(kb, "case_studies", []):
        names += c.get("technologies", [])
    for a in getattr(kb, "accelerators", []):
        names += a.get("technologies", [])
    for e in getattr(kb, "employees", []):
        names += [s.get("name", "") if isinstance(s, dict) else str(s) for s in e.get("skills", [])]
    out = {}
    for n in names:
        n = (n or "").strip()
        if not n or len(n) > 40:
            continue
        words = n.split()
        if any(_product_like(w) for w in words) or (len(words) <= 3 and all(w[:1].isupper() for w in words) and len(n) > 3) or re.fullmatch(r"[a-z]{2,4}", n):
            out[n.lower()] = n
    return out


# --------------------------------------------------------------------------- the profile
def rules_profile(doc, reqs: list[dict], meta: dict, kb=None, client_words: set[str] | None = None) -> dict:
    text = doc.text
    corpus = text
    lib = library_tech_terms(kb) if kb is not None else {}
    excl = set(client_words or set())
    techs: dict[str, dict] = {}
    for r in reqs:
        if r.get("category") == "Commercial" or r.get("subcategory") in ("Submission", "Evaluation & Award"):
            continue
        for t in technologies_for(r.get("text", ""), corpus, lib, excl):
            e = techs.setdefault(t.lower(), {"name": t, "refs": []})
            e["refs"].append(r.get("source_ref") or r.get("code", ""))
    term = parse_term(text)
    return {
        "term": term,
        "evaluation": parse_weights(doc.blocks),
        "eligibility": parse_eligibility(reqs),
        "scope_units": parse_scope_units(reqs),
        "service": parse_service(" ".join(r.get("text", "") for r in reqs) + " " + text[:4000]),
        "commercial": parse_commercial(text, reqs),
        "technologies": list(techs.values()),
        "domains": [],
        "source": "rules",
        "conflicts": [],
    }


AI_SYSTEM = ("You are a senior bid manager reading an IT RFP. Extract facts exactly as the RFP states them. Quote the RFP sentence each "
             "fact comes from, word for word. Never infer a number the RFP doesn't state.")


def ai_profile(masked_text: str) -> dict | None:
    if not llm.is_enabled():
        return None
    prompt = (masked_text[:60000] + "\n\nReturn JSON with these keys (omit what the RFP doesn't state):\n"
              '{"term": {"transition_months": n, "build_months": n, "run_months": n, "quote": "..."},\n'
              ' "evaluation": [{"criterion": "...", "weight": n, "quote": "..."}],\n'
              ' "eligibility": [{"ref": "<RFP id or empty>", "text": "...", "kind": "certification|accreditation|partner_status|experience|staff|financial|presence|other", "mandatory": true}],\n'
              ' "scope_units": [{"quantity": n, "unit": "...", "frequency": "", "ref": "", "quote": "..."}],\n'
              ' "service": {"coverage": "24x7|business hours|extended|", "p1_response_minutes": n, "p1_resolution_minutes": n},\n'
              ' "commercial": {"bidder_supplied": [{"ref": "", "text": "..."}], "client_supplied": ["..."]},\n'
              ' "technologies": [{"name": "<product, platform, protocol or standard exactly as named>", "kind": "product|platform|protocol|standard|certification", "refs": ["<RFP ids>"]}],\n'
              ' "domains": ["<IT work areas, e.g. security operations, identity, data engineering>"]}\n'
              "Months as numbers (3 years = 36). Transition = onboarding/knowledge transfer; build = implementation, migration, rollout, development; "
              "run = support, managed service, operations, warranty.")
    try:
        out = llm.complete_json(AI_SYSTEM, prompt, max_tokens=6000)
    except Exception:
        return None
    return out if isinstance(out, dict) else None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _quoted(quote: str, text_n: str) -> bool:
    q = _norm(quote)
    if len(q) < 12:
        return False
    if q in text_n:
        return True
    words = q.split()  # tolerate small differences: 80% of an 8-word window must be present in order
    return any(" ".join(words[i:i + 8]) in text_n for i in range(0, max(1, len(words) - 7), 4))


def merge(rules: dict, ai: dict | None, masked_text: str) -> dict:
    """AI values win only when their quote is in the RFP; disagreements are recorded for a person to confirm."""
    if not ai:
        return rules
    text_n = _norm(masked_text)
    out = dict(rules)
    out["source"] = "ai+rules"
    conflicts = []
    t = ai.get("term") or {}
    if isinstance(t, dict) and _quoted(str(t.get("quote", "")), text_n):
        term = {k: float(t.get(k) or 0) for k in ("transition_months", "build_months", "run_months")}
        term["total_months"] = sum(term.values())
        term["quote"] = str(t["quote"])[:240]
        if rules.get("term") and abs(rules["term"].get("total_months", 0) - term["total_months"]) > 0.5:
            conflicts.append({"field": "term", "rules": rules["term"].get("total_months"), "ai": term["total_months"]})
        if term["total_months"] > 0:
            out["term"] = term
    ev = [e for e in (ai.get("evaluation") or []) if isinstance(e, dict) and e.get("weight") not in (None, "")]
    if ev and all(_quoted(str(e.get("quote", "")) or str(e.get("criterion", "")), text_n) or _norm(str(e.get("criterion", ""))) in text_n for e in ev):
        try:
            tot = sum(float(e["weight"]) for e in ev)
        except (TypeError, ValueError):
            tot = 0
        if abs(tot - 100) <= 1 and (not rules.get("evaluation") or abs(sum(float(x["weight"]) for x in rules["evaluation"]) - 100) > 1
                                    or len(ev) >= len(rules["evaluation"])):
            out["evaluation"] = [{"criterion": str(e.get("criterion", ""))[:120], "weight": e["weight"], "quote": str(e.get("quote", ""))[:200]} for e in ev]
        elif abs(tot - 100) > 1:
            conflicts.append({"field": "evaluation", "ai_total": tot})
    if isinstance(ai.get("eligibility"), list):
        known = {(_norm(e["text"])[:60]) for e in rules.get("eligibility", [])}
        extra = [e for e in ai["eligibility"] if isinstance(e, dict) and e.get("text") and _norm(e["text"])[:60] not in known and _quoted(e["text"], text_n)]
        out["eligibility"] = rules.get("eligibility", []) + [{"ref": str(e.get("ref", ""))[:30], "code": "", "text": str(e["text"])[:300],
                                                               "kind": e.get("kind") or eligibility_kind(e["text"]), "mandatory": e.get("mandatory", True) is not False}
                                                              for e in extra]
    if isinstance(ai.get("scope_units"), list):
        have = {(u["quantity"], u["unit"]) for u in rules.get("scope_units", [])}
        for u in ai["scope_units"]:
            try:
                q = int(float(u.get("quantity")))
            except (TypeError, ValueError):
                continue
            if (q, str(u.get("unit", "")).lower()) not in have and _quoted(str(u.get("quote", "")) or f"{q} {u.get('unit', '')}", text_n):
                out.setdefault("scope_units", []).append({"quantity": q, "unit": str(u.get("unit", "")).lower()[:40], "phrase": str(u.get("quote", ""))[:120],
                                                          "frequency": str(u.get("frequency", ""))[:20], "ref": str(u.get("ref", ""))[:30]})
    sv = ai.get("service") or {}
    if isinstance(sv, dict):
        s2 = dict(rules.get("service") or {})
        for k in ("coverage", "p1_response_minutes", "p1_resolution_minutes"):
            if not s2.get(k) and sv.get(k):
                s2[k] = sv[k]
        out["service"] = s2
    cm = ai.get("commercial") or {}
    if isinstance(cm, dict):
        c2 = dict(rules.get("commercial") or {})
        if isinstance(cm.get("bidder_supplied"), list):
            have = {_norm(x["text"])[:50] for x in c2.get("bidder_supplied", [])}
            c2["bidder_supplied"] = c2.get("bidder_supplied", []) + [{"ref": str(x.get("ref", ""))[:30], "text": str(x.get("text", ""))[:240]}
                                                                      for x in cm["bidder_supplied"] if isinstance(x, dict) and x.get("text")
                                                                      and _norm(x["text"])[:50] not in have and _quoted(x["text"], text_n)]
        out["commercial"] = c2
    if isinstance(ai.get("technologies"), list):
        have = {t["name"].lower() for t in rules.get("technologies", [])}
        techs = list(rules.get("technologies", []))
        for t in ai["technologies"]:
            name = str((t or {}).get("name", "")).strip() if isinstance(t, dict) else str(t).strip()
            if name and name.lower() not in have and _norm(name) in text_n:
                have.add(name.lower())
                techs.append({"name": name[:80], "refs": [str(x)[:30] for x in (t.get("refs") or [])][:10] if isinstance(t, dict) else [],
                              "kind": t.get("kind", "") if isinstance(t, dict) else ""})
        out["technologies"] = techs
    if isinstance(ai.get("domains"), list):
        out["domains"] = [str(d)[:60] for d in ai["domains"][:10]]
    out["conflicts"] = conflicts
    return out


def to_meta(profile: dict, meta: dict) -> dict:
    """What the existing stages read from deal.meta, filled from the Profile so the old consumers see the same facts."""
    m = dict(meta)
    t = profile.get("term") or {}
    if t.get("run_months"):
        m["contract_term_months"] = int(round(t["run_months"]))
    if t.get("build_months"):
        m["build_months"] = int(round(t["build_months"]))
    m["transition_months"] = t.get("transition_months") or 0
    if profile.get("evaluation"):
        m["evaluation_criteria"] = [{"criterion": e["criterion"], "weight": e["weight"], "detail": e.get("quote", "")} for e in profile["evaluation"]]
    if (profile.get("commercial") or {}).get("budget"):
        m["budget"] = profile["commercial"]["budget"]
    m["profile"] = profile
    return m


def engagement_from_term(term: dict, current: str) -> str:
    """The contract's own phases decide the engagement shape when they're stated."""
    b, r = (term or {}).get("build_months") or 0, (term or {}).get("run_months") or 0
    if b and r:
        return "build_run"
    if r and not b and current in ("", "implementation", "build_run"):
        return "managed_services"
    if b and not r and current in ("", "managed_services", "build_run"):
        return "implementation"
    return current
