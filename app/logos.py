"""Company logos, cached locally.

Two public icon endpoints are used, in order, both purpose-built for this and
keyed only on a domain we already hold from Cala:

    https://www.google.com/s2/favicons?domain=<d>&sz=128
    https://icons.duckduckgo.com/ip3/<d>.ico        (fallback)

Bytes are cached on disk, so after the first run the UI renders offline and we
stop hitting either service. A domain that resolves to nothing is cached as a
miss and the UI falls back to a generated monogram.

Note on people: there is no equivalent for faces. Scraping image search for
photographs of identifiable individuals is a different thing entirely - it is
against those services' terms and it pulls private people's likenesses into a
product without consent - so people get a generated monogram instead.
"""
import os, sqlite3, threading, time
from urllib.parse import urlparse

import httpx

DB = os.getenv("LOGO_DB", "logos.sqlite")
SOURCES = [
    "https://www.google.com/s2/favicons?domain={d}&sz=128",
    "https://icons.duckduckgo.com/ip3/{d}.ico",
]

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS l "
              "(d TEXT PRIMARY KEY, body BLOB, ct TEXT, ts REAL)")
_lock = threading.Lock()


def domain_of(url_or_domain: str | None) -> str | None:
    if not url_or_domain:
        return None
    t = url_or_domain.strip().lower()
    if "://" not in t:
        t = "https://" + t
    host = (urlparse(t).hostname or "").removeprefix("www.")
    return host if "." in host else None


def _cached(d):
    row = _conn.execute("SELECT body, ct FROM l WHERE d=?", (d,)).fetchone()
    return row if row else None


def _store(d, body, ct):
    with _lock:
        _conn.execute("REPLACE INTO l VALUES (?,?,?,?)", (d, body, ct, time.time()))
        _conn.commit()


def fetch(domain: str, *, cache_only: bool = False, timeout: float = 8.0):
    """(bytes, content_type) or (None, None)."""
    d = domain_of(domain)
    if not d:
        return None, None
    hit = _cached(d)
    if hit is not None:
        return (hit[0] or None), (hit[1] or None)
    if cache_only:
        return None, None

    for tpl in SOURCES:
        try:
            r = httpx.get(tpl.format(d=d), timeout=timeout, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 120 \
               and r.headers.get("content-type", "").startswith("image"):
                _store(d, r.content, r.headers["content-type"])
                return r.content, r.headers["content-type"]
        except httpx.HTTPError:
            continue
    _store(d, b"", "")          # remember the miss
    return None, None
