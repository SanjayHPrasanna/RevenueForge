"""Public facts for the Trust & data, Privacy and Terms pages. Everything here is read from how this server is actually set up,
so the pages can't promise something the deployment doesn't do."""
from __future__ import annotations

from fastapi import APIRouter

from ..config import settings
from ..services import llm, tender_feeds

router = APIRouter(prefix="/api", tags=["trust"])

UPDATED = "2026-11-07"

AI_TERMS = {
    "gemini": ("Google (Gemini API)", "https://ai.google.dev/terms"),
    "openai": ("OpenAI", ""),
    "anthropic": ("Anthropic", ""),
    "azure": ("Microsoft (Azure OpenAI)", ""),
}


def _ai() -> dict:
    p = llm.server_profile()
    name = llm._usable(p)
    if name == "none":
        return {"enabled": False, "summary": "No AI service is switched on. Requirements, matches, estimates and documents come from the built-in "
                                              "rules engine, which runs entirely on this server."}
    who, terms = AI_TERMS[name]
    if name == "gemini" and not p.paid:
        trains = ("This is a free-tier key. Google's terms allow it to use what is sent on the free tier to improve its products, and "
                  "people may review it. Use sample or non-confidential documents only; the app asks you to confirm before each RFP.")
    elif name == "gemini":
        trains = ("This key is on a billed Google Cloud project. Google's paid-tier terms say prompts and responses aren't used to improve its "
                  "products; Google keeps them for a limited time only to detect misuse.")
    else:
        trains = f"Business API terms apply. Check {who}'s terms for how long it keeps data and whether it uses it for training."
    return {"enabled": True, "provider": who, "terms_url": terms, "paid": p.paid if name == "gemini" else None, "training": trains,
            "summary": f"When AI is used, the parts of a document being worked on are sent to {who}. Client names can be masked first "
                       "(each deal has a client alias)."}


@router.get("/trust")
def trust():
    sub = [{"name": "Microsoft Azure", "purpose": "Hosting: the app, its database and uploaded files",
            "where": settings.data_location or "Region chosen by the operator"}]
    ai = _ai()
    if ai["enabled"]:
        sub.append({"name": ai["provider"], "purpose": "AI: reading RFPs, judging matches, drafting text", "where": "Per the provider's terms"})
    if settings.google_client_id:
        sub.append({"name": "Google", "purpose": "Sign in with Google; Google Drive import (your browser talks to Google directly, "
                                                 "and no Google key is stored on our server)", "where": "Google"})
    if settings.ms_client_id:
        sub.append({"name": "Microsoft Entra ID", "purpose": "Sign in with Microsoft", "where": "Microsoft"})
    if settings.smtp_host:
        sub.append({"name": settings.smtp_host, "purpose": "Sending notification emails", "where": "Per the email provider"})
    return {
        "operator": settings.operator_name, "contact": settings.contact_email, "updated": UPDATED,
        "data_location": settings.data_location or "",
        "ai": ai,
        "company_ai_note": "A company can switch to its own AI provider and key in Settings. Its documents then go to that provider "
                           "under the company's own agreement, and the platform's AI isn't used for it.",
        "subprocessors": sub,
        "sources": [{"name": m["name"], "covers": m["covers"], "licence": m["licence"], "licence_url": m.get("licence_url", ""),
                     "attribution": m.get("attribution", ""), "enabled": k in tender_feeds.enabled_sources()}
                    for k, m in tender_feeds.SOURCES.items()],
        "in_place": [
            "Every company's data is kept separate: each request is checked against the signed-in company, and other companies' "
            "records answer as \"not found\".",
            "Six roles (admin, presales, architect, finance, delivery, viewer); each action is limited to the roles that need it.",
            "Passwords are stored as salted hashes, never in plain text. Repeated wrong passwords pause sign-in for that email and address.",
            "Sign-in tokens expire and are checked against the database on every request, so a removed user is locked out at once.",
            "An audit log records who imported, approved, changed or deleted what.",
            "Uploads are limited by type and size, and spreadsheets exported from the app can't run formulas hidden in client text.",
            "Employee names are hidden by default; skills are matched by employee code.",
            "Contact names, emails and phone numbers in public tender notices are removed before storing.",
            "Company admins can download all their company's data, or delete it permanently, from Settings.",
            "Automated security, fairness and end-to-end tests (more than 1,600 checks) run against every role and company type.",
        ],
        "not_yet": [
            "No independent security certification yet (for example ISO/IEC 27001 or SOC 2).",
            "No two-step sign-in (MFA) for email-and-password accounts yet. Sign in with Google or Microsoft to use your organisation's MFA.",
            "Backups depend on the hosting setup and aren't yet tested by restoring them on a schedule.",
            "The Google Drive connection uses a permission Google hasn't reviewed for this app yet, so Google shows an \"unverified app\" "
            "warning and only listed test users can connect.",
        ],
        "fairness": [
            "Supplier shortlists and tender fits are computed the same way for every company, from its own library, with no AI and no paid placement.",
            "A technology name alone never makes a match; certificates count only from the certificate register, and only while valid.",
            "Fictional demo suppliers are always labelled as fictional.",
            "Shortlists are advice to help a buyer find suppliers. They are not a procurement decision and don't replace the buyer's own rules.",
        ],
    }
