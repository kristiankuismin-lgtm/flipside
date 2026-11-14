"""Where a fund takes you.

Everything else in this product scores an investor in isolation: do they lead,
do they follow on, are they still deploying. None of that answers the question
a founder is actually deciding - if I take this money now, who leads my next
round?

That is a transition in the graph, not an attribute of a node:

    investor on round k  ->  lead of round k+1

Across the rounds already cached it yields 2,545 observations and needs no
further Cala calls. Index Ventures hands off 48 times, most often to Tiger
Global, Accel and Spark. Creandum to Valar, Index and Accel.

It also exposes who the connectors are. A fund that hands off to many distinct
leads sits between clusters; one that always hands to the same two does not.
Both facts are useful and neither is on anybody's website.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import norm

MIN_OBS = 3          # below this a handoff pattern is an anecdote


def build(rounds_by_company: dict[str, list[dict]]) -> dict:
    """{handoffs, co_invest, led_by, totals} keyed on normalised names."""
    handoff: dict[str, Counter] = defaultdict(Counter)
    co: dict[str, Counter] = defaultdict(Counter)
    led_by: dict[str, Counter] = defaultdict(Counter)   # who led INTO this fund's companies
    display: dict[str, str] = {}

    def remember(name: str) -> str | None:
        k = norm.name(name)
        if len(k) < 3:
            return None
        if len(name) > len(display.get(k, "")):
            display[k] = name.strip()
        return k

    for rs in rounds_by_company.values():
        rs = sorted(rs or [], key=lambda r: r.get("date") or "")
        for i, r in enumerate(rs):
            invs = [k for k in (remember(x) for x in (r.get("investors") or [])) if k]
            # who sits on a cap table together
            for a in invs:
                for b in invs:
                    if a != b:
                        co[a][b] += 1
            if i + 1 >= len(rs):
                continue
            leads = [k for k in (remember(x) for x in (rs[i + 1].get("leads") or [])) if k]
            for a in invs:
                for L in leads:
                    if L != a:
                        handoff[a][L] += 1
                        led_by[L][a] += 1

    return {"handoff": handoff, "co": co, "led_by": led_by, "display": display}


def where_it_takes_you(graph: dict, investor: str, top: int = 6) -> dict:
    """Who leads the next round after this fund is on the cap table."""
    k = norm.name(investor)
    c: Counter = graph["handoff"].get(k) or Counter()
    total = sum(c.values())
    disp = graph["display"]
    rows = [{"name": disp.get(n, n), "count": v,
             "share": round(v / total, 3) if total else None}
            for n, v in c.most_common(top)]
    return {"investor": disp.get(k, investor), "observations": total,
            "distinct_leads": len(c), "next_leads": rows,
            # Many distinct leads from the same base means this fund connects
            # clusters rather than feeding one. Concentration is the inverse.
            "concentration": round(c.most_common(1)[0][1] / total, 3) if total else None,
            "enough": total >= MIN_OBS}


def who_leads_into(graph: dict, investor: str, top: int = 6) -> dict:
    """The reverse: whose companies does this fund end up leading?"""
    k = norm.name(investor)
    c: Counter = graph["led_by"].get(k) or Counter()
    disp = graph["display"]
    return {"investor": disp.get(k, investor), "observations": sum(c.values()),
            "from": [{"name": disp.get(n, n), "count": v} for n, v in c.most_common(top)]}


def co_investors(graph: dict, investor: str, top: int = 8) -> list[dict]:
    k = norm.name(investor)
    c: Counter = graph["co"].get(k) or Counter()
    disp = graph["display"]
    return [{"name": disp.get(n, n), "count": v} for n, v in c.most_common(top)]


def connectors(graph: dict, top: int = 12) -> list[dict]:
    """Funds whose handoffs spread widest - the bridges in the network."""
    out = []
    for k, c in graph["handoff"].items():
        total = sum(c.values())
        if total < MIN_OBS * 2:
            continue
        out.append({"name": graph["display"].get(k, k), "handoffs": total,
                    "distinct_leads": len(c),
                    "spread": round(len(c) / total, 3)})
    out.sort(key=lambda x: (-x["distinct_leads"], -x["handoffs"]))
    return out[:top]
