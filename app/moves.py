"""People who just changed seats, which is the earliest signal there is.

A founder leaving to start something is the thing every investor wants to
hear about first, and by the time it is a funding round it is not early any
more. The graph can say it: a FOUNDED or IS_CEO_OF edge carries valid_since,
and a company with no rounds on record has not raised yet.

What this module will NOT do is pretend the data is there. Measured on the
cache as it stands:

    133 people harvested with edges
      4 of them have a founding or chief-executive edge dated 2023 or later
      1 of those four is wrong - Cala dates Gustav Soderstrom at Spotify AB
        from 2026, which is a valid_since on a role, not a founding

So `moves()` is written to be right, reports how much it could see, and the
UI says the coverage out loud. It gets better as the harvest reaches more
people, and it is not allowed to look confident in the meantime.

Two kinds of move, because they are read differently:

  new_venture  someone who has built before has a recent role at a company
               with no rounds. For an investor this is the lead.
  new_seat     a partner recently started at a firm. For a founder this is
               a partner still building a portfolio, which is a different
               conversation from one with a full one.
"""
from __future__ import annotations

import re
from datetime import date

from . import norm

# How recent counts as a move. Eighteen months is one fundraising cycle:
# shorter and a quiet year looks like nothing happened, longer and the
# word "just" stops being true.
RECENT_MONTHS = 18

# Only FOUNDED means someone started something. Becoming chief executive of
# a company that already exists is a seat, however senior - Cala has Gustav
# Soderstrom as IS_CEO_OF Spotify AB from 2026, which is true, and is a
# promotion rather than a new venture. Treating the chief-executive edges as
# foundings turned that into a lead.
FOUNDER_EDGES = ["FOUNDED"]
SEAT_EDGES = ["IS_CEO_OF", "IS_CTO_OF", "IS_COO_OF", "WORKS_AT",
              "IS_GENERAL_PARTNER_OF", "IS_MANAGING_DIRECTOR_OF",
              "IS_EXECUTIVE_OF"]

# A name that says the company is not telling you what it is yet.
STEALTH = re.compile(r"\b(stealth|new ?co|newco|undisclosed|confidential|"
                     r"in ?stealth|unannounced)\b", re.I)
# A firm, not a startup. A partner "founding" their own fund is a seat move.
FUNDISH = re.compile(r"ventures?|capital|partners?|\bfund\b|advisors?|"
                     r"asset management|holdings?", re.I)


def _val(props, key):
    v = (props or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def _rel(e, name):
    return ((e.get("relationships") or {}).get("outgoing") or {}).get(name) or []


def months_between(since, today: date) -> int | None:
    """Whole months from a date string to today, or None if undatable."""
    if not since:
        return None
    t = str(since)[:10]
    try:
        d = date.fromisoformat(t)
    except ValueError:
        try:
            d = date(int(t[:4]), 1, 1)
        except (ValueError, TypeError):
            return None
    if d > today:
        # A start date in the future is a bad record, not a move. Cala dates
        # Gustav Soderstrom at Spotify AB from 2026; that is a role field,
        # not a founding, and treating it as news would be our error.
        return None
    return (today.year - d.year) * 12 + (today.month - d.month)


# A company founded this much earlier than the person's start date was not
# founded by them on that date - the date is when their role began. Two
# years is generous: it keeps a co-founder who joined in year one and
# excludes Cala dating Gustav Soderstrom at Spotify AB from 2026.
FOUNDED_BEFORE_YEARS = 2


def _company_age_conflict(co_entity: dict | None, since) -> int | None:
    """Years between the company's own founding date and this role's start.

    Positive means the company already existed, which makes the edge a role
    rather than a founding however it is labelled.
    """
    if not co_entity or not since:
        return None
    fd = _val((co_entity.get("properties") or {}), "founding_date")
    if not fd:
        return None
    try:
        return int(str(since)[:4]) - int(str(fd)[:4])
    except (TypeError, ValueError):
        return None


def moves(person: dict, *, rounds_by_company: dict | None = None,
          today: date | None = None, company_lookup=None) -> list[dict]:
    """Every recent, dated seat change this person's record supports.

    `company_lookup(name_or_id)` is optional and, when given, is used to
    check the company's own founding date against the role's start - which
    is what separates "founded something" from "took a job somewhere old".
    """
    today = today or date.today()
    rbc = rounds_by_company or {}
    out = []

    for edge in FOUNDER_EDGES:
        for it in _rel(person, edge):
            co = (it.get("name") or "").strip()
            age = months_between(_val(it.get("properties"), "valid_since"), today)
            if not co or age is None or age > RECENT_MONTHS:
                continue
            rounds = rbc.get(norm.name(co)) or []

            # Did the company already exist? Then the date is when the role
            # started, not when the company did, and this is not a founding.
            if company_lookup is not None:
                gap = _company_age_conflict(
                    company_lookup(it.get("id") or co),
                    _val(it.get("properties"), "valid_since"))
                if gap is not None and gap > FOUNDED_BEFORE_YEARS:
                    out.append({"kind": "new_seat", "person": person.get("name"),
                                "person_id": person.get("id"), "company": co,
                                "company_id": it.get("id"), "months_ago": age,
                                "role": _val(it.get("properties"), "role") or "joined",
                                "why": f"the company is {gap} years older than "
                                       f"this role, so this is a seat, not a founding"})
                    continue

            # A fund is not a startup. A partner who started their own
            # vehicle has moved seat, not gone building.
            if FUNDISH.search(co):
                out.append({"kind": "new_seat", "person": person.get("name"),
                            "person_id": person.get("id"), "company": co,
                            "company_id": it.get("id"), "months_ago": age,
                            "role": _val(it.get("properties"), "role") or "founder",
                            "why": "started their own firm"})
                continue
            out.append({
                "kind": "new_venture", "person": person.get("name"),
                "person_id": person.get("id"), "company": co,
                "company_id": it.get("id"), "months_ago": age,
                "role": _val(it.get("properties"), "role")
                        or edge.replace("IS_", "").replace("_OF", "").lower(),
                "stealth": bool(STEALTH.search(co)),
                "rounds": len(rounds),
                "why": ("has not raised on record" if not rounds
                        else f"{len(rounds)} rounds already on record"),
            })

    for edge in SEAT_EDGES:
        for it in _rel(person, edge):
            co = (it.get("name") or "").strip()
            age = months_between(_val(it.get("properties"), "valid_since"), today)
            if not co or age is None or age > RECENT_MONTHS:
                continue
            if any(m["company"] == co for m in out):
                continue
            out.append({"kind": "new_seat", "person": person.get("name"),
                        "person_id": person.get("id"), "company": co,
                        "company_id": it.get("id"), "months_ago": age,
                        "role": _val(it.get("properties"), "role") or "joined",
                        "why": "recently started there"})

    out.sort(key=lambda m: m["months_ago"])
    return out


def scan(people, *, rounds_by_company=None, today=None, company_lookup=None) -> dict:
    """Run it over a set of people and say how much of them we could read.

    The coverage numbers are the point. A detector that finds two moves out
    of a hundred and thirty people is a detector that cannot see, and it has
    to say so rather than presenting two rows as the answer.
    """
    today = today or date.today()
    hits, dated, with_edges = [], 0, 0
    for e in people:
        rel = (e.get("relationships") or {}).get("outgoing") or {}
        if not rel:
            continue
        with_edges += 1
        has_date = any(
            _val(it.get("properties"), "valid_since")
            for edge in FOUNDER_EDGES + SEAT_EDGES for it in (rel.get(edge) or []))
        dated += bool(has_date)
        hits += moves(e, rounds_by_company=rounds_by_company, today=today,
                      company_lookup=company_lookup)

    # Cala holds some people under two entities, so the same move arrives
    # twice with two person ids. One person, one company, one row.
    seen, uniq = set(), []
    for h in hits:
        k = (norm.name(h["person"] or ""), norm.name(h["company"] or ""))
        if k in seen:
            continue
        seen.add(k)
        uniq.append(h)
    hits = uniq
    ventures = [h for h in hits if h["kind"] == "new_venture"]
    return {
        "moves": hits,
        "new_ventures": ventures,
        "coverage": {
            "people_with_edges": with_edges,
            "people_with_a_dated_role": dated,
            "moves_found": len(hits),
            "ventures_found": len(ventures),
        },
    }
