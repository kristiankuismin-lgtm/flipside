"""Yhtion koko kierroshistoria sijoittajineen ja liideineen. M2:n perusta.

Kanoninen kysely lukittu empiirisesti (ks. recon_report.md ja keskustelu):
luonnollisen kielen kysely voitti return()-projektion kahdesta syysta:

  1. Se palauttaa normalisoituja pareja {round_name, date, investor, lead}
     eika vapaata tekstia, joka pitaisi jasentaa.
  2. return()-projektio tiivisti siemenkierrosten sijoittajat muotoon
     "Angel investors" ja hukkasi juuri siemenrahastot - eli kohderyhmamme.
     NL-kysely antoi samoista kierroksista Lifeline Ventures / Inventure.

lead tulee boolean-kenttana, joten M2:n liiditieto on natiivi.
"""
from collections import defaultdict

from . import cala_client as cala, norm
from .extract import parse_amount, parse_date
from .models import Round

QUERY = ("For each funding round of {company}, list the round name, date, "
         "each investor that participated, and whether that investor led the round.")

# Investor-side variant: conviction needs round SIZE to tell a pre-emption
# (insiders back in at >=2x) from a bridge. Without amounts the structure is
# reported as unknown rather than guessed.
QUERY_WITH_AMOUNT = (
    "For each funding round of {company}, list the round name, date, the total "
    "amount raised in that round, each investor that participated, and whether "
    "that investor led the round.")


def _truthy(v) -> bool:
    return v is True or str(v).strip().lower() in {"true", "yes", "lead", "led", "1"}


def company_history(company: str, with_amount: bool = False, **kw) -> list[Round]:
    """Company rounds in date order, grouped from (round, investor) pairs."""
    q = (QUERY_WITH_AMOUNT if with_amount else QUERY).format(company=company)
    resp = cala.query(q, **kw) or {}
    rows = resp.get("results") or []

    # Rivi per (kierros, sijoittaja) -> ryhmita kierroksiksi.
    # Avain on vaihe + vuosi/kk: saman kierroksen paivamaara voi vaihdella
    # rivilta toiselle ("November 2014" vs "November 10, 2014").
    groups: dict[tuple, dict] = defaultdict(
        lambda: {"date": None, "stage": "", "investors": [], "leads": [], "amount": None})

    for r in rows:
        if not isinstance(r, dict):
            continue
        stage = str(r.get("round_name") or r.get("round") or r.get("stage") or "").strip()
        d = parse_date(r.get("date") or r.get("year"))
        inv = (r.get("investor") or r.get("investors") or "")
        inv = str(inv).strip() if not isinstance(inv, list) else ", ".join(map(str, inv))
        if not d or not inv:
            continue

        g = groups[(norm.stage(stage), d.year, d.month)]
        g["stage"] = g["stage"] or stage
        if g.get("amount") is None:
            g["amount"] = parse_amount(r.get("amount") or r.get("total_amount"))
        # Tarkin paivamaara voittaa (paivatason tieto > kuukausitason oletus).
        if g["date"] is None or (d.day != 1 and g["date"].day == 1):
            g["date"] = d
        if inv not in g["investors"]:
            g["investors"].append(inv)
        if _truthy(r.get("lead")) and inv not in g["leads"]:
            g["leads"].append(inv)

    out = [Round(company=company, date=g["date"], stage=g["stage"], amount_eur=g.get("amount"),
                 investors=g["investors"], leads=g["leads"],
                 lead_is_native=True, sources=[])
           for g in groups.values() if g["date"]]
    out.sort(key=lambda x: x.date)
    return out


# --------------------------------------------------------------- the graph

def _val(x):
    return x.get("value") if isinstance(x, dict) else x


def from_cache(index: dict) -> dict[str, list[dict]]:
    """Harvested FundingRound entities -> company -> rounds, free and offline.

    company_history() above asks a natural-language question per company and
    takes the better part of a minute each, which is why only 197 companies
    have ever been through it. A harvested FundingRound entity carries the
    same facts as structured fields - the issuer, every investor, the date
    and the amount - for the price of one entity fetch.

    Lead attribution is here too, and it was nearly thrown away. A first
    scan looked for is_lead at the top level of each participant edge, found
    none in the rounds fetched that morning, and concluded the graph had no
    lead marker. It sits one level down, on the edge's own properties,
    alongside role - 279 of them across the cache. Reading role but not the
    boolean beside it would have discarded the single fact an investor most
    wants, while reporting confidently that it did not exist.
    """
    out: dict[str, list[dict]] = {}
    for e in index.values():
        if e.get("entity_type") != "FundingRound":
            continue
        rel = e.get("relationships") or {}
        issuer, investors, leads = None, [], []
        for d in ("incoming", "outgoing"):
            for items in (rel.get(d) or {}).values():
                for x in items or []:
                    if not isinstance(x, dict):
                        continue
                    xp = x.get("properties") or {}
                    role = _val(xp.get("role"))
                    nm = (x.get("name") or "").strip()
                    if not nm:
                        continue
                    if role == "ISSUER" and not issuer:
                        issuer = nm
                    elif role == "INVESTOR":
                        investors.append(nm)
                        if _val(xp.get("is_lead")) is True:
                            leads.append(nm)
        if not issuer or not investors:
            continue
        p = e.get("properties") or {}
        amount = _val(p.get("transaction_value"))
        try:
            amount = float(amount) if amount is not None else None
        except (TypeError, ValueError):
            amount = None
        seen, uniq = set(), []
        for nm in investors:
            k = norm.name(nm) or nm.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(nm)
        out.setdefault(issuer.strip().lower(), []).append({
            "stage": _val(p.get("round_label")) or e.get("name") or "",
            "date": (str(_val(p.get("announcement_date")) or "") or None),
            "amount": amount,
            "currency": _val(p.get("transaction_value_units")),
            "investors": uniq,
            "leads": [nm for nm in uniq if nm in set(leads)],
            "source": "cala entity",
        })
    return out
