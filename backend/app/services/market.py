"""Market insights: where a company's offerings are in demand, from the public tenders the radar has read.

Each tender is assigned to the company's single closest offering (a capability or an accelerator/product), and only when
the overlap is real. Everything is counted from the notices themselves: no estimates, no AI, no outside market data. The
coverage limits of the radar (which countries publish open data) apply here too, and the page says so.
"""
from __future__ import annotations

import hashlib
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sqlalchemy import func, select

from . import knowledge as K
from .matching import _STEMMED_STOP, _stem_text, squash_repeats

MIN_SIM = 0.10  # below this the overlap is a few shared words, not the same kind of work
WINDOW_DAYS = 90

# What the buyer does, from the notice text. Public tenders are mostly government, so "Public administration" is the
# fallback rather than a guess at an industry.
SECTORS = [
    ("Healthcare", r"\bhealth|hospital|clinical|patient|medical|\bnhs\b|pharma"),
    ("Transport", r"transit|transport|railway|\brail\b|\bbus(es)?\b|ferr(y|ies)|aviation|airport|\bport\b|highway|road|traffic|vehicle"),
    ("Education", r"school|universit|college|education|learning|student|academ"),
    ("Defence & security", r"defen[cs]e|military|armed forces|police|border|justice|prison"),
    ("Energy & utilities", r"energy|electric|utilit|\bwater\b|wastewater|gas grid|power"),
    ("Finance & tax", r"\bbank|finance|financial|tax|revenue authority|treasury|pension|insurance|customs"),
    ("Social services & employment", r"social|welfare|employment|employability|housing|benefit"),
    ("Agriculture & environment", r"agricultur|farm|irrigation|forest|environment|climate|fisher"),
    ("Telecom & digital", r"telecom|broadband|digital transformation|e-government|egov|connectivity"),
]


def sector_of(text: str) -> str:
    low = (text or "").lower()
    scores = {name: len(re.findall(rx, low)) for name, rx in SECTORS}
    best = max(scores, key=scores.get)
    return best if scores[best] else "Public administration & other"


def _offerings(db, tid: str) -> list[dict]:
    from ..models import Accelerator, Capability
    out = [{"id": c.id, "kind": "Capability", "name": c.name, "text": f"{c.name} {c.service_line} {c.description} {' '.join(c.technologies or [])}"}
           for c in db.scalars(select(Capability).where(Capability.tenant_id == tid))]
    out += [{"id": a.id, "kind": "Product / accelerator", "name": a.name, "text": f"{a.name} {a.description} {' '.join(a.technologies or [])}"}
            for a in db.scalars(select(Accelerator).where(Accelerator.tenant_id == tid))]
    return out


def _served(db, tenant) -> tuple[set[str], set[str]]:
    """Regions the company says it serves (supplier-network listing) and countries where it has case studies."""
    from ..models import CaseStudy
    regions = set(((tenant.settings or {}).get("network") or {}).get("regions") or [])
    countries = {(c.region or "").strip().lower() for c in db.scalars(select(CaseStudy).where(CaseStudy.tenant_id == tenant.id)) if c.region}
    return regions, countries


_cache: dict[str, tuple[str, dict]] = {}
_lock = threading.Lock()


def _signature(db, tid: str) -> str:
    from ..models import Accelerator, Capability, CaseStudy, Tender
    parts = []
    for m in (Capability, Accelerator, CaseStudy):
        n, last = db.execute(select(func.count(), func.max(m.id)).where(m.tenant_id == tid)).one()
        parts.append(f"{n}:{last}")
    n, last = db.execute(select(func.count(), func.max(Tender.fetched_at))).one()
    parts.append(f"{n}:{last}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def market(db, tenant) -> dict:
    sig = _signature(db, tenant.id)
    with _lock:
        hit = _cache.get(tenant.id)
        if hit and hit[0] == sig:
            return hit[1]
    data = _compute(db, tenant)
    with _lock:
        _cache[tenant.id] = (sig, data)
    return data


def _compute(db, tenant) -> dict:
    from ..models import Tender
    from .tender_feeds import NOT_COVERED, REGIONS, SOURCES, enabled_sources
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=WINDOW_DAYS)
    offers = _offerings(db, tenant.id)
    tenders = db.scalars(select(Tender).where((Tender.published.is_(None)) | (Tender.published >= since))).all()
    base = {"window_days": WINDOW_DAYS, "tenders_read": len(tenders), "regions": REGIONS + ["Other"],
            "sources": [SOURCES[k]["name"] for k in enabled_sources()], "not_covered": NOT_COVERED, "generated_at": now.isoformat()}
    if not offers or not tenders:
        return {**base, "offerings": [], "matrix": [], "totals": {"matched": 0, "open": 0, "value_by_currency": {}},
                "untapped": [], "weeks": []}

    def ttext(t):
        cats = " ".join(c.get("label", "") for c in t.categories or [])
        body = t.description[:2500] if (t.language or "en").startswith("en") else ""
        return f"{t.title}. {cats}. {body}"

    vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words=_STEMMED_STOP, preprocessor=_stem_text, min_df=1, max_features=80000)
    docs = [K.expand(squash_repeats(o["text"])) for o in offers]
    texts = [K.expand(squash_repeats(ttext(t))) for t in tenders]
    vec.fit(docs + texts)
    sims = cosine_similarity(vec.transform(texts), vec.transform(docs))
    served_regions, case_countries = _served(db, tenant)
    # Same honesty check as the radar: a shared phrase ("managed services") isn't demand for what the company does.
    # A tender counts only if enough of what it talks about appears anywhere in the company's library.
    from .matching import _covered, _domain_terms, _vocab
    from .pipeline import load_kb
    vocab = _vocab(load_kb(db, tenant.id))

    def relevant(t) -> bool:
        txt = ttext(t)
        terms = _domain_terms(txt, [x for x in K.find_technologies(txt) if x not in K.COMMODITY_TECH])
        if len(terms) < 3:
            return True  # too little text to judge either way; the similarity threshold decides
        return sum(1 for x in terms if _covered(x, vocab)) / len(terms) >= 0.34

    per = {o["id"]: {"id": o["id"], "kind": o["kind"], "name": o["name"], "open": 0, "total": 0, "regions": Counter(), "countries": Counter(),
                     "sectors": Counter(), "buyers": Counter(), "values": defaultdict(float), "examples": []} for o in offers}
    weeks = Counter()
    matrix = defaultdict(Counter)
    matched = 0
    open_matched = 0
    for i, t in enumerate(tenders):
        row = sims[i]
        j = int(row.argmax())
        if row[j] < MIN_SIM or not relevant(t):
            continue
        o = offers[j]
        p = per[o["id"]]
        live = t.deadline is None or (t.deadline.replace(tzinfo=t.deadline.tzinfo or timezone.utc) >= now)
        matched += 1
        p["total"] += 1
        p["regions"][t.region or "Other"] += 1
        p["countries"][t.country or "Unknown"] += 1
        p["sectors"][sector_of(f"{t.buyer} {t.title} {t.description[:600]}")] += 1
        if t.buyer:
            p["buyers"][t.buyer] += 1
        if t.value and t.currency:
            p["values"][t.currency] += t.value
        matrix[o["id"]][t.region or "Other"] += 1
        if t.published:
            pub = t.published.replace(tzinfo=t.published.tzinfo or timezone.utc)
            weeks[(pub - timedelta(days=pub.weekday())).date().isoformat()] += 1
        if live:
            open_matched += 1
            p["open"] += 1
            if len(p["examples"]) < 40:
                p["examples"].append({"id": t.id, "title": t.title, "country": t.country, "deadline": t.deadline, "sim": float(row[j]),
                                      "value": t.value, "currency": t.currency})

    offerings = []
    for o in offers:
        p = per[o["id"]]
        ex = sorted(p["examples"], key=lambda x: -x["sim"])[:5]
        for x in ex:
            x.pop("sim", None)
        offerings.append({"id": p["id"], "kind": p["kind"], "name": p["name"], "open": p["open"], "total": p["total"],
                          "regions": p["regions"].most_common(), "countries": p["countries"].most_common(8),
                          "sectors": p["sectors"].most_common(6), "buyers": p["buyers"].most_common(5),
                          "value_by_currency": {k: round(v) for k, v in sorted(p["values"].items(), key=lambda kv: -kv[1])[:4]},
                          "examples": ex})
    offerings.sort(key=lambda x: (-x["total"], x["name"]))

    # Demand in regions where the company has no case study (or that it doesn't list as served): where else it could sell.
    country_region = {(t.country or "").lower(): t.region for t in tenders if t.country and t.region}
    from .tender_feeds import COUNTRY_NAME, region_for
    for code, name in COUNTRY_NAME.items():
        country_region.setdefault(name.lower(), region_for(code))
    case_regions = {country_region.get(c) or region_for("", c) for c in case_countries}
    untapped = []
    for off in offerings:
        for region, n in off["regions"]:
            if n < 3 or region == "Other":
                continue
            no_case = region not in case_regions
            not_listed = bool(served_regions) and region not in served_regions
            if not (no_case or not_listed):
                continue
            why = []
            if no_case:
                why.append("no case study there yet")
            if not_listed:
                why.append("not among the regions in your supplier-network profile")
            untapped.append({"offering": off["name"], "region": region, "tenders": n, "why": "You have " + " and it's ".join(why) + "." if no_case
                             else "It's " + why[0] + "."})
    untapped.sort(key=lambda x: -x["tenders"])

    region_totals = Counter()
    for off in offerings:
        for r, n in off["regions"]:
            region_totals[r] += n
    week_list = sorted(weeks.items())[-13:]
    return {**base,
            "totals": {"matched": matched, "open": open_matched, "offerings": len(offers),
                       "top_region": region_totals.most_common(1)[0][0] if region_totals else "",
                       "countries": len({c for off in offerings for c, _ in off["countries"]})},
            "offerings": offerings,
            "matrix": [{"offering": o["name"], "id": o["id"], "cells": dict(matrix[o["id"]])} for o in offerings if o["total"]],
            "region_totals": region_totals.most_common(),
            "untapped": untapped[:8],
            "weeks": [{"week": w, "tenders": n} for w, n in week_list],
            "served_regions": sorted(served_regions)}
