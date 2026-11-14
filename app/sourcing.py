"""Per-claim sourcing from /knowledge/search.

The metrics in this product are arithmetic over the graph, which makes them
reproducible but not self-evidently true: a founder reading "Northzone backs
your competitor" is entitled to ask who says so.

/knowledge/search answers that. It returns a narrative answer plus
`explainability` - individual claims, each referencing documents in `context`,
each of which carries its origin URL. So a conflict flag stops being our
assertion and becomes three citations, one of which is usually the fund's own
portfolio page.

This is the surface the first recon identified as "the sourcing anchor" and
that nothing in the project used until now.
"""
from . import cala_client as cala

# A regulator's filing outranks everything. After that, a document published
# by one of the parties outranks commentary about them - but "contains /news"
# is not evidence of that: a law firm's news page and a news aggregator both
# match it, and neither is the party speaking for itself.
FILING_HOSTS = ("sec.gov", "gleif.org", "companieshouse.gov.uk",
                "virk.dk", "brreg.no", "prh.fi", "ytj.fi")


def _host(url: str) -> str:
    u = (url or "").lower()
    return u.split("//")[-1].split("/")[0].removeprefix("www.")


def _rank(url: str, source_name: str, subjects: tuple[str, ...] = ()) -> str:
    """FILING | PRIMARY | PRESS. PRIMARY means a subject's own domain."""
    host = _host(url)
    if any(h in host for h in FILING_HOSTS):
        return "FILING"
    from . import norm
    for s in subjects:
        token = norm.name(s).replace(" ", "")
        if token and len(token) >= 4 and token in host.replace("-", "").replace(".", ""):
            return "PRIMARY"
    return "PRESS"


def explain(question: str, subjects: tuple[str, ...] = (), **kw) -> dict:
    """{answer, claims:[{text, docs:[{name,url,source,rank,excerpt}]}], docs}"""
    r = cala.search(question, **kw) or {}
    ctx = {c.get("id"): c for c in (r.get("context") or [])}

    def docs_for(ids):
        out = []
        for i in ids or []:
            c = ctx.get(i)
            if not c:
                continue
            for o in (c.get("origins") or []):
                doc = o.get("document") or {}
                src = o.get("source") or {}
                url = doc.get("url") or src.get("url") or ""
                out.append({"name": doc.get("name") or src.get("name") or url,
                            "url": url, "source": src.get("name") or "",
                            "rank": _rank(url, src.get("name") or "", subjects),
                            "excerpt": (c.get("content") or "")[:220]})
        return out

    claims = [{"text": e.get("content") or "", "docs": docs_for(e.get("references"))}
              for e in (r.get("explainability") or []) if e.get("content")]

    seen, flat = set(), []
    for c in claims:
        for d in c["docs"]:
            if d["url"] and d["url"] not in seen:
                seen.add(d["url"])
                flat.append(d)
    order = {"FILING": 0, "PRIMARY": 1, "PRESS": 2}
    flat.sort(key=lambda d: order.get(d["rank"], 3))
    return {"question": question, "answer": r.get("content") or "",
            "claims": claims, "docs": flat}


def conflict_evidence(investor: str, competitor: str, **kw) -> dict:
    """Why we say this fund backs that competitor."""
    return explain(f"Did {investor} invest in {competitor}? Cite sources.",
                   subjects=(investor, competitor), **kw)


def lead_evidence(investor: str, company: str, **kw) -> dict:
    return explain(f"Did {investor} lead a funding round in {company}, and when? "
                   f"Cite sources.", subjects=(investor, company), **kw)
