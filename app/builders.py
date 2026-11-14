"""People shipping things who have not founded a company yet.

The scout list ranks people who have already founded, which is the strongest
predictor there is and also the latest one. By the time someone has a
company, a seed round and a LinkedIn title, every fund can see them. The
cohort an investor actually wants to find first is the one before that: the
engineer at a job, the student between terms, the person who keeps putting
things on the internet at the weekend.

Cala does not hold them. It holds investors and known founders - 134 people
with edges, 55 of whom have already founded. So this reads a different
source.

Show HN is the one that fits, and it fits for a reason worth stating: a Show
HN post is somebody deliberately publishing a thing they built, to an
audience, under a handle they chose. That is a public act of showing work.
It is categorically different from reading someone's LinkedIn, their mail,
or a private profile - which this does not do, and will not.

What we can honestly say about a handle:

    it shipped four things in six months
    the last one was two weeks ago
    this is what they were
    one of them is a GitHub repository

What we cannot say is who they are. An HN handle is a pseudonym. The list
names the handle and what it shipped, and leaves identifying the person to
the investor who decides it is worth their time - which is the right place
for that decision to sit.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
from datetime import date, datetime, timezone

import httpx

API = "https://hn.algolia.com/api/v1/search_by_date"
UA = "Flipside/0.1 (Junction hackathon; github.com/kristiankuismin-lgtm)"
DB = os.getenv("BUILDERS_DB", "builders.sqlite")
TTL = 12 * 3600

WINDOW_DAYS = 180        # half a year: long enough to see a pattern
PAGE = 100               # Algolia's maximum per request

# Scoring. A pattern of shipping beats one post that did well, and the
# weights have to actually deliver that: the first version said it in a
# comment and then let a single 736-point post tie someone who had shipped
# twice. The thing being looked for is the habit. One viral weekend is a
# good weekend.
W_SHIPPED = 44           # more than one thing, in the window
W_RECENT = 18            # still doing it
W_RECEPTION = 12         # other builders thought it was worth something
W_CODE = 10              # the work is public and readable
SHIPPED_FULL = 4
RECEPTION_FULL = 120     # points above which more stops counting

_GITHUB = re.compile(r"github\.com/([A-Za-z0-9-]+)/([A-Za-z0-9._-]+)", re.I)
_SHOW = re.compile(r"^\s*show\s+hn\s*:\s*", re.I)

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("PRAGMA busy_timeout=10000")
_conn.execute("CREATE TABLE IF NOT EXISTS b (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()


def _cached(k):
    row = _conn.execute("SELECT v, ts FROM b WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < TTL:
        return json.loads(row[0])
    return None


def _store(k, v):
    with _lock:
        _conn.execute("REPLACE INTO b VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


def fetch(*, days: int = WINDOW_DAYS, pages: int = 3, fetcher=None) -> list[dict]:
    """Show HN posts in the window, newest first. Never raises."""
    key = f"showhn:{days}:{pages}"
    hit = _cached(key)
    if hit is not None:
        return hit
    since = int(time.time()) - days * 86400
    out: list[dict] = []
    for page in range(pages):
        params = {"tags": "show_hn", "hitsPerPage": PAGE, "page": page,
                  "numericFilters": f"created_at_i>{since}"}
        try:
            if fetcher is not None:
                data = fetcher(params)
            else:
                r = httpx.get(API, params=params, headers={"User-Agent": UA},
                              timeout=25)
                if r.status_code >= 400:
                    break
                data = r.json()
        except Exception:                             # noqa: BLE001
            break
        hits = (data or {}).get("hits") or []
        if not hits:
            break
        out.extend(hits)
        if len(hits) < PAGE:
            break
    _store(key, out)
    return out


def _title(h) -> str:
    return _SHOW.sub("", (h.get("title") or "").strip())


def _when(h) -> str | None:
    ts = h.get("created_at_i")
    if not ts:
        return (h.get("created_at") or "")[:10] or None
    return datetime.fromtimestamp(ts, timezone.utc).date().isoformat()


def _months_ago(iso: str | None, today: date) -> float | None:
    if not iso:
        return None
    try:
        d = date.fromisoformat(iso[:10])
    except ValueError:
        return None
    if d > today:
        return None
    return round((today - d).days / 30.4, 1)


def group(posts, *, today: date | None = None) -> list[dict]:
    """One row per handle, with everything it has shown."""
    today = today or date.today()
    by: dict[str, dict] = {}
    for h in posts or []:
        who = (h.get("author") or "").strip()
        title = _title(h)
        if not who or not title:
            continue
        row = by.setdefault(who, {"handle": who, "shipped": [], "github": None})
        url = h.get("url") or ""
        m = _GITHUB.search(url)
        if m and not row["github"]:
            row["github"] = m.group(1)
        row["shipped"].append({
            "what": title[:160], "url": url or None,
            "date": _when(h), "points": h.get("points") or 0,
            "comments": h.get("num_comments") or 0,
            "hn": f"https://news.ycombinator.com/item?id={h.get('objectID')}",
        })

    rows = []
    for row in by.values():
        row["shipped"].sort(key=lambda s: str(s.get("date") or ""), reverse=True)
        best = max(row["shipped"], key=lambda s: s["points"])
        last = row["shipped"][0]
        rows.append({**row,
                     "count": len(row["shipped"]),
                     "best_points": best["points"],
                     "best": best["what"],
                     "last_date": last["date"],
                     "months_since": _months_ago(last["date"], today)})
    return rows


def score(row: dict) -> tuple[float, list[str]]:
    """Points, and the reason for each. Nothing is inferred from absence."""
    pts, why = 0.0, []
    n = row.get("count") or 0
    if n > 1:
        pts += W_SHIPPED * min(n, SHIPPED_FULL) / SHIPPED_FULL
        why.append(f"shipped {n} things")
    elif n == 1:
        why.append("shipped one thing")

    m = row.get("months_since")
    if m is not None:
        # Still going matters more than ever having gone.
        pts += W_RECENT * max(0.0, 1 - m / 6) if m < 6 else 0
        why.append("last one this month" if m < 1 else f"last one {m:g} months ago")

    p = row.get("best_points") or 0
    if p:
        pts += W_RECEPTION * min(p, RECEPTION_FULL) / RECEPTION_FULL
        if p >= 20:
            why.append(f"best got {p} points")

    if row.get("github"):
        pts += W_CODE
        why.append("the code is public")
    return round(pts, 1), why


def rank(*, days: int = WINDOW_DAYS, pages: int = 3, limit: int = 40,
         known=None, today: date | None = None, fetcher=None) -> dict:
    """The cohort, ranked, with an honest account of what it is.

    `known(handle, shipped_titles) -> bool` lets the caller drop anyone it
    can already see as a founder: the point of this list is the people who
    are not one yet.
    """
    posts = fetch(days=days, pages=pages, fetcher=fetcher)
    rows = group(posts, today=today)
    kept, dropped = [], 0
    for r in rows:
        if known and known(r["handle"], [s["what"] for s in r["shipped"]]):
            dropped += 1
            continue
        r["score"], r["why"] = score(r)
        kept.append(r)
    kept.sort(key=lambda r: (-r["score"], -(r["count"] or 0), r["handle"]))
    return {
        "builders": kept[:limit],
        "coverage": {
            "posts_read": len(posts),
            "handles": len(rows),
            "already_known": dropped,
            "window_days": days,
        },
    }
