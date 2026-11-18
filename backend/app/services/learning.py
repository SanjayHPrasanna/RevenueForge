"""Self-learning: how RevenueForge improves with every deal, per company.

1. Correction memory: every human correction (category, match, response...) is stored and the most
   similar ones are injected into future AI prompts as examples of "how this company does it".
2. Company classifier: a model trained only on this company's reviewed requirements; it retrains
   itself as reviews accumulate and overrides generic judgement where it is confident.
3. Answer library: approved proposal answers are kept and reused on similar future requirements;
   answers from won deals rank higher.
4. Outcome calibration: actual effort on delivered deals calibrates future estimates; win/loss by
   margin band informs pricing.
"""
from __future__ import annotations

import base64
import hashlib
import io
import logging
import pickle
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import llm
from ..models import AnswerEntry, Deal, DealStage, EmbeddingCache, LearningExample, ModelState, Requirement, Tenant

log = logging.getLogger("revenueforge.learning")
MIN_TRAIN = 30


# --------------------------------------------------------------------------- embeddings with cache
def _key(text: str, task: str) -> str:
    # Vectors from different embedding models can't be compared, so the cache is kept per model. The original
    # default (Gemini's embedding model) keeps its old keys, so existing caches stay valid.
    model = llm.embed_id()
    prefix = "" if model == "gemini:gemini-embedding-001" else f"{model}|"
    return hashlib.sha1(f"{prefix}{task}|{text}".encode("utf-8", "ignore")).hexdigest()


def embed_cached(db: Session, tid: str, texts: list[str], task: str = "SEMANTIC_SIMILARITY") -> list[list[float]] | None:
    """Embeddings for texts, reusing cached vectors. Returns None when embeddings aren't available."""
    if not texts or not llm.embeddings_enabled():
        return None
    keys = [_key(t, task) for t in texts]
    have = {}
    for i in range(0, len(keys), 500):
        for row in db.scalars(select(EmbeddingCache).where(EmbeddingCache.tenant_id == tid, EmbeddingCache.key.in_(keys[i:i + 500]))):
            have[row.key] = row.vector
    missing = [i for i, k in enumerate(keys) if k not in have]
    if missing:
        try:
            vecs = llm.embed([texts[i] for i in missing], task)
        except llm.LLMUnavailable as e:
            log.info("Embeddings unavailable, using text matching: %s", e)
            return None
        for i, v in zip(missing, vecs):
            if keys[i] not in have:
                have[keys[i]] = v
                db.add(EmbeddingCache(tenant_id=tid, key=keys[i], vector=v))
        db.flush()
    return [have[k] for k in keys]


def _tfidf_sims(queries: list[str], docs: list[str]):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity

    import numpy as np
    if not queries or not docs:
        return np.zeros((len(queries), len(docs)))
    try:
        vec = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, stop_words="english").fit(queries + docs)
    except ValueError:  # only stop words / empty text: nothing to compare
        return np.zeros((len(queries), len(docs)))
    return cosine_similarity(vec.transform(queries), vec.transform(docs))


def similarity_matrix(db: Session, tid: str, queries: list[str], docs: list[str]) -> tuple[list[list[float]], str]:
    """Semantic similarity (embeddings) when available, otherwise TF-IDF. Returns (matrix, method)."""
    if not queries or not docs:
        return [[0.0] * len(docs) for _ in queries], "none"
    qv = embed_cached(db, tid, queries, "SEMANTIC_SIMILARITY")
    dv = embed_cached(db, tid, docs, "SEMANTIC_SIMILARITY") if qv is not None else None
    if qv is not None and dv is not None:
        return [[llm.cosine(q, d) for d in dv] for q in qv], "embeddings"
    return _tfidf_sims(queries, docs).tolist(), "tfidf"


# --------------------------------------------------------------------------- 1. correction memory
def record(db: Session, tid: str, kind: str, text: str, ai_value: str, human_value: str, *, deal_id: str = "", user: str = "", context: dict | None = None):
    if (ai_value or "") == (human_value or "") and kind not in ("added", "removed"):
        return
    # corrections are guidance for every later deal, for any client: stored without this deal's or any confidential
    # client's name (the wording and the reviewer's change are kept; only names become CLIENT_TOKEN)
    nf = library_neutraliser(db, tid, db.get(Deal, deal_id) if deal_id else None)
    db.add(LearningExample(tenant_id=tid, kind=kind, deal_id=deal_id, input_text=nf(text or "")[:2000], ai_value=nf(ai_value or "")[:4000],
                           human_value=nf(human_value or "")[:4000], context=_neutral_obj(nf, context or {}), user=user))


def few_shot(db: Session, tid: str, kinds: list[str], texts: list[str], k: int = 8) -> list[dict]:
    """The past corrections most relevant to these texts (one shared list for a batch prompt)."""
    rows = db.scalars(select(LearningExample).where(LearningExample.tenant_id == tid, LearningExample.kind.in_(kinds))
                      .order_by(LearningExample.created_at.desc()).limit(400)).all()
    if not rows:
        return []
    if len(rows) <= k:
        pick = rows
    else:
        nf = library_neutraliser(db, tid)  # nothing embedded for this search carries a client's name
        sims, _ = similarity_matrix(db, tid, [nf(" ".join(texts)[:6000])], [nf(r.input_text) for r in rows])
        order = sorted(range(len(rows)), key=lambda i: -sims[0][i])
        pick = [rows[i] for i in order[:k]]
    # masked again on the way into a prompt, workspace-wide, so examples stored before masking can't carry a name either
    nf = library_neutraliser(db, tid)
    return [{"kind": r.kind, "text": nf(r.input_text), "ai": nf(r.ai_value), "human": nf(r.human_value), "context": _neutral_obj(nf, r.context or {})}
            for r in pick]


def few_shot_block(examples: list[dict], title: str = "This company's reviewers corrected earlier AI output like this. Follow the same conventions") -> str:
    if not examples:
        return ""
    lines = []
    for e in examples:
        if e["kind"] in ("category", "subcategory", "priority"):
            lines.append(f'- "{e["text"][:220]}" → {e["kind"]} should be {e["human"]} (not {e["ai"]})')
        elif e["kind"] == "match":
            lines.append(f'- "{e["text"][:220]}" → match should be {e["human"]} (not {e["ai"]})')
        elif e["kind"] == "response":
            lines.append(f'- For "{e["text"][:160]}" the team rewrote the answer as: "{e["human"][:400]}"')
        elif e["kind"] == "removed":
            lines.append(f'- "{e["text"][:220]}" is NOT a requirement for this company (removed by reviewer)')
        elif e["kind"] == "added":
            lines.append(f'- Reviewer added a missed requirement: "{e["text"][:220]}" ({e["human"]})')
    return f"\n{title}:\n" + "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- 2. company classifier
def training_rows(db: Session, tid: str) -> list[tuple[str, str]]:
    rows = db.scalars(select(Requirement).where(Requirement.tenant_id == tid, Requirement.verified == True)).all()  # noqa: E712
    return [(f"{r.text} || {r.section}", r.category) for r in rows]


def train_classifier(db: Session, tid: str) -> dict:
    data = training_rows(db, tid)
    labels = Counter(c for _, c in data)
    meta = {"examples": len(data), "classes": dict(labels), "status": "waiting", "needed": MIN_TRAIN}
    if len(data) < MIN_TRAIN or len(labels) < 2:
        _save_model(db, tid, "classifier", None, meta)
        return meta
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score
    from sklearn.pipeline import make_pipeline

    X, y = [d[0] for d in data], [d[1] for d in data]
    pipe = make_pipeline(TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1),
                         LogisticRegression(max_iter=3000, class_weight="balanced", C=4.0))
    folds = max(2, min(5, min(labels.values())))
    try:
        cv = float(cross_val_score(pipe, X, y, cv=folds).mean()) if min(labels.values()) >= 2 else None
    except Exception:
        cv = None
    pipe.fit(X, y)
    meta.update({"status": "trained", "cv_accuracy": round(cv * 100, 1) if cv is not None else None,
                 "trained_at": datetime.now(timezone.utc).isoformat()})
    _save_model(db, tid, "classifier", pipe, meta)
    log.info("Company classifier retrained for %s on %s examples (cv %s)", tid, len(data), meta.get("cv_accuracy"))
    return meta


def _save_model(db: Session, tid: str, kind: str, obj, meta: dict):
    row = db.scalar(select(ModelState).where(ModelState.tenant_id == tid, ModelState.kind == kind))
    if not row:
        row = ModelState(tenant_id=tid, kind=kind)
        db.add(row)
    if obj is not None:
        buf = io.BytesIO()
        pickle.dump(obj, buf)
        row.blob = base64.b64encode(buf.getvalue()).decode()
    row.meta = meta
    row.trained_at = datetime.now(timezone.utc)
    _cache.pop((tid, kind), None)


_cache: dict = {}


def _load_model(db: Session, tid: str, kind: str):
    key = (tid, kind)
    row = db.scalar(select(ModelState).where(ModelState.tenant_id == tid, ModelState.kind == kind))
    if not row or not row.blob:
        return None, (row.meta if row else {})
    stamp = row.trained_at.isoformat() if row.trained_at else ""
    if key in _cache and _cache[key][0] == stamp:
        return _cache[key][1], row.meta
    obj = pickle.loads(base64.b64decode(row.blob))  # our own model, written by this app
    _cache[key] = (stamp, obj)
    return obj, row.meta


def classify_with_company_model(db: Session, tid: str, items: list[dict]) -> list[tuple[str, float]] | None:
    if not items:
        return []
    model, meta = _load_model(db, tid, "classifier")
    if model is None:
        return None
    X = [f"{r['text']} || {r.get('section', '')}" for r in items]
    probs = model.predict_proba(X)
    classes = list(model.classes_)
    out = []
    for p in probs:
        i = int(p.argmax())
        out.append((classes[i], float(p[i])))
    return out


def classifier_meta(db: Session, tid: str) -> dict:
    row = db.scalar(select(ModelState).where(ModelState.tenant_id == tid, ModelState.kind == "classifier"))
    return row.meta if row else {"status": "waiting", "examples": len(training_rows(db, tid)), "needed": MIN_TRAIN}


# --------------------------------------------------------------------------- 3. answer library
CLIENT_TOKEN = "{{CLIENT}}"


GENERIC_ALIASES = {"", "client", "the client"}


def _names(deal: Deal) -> list[str]:
    return [t.strip() for t in [deal.client_name, *(deal.client_aliases or [])] if t and len(t.strip()) > 1]


def _alias(deal: Deal) -> str:
    a = (deal.client_alias or "").strip()
    return "" if a.lower() in GENERIC_ALIASES else a


def library_neutraliser(db: Session, tid: str, deal: Deal | None = None):
    """The shared answer library and everything matched against it never carry a client's name.

    Returns text -> text that puts CLIENT_TOKEN in place of the names, acronyms and app aliases of every confidential
    deal in this workspace, and of `deal` (confidential or not: a library answer is reused for other clients). Used on
    what is stored (questions and answers) and on everything embedded for a library or correction-memory search, so the
    AI provider never sees a confidential client's name through the library, even from a different deal."""
    deals = list(db.scalars(select(Deal).where(Deal.tenant_id == tid, Deal.confidential.is_(True))).all())
    if deal is not None and deal not in deals:
        deals.append(deal)
    names = sorted({n for d in deals for n in _names(d)}, key=len, reverse=True)
    # app aliases ("Client A") only as whole words, so "client application" is left alone
    aliases = [re.compile(rf"(?<![A-Za-z0-9]){re.escape(a)}(?![A-Za-z0-9])") for a in sorted({_alias(d) for d in deals} - {""}, key=len, reverse=True)]
    from .masking import mask

    def fn(text):
        if not text or not isinstance(text, str):
            return text
        if names:
            text = mask(text, names[0], names[1:], CLIENT_TOKEN)
        for rx in aliases:
            text = rx.sub(CLIENT_TOKEN, text)
        return text
    return fn



def _neutral_obj(nf, obj):
    if isinstance(obj, str):
        return nf(obj)
    if isinstance(obj, list):
        return [_neutral_obj(nf, x) for x in obj]
    if isinstance(obj, dict):
        return {k: _neutral_obj(nf, v) for k, v in obj.items()}
    return obj

def _neutral(text: str, deal: Deal) -> str:
    """One deal's names and alias out of a text bound for the library (kept for callers that have no session)."""
    names = _names(deal)
    if names:
        from .masking import mask
        text = mask(text, names[0], names[1:], CLIENT_TOKEN)
    if _alias(deal):
        text = re.sub(rf"(?<![A-Za-z0-9]){re.escape(_alias(deal))}(?![A-Za-z0-9])", CLIENT_TOKEN, text)
    return text


def harvest_answers(db: Session, deal: Deal, approver: str, checker=None) -> int:
    """Approved proposal: keep its answers for reuse. With a checker (the generalised pipeline), an answer that fails the
    proposal checks (a claim its evidence doesn't back, wording from another domain, internal notes) is not kept."""
    reqs = db.scalars(select(Requirement).where(Requirement.deal_id == deal.id)).all()
    candidates = [r for r in reqs if r.response and r.category != "Commercial" and r.match_status in ("strong", "partial") or (r.response and r.response_source == "human")]
    if not candidates:
        return 0
    existing = list(db.scalars(select(AnswerEntry).where(AnswerEntry.tenant_id == deal.tenant_id)).all())
    n0 = len(existing)
    nf = library_neutraliser(db, deal.tenant_id, deal)
    sims, _ = similarity_matrix(db, deal.tenant_id, [nf(r.text) for r in candidates], [nf(e.question) for e in existing]) if existing else ([], "none")
    seen = set()
    n = 0
    for i, r in enumerate(candidates):
        if r.response_source == "library":
            continue
        if checker is not None and (r.response.startswith("[NOT COVERED") or checker.check(r.response, {"text": r.text, "match": r.match or {}})):
            continue
        key = re.sub(r"\W+", " ", r.text.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        answer = nf(r.response)
        if n0:
            best = max(range(n0), key=lambda j: sims[i][j])
            if sims[i][best] >= 0.95:
                e = existing[best]
                if r.response_source == "human" or e.origin != "human":
                    e.answer, e.origin, e.approved_by = answer, ("human" if r.response_source == "human" else e.origin), approver
                continue
        e = AnswerEntry(tenant_id=deal.tenant_id, question=nf(r.text), answer=answer, category=r.category, subcategory=r.subcategory,
                        source_deal=deal.id, source_label=f"{deal.client_alias or 'Client'} · {deal.name}"[:290],
                        origin="human" if r.response_source == "human" else "ai", approved_by=approver,
                        evidence_refs=[x.get("name") for x in (r.match or {}).get("evidence", []) if x.get("name")][:10],
                        technologies=list(r.technologies or [])[:20], industry=(deal.industry or "")[:120])
        db.add(e)
        existing.append(e)
        n += 1
    db.flush()
    vecs = embed_cached(db, deal.tenant_id, [nf(e.question) for e in existing if e.embedding is None])
    if vecs:
        for e, v in zip([e for e in existing if e.embedding is None], vecs):
            e.embedding = v
    return n


def library_matches(db: Session, tid: str, reqs: list[dict], threshold_emb: float = 0.86, threshold_tfidf: float = 0.62,
                    deal: Deal | None = None) -> dict[str, tuple[AnswerEntry, float]]:
    """Callers pass the deal's masked requirement text; both sides are neutralised again here before anything is
    embedded, so neither the requirement nor a stored question can carry a confidential client's name to the AI."""
    entries = db.scalars(select(AnswerEntry).where(AnswerEntry.tenant_id == tid)).all()
    if not entries or not reqs:
        return {}
    nf = library_neutraliser(db, tid, deal)
    sims, method = similarity_matrix(db, tid, [nf(r["text"]) for r in reqs], [nf(e.question) for e in entries])
    th = threshold_emb if method == "embeddings" else threshold_tfidf
    out = {}
    for i, r in enumerate(reqs):
        scored = [(sims[i][j] + (0.03 if entries[j].outcome == "won" else -0.02 if entries[j].outcome == "lost" else 0)
                   + (0.02 if entries[j].origin == "human" else 0), j) for j in range(len(entries))]
        s, j = max(scored)
        if s >= th:
            out[r["id"]] = (entries[j], round(s, 3))
    return out



def clean_library(db: Session, tid: str | None = None, apply: bool = False) -> dict:
    """One-off clean-up of library entries saved before questions were neutralised.

    For each entry, the names and aliases of every confidential deal in its workspace and of the deal it came from are
    replaced with CLIENT_TOKEN in the question and the answer. IDs, the source deal, origin, approver, outcome, uses,
    evidence, technologies and dates are untouched; a changed question drops its cached vector so it is embedded again
    from the clean text. Returns the affected entries as they were (the backup) and as they will be."""
    q = select(AnswerEntry)
    if tid:
        q = q.where(AnswerEntry.tenant_id == tid)
    entries = db.scalars(q.order_by(AnswerEntry.tenant_id)).all()
    backup, changes, cache = [], [], {}
    for e in entries:
        src = db.get(Deal, e.source_deal) if e.source_deal else None
        key = (e.tenant_id, src.id if src else "")
        if key not in cache:
            cache[key] = library_neutraliser(db, e.tenant_id, src)
        nf = cache[key]
        nq, na = nf(e.question), nf(e.answer)
        if (nq, na) == (e.question, e.answer):
            continue
        backup.append({"id": e.id, "tenant_id": e.tenant_id, "question": e.question, "answer": e.answer, "embedding_was_set": e.embedding is not None})
        changes.append({"id": e.id, "question": nq, "answer": na})
        if apply:
            if nq != e.question:
                e.embedding = None
            e.question, e.answer = nq, na
    if apply:
        db.commit()
    return {"checked": len(entries), "changed": len(changes), "backup": backup, "changes": changes}


def clean_corrections(db: Session, tid: str | None = None, apply: bool = False) -> dict:
    """One-off clean-up of correction examples stored before they were masked: names of every confidential deal in the
    workspace and of the deal the correction came from become CLIENT_TOKEN in the requirement text, the AI value, the
    reviewer's value and the context. IDs, kind, deal, user and dates are untouched. Returns the backup and the changes."""
    q = select(LearningExample)
    if tid:
        q = q.where(LearningExample.tenant_id == tid)
    rows = db.scalars(q.order_by(LearningExample.tenant_id)).all()
    backup, changes, cache = [], [], {}
    for x in rows:
        key = (x.tenant_id, x.deal_id or "")
        if key not in cache:
            cache[key] = library_neutraliser(db, x.tenant_id, db.get(Deal, x.deal_id) if x.deal_id else None)
        nf = cache[key]
        new = {"input_text": nf(x.input_text or ""), "ai_value": nf(x.ai_value or ""), "human_value": nf(x.human_value or ""),
               "context": _neutral_obj(nf, x.context or {})}
        old = {"input_text": x.input_text or "", "ai_value": x.ai_value or "", "human_value": x.human_value or "", "context": x.context or {}}
        if new == old:
            continue
        backup.append({"id": x.id, "tenant_id": x.tenant_id, **old})
        changes.append({"id": x.id, **new})
        if apply:
            x.input_text, x.ai_value, x.human_value, x.context = new["input_text"], new["ai_value"], new["human_value"], new["context"]
    if apply:
        db.commit()
    return {"checked": len(rows), "changed": len(changes), "backup": backup, "changes": changes}

# --------------------------------------------------------------------------- 4. outcomes & calibration
def record_outcome(db: Session, deal: Deal) -> dict:
    tid = deal.tenant_id
    for e in db.scalars(select(AnswerEntry).where(AnswerEntry.tenant_id == tid, AnswerEntry.source_deal == deal.id)):
        e.outcome = deal.status if deal.status in ("won", "lost") else "pending"
    tenant = db.get(Tenant, tid)
    s = dict(tenant.settings or {})
    est = db.scalar(select(DealStage).where(DealStage.deal_id == deal.id, DealStage.stage == "estimation"))
    if deal.status == "won" and deal.actual_effort_days and est and est.data.get("total_person_days"):
        planned = est.data["total_person_days"] / max(0.5, est.data.get("calibration", {}).get("factor", 1.0))
        hist = [h for h in s.get("effort_history", []) if h.get("deal_id") != deal.id]
        hist.append({"deal_id": deal.id, "planned": round(planned, 1), "actual": deal.actual_effort_days,
                     "ratio": round(deal.actual_effort_days / planned, 3)})
        s["effort_history"] = hist[-20:]
    tenant.settings = s
    return calibration(tenant)


def calibration(tenant: Tenant) -> dict:
    hist = (tenant.settings or {}).get("effort_history", [])
    if not hist:
        return {"factor": 1.0, "deals": 0}
    w = [0.5 ** (len(hist) - 1 - i) for i in range(len(hist))]  # recent deals weigh more
    f = sum(h["ratio"] * wi for h, wi in zip(hist, w)) / sum(w)
    return {"factor": round(max(0.6, min(1.6, f)), 3), "deals": len(hist)}


def pricing_insight(db: Session, tid: str, industry: str = "") -> dict:
    deals = db.scalars(select(Deal).where(Deal.tenant_id == tid, Deal.status.in_(["won", "lost"]))).all()
    bands: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for d in deals:
        st = db.scalar(select(DealStage).where(DealStage.deal_id == d.id, DealStage.stage == "pricing"))
        if not st or not st.data:
            continue
        sel = next((s for s in st.data.get("scenarios", []) if s["name"] == st.data.get("selected", "Target")), None)
        if not sel:
            continue
        m = sel["margin_pct"]
        band = "< 22%" if m < 22 else "22–30%" if m <= 30 else "> 30%"
        bands[band][0 if d.status == "won" else 1] += 1
    rows = [{"band": b, "won": v[0], "lost": v[1], "win_rate": round(v[0] / (v[0] + v[1]) * 100)} for b, v in bands.items()]
    return {"bands": rows, "deals": len(deals)}


# --------------------------------------------------------------------------- learning page
def stats(db: Session, tid: str) -> dict:
    tenant = db.get(Tenant, tid)
    ex = db.scalars(select(LearningExample).where(LearningExample.tenant_id == tid).order_by(LearningExample.created_at.desc())).all()
    by_kind = Counter(e.kind for e in ex)
    deals = db.scalars(select(Deal).where(Deal.tenant_id == tid).order_by(Deal.created_at)).all()
    timeline = []
    for d in deals:
        rows = db.scalars(select(Requirement).where(Requirement.deal_id == d.id)).all()
        reviewed = [r for r in rows if r.verified]
        if not rows:
            continue
        correct = sum(1 for r in reviewed if r.category == r.original_category)
        lib = sum(1 for r in rows if r.response_source == "library")
        by = Counter(r.classified_by for r in rows)
        timeline.append({"deal_id": d.id, "name": d.name[:60], "created_at": d.created_at, "requirements": len(rows), "reviewed": len(reviewed),
                         "accuracy": round(correct / len(reviewed) * 100, 1) if reviewed else None,
                         "library_reuse_pct": round(lib / max(1, sum(1 for r in rows if r.response)) * 100) if any(r.response for r in rows) else None,
                         "classified_by": dict(by), "engine": (d.meta or {}).get("engine", "")})
    entries = db.scalars(select(AnswerEntry).where(AnswerEntry.tenant_id == tid).order_by(AnswerEntry.uses.desc(), AnswerEntry.updated_at.desc())).all()
    return {
        "corrections": {"total": len(ex), "by_kind": dict(by_kind),
                        "recent": [{"kind": e.kind, "text": e.input_text[:200], "ai": e.ai_value[:200], "human": e.human_value[:300], "user": e.user,
                                    "at": e.created_at} for e in ex[:25]]},
        "classifier": classifier_meta(db, tid),
        "library": {"size": len(entries), "uses": sum(e.uses for e in entries), "human": sum(1 for e in entries if e.origin == "human"),
                    "won": sum(1 for e in entries if e.outcome == "won"), "top": [
                        {"id": e.id, "question": e.question[:220], "answer": e.answer[:600], "uses": e.uses, "outcome": e.outcome, "origin": e.origin,
                         "category": e.category, "source": e.source_label} for e in entries[:60]]},
        "calibration": calibration(tenant),
        "effort_history": (tenant.settings or {}).get("effort_history", []),
        "pricing": pricing_insight(db, tid),
        "timeline": timeline,
        "ai": llm.status(),
    }
