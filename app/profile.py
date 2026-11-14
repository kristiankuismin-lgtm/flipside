"""One fund, assembled: the tabs a reader expects on a firm.

The entity card used to be a flat list of relationship groups. That shows
what the graph holds but not what a person came to find out, which is:
what do they invest in, do they lead, has anything come out, who works
there, and what has been written lately.

Everything here comes from one entity fetch plus what is already cached.
Nothing is invented: a tab with no data says so and names the edge that
was empty.
"""
from __future__ import annotations

from collections import Counter

from . import graph, norm


def _val(props, key):
    v = (props or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def _items(e: dict, direction: str, rel: str) -> list[dict]:
    return ((e.get("relationships") or {}).get(direction) or {}).get(rel) or []


def _role(it: dict, key: str):
    return _val(it.get("properties"), key)


def _city_of(addr):
    """The city in a postal address, which is at the end of it, not the start.

    Reuses the reader built for the near-me grouping, where splitting on the
    first comma once filed a dozen funds under "PL 358".
    """
    if not addr:
        return None
    try:
        from .near import city_of
        return city_of(str(addr))
    except Exception:                                 # noqa: BLE001
        return None


def build(e: dict, *, rounds_by_company: dict | None = None,
          domains: dict | None = None) -> dict:
    """{header, overview, portfolio, rounds, exits, people} for one fund."""
    props = e.get("properties") or {}
    rbc = rounds_by_company or {}
    domains = domains or {}

    invested = _items(e, "outgoing", "INVESTED_IN")
    rounds = _items(e, "outgoing", "PARTICIPATES_IN_FUNDING_ROUND")
    events = _items(e, "outgoing", "PARTICIPATES_IN_CORPORATE_EVENT")
    industries = _items(e, "outgoing", "OPERATES_IN_INDUSTRY")
    hq = _items(e, "outgoing", "HAS_HEADQUARTERS_IN")
    presence = _items(e, "outgoing", "HAS_PRESENCE_IN")
    staff = _items(e, "incoming", "WORKS_AT")
    backers = _items(e, "incoming", "INVESTED_IN")

    # Rounds: stage mix and how often they are the lead. is_lead is native
    # here, which is the whole reason the lead rate is a fact and not a guess.
    stages, led = Counter(), 0
    round_rows = []
    for r in rounds:
        stage = r.get("name") or "Round"
        is_lead = bool(_role(r, "is_lead"))
        led += is_lead
        stages[norm.stage(stage) or stage] += 1
        round_rows.append({"id": r.get("id"), "stage": stage, "lead": is_lead,
                           "role": _role(r, "role")})

    # Portfolio: enrich each company with what we already know of its rounds,
    # so the list shows what they went on to do rather than only a name.
    port, seen_port = [], set()
    for c in invested:
        key = norm.name(c.get("name") or "")
        # The graph can carry the same company under two ids. One row.
        if key in seen_port:
            continue
        seen_port.add(key)
        rs = rbc.get(key) or []
        last = rs[-1] if rs else None
        port.append({
            "id": c.get("id"), "name": c.get("name"),
            "website": domains.get((c.get("name") or "").strip().lower()),
            "rounds": len(rs),
            "last_stage": (last or {}).get("stage"),
            "last_date": (last or {}).get("date"),
            "investors": (last or {}).get("investors", [])[:5],
        })
    port.sort(key=lambda c: (-(c["rounds"] or 0), c["name"] or ""))

    # ---------------------------------------------------------- the shape
    # of a portfolio: where it is, what it is in, what size the cheques are.
    #
    # Every one of these is read off the rounds and the companies we already
    # hold rather than asked for separately, and every one of them counts
    # only what it can see - a sector mix over 9 of 40 companies is a sector
    # mix over 9 companies and says so, because a donut that silently covers
    # a quarter of the portfolio is worse than no donut.
    from . import depth as _depth
    countries, sectors = Counter(), Counter()
    placed = typed = 0
    for c in port:
        ce = _depth.entity(c["name"], types=("Company", "Organization"))
        if not ce:
            continue
        where = [w["name"] for w in _depth.presence(ce) if w["kind"] == "headquarters"]
        if where:
            countries[where[0]] += 1
            placed += 1
        inds = _depth.industries(ce)
        if inds:
            sectors[inds[0]] += 1
            typed += 1

    # Cheque sizes, from the rounds this fund was actually in.
    amounts, dated = [], []
    for c in port:
        for r in (rbc.get(norm.name(c["name"] or "")) or []):
            if not any(norm.name(i) == norm.name(e.get("name") or "")
                       for i in (r.get("investors") or [])):
                continue
            dated.append({"company": c["name"], "stage": r.get("stage"),
                          "date": r.get("date"), "amount": r.get("amount"),
                          "lead": norm.name(e.get("name") or "") in
                                  {norm.name(x) for x in (r.get("leads") or [])},
                          "investors": (r.get("investors") or [])[:6]})
            if r.get("amount"):
                amounts.append(float(r["amount"]))
    dated.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    by_year = Counter(str(r["date"])[:4] for r in dated if r.get("date"))

    # PARTICIPATES_IN_CORPORATE_EVENT is not a list of exits. In the whole
    # cache it is 2,153 FINANCING_RAISED_OR_FACILITY_ENTERED, one
    # MNA_COMPLETED and one COMPANY_LIFECYCLE_EVENT - so counting the edge
    # and calling it "Exits and M&A" put 69 exits on Creandum's headline
    # card when it has none on record. An exit is a sale or a listing.
    EXIT_EVENTS = ("MNA", "ACQUISITION", "ACQUIRED", "MERGER", "IPO",
                   "LISTING", "DIVEST", "SALE", "BUYOUT")
    exits, financings = [], []
    for x in events:
        row = {"id": x.get("id"), "name": x.get("name"),
               "role": _role(x, "role"), "type": _role(x, "event_type"),
               "date": _role(x, "event_date")}
        label = (row["name"] or "") + " " + (row["type"] or "")
        (exits if any(w in label.upper() for w in EXIT_EVENTS)
         else financings).append(row)

    return {
        "id": e.get("id"), "name": e.get("name"),
        "description": e.get("description") or _val(props, "description"),
        "website": _val(props, "website"),
        "address": _val(props, "registered_address") or _val(props, "headquarters_address"),
        # HAS_HEADQUARTERS_IN is often absent where HAS_PRESENCE_IN is not.
        # Creandum has no headquarters edge and three presence countries, and
        # a blank on the headline card read as "we do not cover them".
        "country": (hq[0].get("name") if hq
                    else (presence[0].get("name") if presence else None)),
        "country_is_presence": not hq and bool(presence),
        # The city, read off the end of the address we hold. "Stockholm" is
        # what a founder deciding whether to get on a train needs; "Sweden"
        # is what the country edge happens to carry.
        "city": _city_of(_val(props, "headquarters_address")
                         or _val(props, "registered_address")),
        "presence": [p.get("name") for p in presence],
        "industries": [i.get("name") for i in industries],
        "stats": {
            "investments": len(invested),
            "rounds": len(rounds),
            "led": led,
            "lead_rate": round(led / len(rounds), 3) if rounds else None,
            "exits": len(exits),
            "financing_events": len(financings),
            "people": len(staff),
            "backers": len(backers),
        },
        "stage_mix": stages.most_common(8),
        # Each mix carries the denominator it was computed over, because a
        # share of nine companies and a share of forty are different claims.
        "country_mix": {"rows": countries.most_common(8), "of": placed,
                        "total": len(port)},
        "sector_mix": {"rows": sectors.most_common(8), "of": typed,
                       "total": len(port)},
        "cheques": {
            "n": len(amounts),
            "of": len(dated),
            "avg": round(sum(amounts) / len(amounts)) if amounts else None,
            "median": round(sorted(amounts)[len(amounts) // 2]) if amounts else None,
            "min": round(min(amounts)) if amounts else None,
            "max": round(max(amounts)) if amounts else None,
        },
        "deals": dated[:60],
        "deals_by_year": sorted(by_year.items()),
        "portfolio": port,
        "round_rows": round_rows,
        "exits": exits,
        "financing_events": len(financings),
        "people": [{"id": p.get("id"), "name": p.get("name"),
                    "role": _role(p, "role")} for p in staff],
        # Which tabs have something in them, so the UI never renders an
        # empty tab and leaves the reader guessing whether it failed.
        "has": {"portfolio": bool(port), "rounds": bool(round_rows),
                "exits": bool(exits), "people": bool(staff)},
    }
