"""Find customers for one product or service.

Given a product (a capability or accelerator from the library, or a short description of something built or planned), it
looks through the public notices the radar has read and returns:

- Buying now: open tenders the product could answer.
- Bought before: contract awards for similar work (buyer, winning supplier, value, date).
- Renewals coming up: those awards whose contract ends 6 to 18 months from now.
- Customers: the buyers behind all of that, with what they bought and when.

Same honesty rules as the rest of the radar: no AI, nothing adjusted to look better; a notice needs several of the
product's own key terms (one shared word such as "Azure" or "managed" is not enough), a notice that talks mostly about
things the company doesn't do is marked down, and a notice judged from its title alone (not in English, or no description)
can't be a strong match.
"""
from __future__ import annotations

import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import func, select

from . import knowledge as K
from .matching import _GENERIC, _STEMMED_STOP, _covered, _domain_terms, _stem, _stem_text, _vocab, squash_repeats

BANDS = [(60, "Strong match"), (35, "Possible match"), (0, "Weak match")]
RENEWAL_FROM, RENEWAL_TO = 182, 548  # days: about 6 to 18 months ahead
SHOW_FROM = 35

_index = {"key": None, "vec": None, "X": None, "meta": []}
_index_lock = threading.Lock()


def band(score: int) -> str:
    return next(label for floor, label in BANDS if score >= floor)


def _text(r) -> tuple[str, bool]:
    cats = " ".join(c.get("label", "") for c in r.categories or [])
    english = (r.language or "en").startswith("en") and bool((r.description or "").strip())
    body = r.description[:2500] if english else ""
    return squash_repeats(f"{r.title}. {cats}. {body}"), english


def _index_key(db):
    from ..models import Award, Tender
    t = db.execute(select(func.count(), func.max(Tender.fetched_at))).one()
    a = db.execute(select(func.count(), func.max(Award.fetched_at))).one()
    return (t[0], str(t[1]), a[0], str(a[1]))


def _build(db):
    """One TF-IDF index over every open tender and every stored award, rebuilt only when the notices change."""
    from ..models import Award, Tender
    key = _index_key(db)
    with _index_lock:
        if _index["key"] == key:
            return _index
    now = datetime.now(timezone.utc) - timedelta(days=1)
    meta, texts = [], []
    for t in db.scalars(select(Tender).where((Tender.deadline.is_(None)) | (Tender.deadline >= now))):
        txt, en = _text(t)
        meta.append(("tender", t.id, en))
        texts.append(txt)
    for a in db.scalars(select(Award)):
        txt, en = _text(a)
        meta.append(("award", a.id, en))
        texts.append(txt)
    if not texts:
        built = {"key": key, "vec": None, "X": None, "meta": []}
    else:
        vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words=_STEMMED_STOP, preprocessor=_stem_text,
                              min_df=1, max_features=200000, dtype="float32")
        X = vec.fit_transform([K.expand(x) for x in texts])
        built = {"key": key, "vec": vec, "X": X, "meta": meta}
    with _index_lock:
        _index.update(built)
    return _index


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z][a-z0-9]+", text.lower()) if len(w) >= 3}


def product_from(db, tid: str, body: dict) -> dict:
    """{"name", "text", "techs", "source"} from a library item or a typed description."""
    from fastapi import HTTPException

    from ..models import Accelerator, Capability
    if body.get("item_id"):
        for M, kind in ((Capability, "Capability"), (Accelerator, "Product / accelerator")):
            it = db.get(M, str(body["item_id"]))
            if it and it.tenant_id == tid:
                extra = f" {it.service_line}" if kind == "Capability" else ""
                return {"name": it.name, "kind": kind, "techs": list(it.technologies or []),
                        "text": f"{it.name}{extra} {it.description} {' '.join(it.technologies or [])}", "source": "library"}
        raise HTTPException(404, "That item isn't in your library.")
    name = str(body.get("name") or "").strip()[:200]
    desc = str(body.get("description") or "").strip()[:3000]
    if len(desc) < 20:
        raise HTTPException(400, "Describe the product in a sentence or two (at least 20 characters): what it does, for whom, and with what.")
    techs = K.find_technologies(squash_repeats(f"{name} {desc}", keep=1))
    return {"name": name or "Described product", "kind": "Described product", "techs": techs, "text": f"{name} {desc}", "source": "description"}


def find(db, tenant, product: dict, regions: list[str] | None = None) -> dict:
    from ..models import Award, Tender
    from .pipeline import load_kb
    from .tender_feeds import REGIONS, SOURCES
    now = datetime.now(timezone.utc)
    idx = _build(db)
    regions = [r for r in (regions or []) if r]
    ptext = K.expand(squash_repeats(product["text"], keep=1))  # saying a word twice in a description adds nothing
    once = squash_repeats(product["text"], keep=1)
    ptechs = [t for t in dict.fromkeys(product["techs"] + K.find_technologies(once)) if t not in K.COMMODITY_TECH]
    pterms = _domain_terms(once, ptechs)  # the product's own key words, besides technology names
    need = 2  # evidence from at least two different things the product is about
    vocab = _vocab(load_kb(db, tenant.id)) | set(_stem_text(ptext).split())
    base = {"product": {k: product[k] for k in ("name", "kind", "source")}, "key_terms": (ptechs + list(pterms.values()))[:18],
            "regions": regions, "generated_at": now.isoformat(),
            "warning": "" if len(pterms) + len(ptechs) >= 3 and len(pterms) >= 2 else ("The description is too short or too general to match fairly: a product name or one "
                                                    "technology matches almost anything. Add what it does, for whom, and how.")}
    if idx["vec"] is None:
        return {**base, "buying_now": [], "bought_before": [], "renewals": [], "customers": [], "coverage": _coverage(db, 0, 0),
                "hidden_weak": 0}
    q = idx["vec"].transform([ptext])
    sims = (idx["X"] @ q.T).toarray().ravel()
    order = sims.argsort()[::-1][:1500]
    cand = [(i, float(sims[i])) for i in order if sims[i] > 0.03]
    ids_t = [idx["meta"][i][1] for i, _ in cand if idx["meta"][i][0] == "tender"]
    ids_a = [idx["meta"][i][1] for i, _ in cand if idx["meta"][i][0] == "award"]
    rows = {r.id: r for r in db.scalars(select(Tender).where(Tender.id.in_(ids_t)))} if ids_t else {}
    rows.update({r.id: r for r in db.scalars(select(Award).where(Award.id.in_(ids_a)))} if ids_a else {})
    buying, before, hidden = [], [], 0
    for i, sim in cand:
        kind, rid, english = idx["meta"][i]
        r = rows.get(rid)
        if r is None or (regions and (r.region or "Other") not in regions):
            continue
        txt, _ = _text(r)
        words = _words(txt)
        techs = [x for x in K.find_technologies(txt) if x not in K.COMMODITY_TECH]
        shared = [t for t in ptechs if t in techs] + [pterms[s] for s in pterms if s in words]
        if len(shared) < need or not any(pterms[s] in shared for s in pterms) and len([t for t in ptechs if t in techs]) < 2:
            hidden += 1
            continue  # one shared word (a product name, "managed", "hospital") is not a match
        nterms = _domain_terms(txt, techs)
        hit = [x for x in nterms if _covered(x, vocab)]
        cov = len(hit) / len(nterms) if nterms else 0.0
        s = min(1.0, sim / 0.22)
        score = (0.7 * s + 0.3 * min(1.0, len(shared) / 4)) * (0.5 + 0.5 * min(1.0, cov / 0.6))
        score = int(round(min(1.0, score) * 100))
        notes = []
        if score >= 60 and (cov < 0.5 or len(shared) < 3):
            score = 59
        if not english and score > 55:
            score = 55
        if not english:
            notes.append("Judged from the title only (not in English or no description). Read the notice.")
        missing = [nterms[x] for x in nterms if x not in hit][:5]
        if missing and cov < 0.6 and english:
            notes.append("Also asks for: " + ", ".join(missing))
        if score < SHOW_FROM:
            hidden += 1
            continue
        item = {"id": r.id, "kind": kind, "score": score, "band": band(score), "title": r.title, "buyer": r.buyer, "country": r.country,
                "region": r.region, "value": r.value, "currency": r.currency, "url": r.url, "source": r.source,
                "source_name": SOURCES.get(r.source, {}).get("name", r.source), "attribution": SOURCES.get(r.source, {}).get("attribution", ""),
                "why": shared[:6], "notes": notes, "language": r.language}
        if kind == "tender":
            item.update(deadline=_iso(r.deadline), published=_iso(r.published))
            buying.append(item)
        else:
            item.update(suppliers=r.suppliers or [], awarded=_iso(r.awarded), contract_end=_iso(r.contract_end), end_basis=r.end_basis)
            before.append(item)
    buying.sort(key=lambda x: (-x["score"], x["deadline"] or "9999"))
    before.sort(key=lambda x: x["awarded"] or "", reverse=True)  # newest first ...
    before.sort(key=lambda x: -x["score"])  # ... within each score (the sort is stable)
    lo, hi = now + timedelta(days=RENEWAL_FROM), now + timedelta(days=RENEWAL_TO)
    renewals, sooner, no_end = [], 0, 0
    for a in before:
        end = _date(a["contract_end"])
        if end is None:
            no_end += 1
        elif lo <= end <= hi:
            renewals.append(a)
        elif now <= end < lo:
            sooner += 1
    renewals.sort(key=lambda x: x["contract_end"])
    return {**base, "buying_now": buying[:200], "bought_before": before[:300], "renewals": renewals[:200],
            "renewal_window": {"from": lo.date().isoformat(), "to": hi.date().isoformat(), "ending_sooner": sooner, "no_end_date": no_end},
            "customers": _customers(buying, before, now)[:150], "hidden_weak": hidden, "coverage": _coverage(db, len(buying), len(before)),
            "regions_available": REGIONS + ["Other"]}


def _iso(d):
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


def _date(s):
    return datetime.fromisoformat(s) if s else None


def _customers(buying, before, now) -> list[dict]:
    by: dict[str, dict] = {}
    for it in buying + before:
        name = (it["buyer"] or "").strip()
        if not name:
            continue
        key = re.sub(r"[^a-z0-9]", "", name.lower())
        c = by.setdefault(key, {"buyer": name, "country": it["country"], "region": it["region"], "open_tenders": 0, "past_awards": 0,
                                "value": defaultdict(float), "last_award": None, "suppliers": Counter(), "next_renewal": None,
                                "best_score": 0, "examples": []})
        c["best_score"] = max(c["best_score"], it["score"])
        if it["kind"] == "tender":
            c["open_tenders"] += 1
        else:
            c["past_awards"] += 1
            if it["value"] and it["currency"]:
                c["value"][it["currency"]] += it["value"]
            if it["awarded"] and (c["last_award"] is None or it["awarded"] > c["last_award"]):
                c["last_award"] = it["awarded"]
            for s in it.get("suppliers") or []:
                c["suppliers"][s] += 1
            end = it.get("contract_end")
            if end and end >= now.isoformat() and (c["next_renewal"] is None or end < c["next_renewal"]):
                c["next_renewal"] = end
        if len(c["examples"]) < 3:
            c["examples"].append(it["title"][:140])
    out = []
    for c in by.values():
        c["value"] = {k: round(v) for k, v in c["value"].items()}
        c["suppliers"] = [s for s, _ in c["suppliers"].most_common(3)]
        out.append(c)
    out.sort(key=lambda c: (-c["open_tenders"], -c["best_score"], -c["past_awards"], c["buyer"]))
    return out


def _coverage(db, n_open: int, n_awards: int) -> dict:
    from ..models import Award
    from .tender_feeds import NOT_COVERED, SOURCES, enabled_sources
    rows = db.execute(select(Award.source, func.count(), func.min(Award.awarded)).group_by(Award.source)).all()
    awards = [{"source": SOURCES.get(s, {}).get("name", s), "stored": n, "since": _iso(m)} for s, n, m in rows]
    return {"tender_sources": [SOURCES[k]["name"] for k in enabled_sources()], "award_sources": awards, "not_covered": NOT_COVERED,
            "limits": ["Only public-sector buyers publish tenders and awards; private companies aren't covered.",
                       "UK award notices don't include the contract end date, so UK contracts can't appear under renewals.",
                       "Award history is built up gradually, a month further back each refresh, up to a year.",
                       "Notices not in English are judged from their title only."]}
