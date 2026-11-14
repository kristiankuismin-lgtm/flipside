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

    url = f"{ENDPOINT}?{urlencode({'q': q, 'format': 'json', 'limit': 1})}"
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
           "bbox": [float(bb[2]), float(bb[0]), float(bb[3]), float(bb[1])] if len(bb) == 4 else None}
    _store(q, val)
    return val
