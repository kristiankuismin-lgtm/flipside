"""Company registries, asked directly, one per country.

Cala's own source list is full of them - GLEIF 360 times, Companies House
310, PRH 101 - which means the facts we want are in public registers and we
have only ever seen them second-hand, through whatever Cala happened to read.
Asking the register ourselves costs no Cala credits, is not rate-limited the
way Cala is, and answers for companies Cala does not hold at all: PRH knows
Gosta Labs Oy, registered 2023-10-25, and Cala holds it with four industry
edges and no rounds.

Every adapter here was tested against the live endpoint before it was
written, and the ones that are not here failed that test rather than being
forgotten:

    Finland      PRH avoindata                    open, keyless, by name
    Norway       Brønnøysund enhetsregisteret     open, keyless, by name
    Denmark      cvrapi.dk                        open, keyless, by name
    France       recherche-entreprises.api.gouv   open, keyless, by name
    Estonia      ariregister autocomplete         open, keyless, by name
    United States SEC EDGAR                       open, needs a CIK, and a
                                                  declared contact in the UA
    anywhere     GLEIF                            open, keyless, by legal name

NOTE, and it is a real one: datasets.py already had Finland, Norway and
GLEIF for the older /registry endpoint, with a different record shape and
its own tests. This module has the richer adapters - company form, line of
business, the situations field - and is where new countries go. The two
should be one, and consolidating them properly means rewriting the shape
those tests assert, which is not a thing to do in the last hours before a
deadline. It is written down here rather than left for someone to find.

    United Kingdom   Companies House  401 without a free API key
    Switzerland      Zefix            401
    Netherlands      KVK              key required
    Germany          Handelsregister  no API; bulk only
    Sweden, Italy, Spain, Ireland     closed or paid

What comes back is normalised to one shape, and the country and source
travel with it: a founding date from PRH and one inferred from a press
release are not the same claim, and a reader should be able to see which
they have.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

import httpx

DB = os.getenv("REGISTRY_DB", "registry.sqlite")
TTL = 30 * 86400
UA = "Flipside/0.1 (Junction hackathon; kristiank@inven.ai)"
# The SEC asks callers to declare who they are in the User-Agent, and
# returns 403 to anyone who does not. That is their rule, not a workaround.
SEC_UA = "Flipside Junction Hackathon kristiank@inven.ai"

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("PRAGMA busy_timeout=10000")
_conn.execute("CREATE TABLE IF NOT EXISTS r (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()


def _cached(k):
    row = _conn.execute("SELECT v, ts FROM r WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < TTL:
        return json.loads(row[0])
    return None


def _store(k, v):
    with _lock:
        _conn.execute("REPLACE INTO r VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


ENDPOINT = {
    "gleif": "https://api.gleif.org/api/v1/lei-records",
    "prh": "https://avoindata.prh.fi/opendata-ytj-api/v3/companies",
    "brreg": "https://data.brreg.no/enhetsregisteret/api/enheter",
    "cvr": "https://cvrapi.dk/api",
    "fr": "https://recherche-entreprises.api.gouv.fr/search",
    "ee": "https://ariregister.rik.ee/est/api/autocomplete",
    "sec": "https://data.sec.gov/submissions/CIK{cik}.json",
}


def raw(which: str, params=None, *, ua=UA, cik: str = "") -> dict:
    """One register's raw response, cached.

    Both record shapes in this codebase - the rich one here and the legacy
    one datasets.py returns - now parse from this, so there is one place
    that knows each register's URL and one cache behind it.
    """
    url = ENDPOINT[which].format(cik=cik) if which == "sec" else ENDPOINT[which]
    key = f"raw:{which}:{json.dumps(params, sort_keys=True)}:{cik}"
    hit = _cached(key)
    if hit is not None:
        return hit
    d = _get(url, params, ua=ua)
    _store(key, d)
    return d


def _get(url, params=None, *, ua=UA, timeout=20):
    r = httpx.get(url, params=params, headers={"User-Agent": ua}, timeout=timeout,
                  follow_redirects=True)
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}")
    return r.json()


_DMY = re.compile(r"^(\d{1,2})/(\d{1,2})\s*-\s*(\d{4})$")


def _date(v) -> str | None:
    """One date format out, whatever the register writes.

    cvrapi returns "12/12 - 2025". A reader comparing two founding dates
    should not have to notice which country each came from.
    """
    if not v:
        return None
    t = str(v).strip()
    m = _DMY.match(t)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{int(mo):02d}-{int(d):02d}"
    return t[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", t) else t


def _rec(**kw) -> dict:
    """One shape, whatever the register calls its fields."""
    base = {"name": None, "id": None, "registered": None, "status": None,
            "address": None, "website": None, "country": None, "source": None,
            "source_url": None, "form": None, "business_line": None}
    base.update({k: v for k, v in kw.items() if v not in (None, "", [])})
    return base


# ------------------------------------------------------------ Finland
def _en(descriptions) -> str | None:
    """PRH writes everything three times. languageCode 3 is the English one."""
    for d in descriptions or []:
        if str(d.get("languageCode")) == "3" and d.get("description"):
            return d["description"]
    return (descriptions or [{}])[0].get("description")


def finland(name: str, *, getter=None) -> dict | None:
    d = (getter or _get)("https://avoindata.prh.fi/opendata-ytj-api/v3/companies",
                         {"name": name})
    for c in (d.get("companies") or [])[:1]:
        names = [n.get("name") for n in (c.get("names") or []) if n.get("name")]
        bid = c.get("businessId")
        bid = bid if isinstance(bid, dict) else {"value": bid}
        addr = next((a for a in (c.get("addresses") or [])), {}) or {}
        street = " ".join(filter(None, [
            addr.get("street"), str(addr.get("buildingNumber") or ""),
            addr.get("postCode"),
            ((addr.get("postOffices") or [{}])[0] or {}).get("city")]))
        site = c.get("website")
        site = site.get("url") if isinstance(site, dict) else site
        # PRH's `status` is an undocumented numeric code and we do not decode
        # it. companySituations is the field that carries bankruptcy,
        # liquidation and restructuring, and an empty list is a real answer:
        # nothing adverse on record.
        sits = c.get("companySituations") or []
        status = ("; ".join(filter(None, (_en(x.get("descriptions")) for x in sits)))
                  or "nothing adverse on record")
        return _rec(name=names[0] if names else name,
                    id=bid.get("value"),
                    # The company is registered when its business ID is, not
                    # when its current name was.
                    registered=_date(bid.get("registrationDate")),
                    status=status,
                    form=_en((c.get("companyForms") or [{}])[0].get("descriptions")),
                    business_line=_en((c.get("mainBusinessLine") or {}).get("descriptions")),
                    address=street.strip() or None, website=site,
                    country="FI", source="PRH avoindata",
                    source_url="https://avoindata.prh.fi")
    return None


# ------------------------------------------------------------- Norway
def norway(name: str, *, getter=None) -> dict | None:
    d = (getter or _get)("https://data.brreg.no/enhetsregisteret/api/enheter",
                         {"navn": name, "size": 1})
    for e in ((d.get("_embedded") or {}).get("enheter") or [])[:1]:
        a = e.get("forretningsadresse") or {}
        return _rec(name=e.get("navn"), id=e.get("organisasjonsnummer"),
                    registered=_date(e.get("registreringsdatoEnhetsregisteret")),
                    form=(e.get("organisasjonsform") or {}).get("beskrivelse"),
                    status="dissolved" if e.get("slettedato") else "active",
                    address=", ".join(filter(None, (a.get("adresse") or [None])[:1]
                                             + [a.get("postnummer"), a.get("poststed")])),
                    country="NO", source="Brønnøysundregistrene",
                    source_url="https://data.brreg.no")
    return None


# ------------------------------------------------------------ Denmark
def denmark(name: str, *, getter=None) -> dict | None:
    d = (getter or _get)("https://cvrapi.dk/api",
                         {"search": name, "country": "dk"})
    if not d or not d.get("name"):
        return None
    return _rec(name=d.get("name"), id=str(d.get("vat") or "") or None,
                registered=_date(d.get("startdate")),
                form=d.get("companydesc"), business_line=d.get("industrydesc"),
                status="active" if not d.get("enddate") else "ceased",
                address=", ".join(filter(None, [d.get("address"), d.get("zipcode"),
                                                d.get("city")])),
                website=d.get("website"), country="DK", source="CVR (cvrapi.dk)",
                source_url="https://cvrapi.dk")


# ------------------------------------------------------------- France
def france(name: str, *, getter=None) -> dict | None:
    d = (getter or _get)("https://recherche-entreprises.api.gouv.fr/search",
                         {"q": name, "per_page": 1})
    for c in (d.get("results") or [])[:1]:
        s = c.get("siege") or {}
        return _rec(name=c.get("nom_complet") or c.get("nom_raison_sociale"),
                    id=c.get("siren"), registered=_date(c.get("date_creation")),
                    business_line=c.get("activite_principale"),
                    status="active" if c.get("etat_administratif") == "A" else "ceased",
                    address=s.get("adresse"), country="FR",
                    source="recherche-entreprises (annuaire-entreprises)",
                    source_url="https://recherche-entreprises.api.gouv.fr")
    return None


# ------------------------------------------------------------ Estonia
def estonia(name: str, *, getter=None) -> dict | None:
    d = (getter or _get)("https://ariregister.rik.ee/est/api/autocomplete",
                         {"q": name, "results_count": 1})
    for c in (d.get("data") or [])[:1]:
        return _rec(name=c.get("name"), id=str(c.get("reg_code") or "") or None,
                    country="EE", source="Äriregister",
                    source_url="https://ariregister.rik.ee")
    return None


# ------------------------------------------------- United States (by CIK)
def sec(cik: str, *, getter=None) -> dict | None:
    """SEC EDGAR, which answers on a CIK rather than a name.

    We harvest `cik` as a property from Cala, so this is reachable for
    exactly the companies that carry one.
    """
    c = re.sub(r"\D", "", str(cik or ""))
    if not c:
        return None
    d = (getter or _get)(f"https://data.sec.gov/submissions/CIK{c.zfill(10)}.json",
                         ua=SEC_UA)
    a = (d.get("addresses") or {}).get("business") or {}
    return _rec(name=d.get("name"), id=str(d.get("cik") or c),
                registered=None,
                status="registered" if d.get("name") else None,
                address=", ".join(filter(None, [a.get("street1"), a.get("city"),
                                                a.get("stateOrCountry"),
                                                a.get("zipCode")])),
                website=d.get("website") or None,
                country=d.get("stateOfIncorporation") or "US",
                source="SEC EDGAR", source_url="https://data.sec.gov")


# ----------------------------------------------------- anywhere (GLEIF)
def gleif(name: str, *, getter=None) -> dict | None:
    d = (getter or _get)("https://api.gleif.org/api/v1/lei-records",
                         {"filter[entity.legalName]": name, "page[size]": 1})
    for rec in (d.get("data") or [])[:1]:
        at = rec.get("attributes") or {}
        ent = at.get("entity") or {}
        a = ent.get("legalAddress") or {}
        return _rec(name=(ent.get("legalName") or {}).get("name"),
                    id=at.get("lei"),
                    status=(ent.get("status") or "").lower() or None,
                    address=", ".join(filter(None, (a.get("addressLines") or [])
                                             + [a.get("postalCode"), a.get("city")])),
                    country=a.get("country"), source="GLEIF",
                    source_url="https://search.gleif.org")
    return None


# A registry per country, and the honest reason where there is none.
BY_COUNTRY = {"FI": finland, "NO": norway, "DK": denmark, "FR": france,
              "EE": estonia}
NEEDS_A_KEY = {"GB": "Companies House: free API key required",
               "CH": "Zefix: authenticated",
               "NL": "KVK: key required",
               "IE": "CRO: key required"}
NO_OPEN_API = {"DE": "Handelsregister publishes no API; bulk extracts only",
               "SE": "Bolagsverket is paid",
               "IT": "registroimprese is paid",
               "ES": "no open company API"}


_LEGAL = re.compile(
    r"\b(oy|oyj|ab|abp|a/s|as|aps|ivs|sarl|sas|sa|sasu|gmbh|ltd|limited|llc|"
    r"inc|plc|nv|bv|lp|l\.p|gp|ky|kb|holding|holdings|group|company|co)\b", re.I)


def _tokens(s: str) -> set[str]:
    """Words that are part of the name, legal form removed."""
    return {t for t in re.split(r"[^a-z0-9]+", _LEGAL.sub(" ", (s or "").lower()))
            if len(t) > 1}


def grade(asked: str, found: str) -> str:
    """How well the registry's answer matches what we asked for.

    A register answers whatever is closest, and closest is sometimes a
    different company: asking for "Alven", the French venture firm, returns
    a company of that name whose line of business is restaurants. The grade
    travels with the record so a wrong match is visible rather than becoming
    a founding date on a fund.
    """
    a, f = _tokens(asked), _tokens(found)
    if not a or not f:
        return "none"
    if a == f:
        return "exact"
    # Whole words, not prefixes: "Abridge" is not "Abridgement Holding AB",
    # and a substring test says it is. One name being a subset of the other
    # is a related entity - "Northzone" and "NORTHZONE VII L.P." - which is
    # a partial match and not the same company.
    if a <= f or f <= a:
        return "partial"
    return "none"


def lookup(name: str, *, cc: str | None = None, cik: str | None = None,
           getters: dict | None = None) -> dict | None:
    """The best registry answer for this company, or None.

    Order: the country's own register when we know the country and it has
    one, then GLEIF, which covers anything with an LEI anywhere. A miss is
    None; it is never a guess from another country's register.
    """
    getters = getters or {}
    key = f"reg:{(cc or '').upper()}:{(name or '').lower()}:{cik or ''}"
    hit = _cached(key)
    if hit is not None:
        return hit or None

    tried = []
    if cik:
        tried.append(("sec", lambda: sec(cik, getter=getters.get("sec"))))
    fn = BY_COUNTRY.get((cc or "").upper())
    if fn:
        tried.append((cc, lambda: fn(name, getter=getters.get(cc))))
    tried.append(("gleif", lambda: gleif(name, getter=getters.get("gleif"))))

    for _, call in tried:
        try:
            out = call()
        except Exception:                             # noqa: BLE001
            continue
        if out and out.get("name"):
            out["match"] = grade(name, out["name"])
            if out["match"] == "none":
                continue        # the register answered about somebody else
            _store(key, out)
            return out
    _store(key, "")
    return None


def why_not(cc: str) -> str | None:
    """Why a country has no adapter, so the gap is a fact and not a silence."""
    c = (cc or "").upper()
    return NEEDS_A_KEY.get(c) or NO_OPEN_API.get(c)
