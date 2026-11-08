"""Contract awards from the same open-data sources as the radar: who bought what, from which supplier, for how much, and
until when. Used by "Find customers" (bought before / renewals coming up).

Sources (all reused under the licences listed in tender_feeds.SOURCES):
- TED contract award notices (EU/EEA), IT-related CPV codes only.
- UK Find a Tender award releases (OCDS), IT-related CPV codes only. They don't carry the contract end date.
- CanadaBuys award notices (current and previous fiscal year files), IT-related categories only.

Only organisation names are kept: no contact names, emails or phone numbers. The first runs only fetch recent awards; each
run then reaches a month further back (up to BACKFILL_DAYS), so the history fills in over a few days without a huge download.
"""
from __future__ import annotations

import csv
import io
import logging
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone

import httpx

from .tender_feeds import (COUNTRY_NAME, ISO3_TO_2, TED_CPV, _clean, _date, _first, _lang_text, _num, region_for)

log = logging.getLogger("revenueforge")

BACKFILL_DAYS = 365
KEEP_YEARS = 3
CPV_PREFIXES = tuple(c.rstrip("0") for c in TED_CPV)  # "72000000" -> "72"
TED_FIELDS = ["publication-number", "notice-title", "title-proc", "description-proc", "buyer-name", "buyer-country", "winner-name",
              "tender-value", "tender-value-cur", "result-value-notice", "result-value-cur-notice", "winner-decision-date",
              "contract-conclusion-date", "contract-duration-start-date-lot", "contract-duration-end-date-lot",
              "duration-period-value-lot", "duration-period-unit-lot", "publication-date", "classification-cpv"]

AWARD_SOURCES = {
    "ted_awards": {"name": "TED contract awards (EU and EEA)", "tender_source": "ted"},
    "uk_fts_awards": {"name": "Find a Tender awards (UK)", "tender_source": "uk_fts"},
    "canadabuys_awards": {"name": "CanadaBuys award notices", "tender_source": "canadabuys"},
}


def award(source: str, source_id: str, **kw) -> dict:
    return {"source": source, "source_id": str(source_id)[:120], **kw}


def _add_duration(start: datetime | None, value, unit) -> datetime | None:
    try:
        n = float(_first(value))
    except (TypeError, ValueError):
        return None
    if not start or n <= 0 or n > 600:
        return None
    unit = str(_first(unit) or "").upper()
    days = {"DAY": 1, "WEEK": 7, "MONTH": 30.44, "YEAR": 365.25}.get(unit)
    return start + timedelta(days=n * days) if days else None


# --------------------------------------------------------------------------- TED
def parse_ted_award(n: dict) -> dict | None:
    pn = n.get("publication-number")
    names = []
    w = n.get("winner-name")
    if isinstance(w, dict):  # {"eng": ["A", "B"]} or {"deu": ["A"]}: the first language listed holds the names
        first = next(iter(w.values()), [])
        names = [x for x in (first if isinstance(first, list) else [first]) if x]
    if not pn or not names:
        return None  # no winner: not an award we can use (e.g. a lot that wasn't awarded)
    full_title, _ = _lang_text(n.get("notice-title"))
    parts = [p.strip() for p in re.split(r"\s+–\s+", full_title)]
    cpv_label = parts[1] if len(parts) >= 3 else ""
    own_title, tl = _lang_text(n.get("title-proc"))
    desc, dl = _lang_text(n.get("description-proc"))
    title = own_title if tl == "eng" and own_title else (parts[-1] if parts else own_title)
    iso3 = _first(n.get("buyer-country")) or ""
    iso2 = ISO3_TO_2.get(iso3, "")
    bn = n.get("buyer-name")
    if isinstance(bn, dict) and bn:
        first = next(iter(bn.values()))
        buyer = _first(first) if isinstance(first, list) else first  # the lead buyer (joint procurements list several)
    else:
        buyer = bn or ""
    value = _num(n.get("result-value-notice"))
    cur = n.get("result-value-cur-notice") or _first(n.get("tender-value-cur")) or ""
    if value is None:
        vals = [v for v in (_num(x) for x in (n.get("tender-value") or [])) if v]
        value = sum(vals) if vals else None
    concluded = [d for d in (_date(x) for x in (n.get("contract-conclusion-date") or [])) if d]
    decided = [d for d in (_date(x) for x in (n.get("winner-decision-date") or [])) if d]
    awarded = min(concluded) if concluded else (min(decided) if decided else _date(n.get("publication-date")))
    ends = [d for d in (_date(x) for x in (n.get("contract-duration-end-date-lot") or [])) if d]
    end, basis = (max(ends), "published end date") if ends else (None, "")
    if not end:
        starts = [d for d in (_date(x) for x in (n.get("contract-duration-start-date-lot") or [])) if d]
        end = _add_duration(min(starts) if starts else awarded, n.get("duration-period-value-lot"), n.get("duration-period-unit-lot"))
        basis = "start + duration" if end else ""
    cpvs = list(dict.fromkeys(n.get("classification-cpv") or []))[:8]
    lang = {"eng": "en"}.get(dl or tl, (dl or tl or "")[:2])
    return award("ted", pn, title=_clean(title, 590) or _clean(full_title, 590), description=_clean(desc, 1500), language=lang or "en",
                 buyer=_clean(str(buyer or ""), 290), country=COUNTRY_NAME.get(iso2, iso3), region=region_for(iso2),
                 categories=[{"code": c, "label": cpv_label if i == 0 else ""} for i, c in enumerate(cpvs)],
                 suppliers=[_clean(x, 200) for x in dict.fromkeys(names)][:10], value=value, currency=str(cur or "")[:8],
                 awarded=awarded, contract_end=end, end_basis=basis,
                 url=f"https://ted.europa.eu/en/notice/-/detail/{pn}")


def _ted_query(client: httpx.Client, frm: datetime, to: datetime | None, max_pages: int) -> list[dict]:
    q = f"notice-type IN (can-standard can-social can-desg) AND classification-cpv IN ({' '.join(TED_CPV)}) AND publication-date>={frm:%Y%m%d}"
    if to:
        q += f" AND publication-date<{to:%Y%m%d}"
    out = []
    for page in range(1, max_pages + 1):
        for attempt in range(3):
            r = client.post("https://api.ted.europa.eu/v3/notices/search",
                            json={"query": q, "fields": TED_FIELDS, "limit": 250, "page": page, "scope": "ALL", "paginationMode": "PAGE_NUMBER"})
            if r.status_code != 429:
                break
            time.sleep(10 * (attempt + 1))  # TED rate-limits bursts
        r.raise_for_status()
        notices = r.json().get("notices") or []
        out += [a for a in (parse_ted_award(n) for n in notices) if a]
        if len(notices) < 250:
            break
        time.sleep(1)
    return out


def fetch_ted_awards(client: httpx.Client, src) -> list[dict]:
    now = datetime.now(timezone.utc)
    frm = (src.last_ok - timedelta(days=2)) if src.last_ok else now - timedelta(days=30)
    frm = max(frm if frm.tzinfo else frm.replace(tzinfo=timezone.utc), now - timedelta(days=30))
    out = _ted_query(client, frm, None, 8)
    return out + _backfill(src, frm, lambda a, b: _ted_query(client, a, b, 6))


# --------------------------------------------------------------------------- UK Find a Tender
def _it_cpv(code: str) -> bool:
    code = str(code or "")
    return any(code.startswith(p) for p in CPV_PREFIXES)


def parse_ocds_award(rel: dict) -> dict | None:
    t = rel.get("tender") or {}
    cls = [t.get("classification") or {}] + [c for it in t.get("items") or [] for c in it.get("additionalClassifications") or []]
    codes = [str(c.get("id")) for c in cls if c.get("id")]
    if not codes or not any(_it_cpv(c) for c in codes):
        return None
    awards = [a for a in rel.get("awards") or [] if (a.get("status") or "active") in ("active", "pending")]
    names = list(dict.fromkeys(s.get("name") for a in awards for s in a.get("suppliers") or [] if s.get("name")))
    if not names or not t.get("title"):
        return None
    contracts = rel.get("contracts") or []
    vals = [c.get("value") or {} for c in contracts] or [a.get("value") or {} for a in awards]
    amount = sum(v for v in (_num(x.get("amount")) for x in vals) if v) or None
    cur = next((x.get("currency") for x in vals if x.get("currency")), "GBP")
    signed = [d for d in (_date(c.get("dateSigned")) for c in contracts) if d] + [d for d in (_date(a.get("date")) for a in awards) if d]
    ends = [d for d in (_date((c.get("period") or {}).get("endDate")) for c in contracts) if d] + \
           [d for d in (_date((a.get("contractPeriod") or {}).get("endDate")) for a in awards) if d]
    nid = rel.get("id") or rel.get("ocid")
    return award("uk_fts", nid, title=_clean(t["title"], 590), description=_clean(t.get("description", ""), 1500), language="en",
                 buyer=_clean((rel.get("buyer") or {}).get("name", ""), 290), country="United Kingdom", region="United Kingdom",
                 categories=[{"code": c.get("id"), "label": c.get("description", "")} for c in cls if c.get("id")][:8],
                 suppliers=[_clean(x, 200) for x in names][:10], value=amount, currency=cur,
                 awarded=min(signed) if signed else _date(rel.get("date")),
                 contract_end=max(ends) if ends else None, end_basis="published end date" if ends else "",
                 url=f"https://www.find-tender.service.gov.uk/Notice/{nid}")


def _uk_query(client: httpx.Client, frm: datetime, to: datetime | None, max_pages: int) -> list[dict]:
    url = ("https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?stages=award&limit=100"
           f"&updatedFrom={frm:%Y-%m-%dT%H:%M:%S}" + (f"&updatedTo={to:%Y-%m-%dT%H:%M:%S}" if to else ""))
    out = []
    for _ in range(max_pages):
        r = client.get(url)
        if r.status_code in (429, 503):
            time.sleep(min(30, int(r.headers.get("Retry-After", "5") or 5)))
            r = client.get(url)
        r.raise_for_status()
        j = r.json()
        out += [a for a in (parse_ocds_award(x) for x in j.get("releases") or []) if a]
        url = (j.get("links") or {}).get("next")
        if not url:
            break
    return out


def fetch_uk_awards(client: httpx.Client, src) -> list[dict]:
    now = datetime.now(timezone.utc)
    frm = (src.last_ok - timedelta(days=1)) if src.last_ok else now - timedelta(days=14)
    frm = max(frm if frm.tzinfo else frm.replace(tzinfo=timezone.utc), now - timedelta(days=30))
    return _uk_query(client, frm, None, 15) + _backfill(src, frm, lambda a, b: _uk_query(client, a, b, 10))


# --------------------------------------------------------------------------- CanadaBuys
CANADA_AWARDS = "https://canadabuys.canada.ca/opendata/pub/{fy}-awardNotice-avisAttribution.csv"
_CA_IT_GSIN = ("D3", "N70", "N58", "7010", "7020", "7030")
_CA_IT_UNSPSC = ("43", "8111", "8116")


def parse_canada_award(row: dict) -> dict | None:
    gsin = (row.get("gsin-nibs") or "").replace("*", "")
    unspsc = (row.get("unspsc") or "").replace("*", "")
    codes = [c.strip() for c in re.split(r"[\n,]", gsin + "\n" + unspsc) if c.strip()]
    if not any(c.startswith(_CA_IT_GSIN) or c.startswith(_CA_IT_UNSPSC) for c in codes):
        return None
    title = row.get("title-titre-eng") or ""
    supplier = (row.get("supplierLegalName-nomLegalFournisseur-eng") or "").strip()
    ref = row.get("referenceNumber-numeroReference") or ""
    if not title or not supplier or not ref:
        return None
    if (row.get("awardStatus-attributionStatut-eng") or "Active").lower() not in ("active", ""):
        return None
    labels = [x.strip(" *") for x in ((row.get("gsinDescription-nibsDescription-eng") or "") + "\n" +
                                      (row.get("unspscDescription-eng") or "")).split("\n") if x.strip(" *")]
    value = _num(row.get("totalContractValue-valeurTotaleContrat")) or _num(row.get("contractAmount-montantContrat"))
    end = _date(row.get("contractEndDate-dateFinContrat"))
    return award("canadabuys", ref, title=_clean(title, 590),
                 description=_clean(f"CanadaBuys reference {ref}. " + (row.get("awardDescription-descriptionAttribution-eng") or ""), 1500),
                 language="en",
                 buyer=_clean(row.get("contractingEntityName-nomEntitContractante-eng") or "", 290), country="Canada",
                 region="North America", categories=[{"code": c, "label": labels[i] if i < len(labels) else ""} for i, c in enumerate(codes[:6])],
                 suppliers=[_clean(supplier, 200)], value=value or None, currency=row.get("contractCurrency-contratMonnaie") or "CAD",
                 awarded=_date(row.get("contractAwardDate-dateAttributionContrat")) or _date(row.get("publicationDate-datePublication")),
                 contract_end=end, end_basis="published end date" if end else "",
                 url="https://open.canada.ca/data/en/dataset/a1acb126-9ce8-40a9-b889-5da2b1dd20cb")  # the notice's own page has no stable link


def _fiscal_years(now: datetime) -> list[str]:
    y = now.year if now.month >= 4 else now.year - 1
    return [f"{y}-{y + 1}", f"{y - 1}-{y}"]


def fetch_canada_awards(client: httpx.Client, src) -> list[dict]:
    now = datetime.now(timezone.utc)
    last = src.last_ok if (src.last_ok is None or src.last_ok.tzinfo) else src.last_ok.replace(tzinfo=timezone.utc)
    if last and now - last < timedelta(hours=20):
        return []  # the files are refreshed once a day
    out: dict[str, dict] = {}
    for fy in _fiscal_years(now):
        with tempfile.TemporaryFile() as tmp:  # stream to disk: the files are tens of megabytes
            with client.stream("GET", CANADA_AWARDS.format(fy=fy), headers={"Accept": "text/csv"}) as r:
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                for chunk in r.iter_bytes():
                    tmp.write(chunk)
            tmp.seek(0)
            text = io.TextIOWrapper(tmp, encoding="utf-8-sig", errors="replace", newline="")
            for row in csv.DictReader(text):
                a = parse_canada_award(row)
                if a:
                    out[a["source_id"]] = a  # amendments repeat the reference: keep the latest row
    return list(out.values())


# --------------------------------------------------------------------------- back-filling and storing
def _backfill(src, newest_from: datetime, query) -> list[dict]:
    """Each run reads one more month further back, until BACKFILL_DAYS of history is in."""
    now = datetime.now(timezone.utc)
    floor = now - timedelta(days=BACKFILL_DAYS)
    cursor = _date(src.cursor) if src.cursor else newest_from
    cursor = cursor if cursor.tzinfo else cursor.replace(tzinfo=timezone.utc)
    if cursor <= floor:
        return []
    start = max(floor, cursor - timedelta(days=30))
    items = query(start, cursor)
    src.cursor = start.date().isoformat()
    return items


FETCHERS = {"ted_awards": fetch_ted_awards, "uk_fts_awards": fetch_uk_awards, "canadabuys_awards": fetch_canada_awards}
_KEYS = {"title", "description", "language", "buyer", "country", "region", "categories", "suppliers", "value", "currency",
         "awarded", "contract_end", "end_basis", "url"}


def store(db, items: list[dict]) -> int:
    from sqlalchemy import select

    from ..models import Award
    now = datetime.now(timezone.utc)
    n = 0
    seen: dict = {}
    for it in items:
        if not isinstance(it, dict) or not it.get("source_id") or not it.get("title"):
            continue
        for k in ("awarded", "contract_end"):
            v = it.get(k)
            if v is not None and not isinstance(v, datetime):
                it[k] = None
            elif v is not None and v.tzinfo is None:
                it[k] = v.replace(tzinfo=timezone.utc)
        if it.get("value") is not None and not (0 < it["value"] < 1e13):
            it["value"] = None
        k = (it["source"], it["source_id"])
        row = seen.get(k) or db.scalar(select(Award).where(Award.source == it["source"], Award.source_id == it["source_id"]))
        if row is None:
            row = Award(source=it["source"], source_id=it["source_id"])
            db.add(row)
        seen[k] = row  # the same notice twice in one batch updates one row
        for k in _KEYS:
            if k in it:
                setattr(row, k, it[k])
        row.fetched_at = now
        n += 1
        if n % 200 == 0:
            db.commit()
    db.commit()
    return n


def prune(db) -> int:
    """Awards older than KEEP_YEARS are removed, unless the contract is still running."""
    from sqlalchemy import and_, delete, or_

    from ..models import Award
    cutoff = datetime.now(timezone.utc) - timedelta(days=365 * KEEP_YEARS)
    res = db.execute(delete(Award).where(and_(Award.awarded.is_not(None), Award.awarded < cutoff,
                                              or_(Award.contract_end.is_(None), Award.contract_end < datetime.now(timezone.utc)))))
    db.commit()
    return res.rowcount or 0


def enabled() -> list[str]:
    from .tender_feeds import enabled_sources
    on = set(enabled_sources())
    return [k for k, m in AWARD_SOURCES.items() if m["tender_source"] in on]


def refresh(db, client: httpx.Client, state: dict) -> dict:
    from ..models import TenderSource
    result = {}
    for key in enabled():
        state["current"] = key
        src = db.get(TenderSource, key) or TenderSource(key=key)
        db.add(src)
        src.last_run = datetime.now(timezone.utc)
        try:
            items = FETCHERS[key](client, src)
            cursor = src.cursor
            src.fetched = store(db, items)
            src.cursor = cursor
            src.last_ok, src.error = datetime.now(timezone.utc), ""
            result[key] = src.fetched
        except Exception as e:
            log.warning("Award source %s failed: %s", key, e)
            db.rollback()
            src = db.get(TenderSource, key) or TenderSource(key=key)
            db.add(src)
            src.last_run = datetime.now(timezone.utc)
            src.error = str(e)[:500]
            result[key] = f"failed: {str(e)[:120]}"
        db.commit()
    prune(db)
    return result
