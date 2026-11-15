"""Which employers actually produce founders, measured rather than assumed.

Everyone in venture has a list of these in their head - Google, Palantir,
Wolt, Spotify - and the list is folklore. It is also the wrong shape: what
an investor needs is not "which famous company" but "which employer, among
the ones in MY graph, has the highest rate of people leaving it to start
something", and that is a ratio the graph can compute.

The numerator is a person on whose record both an employer and a FOUNDED
edge appear, with their own company excluded so that founding something is
not evidence that founding it made them a founder. The denominator is
everyone we hold at that employer at all. A company where four of six
people we know went on to found is a different proposition from one where
four of four hundred did, and only the ratio says which is which.

Two things this is honest about.

The denominator is our coverage, not the company's headcount. Cala holds
the people attached to funded companies, which skews towards the senior and
the already-notable, so these rates are far higher than a real leaver rate
and are only comparable to each other.

And WORKS_AT carries no end date on most records, so "prior employer" here
means "an employer that appears on the record of someone who founded",
which includes the job they still hold. The Wilson lower bound is used for
ranking so that one founder out of one does not outrank four out of six.
"""
from __future__ import annotations

import collections
import math
import re

MIN_PEOPLE = 3          # below this the ratio is an anecdote
EMPLOYER_EDGES = ("WORKS_AT", "IS_EXECUTIVE_OF", "IS_BOARD_MEMBER_OF")


def _rel(e: dict, kind: str) -> list[dict]:
    out = []
    for d in ("outgoing", "incoming"):
        for x in ((e.get("relationships") or {}).get(d) or {}).get(kind) or []:
            if isinstance(x, dict) and (x.get("name") or "").strip():
                out.append(x)
    return out


def _wilson(k: int, n: int, z: float = 1.96) -> float:
    """Lower bound of the proportion. One-of-one is not a hundred percent."""
    if n <= 0:
        return 0.0
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / d)


# The answers write the previous employer in prose, so splitting on the
# separators yields sentence fragments alongside the real names: "Veteran
# with AAA console", "free-to-play gaming experience", "mobile". A company
# name starts with a capital and does not describe a person, which is
# enough to tell the two apart without a list of companies to check against.
_NOT_A_COMPANY = (
    "student", "veteran", "experience", "background", "co-founder",
    "founder of", "ceo of", "worked", "years", "graduate", "phd", "msc",
    "degree", "alumni", "alumnus", "previously", "prior to", "serial",
)


def _is_employer(name: str, founded: str | None) -> bool:
    nm = (name or "").strip()
    if len(nm) < 3 or len(nm) > 48:
        return False
    if not (nm[0].isupper() or nm[0].isdigit()):
        return False          # a fragment lifted from mid-sentence
    low = nm.lower()
    if any(w in low for w in _NOT_A_COMPANY):
        return False
    # Founding a company is not having worked at it.
    if founded and low == str(founded).strip().lower():
        return False
    return True


def from_queries(min_people: int = 2) -> list[dict]:
    """Founder factories as Cala will describe them, not as it edges them.

    rank() below reads WORKS_AT and FOUNDED off the same Person record, and
    almost nobody carries both: 154 of 3,576 people have an employer edge at
    all, and exactly one employer cleared three people. Asked instead -
    "the founders backed by this firm and where they worked before" - the
    same graph names the previous employer in a row. That is the fact the
    edges were missing, and it arrives a hundred at a time.
    """
    try:
        from . import bulk, norm
        rows = bulk.rows_of("priors")
    except Exception:
        return []
    by: dict[str, dict] = {}
    for r in rows:
        prior = (r.get("role") or "").strip()      # the previous employer
        person = (r.get("person") or "").strip()
        if not prior or not person:
            continue
        # The answers write it as prose - "Sumea (co-founder & CEO), then
        # Digital Chocolate" - so take the employer before the first bracket
        # and split on the obvious separators.
        for part in re.split(r",| then | and ", prior):
            nm = re.sub(r"\(.*?\)", "", part).strip(" .;")
            if not _is_employer(nm, r.get("org")):
                continue
            k = norm.name(nm) or nm.lower()
            b = by.setdefault(k, {"employer": nm, "people": set(), "founded": set()})
            b["people"].add(person.lower())
            if r.get("org"):
                b["founded"].add(r["org"])
    out = []
    for b in by.values():
        n = len(b["people"])
        if n < min_people:
            continue
        out.append({"employer": b["employer"], "founders": n,
                    "people_held": n, "rate": 1.0,
                    "companies": sorted(b["founded"])[:6],
                    "score": round(_wilson(n, n) * 100, 1),
                    "from_query": True})
    out.sort(key=lambda r: (-r["founders"], r["employer"]))
    return out


def rank(index: dict, *, min_people: int = MIN_PEOPLE,
         limit: int = 40) -> list[dict]:
    """Employers ordered by how reliably people leave them to found."""
    people = [e for e in index.values() if e.get("entity_type") == "Person"]

    founded_at: dict[str, set[str]] = collections.defaultdict(set)
    seen_at: dict[str, set[str]] = collections.defaultdict(set)
    names: dict[str, str] = {}

    for p in people:
        pid = p.get("id") or p.get("name")
        own = {(x.get("name") or "").strip().lower() for x in _rel(p, "FOUNDED")}
        employers = set()
        for kind in EMPLOYER_EDGES:
            for x in _rel(p, kind):
                nm = (x.get("name") or "").strip()
                key = nm.lower()
                if not key or key in own:
                    continue      # their own company is not a factory
                employers.add(key)
                names.setdefault(key, nm)
        for key in employers:
            seen_at[key].add(pid)
            if own:
                founded_at[key].add(pid)

    rows = []
    for key, everyone in seen_at.items():
        n = len(everyone)
        if n < min_people:
            continue
        k = len(founded_at.get(key) or ())
        if not k:
            continue
        rows.append({
            "employer": names.get(key, key),
            "founders": k,
            "people_held": n,
            "rate": round(k / n, 3),
            "score": round(_wilson(k, n) * 100, 1),
        })
    rows.sort(key=lambda r: (-r["score"], -r["founders"]))
    return rows[:limit]


def coverage(index: dict) -> dict:
    people = [e for e in index.values() if e.get("entity_type") == "Person"]
    with_emp = sum(1 for p in people
                   if any(_rel(p, k) for k in EMPLOYER_EDGES))
    with_fnd = sum(1 for p in people if _rel(p, "FOUNDED"))
    return {"people": len(people), "with_an_employer": with_emp,
            "with_a_founding": with_fnd}
