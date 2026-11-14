"""Find the founders before they are founders again.

By the time someone has a company and a deck, every fund has the same
information and the round is a race. The investors who are early are early
because they knew the person, not the company - and the graph knows a lot
about people before it knows anything about what they are about to build.

What actually predicts it, in the order the evidence supports:

  founded before     the single strongest thing on the record. 54 of the 133
                     people we have fetched have a FOUNDED edge, 22 of them
                     more than one.
  did it twice       someone who has founded twice is not experimenting.
  ran something      an operator role is a weaker version of the same claim:
                     they have carried a company without owning the idea.
  sitting in a seat  the point of this tool. Someone already building their
                     own company is not a lead for this list - they are a
                     deal, and a different screen.
  writes cheques     they see what is being funded and they have capital.
  recognised         an award is weak on its own and real alongside the rest.

What this deliberately does NOT do: read LinkedIn, read anyone's mail, or
watch a private person's posting. Those are the signals an investor would
most like and they are not ours to take - the first is against LinkedIn's
terms, and the second two are surveillance of people who have not asked to
be watched. What is here is a public record of companies founded and roles
held, plus open news that already names them.
"""
from __future__ import annotations

from datetime import date

from . import moves as MV, norm, person as PS

WEIGHTS = {
    "founded": 30,      # has founded a company before
    "serial": 18,       # has done it more than once
    "operator": 12,     # has run one without founding it
    "angel": 10,        # writes their own cheques, so sees the deal flow
    "tenure": 10,       # years into the current seat
    "recognised": 6,    # an award or a named talk
    "educated": 4,      # a school we can name
}
SERIAL_FULL = 3         # foundings above which more stops counting
# Markets so broad that matching one proves nothing on its own: nearly every
# technology company's description contains "platform" or "AI".
BROAD = {"software", "ai"}
TENURE_PEAK = 6         # years in a seat at which leaving is most likely
TENURE_FULL = 12        # beyond this the signal flattens, it does not reverse


def _rel(e, name):
    return ((e.get("relationships") or {}).get("outgoing") or {}).get(name) or []


def _val(props, key):
    v = (props or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def years_in_seat(e: dict, today: date) -> float | None:
    """How long they have been where they are, from the earliest dated role."""
    best = None
    for edge in ("WORKS_AT", "IS_CEO_OF", "IS_CTO_OF", "IS_COO_OF",
                 "IS_EXECUTIVE_OF"):
        for it in _rel(e, edge):
            since = _val(it.get("properties"), "valid_since")
            if not since:
                continue
            try:
                y = int(str(since)[:4])
            except (TypeError, ValueError):
                continue
            if 1950 < y <= today.year and (best is None or y < best):
                best = y
    return None if best is None else today.year - best


def tenure_points(years: float | None) -> float:
    """Longer is more, up to a point, and never negative.

    The pattern this is reaching for is real - people leave after they have
    seen a thing through - but we have no backtest for the shape of it, so
    it rises to a peak and then holds rather than claiming a cliff we cannot
    evidence.
    """
    if years is None:
        return 0.0
    if years <= TENURE_PEAK:
        return WEIGHTS["tenure"] * (years / TENURE_PEAK)
    return WEIGHTS["tenure"]


def is_a_firm(item: dict, lookup=None) -> bool:
    """Is this founded thing an investor rather than a company?

    The name catches "Moonfire Ventures" and misses "Atomico", so the name
    is only the fallback. The graph settles it: a fund has INVESTED_IN edges
    going out of it, and a startup raises rather than invests.
    """
    if MV.FUNDISH.search(item.get("name") or ""):
        return True
    if lookup is None:
        return False
    e = lookup(item.get("id") or item.get("name"))
    out = ((e or {}).get("relationships") or {}).get("outgoing") or {}
    return len(out.get("INVESTED_IN") or []) >= 2


def build(e: dict, *, today: date | None = None,
          thesis_markets: set[str] | None = None, company_lookup=None) -> dict | None:
    """One candidate, or None when there is nothing founder-shaped here."""
    today = today or date.today()
    # Founding a fund is not founding a company. Mattias Ljungman founded
    # Atomico and Moonfire; that makes him a co-investor, not a lead for a
    # list of people who might start something to invest in.
    all_founded = _rel(e, "FOUNDED")
    firms = [f for f in all_founded if is_a_firm(f, company_lookup)]
    founded = [f for f in all_founded if f not in firms]
    operated = [it for k in PS.OPERATOR_ROLES for it in _rel(e, k)]
    works = _rel(e, "WORKS_AT") + _rel(e, "IS_EXECUTIVE_OF")
    angel = _rel(e, "INVESTED_IN") + _rel(e, "PARTICIPATES_IN_FUNDING_ROUND")
    awards = _rel(e, "RECEIVED_AWARD") + _rel(e, "SPOKE_AT")
    studied = _rel(e, "STUDIED_AT")

    if not founded and not operated:
        return None                      # no evidence they have built anything

    pts, why = 0.0, []
    if founded:
        pts += WEIGHTS["founded"]
        why.append(f"founded {_names(founded, 2)}")
    if len(founded) >= 2:
        pts += WEIGHTS["serial"] * min(len(founded), SERIAL_FULL) / SERIAL_FULL
        why.append(f"{len(founded)} companies founded, not one")
    if operated and not founded:
        pts += WEIGHTS["operator"]
        why.append(f"ran {_names(operated, 2)}")
    elif operated:
        pts += WEIGHTS["operator"] * 0.5
    if angel:
        pts += WEIGHTS["angel"]
        why.append(f"invests personally in {len(angel)}")
    yrs = years_in_seat(e, today)
    pts += tenure_points(yrs)
    if yrs:
        why.append(f"{yrs:g} years in the current seat")
    if awards:
        pts += WEIGHTS["recognised"]
    if studied:
        pts += WEIGHTS["educated"]

    card = PS.build(e, today=today)
    markets = set(card["domain"]["markets"])
    match = sorted(markets & (thesis_markets or set()))
    # "software" is in almost every technology company's description, so a
    # match on it alone flags the whole list and tells an investor nothing.
    # It counts, and it does not count as a specific match on its own.
    specific = sorted(set(match) - BROAD)

    return {
        "id": e.get("id"), "name": e.get("name"),
        "score": round(pts, 1),
        "why": why,
        "founded": [{"name": f.get("name"), "id": f.get("id")} for f in founded][:6],
        "founded_firms": [{"name": f.get("name"), "id": f.get("id")} for f in firms][:4],
        "now_at": [{"name": w.get("name"), "id": w.get("id"),
                    "role": _val(w.get("properties"), "role")} for w in works][:3],
        "years_in_seat": yrs,
        "markets": sorted(markets),
        "match": match,
        "match_specific": specific,
        "angel": bool(angel),
        # What would have to happen for this to stop being a guess. Named so
        # the list is a watchlist rather than a ranking nobody can act on.
        "watch_for": _triggers(founded, works),
    }


def _names(items, n):
    out = [i.get("name") for i in items if i.get("name")][:n]
    return ", ".join(out) if out else "something"


def _triggers(founded, works) -> list[str]:
    t = ["a FOUNDED edge appears on their record"]
    if works:
        t.append(f"they leave {works[0].get('name')}")
    if founded:
        t.append("one of their companies raises or is acquired")
    t.append("the open news index names them")
    return t


def rank(people, *, today: date | None = None, thesis: str = "",
         limit: int = 50, company_lookup=None) -> dict:
    """The list, and an honest account of what it was computed over."""
    today = today or date.today()
    want = PS.markets_in(thesis or "")
    rows, seen, with_edges = [], set(), 0
    for e in people:
        if not ((e.get("relationships") or {}).get("outgoing") or {}):
            continue
        with_edges += 1
        key = norm.name(e.get("name") or "")
        if not key or key in seen:
            continue
        c = build(e, today=today, thesis_markets=want,
                  company_lookup=company_lookup)
        if c is None:
            continue
        seen.add(key)
        rows.append(c)
    # A thesis match outranks a higher score without one: an investor asked
    # for their market, and the point of the list is who they should meet.
    # A specific market match outranks a broad one, and a broad one outranks
    # none - but neither is allowed to bury a much stronger record.
    rows.sort(key=lambda r: (not r["match_specific"], not r["match"],
                             -r["score"], r["name"] or ""))
    return {
        "candidates": rows[:limit],
        "thesis": sorted(want),
        "coverage": {
            "people_with_edges": with_edges,
            "candidates": len(rows),
            "matched_thesis": sum(1 for r in rows if r["match"]),
            "matched_specifically": sum(1 for r in rows if r["match_specific"]),
        },
    }
