"""Questions to send the client: requirements that are vague, open-ended, conflicting or missing a number.

The AI drafts them when it's available; otherwise simple rules pick vague wording and unconfirmed items. The result is
saved on the deal so the team can edit it before sending."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import Deal, Requirement
from . import llm
from .masking import deal_masker

log = logging.getLogger("revenueforge.clarify")

VAGUE = re.compile(r"\b(as (?:required|needed|appropriate|applicable)|where (?:appropriate|applicable|possible)|etc\.?|tbd|tbc|to be (?:confirmed|"
                   r"determined|agreed)|industry[- ]standard|best[- ]practice|suitable|adequate|appropriate|reasonable|sufficient|timely|"
                   r"user[- ]friendly|high(?:ly)? available|scalable|robust|seamless|real[- ]time|minimal|as soon as possible|asap|and/or|"
                   r"including but not limited to|state[- ]of[- ]the[- ]art|latest|modern)\b", re.I)

SYSTEM = """You help a pre-sales team prepare clarification questions for a client before they answer an RFP.
From the requirements given, pick the ones that are vague, open-ended, contradictory with each other, or missing a
number the team needs to size or price the work (volumes, users, response times, environments, dates, locations).
Write one short, polite, specific question per item, as the team would send it to the client. Do not ask about
anything the requirement already states clearly. Respond with JSON:
{"questions": [{"code": "REQ-012", "question": "...", "why": "short reason (vague / missing volume / conflicts with REQ-030 ...)"}]}
Return at most 15 questions, most important first."""


INSTRUCTION = re.compile(r"^\s*(?:the\s+)?(?:bidders?|respondents?|tenderers?|suppliers?)\s+(?:shall|must|should|are to)\s+(?:submit|address|provide (?:a|their) "
                         r"response|respond|include in (?:their|the) response|complete)", re.I)


def _rules(reqs: list[Requirement], mask) -> list[dict]:
    """Without AI: vague wording first, then a few items the matcher couldn't confirm. Submission instructions are skipped."""
    vague, confirm = [], []
    for r in reqs:
        text = r.text or ""
        if INSTRUCTION.search(text) or (r.category or "").lower().startswith("instruction"):
            continue
        m = None if re.search(r"\d", text) else VAGUE.search(text)  # a stated number is already measurable
        if m:
            vague.append({"code": r.code, "question": f"{r.code} (p. {r.page}) says \"{mask(text)[:180]}\". What does \"{m.group(0)}\" mean in "
                                                      "practice here? A measurable target (volume, time, level) would help us size and price it accurately.",
                          "why": f"Vague wording: \"{m.group(0)}\""})
        elif r.match_status == "confirm" and r.priority == "Mandatory":
            confirm.append({"code": r.code, "question": f"Could you share more detail on {r.code} (p. {r.page}): \"{mask(text)[:180]}\"? "
                                                         "For example the expected scope, volumes or any constraints we should plan for.",
                            "why": "Not enough detail to commit"})
    return (vague[:12] + confirm[:5])[:15]


def generate(db, deal: Deal) -> dict:
    mask = deal_masker(deal)
    reqs = db.scalars(select(Requirement).where(Requirement.deal_id == deal.id).order_by(Requirement.seq)).all()
    codes = {r.code for r in reqs}
    items, by = [], "rules"
    if llm.is_enabled() and reqs:
        lines = "\n".join(f"{r.code} [{r.category}, {r.priority}, p.{r.page}]: {mask(r.text)[:300]}" for r in reqs[:150])
        try:
            res = llm.complete_json(SYSTEM, f"Requirements:\n{lines}", max_tokens=4000)
            for q in (res.get("questions") if isinstance(res, dict) else res) or []:
                if isinstance(q, dict) and q.get("question"):
                    items.append({"code": q.get("code") if q.get("code") in codes else "", "question": mask(str(q["question"]))[:600],
                                  "why": mask(str(q.get("why") or ""))[:160]})
            by = "ai" if items else by
        except Exception as e:  # busy or failed AI: fall back to rules
            log.warning("Clarification questions by AI failed: %s", e)
    if not items:
        items = _rules(reqs, mask)
    result = {"items": items[:20], "by": by, "generated_at": datetime.now(timezone.utc).isoformat()}
    meta = dict(deal.meta or {})
    meta["clarifications"] = result
    deal.meta = meta
    db.commit()
    return result
