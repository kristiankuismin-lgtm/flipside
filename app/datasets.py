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

Finland, Norway and GLEIF moved to registry.py when that grew into a
per-country layer - Denmark, France and Estonia live there too. The
functions here stay as the names the rest of the app already calls, and
delegate, so there is one implementation of each register rather than two
that can drift apart.

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
# These three used to have their own HTTP, their own parsing and their own
# cache, duplicating registry.py, which grew the richer adapters when it
# became a per-country layer. Two implementations of the same register can
# drift apart and one of them will be the one somebody reads. There is now
# one fetch per register, in registry.raw(), and these are the shape the
# older /registry endpoint and resolve.py already expect.


def _reg():
    from . import registry as R
    return R


def gleif(name: str, **kw) -> dict | None:
    """Registered legal entity behind a trading name."""
    if len(name or "") < 3:
        return None
    R = _reg()
    legacy = _cached(f"gleif:{name.lower()}", kw.get("ttl", 86400))
    d = legacy if legacy is not None else R.raw(
        "gleif", {"filter[entity.legalName]": name, "page[size]": 5})
    rows = (d or {}).get("data") or []
    for row in rows:
        a = row.get("attributes") or {}
        ent = a.get("entity") or {}
        found = (ent.get("legalName") or {}).get("name")
        # A register answers whatever is closest. "Abridge" must not come
        # back as a Swedish company of a similar name.
        if R.grade(name, found or "") == "none":
            continue
        addr = ent.get("legalAddress") or {}
        return {"lei": a.get("lei"), "name": found, "status": ent.get("status"),
                "country": addr.get("country"), "city": addr.get("city"),
                "address": ", ".join(filter(None, (addr.get("addressLines") or [])
                                            + [addr.get("postalCode"), addr.get("city")])),
                "url": f"https://search.gleif.org/#/record/{a.get('lei')}"}
    return None


def prh(name: str, **kw) -> dict | None:
    """Finnish company register, in the shape the older endpoint expects."""
    if len(name or "") < 3:
        return None
    R = _reg()
    rec = R.finland(name, getter=lambda url, params=None, **k: R.raw("prh", params))
    if not rec or R.grade(name, rec.get("name") or "") == "none":
        return None
    return {"business_id": rec["id"], "registered": rec["registered"],
            "name": rec["name"], "status": rec["status"],
            "url": f"https://tietopalvelu.ytj.fi/yritys/{rec['id']}" if rec["id"] else None}


def brreg(name: str, **kw) -> dict | None:
    """Norwegian company register, in the shape the older endpoint expects."""
    if len(name or "") < 3:
        return None
    R = _reg()
    rec = R.norway(name, getter=lambda url, params=None, **k: R.raw("brreg", params))
    if not rec or R.grade(name, rec.get("name") or "") == "none":
        return None
    return {"orgnr": rec["id"], "name": rec["name"], "registered": rec["registered"],
            "employees": None,
            "url": f"https://virksomhet.brreg.no/nb/oppslag/enheter/{rec['id']}"}
