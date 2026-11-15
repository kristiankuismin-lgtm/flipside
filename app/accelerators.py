"""Accelerator batches, and which of them no database has yet.

An accelerator batch is the earliest public list of companies that exist.
The company is weeks old, usually pre-seed, and by the time it reaches an
investor database it has already raised. So the interesting column is not
the batch - everyone can read the batch - it is which rows are NOT in Cala.
A company on a demo day list and absent from the graph is one an investor
can reach before the graph catches up, and that difference is computed here
rather than asserted.

Batch pages are published to be read: that is what a demo day list is for.
The ones used are static HTML, because the accelerators' own directories
are single-page apps that return an empty document to any fetch - measured,
not assumed: ycombinator.com/companies and joinef.com/portfolio both
scraped to zero characters.

Europe and the United States both matter here and the row carries whichever
the page gives, unresolved rather than guessed.
"""
from __future__ import annotations

import json
import re

from . import context_dev as cx, norm

# Static, parseable batch lists. yclist is a community mirror of YC's own
# directory and renders a markdown table; the accelerators' own sites do not.
SOURCES: dict[str, dict] = {
    "yc": {
        "name": "Y Combinator", "parser": "table",
        "pages": ["https://yclist.com/{b}/"],
        "batches": ["s26", "w26", "f25", "s25"],
    },
    # vcbacked publishes one directory per investor, 24 companies a page,
    # in a consistent URL shape - which is why three accelerators that have
    # no list of their own are reachable at all.
    "techstars": {
        "name": "Techstars", "parser": "links",
        "company_url": r"vcbacked\.co/company/",
        "pages": ["https://www.vcbacked.co/directory/investors/techstars",
                  "https://www.vcbacked.co/directory/investors/techstars/page/2",
                  "https://www.vcbacked.co/directory/investors/techstars/page/3"],
    },
    "ef": {
        "name": "Entrepreneur First", "parser": "links",
        "company_url": r"vcbacked\.co/company/",
        "pages": ["https://www.vcbacked.co/directory/investors/entrepreneurs-first",
                  "https://www.vcbacked.co/directory/investors/entrepreneurs-first/page/2"],
    },
    "antler": {
        "name": "Antler", "parser": "links",
        "company_url": r"vcbacked\.co/company/",
        "pages": ["https://www.vcbacked.co/directory/investors/antler",
                  "https://www.vcbacked.co/directory/investors/antler/page/2"],
    },
    "speedrun": {
        "name": "a16z speedrun", "parser": "links",
        "company_url": r"recentfunding\.com/companies/",
        "pages": ["https://recentfunding.com/accelerators/speedrun/"],
    },
}

# Links that are site furniture rather than a company.
_CHROME = re.compile(
    r"^(home|directory|investors?|search|jobs|digest|log ?in|sign ?up|sign ?in|"
    r"get started|pricing|api|blog|about|contact|privacy|terms|menu|skip to|"
    r"companies|team|next|previous|page \d+|\d+|more|view all|visit|"
    r"recently raised|startups|stealth|accelerators|funding data|money flow)",
    re.I)

# A batch list is mostly chrome. A row is a row only if it names something
# and says something about it.
_ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")


def _key(name: str) -> str:
    """The identity of a company name for matching, spaces included.

    norm.name lowercases and drops legal suffixes but keeps internal spaces,
    so "6thSense" and "6th Sense" survived as two companies - and, worse, a
    batch row written one way would not have matched its own Cala record
    written the other. Dropping everything that is not a letter or a digit
    collapses both. It also empties a name that is only a legal suffix, so
    the raw name is the fallback, the same guard the rest of this codebase
    learned to use.
    """
    k = re.sub(r"[^a-z0-9]+", "", (norm.name(name) or "").lower())
    return k or re.sub(r"[^a-z0-9]+", "", (name or "").lower()) or (name or "")


def _markdown(payload) -> str:
    """Unwrap the scrape envelope: {"requested":..,"success":..,"data":"..."}."""
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "markdown", "content"):
            v = payload.get(k)
            if isinstance(v, str):
                return v
            if isinstance(v, dict):
                inner = _markdown(v)
                if inner:
                    return inner
    return ""


def _link(cell: str) -> tuple[str, str | None]:
    """A markdown cell -> (text, href)."""
    m = re.search(r"\[([^\]]*)\]\(([^)]+)\)", cell)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return re.sub(r"[*_`]", "", cell).strip(), None


def parse(md: str, *, batch: str, accelerator: str) -> list[dict]:
    """A markdown table of companies -> rows, whatever the column order."""
    out, header = [], None
    for line in md.splitlines():
        m = _ROW.match(line.strip())
        if not m:
            continue
        cells = [c.strip() for c in m.group("cells").split("|")]
        low = [c.lower() for c in cells]
        if header is None:
            if "name" in low:
                header = low
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue                      # the ---|--- separator
        row = dict(zip(header, cells))
        name, _ = _link(row.get("name", ""))
        if not name or name.lower() == "name":
            continue
        _, site = _link(row.get("url", ""))
        desc, _ = _link(row.get("description", ""))
        out.append({
            "name": name,
            "website": site,
            "description": desc[:200],
            "status": (row.get("status") or "").strip() or None,
            "batch": (row.get("class") or batch).strip().upper(),
            "accelerator": accelerator,
        })
    return out


def parse_links(md: str, *, accelerator: str, company_url: str = "") -> list[dict]:
    """A directory page that lists companies as links rather than a table.

    Two shapes in the wild and both fit here. vcbacked writes the entry as
    "[Name\\ \\ October 2026\\ \\ What they do](url)", so the backslash
    runs separate the fields. recentfunding writes "[SSnapp AISR006](url)" -
    the avatar initial is glued to the front and the batch code to the back -
    so the leading duplicate letter and a trailing batch token are stripped.

    Anything that matches the site's own navigation is dropped: a directory
    page is mostly chrome and "Pricing" is not a startup.
    """
    # Every one of these directories links a company at one URL shape and
    # its own navigation at another. Filtering on the shape removes the
    # chrome outright; a blocklist of names would have to grow for every
    # site and would still have let "Research" and "PE firms" through.
    want = re.compile(company_url) if company_url else None
    out, seen = [], set()
    for text, url in re.findall(r"\[([^\]]{2,400})\]\(([^)]+)\)", md):
        if want and not want.search(url):
            continue
        parts = [x.strip() for x in re.split(r"\\+", text) if x.strip()]
        if not parts:
            continue
        name = re.sub(r"\s+", " ", parts[0]).strip()
        # recentfunding renders an entry as avatar-initial + name + stage +
        # batch, with no separators: "SSnapp AISR006" and
        # "SSyncerePre-seed · SR006". There is no word boundary before the
        # batch code, so a \b anchor missed it and left "Snapp AISR006".
        name = re.sub(r"\s*·?\s*(SR\d{3}|[SWF]\d{2})\s*$", "", name).strip()
        name = re.sub(r"\s*·?\s*(Pre-?seed|Seed|Series\s+[A-Z])\s*$", "",
                      name, flags=re.I).strip()
        name = re.sub(r"\s*·\s*$", "", name).strip()
        if len(name) > 1 and name[0] == name[1] and name[:2].isalpha():
            name = name[1:]
        if not name or _CHROME.match(name) or len(name) > 60:
            continue
        desc = ""
        for q in parts[1:]:
            if len(q) > len(desc) and not re.match(r"^[A-Z][a-z]+ \d{4}$", q):
                desc = q
        k = _key(name)
        if not k or k in seen:
            continue
        seen.add(k)
        out.append({"name": name, "website": None,
                    "description": re.sub(r"\s+", " ", desc)[:200],
                    "status": None, "batch": None,
                    "accelerator": accelerator})
    return out


def batch(key: str = "yc", code: str = "s26", *, fetcher=None) -> list[dict]:
    src = SOURCES.get(key)
    if not src:
        return []
    rows: list[dict] = []
    for tmpl in src["pages"]:
        url = tmpl.format(b=code)
        try:
            payload = (fetcher or cx.call)(
                "/web/scrape", {"url": url, "formats": {"markdown": True}},
                timeout=150)
        except Exception:
            continue
        md = _markdown((payload or {}).get("markdown"))
        if src.get("parser") == "links":
            rows += parse_links(md, accelerator=src["name"],
                                company_url=src.get("company_url", ""))
        else:
            rows += parse(md, batch=code, accelerator=src["name"])
    seen, uniq = set(), []
    for r in rows:
        k = _key(r["name"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(r)
    return uniq


def against_cala(rows: list[dict], index: dict) -> dict:
    """Split a batch into what the graph already holds and what it does not."""
    known: dict[str, dict] = {}
    for e in index.values():
        if e.get("entity_type") not in ("Company", "Organization"):
            continue
        k = _key(e.get("name") or "")
        if k and k not in known:
            known[k] = e

    for r in rows:
        hit = known.get(_key(r["name"]))
        r["in_cala"] = bool(hit)
        r["cala_id"] = (hit or {}).get("id")

    fresh = [r for r in rows if not r["in_cala"]]
    return {
        "rows": rows,
        "new_to_cala": fresh,
        "counts": {"total": len(rows), "in_cala": len(rows) - len(fresh),
                   "new": len(fresh)},
    }
