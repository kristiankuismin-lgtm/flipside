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

    exits = [{"id": x.get("id"), "name": x.get("name"),
              "role": _role(x, "role"), "type": _role(x, "event_type")}
             for x in events]

    return {
        "id": e.get("id"), "name": e.get("name"),
        "description": e.get("description") or _val(props, "description"),
        "website": _val(props, "website"),
        "address": _val(props, "registered_address") or _val(props, "headquarters_address"),
        "country": (hq[0].get("name") if hq else None),
        "presence": [p.get("name") for p in presence],
        "industries": [i.get("name") for i in industries],
        "stats": {
            "investments": len(invested),
            "rounds": len(rounds),
            "led": led,
            "lead_rate": round(led / len(rounds), 3) if rounds else None,
            "exits": len(exits),
            "people": len(staff),
            "backers": len(backers),
        },
        "stage_mix": stages.most_common(8),
        "portfolio": port,
        "round_rows": round_rows,
        "exits": exits,
        "people": [{"id": p.get("id"), "name": p.get("name"),
                    "role": _role(p, "role")} for p in staff],
        # Which tabs have something in them, so the UI never renders an
        # empty tab and leaves the reader guessing whether it failed.
        "has": {"portfolio": bool(port), "rounds": bool(round_rows),
                "exits": bool(exits), "people": bool(staff)},
    }
