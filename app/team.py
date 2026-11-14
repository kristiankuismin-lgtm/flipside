"""People from a company's own team page, and only what it literally says.

Cala carries relationships for one of the 227 people we hold, so the founder
signal has almost nothing to read. The web has the rest - but "found on the
web" is not evidence, and a name scraped off a profile aggregator is someone
else's data about a person.

The rule borrowed from BlueWatch: a claim is kept only when its quote is
literally on the page, and the page is the organisation's own. A company
saying "Jane Smith, CTO" on its own team page is the company speaking about
itself. Anything we cannot quote back is dropped, not guessed.

Boundaries, kept deliberately narrow:
  - the company's own domain only, never an aggregator or a social network
  - names and roles only; e-mail addresses and phone numbers are discarded
    even when the page shows them
  - every person carries the URL and the exact sentence they came from
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from . import website as W

# Where companies put their people.
TEAM_HINTS = re.compile(
    r"/(?:team|about|about-us|people|leadership|management|founders|who-we-are|"
    r"meet-the-team|our-team|company)\b", re.I)
TEAM_TEXT = re.compile(
    r"\b(?:team|about us|our people|leadership|management|founders|who we are)\b", re.I)

# A role worth recording. Ordered: the first match wins, so "co-founder and
# CEO" records the founder claim rather than the operating one.
ROLES = [
    ("founder", re.compile(r"\b(?:co-?founder|founder|co-?founded)\b", re.I)),
    ("ceo", re.compile(r"\b(?:chief executive(?: officer)?|CEO)\b", re.I)),
    ("cto", re.compile(r"\b(?:chief technolog\w+(?: officer)?|CTO)\b", re.I)),
    ("coo", re.compile(r"\b(?:chief operating(?: officer)?|COO)\b", re.I)),
    ("cfo", re.compile(r"\b(?:chief financial(?: officer)?|CFO)\b", re.I)),
    ("chair", re.compile(r"\b(?:chair(?:man|woman|person)?|board member)\b", re.I)),
    ("head", re.compile(r"\b(?:head of|VP |vice president|director of)\b", re.I)),
]

# Two or three capitalised words, allowing Nordic and hyphenated names. Not a
# person detector - a candidate generator the quote check then has to accept.
NAME = re.compile(
    r"\b([A-ZÅÄÖØÆÉÈÜ][\w'’\-]{1,20}(?:\s+[A-ZÅÄÖØÆÉÈÜ][\w'’\-]{1,20}){1,2})\b")

# Things shaped like a name that are not one.
NOT_A_NAME = re.compile(
    r"\b(?:privacy|cookie|terms|contact|read more|learn more|our team|the team|"
    r"get in touch|all rights|sign up|log in|book a|case stud|united states|"
    r"united kingdom|new york|san francisco|machine learning|artificial "
    r"intelligence|customer success|product manager)\b", re.I)

CONTACT = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s()-]{7,}")

# Title words are capitalised too, so "Jane Smith Co-founder" comes back as
# one candidate. Trim them off the end rather than widening the name pattern,
# which would start swallowing sentences.
TITLE_WORD = re.compile(
    r"^(?:co-?founder|founder|ceo|cto|coo|cfo|cmo|cpo|chair(?:man|woman|person)?|"
    r"head|vp|president|director|partner|lead|board|member|officer|chief|"
    r"advisor|adviser|advisory|special|general|managing|senior|junior|"
    r"founders|cofounder|cofounders|wellbeing|portfolio|"
    r"associate|principal|analyst|operating|venture|investment|"
    # Sentence furniture that is capitalised on a team page: "Meet Anni Harju",
    # "Introducing Cristina Koehn", "Jan Goetz ... IQM Read more".
    r"meet|introducing|welcome|welcoming|read|more|new|join|joins|joining|"
    r"hello|hi|say|see|view|profile|team|about|contact|"
    r"and|of|the|at|our|is|was|as|to|for)$", re.I)

# A fragment of an organisation's name is not a person. These words never
# appear in one.
ORGWORD = re.compile(
    r"\b(?:ventures?|capital|partners?|fund|invest\w*|equity|holdings?|group|"
    r"compan(?:y|ies)|corporation|technolog\w+|labs?|systems?|solutions?|"
    r"industries|institute|foundation|university|collective|studio|agency|"
    r"oy|oyj|ab|a/s|aps|gmbh|ltd|llc|inc|plc)\b", re.I)


def _trim_name(cand: str) -> str | None:
    """A candidate with its title words removed, or None if nothing is left."""
    words = cand.split()
    while words and TITLE_WORD.match(words[-1]):
        words.pop()
    while words and TITLE_WORD.match(words[0]):
        words.pop(0)
    name = " ".join(words)
    if not name or ORGWORD.search(name):
        return None
    # An apostrophe in the middle is a possessive ("Voima Ventures' New"),
    # not a surname like O'Brien, which keeps its apostrophe inside a word.
    if re.search(r"[\u2019']\s", name):
        return None
    return name if len(words) >= 2 else None

MAX_PEOPLE = 24


def team_url(html: str | None, base: str | None) -> str | None:
    """The company's own team page, from links on its homepage."""
    if not html or not base:
        return None
    host = urlparse(base).netloc.lower()
    best = None
    for href, text in W._LINK.findall(html):
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base, href)
        if urlparse(absolute).netloc.lower() != host:
            continue              # the company's own domain, nothing else
        label = W._clean(text)
        if TEAM_HINTS.search(urlparse(absolute).path) or TEAM_TEXT.search(label):
            # Prefer an explicit /team over a general /about.
            score = 0 if re.search(r"/(?:team|people|leadership|founders)", absolute, re.I) else 1
            if best is None or score < best[0]:
                best = (score, absolute)
    return best[1] if best else None


def _blocks(html: str) -> list[str]:
    """Rough per-person chunks. Team pages repeat one card per person."""
    text = re.sub(r"<(?:script|style)[^>]*>.*?</(?:script|style)>", " ", html or "",
                  flags=re.S | re.I)
    # Split on block boundaries, keeping each card's text together.
    parts = re.split(r"</(?:li|article|section|div|td|tr|figure|p)>", text, flags=re.I)
    return [W._clean(p) for p in parts]


def people(html: str | None, page_url: str | None) -> list[dict]:
    """Named people with a role, each carrying the sentence that says so.

    A person is kept only when one chunk of the page contains both the name
    and the role word - so a name in a footer and a role in a heading never
    combine into a claim the page never made.
    """
    if not html:
        return []
    out, seen = [], set()
    for block in _blocks(html):
        if not block or len(block) > 600:
            continue
        role = next((label for label, rx in ROLES if rx.search(block)), None)
        if not role:
            continue
        for raw in NAME.findall(block):
            cand = _trim_name(raw)
            if not cand or NOT_A_NAME.search(cand) or cand.lower() in seen:
                continue
            if _is_label(block, cand):
                continue
            # The quote check: the claim must be literally on the page, as
            # one sentence, with the name and the role together in it.
            quote = _sentence_with(block, cand)
            if not quote or not any(rx.search(quote) for label, rx in ROLES if label == role):
                continue
            seen.add(cand.lower())
            out.append({"name": cand, "role": role,
                        "quote": CONTACT.sub("", quote).strip()[:220],
                        "source": page_url})
            if len(out) >= MAX_PEOPLE:
                return out
    return out


# "Coherence Quantum CEO: Aashish Sah" is a company label, a role and then a
# person. Taking the first capitalised run before the role word reads the
# company as the person, which is how a portfolio listing becomes 24 staff.
LABELLED = re.compile(r"\b([A-Z][\w'\u2019\-]*(?:\s+[A-Z][\w'\u2019\-]*){0,2})\s*:\s*$")


def _is_label(block: str, name: str) -> bool:
    """Is this candidate a heading for somebody else?

    The portfolio-listing shape is "Coherence Quantum CEO: Aashish Sah" - a
    company, a role, then the person. The tell is a role word sitting between
    the candidate and the colon.

    Not every name before a colon is a label: "Meet Anni Harju: Voima
    Ventures' New Chief Financial Officer" puts the person first and the
    title after, and an earlier version of this rule threw her away.
    """
    i = block.find(name)
    if i < 0:
        return False
    gap = block[i + len(name):i + len(name) + 26]
    m = re.match(r"([^:]{0,24}):", gap)
    if not m:
        return False
    return any(rx.search(m.group(1)) for _label, rx in ROLES)


def _sentence_with(text: str, name: str) -> str | None:
    """The sentence containing this name, which is what we have to quote."""
    for part in re.split(r"(?<=[.!?])\s+|\s{2,}|\|", text):
        if name in part:
            return part.strip()
    return text.strip() if name in text else None


# "Alex Kendall Co-founder and CEO, Wayve" on balderton.com is a portfolio
# founder, not a Balderton partner. A call list that cannot tell the
# difference has you phoning Wayve's CEO about a term sheet.
_AT_COMPANY = re.compile(
    r"\b(?:at|of|,)\s+((?:[A-Z][\w&.'\u2019-]*)(?:\s+[A-Z][\w&.'\u2019-]*){0,3})\s*$")
_ROLE_THEN_COMPANY = re.compile(
    r"(?:founder|ceo|cto|coo|chief\s+\w+)\b[^,]{0,20}[,.]?\s+(?:at\s+)?"
    r"((?:[A-Z][\w&.'\u2019-]*)(?:\s+[A-Z][\w&.'\u2019-]*){0,3})", re.I)


def affiliation(quote: str, firm: str | None) -> str | None:
    """The organisation a quote attaches this person to, if not the firm.

    Returns the other company's name, or None when the quote says nothing
    about one - which is the normal case for a real team page.
    """
    q = (quote or "").strip()
    if not q:
        return None
    firm_key = re.sub(r"[^a-z0-9]", "", (firm or "").lower())
    for rx in (_ROLE_THEN_COMPANY, _AT_COMPANY):
        m = rx.search(q)
        if not m:
            continue
        other = _trim_name(m.group(1)) or m.group(1)
        key = re.sub(r"[^a-z0-9]", "", other.lower())
        if len(key) < 3 or (firm_key and (key in firm_key or firm_key in key)):
            continue
        if TITLE_WORD.match(other.split()[0] if other.split() else ""):
            continue
        return other.strip()
    return None


def read(site: str | None, **kw) -> dict:
    """Homepage -> team page -> people. Everything cached by website.fetch."""
    home = W.fetch(site, **kw)
    base = W.normalise(site)
    if not home:
        return {"ok": False, "site": base, "team_url": None, "people": [],
                "why": "the homepage did not answer"}
    url = team_url(home, base)
    if not url:
        return {"ok": True, "site": base, "team_url": None, "people": [],
                "why": "no team or about page linked from the homepage"}
    page = W.fetch(url, **kw)
    if not page:
        return {"ok": True, "site": base, "team_url": url, "people": [],
                "why": "the team page did not answer"}
    found = people(page, url)
    return {"ok": True, "site": base, "team_url": url, "people": found,
            "why": None if found else "no name and role appeared in the same sentence"}


# --- reading every source a company actually offers --------------------------
# Checked before building: of five VC sites sampled, none published JSON-LD
# Person or schema.org microdata, and none kept people in an embedded JSON
# payload. The people are in plain HTML. Both structured readers are kept
# anyway because they are cheap and correct where a site does have them, and
# the result says which reader produced each person.
import json as _json

MAX_PAGES = 5
MAX_BIOS = 6

_JSONLD = re.compile(
    r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_MICRO = re.compile(
    r'itemtype="[^"]*schema\.org/Person"(.*?)(?=itemtype=|</(?:div|li|article)>)',
    re.S | re.I)
_ITEMPROP = re.compile(r'itemprop="(name|jobTitle)"[^>]*>([^<]{2,80})<', re.I)


def candidate_pages(html: str | None, base: str | None) -> list[str]:
    """Every page on the company's own domain that might name people."""
    if not html or not base:
        return []
    host = urlparse(base).netloc.lower()
    hits: list[tuple[int, str]] = []
    seen = set()
    for href, text in W._LINK.findall(html):
        if href.startswith(("mailto:", "tel:", "javascript:", "#")):
            continue
        absolute = urljoin(base, href).split("#")[0].rstrip("/")
        if urlparse(absolute).netloc.lower() != host or absolute in seen:
            continue
        path = urlparse(absolute).path
        label = W._clean(text)
        if not (TEAM_HINTS.search(path) or TEAM_TEXT.search(label)):
            continue
        seen.add(absolute)
        # A dedicated people page before a general company page.
        rank = 0 if re.search(r"/(?:team|people|leadership|founders|management)",
                              path, re.I) else 1
        hits.append((rank, absolute))
    hits.sort()
    return [u for _, u in hits][:MAX_PAGES]


def _walk_jsonld(node, out: list[dict], url: str | None):
    if isinstance(node, list):
        for x in node:
            _walk_jsonld(x, out, url)
        return
    if not isinstance(node, dict):
        return
    types = node.get("@type")
    types = types if isinstance(types, list) else [types]
    if any(str(t).lower() == "person" for t in types if t):
        name = node.get("name")
        if isinstance(name, str) and len(name.split()) >= 2:
            role = node.get("jobTitle") or node.get("description") or ""
            out.append({"name": name.strip(),
                        "role": _role_of(str(role)) or "person",
                        "quote": str(role)[:200].strip() or name.strip(),
                        "source": url, "via": "json-ld"})
    for v in node.values():
        if isinstance(v, (dict, list)):
            _walk_jsonld(v, out, url)


def _role_of(text: str) -> str | None:
    return next((label for label, rx in ROLES if rx.search(text or "")), None)


def from_jsonld(html: str | None, url: str | None) -> list[dict]:
    """People a site publishes as structured data. Exact when present."""
    out: list[dict] = []
    for blob in _JSONLD.findall(html or ""):
        try:
            _walk_jsonld(_json.loads(blob), out, url)
        except (ValueError, TypeError):
            continue
    return out


def from_microdata(html: str | None, url: str | None) -> list[dict]:
    """schema.org/Person marked up inline."""
    out = []
    for chunk in _MICRO.findall(html or ""):
        props = dict((k.lower(), W._clean(v)) for k, v in _ITEMPROP.findall(chunk))
        name = props.get("name")
        if not name or len(name.split()) < 2:
            continue
        title = props.get("jobtitle", "")
        out.append({"name": name, "role": _role_of(title) or "person",
                    "quote": (f"{name} — {title}" if title else name)[:200],
                    "source": url, "via": "microdata"})
    return out


def _merge(groups: list[list[dict]]) -> list[dict]:
    """One row per person, keeping the reading with the most to say."""
    best: dict[str, dict] = {}
    for group in groups:
        for p in group:
            trimmed = _trim_name(p["name"]) or p["name"]
            key = re.sub(r"[^a-z]", "", trimmed.lower())
            if len(key) < 5:
                continue
            p = {**p, "name": trimmed}
            cur = best.get(key)
            if cur is None:
                best[key] = p
                continue
            # A named role beats "person"; a longer quote beats a shorter one.
            better = (p["role"] != "person", len(p.get("quote") or ""))
            worse = (cur["role"] != "person", len(cur.get("quote") or ""))
            if better > worse:
                best[key] = p
    return sorted(best.values(), key=lambda p: (p["role"] == "person", p["name"]))


def read_deep(site: str | None, *, follow_bios: bool = True, **kw) -> dict:
    """Every page on the company's own site that names people.

    Reports what each page yielded and which reader produced each person, so
    an empty result is attributable rather than just empty.
    """
    base = W.normalise(site)
    home = W.fetch(site, **kw)
    if not home:
        return {"ok": False, "site": base, "pages": [], "people": [],
                "why": "the homepage did not answer"}

    urls = candidate_pages(home, base) or []
    pages, groups = [], []
    # The homepage itself sometimes names the founders.
    for url, html in [(base, home)] + [(u, W.fetch(u, **kw)) for u in urls]:
        if not html:
            pages.append({"url": url, "people": 0, "why": "did not answer"})
            continue
        found = _merge([from_jsonld(html, url), from_microdata(html, url),
                        [{**p, "via": "page text"} for p in people(html, url)]])
        groups.append(found)
        pages.append({"url": url, "people": len(found),
                      "why": None if found else "no name and role in one sentence"})

    merged = _merge(groups)
    firm = urlparse(base or "").netloc.split(".")[0] if base else None
    for person in merged:
        other = affiliation(person.get("quote"), firm)
        if other:
            # Named with another company: they are that company's, not this
            # firm's. Kept and labelled rather than dropped, because on a
            # VC site this is the portfolio and that is worth seeing.
            person["affiliation"] = other
            person["is_staff"] = False
        else:
            person["is_staff"] = True

    # Follow a few person pages for the sentence a listing never has room for.
    if follow_bios and merged:
        host = urlparse(base).netloc.lower()
        for p in merged[:MAX_BIOS]:
            link = _bio_link(home, urls, p["name"], base, host, **kw)
            if link:
                p["bio_url"] = link
    return {"ok": True, "site": base, "pages": pages, "people": merged,
            "why": None if merged else "no page on this site names a person with a role"}


def _bio_link(home, urls, name, base, host, **kw):
    """A dedicated page for this person, if the site has one."""
    slug = re.sub(r"[^a-z]+", "-", name.lower()).strip("-")
    if len(slug) < 5:
        return None
    for src in [home] + [W.fetch(u, cache_only=True, **kw) for u in urls]:
        for href, _text in W._LINK.findall(src or ""):
            absolute = urljoin(base, href).split("#")[0]
            if urlparse(absolute).netloc.lower() != host:
                continue
            if slug in absolute.lower():
                return absolute
    return None
