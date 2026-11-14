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


def _sentence_with(text: str, name: str) -> str | None:
    """The sentence containing this name, which is what we have to quote."""
    for part in re.split(r"(?<=[.!?])\s+|\s{2,}|\|", text):
        if name in part:
            return part.strip()
    return text.strip() if name in text else None


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
