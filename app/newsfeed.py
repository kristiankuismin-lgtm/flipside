"""What has been written about a firm lately, and when it stopped.

Cala's graph is a record of things that completed: a round closed, a person
joined, a company was acquired. It is excellent on what happened and silent
on what is being said. An investor deciding whether to spend an hour on a
firm wants both, and the gap between them is often the interesting part - a
fund the graph shows as quiet that the press has been writing about every
week is a different proposition from one nobody has mentioned since 2023.

So this reads Context.dev's news index and answers two questions the graph
cannot:

    how recently was this firm written about at all
    and by how many distinct publications

The second matters more than it looks. One outlet running five pieces is a
relationship with a journalist; five outlets running one each is a story.
Counting sources rather than articles is the difference, and it is cheap.

Nothing here infers sentiment. A headline is evidence that something was
said, not evidence of what it means, and this product does not guess at
tone it cannot measure.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from . import context_dev as cx

QUIET_DAYS = 180        # beyond this, "nothing recent" is itself the finding


def _when(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(iso)[:10]).date()
        except ValueError:
            return None


def _article(a: dict) -> dict:
    src = a.get("source") or {}
    return {
        "title": (a.get("title") or "").strip()[:160],
        "url": a.get("url"),
        "source": (src.get("name") if isinstance(src, dict) else src) or "",
        "published": str(a.get("published_at") or "")[:10] or None,
        "description": (a.get("description") or "").strip()[:220],
    }


def _domain(site: str | None) -> str | None:
    d = (site or "").strip().lower()
    if not d:
        return None
    d = d.split("//")[-1].split("/")[0].removeprefix("www.")
    return d or None


def about(name: str, *, website: str | None = None, limit: int = 8,
          today: date | None = None, fetcher=None) -> dict:
    """Recent coverage of one firm, with its own silence reported.

    Matched on the domain when we hold one. A fund name is ambiguous in a
    news index in exactly the way it is ambiguous everywhere else in this
    product - "Index" and "Atomico" are also English words - and the domain
    is the identifier that is not. The entity variant takes name, domain,
    ticker or isin; the shape came from the API's own discriminator error.
    """
    today = today or datetime.now(timezone.utc).date()
    q = (name or "").strip()
    if not q:
        return {"articles": [], "error": "no name"}
    dom = _domain(website)
    # The discriminator names the key that carries the value, so a domain
    # lookup is {"type":"domain","domain":...} rather than a generic "value".
    by = ({"type": "domain", "domain": dom} if dom
          else {"type": "name", "name": q})
    try:
        r = (fetcher or cx.call)("/news/search",
                                 {"searchBy": {"type": "entity",
                                               "entity": by}},
                                 timeout=60) or {}
    except Exception as e:
        # A missing news layer must not take a profile page down with it.
        return {"articles": [], "error": f"{type(e).__name__}: {str(e)[:120]}"}

    arts = [_article(a) for a in (r.get("data") or []) if isinstance(a, dict)]
    arts = [a for a in arts if a["title"] and a["url"]]
    arts.sort(key=lambda a: a["published"] or "", reverse=True)

    dates = [d for d in (_when(a["published"]) for a in arts) if d]
    newest = max(dates) if dates else None
    sources = sorted({a["source"] for a in arts if a["source"]})

    return {
        "firm": q,
        "matched_on": by["type"],
        "articles": arts[:limit],
        "count": len(arts),
        # Outlets, not articles. Five pieces in one outlet is a relationship
        # with a journalist; one piece in five outlets is a story.
        "outlets": len(sources),
        "sources": sources[:8],
        "latest": newest.isoformat() if newest else None,
        "days_since": (today - newest).days if newest else None,
        "quiet": (not newest) or (today - newest).days > QUIET_DAYS,
        "as_of": today.isoformat(),
    }


def line(n: dict) -> str:
    """One sentence a profile page can print without further thought."""
    if n.get("error"):
        return "Coverage could not be read."
    if not n.get("count"):
        return "No coverage found in the news index."
    d = n.get("days_since")
    when = ("today" if d == 0 else f"{d} days ago" if d is not None
            else "at an unknown date")
    outlets = n.get("outlets") or 0
    return (f"{n['count']} article{'s' if n['count'] != 1 else ''} across "
            f"{outlets} outlet{'s' if outlets != 1 else ''}, most recent {when}.")
