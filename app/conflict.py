"""M3: onko sijoittaja jo rahoittanut kilpailijasi?

Kilpailijat kysytaan Calalta, ei johdeta embeddingeista. Kaksi syyta:
  1. Cala tuntee kilpailijat nimeltä ja perustelee ne - embedding arvaa.
  2. Se pitaa tuotteen Cala-natiivina eika tuo uutta riippuvuutta.

Konflikti = leikkaus(kilpailijat(F), portfolio(I)).
"""
from . import cala_client as cala, norm
from .models import Signal, Evidence

COMPETITORS_Q = ("Who are the direct competitors of {company}? "
                 "List each competitor's name and what they do.")
# Eksplisiittinen kenttaluettelo, EI dot-notaatiota. Sama syy kuin
# extract.CANONICAL:ssa: '{investor}.portfolio' palautti Northzonelle 58
# riviä mutta Atomicolle ja a16z:lle nolla - LLM-tulkittu dot-notaatio
# valitsee skeeman arvaamalla. Kenttien nimeaminen vakauttaa sen.
PORTFOLIO_Q = ("List the portfolio companies that {investor} has invested in. "
               "For each company give: the company name and its sector.")

# Sanat, jotka eivat erota toimialoja toisistaan.
_STOP = {"and", "the", "for", "with", "that", "platform", "company", "software",
         "solution", "solutions", "technology", "technologies", "services",
         "service", "based", "its", "their", "offering", "provider", "tools"}


def competitors(company: str, **kw) -> list[dict]:
    """[{'name','what'}] - Calan nimeamat suorat kilpailijat.

    Huom: 'what'-kentta voi jaada tyhjaksi - Cala palauttaa joskus pelkat
    nimet. Konfliktin tunnistus ei siita karsi, mutta perustelu korttiin
    haetaan silloin erikseen /knowledge/search-endpointista.
    """
    resp = cala.query(COMPETITORS_Q.format(company=company), **kw) or {}
    out = []
    for r in resp.get("results") or []:
        if isinstance(r, dict) and (n := r.get("name")):
            what = r.get("what they do") or r.get("description") or r.get("what") or ""
            out.append({"name": str(n).strip(), "what": str(what).strip()})
    return out


def portfolio(investor: str, **kw) -> list[dict]:
    """[{'name','sector'}] - sijoittajan portfolioyhtiot."""
    resp = cala.query(PORTFOLIO_Q.format(investor=investor), **kw) or {}
    out = []
    for r in resp.get("results") or []:
        if isinstance(r, dict) and (n := r.get("name")):
            out.append({"name": str(n).strip(),
                        "sector": str(r.get("sector") or "").strip()})
    return out


def _tokens(s: str) -> set[str]:
    return {w for w in "".join(c if c.isalnum() else " " for c in s.lower()).split()
            if len(w) > 3 and w not in _STOP}


def matches(comps: list[dict], port: list[dict]) -> list[dict]:
    """ALL portfolio companies that are named competitors, not just the first.

    The conflict map needs every edge: a fund backing two of your competitors
    is a stronger signal than one backing a single competitor.
    """
    by_name = {norm.name(c["name"]): c for c in comps or []}
    out = []
    for p in port or []:
        if (c := by_name.get(norm.name(p["name"]))):
            out.append({"competitor": p["name"], "sector": p.get("sector", ""),
                        "what": c.get("what", "")})
    return out


def detect(founder_company: str, founder_desc: str,
           comps: list[dict], port: list[dict]) -> Signal:
    """Puhdas funktio: ei API-kutsuja, jotta testattavissa.

    🔴 portfolioyhtio on Calan nimeama kilpailija
    🟡 portfolioyhtion sektori/kuvaus osuu founderin alaan
    🟢 ei osumaa
    ⚪ portfoliota ei saatu
    """
    if not port:
        return Signal("conflict", None, "⚪", "Portfolio unavailable", 0, "Low")

    hits = matches(comps, port)
    if hits:
        names = ", ".join(h["competitor"] for h in hits)
        t = f"Backs your competitor: {names}" if len(hits) == 1 \
            else f"Backs {len(hits)} of your competitors: {names}"
        return Signal("conflict", 1.0, "🔴", t, len(port), "High",
                      [Evidence(f"{h['competitor']}: {h['what'][:150]}"
                                if h["what"] else h["competitor"]) for h in hits])

    # Ei nimiosumaa -> katso osuuko toimiala.
    fv = _tokens(founder_desc) | _tokens(" ".join(c["what"] for c in comps))
    best, best_p = 0.0, None
    for p in port:
        pv = _tokens(f"{p['name']} {p['sector']}")
        if not pv:
            continue
        j = len(fv & pv) / len(pv)
        if j > best:
            best, best_p = j, p

    if best >= 0.5 and best_p:
        return Signal("conflict", best, "🟡", f"Adjacent: {best_p['name']}",
                      len(port), "Medium",
                      [Evidence(f"{best_p['name']} ({best_p['sector']})")])
    return Signal("conflict", 0.0, "🟢", "No competitor in portfolio",
                  len(port), "Korkea" if len(port) >= 10 else "Medium", [])


def check(founder_company: str, founder_desc: str, investor: str, **kw) -> Signal:
    """Taysi tarkistus (tekee 2 Cala-kyselya, ~45 s kylmana)."""
    return detect(founder_company, founder_desc,
                  competitors(founder_company, **kw), portfolio(investor, **kw))
