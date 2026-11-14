"""People, read out of the graph we already hold.

Cala has no Person participant list for Slush and no address on a Person, so
"show me people" looked like a dead end. It is not: every entity payload we
have ever cached carries the people attached to it - founders, CEOs, board
members, angels - with role text, LinkedIn handles and per-claim sources.

So this module reads nothing new. It walks the response cache once and turns
it into a person index, and it resolves a person to a place the only way the
graph allows: through a company they are attached to.

That makes the People layer work offline, instantly, and from data that was
already paid for.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Outgoing relationships that put a person somewhere. Order is priority:
# where someone works now beats a company they founded years ago.
PLACING = ["IS_CEO_OF", "WORKS_AT", "FOUNDED", "INVESTED_IN", "IS_MEMBER_OF"]
# Everything else worth showing on a person card but never used for placement.
CONTEXT = ["STUDIED_AT", "RECEIVED_AWARD", "SPOKE_AT", "FEATURED_IN",
           "PARTICIPATES_IN_EVENT"]
REL_LABEL = {
    "IS_CEO_OF": "CEO of", "WORKS_AT": "works at", "FOUNDED": "founded",
    "INVESTED_IN": "invested in", "IS_MEMBER_OF": "board member of",
    "STUDIED_AT": "studied at", "RECEIVED_AWARD": "awarded",
    "SPOKE_AT": "spoke at", "FEATURED_IN": "featured in",
    "PARTICIPATES_IN_EVENT": "attending",
}


def _val(props: dict | None, key: str):
    """Cala wraps every property as {value, sources}. Unwrap, tolerate both."""
    v = (props or {}).get(key)
    if isinstance(v, dict):
        return v.get("value")
    return v


def _sources(props: dict | None, key: str | None = None) -> list[dict]:
    """Document URLs behind a claim, newest first, de-duplicated."""
    v = (props or {}).get(key) if key else props
    src = (v or {}).get("sources") if isinstance(v, dict) else None
    out, seen = [], set()
    for s in src or []:
        doc = (s or {}).get("document")
        if not doc or doc in seen:
            continue
        seen.add(doc)
        out.append({"url": doc, "name": (s.get("name") or "")[:90],
                    "date": s.get("date"), "rank": s.get("source_rank")})
    return out[:4]


def _merge_person(into: dict, node: dict) -> dict:
    """Same person seen in two cached payloads: keep the richer fields.

    A person who shows up as a funding-round participant has a name and
    nothing else; the same person fetched as an entity has roles and sources.
    Neither copy is authoritative, so take the longer of each field.
    """
    for k in ("name", "description", "linkedin", "birth_date"):
        new = node.get(k)
        if new and len(str(new)) > len(str(into.get(k) or "")):
            into[k] = new
    seen = {(r["rel"], r["company_id"] or r["company"]) for r in into["roles"]}
    for r in node.get("roles") or []:
        key = (r["rel"], r["company_id"] or r["company"])
        if key not in seen:
            seen.add(key)
            into["roles"].append(r)
    return into


def _person_node(o: dict) -> dict:
    """One cached Person payload -> the fields a person card needs."""
    props = o.get("properties") or {}
    roles = []
    out = ((o.get("relationships") or {}).get("outgoing") or {})
    for rel, items in out.items():
        if rel not in PLACING and rel not in CONTEXT:
            continue
        for it in (items or [])[:12]:
            rp = it.get("properties") or {}
            roles.append({
                "rel": rel,
                "label": REL_LABEL.get(rel, rel.lower().replace("_", " ")),
                "company": it.get("name"),
                "company_id": it.get("id"),
                "company_type": it.get("entity_type"),
                "role": _val(rp, "role") or rp.get("role"),
                "since": _val(rp, "start_date") or _val(rp, "date"),
                "sources": _sources(rp) or _sources(rp, "role"),
                "places": rel in PLACING,
            })
    # Priority order, so the card and the pin agree on the primary company.
    roles.sort(key=lambda r: PLACING.index(r["rel"]) if r["rel"] in PLACING else 99)
    return {"id": o.get("id"), "name": o.get("name"),
            "description": o.get("description") or _val(props, "description"),
            "linkedin": _val(props, "linkedin_url"),
            "birth_date": _val(props, "birth_date"),
            "roles": roles}


def _walk(node, people: dict, hq: dict, depth: int = 0):
    """Collect Person and Company facts from any cached payload shape.

    The cache holds entity responses, round responses and search responses,
    all differently shaped, so this looks for entity nodes rather than
    assuming a layout.
    """
    if depth > 7:
        return
    if isinstance(node, list):
        for x in node[:600]:
            _walk(x, people, hq, depth + 1)
        return
    if not isinstance(node, dict):
        return

    et, pid = node.get("entity_type"), node.get("id")
    if et == "Person" and node.get("name"):
        n = _person_node(node)
        key = pid or n["name"].lower()
        people[key] = _merge_person(people.get(key) or {**n, "roles": list(n["roles"])}, n)
    elif et in ("Company", "Organization") and pid:
        addr = _val(node.get("properties"), "headquarters_address") \
            or _val(node.get("properties"), "registered_address")
        if addr and pid not in hq:
            hq[pid] = {"name": node.get("name"), "hq": addr,
                       "website": _val(node.get("properties"), "website")}

    for v in node.values():
        if isinstance(v, (dict, list)):
            _walk(v, people, hq, depth + 1)


def build(cache_path: str | Path = "cache.sqlite") -> dict:
    """Walk the response cache once; return {people, company_hq}."""
    people: dict = {}
    hq: dict = {}
    p = Path(cache_path)
    if not p.exists():
        return {"people": [], "company_hq": {}}
    con = sqlite3.connect(str(p))
    try:
        for (v,) in con.execute("select v from cache"):
            try:
                _walk(json.loads(v), people, hq)
            except (ValueError, TypeError):
                continue
    finally:
        con.close()

    out = []
    for person in people.values():
        if not person.get("name"):
            continue
        # A person with no relationship at all is a bare name in a round
        # participant list. Keep them searchable, but they cannot be placed.
        person["placeable"] = any(r["places"] and r["company_id"] in hq
                                  for r in person["roles"])
        out.append(person)
    out.sort(key=lambda x: (-len(x["roles"]), x["name"]))
    return {"people": out, "company_hq": hq}


def primary_company(person: dict, company_hq: dict) -> dict | None:
    """The company that should carry this person's pin, and why.

    Returns the relationship too, because "placed via FOUNDED Supercell" is a
    claim the user can check, and "somewhere in Helsinki" is not.
    """
    for r in person.get("roles") or []:
        if r["places"] and r["company_id"] in company_hq:
            c = company_hq[r["company_id"]]
            return {"company": r["company"] or c.get("name"),
                    "company_id": r["company_id"], "hq": c["hq"],
                    "rel": r["rel"], "label": r["label"], "role": r.get("role")}
    return None
