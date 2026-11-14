"""News from the open web, for the firms Cala has nothing written about.

/knowledge/search returns sourced claims, which is the better answer when it
has one: each claim carries the document it was read from. For most of the
664 funds it has none, and a News tab that says "nothing" about a firm with
a press page is reporting our coverage, not theirs.

Two open indexes are asked, in that order, both with documented public APIs,
no key, no scraping and no terms problem:

  GDELT      an index of world news. The better source when it answers, and
             it rate-limits anonymous callers hard, so it often does not.
  Hacker News the Algolia search over HN, which is where European venture
             rounds get posted. No rate limit, but its search is fuzzy -
             "Gosta Labs" returns a Costa Rican computer lab - so every hit
             has to carry the name in its title or its URL to count.

We keep the headline, the domain, the date and the link, and never the
article body: the headline plus where to read it is the checkable part, and
republishing someone's text is not ours to do.

A result from here is labelled as coming from here. It is weaker evidence
than a Cala claim - nobody has decided these articles are about the right
company - so the UI says which it got rather than blending the two.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

import httpx

API = "https://api.gdeltproject.org/api/v2/doc/doc"
UA = "Flipside/0.1 (Junction hackathon; contact via github)"
DB = os.getenv("NEWS_DB", "opennews.sqlite")
TTL = 6 * 3600

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("PRAGMA busy_timeout=10000")
_conn.execute("CREATE TABLE IF NOT EXISTS n (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()

# Hosts that aggregate rather than report, or that republish wholesale. Their
# links are real but they are not a source anyone should be sent to.
_SKIP_HOST = re.compile(r"(^|\.)(msn\.com|news\.google\.|finance\.yahoo\.|"
                        r"biztoc\.com|newsbreak\.com|marketscreener\.com)", re.I)


def _cached(k: str):
    row = _conn.execute("SELECT v, ts FROM n WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < TTL:
        return json.loads(row[0])
    return None


def _store(k: str, v) -> None:
    with _lock:
        _conn.execute("REPLACE INTO n VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


def _date(s: str | None) -> str | None:
    """GDELT stamps are 20261019T121500Z. Keep the day."""
    if not s or len(s) < 8:
        return None
    return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"


HN_API = "https://hn.algolia.com/api/v1/search"


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def relevant(name: str, title: str, url: str | None) -> bool:
    """Does this hit actually mention the firm?

    HN's search is fuzzy enough to return a Costa Rican computer lab for
    "Gosta Labs". A hit counts only if the name, run together, appears in
    the title or the link - which is a low bar and still excludes that.
    """
    want = _slug(name)
    if len(want) < 4:
        return False
    hay = _slug(title) + " " + _slug(url or "")
    if want in hay:
        return True
    # "Icebreaker.vc" is written "Icebreaker" in a headline. Allow the head
    # of the name when it is long enough to mean something on its own.
    head = _slug(re.split(r"[.\s]", name.strip())[0])
    return len(head) >= 6 and head in hay


def _hn(name: str, limit: int, timeout: float) -> list[dict]:
    try:
        r = httpx.get(HN_API, params={"query": name, "tags": "story",
                                      "hitsPerPage": limit * 3},
                      headers={"User-Agent": UA}, timeout=timeout)
        if r.status_code >= 400:
            return []
        hits = (r.json() or {}).get("hits") or []
    except Exception:                                 # noqa: BLE001
        return []
    out = []
    for h in hits:
        title = (h.get("title") or h.get("story_title") or "").strip()
        url = h.get("url") or h.get("story_url")
        if not title or not relevant(name, title, url):
            continue
        link = url or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        host = re.sub(r"^www\.", "", (link.split("//")[-1].split("/")[0] or "")).lower()
        out.append({"title": title[:180], "url": link, "domain": host,
                    "date": (h.get("created_at") or "")[:10],
                    "via": "Hacker News"})
        if len(out) >= limit:
            break
    return out


def search(name: str, *, limit: int = 12, timeout: float = 20.0,
           retries: int = 2, fetcher=None) -> dict:
    """{items, error}. Never raises: an empty News tab is not an exception."""
    q = (name or "").strip()
    if len(q) < 3:
        return {"items": [], "error": None}
    key = f"open:{q.lower()}:{limit}"
    hit = _cached(key)
    if hit is not None:
        return {**hit, "cached": True}

    params = {"query": f'"{q}"', "mode": "artlist", "maxrecords": str(limit * 3),
              "format": "json", "sort": "datedesc"}
    last = None
    for i in range(retries):
        try:
            if fetcher is not None:
                data = fetcher(params)
            else:
                r = httpx.get(API, params=params, headers={"User-Agent": UA},
                              timeout=timeout)
                # GDELT rate-limits anonymously and says so with a 429. It
                # clears in seconds, unlike a bad query, which never will.
                if r.status_code == 429:
                    last = "GDELT is rate-limiting; try again in a moment."
                    time.sleep(3 * (i + 1))
                    continue
                if r.status_code >= 400:
                    return {"items": [], "error": f"Open news returned {r.status_code}."}
                data = r.json()
        except ValueError:
            last = "Open news returned something that was not JSON."
            time.sleep(2)
            continue
        except Exception as e:                        # noqa: BLE001
            return {"items": [], "error": f"{type(e).__name__}: {str(e)[:90]}"}

        items, seen = [], set()
        for a in (data or {}).get("articles") or []:
            url, title = a.get("url"), (a.get("title") or "").strip()
            host = (a.get("domain") or "").lower()
            if not url or not title or _SKIP_HOST.search(host):
                continue
            k = re.sub(r"\W+", "", title.lower())[:60]
            if k in seen:
                continue
            seen.add(k)
            items.append({"title": title[:180], "url": url, "domain": host,
                          "date": _date(a.get("seendate")),
                          "language": a.get("language")})
            if len(items) >= limit:
                break
        items = [{**it, "via": "GDELT"} for it in items]
        items += [h for h in _hn(q, limit, timeout)
                  if _slug(h["title"])[:60] not in
                  {_slug(i["title"])[:60] for i in items}]
        out = {"items": items[:limit], "error": None}
        _store(key, out)
        return out

    # GDELT would not answer. Hacker News has no rate limit and is where
    # European rounds get posted, so a silent News tab is still avoidable.
    hn = _hn(q, limit, timeout)
    out = {"items": hn, "error": None if hn else last or "Open news did not answer."}
    if hn:
        _store(key, out)
    return out
