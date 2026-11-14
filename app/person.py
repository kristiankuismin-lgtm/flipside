"""A person card, and how much to trust the person behind it.

A founder choosing who to call at a fund is asking three things a title
cannot answer: have you ever been where I am, will you understand what I
am building, and who can you introduce me to. Cala answers all three from
edges on the Person entity.

Measured across ten VC people before this was written, because the design
depends on what exists:

    WORKS_AT 9/10   IS_MEMBER_OF 8/10   STUDIED_AT 7/10   INVESTED_IN 6/10
    FOUNDED 5/10    IS_CEO_OF 4/10      RECEIVED_AWARD 3/10

FOUNDED and IS_CEO_OF carry valid_since, so "has been building since 2010"
is a fact rather than an impression.

What is NOT here, and is not approximated: there is no sanction, criminal,
regulatory or litigation edge on a Person in Cala. None of the ten had one
and the schema does not offer the shape. A background check is not possible
on this data and the card says so rather than implying a clean record.
"""
from __future__ import annotations

from datetime import date

OPERATOR_ROLES = ["IS_CEO_OF", "IS_COO_OF", "IS_CSO_OF", "IS_CFO_OF"]

# Literal word matching cannot see that a founder writing "clinical
# documentation for doctors" and a company described as a "digital health
# care provider" are in the same market. Nothing they write overlaps.
# A small vocabulary of markets does, and it is inspectable - the card
# shows which market matched and through which company.
MARKETS = {
    "health": ["health", "healthcare", "clinical", "clinic", "medical", "medicine",
               "patient", "doctor", "physician", "hospital", "care", "therapy",
               "diagnost", "pharma", "biotech", "life science", "wellbeing"],
    "fintech": ["fintech", "payment", "bank", "lending", "credit", "insurance",
                "insurtech", "wealth", "treasury", "accounting", "invoice"],
    "software": ["software", "saas", "developer", "platform", "api", "cloud",
                 "infrastructure", "devops", "database"],
    "ai": ["artificial intelligence", " ai ", "machine learning", "llm",
           "language model", "neural", "computer vision"],
    "commerce": ["commerce", "retail", "marketplace", "shopping", "consumer brand",
                 "logistics", "delivery", "supply chain"],
    "climate": ["climate", "carbon", "energy", "solar", "battery", "emission",
                "sustainab", "circular", "renewable"],
    "industrial": ["manufactur", "industrial", "robot", "hardware", "sensor",
                   "machinery", "construction"],
    "security": ["security", "cyber", "privacy", "compliance", "fraud", "identity"],
    "gaming": ["game", "gaming", "entertainment", "esport"],
    "space": ["space", "satellite", "aerospace", "defence", "defense", "orbit"],
}


def markets_in(text: str) -> set[str]:
    """Which markets a piece of text is about. Substrings on purpose:
    "diagnost" catches diagnostic and diagnostics alike."""
    low = f" {(text or '').lower()} "
    return {m for m, words in MARKETS.items() if any(w in low for w in words)}
NETWORK_EDGES = ["IS_MEMBER_OF", "IS_BOARD_MEMBER_OF", "INVESTED_IN"]

# What a legal check would need, named so its absence is specific rather
# than a shrug. None of these exist on a Person entity in Cala today.
LEGAL_EDGES_WE_LOOKED_FOR = ["SANCTIONED_BY", "PARTY_TO", "SUBJECT_OF",
                             "IS_SUBJECT_OF_REGULATORY_EVENT"]


def _val(props, key):
    v = (props or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def _rel(e, name):
    return ((e.get("relationships") or {}).get("outgoing") or {}).get(name) or []


def _year(item) -> int | None:
    v = _val(item.get("properties"), "valid_since") or _val(item.get("properties"), "year")
    try:
        return int(str(v)[:4])
    except (TypeError, ValueError):
        return None


def build(e: dict, *, today: date | None = None, sector_words: set[str] | None = None) -> dict:
    """{identity, operator, network, domain, recognition, unchecked}."""
    today = today or date.today()
    props = e.get("properties") or {}
    words = {w.lower() for w in (sector_words or set()) if len(w) > 3}

    founded = _rel(e, "FOUNDED")
    operated = [(r, it) for r in OPERATOR_ROLES for it in _rel(e, r)]
    invested = _rel(e, "INVESTED_IN")
    boards = _rel(e, "IS_MEMBER_OF") + _rel(e, "IS_BOARD_MEMBER_OF")
    studied = _rel(e, "STUDIED_AT")
    awards = _rel(e, "RECEIVED_AWARD")
    works = _rel(e, "WORKS_AT")

    # Operator: the thing a founder most wants to know about an investor.
    years = [y for y in (_year(f) for f in founded) if y]
    years += [y for y in (_year(it) for _r, it in operated) if y]
    building_since = min(years) if years else None

    operator = {
        "founded": [{"name": f.get("name"), "id": f.get("id"), "year": _year(f)}
                    for f in founded],
        "operated": [{"name": it.get("name"), "id": it.get("id"),
                      "role": r.replace("IS_", "").replace("_OF", "").lower(),
                      "year": _year(it)} for r, it in operated],
        "building_since": building_since,
        "years_building": (today.year - building_since) if building_since else None,
    }

    # Network: what they can do for you that is not money. A board seat and
    # a personal cheque are both doors.
    net = []
    seen = set()
    for src, items in (("board", boards), ("invested", invested)):
        for it in items:
            key = (it.get("name") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            net.append({"name": it.get("name"), "id": it.get("id"), "via": src})
    network = {"companies": net, "count": len(net),
               "boards": sum(1 for n in net if n["via"] == "board"),
               "personal_cheques": sum(1 for n in net if n["via"] == "invested")}

    # Domain: are they in the founder's market? Compared as markets rather
    # than as words, and across everything they have touched - the company
    # they ran counts as much as one they wrote a cheque to.
    own_text = " ".join(filter(None, [
        e.get("description") or _val(props, "description") or "",
        " ".join(n["name"] or "" for n in net),
        " ".join(o["name"] or "" for o in operator["operated"]),
        " ".join(f["name"] or "" for f in operator["founded"]),
        " ".join(s.get("name") or "" for s in studied),
    ]))
    want_markets = markets_in(" ".join(words)) if words else set()
    theirs = markets_in(own_text)
    domain = {"markets": sorted(theirs), "wanted": sorted(want_markets),
              "matched": sorted(theirs & want_markets),
              "education": [s.get("name") for s in studied],
              "via": []}

    return {
        "id": e.get("id"), "name": e.get("name"),
        "description": e.get("description") or _val(props, "description"),
        "linkedin": _val(props, "linkedin_url"),
        "website": _val(props, "personal_website"),
        "nationality": [n.get("name") for n in _rel(e, "HAS_NATIONALITY")],
        "works_at": [{"name": w.get("name"), "id": w.get("id"),
                      "role": _val(w.get("properties"), "role")} for w in works],
        "operator": operator,
        "network": network,
        "domain": domain,
        "recognition": [{"name": a.get("name"), "year": _year(a),
                         "category": _val(a.get("properties"), "category")}
                        for a in awards],
        "spoke_at": [s.get("name") for s in _rel(e, "SPOKE_AT")],
        # Said out loud, because its absence is the kind of thing a reader
        # will otherwise assume we checked.
        "unchecked": {
            "legal": ("Cala holds no sanction, criminal, regulatory or "
                      "litigation edge on a person. This is not a clean "
                      "record; it is no record."),
            "edges_we_looked_for": LEGAL_EDGES_WE_LOOKED_FOR,
        },
    }


def confidence(card: dict) -> dict:
    """How much of this person we can actually see, and what it rests on.

    Not a score of the person - a score of our evidence about them. A
    partner with three edges is not worse than one with ten; we simply know
    less, and the card should not read as though we know the same.
    """
    op = card.get("operator") or {}
    net = card.get("network") or {}
    have = {
        "operator": bool(op.get("founded") or op.get("operated")),
        "network": net.get("count", 0) > 0,
        "domain": bool((card.get("domain") or {}).get("matched")),
        "identity": bool(card.get("linkedin") or card.get("website")),
        "role": bool(card.get("works_at")),
    }
    n = sum(have.values())
    return {"signals": have, "known": n, "of": len(have),
            "label": "High" if n >= 4 else "Medium" if n >= 2 else "Low"}
