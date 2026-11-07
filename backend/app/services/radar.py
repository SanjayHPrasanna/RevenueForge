"""Opportunity radar, part 2: how well a company fits each public tender.

The score is an estimate from the notice summary only (title, description, categories), scored against the company's
own library: capabilities, case studies, accelerators/products, people's skills and the certificate register. It is
never adjusted to look favourable: no AI is involved, missing certificates and technologies count against it, and a
notice written in another language is scored on its title and category only, which the screen says.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from sklearn.metrics.pairwise import cosine_similarity
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import func, select

from . import knowledge as K
from .matching import (CompanyKB, _STEMMED_STOP, _acc_text, _cap_text, _covered, _cs_text, _domain_terms, _stem_text, _vocab,
                       current_certs, squash_repeats, standards_in)

BANDS = [(60, "Strong fit"), (35, "Possible fit"), (0, "Weak fit")]
SCORER_VERSION = 2


def band(score: int) -> str:
    return next(label for floor, label in BANDS if score >= floor)


def library_signature(db, tid: str) -> str:
    """Changes whenever the library changes, so fits are re-scored."""
    from ..models import Accelerator, CaseStudy, Capability, Certification, Employee
    parts = [str(SCORER_VERSION)]
    for m in (Capability, CaseStudy, Accelerator, Certification, Employee):
        n, last = db.execute(select(func.count(), func.max(m.id)).where(m.tenant_id == tid)).one()
        parts.append(f"{n}:{last}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def _tender_text(t) -> tuple[str, bool]:
    cats = " ".join(c.get("label", "") for c in t.categories or [])
    english = (t.language or "en").startswith("en")
    body = t.description[:3000] if english else ""
    return squash_repeats(f"{t.title}. {cats}. {body}"), english


def score_all(kb: CompanyKB, tenders: list, inventory: dict | None = None) -> list[dict]:
    """One fit per tender: {"score", "band", "matches", "missing_tech", "missing_standards", "have_tech", "notes"}."""
    if not tenders:
        return []
    inv = inventory or kb.tech_inventory()
    company_techs = {t for t, v in inv.items() if v["people"] or v["capabilities"]}
    held_std = {s for c in current_certs(kb.certifications) for s in standards_in(f"{c['name']} {c.get('description', '')}")}
    caps, css, accs = kb.capabilities, kb.case_studies, kb.accelerators
    docs = [K.expand(squash_repeats(_cap_text(c))) for c in caps] + [K.expand(squash_repeats(_cs_text(c))) for c in css] + \
        [K.expand(squash_repeats(_acc_text(a))) for a in accs]
    vocab = _vocab(kb)
    texts = [_tender_text(t) for t in tenders]
    out = []
    if not docs:
        for t, (txt, english) in zip(tenders, texts):
            out.append({"score": 0, "band": band(0), "matches": [], "missing_tech": [], "missing_standards": [], "have_tech": [],
                        "notes": ["Your knowledge library is empty, so there is nothing to compare this tender with yet."]})
        return out
    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words=_STEMMED_STOP, min_df=1, preprocessor=_stem_text,
                          max_features=60000)
    vec.fit(docs + [K.expand(x) for x, _ in texts])
    D = vec.transform(docs)
    Q = vec.transform([K.expand(x) for x, _ in texts])
    sims = cosine_similarity(Q, D)
    nc, ncs = len(caps), len(css)
    regions_done = {(c.get("region") or "").lower() for c in css if c.get("region")}

    def norm(s, scale):
        return max(0.0, min(1.0, s / scale))

    for i, (t, (txt, english)) in enumerate(zip(tenders, texts)):
        row = sims[i]
        cap_rank = sorted(((row[j], j) for j in range(nc)), reverse=True)[:3]
        cs_rank = sorted(((row[nc + j], j) for j in range(ncs)), reverse=True)[:2]
        acc_rank = sorted(((row[nc + ncs + j], j) for j in range(len(accs))), reverse=True)[:1]
        cap = norm(cap_rank[0][0], 0.28) if cap_rank else 0.0
        cs = norm(cs_rank[0][0], 0.25) if cs_rank else 0.0
        techs = [x for x in K.find_technologies(txt) if x not in K.COMMODITY_TECH]
        have = [x for x in techs if x in company_techs]
        missing = [x for x in techs if x not in company_techs]
        stds = standards_in(txt)
        lacking_std = sorted(stds - held_std)
        if techs:
            raw = 0.5 * cap + 0.15 * cs + 0.35 * (len(have) / len(techs))
        else:
            raw = 0.75 * cap + 0.25 * cs
        raw -= min(0.3, 0.15 * len(lacking_std))
        score = int(round(max(0.0, min(1.0, raw)) * 100))
        # Same honesty checks as requirement matching: a notice that is little more than product names, or whose only
        # overlap with the library is a product name, can't be a strong fit.
        terms = _domain_terms(txt, techs)
        cov = sum(1 for x in terms if _covered(x, vocab)) / len(terms) if terms else 0.0
        thin_note = ""
        if len(terms) < 3 and score > 50:
            score, thin_note = 50, "The notice says little beyond product names, so the fit can't be judged from it. Read the full notice."
        elif techs and len(terms) >= 3 and cov < 0.2 and cap < 0.5 and score > 34:
            score, thin_note = 34, "Only product names overlap with your library; the work itself isn't covered."
        matches = [{"type": "Capability", "name": caps[j]["name"], "strength": round(norm(s, 0.28), 2)} for s, j in cap_rank if s > 0.05]
        matches += [{"type": "Case study", "name": css[j]["title"], "strength": round(norm(s, 0.25), 2)} for s, j in cs_rank if s > 0.05]
        matches += [{"type": "Accelerator / product", "name": accs[j]["name"], "strength": round(norm(s, 0.28), 2)} for s, j in acc_rank if s > 0.08]
        notes = [thin_note] if thin_note else []
        if not english:
            notes.append("The notice isn't in English, so only its title and category were scored. Read the full notice before deciding.")
        if not (t.description or "").strip():
            notes.append("The source gives no description, so only the title and category were scored.")
        if lacking_std:
            notes.append(f"Mentions {', '.join(lacking_std)}, which isn't in your certificate register.")
        held = sorted(stds & held_std)
        if held:
            notes.append(f"Mentions {', '.join(held)}, which you hold.")
        if t.region and any(t.region.lower() in r or (t.country or "").lower() in r for r in regions_done):
            notes.append(f"You have a case study in {t.country or t.region}.")
        out.append({"score": score, "band": band(score), "matches": matches[:5], "have_tech": have[:8], "missing_tech": missing[:8],
                    "missing_standards": lacking_std, "notes": notes})
    return out


def ensure_scored(db, tid: str, kb_loader) -> int:
    """Score every live tender this company hasn't been scored against (or all of them after the library changed)."""
    from ..models import Tender, TenderFit
    sig = library_signature(db, tid)
    have = {f.tender_id: f for f in db.scalars(select(TenderFit).where(TenderFit.tenant_id == tid))}
    since = datetime.now(timezone.utc) - timedelta(days=1)
    tenders = db.scalars(select(Tender).where((Tender.deadline.is_(None)) | (Tender.deadline >= since))).all()  # live ones only
    todo = [t for t in tenders if t.id not in have or (have[t.id].detail or {}).get("sig") != sig
            or have[t.id].scored_at.replace(tzinfo=have[t.id].scored_at.tzinfo or timezone.utc) < t.fetched_at.replace(tzinfo=t.fetched_at.tzinfo or timezone.utc)]
    if not todo:
        return 0
    kb = kb_loader(db, tid)
    now = datetime.now(timezone.utc)
    for t, fit in zip(todo, score_all(kb, todo)):
        row = have.get(t.id)
        if row is None:
            row = TenderFit(tenant_id=tid, tender_id=t.id)
            db.add(row)
        row.score, row.detail, row.scored_at = fit["score"], {**fit, "sig": sig}, now
    db.commit()
    return len(todo)
