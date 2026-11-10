"""Deadline calendar: every deal's submission date and every relevant open tender's closing date, in one view,
plus the reminders that matter to the person looking (what's due soon that they own or must approve) and a calendar
file (.ics) so the same dates, with alarms, land in Outlook or Google Calendar."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import func, or_, select

from ..config import settings
from ..models import STAGES, Deal, DealStage, StageComment, Tender, TenderFit, User
from ..security import Ctx, current_ctx
from ..services.masking import deal_masker
from ..services.notify import STAGE_NAME, parse_due
from .deals import STAGE_ROLES

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

CLOSED = ("submitted", "won", "lost", "no_bid")
STRONG = 60  # same line as "Strong fit" on the opportunities page
SOON_DAYS = 7


def _day(s: str, default: date) -> date:
    if not s:
        return default
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        raise HTTPException(400, "Dates must look like 2026-11-30.")


def _deals(ctx: Ctx, today: date) -> tuple[list[dict], list[dict]]:
    deals = ctx.db.scalars(select(Deal).where(Deal.tenant_id == ctx.tenant_id)).all()
    if not deals:
        return [], []
    ids = [d.id for d in deals]
    stages: dict[str, dict[str, str]] = {}
    for st in ctx.db.scalars(select(DealStage).where(DealStage.deal_id.in_(ids))):
        stages.setdefault(st.deal_id, {})[st.stage] = st.status
    notes = dict(ctx.db.execute(select(StageComment.deal_id, func.count()).where(StageComment.deal_id.in_(ids), StageComment.status == "open")
                                .group_by(StageComment.deal_id)).all())
    owners = {u.id: u for u in ctx.db.scalars(select(User).where(User.tenant_id == ctx.tenant_id))}
    me = ctx.user
    dated, undated = [], []
    for d in deals:
        st = stages.get(d.id, {})
        waiting = [k for k in STAGES if st.get(k) == "draft"]
        mine = [k for k in waiting if me.role == "admin" or me.role in STAGE_ROLES[k]]
        owner = owners.get(d.owner_id)
        item = {
            "kind": "deal", "id": d.id, "title": deal_masker(d)(d.name),
            "client": d.client_alias if d.confidential else (d.client_name or d.client_alias),
            "status": d.status, "closed": d.status in CLOSED, "due_text": d.due_date,
            "owner": {"id": owner.id, "name": owner.name} if owner else None, "is_mine": d.owner_id == me.id,
            "approved": sum(1 for k in STAGES if st.get(k) == "approved"), "stages": len(STAGES),
            "waiting": [STAGE_NAME[k] for k in waiting], "waiting_for_me": [STAGE_NAME[k] for k in mine],
            "open_notes": notes.get(d.id, 0), "link": f"/app/deals/{d.id}",
        }
        due = parse_due(d.due_date)
        if due:
            item["date"] = due.isoformat()
            item["days_left"] = (due - today).days
            dated.append(item)
        elif d.status not in CLOSED:
            undated.append(item)
    return dated, undated


def _tenders(ctx: Ctx, start: date, end: date, scope: str) -> list[dict]:
    if scope == "none":
        return []
    lo = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    hi = datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)
    want = TenderFit.status == "saved" if scope == "saved" else or_(TenderFit.status == "saved", (TenderFit.status == "new") & (TenderFit.score >= STRONG))
    rows = ctx.db.execute(select(Tender, TenderFit).join(TenderFit, (TenderFit.tender_id == Tender.id) & (TenderFit.tenant_id == ctx.tenant_id))
                          .where(want, Tender.deadline.is_not(None), Tender.deadline >= lo, Tender.deadline < hi)
                          .order_by(Tender.deadline).limit(400)).all()
    today = datetime.now(timezone.utc).date()
    out = []
    for t, f in rows:
        dl = t.deadline if t.deadline.tzinfo else t.deadline.replace(tzinfo=timezone.utc)
        out.append({"kind": "tender", "id": t.id, "title": t.title, "buyer": t.buyer, "country": t.country, "date": dl.date().isoformat(),
                    "days_left": (dl.date() - today).days, "score": f.score, "saved": f.status == "saved", "value": t.value,
                    "currency": t.currency, "url": t.url, "link": f"/app/opportunities?t={t.id}"})
    return out


def _reminders(ctx: Ctx, deals: list[dict], tenders: list[dict]) -> list[dict]:
    """What this person should act on: overdue or due within a week, that they own or must approve; saved tenders closing soon."""
    out = []
    for d in deals:
        if d["closed"] or d["days_left"] > SOON_DAYS:
            continue
        if not (d["is_mine"] or d["waiting_for_me"]):
            continue
        why = []
        if d["waiting_for_me"]:
            why.append("Waiting for your approval: " + ", ".join(d["waiting_for_me"]))
        if d["is_mine"] and d["open_notes"]:
            why.append(f"{d['open_notes']} review note{'s' if d['open_notes'] > 1 else ''} to fix")
        if d["is_mine"] and not why:
            why.append(f"{d['approved']} of {d['stages']} stages approved" if d["approved"] < d["stages"] else "All stages approved, ready to submit")
        out.append({**d, "why": " · ".join(why), "overdue": d["days_left"] < 0})
    if ctx.user.role in ("admin", "presales"):
        out += [{**t, "why": "Saved tender closing", "overdue": False} for t in tenders if t["saved"] and 0 <= t["days_left"] <= SOON_DAYS]
    out.sort(key=lambda x: x["days_left"])
    return out


@router.get("")
def calendar(start: str = "", end: str = "", tenders: str = "saved_strong", ctx: Ctx = Depends(current_ctx)):
    today = datetime.now(timezone.utc).date()
    a = _day(start, today.replace(day=1) - timedelta(days=7))
    b = _day(end, a + timedelta(days=50))
    if b < a or (b - a).days > 400:
        raise HTTPException(400, "Pick a range of up to about a year.")
    if tenders not in ("saved_strong", "saved", "none"):
        raise HTTPException(400, "Tenders must be saved_strong, saved or none.")
    dated, undated = _deals(ctx, today)
    in_range = [d for d in dated if a.isoformat() <= d["date"] <= b.isoformat()]
    tl = _tenders(ctx, a, b, tenders)
    soon_tenders = tl if tenders != "none" else []
    if a > today or b < today + timedelta(days=SOON_DAYS):  # reminders always look at the coming week, whatever month is shown
        soon_tenders = _tenders(ctx, today, today + timedelta(days=SOON_DAYS), "saved")
    return {"today": today.isoformat(), "start": a.isoformat(), "end": b.isoformat(), "events": in_range + tl,
            "undated": undated, "reminders": _reminders(ctx, dated, soon_tenders), "strong_line": STRONG}


@router.get("/reminders")
def reminders(ctx: Ctx = Depends(current_ctx)):
    """Just the count and list for the sidebar badge."""
    today = datetime.now(timezone.utc).date()
    dated, _ = _deals(ctx, today)
    items = _reminders(ctx, dated, _tenders(ctx, today, today + timedelta(days=SOON_DAYS), "saved"))
    return {"count": len(items), "overdue": sum(1 for i in items if i["overdue"]), "items": items[:20]}


def _ics_text(s: str) -> str:
    return (s or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r", "").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCalendar lines are at most 75 octets; longer ones continue on the next line after a space."""
    b = line.encode("utf-8")
    if len(b) <= 75:
        return line
    parts, cur = [], b""
    for ch in line:
        e = ch.encode("utf-8")
        if len(cur) + len(e) > (75 if not parts else 74):
            parts.append(cur.decode("utf-8"))
            cur = b""
        cur += e
    parts.append(cur.decode("utf-8"))
    return "\r\n ".join(parts)


@router.get("/deadlines.ics")
def ics(tenders: str = "saved", ctx: Ctx = Depends(current_ctx)):
    """All-day events for the next year, each with alarms 3 days and 1 day before."""
    if tenders not in ("saved_strong", "saved", "none"):
        raise HTTPException(400, "Tenders must be saved_strong, saved or none.")
    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=366)
    dated, _ = _deals(ctx, today)
    items = [d for d in dated if not d["closed"] and today.isoformat() <= d["date"] <= end.isoformat()] + _tenders(ctx, today, end, tenders)
    base = settings.app_url.rstrip("/")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//RevenueForge//Deadlines//EN", "CALSCALE:GREGORIAN", "METHOD:PUBLISH",
             f"X-WR-CALNAME:{_ics_text(ctx.tenant.name + ' deadlines')}"]
    for it in items:
        day = date.fromisoformat(it["date"])
        if it["kind"] == "deal":
            summary = f"Deal due: {it['title']}" + (f" ({it['client']})" if it["client"] else "")
            desc = f"Owner: {it['owner']['name'] if it['owner'] else 'not set'}. {it['approved']} of {it['stages']} stages approved."
        else:
            summary = f"Tender closes: {it['title']}"
            desc = f"Buyer: {it['buyer'] or 'not stated'}. Fit score {it['score']}." + (f" Notice: {it['url']}" if it["url"] else "")
        url = base + it["link"]
        lines += ["BEGIN:VEVENT", f"UID:{it['kind']}-{it['id']}@revenueforge", f"DTSTAMP:{stamp}",
                  f"DTSTART;VALUE=DATE:{day:%Y%m%d}", f"DTEND;VALUE=DATE:{day + timedelta(days=1):%Y%m%d}",
                  f"SUMMARY:{_ics_text(summary[:200])}", f"DESCRIPTION:{_ics_text(desc + ' ' + url)}", f"URL:{url}", "TRANSP:TRANSPARENT"]
        for before in ("P3D", "P1D"):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"TRIGGER:-{before}", f"DESCRIPTION:{_ics_text(summary[:200])}", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    body = "\r\n".join(_fold(x) for x in lines) + "\r\n"
    return Response(body, media_type="text/calendar; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="revenueforge-deadlines.ics"'})
