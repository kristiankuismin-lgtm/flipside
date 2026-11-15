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

from . import norm

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

# Words that mark a role as the one worth printing under someone's name.
SENIOR = __import__("re").compile(
    r"founder|chief|ceo|cto|coo|cfo|president|partner|managing|head of|"
    r"director|chair", __import__("re").I)

# Titles a person holds at a firm, strongest first. A scraped team page says
# "Partner"; these say it in the graph, with a start date. One of the harvest's
# findings was that Cala models each of these as its own edge rather than as a
# role string, so asking only for WORKS_AT loses the seniority entirely.
PARTNER_EDGES = [
    ("IS_GENERAL_PARTNER_OF", "General Partner"),
    ("IS_MANAGING_DIRECTOR_OF", "Managing Director"),
    ("IS_EXECUTIVE_OF", "Executive"),
    ("IS_VICEPRESIDENT_OF", "Vice President"),
]

# What a legal check would need, named so its absence is specific rather
# than a shrug. None of these exist on a Person entity in Cala today.
LEGAL_EDGES_WE_LOOKED_FOR = ["SANCTIONED_BY", "PARTY_TO", "SUBJECT_OF",
                             "IS_SUBJECT_OF_REGULATORY_EVENT"]


def _val(props, key):
    v = (props or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def _round_issuer(round_id: str | None) -> str | None:
    """Which company a funding round was for, if we have fetched the round."""
    if not round_id:
        return None
    try:
        from . import cache_index
        e = cache_index.get(round_id) or {}
    except Exception:
        return None
    rel = e.get("relationships") or {}
    for d in ("incoming", "outgoing"):
        for items in (rel.get(d) or {}).values():
            for x in items or []:
                if not isinstance(x, dict):
                    continue
                role = (x.get("properties") or {}).get("role")
                role = role.get("value") if isinstance(role, dict) else role
                if role == "ISSUER" and (x.get("name") or "").strip():
                    return x["name"].strip()
    return None


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
    rounds = _rel(e, "PARTICIPATES_IN_FUNDING_ROUND")
    # Who actually owns and controls a company, rather than works at it.
    # Cala carries these from beneficial-ownership filings - Companies House
    # PSC and its equivalents - so what they mostly name is a person's own
    # holding vehicles rather than the fund they are a partner at. That is
    # still the question a founder is asking: is the person opposite an
    # owner somewhere, or an employee everywhere.
    owns = _rel(e, "IS_BENEFICIARY_OWNER_OF")
    controls = _rel(e, "IS_CONTROL_PERSON_OF")
    titled = [(label, it) for edge, label in PARTNER_EDGES for it in _rel(e, edge)]

    # Operator: the thing a founder most wants to know about an investor.
    years = [y for y in (_year(f) for f in founded) if y]
    years += [y for y in (_year(it) for _r, it in operated) if y]
    building_since = min(years) if years else None

    # One company, one row.
    #
    # Gustav Soderstrom's card listed "Kenet Works" twice - once as FOUNDED
    # and once as CEO - and put "Spotify AB, CEO, 2026" under "has built",
    # which is a promotion at a twenty-year-old company, not something he
    # built. Founding and holding a role are different claims and the card
    # now keeps them apart: companies they started, and seats they have held
    # at companies they did not.
    by_co: dict[str, dict] = {}

    def _co(item, *, founder=False, role=None, year=None):
        raw = (item.get("name") or "").strip()
        # norm.name strips legal suffixes, and a company called "Co" is
        # nothing but one - the key vanished and the row with it. The raw
        # name is the fallback, so a key can never be empty for a company
        # that has a name at all.
        key = norm.name(raw) or raw.lower()
        if not key:
            return
        row = by_co.setdefault(key, {
            "name": item.get("name"), "id": item.get("id"),
            "founder": False, "roles": [], "year": None})
        row["founder"] = row["founder"] or founder
        if role and role not in [r["role"] for r in row["roles"]]:
            row["roles"].append({"role": role, "year": year})
        if year and (row["year"] is None or year < row["year"]):
            row["year"] = year

    for f in founded:
        _co(f, founder=True, role="founder", year=_year(f))
    for r, it in operated:
        _co(it, role=r.replace("IS_", "").replace("_OF", "").lower(), year=_year(it))

    started = [c for c in by_co.values() if c["founder"]]
    held = [c for c in by_co.values() if not c["founder"]]
    started.sort(key=lambda c: (c["year"] is None, c["year"] or 0))
    held.sort(key=lambda c: (c["year"] is None, -(c["year"] or 0)))

    operator = {
        "founded": [{"name": c["name"], "id": c["id"], "year": c["year"],
                     "roles": [r["role"] for r in c["roles"] if r["role"] != "founder"]}
                    for c in started],
        "operated": [{"name": c["name"], "id": c["id"], "year": c["year"],
                      "role": (c["roles"] or [{}])[0].get("role")}
                     for c in held],
        "building_since": building_since,
        "years_building": (today.year - building_since) if building_since else None,
    }

    # A career in order, from the roles that carry a date. It is the thing a
    # list of companies cannot show: how long each one lasted and what came
    # after what.
    timeline = sorted(
        ({"name": c["name"], "id": c["id"], "year": c["year"],
          "founder": c["founder"],
          "role": "founder" if c["founder"] else (c["roles"] or [{}])[0].get("role")}
         for c in by_co.values() if c["year"]),
        key=lambda x: -x["year"])

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

    # Angel: do they write their own cheques?
    #
    # A founder reads this differently from everything else on the card. A
    # partner who has only ever deployed the fund's money needs the whole
    # partnership to say yes. One who has put their own in has decided
    # alone before, and can again - and a personal cheque is a way into a
    # round that a fund's process cannot move fast enough for.
    #
    # Two edges say it: INVESTED_IN on the person, and the rounds they
    # personally took part in. They overlap, so the rounds are counted
    # separately and the companies are deduped against the network above.
    # A funding-round edge carries the round's own name, which is its stage.
    # Printing that as if it were the investment produced rows reading
    # "Seed", "Grant", "Series A" under "writes their own cheques" - three
    # stages and no companies. The company is the ISSUER on the round's own
    # participant edges, so resolve it where the round has been harvested
    # and say "Seed round" rather than "Seed" where it has not.
    angel_rounds = []
    for r in rounds:
        stage = r.get("name") or "round"
        issuer = _round_issuer(r.get("id"))
        angel_rounds.append({
            "name": issuer or f"{stage} round",
            "stage": stage if issuer else None,
            "id": r.get("id"),
            "date": _val(r.get("properties"), "event_date"),
            "role": _val(r.get("properties"), "role"),
        })
    angel_years = sorted({str(x["date"])[:4] for x in angel_rounds if x.get("date")})
    angel = {
        "companies": [n["name"] for n in net if n["via"] == "invested"][:8],
        "company_count": sum(1 for n in net if n["via"] == "invested"),
        "rounds": angel_rounds[:8],
        "round_count": len(angel_rounds),
        "active_years": angel_years[-4:],
        "last_year": angel_years[-1] if angel_years else None,
    }
    angel["is_angel"] = bool(angel["company_count"] or angel["round_count"])

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
    # "no" and "we did not look" are different answers, and the card showed
    # "no" under the words "not checked".
    domain = {"markets": sorted(theirs), "wanted": sorted(want_markets),
              "matched": sorted(theirs & want_markets),
              "checked": bool(want_markets),
              "education": [s.get("name") for s in studied],
              "via": []}

    # The line under their name. works_at comes back in id order, so the
    # first row was whichever entity happened to sort first - Josefin
    # Landgard, co-founder of KRY, was introduced as "Head of Client
    # Relations + Marketing, Videoplaza", a job she left a decade ago.
    founded_names = {norm.name(c["name"] or "") for c in started}

    def _rank(w):
        role = (w.get("role") or "").lower()
        return (
            norm.name(w.get("name") or "") not in founded_names,   # theirs first
            not SENIOR.search(role),                               # then seniority
            -(by_co.get(norm.name(w.get("name") or ""), {}).get("year") or 0),
        )

    best = sorted(works, key=lambda w: _rank(
        {"name": w.get("name"), "role": _val(w.get("properties"), "role")}))
    headline = None
    if best:
        headline = {"name": best[0].get("name"),
                    "role": _val(best[0].get("properties"), "role")}

    return {
        "id": e.get("id"), "name": e.get("name"),
        "headline_role": headline,
        "description": e.get("description") or _val(props, "description"),
        "linkedin": _val(props, "linkedin_url"),
        "website": _val(props, "personal_website"),
        "nationality": [n.get("name") for n in _rel(e, "HAS_NATIONALITY")],
        "works_at": [{"name": w.get("name"), "id": w.get("id"),
                      "role": _val(w.get("properties"), "role")} for w in works],
        # A title held in the graph, not quoted off a page.
        "titles": [{"name": it.get("name"), "id": it.get("id"), "title": label,
                    "since": _val(it.get("properties"), "valid_since")}
                   for label, it in titled],
        "operator": operator,
        "control": {
            "companies": [{"name": c.get("name"), "id": c.get("id"),
                           "owner": True,
                           "control": any(norm.name(x.get("name") or "")
                                          == norm.name(c.get("name") or "")
                                          for x in controls)}
                          for c in owns]
            + [{"name": c.get("name"), "id": c.get("id"), "owner": False,
                "control": True} for c in controls
               if not any(norm.name(o.get("name") or "")
                          == norm.name(c.get("name") or "") for o in owns)],
            "owns": len(owns),
            "controls": len(controls),
        },
        "timeline": timeline,
        "network": network,
        "angel": angel,
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


def enrich_markets(card: dict, fetch) -> dict:
    """Fill in which market each connected company is in, and re-match.

    A company name does not say what the company does: Kry is healthtech and
    "Kry International AB" contains no word a market vocabulary can find. So
    the description has to be fetched for the handful of companies a person
    is closest to.

    `fetch(entity_id) -> description or None` is passed in so this stays a
    pure function over whatever the caller can reach, and so both the card
    endpoint and the call-list enrichment use the same code rather than two
    copies that drift.
    """
    want = set(card.get("domain", {}).get("wanted") or [])
    if not want:
        return card
    via, matched = [], set(card["domain"].get("matched") or [])

    groups = [(card["network"]["companies"], 6),
              (card["operator"]["operated"], 4),
              (card["operator"]["founded"], 4)]
    seen = set()
    for items, cap in groups:
        for it in items[:cap]:
            eid = it.get("id")
            if not eid or eid in seen:
                continue
            seen.add(eid)
            try:
                what = fetch(eid)
            except Exception:
                continue
            if not what:
                continue
            it["what"] = what[:160]
            hit = markets_in(it["what"]) & want
            if hit:
                it["markets"] = sorted(hit)
                matched |= hit
                via.append({"name": it.get("name"), "what": it["what"],
                            "markets": sorted(hit)})

    card["domain"]["matched"] = sorted(matched)
    card["domain"]["via"] = via[:4]
    return card
