"""What a harvested entity carries, once you ask it for everything.

The rest of the codebase asks Cala for the edges a feature needs. That was the
right habit while the schema was unknown, but it means every feature reads a
different slice and nobody reads the whole record. harvest_all.py now stores
the whole record, and this reads it back - from cache, with no network - so a
fund page can show things no request was ever written for:

  * a fuller portfolio        INVESTED_IN, read in both directions
  * who works there, and when incoming WORKS_AT / IS_EXECUTIVE_OF / FOUNDED
  * where its offices are     HAS_PRESENCE_IN
  * which legal entity it is  lei / cik, which name matching cannot settle

Everything here returns [] or {} when the entity was never harvested. A thin
record and an empty one are different facts, and `coverage()` says which.
"""
from __future__ import annotations

from . import cache_index, norm

# Edges that put a person inside an organisation, strongest claim first. A
# founder outranks an executive outranks staff, and the role text we show
# comes from the first edge that carries one.
STAFF_EDGES = [
    ("FOUNDED", "Founder"),
    ("IS_GENERAL_PARTNER_OF", "General Partner"),
    ("IS_MANAGING_DIRECTOR_OF", "Managing Director"),
    ("IS_EXECUTIVE_OF", "Executive"),
    ("IS_BOARD_MEMBER_OF", "Board member"),
    ("IS_CONTROL_PERSON_OF", "Control person"),
    ("IS_BENEFICIARY_OWNER_OF", "Beneficial owner"),
    ("WORKS_AT", None),
    ("IS_MEMBER_OF", None),
]
STAFF_RANK = {e: i for i, (e, _) in enumerate(STAFF_EDGES)}

# Properties worth showing that no feature ever asked for.
FACT_LABELS = {
    "legal_name": "Legal name",
    "founding_date": "Founded",
    "employee_count": "Employees",
    "headquarters_address": "Headquarters",
    "registered_address": "Registered address",
    "website": "Website",
    "lei": "LEI",
    "cik": "CIK",
    "esg_policy": "ESG policy",
}


def _val(p):
    """Properties come back as {'value':..,'sources':[..]} or bare."""
    return p.get("value") if isinstance(p, dict) and "value" in p else p


def _sources(p) -> list[dict]:
    if isinstance(p, dict):
        s = p.get("sources")
        if isinstance(s, list):
            return [x for x in s if isinstance(x, dict) and x.get("document")]
    return []


def _edges(e: dict, direction: str, name: str) -> list[dict]:
    block = ((e or {}).get("relationships") or {}).get(direction) or {}
    return [x for x in (block.get(name) or []) if isinstance(x, dict)]


_BY_NAME: dict[str, dict] = {}
_BY_NAME_FOR: int | None = None


def _name_index() -> dict[str, dict]:
    """normalised name -> richest payload, rebuilt only when the cache grows.

    A linear scan per lookup is fine once and ruinous in a loop: placing 664
    funds on the map did 664 passes over eleven thousand entities and turned
    a one-second demo into an eight-second one.
    """
    global _BY_NAME, _BY_NAME_FOR
    idx = cache_index.build()
    if _BY_NAME_FOR == len(idx) and _BY_NAME:
        return _BY_NAME
    out: dict[str, dict] = {}
    for e in idx.values():
        key = norm.name(e.get("name") or "")
        if not key:
            continue
        # Keyed by type as well as by name: "Ilkka Paananen" is both a Person
        # and an Organization in Cala, and a caller asking for one must not
        # be handed the other just because it had the longer payload.
        for k in (key, f"{key}\x00{e.get('entity_type')}"):
            cur = out.get(k)
            if cur is None or len(str(e)) > len(str(cur)):
                out[k] = e
    _BY_NAME, _BY_NAME_FOR = out, len(idx)
    return out


def entity(name_or_id: str, types=None) -> dict | None:
    """The richest payload we hold, by id or by name."""
    idx = cache_index.build()
    if name_or_id in idx:
        return idx[name_or_id]
    want = norm.name(name_or_id or "")
    if not want:
        return None
    by = _name_index()
    if types:
        hits = [h for h in (by.get(f"{want}\x00{t}") for t in types) if h]
        return max(hits, key=lambda h: len(str(h))) if hits else None
    return by.get(want)


def facts(e: dict) -> list[dict]:
    """The plain record: legal name, age, size, identifiers - with sources."""
    props = (e or {}).get("properties") or {}
    out = []
    for key, label in FACT_LABELS.items():
        v = _val(props.get(key))
        if v in (None, "", [], {}):
            continue
        # A firm with zero employees is a gap in the record, not a fact about
        # the firm. This codebase has shipped "0" as an answer before and it
        # reads as broken rather than unknown.
        if key == "employee_count" and not v:
            continue
        out.append({"key": key, "label": label, "value": v,
                    "sources": _sources(props.get(key))[:3]})
    return out


def identifiers(e: dict) -> dict:
    """LEI and CIK, the only way to name an entity without ambiguity.

    Three separate bugs in this codebase came from matching firms by name -
    a Munich fund placed in Tampere, a company called NORRSKEN COMPANY LIMITED
    outranking Norrsken VC. An identifier settles all of them.
    """
    props = (e or {}).get("properties") or {}
    out = {}
    for k in ("lei", "cik", "companies_house_uk_company_number", "siren"):
        v = _val(props.get(k))
        if v:
            out[k] = str(v)
    return out


def staff(e: dict, limit: int = 60) -> list[dict]:
    """People attached to this organisation, with role and start date.

    One person often arrives on several edges - Paul Murphy is both a General
    Partner and a Partner at Northzone - so they are merged, keeping the
    strongest claim and the earliest date we have for them.
    """
    by_person: dict[str, dict] = {}
    for edge, default_role in STAFF_EDGES:
        for p in _edges(e, "incoming", edge):
            key = norm.name(p.get("name") or "")
            # IS_MEMBER_OF carries programmes and affiliates as well as people:
            # Accel's members include "Accel Starter Programme" and "Accel-KKR".
            # A call list that offers you a scout programme is worse than one
            # that offers you nobody.
            if not key or p.get("entity_type") != "Person":
                continue
            pr = p.get("properties") or {}
            role = _val(pr.get("role")) or default_role
            since = _val(pr.get("valid_since")) or _val(pr.get("event_date"))
            row = by_person.get(key)
            if row is None:
                by_person[key] = {
                    "name": p.get("name"), "id": p.get("id"), "role": role,
                    "since": since, "edges": [edge], "rank": STAFF_RANK[edge],
                    "source": "cala",
                    "sources": [s.get("document") for s in _sources(pr)][:2],
                }
                continue
            row["edges"].append(edge)
            if role and not row["role"]:
                row["role"] = role
            if since and (not row["since"] or str(since) < str(row["since"])):
                row["since"] = since
            row["rank"] = min(row["rank"], STAFF_RANK[edge])
    out = sorted(by_person.values(), key=lambda r: (r["rank"], r["name"] or ""))
    return out[:limit]


def portfolio(e: dict, limit: int = 400) -> list[dict]:
    """Companies this organisation has invested in, from both edge directions.

    INVESTED_IN points both ways in Cala's data and the direction does not
    mean what it looks like: a fund's *incoming* INVESTED_IN is not its own
    backers, it is more portfolio - Accel's incoming side is Flipkart, Snyk
    and Klaviyo, and 40% of it is literally the same companies as its outgoing
    side. Reading only one direction silently loses the rest, so we read both
    and say which direction each came from.

    Accel: 183 outgoing + 82 incoming, 33 shared -> 232 distinct companies.
    """
    out: dict[str, dict] = {}
    for direction in ("outgoing", "incoming"):
        for b in _edges(e, direction, "INVESTED_IN"):
            key = norm.name(b.get("name") or "")
            if not key:
                continue
            pr = b.get("properties") or {}
            row = out.get(key)
            if row is None:
                out[key] = {"name": b.get("name"), "id": b.get("id"),
                            "entity_type": b.get("entity_type"),
                            "directions": [direction],
                            "sources": [s.get("document") for s in _sources(pr)][:2]}
            elif direction not in row["directions"]:
                row["directions"].append(direction)
    return list(out.values())[:limit]


def presence(e: dict) -> list[dict]:
    """Offices and countries of operation, headquarters first."""
    out, seen = [], set()
    for edge, kind in (("HAS_HEADQUARTERS_IN", "headquarters"),
                       ("HAS_PRESENCE_IN", "presence")):
        for p in _edges(e, "outgoing", edge):
            key = norm.name(p.get("name") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"name": p.get("name"), "kind": kind,
                        "entity_type": p.get("entity_type")})
    return out


def industries(e: dict) -> list[str]:
    seen, out = set(), []
    for p in _edges(e, "outgoing", "OPERATES_IN_INDUSTRY"):
        n = (p.get("name") or "").replace("_", " ").title()
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def coverage(e: dict) -> dict:
    """How much of this entity we actually hold.

    A page that shows nothing because an entity is empty and a page that shows
    nothing because we never asked look identical, and only one of them is our
    fault. This is what tells them apart.
    """
    rel = (e or {}).get("relationships") or {}
    edges = {f"{d}:{k}": len(v or []) for d, b in rel.items()
             if isinstance(b, dict) for k, v in (b or {}).items() if v}
    props = {k: v for k, v in ((e or {}).get("properties") or {}).items()
             if _val(v) not in (None, "", [], {})}
    sourced = sum(1 for v in props.values() if _sources(v))
    return {
        "harvested": bool(rel),
        "properties": len(props),
        "sourced_properties": sourced,
        "edge_types": len(edges),
        "edges": sum(edges.values()),
        "by_edge": dict(sorted(edges.items(), key=lambda kv: -kv[1])),
    }


def profile(name_or_id: str, types=None) -> dict:
    """Everything the harvest knows about one organisation."""
    e = entity(name_or_id, types=types)
    if not e:
        return {"found": False, "name": name_or_id,
                "coverage": {"harvested": False, "properties": 0,
                             "sourced_properties": 0, "edge_types": 0,
                             "edges": 0, "by_edge": {}}}
    return {
        "found": True,
        "id": e.get("id"),
        "name": e.get("name"),
        "entity_type": e.get("entity_type"),
        "description": e.get("description") or "",
        "facts": facts(e),
        "identifiers": identifiers(e),
        "staff": staff(e),
        "portfolio": portfolio(e),
        "presence": presence(e),
        "industries": industries(e),
        "coverage": coverage(e),
    }


# ----------------------------------------------------- learned vocabulary
def vocabulary(entity_type: str, db: str = "cache.sqlite") -> dict | None:
    """What the harvester learned this entity type carries.

    An entity knows its own schema, but asking it costs a round trip. The
    harvester has already asked several of each type and stored the union,
    so a one-off live fetch can skip the introspection and still ask for
    everything.
    """
    import sqlite3
    try:
        con = sqlite3.connect(db)
        row = con.execute("SELECT props, outgoing, incoming FROM harvest_vocab "
                          "WHERE entity_type=?", (entity_type,)).fetchone()
        con.close()
    except sqlite3.Error:
        return None
    if not row:
        return None
    import json as _json
    try:
        return {"properties": _json.loads(row[0]),
                "outgoing": _json.loads(row[1]),
                "incoming": _json.loads(row[2])}
    except ValueError:
        return None
