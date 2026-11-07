"""Opportunity radar, part 1: reading public tender notices from open-data sources.

Only sources that publish open data under an open licence are read, through their official APIs or files:
  ted         EU and EEA: Tenders Electronic Daily search API (api.ted.europa.eu), no key needed
  uk_fts      United Kingdom: Find a Tender service OCDS API, no key needed
  worldbank   100+ countries: World Bank procurement notices API (projects the Bank finances), no key needed
  canadabuys  Canada: CanadaBuys open tender notices file (Open Government Licence), refreshed daily
  sam         United States: SAM.gov opportunities API, only when SAM_API_KEY is set (a free key from a SAM.gov account)

Not covered, because they have no open data feed: India (CPPP, GeM), Australia (AusTender publishes awarded
contracts only), the Gulf states and most of Asia outside World Bank-financed projects. The radar says so on screen.

Personal contact details in notices (names, emails, phone numbers) are never stored: only the organisation.
"""
from __future__ import annotations

import csv
import html
import io
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx

from ..config import settings

log = logging.getLogger("revenueforge.tenders")
UA = {"User-Agent": "RevenueForge opportunity radar (open-data reader)", "Accept": "application/json"}
LOOKBACK_DAYS = 21

SOURCES = {
    "ted": {"name": "TED (EU and EEA)", "covers": "European Union, Norway, Iceland, Switzerland and other EEA buyers",
            "url": "https://ted.europa.eu", "licence": "EU open data, free reuse"},
    "uk_fts": {"name": "Find a Tender (UK)", "covers": "United Kingdom public sector, higher-value contracts",
               "url": "https://www.find-tender.service.gov.uk", "licence": "Open Government Licence v3.0"},
    "worldbank": {"name": "World Bank procurement notices", "covers": "World Bank-financed projects in 100+ countries across Africa, Asia, "
                  "Latin America, the Middle East and Europe", "url": "https://projects.worldbank.org/en/projects-operations/procurement",
                  "licence": "CC BY 4.0"},
    "canadabuys": {"name": "CanadaBuys", "covers": "Government of Canada", "url": "https://canadabuys.canada.ca",
                   "licence": "Open Government Licence – Canada"},
    "sam": {"name": "SAM.gov (US federal)", "covers": "United States federal government", "url": "https://sam.gov",
            "licence": "US public domain", "needs_key": True},
}
NOT_COVERED = [
    {"where": "India (national portals)", "why": "CPPP and GeM publish no open data feed or API. World Bank-financed projects in India are covered."},
    {"where": "Australia", "why": "AusTender's open data covers awarded contracts only, not open tenders."},
    {"where": "Gulf states (UAE, Saudi Arabia, Qatar, Kuwait, Oman, Bahrain)", "why": "No open tender data feeds."},
    {"where": "Most other national portals in Asia, Africa and Latin America",
     "why": "Covered only where the World Bank finances the project."},
]

# CPV codes read from TED: IT services and software, R&D, management consultancy, telecom and network services, computer
# equipment and IT training. About 2,500 notices a fortnight; widening this list multiplies the volume quickly.
TED_CPV = ["72000000", "48000000", "73000000", "79400000", "64200000", "32400000", "30200000", "80500000"]

# --------------------------------------------------------------------------- regions
_REGION_ISO2 = {
    "Europe": "AL AD AT BY BE BA BG HR CY CZ DK EE FO FI FR DE GI GR HU IS IE IT XK LV LI LT LU MT MD MC ME NL MK NO PL PT RO RU SM RS SK SI ES SE CH UA VA",
    "United Kingdom": "GB",
    "North America": "US CA",
    "Latin America & Caribbean": "AR BO BR CL CO CR CU DO EC SV GT HT HN JM MX NI PA PY PE PR TT UY VE BB BZ GY SR LC VC GD DM AG KN BS",
    "Middle East & North Africa": "DZ BH EG IR IQ IL JO KW LB LY MA OM PS QA SA SY TN AE YE DJ",
    "Sub-Saharan Africa": "AO BJ BW BF BI CV CM CF TD KM CD CG CI GQ ER SZ ET GA GM GH GN GW KE LS LR MG MW ML MR MU MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG UG ZM ZW",
    "South Asia": "AF BD BT IN MV NP PK LK",
    "East Asia & Pacific": "AU BN KH CN FJ HK ID JP KI KR LA MO MY MH FM MN MM NR NZ PW PG PH WS SG SB TH TL TO TV VU VN TW",
    "Central Asia & Caucasus": "AM AZ GE KZ KG TJ TM UZ TR",
}
REGION_OF = {c: r for r, codes in _REGION_ISO2.items() for c in codes.split()}
REGIONS = list(_REGION_ISO2)
ISO3_TO_2 = {
    "AUT": "AT", "BEL": "BE", "BGR": "BG", "HRV": "HR", "CYP": "CY", "CZE": "CZ", "DNK": "DK", "EST": "EE", "FIN": "FI", "FRA": "FR",
    "DEU": "DE", "GRC": "GR", "HUN": "HU", "IRL": "IE", "ITA": "IT", "LVA": "LV", "LTU": "LT", "LUX": "LU", "MLT": "MT", "NLD": "NL",
    "POL": "PL", "PRT": "PT", "ROU": "RO", "SVK": "SK", "SVN": "SI", "ESP": "ES", "SWE": "SE", "NOR": "NO", "ISL": "IS", "LIE": "LI",
    "CHE": "CH", "GBR": "GB", "MKD": "MK", "SRB": "RS", "MNE": "ME", "ALB": "AL", "BIH": "BA", "MDA": "MD", "UKR": "UA", "GEO": "GE",
    "TUR": "TR", "USA": "US", "CAN": "CA",
}
COUNTRY_NAME = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark", "EE": "Estonia",
    "FI": "Finland", "FR": "France", "DE": "Germany", "GR": "Greece", "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LV": "Latvia",
    "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "NL": "Netherlands", "PL": "Poland", "PT": "Portugal", "RO": "Romania",
    "SK": "Slovakia", "SI": "Slovenia", "ES": "Spain", "SE": "Sweden", "NO": "Norway", "IS": "Iceland", "LI": "Liechtenstein",
    "CH": "Switzerland", "GB": "United Kingdom", "MK": "North Macedonia", "RS": "Serbia", "ME": "Montenegro", "AL": "Albania",
    "BA": "Bosnia and Herzegovina", "MD": "Moldova", "UA": "Ukraine", "GE": "Georgia", "TR": "Türkiye", "US": "United States", "CA": "Canada",
}


def region_for(iso2: str = "", country_name: str = "") -> str:
    if iso2 and iso2.upper() in REGION_OF:
        return REGION_OF[iso2.upper()]
    n = (country_name or "").lower()
    for word, reg in (("africa", "Sub-Saharan Africa"), ("asia", "East Asia & Pacific"), ("latin america", "Latin America & Caribbean"),
                      ("caribbean", "Latin America & Caribbean"), ("middle east", "Middle East & North Africa"), ("europe", "Europe"),
                      ("pacific", "East Asia & Pacific"), ("south asia", "South Asia"), ("central asia", "Central Asia & Caucasus")):
        if word in n:
            return reg
    return "Other"


# --------------------------------------------------------------------------- helpers
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+|\b00)?\d[\d\s().-]{7,}\d")


def _phone(m) -> str:
    raw = m.group(0)
    digits = sum(ch.isdigit() for ch in raw)
    if digits < 9 or re.fullmatch(r"\d{4}\s*[-–]\s*\d{2,4}", raw.strip()):  # years, date ranges, amounts
        return raw
    return "[phone removed]"


def _clean(text: str, n: int = 6000) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    # notices often embed the procurement officer's email and phone number: never stored
    text = PHONE_RE.sub(_phone, EMAIL_RE.sub("[email removed]", text))
    return re.sub(r"\s+", " ", text).strip()[:n]


def _date(s: str | None) -> datetime | None:
    """Dates as the sources write them: 2026-11-30T00:00:00Z, 2026-11-09+02:00, 2026-11-23Z, 2026-11-30, 30/11/2026."""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?)?", s)
    if m:
        y, mo, d, hh, mm, ss = m.groups()
        try:
            return datetime(int(y), int(mo), int(d), int(hh or 23), int(mm or 59), int(ss or 0), tzinfo=timezone.utc)
        except ValueError:
            return None
    m = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), 23, 59, tzinfo=timezone.utc)
        except ValueError:
            return None
    try:
        return datetime.strptime(s, "%d-%b-%Y").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _first(v):
    if isinstance(v, list):
        return v[0] if v else None
    return v


def _lang_text(obj, prefer=("eng",)) -> tuple[str, str]:
    """TED multilingual field {"eng": "...", "deu": [...]} -> (text, 3-letter language)."""
    if not obj:
        return "", ""
    if isinstance(obj, str):
        return obj, "eng"
    if isinstance(obj, dict):
        for lang in list(prefer) + list(obj):
            if lang in obj:
                v = obj[lang]
                return (" ".join(v) if isinstance(v, list) else str(v)), lang
    return "", ""


def tender(source: str, source_id: str, **kw) -> dict:
    return {"source": source, "source_id": str(source_id)[:120], **kw}


# --------------------------------------------------------------------------- TED (EU)
TED_FIELDS = ["publication-number", "notice-title", "buyer-name", "buyer-country", "deadline-receipt-tender-date-lot",
              "estimated-value-glo", "estimated-value-cur-glo", "estimated-value-lot", "estimated-value-cur-lot",
              "classification-cpv", "description-proc", "description-lot", "title-proc", "publication-date", "notice-type"]


def parse_ted(n: dict) -> dict | None:
    pn = n.get("publication-number")
    if not pn:
        return None
    full_title, _ = _lang_text(n.get("notice-title"))
    # "Norway – IT services: consulting, ... – Platform for strategic traffic analysis": country – CPV label – buyer's own title
    parts = [p.strip() for p in re.split(r"\s+–\s+", full_title)]
    cpv_label = parts[1] if len(parts) >= 3 else ""
    own_title, tl = _lang_text(n.get("title-proc"))
    desc, dl = _lang_text(n.get("description-proc"))
    if not desc:
        desc, dl = _lang_text(n.get("description-lot"))
    title = own_title if tl == "eng" and own_title else (parts[-1] if parts else own_title)
    iso3 = _first(n.get("buyer-country")) or ""
    iso2 = ISO3_TO_2.get(iso3, "")
    buyer, _ = _lang_text(n.get("buyer-name"))
    value = _num(_first(n.get("estimated-value-glo")))
    cur = _first(n.get("estimated-value-cur-glo"))
    if value is None:
        lots = [v for v in (_num(x) for x in (n.get("estimated-value-lot") or [])) if v]
        value = sum(lots) if lots else None
        cur = _first(n.get("estimated-value-cur-lot"))
    deadlines = [d for d in (_date(x) for x in (n.get("deadline-receipt-tender-date-lot") or [])) if d]
    cpvs = list(dict.fromkeys(n.get("classification-cpv") or []))[:8]
    lang = {"eng": "en"}.get(dl or tl, (dl or tl or "")[:2])
    return tender("ted", pn, title=_clean(title, 590) or _clean(full_title, 590),
                  description=_clean(desc), language=lang or "en", buyer=_clean(buyer, 290),
                  country=COUNTRY_NAME.get(iso2, iso3), region=region_for(iso2),
                  categories=[{"code": c, "label": cpv_label if i == 0 else ""} for i, c in enumerate(cpvs)],
                  notice_type="Contract notice", value=value, currency=cur or "",
                  published=_date(n.get("publication-date")), deadline=max(deadlines) if deadlines else None,
                  url=f"https://ted.europa.eu/en/notice/-/detail/{pn}")


def fetch_ted(client: httpx.Client, since: datetime, max_pages: int = 12) -> list[dict]:
    since = max(since, datetime.now(timezone.utc) - timedelta(days=14))
    q = (f"notice-type IN (cn-standard cn-social cn-desg) AND classification-cpv IN ({' '.join(TED_CPV)}) "
         f"AND publication-date>={since.strftime('%Y%m%d')}")
    out = []
    for page in range(1, max_pages + 1):
        r = client.post("https://api.ted.europa.eu/v3/notices/search",
                        json={"query": q, "fields": TED_FIELDS, "limit": 250, "page": page, "scope": "ACTIVE",
                              "paginationMode": "PAGE_NUMBER"})
        r.raise_for_status()
        notices = r.json().get("notices") or []
        out += [t for t in (parse_ted(n) for n in notices) if t]
        if len(notices) < 250:
            break
    return out


# --------------------------------------------------------------------------- UK Find a Tender
def parse_ocds_release(rel: dict) -> dict | None:
    t = rel.get("tender") or {}
    if not t.get("title") or (t.get("status") and t["status"] not in ("active", "planned")):
        return None
    value = t.get("value") or {}
    amount, cur = _num(value.get("amount")), value.get("currency", "")
    if amount is None:
        lots = [l.get("value") or {} for l in t.get("lots") or []]
        vals = [_num(v.get("amount")) for v in lots]
        if any(vals):
            amount, cur = sum(v for v in vals if v), next((v.get("currency") for v in lots if v.get("currency")), "")
    cls = [t.get("classification") or {}] + [c for it in t.get("items") or [] for c in it.get("additionalClassifications") or []]
    cats = []
    for c in cls:
        if c.get("id") and c["id"] not in [x["code"] for x in cats]:
            cats.append({"code": str(c["id"]), "label": c.get("description", "")})
    nid = rel.get("id") or rel.get("ocid")
    return tender("uk_fts", nid, title=_clean(t["title"], 590), description=_clean(t.get("description", "")), language="en",
                  buyer=_clean((rel.get("buyer") or {}).get("name", ""), 290), country="United Kingdom", region="United Kingdom",
                  categories=cats[:8], notice_type=(t.get("procurementMethodDetails") or "Tender notice")[:80],
                  value=amount, currency=cur or "GBP", published=_date(rel.get("date")),
                  deadline=_date((t.get("tenderPeriod") or {}).get("endDate")),
                  url=f"https://www.find-tender.service.gov.uk/Notice/{nid}")


def fetch_uk_fts(client: httpx.Client, since: datetime, max_pages: int = 15) -> list[dict]:
    url = ("https://www.find-tender.service.gov.uk/api/1.0/ocdsReleasePackages?stages=tender&limit=100"
           f"&updatedFrom={since.strftime('%Y-%m-%dT%H:%M:%S')}")
    out = []
    for _ in range(max_pages):
        r = client.get(url)
        if r.status_code in (429, 503):
            time.sleep(min(30, int(r.headers.get("Retry-After", "5") or 5)))
            r = client.get(url)
        r.raise_for_status()
        j = r.json()
        out += [t for t in (parse_ocds_release(x) for x in j.get("releases") or []) if t]
        url = (j.get("links") or {}).get("next")
        if not url:
            break
    return out


# --------------------------------------------------------------------------- World Bank
WB_GROUP = {"CW": "Works", "GO": "Goods", "CS": "Consulting services", "NC": "Non-consulting services"}


def parse_worldbank(n: dict) -> dict | None:
    if not n.get("id") or n.get("notice_status") not in (None, "Published", "Revised"):
        return None
    title = n.get("noticetitle") or n.get("bid_description") or n.get("project_name") or ""
    desc = _clean(n.get("notice_text") or n.get("bid_description") or "")
    iso2 = (n.get("contact_ctry_code") or "").upper()
    country = n.get("project_ctry_name") or n.get("contact_ctry_name") or COUNTRY_NAME.get(iso2, iso2)
    group = WB_GROUP.get(n.get("procurement_group") or "", n.get("procurement_group_desc") or "")
    return tender("worldbank", n["id"], title=_clean(title, 590), description=desc,
                  language=(n.get("notice_lang_code") or "EN").lower()[:2],
                  buyer=_clean(n.get("agency_name") or n.get("contact_organization") or n.get("project_name") or "", 290),
                  country=country, region=region_for(iso2, country),
                  categories=[{"code": n.get("procurement_group") or "", "label": group}] if group else [],
                  notice_type=n.get("notice_type") or "", value=_num(n.get("bid_estimate_amount")), currency=n.get("bid_currency_code") or "",
                  published=_date(n.get("submission_date")) or _date(n.get("noticedate")),
                  deadline=_date(n.get("submission_deadline_date")),
                  url=f"https://projects.worldbank.org/en/projects-operations/procurement-detail/{n['id']}",
                  project=n.get("project_name") or "")


def fetch_worldbank(client: httpx.Client, since: datetime, max_pages: int = 10) -> list[dict]:
    out = []
    for kind in ("Invitation for Bids", "Request for Expression of Interest"):
        for page in range(max_pages):
            r = client.get("https://search.worldbank.org/api/v2/procnotices",
                           params={"format": "json", "rows": 100, "os": page * 100, "srt": "submission_date", "order": "desc",
                                   "notice_type_exact": kind, "fl": "*"})
            r.raise_for_status()
            rows = r.json().get("procnotices") or []
            fresh = [x for x in rows if (_date(x.get("submission_date")) or since) >= since]
            out += [t for t in (parse_worldbank(x) for x in fresh) if t]
            if len(rows) < 100 or len(fresh) < len(rows):
                break
    return out


# --------------------------------------------------------------------------- CanadaBuys
CANADA_CSV = "https://canadabuys.canada.ca/opendata/pub/openTenderNotice-ouvertAvisAppelOffres.csv"


def parse_canada_row(row: dict) -> dict | None:
    title = row.get("title-titre-eng") or ""
    ref = row.get("referenceNumber-numeroReference") or row.get("solicitationNumber-numeroSollicitation")
    if not title or not ref:
        return None
    if (row.get("tenderStatus-appelOffresStatut-eng") or "Open").lower() not in ("open", "amended"):
        return None
    cats = []
    for code_k, label_k in (("unspsc", "unspscDescription-eng"), ("gsin-nibs", "gsinDescription-nibsDescription-eng")):
        codes = [c.strip(" *") for c in (row.get(code_k) or "").split("\n") if c.strip(" *")]
        labels = [c.strip(" *") for c in (row.get(label_k) or "").split("\n") if c.strip(" *")]
        for i, c in enumerate(codes[:4]):
            cats.append({"code": c, "label": labels[i] if i < len(labels) else ""})
    region = (row.get("regionsOfDelivery-regionsLivraison-eng") or "").replace("*", "").strip()
    return tender("canadabuys", ref, title=_clean(title, 590), description=_clean(row.get("tenderDescription-descriptionAppelOffres-eng") or ""),
                  language="en", buyer=_clean(row.get("contractingEntityName-nomEntitContractante-eng") or "", 290),
                  country="Canada", region="North America", categories=cats[:8],
                  notice_type=(row.get("procurementMethod-methodeApprovisionnement-eng") or row.get("noticeType-avisType-eng") or "")[:80],
                  value=None, currency="CAD", published=_date(row.get("publicationDate-datePublication")),
                  deadline=_date(row.get("tenderClosingDate-appelOffresDateCloture")),
                  url=row.get("noticeURL-URLavis-eng") or "", delivery_region=region[:120])


def fetch_canadabuys(client: httpx.Client, since: datetime) -> list[dict]:
    r = client.get(CANADA_CSV, headers={"Accept": "text/csv"})
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        t = parse_canada_row(row)
        if t:
            out.append(t)
    return out


# --------------------------------------------------------------------------- SAM.gov (US), optional
def parse_sam(o: dict) -> dict | None:
    if not o.get("noticeId") or not o.get("title"):
        return None
    pop = o.get("placeOfPerformance") or {}
    return tender("sam", o["noticeId"], title=_clean(o["title"], 590), description="", language="en",
                  buyer=_clean(o.get("fullParentPathName") or "", 290).replace(".", " / "), country="United States", region="North America",
                  categories=[{"code": o.get("naicsCode") or "", "label": "NAICS"}] if o.get("naicsCode") else [],
                  notice_type=o.get("type") or "", value=None, currency="USD", published=_date(o.get("postedDate")),
                  deadline=_date(o.get("responseDeadLine")), url=o.get("uiLink") or "",
                  delivery_region=((pop.get("state") or {}).get("name") or "")[:120])


def fetch_sam(client: httpx.Client, since: datetime) -> list[dict]:
    if not settings.sam_api_key:
        return []
    today = datetime.now(timezone.utc)
    r = client.get("https://api.sam.gov/opportunities/v2/search",
                   params={"api_key": settings.sam_api_key, "postedFrom": since.strftime("%m/%d/%Y"), "postedTo": today.strftime("%m/%d/%Y"),
                           "ptype": "o,k,r", "limit": 1000, "offset": 0})
    r.raise_for_status()
    return [t for t in (parse_sam(o) for o in r.json().get("opportunitiesData") or []) if t]


FETCHERS = {"ted": fetch_ted, "uk_fts": fetch_uk_fts, "worldbank": fetch_worldbank, "canadabuys": fetch_canadabuys, "sam": fetch_sam}


def enabled_sources() -> list[str]:
    return [k for k in FETCHERS if k != "sam" or settings.sam_api_key]


# --------------------------------------------------------------------------- storing
_STORE_KEYS = {"title", "description", "language", "buyer", "country", "region", "categories", "notice_type", "value", "currency",
               "published", "deadline", "url"}


def store(db, items: list[dict]) -> int:
    from sqlalchemy import select

    from ..models import Tender
    now = datetime.now(timezone.utc)
    cols = Tender.__table__.columns
    n = 0
    for it in items:
        if not isinstance(it, dict) or not it.get("source_id") or not str(it.get("title") or "").strip():
            continue  # a notice without an id or a title can't be shown or de-duplicated
        for k in ("published", "deadline"):
            v = it.get(k)
            if v is not None and not isinstance(v, datetime):
                it[k] = None
            elif v is not None and v.tzinfo is None:
                it[k] = v.replace(tzinfo=timezone.utc)
        if it.get("deadline") and it["deadline"] < now:
            continue  # closed already
        if it.get("value") is not None:
            try:
                it["value"] = float(it["value"])
                if it["value"] != it["value"] or it["value"] < 0 or it["value"] > 1e13:
                    it["value"] = None
            except (TypeError, ValueError):
                it["value"] = None
        sid = str(it["source_id"])[:120]
        row = db.scalar(select(Tender).where(Tender.source == it["source"], Tender.source_id == sid))
        if row is None:
            row = Tender(source=it["source"], source_id=sid)
            db.add(row)
        for k in _STORE_KEYS:
            if k in it:
                v = it[k]
                length = getattr(cols[k].type, "length", None)
                if isinstance(v, str) and length:
                    v = v[:length]  # PostgreSQL refuses over-long text; SQLite doesn't care
                setattr(row, k, v)
        row.fetched_at = now
        n += 1
    db.commit()
    return n


def prune(db, keep_days_after_deadline: int = 120) -> int:
    """Closed tenders are kept for a few months (they are history for market insights), then removed."""
    from sqlalchemy import delete

    from ..models import Tender
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days_after_deadline)
    res = db.execute(delete(Tender).where(Tender.deadline.is_not(None), Tender.deadline < cutoff))
    db.commit()
    return res.rowcount or 0


_run_lock = threading.Lock()
_state = {"running": False, "current": "", "started": None}


def status() -> dict:
    return dict(_state)


def refresh(sources: list[str] | None = None) -> dict:
    """Read every enabled source once. Safe to call from a thread; only one refresh runs at a time."""
    from ..db import SessionLocal
    from ..models import TenderSource
    if not _run_lock.acquire(blocking=False):
        return {"started": False, "reason": "A refresh is already running."}
    _state.update(running=True, started=datetime.now(timezone.utc).isoformat())
    result = {}
    db = SessionLocal()
    try:
        since = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
        with httpx.Client(timeout=60, headers=UA, follow_redirects=True) as client:
            for key in sources or enabled_sources():
                _state["current"] = key
                src = db.get(TenderSource, key) or TenderSource(key=key)
                db.add(src)
                src.last_run = datetime.now(timezone.utc)
                try:
                    items = FETCHERS[key](client, since)
                    src.fetched = store(db, items)
                    src.last_ok, src.error = datetime.now(timezone.utc), ""
                    result[key] = src.fetched
                except Exception as e:  # one source failing never stops the others
                    log.warning("Tender source %s failed: %s", key, e)
                    db.rollback()
                    src = db.get(TenderSource, key) or TenderSource(key=key)
                    db.add(src)
                    src.last_run = datetime.now(timezone.utc)
                    src.error = str(e)[:500]
                    result[key] = f"failed: {str(e)[:120]}"
                db.commit()
        prune(db)
    finally:
        db.close()
        _state.update(running=False, current="")
        _run_lock.release()
    return {"started": True, "result": result}


def refresh_in_background(sources: list[str] | None = None) -> bool:
    if _state["running"]:
        return False
    threading.Thread(target=refresh, args=(sources,), daemon=True, name="tender-refresh").start()
    return True


def start_schedule() -> None:
    """Read the sources a minute after start-up, then every RADAR_REFRESH_HOURS hours (default 12). RADAR_REFRESH_HOURS=0 turns it off."""
    hours = settings.radar_refresh_hours
    if hours <= 0:
        return

    def loop():
        time.sleep(60)
        while True:
            try:
                refresh()
            except Exception as e:
                log.warning("Tender refresh failed: %s", e)
            time.sleep(hours * 3600)

    threading.Thread(target=loop, daemon=True, name="tender-schedule").start()
