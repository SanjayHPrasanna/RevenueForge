"""Client-name masking. When a deal is confidential, the client's names are replaced with an
alias everywhere RevenueForge shows or sends text (UI, LLM prompts, internal documents). The proposal sent to the client names it."""
from __future__ import annotations

import re


def build_terms(client_name: str, aliases: list[str] | None) -> list[str]:
    terms = [t.strip() for t in [client_name, *(aliases or [])] if t and t.strip()]
    # Longest first so a full name is replaced before its acronym.
    return sorted(set(terms), key=len, reverse=True)


def mask(text: str, client_name: str, aliases: list[str] | None, alias: str) -> str:
    if not text:
        return text
    for term in build_terms(client_name, aliases):
        if len(term) <= 4:
            # Acronyms: case-sensitive, and not part of a longer capitalised word ("SHN" but not "SHNX" or "ASHN"). Lower-case
            # letters next to it still count as a boundary, so text that lost its spaces ("SHNhasan") is masked too.
            if term.isupper():
                text = re.sub(rf"(?<![A-Z]){re.escape(term)}(?![A-Z])", alias, text)
            else:
                text = re.sub(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", alias, text)
        else:
            text = re.sub(re.escape(term), alias, text, flags=re.I)
    return text


def mask_obj(obj, client_name: str, aliases: list[str] | None, alias: str):
    if isinstance(obj, str):
        return mask(obj, client_name, aliases, alias)
    if isinstance(obj, list):
        return [mask_obj(x, client_name, aliases, alias) for x in obj]
    if isinstance(obj, dict):
        return {k: mask_obj(v, client_name, aliases, alias) for k, v in obj.items()}
    return obj


def deal_masker(deal):
    """Return a function that masks text for this deal (no-op when not confidential)."""
    if not deal.confidential or not deal.client_name:
        return lambda x: x
    alias = deal.client_alias or "the Client"
    return lambda x: mask_obj(x, deal.client_name, deal.client_aliases, alias)


ORG_HINT_RE = re.compile(r"\b([A-Z][A-Za-z&'\-]+(?:\s+(?:of|for|and|&)?\s*[A-Z][A-Za-z&'\-]+){1,6})\s*(?:\(([A-Z]{2,6})\))?")


def guess_client(text: str) -> tuple[str, list[str]]:
    """Best-effort guess of the issuing organisation and its acronym from the first pages."""
    head = text[:4000]
    m = re.search(r"([A-Z][A-Za-z\-]+(?:[ \t]+[A-Za-z\-]+){1,5})[ \t]*\(\s*([A-Z]{2,6})\s*\)", head)
    if m and m.group(2) not in ("RFP", "RFI", "RFQ", "SOW", "SLA"):
        name = m.group(1).strip()
        name = re.sub(r"^(the|a|an)\s+", "", name, flags=re.I)
        return name.title() if name.isupper() else name, [m.group(2)]
    for line in head.splitlines()[:25]:
        l = line.strip().strip("[]")
        if 5 < len(l) < 70 and re.search(r"(authority|bank|ministry|department|university|hospital|group|corporation|company|council|agency|limited|ltd|inc)\b", l, re.I):
            name = l.title() if l.isupper() else l
            acr = "".join(w[0] for w in re.findall(r"[A-Za-z]+", name) if w.lower() not in ("of", "and", "for", "the"))
            return name, [acr.upper()] if 2 <= len(acr) <= 6 else []
    return "", []
