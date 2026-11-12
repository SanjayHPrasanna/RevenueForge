"""Stages 7 & 8 - Proposal Generation and Delivery Handoff.

The proposal is written into the company's own Word template (styles, header, footer, cover
placeholders preserved). Every claim in it comes from matched evidence in the company's
knowledge base; nothing is invented.
"""
from __future__ import annotations

import copy
import io
import re
from datetime import date

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from . import llm

ENG_LABEL = {"managed_services": "outcome-based managed service", "build_run": "platform build and migration followed by an outcome-based managed service",
             "product": "product-led solution with full system integration",
             "consulting": "enterprise architecture advisory engagement", "implementation": "design-and-build implementation"}
COMPLIANCE = {"strong": "Fully compliant", "partial": "Compliant (with approach)", "gap": "Partially compliant – mitigation", "confirm": "Acknowledged"}


def _is_standard_name(t: str) -> bool:
    from .matching import _is_standard
    return _is_standard(t)


def client_ref(r: dict) -> str:
    """The reference a client recognises: the RFP's own ID, else its section number, else its page. Never our REQ-0xx codes."""
    if r.get("source_ref"):
        return r["source_ref"]
    m = re.match(r"\s*(\d+(?:\.\d+)*)[.)]?\s", (r.get("section") or "") + " ")
    if m:
        return f"§{m.group(1)}"
    return f"p.{r['page']}" if r.get("page") else ""


def compliance_label(r: dict) -> str:
    """The compliance column. "Fully compliant" needs evidence: a held certificate, the AI check, a reviewer, or the rules
    engine's direct match. A match the AI was meant to check but couldn't is never presented as fully compliant."""
    st = r.get("match_status")
    m = r.get("match") or {}
    if st == "strong" and m.get("unverified") and not r.get("verified"):
        return COMPLIANCE["partial"]
    if st == "confirm" and r.get("category") == "Compliance" and r.get("subcategory") != "Submission":
        # A promise to comply needs something behind it; without evidence the position is stated honestly.
        return "Will comply" if (m.get("evidence") or m.get("held_certificates")) else "To be confirmed"
    return COMPLIANCE.get(st, "")


# "The bidder shall provide X" -> "We will provide X." Used when no AI-written answer is available.
_SUBJ_RE = re.compile(r"^\s*(?:the\s+)?(bidder|tenderer|supplier|contractor|vendor|service provider|successful bidder|proposer|respondent|"
                      r"solution|platform|system|service)s?\s+(?:shall|must|should|will|is required to|are required to)\s+(?:be able to\s+)?(.+?)\.?\s*$", re.I)


def _commit_sentence(text: str) -> str:
    m = _SUBJ_RE.match(text.strip())
    if not m:
        return ""
    who, rest = m.group(1).lower(), m.group(2).strip().rstrip(".")
    rest = re.sub(r"\b(its|their)\b", "our", rest)
    if len(rest) > 220:
        return ""
    if who in ("solution", "platform", "system", "service"):
        return f"Our {who} will {rest}."
    return f"We will {rest}."


def money(v: float, ccy: str) -> str:
    if v >= 1_000_000:
        return f"{ccy} {v / 1_000_000:,.2f}M"
    return f"{ccy} {v:,.0f}"


# --------------------------------------------------------------------------- narrative
def response_text(r: dict, company: str) -> str:
    m = r.get("match", {})
    ev = m.get("evidence", [])
    caps = [e["name"] for e in ev if e["type"] == "Capability"]
    cs = [e["name"] for e in ev if e["type"] == "Case study"]
    acc = [e["name"] for e in ev if e["type"] == "Accelerator"]
    certs = [e["name"] for e in ev if e["type"] == "Certification"]
    st = r.get("match_status")
    if st == "confirm":
        dm = re.match(r"Deliverable:\s*(.+?)(?:\s+[—–-]\s+(.+))?$", r.get("text", ""))
        if dm:
            due = (dm.group(2) or "").strip()
            return f"We will deliver the {dm.group(1).strip().rstrip('.')}" + (f" ({due.lower() if due.lower().startswith(('each', 'before')) else 'by ' + due})." if due else ".")
        if r.get("subcategory") in ("Submission", "Evaluation & Award") or re.search(r"\bin (their|the|your) (response|proposal)\b", r.get("text", ""), re.I):
            return f"{company} acknowledges this and has prepared the response accordingly."
        if r.get("category") == "Commercial":
            return f"{company} acknowledges this condition; our position is confirmed in the commercial response."
        commit = _commit_sentence(r.get("text", ""))
        return (commit + " " if commit else "") + "We will comply with this obligation and confirm the specific controls with your security and legal teams during mobilisation."
    if st == "gap" and not (r.get("gap") or {}).get("options"):
        # Nothing in the library covers it and no mitigation was chosen: never write a promise the company can't keep.
        return ("[NOT COVERED: nothing in the knowledge library supports this requirement and no mitigation has been chosen. "
                "Decide whether to partner, hire, take an exception or not bid before this proposal is sent.]")
    parts = []
    missing_std = [t for t in m.get("technologies_missing", []) if _is_standard_name(t)]
    # never "commit" to holding a certificate we don't have
    commit = "" if missing_std or certs else _commit_sentence(r.get("text", ""))
    if commit:
        parts.append(commit)
    if certs:
        parts.append(f"{company} holds {', '.join(certs)}.")
    if caps and not (missing_std and st == "gap"):  # a missing certificate isn't "delivered through" a capability
        lead = "This is delivered through" if commit else "Delivered through"
        parts.append(f"{lead} our {caps[0]} capability" + (f", accelerated by {acc[0]}" if acc else "") + ".")
    if m.get("people_count"):
        n = m["people_count"]
        parts.append(f"{n} engineer{'s' if n != 1 else ''} with {', '.join(m.get('technologies_have', [])[:3])} skills "
                     f"{'are' if n != 1 else 'is'} available to the programme.")
    if cs:
        parts.append(f"Reference: {cs[0]}.")
    if st in ("partial", "gap") and r.get("gap", {}).get("options"):
        o = r["gap"]["options"][0]
        missing = ", ".join(m.get("technologies_missing", [])[:2]) or "this area"
        client_facing = {
            "Partner": f"Delivered together with our specialist {missing} partner, with {company} as prime contractor and integrator.",
            "Upskill": f"Our engineers are completing {missing} certification ahead of mobilisation, backed by our existing integration practice.",
            "Hire": f"Dedicated {missing} specialists will join the team before mobilisation.",
            "Certify": (f"{company} does not currently hold {', '.join(missing_std) or missing}. We operate certified controls"
                        + (f" ({', '.join(c['name'] for c in m.get('held_certificates', [])[:2])})" if m.get("held_certificates") else "")
                        + " and will provide independent assurance evidence; we ask you to confirm whether this is mandatory for award."),
            "Define method": f"{company} will apply its standard delivery method for this, detailed in Section 4 and confirmed with you during mobilisation.",
            "Build": f"{company} will design and validate a dedicated solution component for this requirement during the design phase.",
        }.get(o["type"])
        if client_facing:
            parts.append(client_facing)
    return " ".join(parts) or f"{company} will meet this requirement as part of the delivery approach."


def ai_responses(reqs: list[dict], company: dict, client: str, guidance: str = "", progress=None) -> dict[str, str]:
    """AI drafts the client-facing response for each requirement, using only its matched evidence."""
    # A gap with no chosen mitigation gets the NOT COVERED marker from response_text, never an AI-polished promise.
    todo = [r for r in reqs if r["category"] != "Commercial" and r.get("match_status") != "confirm"
            and not (r.get("match_status") == "gap" and not (r.get("gap") or {}).get("options"))]
    out: dict[str, str] = {}
    batches = [todo[i:i + 15] for i in range(0, len(todo), 15)]
    for n, chunk in enumerate(batches, start=1):
        if progress:
            progress(f"AI writing proposal responses: batch {n} of {len(batches)}")
        lines = []
        for k, r in enumerate(chunk):
            m = r.get("match", {})
            ev = "; ".join(f"{e['type']}: {e['name']}" for e in m.get("evidence", [])[:4]) or "none"
            opt = (r.get("gap", {}).get("options") or [{}])[0] if r.get("match_status") in ("gap", "partial") else {}
            # "Strengthen evidence" is our own to-do (add a reference to the bid), not something to tell the client.
            plan = opt.get("detail", "") if opt.get("type") not in (None, "Strengthen evidence") else ""
            lines.append(f"[{k}] REQUIREMENT: {r['text'][:400]}\n  fit: {r.get('match_status')} | evidence: {ev} | "
                         f"people: {m.get('people_count', 0)} with {', '.join(m.get('technologies_have', [])[:3]) or 'relevant skills'}"
                         + (f"\n  plan to close gap: {plan[:240]}" if plan else ""))
        prompt = (f"Company: {company['name']}. {company.get('about', '')[:500]}\nClient: {client}\n\n" + "\n".join(lines) +
                  '\n\nWrite the response for each requirement as it will appear in the proposal compliance matrix: 2-3 sentences, confident, '
                  "specific, first person plural (we). Mention the cited capability, reference project or certification by name. For a gap or "
                  "partial fit, describe the plan to close it (a partner, new hires, a build) plainly: never say or imply the company already has "
                  "a capability, certificate or reference it doesn't have, and never invent facts. This text goes to the client as it is: "
                  "never mention our internal review, evidence-gathering, adding references or demos to the bid, hiring status, "
                  "employee codes or requirement IDs, and cite a reference project only where it does the same kind of work. JSON array: "
                  '[{"i": index, "response": "..."}]' + guidance)
        res = None
        for _ in range(2):  # one retry, then move on: a failed batch keeps the rules answer and later batches still run
            try:
                res = llm.complete_json("You are an expert bid writer. Use only the facts provided. Never invent clients, numbers, certifications or products.",
                                        prompt, max_tokens=9000)
                break
            except Exception:
                res = None
        if res is None:
            continue
        if isinstance(res, dict):
            res = next((v for v in res.values() if isinstance(v, list)), [])
        for it in res if isinstance(res, list) else []:
            try:
                text = str(it["response"]).strip()[:1200]
                if INTERNAL_RE.search(text):
                    continue  # reads like an internal note: the rules answer stays in the proposal instead
                out[chunk[int(it["i"])]["id"]] = text
            except Exception:
                continue
    return out


# Wording that belongs in our own notes, never in a client document.
INTERNAL_RE = re.compile(r"\b(we (?:plan|intend|will need) to add (?:a )?(?:reference|demo|named expert)|reference project, demo|named expert to (?:our|the) "
                         r"(?:response|bid)|to (?:our|the) response|\(\+\d+ to hire\)|to be hired|knowledge library|evidence is thin|"
                         r"REQ-\d{2,4}|KD\d{3})", re.I)


def executive_summary(ctx: dict) -> str:
    d, company = ctx["deal"], ctx["company"]
    g, est, pr = ctx["gaps"], ctx["estimation"], ctx["pricing"]
    sc = next((s for s in pr["scenarios"] if s["name"] == ctx.get("scenario", "Target")), pr["scenarios"][1])
    rfp_price = sc["price"] * pr["fx_to_rfp"]
    counts = g.get("counts", {})
    tech = [r for r in ctx["requirements"] if r["category"] in ("Functional", "Non-functional")]
    planned_gaps = sum(1 for r in ctx["requirements"] if r.get("match_status") == "gap" and (r.get("gap") or {}).get("options"))
    open_gaps = sum(1 for r in ctx["requirements"] if r.get("match_status") == "gap") - planned_gaps
    cs = ctx.get("case_studies", [])[:2]
    cs_txt = "; ".join(f"{c['title']} ({'; '.join(c.get('outcomes', [])[:1]) or c.get('industry', '')})" for c in cs)
    if llm.is_enabled():
        try:
            facts = {
                "client": d["client_display"], "rfp_title": d["name"], "engagement": ENG_LABEL.get(d["engagement_type"], ""),
                "company": company["name"], "company_about": company.get("about", ""), "requirements": len(ctx["requirements"]),
                "technical_requirements": len(tech), "fully_met": counts.get("strong", 0), "met_with_approach": counts.get("partial", 0),
                "gaps_closed_by_mitigation_plan": planned_gaps, "gaps_without_a_plan_do_not_claim_these": open_gaps, "conditions_and_submission_items_acknowledged": counts.get("confirm", 0),
                "team_size": est["headcount"], "duration_months": est["contract_months"],
                "build_months": est.get("build_months") if d["engagement_type"] == "build_run" else None,
                "managed_service_months": est.get("run_months"),
                "pricing_structure": [m["name"] for m in pr.get("milestones", [])][:8],
                "price": money(rfp_price, pr["rfp_currency"]), "references": cs_txt, "architecture": ctx["architecture"]["summary"],
                "evaluation_criteria": [e["criterion"] for e in ctx["meta"].get("evaluation_criteria", [])],
            }
            return llm.complete("You write crisp, factual executive summaries for enterprise proposals. Use only the facts given. 3 short paragraphs, "
                                "no headings, no bullet points. Don't mention counts that are zero, don't describe the company as serving "
                                "industries that aren't in the facts, and never say every requirement is met or covered unless the facts show "
                                "no gaps without a plan.",
                                f"Facts (JSON): {facts}", max_tokens=900).strip()
        except Exception:
            pass
    p1 = (f"{d['client_display']} is seeking a partner for {d['name']}. {company['name']} proposes {_a(ENG_LABEL.get(d['engagement_type'], 'engagement'))} "
          f"in response to the {len(ctx['requirements'])} requirements identified in the RFP, including {len(tech)} functional and non-functional requirements.")
    bits = [f"{counts.get('strong', 0)} requirements are met by proven, in-house capabilities"]
    if counts.get("partial"):
        bits.append(f"{counts['partial']} by extending them")
    p2 = "; ".join(bits) + (f", and {planned_gaps} more are covered by the mitigation plan in this proposal. " if planned_gaps else ". ") \
        + (f"[INTERNAL - remove before sending: {open_gaps} requirement{'s have' if open_gaps != 1 else ' has'} no capability or mitigation yet.] "
           if open_gaps else "") \
        + (f"Relevant references include {cs_txt}. " if cs_txt else "") + ctx["architecture"]["summary"]
    if d["engagement_type"] == "build_run" and est.get("build_months"):
        when = f"build and migrate the platform in {est['build_months']} months and then run it for {est.get('run_months')} months"
    else:
        when = f"deliver over {est['contract_months']} months"
    pay = ("with the build priced by milestone and the managed service as a fixed monthly fee" if pr.get("phase_split")
           else "with payments linked to accepted milestones")
    p3 = (f"A {est['headcount']}-person team, led by an engagement manager accountable for outcomes, will {when}. "
          f"Our commercial offer is {money(rfp_price, pr['rfp_currency'])}, {pay}.")
    return "\n\n".join([p1, p2, p3])


# --------------------------------------------------------------------------- docx helpers
#
# A company's proposal template can come in three shapes, and each is handled differently:
#   marker    - it contains {{CONTENT}}: the generated proposal goes exactly there (the template author decided).
#   sections  - it has its own section headings with placeholders such as "[Insert Solution Overview Here]":
#               each placeholder is filled with the matching generated content, the template's sample tables
#               (example figures that are not this company's facts) are removed, and anything left unplaced is
#               added as an appendix.
#   styles    - neither: only the look is reused (styles, page setup, header, footer, logo); the body is replaced.
# The delivery handoff is an internal document, so it always uses the template's look only.

PLACEHOLDER_RE = re.compile(r"^\s*[\[<«]\s*(insert|enter|add|provide|describe|include|type|write|paste|place)\b[^\]>»]{0,160}[\]>»]\s*\.?\s*$", re.I)


def _replace_in_paragraph(p, mapping: dict[str, str]):
    full = "".join(r.text for r in p.runs)
    if "{{" not in full:
        return
    new = full
    for k, v in mapping.items():
        new = new.replace("{{" + k + "}}", v)
    if new != full and p.runs:
        p.runs[0].text = new
        for r in p.runs[1:]:
            r.text = ""


def _replace_everywhere(doc, mapping):
    for p in doc.paragraphs:
        _replace_in_paragraph(p, mapping)
    for t in doc.tables:
        for row in t.rows:
            for c in row.cells:
                for p in c.paragraphs:
                    _replace_in_paragraph(p, mapping)
    for s in doc.sections:
        for part in (s.header, s.footer, s.first_page_header, s.first_page_footer):
            try:
                for p in part.paragraphs:
                    _replace_in_paragraph(p, mapping)
            except Exception:
                pass


def _style(doc, name, fallback="Normal"):
    try:
        doc.styles[name]
        return name
    except KeyError:
        return fallback


def _shade(cell, hex_fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hex_fill)
    tcPr.append(shd)


def _clip(text: str, n: int) -> str:
    """Shorten at a word boundary and say so, instead of cutting mid-word."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0].rstrip(",;:–-")
    return cut + "…"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


class Writer:
    """Writes blocks either before an anchor element (a placeholder or {{CONTENT}}) or at the end of the body."""

    def __init__(self, doc, anchor=None):
        self.doc = doc
        self.anchor = anchor
        self.body = doc.element.body
        self.wrote = 0

    def _place(self, el):
        if self.anchor is not None:
            self.anchor.addprevious(el)
        else:
            sect = self.body.find(qn("w:sectPr"))
            if sect is not None:
                sect.addprevious(el)
            else:
                self.body.append(el)
        self.wrote += 1

    def h(self, text, level=1):
        p = self.doc.add_paragraph(text, style=_style(self.doc, f"Heading {level}"))
        self._place(p._p)
        return p

    def title(self, text):
        p = self.doc.add_paragraph(text, style=_style(self.doc, "Title", _style(self.doc, "Heading 1")))
        self._place(p._p)
        return p

    def p(self, text, bold_prefix: str | None = None, italic=False, size=None, color=None):
        p = self.doc.add_paragraph(style=_style(self.doc, "Normal"))
        if bold_prefix:
            r = p.add_run(bold_prefix)
            r.bold = True
        r = p.add_run(text)
        r.italic = italic
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = color
        self._place(p._p)
        return p

    def bullets(self, items):
        st = _style(self.doc, "List Bullet")
        mark = "" if st == "List Bullet" else "•  "  # templates without a bullet style still get visible bullets
        for it in items:
            p = self.doc.add_paragraph(mark + it, style=st)
            if mark:
                p.paragraph_format.left_indent = Pt(14)
                p.paragraph_format.first_line_indent = Pt(-10)
            self._place(p._p)

    def table(self, header, rows, widths=None, font=8.5):
        from docx.shared import Cm
        t = self.doc.add_table(rows=1, cols=len(header))
        t.autofit = False
        try:
            t.style = self.doc.styles["Table Grid"]
        except KeyError:
            pass
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        for i, h in enumerate(header):
            c = t.rows[0].cells[i]
            c.text = ""
            r = c.paragraphs[0].add_run(str(h))
            r.bold = True
            r.font.size = Pt(font)
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
            _shade(c, "1F3A5F")
        for row in rows:
            cells = t.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ""
                r = cells[i].paragraphs[0].add_run(str(v))
                r.font.size = Pt(font)
        if widths:
            grid = t._tbl.tblGrid
            for i, gc in enumerate(grid.findall(qn("w:gridCol"))):
                if i < len(widths):
                    gc.set(qn("w:w"), str(int(widths[i] * 567)))
            for row in t.rows:
                for i, wcm in enumerate(widths[:len(row.cells)]):
                    row.cells[i].width = Cm(wcm)
        self._place(t._tbl)
        spacer = self.doc.add_paragraph()
        self._place(spacer._p)
        return t

    def page_break(self):
        from docx.enum.text import WD_BREAK
        p = self.doc.add_paragraph()
        p.add_run().add_break(WD_BREAK.PAGE)
        self._place(p._p)


class Numbered:
    """Section headings numbered in the order they are actually written, so skipped sections leave no gaps."""

    def __init__(self, w: Writer, level=1):
        self.w, self.level, self.n = w, level, 0

    def __call__(self, text):
        self.n += 1
        return self.w.h(f"{self.n}. {text}", self.level)


def _open_template(template_bytes: bytes | None):
    if template_bytes:
        try:
            return Document(io.BytesIO(template_bytes))
        except Exception:
            pass
    return Document()


def _placeholders(doc) -> list:
    return [p for p in doc.paragraphs if PLACEHOLDER_RE.match(p.text or "")]


def template_mode(doc) -> str:
    if any("{{CONTENT}}" in p.text for p in doc.paragraphs):
        return "marker"
    if len(_placeholders(doc)) >= 2:
        return "sections"
    return "styles"


def _clear_body(doc):
    """Keep page setup, header, footer and styles; drop the template's body content."""
    body = doc.element.body
    for el in list(body.iterchildren()):
        if el.tag != qn("w:sectPr"):
            body.remove(el)


def _remove(el):
    parent = el.getparent()
    if parent is not None:
        parent.remove(el)


def _retitle(doc, title: str, subtitle: str) -> bool:
    """A template's own title ('… Proposal Template') becomes the deal's title."""
    for p in doc.paragraphs[:8]:
        if p.style.name.startswith(("Title", "Heading 1")) and re.search(r"template|proposal title|\btitle\b", p.text, re.I):
            for r in p.runs[1:]:
                r.text = ""
            if p.runs:
                p.runs[0].text = title
            else:
                p.add_run(title)
            sub = p._p.makeelement(qn("w:p"), {})
            p._p.addnext(sub)
            from docx.text.paragraph import Paragraph
            sp = Paragraph(sub, p._parent)
            sp.style = doc.styles[_style(doc, "Subtitle")]
            sp.add_run(subtitle)
            return True
    return False


# --------------------------------------------------------------------------- shared content blocks
class Content:
    """Every block of the proposal, written from the deal's own data. Blocks can be placed in any order."""

    def __init__(self, ctx: dict):
        self.ctx = ctx
        d, company = ctx["deal"], ctx["company"]
        self.d, self.company, self.cname = d, company, company["name"]
        self.reqs = ctx["requirements"]
        self.est, self.pr, self.arch, self.g = ctx["estimation"], ctx["pricing"], ctx["architecture"], ctx["gaps"]
        self.summary = ctx.get("executive_summary") or executive_summary(ctx)
        self.sc = next((s for s in self.pr["scenarios"] if s["name"] == ctx.get("scenario", "Target")), self.pr["scenarios"][1])
        self.fx, self.ccy = self.pr["fx_to_rfp"], self.pr["rfp_currency"]
        self.price = self.sc["price"] * self.fx
        self.compliance_rows = 0

    # -- narrative
    def executive_summary(self, w):
        for para in self.summary.split("\n\n"):
            if para.strip():
                w.p(para.strip())

    def at_a_glance(self, w):
        g, est = self.g, self.est
        w.table(["At a glance", ""], [
            ["Engagement model", ENG_LABEL.get(self.d["engagement_type"], self.d["engagement_type"]).capitalize()],
            ["Requirements addressed", _req_breakdown(len(self.reqs), g.get("counts", {}))],
            ["Team", f"{est['headcount']} people ({est['fte']} FTE at peak), {round(est.get('onsite_share', est['onsite_ratio']) * 100)}% onsite"],
            ["Duration", (f"{est['build_months']}-month build, then a {est['run_months']}-month managed service"
                          if self.d["engagement_type"] == "build_run" and est.get("build_months") else f"{est['contract_months']} months")],
            ["Commercial offer", money(self.price, self.ccy)],
        ], widths=[5.0, 11.7])

    def value(self, w):
        self.executive_summary(w)
        self.at_a_glance(w)

    def understanding(self, w):
        by_cat: dict[str, int] = {}
        for r in self.reqs:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
        w.p(f"We analysed the {self.d['doc_type']} in full and identified {len(self.reqs)} requirements: "
            + ", ".join(f"{v} {k.lower()}" for k, v in by_cat.items()) + ". Each one is traced to its page in the source document in the compliance matrix.")
        ws = self.ctx["meta"].get("workstreams") or []
        if ws:
            w.p("The scope covers these workstreams, each answered in this proposal:")
            w.table(["Workstream", "Summary"], [[x["name"], x.get("summary", "")] for x in ws], widths=[5.0, 11.7])
        objectives = [o for o in self.ctx["meta"].get("objectives") or [] if not PROCESS_SENTENCE_RE.search(o)]
        key = objectives[:8] or [r["text"] for r in self.reqs if r["category"] in ("Functional", "Non-functional") and r.get("priority") == "Mandatory"
                                 and not PROCESS_SENTENCE_RE.search(r["text"])][:8]
        if key:
            w.p("The outcomes we will deliver include:")
            w.bullets([_clip(t, 220) for t in key])
        ev = self.ctx["meta"].get("evaluation_criteria", [])
        if ev:
            w.p("How our response maps to your evaluation criteria:")
            w.table(["Criterion", "Weight"], [[re.sub(r":\s*\d+\s*%$", "", e["criterion"]), f"{e['weight']}%" if e.get("weight") is not None else ""] for e in ev],
                    widths=[13.2, 3.5])

    def solution(self, w):
        w.p(self.arch["summary"])
        rows = [[l["layer"], "; ".join(c["name"] + (" (partner)" if c["source"] == "Partner product" else "") for c in l["components"][:6])]
                for l in self.arch["layers"]]
        if rows:
            w.table(["Layer / domain", "Components"], rows, widths=[4.5, 12.2])

    def tech_stack(self, w):
        if self.arch.get("choices"):
            w.table(["Area", "Choice", "Basis", "Rationale"], [[c["area"], c["choice"], c["basis"], c["rationale"]] for c in self.arch["choices"]],
                    widths=[3.6, 4.2, 3.0, 5.9])
        else:
            self.solution(w)

    def differentiators(self, w):
        g = self.g
        tech = [r for r in self.reqs if r.get("match_status") in ("strong", "partial", "gap")]
        items = [f"{g['counts'].get('strong', 0) + g['counts'].get('partial', 0)} of the {len(tech)} technical and service requirements are met by capabilities we deliver today."]
        cases = self.ctx.get("case_studies", [])
        if cases:
            same = [c for c in cases if self.d.get("industry") and self.d["industry"].lower() in (c.get("industry") or "").lower()]
            items.append(("Proven in your industry: " if same else "Proven on comparable integration programmes: ") + "; ".join(c["title"] for c in cases[:3]) + ".")
        if self.est.get("accelerators"):
            items.append("Reusable accelerators that cut effort and risk: " + ", ".join(a["name"] for a in self.est["accelerators"]) + ".")
        certs = self.ctx.get("certifications", [])
        if certs:
            items.append("Certified: " + ", ".join(c["name"] for c in certs[:5]) + ".")
        items.append(f"A named {self.est['headcount']}-person team matched from our own people on role, skills and availability.")
        w.bullets(items)

    def phases(self, w):
        w.table(["Phase", "Duration", "Activities"], [[ph["name"], _dur(ph["weeks"]) + (" (in parallel)" if ph.get("parallel") else ""), ph["detail"]]
                                                     for ph in self.est["phases"]], widths=[4.5, 3.5, 8.7])
        if self.est.get("accelerators"):
            w.p("Accelerators that reduce effort and risk: " + "; ".join(f"{a['name']} (~{a['saving_pct']:.0f}% saving)" for a in self.est["accelerators"]) + ".")

    def governance(self, w):
        w.bullets(["Monthly steering committee with the client sponsor; weekly service and delivery reviews.",
                   "A single accountable engagement manager; escalation matrix agreed during mobilisation.",
                   "Change, release and configuration management aligned with the client's change board and quality standards."])

    def operating_model(self, w):
        w.p(f"A single team of {self.est['headcount']} people ({self.est['fte']} FTE at peak), led by an accountable engagement manager:")
        self.team(w)
        self.governance(w)

    def team(self, w):
        phased = len({t.get("phase") for t in self.est["team"]}) > 1
        def people(t):
            # Client-facing: real names only when the company shows them; never internal codes or hiring status.
            n, open_ = len(t["assigned"]), t["unfilled"]
            if self.d.get("show_names"):
                named = ", ".join(p["name"] for p in t["assigned"] if p.get("name"))
            else:
                named = f"{n} named consultant{'s' if n != 1 else ''}" if n else ""
            more = f"{open_} to be named at mobilisation" if open_ else ""
            return "; ".join(x for x in (named, more) if x) or "To be named at mobilisation"
        if phased:
            w.table(["Phase", "Role", "FTE", "Location", "Responsibility", "Proposed people"], widths=[1.6, 3.0, 1.0, 1.7, 5.4, 4.0], rows=[
                [t.get("phase", ""), t["role"], t["fte"], t["location"], t["responsibility"], people(t)] for t in self.est["team"]])
        else:
            w.table(["Role", "FTE", "Location", "Responsibility", "Proposed people"], widths=[3.4, 1.1, 1.8, 6.0, 4.4], rows=[
                [t["role"], t["fte"], t["location"], t["responsibility"], people(t)] for t in self.est["team"]])

    def security(self, w):
        sec = [r for r in self.reqs if r["category"] == "Compliance" or re.search(r"secur|privacy|encrypt|identity|audit", r.get("subcategory", "") + " " + r["text"], re.I)]
        certs = [c for c in self.ctx.get("certifications", []) if re.search(r"iso|soc|pci|nist|csa|hipaa|27001", c["name"], re.I)]
        if certs:
            w.p("Certifications relevant to security and compliance: " + ", ".join(c["name"] for c in certs) + ".")
        if sec:
            w.table(["Ref", "Requirement", "Our response"], [[client_ref(r), _clip(r["text"], 220), _clip(r.get("response") or response_text(r, self.cname), 420)]
                                                              for r in sec[:20]], widths=[1.8, 6.4, 8.5], font=8)
        elif not certs:
            w.p("Security controls are covered requirement by requirement in the compliance matrix.")

    def quality(self, w):
        certs = [c for c in self.ctx.get("certifications", []) if re.search(r"iso|cmmi|9001|itil", c["name"], re.I)]
        qa = [t for t in self.est["team"] if re.search(r"qa|quality|test", t["role"], re.I)]
        items = []
        if certs:
            items.append("Quality certifications: " + ", ".join(c["name"] for c in certs) + ".")
        if qa:
            items.append("Dedicated quality roles in the team: " + ", ".join(f"{t['role']} ({t['fte']} FTE)" for t in qa) + ".")
        items.append("Every deliverable is reviewed and signed off against the acceptance criteria agreed at mobilisation.")
        w.bullets(items)

    def commercial(self, w):
        pr, est = self.pr, self.est
        ps = pr.get("phase_split")
        if ps:
            build = self.price * ps["build_pct"] / 100
            run = self.price - build
            w.p(f"Our offer for the full scope is {money(self.price, self.ccy)}" + (f" ({money(self.sc['price'], pr['currency'])})" if self.ccy != pr["currency"] else "")
                + ", priced as you asked:")
            w.bullets([f"Platform build and migration: {money(build, self.ccy)} fixed price, paid against the milestones below"
                       + (f" over {ps['build_months']} months." if ps.get("build_months") else "."),
                       f"Managed service: a fixed monthly fee of {money(run / ps['run_months'], self.ccy)} for {ps['run_months']} months "
                       f"({money(run, self.ccy)} in total)."])
        else:
            w.p(f"Our offer for the full scope is {money(self.price, self.ccy)}" + (f" ({money(self.sc['price'], pr['currency'])})" if self.ccy != pr["currency"] else "")
                + f" for {est['contract_months']} months, inclusive of the team, governance and transition.")
        w.table(["Milestone", "Share", "Amount"], [[m["name"], f"{m['pct']}%", money(self.price * m["pct"] / 100, self.ccy)] for m in pr["milestones"]],
                widths=[9.7, 2.5, 4.5])
        if pr.get("partner_note"):
            w.p(pr["partner_note"], italic=True)

    def slas(self, w):
        slas = self.ctx["meta"].get("slas", [])
        if slas:
            rows = []
            for s in slas:
                m = re.match(r"(.+?):\s*(.+)", s)
                rows.append([m.group(1), m.group(2)] if m else [s, ""])
            w.table(["Service level required", "Target"], rows, widths=[10.2, 6.5])
            w.p(f"{self.cname} commits to these service levels, reported monthly.")
        else:
            w.p("Service levels will be agreed during mobilisation and reported monthly.")

    def improvement(self, w):
        enh = [t for t in self.est["phases"] if re.search(r"improv|enhanc|lifecycle|optimi", t["name"] + t.get("detail", ""), re.I)]
        if enh:
            w.bullets([f"{ph['name']}: {ph['detail']}" for ph in enh])
        else:
            w.p("We run a continual improvement register from the first month, reviewed with you at every steering committee.")

    def certifications(self, w):
        certs = self.ctx.get("certifications", [])
        if certs:
            w.table(["Certification", "Type", "Issuer", "Valid until"], [[c["name"], c.get("kind", "").title(), c.get("issuer", ""), c.get("valid_until", "")] for c in certs],
                    widths=[6.5, 2.7, 4.5, 3.0])

    def case_studies(self, w):
        for c in self.ctx.get("case_studies", [])[:4]:
            w.h(c["title"], 3)
            meta_line = ", ".join(x for x in [c.get("client"), c.get("industry"), c.get("region"), c.get("year")] if x)
            if meta_line:
                w.p(meta_line, italic=True)
            if c.get("summary"):
                w.p(c["summary"])
            outs = [o.strip(" .;,") for o in c.get("outcomes") or [] if o and o.strip(" .;,")]
            if outs:
                w.bullets([o[:1].upper() + o[1:] for o in outs[:4]])

    def compliance(self, w):
        rows = [[client_ref(r), _clip(r["text"], 300), f"p.{r['page']}", compliance_label(r),
                 _clip(r.get("response") or response_text(r, self.cname), 700)] for r in self.reqs if r["category"] != "Commercial"]
        self.compliance_rows = len(rows)
        w.table(["Ref", "Requirement", "Source", "Compliance", "Our response"], rows, widths=[1.6, 6.0, 1.1, 2.2, 5.8], font=7.5)

    def assumptions(self, w):
        w.bullets(self.est.get("assumptions", []) + self.pr.get("assumptions", []))
        oos = self.ctx["meta"].get("out_of_scope", [])
        if oos:
            w.p("Out of scope (as defined in the RFP):")
            w.bullets(oos)

    def risks(self, w):
        risks = [r for r in self.reqs if r.get("gap", {}).get("risk") in ("High", "Medium") and r["gap"].get("options")
                 and r["gap"]["options"][0]["type"] != "Strengthen evidence"][:15]  # thin evidence is our homework, not a client risk
        rows = [[_ref(r), _clip(r["text"], 200), r["gap"]["risk"], _clip(client_mitigation(r, self.cname), 260)] for r in risks]
        rows += [["Delivery", risk, level, mit] for risk, level, mit in delivery_risks(self.d["engagement_type"], self.ctx["meta"], self.est)]
        w.table(["Ref", "Risk", "Level", "Mitigation"], rows, widths=[1.8, 7.0, 1.6, 6.3])

    def commercial_conditions(self, w):
        commercial = [r for r in self.reqs if r["category"] == "Commercial"]
        if commercial:
            w.table(["Ref", "Condition", "Source", "Position"], [[client_ref(r), _clip(r["text"], 300), f"p.{r['page']}",
                                                                 condition_position(r, self.pr)] for r in commercial],
                    widths=[1.8, 10.0, 1.4, 3.5], font=7.5)

    def appendix(self, w):
        self.commercial_conditions(w)


PROCESS_SENTENCE_RE = re.compile(r"\b(bidders?|tenderers?|proposers?|respondents?)\s+(shall|must|should)\s+(address|submit|include|describe|"
                                 r"provide (?:details|a description)|respond|state|list)\b|\bin their (response|proposal)\b", re.I)


def client_mitigation(r: dict, company: str) -> str:
    """How a gap is closed, worded for the client (the internal plan stays in the app and the handoff)."""
    o = r["gap"]["options"][0]
    if o.get("ai"):
        return o["detail"]
    missing = ", ".join((r.get("match") or {}).get("technologies_missing", [])[:2]) or "this area"
    return {
        "Partner": f"Delivered with a specialist {missing} partner under {company}'s prime contract.",
        "Upskill": f"Engineers from our existing practice complete {missing} training before mobilisation.",
        "Hire": f"Specialists in {missing} join the team before mobilisation.",
        "Certify": f"Independent assurance for {missing} is planned; interim controls are shared during mobilisation.",
        "Define method": "Our standard delivery method is applied and confirmed with you during mobilisation.",
        "Build": "A dedicated solution component is designed during the design phase and validated with our architects.",
    }.get(o["type"], o["detail"])


def _req_breakdown(total: int, counts: dict) -> str:
    parts = [f"{counts.get('strong', 0)} fully met"]
    if counts.get("partial"):
        parts.append(f"{counts['partial']} with an approach")
    if counts.get("gap"):
        parts.append(f"{counts['gap']} with a mitigation plan")
    if counts.get("confirm"):
        parts.append(f"{counts['confirm']} conditions and submission rules acknowledged")
    return f"{total}: " + ", ".join(parts)


def condition_position(r: dict, pr: dict) -> str:
    """Our position on a commercial condition. Only what our offer actually does is stated as complied."""
    t = r.get("text", "").lower()
    sub = r.get("subcategory", "")
    if sub == "Evaluation & Award":
        return "Addressed in this proposal"
    if sub == "Submission":
        return "Complied"
    if re.search(r"price|pric", t) and re.search(r"milestone|monthly", t):
        ps = pr.get("phase_split")
        want_ms, want_monthly = "milestone" in t, "monthly" in t
        has_ms = any("Build:" in m["name"] or not m.get("monthly") for m in pr.get("milestones", []))
        has_monthly = any(m.get("monthly") for m in pr.get("milestones", []))
        if (not want_ms or has_ms) and (not want_monthly or has_monthly) and (ps or not (want_ms and want_monthly)):
            return "Complied: see the commercial summary"
        return "To confirm: our pricing structure differs"
    if re.search(r"currency|dollars|quoted in|exclusive of|inclusive of", t):
        return "Complied"
    return "Accepted, subject to contract"


def delivery_risks(eng: str, meta: dict, est: dict) -> list[tuple[str, str, str]]:
    """Standard risks for the kind of engagement, so the register is never just the requirement gaps."""
    out = []
    if eng in ("build_run", "implementation"):
        out.append(("Migration cut-over disrupts live services.", "Medium",
                    "Wave-based migration with parallel running, rehearsed rollback and agreed cut-over windows."))
        if est.get("build_months"):
            out.append((f"The {est['build_months']}-month timeline slips because of client dependencies (environments, test data, SMEs).", "Medium",
                        "Dependencies and dates agreed at mobilisation, tracked weekly and escalated through the steering committee."))
    if eng in ("build_run", "managed_services"):
        out.append(("Service levels missed in the first months of the run phase.", "Medium",
                    "Hypercare before service start, runbooks validated in rehearsal, and early-life support from the build team."))
    if est.get("unfilled_roles"):
        out.append((f"{est['unfilled_roles']} role(s) still to be filled before mobilisation.", "Medium",
                    "Recruitment starts at contract award, with named backups from the bench."))
    return out


def _ref(r: dict) -> str:
    """The RFP's own id when it has one (INT-03); a bare section number (3.3.1) is not an id, so use our code."""
    ref = (r.get("source_ref") or "").strip()
    return ref if ref and not re.fullmatch(r"[\d.]+", ref) else r["code"]


# Placeholder wording -> content block. First match wins; the nearest heading is used when the placeholder itself is vague.
TOPICS = [
    (r"compliance matrix|compliance table|requirement.{0,20}matrix", "compliance"),
    (r"risk", "risks"),
    (r"executive summary|value proposition|value summary", "value"),
    (r"differentiator|why us|why choose", "differentiators"),
    (r"business context|client context|context|background|understanding|business driver", "understanding"),
    (r"solution overview|proposed solution|solution summary", "solution"),
    (r"technology stack|tech stack|technology detail|architecture", "tech_stack"),
    (r"operating model|delivery model|service delivery", "operating_model"),
    (r"security|zero.?trust|compliance framework", "security"),
    (r"transition|knowledge transfer|methodology|approach|plan", "phases"),
    (r"quality", "quality"),
    (r"governance|account management", "governance"),
    (r"commercial|pricing|price|cost|payment", "commercial"),
    (r"\bsla|service level|kpi", "slas"),
    (r"\bcsi\b|innovation|improvement", "improvement"),
    (r"certification|accreditation|maturity", "certifications"),
    (r"case stud|experience|reference|credential", "case_studies"),
    (r"team|resource|staff|organi[sz]ation", "team"),
    (r"assumption|dependenc|exclusion", "assumptions"),
    (r"appendi|attachment", "appendix"),
]
ESSENTIAL = [("Executive summary", "value"), ("Requirement compliance matrix", "compliance"), ("Commercial summary", "commercial"),
             ("Team and organisation", "team"), ("Assumptions, dependencies and exclusions", "assumptions"), ("Risks and mitigations", "risks")]
COVERS = {"team": {"team", "operating_model"}}


def _topic(text: str) -> str | None:
    t = text.lower()
    for pat, key in TOPICS:
        if re.search(pat, t):
            return key
    return None


def _fill_sections(doc, c: Content) -> list[str]:
    """Fill each placeholder in the company's template with the matching block. Returns the blocks placed."""
    # Sample tables in a placeholder template carry example claims (figures, maturity levels) that are not this
    # company's facts, so they never reach a client. Tables holding {{FIELDS}} are kept: they were meant to be filled.
    for t in list(doc.tables):
        if "{{" not in "".join(cell.text for row in t.rows for cell in row.cells):
            _remove(t._tbl)
    placed: list[str] = []
    last_heading = ""
    for p in list(doc.paragraphs):
        if p.style.name.startswith(("Heading", "Title")):
            last_heading = p.text
            continue
        if not PLACEHOLDER_RE.match(p.text or ""):
            continue
        key = _topic(p.text) or _topic(last_heading)
        if key == "governance" and "operating_model" in placed:
            key = None  # already written with the operating model
        if key == "team" and "operating_model" in placed:
            key = None
        if key and key not in placed:
            w = Writer(doc, anchor=p._p)
            getattr(c, key)(w)
            placed.append(key)
        _remove(p._p)
    return placed


# --------------------------------------------------------------------------- proposal
def build_proposal(ctx: dict, template_bytes: bytes | None) -> tuple[bytes, dict]:
    d, company = ctx["deal"], ctx["company"]
    doc = _open_template(template_bytes)
    today = date.today().strftime("%d %B %Y")
    mode = template_mode(doc)
    _replace_everywhere(doc, {"TITLE": d["name"], "CLIENT": d["client_display"], "DATE": today, "COMPANY": company["name"]})
    c = Content(ctx)
    subtitle = f"Proposal for {d['client_display']}, submitted by {company['name']}, {today}"

    if mode == "sections":
        _retitle(doc, d["name"], subtitle)
        placed = _fill_sections(doc, c)
        missing = [(t, k) for t, k in ESSENTIAL if not (COVERS.get(k, {k}) & set(placed))]
        if "appendix" not in placed and any(r["category"] == "Commercial" for r in c.reqs):
            missing.append(("Commercial and contractual conditions", "commercial_conditions"))
        if missing:
            # sections the template has no slot for become lettered appendices, so they never clash with its own numbering
            w = Writer(doc)
            w.page_break()
            for i, (title, key) in enumerate(missing):
                w.h(f"Appendix {chr(65 + i)}. {title}", 1)
                getattr(c, key)(w)
        sections = len(placed) + len(missing)
    else:
        if mode == "styles":
            _clear_body(doc)
            w = Writer(doc)
            w.title(d["name"])
            w.p(subtitle, italic=True)
        else:
            marker = next(p for p in doc.paragraphs if "{{CONTENT}}" in p.text)
            w = Writer(doc, anchor=marker._p)
        sec = Numbered(w)
        sec("Executive summary"); c.value(w)
        sec("Our understanding of your requirements"); c.understanding(w)
        sec("Proposed solution"); c.solution(w)
        if c.arch.get("choices"):
            w.h("Technology decisions", 2); c.tech_stack(w)
        sec("Delivery approach and plan"); c.phases(w)
        w.h("Governance", 2); c.governance(w)
        sec("Team and organisation"); c.team(w)
        if ctx.get("case_studies"):
            sec("Relevant experience"); c.case_studies(w)
        if ctx.get("certifications"):
            sec("Certifications and partnerships"); c.certifications(w)
        sec("Commercial summary"); c.commercial(w)
        if ctx["meta"].get("slas"):
            sec("Service levels"); c.slas(w)
        sec("Requirement compliance matrix"); c.compliance(w)
        sec("Assumptions, dependencies and exclusions"); c.assumptions(w)
        sec("Risks and mitigations"); c.risks(w)
        if any(r["category"] == "Commercial" for r in c.reqs):
            w.h("Appendix A. Commercial and contractual conditions", 1); c.commercial_conditions(w)
        if mode == "marker":
            _remove(marker._p)
        sections = sec.n
    if ctx.get("unmask"):
        unmask_document(doc, *ctx["unmask"])
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), {"executive_summary": c.summary, "sections": sections, "compliance_rows": c.compliance_rows, "scenario": c.sc["name"],
                            "price": round(c.price, 2), "currency": c.ccy, "template_mode": mode}


def unmask_document(doc, alias: str, real: str) -> None:
    """Put the client's real name back into a finished document (AI prompts and the app only ever saw the alias)."""
    if not alias or alias == real:
        return
    rx = re.compile(re.escape(alias))

    def fix(paragraphs):
        for p in paragraphs:
            if alias not in p.text:
                continue
            for run in p.runs:
                if alias in run.text:
                    run.text = rx.sub(real, run.text)
            if alias in p.text and p.runs:  # the alias was split across runs
                full = rx.sub(real, p.text)
                p.runs[0].text = full
                for run in p.runs[1:]:
                    run.text = ""

    def walk(container):
        fix(container.paragraphs)
        for t in container.tables:
            for row in t.rows:
                for cell in row.cells:
                    walk(cell)

    walk(doc)
    for sec in doc.sections:
        for part in (sec.header, sec.footer, sec.first_page_header, sec.first_page_footer):
            try:
                walk(part)
            except Exception:
                continue


def _a(phrase: str) -> str:
    return ("an " if phrase[:1].lower() in "aeiou" else "a ") + phrase


def _dur(weeks: float) -> str:
    return f"{round(weeks)} weeks" if weeks < 26 else f"{round(weeks / 4.33)} months"


# --------------------------------------------------------------------------- handoff
def _team_rows(team: list[dict]) -> list[dict]:
    """One row per role and location: FTE added up, people listed once, open seats counted."""
    out: dict[tuple, dict] = {}
    for t in team:
        k = (t["role"], t["location"])
        r = out.setdefault(k, {"role": t["role"], "location": t["location"], "fte": 0.0, "people": [], "unfilled": 0,
                               "responsibility": t.get("responsibility", "")})
        r["fte"] = round(r["fte"] + float(t["fte"]), 2)
        r["people"] += [p for p in t.get("people", [p["code"] for p in t.get("assigned", [])]) if p not in r["people"]]
        r["unfilled"] += int(t.get("unfilled") or 0)
    return list(out.values())


def _split_deliverable(text: str) -> tuple[str, str]:
    parts = [x.strip() for x in re.split(r"\s+[—–]\s+", text) if x.strip()]
    if len(parts) >= 2:
        return _clip(" – ".join(parts[:-1]), 160), _clip(parts[-1], 300)
    m = re.match(r"(.+?)\s*[:–-]\s*(.+)", text)
    return (m.group(1).strip(), m.group(2).strip()) if m and len(m.group(1)) < 120 else (_clip(text, 300), "")


def build_handoff_data(ctx: dict) -> dict:
    reqs, est, pr, g = ctx["requirements"], ctx["estimation"], ctx["pricing"], ctx["gaps"]
    sc = next((s for s in pr["scenarios"] if s["name"] == ctx.get("scenario", "Target")), pr["scenarios"][1])
    ccy = pr["rfp_currency"]
    scope = [{"workstream": w["name"], "requirements": w["requirements"], "codes": w["codes"][:20], "effort_days": w["effort_days"]} for w in est["workstreams"]]
    order = {"High": 0, "Medium": 1}
    risky = sorted([r for r in reqs if r.get("gap", {}).get("risk") in ("High", "Medium")], key=lambda r: order[r["gap"]["risk"]])
    risks = [{"code": r["code"], "ref": _ref(r), "risk": _clip(r["text"], 220), "level": r["gap"]["risk"],
              "mitigation": _clip((r["gap"]["options"][0]["type"] + ": " + r["gap"]["options"][0]["detail"]) if r["gap"].get("options") else "", 240),
              "owner": "Delivery lead"} for r in risky][:25]
    team = _team_rows([{"role": t["role"], "fte": t["fte"], "location": t["location"], "people": [p["code"] for p in t["assigned"]],
                        "unfilled": t["unfilled"], "responsibility": t.get("responsibility", "")} for t in est["team"]])
    open_items = [f"Hire or contract {t['unfilled']} × {t['role']} ({t['location'].lower()}) before mobilisation." for t in team if t["unfilled"]]
    busy = sorted({(p["code"], t["role"]) for t in est["team"] for p in t["assigned"] if p["status"] != "Available"})
    open_items += [f"Release {code} from their current assignment to take the {role} role." for code, role in busy]
    for t in g.get("top_missing", [])[:6]:
        open_items.append(f"{t['recommendation']}: {t['technology']} (affects {_plural(t['requirements'], 'requirement')}).")
    confirm = [r for r in reqs if r.get("match_status") == "confirm" and r["category"] == "Commercial"
               and r.get("subcategory") not in ("Evaluation & Award", "Submission")][:12]
    unfilled = sum(t["unfilled"] for t in team)
    return {
        "summary": f"{ctx['deal']['name']} for {ctx['deal']['client_display']}: {ENG_LABEL.get(ctx['deal']['engagement_type'], 'engagement')}, "
                   f"{est['contract_months']} months, {est['headcount']} people, contract value {money(sc['price'] * pr['fx_to_rfp'], ccy)}.",
        "facts": [["Client", ctx["deal"]["client_display"]], ["Engagement", ENG_LABEL.get(ctx["deal"]["engagement_type"], "").capitalize()],
                  ["Term", (f"{est['build_months']}-month build, then {est['run_months']} months of managed service"
                            if ctx["deal"]["engagement_type"] == "build_run" and est.get("build_months") else f"{est['contract_months']} months")],
                  ["Team", f"{est['headcount']} people, {est['fte']} FTE at peak" + (f", {unfilled} still to hire" if unfilled else "")],
                  ["Contract value", money(sc["price"] * pr["fx_to_rfp"], ccy) + f" ({sc['name'].lower()} price, {sc['margin_pct']}% margin)"],
                  ["Requirements", f"{len(reqs)}: {g['counts'].get('strong', 0)} strong, {g['counts'].get('partial', 0)} partial, {g['counts'].get('gap', 0)} gaps, "
                                   f"{g['counts'].get('confirm', 0)} conditions to honour"]],
        "scope": scope,
        "out_of_scope": ctx["meta"].get("out_of_scope", []),
        "deliverables": [_split_deliverable(x) for x in ctx["meta"].get("deliverables", [])],
        "slas": ctx["meta"].get("slas", []),
        "assumptions": est.get("assumptions", []) + pr.get("assumptions", []),
        "risks": risks,
        "team": team,
        "plan": est["phases"],
        "currency": ccy,
        "milestones": [{**m, "amount": round(sc["price"] * pr["fx_to_rfp"] * m["pct"] / 100, 2)} for m in pr["milestones"]],
        "commercial_conditions": [{"code": r["code"], "text": _clip(r["text"], 240)} for r in confirm],
        "open_items": open_items[:20],
        "first_30_days": ["Kick-off with the client sponsor; confirm governance, escalation matrix and reporting cadence.",
                          "Provision access to environments and source and target systems.",
                          "Baseline scope against this handoff pack; log any differences as change requests.",
                          "Confirm the named team, release dates and onboarding for any new hires."],
    }


def build_handoff_docx(ctx: dict, data: dict, template_bytes: bytes | None) -> bytes:
    """Internal document for the delivery team: the template's look, none of its proposal content."""
    doc = _open_template(template_bytes)
    _clear_body(doc)
    d = ctx["deal"]
    today = date.today().strftime("%d %B %Y")
    _replace_everywhere(doc, {"TITLE": f"Delivery handoff – {d['name']}", "CLIENT": d["client_display"], "DATE": today, "COMPANY": ctx["company"]["name"]})
    w = Writer(doc)
    w.title(f"Delivery handoff: {d['name']}")
    w.p(f"Internal to {ctx['company']['name']}. Prepared {today} from the approved deal package.", italic=True)
    w.p(data["summary"])
    w.table(["", ""], data.get("facts", []), widths=[4.0, 12.7])
    sec = Numbered(w)
    ccy = data.get("currency", "")

    sec("Scope by workstream")
    w.table(["Workstream", "Requirements", "Effort (days)", "Requirement refs"],
            [[s["workstream"], s["requirements"], f"{s['effort_days']:,.0f}", ", ".join(s["codes"][:12]) + (" …" if len(s["codes"]) > 12 else "")] for s in data["scope"]],
            widths=[4.6, 2.4, 2.4, 7.3])
    if data["out_of_scope"]:
        sec("Out of scope"); w.bullets(data["out_of_scope"])
    if data["deliverables"]:
        sec("Contractual deliverables")
        w.table(["Deliverable", "Detail / due"], [list(x) for x in data["deliverables"]], widths=[6.2, 10.5])
    if data["slas"]:
        sec("Service levels committed")
        rows = []
        for s_ in data["slas"]:
            m = re.match(r"(.+?):\s*(.+)", s_)
            rows.append([m.group(1), m.group(2)] if m else [s_, ""])
        w.table(["Service level", "Target"], rows, widths=[10.2, 6.5])
    sec("Team")
    w.table(["Role", "Location", "FTE", "Named people", "To hire"],
            [[t["role"], t["location"], f"{t['fte']:g}", ", ".join(t["people"]) or "–", t["unfilled"] or "–"] for t in data["team"]],
            widths=[4.6, 2.4, 1.5, 6.2, 2.0])
    sec("Plan")
    w.table(["Phase", "Duration", "Activities"], [[p["name"], _dur(p["weeks"]) + (" (in parallel)" if p.get("parallel") else ""), p["detail"]] for p in data["plan"]],
            widths=[4.6, 3.0, 9.1])
    sec("Commercial milestones")
    w.table(["Milestone", "Share", "Amount"], [[m["name"], f"{m['pct']:g}%", money(m["amount"], ccy)] for m in data["milestones"]], widths=[9.7, 2.5, 4.5])
    if data.get("commercial_conditions"):
        sec("Commercial conditions to honour")
        w.table(["Ref", "Condition"], [[x["code"], x["text"]] for x in data["commercial_conditions"]], widths=[2.2, 14.5])
    sec("Assumptions"); w.bullets(data["assumptions"])
    if data["risks"]:
        sec("Risks")
        w.table(["Ref", "Risk", "Level", "Mitigation", "Owner"], [[r["ref"], r["risk"], r["level"], r["mitigation"], r["owner"]] for r in data["risks"]],
                widths=[1.8, 6.0, 1.5, 5.5, 1.9], font=8)
    if data["open_items"]:
        sec("Open items before mobilisation"); w.bullets(data["open_items"])
    sec("First 30 days"); w.bullets(data["first_30_days"])
    if ctx.get("unmask"):
        unmask_document(doc, *ctx["unmask"])
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
