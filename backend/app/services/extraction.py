"""Stage 1 - Requirement Intelligence.

Turns parsed RFP blocks into atomic, classified requirements, each tied to the block (and so the
page and section) it came from. Also extracts deal metadata: document type, dates, currency,
engagement model, evaluation criteria, SLAs, deliverables and out-of-scope items.
"""
from __future__ import annotations

import re

from . import knowledge as K
from . import llm
from .parsing import Block, ParsedDocument

REQ_SECTION_RE = re.compile(r"(scope|requirement|specification|objective|deliverable|program|phase|criteria|capabilit|deployment|option|"
                            r"service|support|sla|technical|function|security|integration|journey|channel|intelligence|profil|"
                            r"fingerprint|geolocation|network|response|submission|expertise|approach|experience|proposal|information to be provided|"
                            r"case manage|analytics|reporting|operations|monitor|continuity|quality)", re.I)
OUT_OF_SCOPE_RE = re.compile(r"out[- ]of[- ]scope|exclusion|not in scope", re.I)
METRIC_RE = re.compile(r"(≤|≥|<=|>=|\d+\s?%|\d+\s?(ms|milliseconds|seconds|minutes|mins|hours|hrs|days|business days|working days)\b|99\.\d+)", re.I)
DATE_ONLY_RE = re.compile(r"^[^|]{3,80}\|\s*(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|n/?a|tbd)\s*$", re.I)
SENT_SPLIT_RE = re.compile(r"(?<=[.;])\s+(?=[A-Z(])")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _sentences(text: str) -> list[str]:
    parts = SENT_SPLIT_RE.split(text)
    out = []
    for p in parts:
        p = p.strip()
        if len(p) > 3:
            out.append(p)
    return out


def _is_requirement_sentence(s: str, section: str, in_req_section: bool) -> bool:
    if len(s) < 18 or K.INFO_ONLY_RE.search(s) or K.CLIENT_SUBJECT_RE.search(s):
        return False
    if re.match(r"^(note|e\.g|i\.e)\b", s, re.I) or re.match(r"^[“\"'][^”\"']{1,40}[”\"']\s+means\b", s):
        return False
    has_oblig = bool(K.MANDATORY_RE.search(s) or K.DESIRABLE_RE.search(s))
    has_vendor = bool(K.VENDOR_SUBJECT_RE.search(s))
    if has_oblig and (has_vendor or in_req_section or K.ACTION_START_RE.search(s)):
        return True
    if in_req_section and K.ACTION_START_RE.search(s):
        return True
    return False


PRIO_CELL_RE = re.compile(r"^(mandatory|desirable|optional|required|must( have)?|should( have)?|nice to have|could( have)?|m|d|o)$", re.I)


def _row_priority(b: Block) -> str:
    """A priority written in its own table cell ("Mandatory", "Desirable")."""
    for c in reversed([c.strip() for c in b.text.split(" | ") if c.strip()]):
        if PRIO_CELL_RE.match(c):
            return "Desirable" if re.match(r"(desirable|optional|should|nice|could|d$|o$)", c, re.I) else "Mandatory"
    return ""


def _table_row_text(b: Block, header: list[str] | None) -> str:
    cells = [c.strip() for c in b.text.split(" | ") if c.strip()]
    # a priority column is metadata, not part of the requirement's wording
    if len(cells) > 1 and PRIO_CELL_RE.match(cells[-1]):
        cells = cells[:-1]
    # drop leading row numbers
    if cells and re.fullmatch(r"\d{1,3}\.?", cells[0]):
        cells = cells[1:]
    if not cells:
        return ""
    if len(cells) == 1:
        return cells[0]
    metric_cells = [c for c in cells if METRIC_RE.search(c) and len(c) < 40]
    if metric_cells and len(cells) <= 5:
        head = [c for c in cells if c not in metric_cells]
        return f"{' – '.join(head)}: {'; '.join(metric_cells)}"
    return " — ".join(cells)


COVER_SECTION_RE = re.compile(r"^(request for (proposal|information|quotation|tender)|invitation to tender|rf[piqt])$", re.I)


def rules_extract(doc: ParsedDocument) -> tuple[list[dict], dict]:
    reqs: list[dict] = []
    seen: set[str] = set()
    out_of_scope: list[str] = []
    deliverables: list[str] = []
    evaluation: list[dict] = []
    slas: list[str] = []
    workstreams: list[dict] = []
    objectives: list[str] = []
    header: list[str] | None = None

    def add(text: str, b: Block, ref: str = "", kind_hint: str = "", prio: str = ""):
        text = re.sub(r"\s+", " ", text).strip(" -–•")
        if len(text) < 12 or (len(text) < 22 and not ref and not METRIC_RE.search(text) and not K.find_technologies(text)):
            return
        key = _norm(text)[:180]
        if key in seen:
            return
        seen.add(key)
        cat, sub, conf = K.classify(text, b.section)
        if len(text) < 90 and re.search(r"submission|response format|documents|information to be provided|technical (offer|envelope)|commercial (offer|envelope)", b.section, re.I) \
                and not METRIC_RE.search(text):
            cat, sub, conf = "Compliance", "Submission", 0.8
        if kind_hint == "evaluation":
            cat, sub, conf = "Commercial", "Evaluation & Award", 0.9
        if kind_hint == "sla":
            cat, sub, conf = "Non-functional", "Service Levels", 0.92
        if kind_hint == "deliverable" and cat == "Commercial":
            cat, sub = "Functional", "Project Management"
        reqs.append({
            "text": text, "category": cat, "subcategory": sub, "priority": prio or K.priority(text),
            "page": b.page, "section": b.section[:290], "block_idx": b.idx, "source_ref": ref if ref != "header" else "",
            "class_confidence": conf,
        })

    for b in doc.blocks:
        sec = b.section or ""
        if b.kind == "heading":
            header = None
            continue
        if OUT_OF_SCOPE_RE.search(sec):
            if b.kind in ("bullet", "para", "table_row"):
                out_of_scope.append(b.text)
            continue
        if b.kind in ("para", "bullet") and (not sec or COVER_SECTION_RE.match(sec.strip())):
            continue  # cover page: title, reference, dates
        skip_section = bool(K.SKIP_SECTION_RE.search(sec))
        in_req = bool(REQ_SECTION_RE.search(sec)) and not skip_section

        if b.kind in ("bullet", "para") and re.search(r"\bobjectives?\b|\bgoals?\b|\boutcomes\b", sec, re.I) and 12 < len(b.text) < 300:
            objectives.append(re.sub(r"\s+", " ", b.text).strip(" -–•"))
        if b.kind == "table_row":
            if b.ref == "header":
                header = [c.strip() for c in b.text.split("|")]
                continue
            if header and re.match(r"^(workstreams?|work packages?|lots?|scope areas?)$", header[0], re.I):
                cells = [c.strip() for c in b.text.split("|")]
                if cells and cells[0]:
                    workstreams.append({"name": cells[0][:120], "summary": " ".join(cells[1:])[:300]})
            if DATE_ONLY_RE.match(b.text) or re.fullmatch(r"total\s*\|?\s*100\s?%", b.text.strip(), re.I):
                continue
            text = _table_row_text(b, header)
            if not text:
                continue
            is_eval = bool(re.search(r"evaluat|criteria|weight", sec + " " + " ".join(header or []), re.I)) and re.search(r"\d+\s?%", b.text)
            if is_eval:
                weight = re.search(r"(\d+)\s?%", b.text)
                name = re.split(r"[•|]", text)[0].strip(" —-:")
                evaluation.append({"criterion": name[:120], "weight": int(weight.group(1)) if weight else None, "detail": text})
                add(f"Evaluation criterion – {text}", b, kind_hint="evaluation")
                continue
            if b.ref:
                add(text, b, b.ref, prio=_row_priority(b))
                continue
            if re.search(r"deliverable", sec + " " + " ".join(header or []), re.I):
                deliverables.append(text)
                add(f"Deliverable: {text}", b, kind_hint="deliverable")
                continue
            if METRIC_RE.search(text) and re.search(r"sla|incident|response|resolution|availability|severity|fulfil", text + sec, re.I):
                slas.append(text)
                add(text, b, kind_hint="sla")
                continue
            if in_req and (K.ACTION_START_RE.search(text) or K.MANDATORY_RE.search(text) or len(text) > 50):
                add(text, b, prio=_row_priority(b))
            continue

        if b.kind == "bullet":
            t = b.text.strip()
            if skip_section and not K.MANDATORY_RE.search(t):
                continue
            if in_req or K.ACTION_START_RE.search(t) or K.MANDATORY_RE.search(t):
                # long bullets with several obligations get split
                sents = _sentences(t) if len(t) > 260 else [t]
                for s in sents:
                    if len(sents) == 1 or _is_requirement_sentence(s, sec, True):
                        add(s, b)
            continue

        if b.kind == "para":
            for s in _sentences(b.text):
                if skip_section and not (K.MANDATORY_RE.search(s) and K.VENDOR_SUBJECT_RE.search(s)):
                    continue
                if _is_requirement_sentence(s, sec, in_req):
                    add(s, b)
                elif in_req and len(s) < 90 and not s.endswith(":") and K.ACTION_START_RE.search(s):
                    add(s, b)  # short spec items rendered as paragraphs

    if not reqs:
        # A short scope (e.g. a published tender notice) with no "shall"/"must" sentences: each scope sentence is taken
        # as one requirement, so the deal still has something to match and estimate. Low confidence, for review.
        after_heading = False
        for b in doc.blocks:
            t = (b.text or "").strip()
            # plain-text notices have no real headings: a short "Scope of work ..." line starts the scope
            if b.kind in ("heading", "para") and len(t) < 90 and REQ_SECTION_RE.search(t) and not t.endswith("."):
                after_heading = True
                continue
            if b.kind in ("para", "bullet") and (after_heading or REQ_SECTION_RE.search(b.section or "")):
                for s in _sentences(b.text):
                    if len(s) >= 30 and not s.startswith("("):  # "(The notice gives no description.)" is not a requirement
                        add(s, b)
        for r in reqs:
            r["class_confidence"] = min(r["class_confidence"], 0.5)
    meta = {"out_of_scope": out_of_scope[:40], "deliverables": deliverables[:40], "evaluation_criteria": evaluation, "slas": slas[:40],
            "workstreams": workstreams[:12], "objectives": objectives[:12]}
    return reqs, meta


# --------------------------------------------------------------------------- LLM path
LLM_SYSTEM = (
    "You are a senior bid manager. You extract every requirement a bidder must respond to from RFP text. "
    "A requirement is an obligation, capability, service level, deliverable, compliance condition, submission rule or "
    "commercial term the bidder must satisfy or respond to. Ignore definitions, background about the client, and the client's own rights. "
    "Split compound sentences into atomic requirements but keep wording faithful to the source."
)

SUBCATS = list(K.SUBCATEGORIES.keys())


def llm_extract(doc: ParsedDocument, mask_fn=lambda x: x, guidance: str = "", progress=None, failed: list | None = None) -> list[dict]:
    """AI extraction in batches of blocks. Each requirement keeps the id of the block it came from (traceability).

    failed: if given, receives the ids of blocks in parts the AI couldn't read, so the rules engine can fill them in."""
    blocks = [b for b in doc.blocks if b.kind != "heading" and b.ref != "header"]
    out: list[dict] = []
    by_idx = {b.idx: b for b in doc.blocks}
    size = 40
    batches = [blocks[i:i + size] for i in range(0, len(blocks), size)]
    failures = 0
    for n, chunk in enumerate(batches, start=1):
        if progress:
            progress(f"AI reading the RFP: part {n} of {len(batches)}")
        payload = "\n".join(f"[{b.idx}] (p{b.page}; {mask_fn(b.section)[:80]}) {(b.ref + ': ') if b.ref and b.ref != 'header' else ''}{mask_fn(b.text)}"
                            for b in chunk)
        prompt = (
            "Blocks from an RFP, each prefixed with [block id] (page; section):\n\n" + payload +
            "\n\nReturn a JSON array. One object per requirement: "
            '{"block": <block id>, "text": "<requirement, faithful to source wording>", "category": "Functional|Non-functional|Compliance|Commercial", '
            f'"subcategory": one of {SUBCATS}, "priority": "Mandatory|Desirable", "ref": "<id printed in the RFP or empty>", "confidence": 0.0-1.0}}. '
            "Categories: Functional = what the solution/service must do; Non-functional = quality attributes and service levels "
            "(performance, availability, security controls, SLAs); Compliance = laws, regulations, standards, certifications, policies, "
            "submission rules; Commercial = price, payment, bonds, insurance, contract terms, evaluation and award. "
            "Return [] if the blocks contain no requirements." + guidance
        )
        items = None
        for attempt in range(2):  # one retry per part before falling back to the rules engine for it
            try:
                items = llm.complete_json(LLM_SYSTEM, prompt, max_tokens=12000)
                break
            except Exception:
                if progress and attempt == 0:
                    progress(f"AI reading the RFP: retrying part {n} of {len(batches)}")
        if items is None:
            failures += 1
            if failed is not None:
                failed.extend(b.idx for b in chunk)
            if failures >= 2 and not out:
                return []
            continue
        if isinstance(items, dict):
            items = items.get("requirements") or next((v for v in items.values() if isinstance(v, list)), [])
        for it in items if isinstance(items, list) else []:
            if not isinstance(it, dict):
                continue
            b = by_idx.get(int(it.get("block", -1))) if str(it.get("block", "")).lstrip("-").isdigit() else None
            if not b or not it.get("text"):
                continue
            cat = it.get("category") if it.get("category") in K.CATEGORIES else None
            sub = it.get("subcategory") if it.get("subcategory") in SUBCATS else None
            if not cat:
                cat, sub2, _ = K.classify(it["text"], b.section)
                sub = sub or sub2
            if not sub:
                sub = K.classify(it["text"], b.section)[1]
            try:
                conf = float(it.get("confidence", 0.9))
            except (TypeError, ValueError):
                conf = 0.9
            out.append({"text": str(it["text"]).strip(), "category": cat, "subcategory": sub,
                        "priority": it.get("priority") if it.get("priority") in ("Mandatory", "Desirable") else K.priority(it["text"]),
                        "page": b.page, "section": b.section[:290], "block_idx": b.idx,
                        "source_ref": (it.get("ref") or b.ref or "")[:30] if (it.get("ref") or b.ref) != "header" else "",
                        "class_confidence": round(max(0.3, min(0.99, conf)), 2), "classified_by": "ai"})
    return out


# --------------------------------------------------------------------------- metadata
def extract_metadata(doc: ParsedDocument) -> dict:
    text = doc.text
    head = text[:5000]
    low = text.lower()
    meta: dict = {}
    if re.search(r"request for information|\brfi\b", head, re.I):
        meta["doc_type"] = "RFI"
    elif re.search(r"request for quotation|\brfq\b", head, re.I):
        meta["doc_type"] = "RFQ"
    elif re.search(r"statement of work|\bsow\b", head[:1500], re.I) and not re.search(r"request for proposal", head, re.I):
        meta["doc_type"] = "SOW"
    else:
        meta["doc_type"] = "RFP"

    title = ""
    first = doc.blocks[:12]
    for i, b in enumerate(first):
        m = re.match(r"project title\s*:?\s*(.+)", b.text, re.I)
        if m:
            title = m.group(1).strip()
            nxt = first[i + 1] if i + 1 < len(first) else None
            if nxt and nxt.page == b.page and nxt.kind == "heading" and nxt.text[:1].islower() or (nxt and nxt.text.lower().startswith("and ")):
                title += " " + nxt.text
            break
    if not title:
        for i, b in enumerate(first):
            if re.fullmatch(r"(request for (proposal|information|quotation)|rf[piq])\s*(\(rf[piq]\))?", b.text.strip(), re.I) and i + 1 < len(first):
                cand = first[i + 1].text
                if 15 < len(cand) < 200:
                    title = cand
                break
    if not title:
        from pathlib import Path
        stem = Path(doc.filename).stem
        stem = re.sub(r"\(\d+\)|\b(rfp|rfi|rfq)\b|request for (proposal|information|quotation)|_v\d+|[()_]", " ", stem, flags=re.I)
        title = re.sub(r"\s*-\s*", " ", re.sub(r"\s+", " ", stem)).strip(" -")
    meta["title"] = re.sub(r"[\[\]]", "", title)[:200]

    # the currency the RFP names most often wins; "$" alone is too ambiguous to count
    cur_pats = {"AED": r"\baed\b|dirham", "KWD": r"\bkwd\b|kuwaiti dinar", "SAR": r"\bsar\b|saudi riyal", "INR": r"\binr\b|rupee",
                "AUD": r"\baud\b|australian dollar", "GBP": r"\bgbp\b|pounds? sterling|£", "EUR": r"\beur\b|\beuros?\b|€",
                "SGD": r"\bsgd\b|singapore dollar", "QAR": r"\bqar\b|qatari riyal", "CAD": r"\bcad\b|canadian dollar",
                "USD": r"\busd\b|us dollars?|u\.s\. dollars?"}
    counts = {c: len(re.findall(p, low)) for c, p in cur_pats.items()}
    cur = max(counts, key=counts.get) if max(counts.values()) else None
    meta["currency"] = cur or ""

    due = ""
    date_re = r"(\d{1,2}(?:st|nd|rd|th)?\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+\d{4}|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4})"
    for pat in [r"(?:proposal|bid|tender|submission|response)s?\s+(?:due|closing)\s+date\s*[:|]?\s*" + date_re,
                r"(?:due date|deadline|closing date)\s*(?:and time)?\s*(?:for submission)?\s*[:|]?\s*" + date_re,
                r"submitted[^.\n]{0,80}?\bby\s+" + date_re,
                r"closing date(?: and time)?\s*[:|]?\s*\[?([^\]\n|]{4,40})", r"submission deadline\s*[:|]?\s*([^\n|]{4,40})",
                r"closing date\s*\|\s*([0-9]{1,2}[-/.][0-9]{1,2}[-/.][0-9]{2,4})"]:
        m = re.search(pat, text, re.I)
        if m:
            due = m.group(1).strip(" :[]")
            break
    meta["due_date"] = due

    m = re.search(r"(\d+|one|two|three|four|five)\s*\(?\d*\)?\s*(year|month)s?\s*(contract|term|duration|period)", low) or \
        re.search(r"(?:contract|initial|service|managed service)?\s*(term|duration|period) of (?:an? )?(?:initial )?(\d+|one|two|three|four|five)\s*\(?\d*\)?\s*(year|month)", low) or \
        re.search(r"contract (term|duration|period) (of )?(\d+)\s*(year|month)", low)
    words = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
    term_months = None
    if m:
        g = m.groups()
        try:
            if g[0] in ("term", "duration", "period") and len(g) == 3:  # "term of three years"
                n = int(g[1]) if g[1].isdigit() else words[g[1]]
                unit = g[2]
            elif g[0] in ("term", "duration", "period"):
                n, unit = int(g[2]), g[3]
            else:
                n = int(g[0]) if g[0].isdigit() else words[g[0]]
                unit = g[1]
            term_months = n * 12 if unit.startswith("year") else n
        except Exception:
            term_months = None
    meta["contract_term_months"] = term_months

    scores = {
        "managed_services": len(re.findall(r"managed service|steady[- ]state|24\s?x\s?7|\bsla\b|incident management|run and maintain|operations support", low)),
        "product": len(re.findall(r"licen[cs]e|saas|subscription|procure|out[- ]of[- ]the[- ]box|vendor product|sdk|platform limitations", low)),
        "consulting": len(re.findall(r"assessment|advisory|roadmap|target state|current state|maturity|enterprise architecture services|recommendation", low)),
        "implementation": len(re.findall(r"implement|design and build|develop|migration|go-live|rollout|deploy", low)),
    }
    if meta["doc_type"] == "RFI":
        scores["consulting"] += 3
    # How long the build is meant to take: "complete within 12 months of contract signature", "a 9-month implementation".
    bm = re.search(r"(?:build|implementation|migration|delivery|deploy\w*)[^.]{0,80}?(?:within|in|over)\s+(\d{1,2})\s+months", low) or \
        re.search(r"(\d{1,2})[- ]month (?:build|implementation|programme|program|project|migration)", low)
    meta["build_months"] = int(bm.group(1)) if bm and 2 <= int(bm.group(1)) <= 36 else None
    # Pricing instructions: "price the build as fixed price by milestone and the managed service as a fixed monthly fee".
    meta["pricing_model"] = {
        "milestones": bool(re.search(r"(fixed[- ]price|price)[^.]{0,40}(by|per|against) milestones?|milestone[- ]based (payment|pricing)", low)),
        "monthly_fee": bool(re.search(r"monthly (fee|charge|service charge)|per month|fixed monthly", low)),
        "time_and_materials": bool(re.search(r"time[- ]and[- ]materials?|\bt&m\b|daily rates?|day rates?", low)),
    }
    # The client's own milestone plan, from a "Milestone | Target" table: [{"name": ..., "month": 4}, ...]
    ms, on = [], False
    for line in text.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if len(cells) >= 2 and re.match(r"^(key )?milestones?$", cells[0], re.I):
            on = True
            continue
        mm = re.match(r"^(?:month|m)\s*(\d{1,2})$", cells[-1], re.I) if on and len(cells) >= 2 else None
        if mm:
            ms.append({"name": cells[0][:120], "month": int(mm.group(1))})
        elif on and ms:
            break
    meta["rfp_milestones"] = ms[:12]
    eng = max(scores, key=scores.get)
    # Build and run in one contract: a build or migration with a timeline, plus a managed service to follow.
    builds = scores["implementation"] >= 3 and (meta["build_months"] or meta["pricing_model"]["milestones"])
    runs = scores["managed_services"] >= 3 and (meta["pricing_model"]["monthly_fee"] or re.search(r"operate[^.]{0,60}managed service|managed service[^.]{0,80}(term|years)", low))
    if eng in ("implementation", "managed_services") and builds and runs:
        eng = "build_run"
    meta["engagement_type"] = eng
    meta["engagement_scores"] = scores

    industries = {
        "Healthcare": r"health|hospital|clinical|patient|hl7|fhir|pharma",
        "BFSI": r"\bbank|financial services|insurance|capital markets|fraud|lending|wealth management",
        "Transportation": r"transit|transport|railway|light rail|\bbus(es)?\b|ferr(y|ies)|aviation|airport|airline|logistics|port authority|vehicle",
        "Retail": r"retail|e-?commerce|store|merchandis",
        "Telecom": r"telecom|mobile network|\b5g\b|subscriber",
        "Energy & utilities": r"utilit(y|ies)|electricity|power grid|oil and gas|energy",
        "Government": r"ministry|municipalit|citizen services|e-government",
        "Manufacturing": r"manufactur|factory|plant floor|industry 4\.0",
    }
    ind_scores = {k: len(re.findall(p, low)) for k, p in industries.items()}
    best = max(ind_scores, key=ind_scores.get)
    meta["industry"] = best if ind_scores[best] >= 2 else "Cross-industry"
    meta["sector"] = "Public" if re.search(r"government|authority|ministry|public sector|municipality", head, re.I) else "Private"
    regions = [("UAE", r"\bu\.?a\.?e\b|dubai|abu dhabi|emirat"), ("Kuwait", r"kuwait"), ("Saudi Arabia", r"saudi|riyadh|ksa"),
               ("India", r"\bindia\b"), ("USA", r"united states|\busa\b"), ("Singapore", r"singapore"), ("Qatar", r"qatar|doha"),
               ("Australia", r"australia|sydney|melbourne|brisbane|perth"), ("United Kingdom", r"united kingdom|\buk\b|london"),
               ("Canada", r"canada|toronto|ottawa")]
    meta["region"] = next((r for r, p in regions if re.search(p, low)), "")
    return meta


def extract_requirements(doc: ParsedDocument, use_llm: bool = True, mask_fn=lambda x: x, guidance: str = "",
                         progress=None) -> tuple[list[dict], dict, str]:
    """Returns (requirements, metadata, engine)."""
    rules_reqs, rmeta = rules_extract(doc)
    for r in rules_reqs:
        r["classified_by"] = "rules"
    reqs, engine = rules_reqs, "rules"
    if use_llm and llm.is_enabled():
        failed: list[int] = []
        lreqs = llm_extract(doc, mask_fn, guidance, progress, failed)
        failed_set = set(failed)
        expected = sum(1 for r in rules_reqs if r["block_idx"] not in failed_set)
        if lreqs and len(lreqs) >= max(5, int(expected * 0.5)):
            covered = {r["block_idx"] for r in lreqs}
            for r in rules_reqs:
                # Parts the AI couldn't read are filled in by the rules engine, and RFP rows with their own
                # requirement ID are never dropped.
                if r["block_idx"] not in covered and (r["block_idx"] in failed_set or r.get("source_ref")):
                    lreqs.append(r)
            lreqs.sort(key=lambda r: (r["block_idx"]))
            reqs, engine = lreqs, "ai"
    for r in reqs:
        b = doc.blocks[r["block_idx"]] if 0 <= r["block_idx"] < len(doc.blocks) else None
        context = f"{r['text']} {r['section']}"
        r["technologies"] = K.find_technologies(context if b is None else f"{r['text']} {r['section']}")
    meta = extract_metadata(doc)
    meta.update(rmeta)
    return reqs, meta, engine
