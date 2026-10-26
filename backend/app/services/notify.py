"""Email notifications: tell the person who started a deal when its package is ready for review.

Sent over SMTP (Gmail, Microsoft 365, Azure Communication Services, SendGrid…). With no SMTP_HOST set, nothing is sent
and the app doesn't promise an email. Deal emails use the client alias for confidential deals, like the screens do."""
from __future__ import annotations

import html
import logging
import threading
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from sqlalchemy import func, select

from ..config import settings
from ..models import STAGES, Deal, DealStage, Requirement, User
from .masking import deal_masker

log = logging.getLogger("revenueforge.notify")


def enabled() -> bool:
    return bool(settings.smtp_host and (settings.smtp_from or settings.smtp_user))


def send(to: str, subject: str, text: str, html_body: str | None = None) -> bool:
    if not enabled() or not to:
        return False
    sender = settings.smtp_from or settings.smtp_user
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((settings.smtp_from_name, sender))
    msg["To"] = to
    msg.set_content(text)
    if html_body:
        msg.add_alternative(html_body, subtype="html")
    try:
        mode = settings.smtp_security
        if mode == "ssl":
            server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20)
            if mode == "starttls":
                server.starttls(context=ssl.create_default_context())
        with server:
            if settings.smtp_user and settings.smtp_password:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
        log.info("Email sent to %s: %s", to, subject)
        return True
    except Exception as e:  # an email problem must never break a deal
        log.warning("Could not send email to %s: %s", to, e)
        return False


# --------------------------------------------------------------------------- shared
STAGE_NAME = {"requirements": "Requirements", "matching": "Capability match", "gaps": "Gaps & risks", "architecture": "Architecture",
              "estimation": "Effort & team", "pricing": "Pricing", "proposal": "Proposal", "handoff": "Delivery handoff"}
# Email types a person can switch off in Settings → My email notifications.
KINDS = {"ready": "When a deal I started is ready for review",
         "stage": "When a stage is ready for my approval",
         "reminders": "Deadline reminders for deals I own or need to approve",
         "mentions": "When someone mentions me in a comment"}


def wants(user: User, kind: str) -> bool:
    return bool(user and user.is_active and user.email and (user.prefs or {}).get(f"email_{kind}", True))


def send_async(to: str, subject: str, text: str, html_body: str | None = None) -> None:
    """Send without making the person who triggered it wait for the mail server."""
    if enabled() and to:
        threading.Thread(target=send, args=(to, subject, text, html_body), daemon=True).start()


def _deal_link(deal: Deal, stage: str | None = None) -> str:
    return f"{settings.app_url.rstrip('/')}/app/deals/{deal.id}" + (f"/{stage}" if stage else "")


def _deal_label(deal: Deal) -> tuple[str, str]:
    name = deal_masker(deal)(deal.name)
    client = deal.client_alias if deal.confidential else (deal.client_name or deal.client_alias)
    return name, client


def compose(user: User, intro: str, rows: list[tuple[str, str]], outro: str, link: str, button: str, why: str) -> tuple[str, str]:
    """Plain-text and HTML versions of a RevenueForge email."""
    first = (user.name or "").split(" ")[0] or "there"
    text = "\n".join([f"Hi {first},", "", intro, ""] + [f"{k}: {v}" for k, v in rows] + ["", outro, "", f"{button}: {link}", "", "RevenueForge"])
    e = html.escape
    table = "".join(f'<tr><td style="padding:6px 16px 6px 0;color:#5F707B;white-space:nowrap;vertical-align:top">{e(k)}</td>'
                    f'<td style="padding:6px 0;color:#10222E;font-weight:600">{e(v)}</td></tr>' for k, v in rows)
    html_body = f"""<div style="font-family:Segoe UI,Helvetica,Arial,sans-serif;background:#F3F6F8;padding:28px 12px">
<div style="max-width:560px;margin:0 auto;background:#fff;border-radius:14px;border:1px solid #DCE3E8;overflow:hidden">
<div style="background:#082B3D;padding:18px 24px;color:#fff;font-weight:800;font-size:17px">Revenue<span style="color:#F79A5E">Forge</span></div>
<div style="padding:24px">
<p style="margin:0 0 12px;color:#10222E;font-size:15px">Hi {e(first)},</p>
<p style="margin:0 0 16px;color:#10222E;font-size:15px;line-height:1.55">{e(intro)}</p>
{f'<table style="border-collapse:collapse;font-size:14px;margin:0 0 18px">{table}</table>' if rows else ''}
<p style="margin:0 0 22px;color:#3D4F5B;font-size:14px;line-height:1.55">{e(outro)}</p>
<a href="{e(link)}" style="display:inline-block;background:#0A7DB4;color:#fff;text-decoration:none;font-weight:600;font-size:14px;padding:11px 20px;border-radius:10px">{e(button)}</a>
</div></div>
<p style="max-width:560px;margin:14px auto 0;color:#8A99A3;font-size:12px;text-align:center">{e(why)} You can change which emails you get in Settings.</p>
</div>"""
    return text, html_body


def _approvers(db, deal: Deal, stage: str) -> list[User]:
    """People whose role approves this stage; the company's admins when nobody has that role."""
    from ..routers.deals import STAGE_ROLES

    users = db.scalars(select(User).where(User.tenant_id == deal.tenant_id, User.is_active == True)).all()  # noqa: E712
    by_role = [u for u in users if u.role in STAGE_ROLES.get(stage, ())]
    return by_role or [u for u in users if u.role == "admin"]


def _summary(db, deal: Deal) -> list[tuple[str, str]]:
    st = {s.stage: s for s in db.scalars(select(DealStage).where(DealStage.deal_id == deal.id))}
    g = st["gaps"].data if "gaps" in st else {}
    pr = st["pricing"].data if "pricing" in st else {}
    sel = next((s for s in pr.get("scenarios", []) if s["name"] == pr.get("selected", "Target")), None) if pr else None
    n = db.scalar(select(func.count()).select_from(Requirement).where(Requirement.deal_id == deal.id)) or 0
    rows = [("Requirements found", str(n))]
    if g.get("readiness") is not None:
        rows.append(("Bid readiness", f"{g['readiness']}% today, {g.get('mitigated_readiness', g['readiness'])}% with the mitigation plan"))
    if g.get("verdict"):
        rows.append(("Recommendation", str(g["verdict"])))
    if sel:
        ccy = pr.get("rfp_currency") or pr.get("currency") or ""
        rows.append(("Proposed price", f"{ccy} {sel['price'] * pr.get('fx_to_rfp', 1):,.0f} at a {sel['margin_pct']}% margin"))
    return rows


def deal_finished(db, deal_id: str, user_id: str | None, ok: bool, error: str = "") -> None:
    if not enabled():
        return
    deal, user = db.get(Deal, deal_id), db.get(User, user_id) if user_id else None
    if not deal:
        return
    name, client = _deal_label(deal)
    if user and user.tenant_id == deal.tenant_id and wants(user, "ready"):
        if ok:
            text, body = compose(user, f"The deal package for {name}{f' ({client})' if client else ''} is ready for review.", _summary(db, deal),
                                 "Each stage is a draft: open the deal to review and approve requirements, matches, architecture, team, price and proposal.",
                                 _deal_link(deal), "Review the deal", "You started this deal in RevenueForge.")
            send(user.email, f"Ready for review: {name}", text, body)
        else:
            text, body = compose(user, f"RevenueForge couldn't finish preparing {name}{f' ({client})' if client else ''}.",
                                 [("What happened", error[:300] or "Processing stopped.")],
                                 "Open the deal and use Re-run to try again. If the AI service was busy, a later try usually works.",
                                 _deal_link(deal), "Open the deal", "You started this deal in RevenueForge.")
            send(user.email, f"Couldn't finish: {name}", text, body)
    if ok:
        next_stage_ready(db, deal, exclude_user_id=user_id)


# --------------------------------------------------------------------------- "your turn"
def next_stage_ready(db, deal: Deal, exclude_user_id: str | None = None, after: str | None = None) -> None:
    """Email the approvers of the first stage still waiting for approval (after `after`, if given)."""
    if not enabled():
        return
    st = {s.stage: s for s in db.scalars(select(DealStage).where(DealStage.deal_id == deal.id))}
    order = STAGES[STAGES.index(after) + 1:] if after in STAGES else STAGES
    stage = next((k for k in order if k in st and st[k].status == "draft"), None)
    if not stage:
        return
    name, client = _deal_label(deal)
    done = [STAGE_NAME[k] for k in STAGES if k in st and st[k].status == "approved"]
    for u in _approvers(db, deal, stage):
        if u.id == exclude_user_id or not wants(u, "stage"):
            continue
        rows = [("Deal", f"{name}{f' ({client})' if client else ''}"), ("Waiting for you", STAGE_NAME[stage])]
        if deal.due_date:
            rows.append(("Due", deal.due_date))
        if done:
            rows.append(("Already approved", ", ".join(done)))
        text, body = compose(u, f"{STAGE_NAME[stage]} is ready for your approval.", rows,
                             "Review the draft, change anything that needs it, then approve so the next person can continue.",
                             _deal_link(deal, stage), f"Review {STAGE_NAME[stage].lower()}", f"Your role ({u.role}) approves this stage.")
        send_async(u.email, f"Your turn: {STAGE_NAME[stage]} for {name}", text, body)


# --------------------------------------------------------------------------- deadlines
def parse_due(s: str):
    from datetime import datetime

    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        from dateutil import parser

        return parser.parse(s, dayfirst=True, fuzzy=True).date()
    except Exception:
        return None


def check_deadlines(db, today=None) -> int:
    """Remind the owner and the pending approvers 3 days and 1 day before a deal is due. Returns emails sent."""
    from datetime import date

    if not enabled():
        return 0
    today = today or date.today()
    sent = 0
    for deal in db.scalars(select(Deal).where(Deal.status.in_(("in_review", "processing")))):
        due = parse_due(deal.due_date)
        if not due:
            continue
        left = (due - today).days
        mark = "1" if 0 <= left <= 1 else "3" if 2 <= left <= 3 else None
        meta = dict(deal.meta or {})
        done = dict(meta.get("reminders") or {})
        if not mark or done.get(mark):
            continue
        st = {s.stage: s for s in db.scalars(select(DealStage).where(DealStage.deal_id == deal.id))}
        pending = [k for k in STAGES if k in st and st[k].status != "approved"]
        if not pending:
            continue
        people: dict[str, User] = {}
        owner = db.get(User, deal.owner_id) if deal.owner_id else None
        if owner and owner.tenant_id == deal.tenant_id:
            people[owner.id] = owner
        for k in pending:
            for u in _approvers(db, deal, k):
                people.setdefault(u.id, u)
        name, client = _deal_label(deal)
        when = "today" if left == 0 else "tomorrow" if left == 1 else f"in {left} days"
        for u in people.values():
            if not wants(u, "reminders"):
                continue
            from ..routers.deals import STAGE_ROLES

            mine = [STAGE_NAME[k] for k in pending if u.role == "admin" or u.role in STAGE_ROLES.get(k, ())]
            rows = [("Deal", f"{name}{f' ({client})' if client else ''}"), ("Due", f"{deal.due_date} ({when})"),
                    ("Not approved yet", ", ".join(STAGE_NAME[k] for k in pending))]
            if mine and len(mine) < len(pending):
                rows.append(("Waiting for you", ", ".join(mine)))
            text, body = compose(u, f"{name} is due {when} and still has stages to approve.", rows,
                                 "Open the deal to review and approve the remaining stages in time.", _deal_link(deal), "Open the deal",
                                 "You own this deal or approve one of its stages.")
            if send(u.email, f"Due {when}: {name}", text, body):
                sent += 1
        done[mark] = today.isoformat()
        meta["reminders"] = done
        deal.meta = meta
        db.commit()
    return sent


def start_deadline_watch() -> None:
    """Checks deadlines at start-up and then every hour (one app instance)."""
    import time

    from ..db import SessionLocal

    def loop():
        time.sleep(30)
        while True:
            db = SessionLocal()
            try:
                check_deadlines(db)
            except Exception as e:
                log.warning("Deadline check failed: %s", e)
            finally:
                db.close()
            time.sleep(3600)

    threading.Thread(target=loop, daemon=True, name="deadline-watch").start()


# --------------------------------------------------------------------------- mentions
def mentioned(db, deal: Deal, author: User, comment_text: str, requirement_code: str, user_ids: list[str]) -> None:
    if not enabled():
        return
    name, client = _deal_label(deal)
    for uid in user_ids:
        u = db.get(User, uid)
        if not u or u.id == author.id or u.tenant_id != deal.tenant_id or not wants(u, "mentions"):
            continue
        text, body = compose(u, f"{author.name} mentioned you in a comment on {requirement_code}.",
                             [("Deal", f"{name}{f' ({client})' if client else ''}"), ("Comment", deal_masker(deal)(comment_text)[:600])],
                             "Reply in RevenueForge so the whole team sees the discussion.", _deal_link(deal, "requirements"),
                             "Open the requirement", "Someone mentioned you.")
        send_async(u.email, f"{author.name} mentioned you on {requirement_code} ({name})", text, body)
