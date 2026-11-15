"""Warm routes that are not made of money.

warmpath.py answers one question: has a fund been in a round with one of
your existing backers? That is the strongest introduction there is and it is
also the only one the product could see, which made every founder without a
cap table unreachable by definition.

People share other things, and Cala holds them: where they studied, what
they won, which boards they sit on, which events they spoke at. Two partners
who were both at the Stockholm School of Economics have a reason to reply to
each other that a cold email does not.

These are weaker than a shared round and the product should say so. A shared
cap table means they have done business together; a shared university means
they walked the same corridors, possibly decades apart. The strength is
ordered, stated, and never dressed up:

    board       they sit on the same board now
    award       the same prize, and the year is checkable
    school      the same institution, which may be forty years apart
    event       the same stage

Nothing here is inferred from an absence. Two people with no shared anything
produce no route, which is different from "no route exists".
"""
from __future__ import annotations

from . import norm

# Ordered by what the connection actually implies, strongest first.
KINDS = [
    ("IS_BOARD_MEMBER_OF", "board", "sit on the same board"),
    ("IS_MEMBER_OF", "board", "are both members of"),
    ("RECEIVED_AWARD", "award", "both received"),
    ("STUDIED_AT", "school", "both studied at"),
    ("SPOKE_AT", "event", "both spoke at"),
]
STRENGTH = {"board": 3, "award": 2, "school": 1, "event": 1}

# Institutions so large that sharing one says almost nothing. A shared
# employer of a hundred thousand people is not an introduction.
_TOO_BIG = 40


def _rel(e, name):
    return ((e.get("relationships") or {}).get("outgoing") or {}).get(name) or []


def _year(item):
    p = item.get("properties") or {}
    for k in ("valid_since", "year", "event_date"):
        v = p.get(k)
        v = v.get("value") if isinstance(v, dict) else v
        if v:
            try:
                return int(str(v)[:4])
            except (TypeError, ValueError):
                pass
    return None


def index(people) -> dict:
    """node -> everyone attached to it, per kind of attachment."""
    out: dict[tuple[str, str], dict] = {}
    for e in people:
        if e.get("entity_type") != "Person":
            continue
        for edge, kind, _ in KINDS:
            for it in _rel(e, edge):
                raw = (it.get("name") or "").strip()
                # norm.name strips legal suffixes, so an institution called
                # "Co" normalises to nothing and the node disappears with
                # its key. The raw name is the fallback.
                key = norm.name(raw) or raw.lower()
                if not key:
                    continue
                node = out.setdefault((kind, key), {"kind": kind,
                                                    "name": it.get("name"),
                                                    "people": {}})
                node["people"][e.get("id") or e.get("name")] = {
                    "id": e.get("id"), "name": e.get("name"), "year": _year(it)}
    return out


def routes(person_id: str, idx: dict, *, limit: int = 20) -> list[dict]:
    """Everyone this person shares something with, strongest first."""
    out: dict[str, dict] = {}
    for node in idx.values():
        people = node["people"]
        if person_id not in people or len(people) < 2:
            continue
        if len(people) > _TOO_BIG:
            # Sharing an institution with four hundred people is not a route.
            continue
        mine = people[person_id]
        for pid, other in people.items():
            if pid == person_id:
                continue
            row = out.setdefault(pid, {"id": other["id"], "name": other["name"],
                                       "via": [], "strength": 0})
            same_year = (mine.get("year") and other.get("year")
                         and abs(mine["year"] - other["year"]) <= 1)
            row["via"].append({
                "kind": node["kind"], "name": node["name"],
                "their_year": other.get("year"), "your_year": mine.get("year"),
                # Overlapping in time turns "the same school" into "the same
                # year", which is the difference between a fact and a reason
                # to write.
                "overlapped": bool(same_year),
            })
            row["strength"] += STRENGTH.get(node["kind"], 1) + (1 if same_year else 0)
    rows = sorted(out.values(), key=lambda r: (-r["strength"], r["name"] or ""))
    return rows[:limit]


def phrase(route: dict) -> str:
    """One sentence a founder could actually put in an email."""
    best = max(route["via"], key=lambda v: STRENGTH.get(v["kind"], 1)
               + (1 if v["overlapped"] else 0))
    verb = next(v for _, k, v in KINDS if k == best["kind"])
    when = (f", the same year" if best["overlapped"]
            else f" ({best['their_year']})" if best["their_year"] else "")
    extra = (f" and {len(route['via']) - 1} other thing"
             f"{'' if len(route['via']) == 2 else 's'}"
             if len(route["via"]) > 1 else "")
    return f"You {verb} {best['name']}{when}{extra}."
