"""Cala knowledge-graph data layer.

Why this exists: the /knowledge/query endpoint is LLM-interpreted. It takes
20-60s, returns a different schema per investor, and carries no per-row
sources. The Entities API is the real graph:

    GET  /v1/entities?name=X&entity_types=Organization   -> entity id
    POST /v1/entities/{id} {relationships:{outgoing:{REL:{limit}}}}
    POST /v1/entities/{round_id}                         -> participants + roles

It answers in ~0.3s and every property carries sources[] with document URLs.

Design rule learned the hard way: never hardcode a relationship name.
We introspect the entity and discover which relationships exist, because
guessing a schema is exactly what broke the query-based layer.
"""
from __future__ import annotations

import re
from datetime import date

from . import cala_client as cala, norm
from .models import Round

# Investors are usually Organization; Company picks up funds and legal
# entities. The rest are the organisation-ish types Cala models separately: a
# public funder typed GovernmentalInstitution used to return nothing from a
# fund search, and the failure was silent - the kind this codebase keeps
# finding. Asking for a type that matches nothing costs nothing.
INVESTOR_TYPES = ["Organization", "Company", "GovernmentalInstitution",
                  "NonprofitOrganization", "IntergovernmentalOrganization",
                  "ResearchInstitution"]
COMPANY_TYPES = ["Company", "Organization"]

# Ranked best-first. Drives the reliability badge in the UI.
SOURCE_RANK = ["FILING", "PRIMARY", "PRESS", "AGGREGATOR"]

_VC_WORDS = re.compile(r"venture|capital|invest|fund|partners|seed|equity", re.I)
_FUNDING_REL = re.compile(r"fund|invest", re.I)


# ---------------------------------------------------------------- entities
def search(name: str, types=None, limit: int = 10, **kw) -> list[dict]:
    kw.setdefault("allow_live", True)      # may hit the network
    kw.setdefault("ttl", 86400)
    # Interactive callers (the search box) fail fast; batch jobs override these
    # and wait out a rate limit instead of abandoning the row.
    kw.setdefault("interactive", True)
    kw.setdefault("timeout", 8)
    kw.setdefault("retries", 1)
    return cala.entities_search(name, entity_types=types or INVESTOR_TYPES,
                                limit=limit, **kw)


def find_investor(name: str, **kw) -> dict | None:
    """Pick the right entity for an investor name.

    'Lifeline Ventures' returns three entities: a Swedish namesake company,
    the Finnish VC (Organization) and a fund. Preferring Organization plus a
    venture-ish description picks the firm, not the namesake.
    """
    hits = search(name, **kw)
    if not hits:
        return None
    want = norm.name(name)

    def rank(e):
        exact = norm.name(e.get("name")) == want
        org = e.get("entity_type") == "Organization"
        vc = bool(_VC_WORDS.search(e.get("description") or ""))
        return (not exact, not org, not vc)

    return sorted(hits, key=rank)[0]


def find_company(name: str, website: str | None = None, **kw) -> dict | None:
    """Brand vs legal entity: the website decides when we have one."""
    hits = search(name, types=COMPANY_TYPES, **kw)
    if not hits:
        return None
    if website:
        host = re.sub(r"^www\.", "", website.split("//")[-1].split("/")[0]).lower()
        for e in hits:
            if host and host in str(e.get("description", "")).lower():
                return e
    want = norm.name(name)
    return sorted(hits, key=lambda e: norm.name(e.get("name")) != want)[0]


# Address lives under different property names by entity type: companies use
# headquarters_address, investor Organizations use registered_address. Guessing
# one cost us every fund address until introspection caught it.
ADDRESS_PROPS = ["headquarters_address", "registered_address", "address",
                 "principal_address", "location"]
SITE_PROPS = ["website", "homepage", "url", "domain"]


def pick_props(entity_id: str, wanted: list[str], **kw) -> list[str]:
    """Only ask for properties this entity actually has."""
    intro = cala.introspect(entity_id, **kw) or {}
    have = set(intro.get("properties") or [])
    return [p for p in wanted if p in have]


def first_prop(entity: dict, names: list[str]):
    """(value, sources) for the first of `names` that carries a value."""
    for n in names:
        v, src = prop(entity, n)
        if v:
            return v, src, n
    return None, [], None


def funding_relationships(entity_id: str, direction: str = "outgoing", **kw) -> list[str]:
    """Ask the graph which funding relationships this entity actually has."""
    intro = cala.introspect(entity_id, **kw) or {}
    rels = (intro.get("relationships") or {}).get(direction) or []
    return [r for r in rels if _FUNDING_REL.search(str(r))]


# ---------------------------------------------------------------- sources
def best_source(sources: list[dict] | None) -> dict | None:
    """FILING > PRIMARY > PRESS > AGGREGATOR."""
    if not sources:
        return None
    def key(s):
        r = str(s.get("source_rank") or "").upper()
        return SOURCE_RANK.index(r) if r in SOURCE_RANK else len(SOURCE_RANK)
    return sorted(sources, key=key)[0]


def prop(entity: dict, key: str):
    """(value, sources). Properties come as {'value':x,'sources':[...]}."""
    p = (entity.get("properties") or {}).get(key)
    if isinstance(p, dict):
        return p.get("value"), p.get("sources") or []
    return p, []


def rels(entity: dict, direction: str, name: str) -> list[dict]:
    r = ((entity.get("relationships") or {}).get(direction) or {}).get(name)
    if isinstance(r, dict):
        r = r.get("items") or r.get("results") or r.get("data") or []
    return r or []


# ---------------------------------------------------------------- rounds
def _as_date(v):
    if not v:
        return None
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def _is_lead(item: dict) -> bool:
    for k, v in item.items():
        if re.search(r"\blead\b|is_lead|led", str(k), re.I):
            if v is True:
                return True
            if isinstance(v, str) and v.strip().lower() in {"true", "yes", "lead", "led"}:
                return True
    role = str(item.get("role") or "")
    return bool(re.match(r"lead|led", role, re.I))


ROUND_PROPS = ["name", "round_label", "instrument", "transaction_value",
               "transaction_value_units", "announcement_date", "event_date"]


def round_detail(round_id: str, participant_rel: str, **kw) -> Round | None:
    """One funding round with its participants, roles and sources."""
    r = cala.get_entity(round_id, properties=ROUND_PROPS,
                        incoming=[participant_rel], limit=100, **kw) or {}
    parts = rels(r, "incoming", participant_rel)

    issuer = next((p for p in parts if str(p.get("role", "")).upper() == "ISSUER"), None)
    investors = [p for p in parts
                 if str(p.get("role", "")).upper() in {"INVESTOR", "LENDER"}] \
        or [p for p in parts if p is not issuer]

    d = _as_date(prop(r, "event_date")[0]) or _as_date(prop(r, "announcement_date")[0])
    if not d:
        return None

    label, label_src = prop(r, "round_label")
    amount, amt_src = prop(r, "transaction_value")
    company = (issuer or {}).get("name") or prop(r, "name")[0] or "?"

    src = best_source(label_src or amt_src)
    return Round(
        company=str(company),
        date=d,
        stage=str(label or ""),
        amount_eur=float(amount) if isinstance(amount, (int, float)) else None,
        investors=[p.get("name") for p in investors if p.get("name")],
        leads=[p.get("name") for p in investors if p.get("name") and _is_lead(p)],
        lead_is_native=True,
        sources=[s for s in [(src or {}).get("document")] if s],
    )
