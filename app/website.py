"""What a company says about itself on its own site.

Cala is the primary source and a registry is the authoritative one, but
neither notices that a seed company put up a pricing page last month or that
it is advertising eleven engineering roles. A company's own homepage is
public, is the company speaking in its own voice, and is the cheapest honest
signal of momentum available between funding announcements.

Scope is deliberately narrow: one GET of the homepage, a handful of links
read out of it, and nothing behind a login. No third-party profile sites and
no social networks - their terms forbid it and the data would not be the
company's own words anyway.

Every derived signal says what it is counting, because "hiring" inferred
from the word "careers" appearing once is not a fact about headcount.
"""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

UA = ("Flipside/0.1 (Junction 2026 hackathon project; "
      "contact via the repository) httpx")
DB = Path(__file__).resolve().parent.parent / "website.sqlite"
TTL = 7 * 86400

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_META = re.compile(
    r'<meta[^>]+(?:name|property)=["\'](?:description|og:description)["\'][^>]*'
    r'content=["\'](.*?)["\']', re.I | re.S)
_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)

# A link's text and its href both carry the intent; checking only one misses
# "/careers" labelled "Join us" and "Careers" pointing at a job board.
INTENT = {
    "careers": re.compile(r"career|jobs?\b|join[- ]us|we.?re hiring|open roles|vacanc", re.I),
    "pricing": re.compile(r"pricing|plans\b|buy\b|subscribe", re.I),
    "docs": re.compile(r"\bdocs?\b|documentation|developer|api\b", re.I),
    "customers": re.compile(r"customers?|case stud|success stor|testimonial", re.I),
    "investors": re.compile(r"investors?|backed by|our backers", re.I),
    "blog": re.compile(r"\bblog\b|newsroom|news\b|press\b", re.I),
}


def _db():
    con = sqlite3.connect(str(DB))
    con.execute("create table if not exists w (k text primary key, v text, ts real)")
    return con


def _cached(url: str):
    con = _db()
    try:
        row = con.execute("select v, ts from w where k=?", (url,)).fetchone()
    finally:
        con.close()
    if row and time.time() - row[1] < TTL:
        return row[0]
    return None


def _store(url: str, body: str):
    con = _db()
    try:
        con.execute("insert or replace into w values (?,?,?)", (url, body, time.time()))
        con.commit()
    finally:
        con.close()


def normalise(site: str | None) -> str | None:
    """'humanpath.si' and 'https://humanpath.si/' are the same site."""
    if not site:
        return None
    s = site.strip()
    if not s:
        return None
    if not s.startswith(("http://", "https://")):
        s = "https://" + s
    p = urlparse(s)
    if not p.netloc or "." not in p.netloc:
        return None
    return f"{p.scheme}://{p.netloc}"


def fetch(site: str | None, *, cache_only: bool = False, timeout: float = 8.0) -> str | None:
    """The homepage HTML, cached on disk for a week."""
    url = normalise(site)
    if not url:
        return None
    hit = _cached(url)
    if hit is not None or cache_only:
        return hit
    try:
        r = httpx.get(url, headers={"User-Agent": UA}, timeout=timeout,
                      follow_redirects=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            _store(url, "")
            return ""
        body = r.text[:400_000]
    except Exception:
        return None
    _store(url, body)
    return body


def _clean(s: str) -> str:
    """Strip tags, collapse whitespace, and decode entities.

    Titles arrive as "Instant Quotes &amp; Delivery", and rendering that
    literally is how a product looks unfinished.
    """
    import html as _html
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub(" ", s or ""))).strip()


def read(html: str | None, base: str | None = None) -> dict:
    """Turn homepage HTML into the few things worth saying about it."""
    if not html:
        return {"ok": False, "title": None, "tagline": None, "links": {}, "signals": []}

    title = _clean((_TITLE.search(html) or [None, ""])[1])[:140] or None
    tagline = _clean((_META.search(html) or [None, ""])[1])[:280] or None

    found: dict[str, str] = {}
    for href, text in _LINK.findall(html):
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        label = _clean(text)[:60]
        for kind, rx in INTENT.items():
            if kind in found:
                continue
            if rx.search(href) or rx.search(label):
                found[kind] = urljoin(base or "", href) if base else href

    # Stated plainly, so nobody reads "hiring" as a headcount number.
    signals = []
    if "careers" in found:
        signals.append({"k": "hiring", "text": "has a careers page",
                        "why": "a link on the homepage, not a headcount",
                        "url": found["careers"]})
    if "pricing" in found:
        signals.append({"k": "pricing", "text": "sells a priced product",
                        "why": "a pricing page is public", "url": found["pricing"]})
    if "customers" in found:
        signals.append({"k": "customers", "text": "names customers publicly",
                        "why": "case studies or logos page", "url": found["customers"]})
    if "docs" in found:
        signals.append({"k": "docs", "text": "ships a developer surface",
                        "why": "public API or docs", "url": found["docs"]})
    if "investors" in found:
        signals.append({"k": "investors", "text": "names its backers",
                        "why": "an investors page", "url": found["investors"]})
    return {"ok": True, "title": title, "tagline": tagline,
            "links": found, "signals": signals}


def profile(site: str | None, **kw) -> dict:
    """fetch + read, with the site echoed back so the UI can cite it."""
    url = normalise(site)
    html = fetch(site, **kw)
    out = read(html, base=url)
    out["site"] = url
    out["fetched"] = html is not None
    return out


# --- finding a site when no source carries one -------------------------------
# Guessing "andercore.com" is not evidence. Fetching it and finding the
# company's own name in the page is. Every candidate is verified before it is
# used, and a failure is cached too so we try each name only once.
_SLUG_DROP = re.compile(
    r"\b(gmbh|ab|oy|oyj|a/s|as|aps|ltd|limited|llc|inc|plc|sa|nv|bv|kb|ky|"
    r"holding|holdings|group|company|co)\b", re.I)
# .vc sits second because it is the most self-identifying TLD a fund can
# have: fabric.vc is Fabric Ventures and nothing else. It used to be fifth,
# which meant that for any name with more than one candidate shape the list
# was truncated before .vc was ever fetched.
TLDS = ["com", "vc", "io", "ai", "co", "net"]
CC_TLD = {"DE": "de", "FI": "fi", "SE": "se", "NO": "no", "DK": "dk",
          "NL": "nl", "FR": "fr", "ES": "es", "IT": "it", "PL": "pl",
          "EE": "ee", "LV": "lv", "LT": "lt", "GB": "co.uk", "IE": "ie",
          "CH": "ch", "AT": "at", "BE": "be", "PT": "pt", "CZ": "cz"}


MIN_SLUG = 6      # below this, a name match proves too little

# Words a fund puts at the end of its name and leaves out of its domain.
# "Coatue Management" is coatue.com; "Project A Ventures" is project-a.com.
# Dropping them produces a second, shorter stem to try and to verify against.
_TAIL_DROP = re.compile(
    r"\s*\b(ventures?|partners?|capital|management|investments?|invest|"
    r"equity|advisors?|associates|vc|fund|funds|group)\b\s*$", re.I)


# A stem made only of these proves nothing: "ventures" is in the title of
# every venture firm's homepage. "AB Ventures" loses "AB" to the legal-form
# filter and would otherwise be matched on the word "ventures" alone.
_GENERIC_ONLY = re.compile(
    r"^(ventures?|partners?|capital|management|investments?|invest|equity|"
    r"advisors?|associates|fund|funds|group|holdings?)+$", re.I)


def stems(name: str) -> list[str]:
    """The name, and the name with its fund-ish tail words removed.

    Both are long enough to be evidence on their own; anything shorter than
    MIN_SLUG is dropped, because matching "abc" in a page title proves
    nothing about whose page it is - and so is anything made only of the
    words every fund has in its name.
    """
    out, seen = [], set()
    cur = (name or "").strip()
    for _ in range(3):
        sl = slug(cur)
        if (len(sl) >= MIN_SLUG and sl not in seen
                and not _GENERIC_ONLY.match(sl)):
            seen.add(sl)
            out.append(sl)
        nxt = _TAIL_DROP.sub("", cur).strip()
        if nxt == cur:
            break
        cur = nxt
    return out


def slug(name: str) -> str:
    """'Andercore GmbH' -> 'andercore'. Legal form is not part of a domain."""
    s = _SLUG_DROP.sub(" ", name or "")
    s = re.sub(r"[^A-Za-z0-9]+", "", s)
    return s.lower()


# A parked domain carries the company's name in its title by definition, so
# the name check alone accepts it. bliq.com is "bliq.com - Tama WWW-sivu on
# myynnissa" - a page selling the domain, not the company.
_PARKED = re.compile(
    r"(?:domain|www-sivu|sivusto|dom\u00e4n|domein|domaine)[^.]{0,40}"
    r"(?:for sale|is for sale|on myynniss|till salu|te koop|zu verkaufen|\u00e0 vendre)"
    r"|buy this domain|this domain (?:is|may be) for sale|parked (?:free )?(?:at|by)"
    r"|sedoparking|afternic|dan\.com|hugedomains|undeveloped\.com"
    r"|t\u00e4m\u00e4 www-sivu on myynniss\u00e4"
    r"|\bdomain (?:name )?(?:parking|broker)\b", re.I)


def is_parked(html: str) -> bool:
    """A page selling the domain is not the company's homepage."""
    if not html:
        return True
    head = _clean((_TITLE.search(html) or [None, ""])[1])
    body = _clean(html)[:4000]
    return bool(_PARKED.search(head) or _PARKED.search(body))


def _mentions(html: str, name: str) -> str | None:
    """Does this page claim to be this company, and on what strength?

    Compares the page title and og:site_name against the name with spacing
    and legal form removed, so "Andercore" matches "ANDERCORE | Solar".

    Returns "full" when the whole name is in the title, "stem" when only the
    distinctive head of it is - coatue.com says "Coatue", not "Coatue
    Management". A stem match is weaker evidence and is labelled, not hidden:
    it is good enough to hang a logo on and not good enough to assert an
    address from.
    """
    want = stems(name)
    if not want:
        return None
    head = (_TITLE.search(html or "") or [None, ""])[1]
    og = re.search(r'property=["\']og:site_name["\'][^>]*content=["\'](.*?)["\']',
                   html or "", re.I)
    hay = slug(_clean(head) + " " + (og.group(1) if og else ""))
    for i, w in enumerate(want):
        if w in hay:
            return "full" if i == 0 else "stem"
    return None


def candidates(name: str, cc: str | None = None) -> list[str]:
    """Domains worth fetching for this name, most likely first.

    Three shapes, because funds use all three: the whole name run together,
    the name with its tail words dropped, and the words hyphenated. Every one
    of them is still fetched and checked before it is believed.
    """
    bases = list(stems(name))
    words = [w for w in re.split(r"[^A-Za-z0-9]+", name or "") if w]
    if len(words) > 1:
        hyph = "-".join(w.lower() for w in words)
        hyph_short = "-".join(w.lower() for w in
                              re.split(r"[^A-Za-z0-9]+", _TAIL_DROP.sub("", name or "")) if w)
        for h in (hyph_short, hyph):
            if len(h.replace("-", "")) >= MIN_SLUG and h not in bases:
                bases.append(h)
    if not bases:
        return []
    tlds = list(TLDS)
    if cc and CC_TLD.get(cc.upper()):
        tlds.insert(0, CC_TLD[cc.upper()])
    seen, out = set(), []
    # Breadth first: the .com of every shape before the .io of any of them.
    for t in tlds:
        for b in bases:
            d = f"{b}.{t}"
            if d not in seen:
                seen.add(d)
                out.append(d)
    # Eight was too few once a name produced three shapes: the whole list
    # was spent on .com and .vc before anything else was tried.
    return out[:14]


def discover(name: str, cc: str | None = None, *, fetcher=None,
             cache_only: bool = False, use_cache: bool = True) -> dict | None:
    """A verified homepage for a company we have no website for.

    Returns {site, domain, title, verified} or None. `verified` is always
    True - an unverified candidate is never returned, because a wrong logo
    and a wrong description are worse than none.
    """
    key = f"discover:{slug(name)}:{(cc or '').upper()}"
    if use_cache:
        hit = _cached(key)
        if hit is not None:
            return json.loads(hit) if hit else None
    if cache_only:
        return None

    get = fetcher or (lambda d: fetch(d, timeout=6))
    for dom in candidates(name, cc):
        try:
            html = get(dom)
        except Exception:
            continue
        if not html or is_parked(html):
            continue
        how = _mentions(html, name)
        if not how:
            continue
        found = {"site": normalise(dom), "domain": dom,
                 "title": _clean((_TITLE.search(html) or [None, ""])[1])[:140],
                 # "full" means the page title carries the whole name; "stem"
                 # means it carries only the distinctive head of it. Both were
                 # fetched and read, but they are not equally strong and the
                 # caller is told which it got.
                 "verified": True, "match": how}
        if use_cache:
            _store(key, json.dumps(found))
        return found
    if use_cache:
        _store(key, "")    # remember the miss; do not retry every page load
    return None
