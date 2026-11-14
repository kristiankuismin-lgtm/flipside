"""GitHub as a founder signal.

The most predictive public signal for a technical founder is what they have
actually built, and GitHub is the one source for that with a real public API
and no terms problem - unlike the alternatives, which is why this is the only
external profile source here.

Unauthenticated access is 60 calls an hour per IP, which a single demo can
exhaust. Set GITHUB_TOKEN in .env for 5000/hour. Without one this degrades to
"unknown" rather than to zero.
"""
import os, sqlite3, json, threading, time

import httpx

API = "https://api.github.com"
TOKEN = os.getenv("GITHUB_TOKEN", "")
UA = "Flipside/1.0 (Junction 2026)"
DB = os.getenv("GITHUB_DB", "github.sqlite")

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS g (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()


class RateLimited(RuntimeError):
    pass


def _headers():
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if TOKEN:
        h["Authorization"] = f"Bearer {TOKEN}"
    return h


def _cached(k):
    row = _conn.execute("SELECT v FROM g WHERE k=?", (k,)).fetchone()
    return json.loads(row[0]) if row else None


def _store(k, v):
    with _lock:
        _conn.execute("REPLACE INTO g VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


def _get(path, *, cache_only=False, timeout=10.0):
    hit = _cached(path)
    if hit is not None:
        return hit
    if cache_only:
        return None
    try:
        r = httpx.get(API + path, headers=_headers(), timeout=timeout)
    except httpx.HTTPError:
        return None
    if r.status_code == 403 and "rate limit" in r.text.lower():
        raise RateLimited("GitHub rate limit — set GITHUB_TOKEN for 5000/hour")
    if r.status_code != 200:
        _store(path, {})
        return None
    v = r.json()
    _store(path, v)
    return v


def find_user(name: str, hint: str | None = None, **kw):
    """Best-guess GitHub login for a person. Returns None when unsure."""
    q = name.strip()
    if len(q) < 3:
        return None
    d = _get(f"/search/users?q={httpx.QueryParams({'q': q})['q']}&per_page=5", **kw) or {}
    items = d.get("items") or []
    if not items:
        return None
    # A single clear hit is usable; several same-name accounts are not, so we
    # say unknown rather than pick one and attribute someone else's work.
    if len(items) > 1 and not hint:
        return None
    return items[0].get("login")


def profile(login: str, **kw) -> dict | None:
    u = _get(f"/users/{login}", **kw)
    if not u or not u.get("login"):
        return None
    repos = _get(f"/users/{login}/repos?sort=pushed&per_page=100", **kw) or []
    own = [r for r in repos if not r.get("fork")]
    stars = sum(r.get("stargazers_count", 0) for r in own)
    langs = {}
    for r in own:
        if r.get("language"):
            langs[r["language"]] = langs.get(r["language"], 0) + 1
    top = sorted(own, key=lambda r: -r.get("stargazers_count", 0))[:5]
    year = int(str(u.get("created_at", "2020"))[:4])
    return {
        "login": u["login"], "name": u.get("name"), "bio": u.get("bio"),
        "company": u.get("company"), "url": u.get("html_url"),
        "followers": u.get("followers", 0), "public_repos": u.get("public_repos", 0),
        "own_repos": len(own), "stars": stars, "since": year,
        "languages": sorted(langs.items(), key=lambda kv: -kv[1])[:5],
        "top_repos": [{"name": r["name"], "stars": r.get("stargazers_count", 0),
                       "lang": r.get("language"), "url": r.get("html_url"),
                       "description": (r.get("description") or "")[:120]} for r in top],
    }


def signal(p: dict | None) -> dict:
    """Turn a profile into a bounded 0-1 builder signal, or unknown."""
    if not p:
        return {"value": None, "label": "unknown", "why": ["no GitHub account matched"]}
    why = []
    stars = p["stars"]
    repos = p["own_repos"]
    yrs = max(0, time.gmtime().tm_year - p["since"])

    # Logarithmic: the gap between 0 and 50 stars matters, 5000 vs 10000 does not.
    import math
    s_stars = min(1.0, math.log10(stars + 1) / 3.0)
    s_repos = min(1.0, repos / 25.0)
    s_years = min(1.0, yrs / 8.0)
    v = round(0.5 * s_stars + 0.3 * s_repos + 0.2 * s_years, 3)

    if stars:
        why.append(f"{stars} stars across {repos} own repositories")
    elif repos:
        why.append(f"{repos} own repositories, no stars yet")
    if yrs:
        why.append(f"active on GitHub for {yrs} years")
    if p["languages"]:
        why.append("mostly " + ", ".join(k for k, _ in p["languages"][:2]))
    return {"value": v, "label": "strong" if v >= .6 else "some" if v >= .25 else "light",
            "why": why}
