"""Commercial model for the generalised pipeline: the costs beyond the team's labour.

Lines come from the RFP Profile and the deal's own stages, never from a domain list:
  partner   every requirement the plan gives to a partner (gap recommendation, or a failed reference/accreditation gate
            closed through a consortium). Estimated from the labour the partner replaces, at the company's own blended day
            cost plus a partner margin, as a range. Marked "estimate, replace with the partner's quote".
  licence   every product, licence, hardware or subscription the RFP says the bidder supplies. Nothing in the library says
            what these cost, so the amount stays empty and the line needs a quote.
  commitment contractual costs the RFP names: service credits (a risk reserve on the run price), performance or bank
            guarantees (the guarantee fee for the term), insurance (needs a quote).
  hiring    open roles: recruitment and ramp-up for each person still to hire.
Every line that rests on an estimate or has no amount is listed as "needs a quote"; pricing can't be approved until each
one is confirmed or replaced with a real figure (an override), unless the approver says why.
"""
from __future__ import annotations

import hashlib
import re

PARTNER_MARGIN = 0.25        # a partner's price over the labour it replaces
RANGE = 0.3                  # +/- around a partner estimate
RECRUIT_DAYS = 21            # recruitment + ramp-up per open hire, in day-cost of the role
GUARANTEE_FEE_PA = 0.015     # bank guarantee commission, per year
SLA_RESERVE = 0.03           # share of run labour held against service credits


def _id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:10]


def build_lines(est: dict, labour_lines: list[dict], reqs: list[dict], profile: dict, rfp_text: str, gaps: dict | None = None) -> list[dict]:
    lines: list[dict] = []
    days = sum(l["person_days"] for l in labour_lines) or 1
    blended = sum(l["cost"] for l in labour_lines) / days
    run_months = est.get("run_months") or 0
    contract_months = est.get("duration_months") or run_months or 12

    # partner lines: sized from the team the partner replaces (the plan's partner rows), else from the requirement's effort
    conditions = {"Standards & Certifications", "Team & Experience", "Regulatory", "Information Security Policy", "Data Protection & Privacy"}
    consortium = bool((gaps or {}).get("consortium_allowed"))
    gate_partner = {g.get("ref") for g in (gaps or {}).get("gates", [])
                    if consortium and g.get("status") in ("fail", "curable") and g.get("kind") in ("experience", "accreditation", "partner_status")}
    by_ref = {(r.get("source_ref") or r.get("code", "")): r for r in reqs}
    covered: set[str] = set()
    for pw in est.get("partner_work", []):
        refs = [x for x in pw.get("serves", []) if x]
        if not refs or set(refs) <= covered:
            continue
        covered |= set(refs)
        d = pw["fte"] * pw["months"] * 21
        mid = d * blended * (1 + PARTNER_MARGIN)
        first = by_ref.get(refs[0], {})
        lines.append({"id": _id("partner", *refs), "kind": "partner", "label": f"Partner for {', '.join(refs[:4])}: {first.get('text', pw.get('responsibility', ''))[:80]}",
                      "ref": ", ".join(refs[:6]), "amount": round(mid, 2), "low": round(mid * (1 - RANGE), 2), "high": round(mid * (1 + RANGE), 2),
                      "basis": f"{pw['fte']:g} FTE for {pw['months']:g} months ({pw['role']}) at the team's blended cost + {int(PARTNER_MARGIN * 100)}% partner margin",
                      "needs_quote": True, "confirmed": False})
    for r in reqs:
        ref = r.get("source_ref") or r.get("code", "")
        if ref in covered or r.get("match_status") == "strong":
            continue
        partner = (r.get("gap") or {}).get("recommended") == "Partner" and r.get("subcategory") not in conditions
        if not (partner or ref in gate_partner):
            continue
        d = max(10.0, float(r.get("effort_days") or 0))
        mid = d * blended * (1 + PARTNER_MARGIN)
        what = "consortium partner who meets this condition" if ref in gate_partner and not partner else "the work it covers"
        lines.append({"id": _id("partner", ref), "kind": "partner", "label": f"Partner for {ref}: {r.get('text', '')[:90]}", "ref": ref,
                      "amount": round(mid, 2), "low": round(mid * (1 - RANGE), 2), "high": round(mid * (1 + RANGE), 2),
                      "basis": f"{d:g} person-days ({what}) at the team's blended cost + {int(PARTNER_MARGIN * 100)}% partner margin",
                      "needs_quote": True, "confirmed": False})

    # licences, hardware and subscriptions the bidder supplies
    for b in (profile.get("commercial") or {}).get("bidder_supplied", []):
        lines.append({"id": _id("licence", b.get("ref"), b.get("text", "")[:60]), "kind": "licence", "label": f"{b.get('ref')}: {b.get('text', '')[:110]}",
                      "ref": b.get("ref", ""), "amount": 0.0, "low": None, "high": None,
                      "basis": "Supplied by the bidder under the RFP; enter the vendor's quote", "needs_quote": True, "confirmed": False})

    # contractual commitments
    t = rfp_text or ""
    run_labour = sum(l["cost"] for l in labour_lines if l.get("phase") == "Run")
    if run_labour and re.search(r"service credits?|penalt(y|ies)|liquidated damages|sla (deductions|credits)", t, re.I):
        lines.append({"id": _id("sla"), "kind": "commitment", "label": "Service-credit reserve", "ref": "", "amount": round(run_labour * SLA_RESERVE, 2),
                      "low": None, "high": None, "basis": f"{int(SLA_RESERVE * 100)}% of run labour held against SLA credits the RFP names",
                      "needs_quote": False, "confirmed": True})
    m = re.search(r"(?:performance|bank)\s+(?:bank\s+)?guarantee[^.]{0,80}?(\d{1,2}(?:\.\d)?)\s?%", t, re.I)
    if m:
        pct = float(m.group(1)) / 100
        labour = sum(l["cost"] for l in labour_lines)
        fee = labour * 1.3 * pct * GUARANTEE_FEE_PA * max(1, contract_months / 12)
        lines.append({"id": _id("guarantee"), "kind": "commitment", "label": f"Performance guarantee ({m.group(1)}% of contract value)", "ref": "",
                      "amount": round(fee, 2), "low": None, "high": None,
                      "basis": f"bank commission of {GUARANTEE_FEE_PA * 100:g}% a year on the guarantee, for {contract_months} months",
                      "needs_quote": False, "confirmed": True})
    if re.search(r"(professional indemnity|cyber|public liability)\s+insurance", t, re.I):
        lines.append({"id": _id("insurance"), "kind": "commitment", "label": "Insurance the RFP requires", "ref": "", "amount": 0.0, "low": None, "high": None,
                      "basis": "Cover named in the RFP; enter the broker's quote", "needs_quote": True, "confirmed": False})

    # hiring for open roles: people hired for the transition carry on into the run, so each job is hired for once, at the
    # largest number open in any one phase
    peak: dict[str, dict] = {}
    for tm in est.get("team", []):
        n = tm.get("unfilled") or 0
        if not n:
            continue
        base = re.sub(r"\s*\(L\d\)$", "", tm["role"])
        by_phase = peak.setdefault(base, {"phases": {}, "loc": tm["location"], "role": tm["role"]})
        by_phase["phases"][tm.get("phase")] = by_phase["phases"].get(tm.get("phase"), 0) + n
    for base, v in peak.items():
        n = max(v["phases"].values())
        dc = next((l["day_cost"] for l in labour_lines if re.sub(r"\s*\(L\d\)$", "", l["role"]) == base), blended)
        lines.append({"id": _id("hire", base), "kind": "hiring", "label": f"Hire {n} × {base}", "ref": "", "amount": round(n * RECRUIT_DAYS * dc, 2),
                      "low": None, "high": None, "basis": f"recruitment and ramp-up, {RECRUIT_DAYS} days of the role's cost per hire; "
                                                          "people hired for one phase carry on into the next", "needs_quote": False, "confirmed": True})
    return lines


def apply_overrides(lines: list[dict], ov: dict) -> list[dict]:
    """ov: {line id: {"amount": x} | {"confirmed": true}} from the pricing stage's overrides."""
    for l in lines:
        o = (ov or {}).get(l["id"])
        if not o:
            continue
        if o.get("amount") is not None:
            try:
                l["amount"] = round(max(0.0, float(o["amount"])), 2)
                l["confirmed"], l["needs_quote"] = True, False
                l["basis"] += " (figure entered by the team)"
            except (TypeError, ValueError):
                pass
        if o.get("confirmed"):
            l["confirmed"], l["needs_quote"] = True, False
    return lines


def open_quotes(pricing: dict) -> list[dict]:
    return [l for l in pricing.get("other_lines", []) if l.get("needs_quote") and not l.get("confirmed")]
