"""Public registers as index keys into Cala's graph.

A name is a bad key. "Abridge" matches a Swedish company in Alvsjo; "Lifeline
Ventures" matches a British healthcare provider, a Swedish namesake and the
Finnish VC. Every ambiguity bug in this project traces back to resolving by
name.

Registered identifiers do not collide, and Cala's /entities/lookup takes
exactly those: LEI, SEC CIK, UK Companies House number, French SIREN, RSSD ID.
So the public sources are not a substitute for Cala - they are the index:

    GLEIF        name -> LEI        -> Cala entity (global)
    SEC Form D   name -> CIK        -> Cala entity (US private placements)
    Companies House / SIREN         -> Cala entity (UK / France)

That turns a filing into a graph node with no guessing in between, and it is
the cheapest possible call: one lookup instead of a search plus a rank plus a
hope.
"""
from . import cala_client as cala, datasets as D


def by_identifier(scheme: str, value: str, **kw) -> dict | None:
    try:
        return cala.lookup(scheme, value, **kw)
    except (cala.CalaError, ValueError):
        return None


def resolve(name: str, *, prefer: list[str] | None = None, **kw) -> dict | None:
    """Best-effort: find a registered identifier, then enter the graph with it.

    Returns {entity, scheme, identifier, via} or None. `via` names the public
    register that produced the key, so the UI can show how we got there.
    """
    order = prefer or ["lei", "cik"]
    for scheme in order:
        ident = via = None
        if scheme == "lei":
            g = D.gleif(name)
            if g and g.get("lei"):
                ident, via = g["lei"], "GLEIF"
        elif scheme == "cik":
            fils = D.form_d(name)
            cik = next((f.get("cik") for f in fils if f.get("cik")), None)
            if cik:
                ident, via = str(int(cik)), "SEC EDGAR"   # Cala wants it unpadded
        if not ident:
            continue
        ent = by_identifier(scheme, ident, **kw)
        if ent and ent.get("id"):
            return {"entity": ent, "scheme": scheme, "identifier": ident, "via": via}
    return None


def observations(entity_id: str, **kw) -> dict:
    """Numerical time series Cala holds for an entity.

    Introspection advertises these and nothing in this project read them until
    now. They are what a headcount trend needs - and headcount growth is the
    one condition the orphan detector could never evaluate.
    """
    intro = cala.introspect(entity_id, **kw) or {}
    series = intro.get("numerical_observations") or {}
    if not series:
        return {"available": [], "series": {}}
    names = list(series.keys()) if isinstance(series, dict) else list(series)
    try:
        full = cala.get_entity(entity_id, **kw)
    except cala.CalaError:
        full = {}
    return {"available": names,
            "series": (full.get("numerical_observations") or {}) if isinstance(full, dict) else {}}
