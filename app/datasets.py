"""Primary public sources, used directly rather than scraped from a search engine.

Each one here is an official register or filing system with a documented
endpoint, no key, and terms that permit this. They were picked because they
answer something Cala's graph cannot:

  SEC EDGAR Form D   A US private placement must be filed within 15 days of
                     first sale. The filing is public immediately, and often
                     lands weeks before any announcement - so a company with a
                     fresh Form D and no round in the graph is raising right
                     now and has not said so.
  GLEIF              Legal Entity Identifiers. Resolves a trading name to the
                     registered legal entity, which is how you tell a brand
                     from the company that actually signs.
  PRH (Finland)      Finnish company register: incorporation, status, names.
  Brreg (Norway)     Norwegian equivalent.

Everything is cached on disk; all of these ask for an identifying User-Agent
and we give one.
"""
import json, os, sqlite3, threading, time
from urllib.parse import urlencode

import httpx

UA = os.getenv("DATASET_UA", "Flipside/1.0 (Junction 2026 hackathon project)")
DB = os.getenv("DATASET_DB", "datasets.sqlite")

SEC_FTS = "https://efts.sec.gov/LATEST/search-index"
GLEIF = "https://api.gleif.org/api/v1/lei-records"
PRH = "https://avoindata.prh.fi/opendata-ytj-api/v3/companies"
BRREG = "https://data.brreg.no/enhetsregisteret/api/enheter"

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS d (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()


def _cached(k, ttl):
    row = _conn.execute("SELECT v, ts FROM d WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < ttl:
        return json.loads(row[0])
    return None


def _store(k, v):
    with _lock:
        _conn.execute("REPLACE INTO d VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


def _get(url, key, *, ttl=86400, cache_only=False, timeout=12.0):
    hit = _cached(key, ttl)
    if hit is not None:
        return hit
    if cache_only:
        return None
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True)
        if r.status_code != 200:
            _store(key, {})
            return None
        v = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    _store(key, v)
    return v


# ---------------------------------------------------------------- SEC Form D
def form_d(company: str, **kw) -> list[dict]:
    """Form D filings naming this company, newest first."""
    q = (company or "").strip()
    if len(q) < 3:
        return []
    url = f"{SEC_FTS}?{urlencode({'q': f'\"{q}\"', 'forms': 'D'})}"
    d = _get(url, f"formd:{q.lower()}", **kw) or {}
    out = []
    for h in ((d.get("hits") or {}).get("hits") or [])[:10]:
        s = h.get("_source") or {}
        names = s.get("display_names") or []
        out.append({"names": names, "filed": s.get("file_date"),
                    "cik": (names[0].split("CIK ")[-1].rstrip(")")
                            if names and "CIK " in names[0] else None),
                    "id": h.get("_id")})
    out.sort(key=lambda x: x.get("filed") or "", reverse=True)
    return out


def silent_round(company: str, known_round_dates: list[str], **kw) -> dict | None:
    """A Form D with no matching round in the graph: raising, unannounced.

    A filing is only interesting if it is recent and nothing in Cala sits near
    it - a filing that matches a round we already know about is just the
    paperwork for that round.
    """
    from datetime import date, timedelta
    fils = form_d(company, **kw)
    if not fils:
        return None
    newest = fils[0]
    try:
        filed = date.fromisoformat(newest["filed"])
    except (TypeError, ValueError):
        return None
    if (date.today() - filed).days > 400:
        return None                      # stale: not news

    for ds in known_round_dates or []:
        try:
            if abs((date.fromisoformat(ds[:10]) - filed).days) <= 120:
                return None              # this is the filing for a known round
        except ValueError:
            continue
    return {"filed": newest["filed"], "names": newest["names"],
            "cik": newest.get("cik"),
            "url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                   f"&CIK={newest.get('cik')}&type=D" if newest.get("cik") else
                   "https://www.sec.gov/edgar/search/"}


# ---------------------------------------------------------------- registries
def gleif(name: str, **kw) -> dict | None:
    """Registered legal entity behind a trading name."""
    if len(name or "") < 3:
        return None
    url = f"{GLEIF}?{urlencode({'filter[entity.legalName]': name, 'page[size]': 5})}"
    d = _get(url, f"gleif:{name.lower()}", **kw) or {}
    rows = d.get("data") or []
    if not rows:
        return None
    # GLEIF name search matches loosely: "Abridge" returned a Swedish entity
    # in Alvsjo. Attributing the wrong legal entity to a company is worse than
    # returning nothing, so require the registered name to actually match.
    from . import norm
    want = norm.name(name)
    best = None
    for r in rows:
        nm = (((r.get("attributes") or {}).get("entity") or {})
              .get("legalName") or {}).get("name") or ""
        cand = norm.name(nm)
        if cand == want or cand.startswith(want + " ") or want.startswith(cand + " "):
            best = r
            break
    if best is None:
        return None
    a = (best.get("attributes") or {})
    ent = a.get("entity") or {}
    addr = ent.get("legalAddress") or {}
    return {"lei": a.get("lei"), "name": (ent.get("legalName") or {}).get("name"),
            "status": ent.get("status"),
            "country": addr.get("country"), "city": addr.get("city"),
            "address": ", ".join(filter(None, (addr.get("addressLines") or [])
                                        + [addr.get("postalCode"), addr.get("city")])),
            "url": f"https://search.gleif.org/#/record/{a.get('lei')}"}


def prh(name: str, **kw) -> dict | None:
    """Finnish company register."""
    if len(name or "") < 3:
        return None
    d = _get(f"{PRH}?{urlencode({'name': name})}", f"prh:{name.lower()}", **kw) or {}
    cos = d.get("companies") or []
    if not cos:
        return None
    c = cos[0]
    bid = (c.get("businessId") or {})
    names = c.get("names") or []
    return {"business_id": bid.get("value"), "registered": bid.get("registrationDate"),
            "name": (names[0].get("name") if names else None),
            "status": (c.get("status") or {}).get("descriptions", [{}])[0].get("description")
                      if isinstance(c.get("status"), dict) else None,
            "url": f"https://tietopalvelu.ytj.fi/yritys/{bid.get('value')}"
                   if bid.get("value") else None}


def brreg(name: str, **kw) -> dict | None:
    """Norwegian company register."""
    if len(name or "") < 3:
        return None
    d = _get(f"{BRREG}?{urlencode({'navn': name, 'size': 1})}", f"brreg:{name.lower()}", **kw) or {}
    rows = ((d.get("_embedded") or {}).get("enheter") or [])
    if not rows:
        return None
    e = rows[0]
    return {"orgnr": e.get("organisasjonsnummer"), "name": e.get("navn"),
            "registered": e.get("registreringsdatoEnhetsregisteret"),
            "employees": e.get("antallAnsatte"),
            "url": f"https://virksomhet.brreg.no/nb/oppslag/enheter/{e.get('organisasjonsnummer')}"}
