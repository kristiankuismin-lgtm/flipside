"""Is this name a fund or a company raising one?

"lifeline ventures" typed into Ask was screened as a company looking for
investors. It is an investor. Nothing checked, because the router only ever
asked what the sentence looked like, never what the name actually is.

Everything here reads local files and the response cache. No network, so it
can run on a keystroke and it still works with Cala refusing calls.
"""
from __future__ import annotations

import re

from . import norm

# Words that make a name an investor on their face. Weak on their own - a
# company can be called "Capital Bank" - but decisive alongside a match in
# the fund files.
FUNDISH = re.compile(
    r"\b(ventures?|capital|partners?|fund[s]?|invest\w*|equity|"
    r"seed|angels?|syndicate|holdings?|管理)\b", re.I)


def _key(s: str) -> str:
    return norm.name(s) or (s or "").strip().lower()


def classify(q: str, *, funds: dict, companies: dict,
             issuers: dict | None = None) -> dict:
    """{kind, name, why} for a typed name.

    kind is "fund", "company" or "unknown". The caller decides what to do
    with "unknown" - this never guesses one over the other on a tie.
    """
    want = _key(q)
    if not want or len(want) < 2:
        return {"kind": "unknown", "name": q, "why": "too short to resolve"}

    fund_hit = next((orig for k, orig in funds.items() if k == want), None)
    co_hit = next((orig for k, orig in companies.items() if k == want), None)
    issued = bool(issuers and want in issuers)

    # A name we hold on both sides: a fund that has itself raised, or two
    # entities sharing a name. Having raised is the stronger claim about
    # what the user means by typing it into "company raising".
    if fund_hit and (co_hit or issued):
        return {"kind": "company" if issued else "fund", "name": co_hit or fund_hit,
                "why": ("we hold it as both a fund and a company that has raised"
                        if issued else "we hold it as a fund and as a company")}
    if fund_hit:
        return {"kind": "fund", "name": fund_hit,
                "why": "it is in the fund universe we screen against"}
    if co_hit or issued:
        return {"kind": "company", "name": co_hit or q,
                "why": "it appears as a company that has raised"}
    if FUNDISH.search(q or ""):
        return {"kind": "fund", "name": q,
                "why": "the name reads like an investor, though we hold no record of it"}
    return {"kind": "unknown", "name": q, "why": "no record either way"}
