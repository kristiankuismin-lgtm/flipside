"""Precise geocoding of the street addresses Cala returns.

app/geo.py resolves an address to the CITY it names, which is enough to say
"this company is in Helsinki" but puts every Helsinki company on one dot. For
a map you can zoom into, that is not good enough - and scattering them with
jitter, as the first version did, invents positions and drops companies into
the sea.

So real addresses get real coordinates from Nominatim (OpenStreetMap), cached
on disk. Nominatim's usage policy requires an identifying User-Agent and at
most one request per second, both of which this respects. Anything it cannot
resolve falls back to the city centroid and is MARKED approximate, so the map
never implies a precision it does not have.
"""
import json, os, sqlite3, threading, time
from urllib.parse import urlencode

import httpx

ENDPOINT = "https://nominatim.openstreetmap.org/search"
UA = os.getenv("GEOCODE_UA", "Flipside/1.0 (Junction 2026 hackathon project)")
DB = os.getenv("GEOCODE_DB", "geocode.sqlite")
MIN_INTERVAL = 1.05          # Nominatim policy: <= 1 request per second

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS g (q TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()
_last = [0.0]


def _cached(q):
    row = _conn.execute("SELECT v FROM g WHERE q=?", (q,)).fetchone()
    return json.loads(row[0]) if row else None


def _store(q, v):
    with _lock:
        _conn.execute("REPLACE INTO g VALUES (?,?,?)", (q, json.dumps(v), time.time()))
        _conn.commit()


def lookup(query: str, *, timeout: float = 10.0, cache_only: bool = False) -> dict | None:
    """{'lat','lon','display','bbox'} or None. Cached, including misses.

    cache_only is for request paths: Nominatim is rate-limited to one call a
    second, so a page that geocoded on demand would block for minutes.
    """
    q = " ".join((query or "").split())
    if len(q) < 3:
        return None
    hit = _cached(q)
    if hit is not None:
        return hit or None
    if cache_only:
        return None

    with _lock:
        wait = MIN_INTERVAL - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()

    # addressdetails gives country_code directly. Without it the only
    # country in the response was the last word of display_name, in the
    # local language - "Deutschland", "Suomi / Finland", "Lëtzebuerg".
    url = f"{ENDPOINT}?{urlencode({'q': q, 'format': 'json', 'limit': 1, 'addressdetails': 1})}"
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=timeout)
        r.raise_for_status()
        rows = r.json()
    except Exception:
        return None                      # transient: do not cache a failure

    if not rows:
        _store(q, {})                    # cache the miss so we stop asking
        return None
    row = rows[0]
    bb = row.get("boundingbox") or []
    val = {"lat": float(row["lat"]), "lon": float(row["lon"]),
           "display": row.get("display_name", ""),
           "cc": ((row.get("address") or {}).get("country_code") or "").upper() or None,
           "bbox": [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])] if len(bb) == 4 else None}
    _store(q, val)
    return val


# The countries that actually appear in this cache, in the language
# Nominatim returns them in. Written out rather than fetched from a
# library because it is forty-four entries and every one of them is
# visible on the map: a company placed correctly in Rennes was flying a
# globe instead of a French flag, because "France" had never been turned
# into "FR".
_COUNTRY_CODE = {
    "deutschland": "DE", "france": "FR", "united kingdom": "GB",
    "belgië / belgique / belgien": "BE", "italia": "IT", "nederland": "NL",
    "united states": "US", "norge": "NO", "sverige": "SE",
    "suomi / finland": "FI", "schweiz / suisse / svizzera / svizra": "CH",
    "españa": "ES", "danmark": "DK", "lëtzebuerg": "LU",
    "éire / ireland": "IE", "india": "IN", "österreich": "AT",
    "česko": "CZ", "대한민국": "KR", "jersey": "JE", "україна": "UA",
    "polska": "PL", "κύπρος - kıbrıs": "CY", "slovenija": "SI",
    "canada": "CA", "monaco": "MC", "australia": "AU",
    "liechtenstein": "LI", "الإمارات العربية المتحدة": "AE",
    "românia": "RO", "portugal": "PT", "ísland": "IS", "eesti": "EE",
    "latvija": "LV", "lietuva": "LT", "magyarország": "HU",
    "hrvatska": "HR", "slovensko": "SK", "българия": "BG",
    "ελλάδα": "GR", "türkiye": "TR", "ישראל": "IL",
    "日本": "JP", "中国": "CN", "singapore": "SG", "brasil": "BR",
    "საქართველო": "GE", "malta": "MT",
}


def country_of(query: str) -> str | None:
    """ISO-2 for an address we have already geocoded, or None.

    Reads the stored country_code where a lookup carried one, and falls
    back to the last component of display_name otherwise - which is what
    every row cached before addressdetails was asked for has.
    """
    hit = _cached(" ".join((query or "").split()))
    if not hit:
        return None
    cc = (hit.get("cc") or "").upper()
    if len(cc) == 2:
        return cc
    disp = hit.get("display") or ""
    if not disp:
        return None
    tail = disp.rsplit(",", 1)[-1].strip().lower()
    return _COUNTRY_CODE.get(tail)
