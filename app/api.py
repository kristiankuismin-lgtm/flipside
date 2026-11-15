"""FastAPI: founderin syote -> jarjestetty sijoittajalista kortteineen.

Demo ajetaan CALA_CACHE_ONLY=1, jolloin yksikaan pyynto ei odota Calaa
(kyselyt kestavat 20-60 s). Puuttuva data raportoidaan rehellisesti
sen sijaan etta se peitettaisiin nollana.
"""
import json
import re
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import depth as DEPTH, metrics as M, conflict as C, warmpath as W
from . import norm
from .cala_client import CacheMiss, CalaError
from .company_rounds import company_history
from .extract import investor_rounds

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
CONVICTION = ROOT / "conviction.json"
BACKTEST = ROOT / "backtest.json"
PROFILES = ROOT / "slush_profiles.json"

# Demoprofiilit: rikas kuvaus parantaa Calan kilpailijahakua merkittavasti.
PRESETS = {
    "gosta labs": dict(
        query=("Gosta Labs (gostalabs.com), the Finnish healthtech startup whose "
               "AI assistant Gosta Aide writes clinical documentation for doctors"),
        desc="AI assistant writing clinical documentation for doctors and hospitals",
        # Nykyiset sijoittajat = lampimien reittien lahde, eivat pitch-kohteita.
        my_investors=["Voima Ventures", "Terveystalo", "Reaktor"]),
}

app = FastAPI(title="Flipside")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Req(BaseModel):
    company: str
    stage: str = "series a"
    limit: int = 14
    description: str = ""
    investors: list[str] | None = None
    my_investors: list[str] | None = None
    investor: str | None = None        # /outreach: which fund to write to
    question: str | None = None        # /ask-neo
    rules: list[str] | None = None     # /alerts
    seen_conflicts: list[str] | None = None


_DOMAINS = None


_DOMAIN_STAMP = None


def _domains() -> dict:
    """company (lowercased) -> website, from everything already fetched.

    Relationship edges carry no website, so a logo would always fall back to a
    monogram. These files already hold the domains.

    Rebuilt when one of those files changes, because the domain resolver runs
    alongside the server and its output should reach the page it is for
    without a restart.
    """
    global _DOMAINS, _DOMAIN_STAMP
    files = ["slush_profiles.json", "portfolio_places.json",
             "investor_domains.json", "fund_universe.json"]
    stamp = tuple((ROOT / f).stat().st_mtime if (ROOT / f).exists() else 0
                  for f in files)
    if _DOMAINS is not None and _DOMAIN_STAMP == stamp:
        return _DOMAINS
    _DOMAIN_STAMP = stamp
    out = {}
    def add(name, web):
        if name and web:
            out.setdefault(str(name).strip().lower(), web)
    for fname, walk in (
        ("slush_profiles.json", lambda d: ((r.get("name"), r.get("website")) for r in d)),
        ("portfolio_places.json", lambda d: ((k, v.get("website")) for k, v in d.items())),
        ("investor_domains.json", lambda d: ((k, v.get("website")) for k, v in d.items())),
        ("fund_universe.json", lambda d: ((k, v.get("website")) for k, v in d.items())),
    ):
        f = ROOT / fname
        if not f.exists():
            continue
        try:
            for n, w in walk(json.loads(f.read_text())):
                add(n, w)
        except (ValueError, AttributeError, TypeError):
            pass
    # Everything already fetched from Cala carries a website property. The
    # hand-built files cover 49 of 664 funds; this covers the rest.
    try:
        from . import cache_index
        for n, w in cache_index.websites().items():
            add(n, w)
    except Exception:
        pass
    _DOMAINS = out
    return out


_ROUNDS_BY_CO = None


def _rounds_by_company() -> dict:
    """company (lowercased) -> its known rounds, for second-order weighting."""
    global _ROUNDS_BY_CO
    if _ROUNDS_BY_CO is not None:
        return _ROUNDS_BY_CO
    out = {}
    if CONVICTION.exists():
        try:
            for c in json.loads(CONVICTION.read_text()).get("companies") or []:
                out[c["company"].strip().lower()] = c.get("rounds") or []
        except ValueError:
            pass
    w = ROOT / "exhibitor_rounds.json"
    if w.exists():
        try:
            for v in json.loads(w.read_text()).values():
                out.setdefault(v["name"].strip().lower(), v.get("rounds") or [])
        except ValueError:
            pass
    # Harvested FundingRound entities. The two files above cost a
    # natural-language query per company and between them cover a few hundred;
    # this is every round we have ever fetched, for free. A company already
    # described by a file keeps that version, because those rounds carry lead
    # attribution and these cannot.
    try:
        from . import company_rounds as CR, cache_index
        for co, rs in CR.from_cache(cache_index.build()).items():
            out.setdefault(co, rs)
    except Exception:
        pass
    _ROUNDS_BY_CO = out
    return out


def _investor_meta() -> dict:
    """Firmographics resolved from Cala's Organization entities."""
    f = ROOT / "investor_domains.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text())
    except ValueError:
        return {}


def _investor_pool() -> list[str]:
    f = ROOT / "investors.txt"
    if not f.exists():
        return []
    return [l.strip() for l in f.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def _safe(fn, *a, **kw):
    """(tulos, virhe). Yksi puuttuva pala ei saa kaataa koko korttia."""
    try:
        return fn(*a, **kw), None
    except (CacheMiss, CalaError) as e:
        return None, f"{type(e).__name__}: {str(e)[:100]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {str(e)[:100]}"


# Tunnettuuden tasot. Sijoittaja, josta ei ole dataa, EI saa nayttaa
# keskinkertaiselta - se on eri asia kuin huono sijoittaja.
MIN_ROUNDS_TO_RANK = 3
GOOD_EVIDENCE = 10


def evidence_depth(n: int) -> str:
    if n >= GOOD_EVIDENCE:
        return "good"
    if n >= MIN_ROUNDS_TO_RANK:
        return "thin"
    return "insufficient"


def analyze_one(inv, company, desc, stage, comps, histories, mine):
    notes = []
    rounds, err = _safe(investor_rounds, inv)
    if err:
        notes.append(f"kierrokset: {err}")
    rounds = rounds or []

    sig = {"lead_rate": M.lead_rate(inv, rounds, stage)}
    # Jos haetussa vaiheessa ei ole otosta, nayta koko historia - rehellisempi
    # kuin ⚪ silloin kun dataa on, mutta eri vaiheesta.
    if sig["lead_rate"].n == 0 and rounds:
        sig["lead_rate"] = M.lead_rate(inv, rounds)

    # M2 vaatii portfolioyhtioiden koko historian (vain cachesta).
    hist = []
    for r in sorted(rounds, key=lambda x: x.date)[:10]:
        h, _ = _safe(company_history, r.company)
        if h:
            hist.extend(h)
    sig["follow_on"], sig["next_round"] = M.follow_on(inv, M.by_company(hist))
    sig["warm_path"] = W.warm_path(inv, mine or [], histories)
    sig["dry_powder"] = M.dry_powder(inv, M.by_company(rounds))

    port, err = _safe(C.portfolio, inv)
    if err:
        notes.append(f"portfolio: {err}")
    # A firm with 30 rounds does not have a zero portfolio - the portfolio
    # query just returned nothing. Fall back to the companies those rounds
    # name, and say which way we counted.
    port_from_rounds = sorted({r.company for r in rounds if r.company})
    portfolio_source = "portfolio query"
    if not port and port_from_rounds:
        port = [{"name": n, "sector": ""} for n in port_from_rounds]
        portfolio_source = "companies in known rounds"
    sig["conflict"] = C.detect(company, desc, comps or [], port or [])
    edges = C.matches(comps or [], port or [])

    meta = _investor_meta().get(inv) or {}
    fit = {"stage": 1.0, "sector": 0.8, "geo": 0.9, "check": 0.8}
    depth = evidence_depth(len(rounds))
    # Ilman riittavaa otosta pisteet olisivat harhaanjohtavia: nayta se.
    score = None if depth == "insufficient" else M.score(fit, sig)
    # Expose the breakdown rather than only the number: a score nobody can
    # take apart is a number to be trusted on faith.
    q, coverage = M.quality(sig)
    months = M.last_activity(sig)
    rf = M.recency_factor(months)
    breakdown = {
        "fit": round(fit["stage"] * .35 + fit["sector"] * .30
                     + fit["geo"] * .20 + fit["check"] * .15, 3),
        "quality": round(q, 3), "coverage": round(coverage, 3),
        "lead_factor": M.lead_factor(sig),
        "conflict_factor": (0 if sig.get("conflict") and sig["conflict"].label == "🔴"
                            else .7 if sig.get("conflict") and sig["conflict"].label == "🟡"
                            else 1),
        "warm_bonus": round(.15 * ((sig.get("warm_path").value or 0)
                                   if sig.get("warm_path") else 0), 3),
        "recency": round(rf, 3),
        "months_since_activity": months,
        "stale": bool(months is not None and months >= M.STALE_AFTER_MONTHS),
        "weights": M.QUALITY_WEIGHTS,
    }
    # Portfolio highlights: the companies this firm actually led into, newest
    # first, so the card shows what they do rather than only how they behave.
    led = [r for r in sorted(rounds, key=lambda x: x.date, reverse=True)
           if norm.matches(inv, r.leads)]
    by_sector = {}
    for c in (port or []):
        sec = (c.get("sector") or "Unknown").strip() or "Unknown"
        by_sector[sec] = by_sector.get(sec, 0) + 1

    return {"investor": inv, "score": score, "rounds_seen": len(rounds),
            "evidence_depth": depth, "portfolio_size": len(port or []),
            "portfolio_source": portfolio_source,
            "backs": [e["competitor"] for e in edges],
            "firm": {"website": meta.get("website"), "hq": meta.get("hq"),
                     "hq_field": meta.get("hq_field"), "founded": meta.get("founded"),
                     "employees": meta.get("employees"),
                     "description": meta.get("description"),
                     "entity_type": meta.get("entity_type"),
                     "hq_source": meta.get("hq_source")},
            "portfolio": [{"name": c["name"], "sector": c.get("sector", "")}
                          for c in (port or [])[:60]],
            "sectors": sorted(by_sector.items(), key=lambda kv: -kv[1])[:8],
            "led_rounds": [{"company": r.company, "stage": r.stage,
                            "date": str(r.date),
                            "amount": r.amount_eur} for r in led[:9]],
            # Exactly the rounds the lead-rate claim is computed over, so the
            # drawer cannot show nine rows under a claim about six of nine at
            # one stage. Same window, same stage filter, same order.
            "stage_rounds": [
                {"company": r.company, "stage": r.stage, "date": str(r.date),
                 "amount": r.amount_eur, "led": norm.matches(inv, r.leads)}
                for r in sorted(
                    (r for r in rounds
                     if r.date >= M.WINDOW
                     and (not stage or norm.stage(r.stage) == norm.stage(stage))),
                    key=lambda x: x.date, reverse=True)],
            "recent_rounds": [{"company": r.company, "stage": r.stage, "date": str(r.date),
                               "amount": r.amount_eur, "led": norm.matches(inv, r.leads)}
                              for r in sorted(rounds, key=lambda x: x.date, reverse=True)[:14]],
            "signals": {k: asdict(v) for k, v in sig.items()},
            "breakdown": breakdown, "notes": notes}


def _own_backers(name: str) -> list[str]:
    """Who already has money in this company, read rather than configured.

    Warm paths are computed from the founder's existing cap table, and that
    list has been a hardcoded preset since the first demo - which meant the
    feature worked for exactly one company and looked like it worked for
    all of them. It is an incoming INVESTED_IN edge on the company, and Cala
    has it: Voima Ventures, Cor Group and Reaktor for Gosta Labs.

    Duplicates are the norm here. Cala holds "Voima Ventures" and "Voima
    Ventures Oy" as separate entities, and a founder reading "two of your
    backers" when one of them is the same fund twice would be right not to
    trust the rest.
    """
    from . import cala_client as cala
    e = _resolve_company(name)
    if not e:
        return []
    try:
        full = cala.get_entity(e["id"], properties=["name"],
                               incoming=["INVESTED_IN"], limit=60,
                               allow_live=True, ttl=7 * 86400,
                               timeout=25, retries=1, interactive=True)
    except Exception:                                 # noqa: BLE001
        full = e
    rows = (((full.get("relationships") or {}).get("incoming") or {})
            .get("INVESTED_IN") or [])
    out, seen = [], set()
    for r in rows:
        nm = (r.get("name") or "").strip()
        key = norm.name(nm)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(nm)
    return out


def _resolve_company(name: str) -> dict | None:
    """The company entity behind a name, from the harvest or from Cala.

    Cache first: a harvested entity carries its whole record, and asking the
    network for something we already hold in full is a second of a demo
    spent on nothing.
    """
    from . import cala_client as cala, graph
    hit = DEPTH.entity(name, types=("Company", "Organization"))
    if hit is None:
        try:
            hit = graph.find_company(name, allow_live=True, ttl=86400)
        except Exception:                             # noqa: BLE001
            return None
    if hit is None or hit.get("relationships"):
        return hit
    # A stub carries a name and nothing else. One fetch with the vocabulary
    # the harvester learned for this type turns it into the whole record -
    # and this is the moment in the run where showing what Cala actually
    # holds is worth a second.
    voc = DEPTH.vocabulary(hit.get("entity_type") or "Company") or {}
    try:
        full = cala.get_entity(hit["id"], properties=voc.get("properties") or None,
                               outgoing=voc.get("outgoing") or None,
                               incoming=voc.get("incoming") or None,
                               limit=200, allow_live=True, ttl=30 * 86400,
                               timeout=25, retries=1, interactive=True)
        return full or hit
    except Exception:                                 # noqa: BLE001
        return hit


@app.post("/analyze")
def analyze(req: Req):
    from . import progress as PG
    key = PG.key_for(req.company, req.stage)
    PG.start(key, req.company)

    p = PRESETS.get(req.company.strip().lower(), {})
    cq = p.get("query") or req.company
    desc = req.description or p.get("desc", "")

    PG.step(key, f"Reading {req.company}", desc[:140], layer="you",
            because="What you build decides who your competitors are, and "
                    "your competitors decide which investors are closed to you.")
    # Resolving the company is fast and the competitor query is not, so do
    # the cheap, informative thing first. A minute of a single unchanging
    # line is the worst moment in this product: it looks indistinguishable
    # from a hang, and the founder has no idea whether Cala has heard of
    # them at all.
    PG.step(key, f"Resolving {req.company} in Cala's graph", layer="cala")
    ent, _ = _safe(_resolve_company, req.company)
    if ent:
        cov = DEPTH.coverage(ent) if ent.get("relationships") else None
        PG.step(key, f"Cala has {ent.get('name')}",
                f"{ent.get('entity_type')}"
                + (f" · {cov['edges']} relationships, {cov['properties']} properties"
                   if cov else " · a stub, not yet read in full"),
                layer="cala",
                because="Everything below is read off this entity, so if this "
                        "is the wrong company nothing after it is worth "
                        "trusting - which is why we show you which one it is.")
    else:
        PG.step(key, f"Cala has no entity named {req.company}", layer="cala",
                because="The screen still runs: competitors are found from the "
                        "description, and the ranking is about the funds. But "
                        "nothing here is anchored to your company record.")
    # Before anything is ranked: is this the round they are actually
    # raising? A Series B list built off a seed is wrong in the way that
    # costs a founder the week.
    from . import stagecheck as SCK
    own = _rounds_by_company().get(norm.name(req.company)) or []
    stage_note = SCK.check(own, req.stage)
    stale_note = SCK.stale(own)
    PG.step(key, f"Checking {req.stage} against your own rounds",
            stage_note["says"][:160],
            layer="cala" if own else "derived",
            because="A fund that only writes cheques at one stage will not "
                    "start with yours, and the funds at the stage you are "
                    "actually at would not be on this list.")

    PG.step(key, "Asking Cala who competes with you",
            "the slow one \u2014 about a minute", layer="cala",
            because="This is a question about meaning, not a lookup: it reads "
                    "descriptions across the graph rather than following an edge.")
    comps, cerr = _safe(C.competitors, cq)
    PG.step(key, f"Cala names {len(comps or [])} competitors",
            ", ".join(c.get("name", "") for c in (comps or [])[:4]), layer="cala",
            because="An investor already in one of these has a reason not to "
                    "take your call, whatever they say on it.")
    pool = req.investors or _investor_pool()[: req.limit]
    # Read, then the preset, then nothing. The preset stays as a fallback
    # for the demo company whose record predates this, and it is no longer
    # the only way a founder gets a warm path.
    mine = req.my_investors or _own_backers(req.company) or p.get("my_investors", [])
    if mine:
        PG.step(key, f"{len(mine)} investors already in {req.company}",
                ", ".join(mine[:4]), layer="cala",
                because="A fund that has been in a round with one of these "
                        "has met them, and an introduction from a shared "
                        "backer is not a cold email.")
    PG.step(key, f"Screening {len(pool)} funds", layer="derived",
            because="Each one is checked against those competitors before "
                    "anything else, because exclusion is cheaper to be sure of "
                    "than fit.")

    # Yhteinen yhtiohistoria-indeksi lampimia reitteja varten. Kootaan kerran
    # kaikkien sijoittajien portfolioyhtioista - vain cachesta.
    all_rounds = []
    for n, i in enumerate(pool, 1):
        rs, _ = _safe(investor_rounds, i)
        for r in sorted(rs or [], key=lambda x: x.date)[:10]:
            h, _ = _safe(company_history, r.company)
            if h:
                all_rounds.extend(h)
        if n % 3 == 0 or n == len(pool):
            PG.step(key, f"Read {n} of {len(pool)} fund histories",
                    f"{len(all_rounds)} rounds so far", layer="cala")
    histories = W.index_histories(all_rounds)
    PG.step(key, f"Indexed {len(all_rounds)} rounds for warm routes",
            layer="derived",
            because="A fund that has been in a round with one of your existing "
                    "backers is an introduction, not a cold email.")

    out = []
    for n, i in enumerate(pool, 1):
        out.append(analyze_one(i, req.company, desc, req.stage, comps, histories, mine))
        if n % 4 == 0 or n == len(pool):
            last = out[-1]
            PG.step(key, f"Scored {n} of {len(pool)} funds",
                    f"{last['investor']}: "
                    f"{'unranked - too little evidence' if last['score'] is None else last['score']}",
                    layer="derived",
                    because="A fund with too few rounds on record stays "
                            "unranked rather than scoring zero, because we do "
                            "not know that it is bad - we know that we cannot tell.")
    # Unranked (insufficient evidence) always last, never mixed in.
    out.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0), x["investor"]))
    # Kilpailija <-> rahasto -kaaret konfliktikarttaa varten.
    edges = [{"investor": x["investor"], "competitor": c}
             for x in out for c in x.get("backs") or []]
    warm = sum(1 for x in out if x["signals"]["warm_path"]["label"] != "\u26aa")
    PG.done(key, f"{len(edges)} conflicts, {warm} warm route"
                 f"{'' if warm == 1 else 's'}")
    from datetime import datetime, timezone
    return {"company": req.company, "stage": req.stage,
            "stage_check": stage_note, "stage_stale": stale_note,
            "own_rounds": own[-4:],
            # Every claim in the UI is datable: a number with no retrieval
            # time cannot be checked, only believed.
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "competitors": comps or [], "competitors_error": cerr,
            "edges": edges, "investors": out}


@app.post("/intake")
async def intake_endpoint(text: str = Form(""),
                          files: list[UploadFile] = File(default=[])):
    """What the founder brought, turned into something the graph can take.

    A founder arriving with a round to raise already has the material. Asking
    them to retype it into a search box is asking them to summarise themselves
    worse than their deck does - so this takes the deck, the spreadsheet or
    the PDF, and pulls out the handful of fields the screen needs.

    Returns the profile with the line of the slide each field came from, plus
    the first reasoning steps, so the founder can see what we understood
    before we spend ninety seconds acting on it.
    """
    from . import intake as IN, progress as PG

    docs = []
    for f in files or []:
        if not f.filename:
            continue
        docs.append(IN.read(await f.read(), f.filename))

    prof = IN.profile(text, docs)
    key = PG.key_for(prof.get("name") or text or "intake", prof.get("stage") or "")
    PG.start(key, prof.get("name") or "your company")

    for d in docs:
        if d.error:
            PG.step(key, f"Could not read {d.name}", d.error, layer="you")
        else:
            PG.step(key, f"Read {d.name}", f"{len(d.lines)} lines of {d.kind}",
                    layer="you")
    if text.strip():
        PG.step(key, "Read what you wrote", f"{len(text.split())} words", layer="you")

    for fld, label, why in (
        ("name", "company", "The name is what we look up in Cala."),
        ("website", "website", "A website resolves to one company; a name "
                               "resolves to every namesake in the registry."),
        ("stage", "round", "Stage decides which funds are even relevant - a "
                           "seed fund in a Series A is a waste of your week."),
        ("round_size", "round size", "A fund that has never written a cheque "
                                     "this size will not start with yours."),
    ):
        if prof.get(fld):
            src = (prof.get("sources") or {}).get(fld) or {}
            PG.step(key, f"{label.capitalize()}: {prof[fld]}",
                    f"from {src.get('where', 'what you wrote')}", layer="you",
                    because=why)
    if prof.get("markets"):
        PG.step(key, "Market: " + ", ".join(prof["markets"]), layer="derived",
                because="Matched against the same vocabulary we read investors "
                        "with, so 'clinical documentation' and 'digital health "
                        "care provider' can be seen to be the same market.")
    if not prof.get("name"):
        PG.step(key, "No company name found",
                "we need one thing to look up", layer="you",
                because="Everything after this is read off your company's "
                        "record in Cala. Without a name or a website there is "
                        "nothing to resolve, so the screen cannot start.")

    prof["run_key"] = key
    prof["steps"] = PG.get(key)["steps"]
    return prof


@app.get("/reasoning")
def reasoning(key: str = "", company: str = "", stage: str = ""):
    """The live log of what the screen is doing and why."""
    from . import progress as PG
    return PG.get(key or PG.key_for(company, stage))


@app.get("/health")
def health():
    from . import cala_client as cala
    n = 0
    if CONVICTION.exists():
        try:
            n = len(json.loads(CONVICTION.read_text()).get("companies") or [])
        except Exception:
            n = 0
    from . import cache_index
    idx = cache_index.stats()
    return {"ok": True, "cache_only": cala.CACHE_ONLY, "has_key": bool(cala.KEY),
            "pool": len(_investor_pool()), "conviction_n": n,
            # What the product is actually standing on, so the UI can say it
            # rather than implying everything is live.
            "entities_cached": idx["entities"],
            "people_cached": idx["by_type"].get("Person", 0),
            "rounds_cached": sum(len(v or []) for v in _rounds_by_company().values())}


@app.get("/backtest")
def backtest():
    """Accuracy: does insider conviction predict stage progression?"""
    if not BACKTEST.exists():
        return JSONResponse({"error": "Backtest not run yet."}, status_code=200)
    d = json.loads(BACKTEST.read_text())
    d.pop("rows", None)          # the UI only needs the summary
    return d


_MAP_CACHE: dict = {}
# Files the map is computed from. When none of them has changed, neither has
# the map, and recomputing 619 fund placements per request is a quarter of a
# second spent on arriving at the same answer.
_MAP_INPUTS = ("slush_profiles.json", "portfolio_places.json",
               "investor_domains.json", "fund_universe.json",
               "exhibitor_rounds.json", "conviction.json", "cache.sqlite")


def _map_stamp():
    out = []
    for f in _MAP_INPUTS:
        p = ROOT / f
        out.append(p.stat().st_mtime if p.exists() else 0)
    return tuple(out)


@app.get("/map")
def map_data():
    stamp = _map_stamp()
    if _MAP_CACHE.get("stamp") == stamp:
        return _MAP_CACHE["data"]
    data = _map_data_uncached()
    _MAP_CACHE.update(stamp=stamp, data=data)
    return data


def _map_data_uncached():
    """Slush 2026 exhibitors placed on a map, with conviction where we have it."""
    from . import geo
    if not PROFILES.exists():
        return JSONResponse({"error": "Exhibitor profiles not fetched yet.",
                             "points": [], "placed": 0, "total": 0}, status_code=200)
    profs = json.loads(PROFILES.read_text())
    ok = [p for p in profs if not p.get("error")]

    # Funding status from the graph walk. Conviction needs two rounds and
    # prior investors to compare against, which almost no exhibitor has - so
    # the map answers the question the data can actually support: who on this
    # floor has raised at all?
    walked = {}
    wpath = ROOT / "exhibitor_rounds.json"
    if wpath.exists():
        try:
            walked = json.loads(wpath.read_text())
        except ValueError:
            walked = {}

    conv = {}
    if CONVICTION.exists():
        for c in json.loads(CONVICTION.read_text()).get("companies") or []:
            conv[c["company"].lower()] = c["score"]

    from . import geocode
    pts, unplaced, exact = [], 0, 0
    for p in ok:
        hq = p.get("hq")
        # Precise street coordinate when we have one; city centroid otherwise,
        # flagged so the map can show it differently rather than pretend.
        fine = geocode.lookup(hq, cache_only=True) if hq else None
        if fine:
            lat, lon, precise = fine["lat"], fine["lon"], True
            cc = (geo.locate(hq) or (0, 0, "??"))[2]
            exact += 1
        else:
            loc = geo.locate(hq)
            if not loc:
                unplaced += 1
                continue
            lat, lon, cc = loc
            precise = False
        w = walked.get(p["id"])
        n_rounds = len(w["rounds"]) if w else None
        status = ("unknown" if n_rounds is None else
                  "none" if n_rounds == 0 else
                  "once" if n_rounds == 1 else "multiple")
        last = (w["rounds"][-1] if w and w["rounds"] else None)
        conflict = geo.contradicts(hq, cc)
        if conflict:
            unplaced += 1          # the address disagrees with itself: do not plot
            continue
        pts.append({"name": p["name"], "id": p.get("id"),
                    "lat": lat, "lon": lon, "cc": cc,
                    "precise": precise, "hq": hq, "website": p.get("website"),
                    "industries": (p.get("industries") or [])[:2],
                    "score": conv.get(p["name"].lower()),
                    "rounds": n_rounds, "status": status,
                    "last_round": ({"stage": last["stage"], "date": last["date"]}
                                   if last else None),
                    "source": p.get("hq_source")})
    # Second layer: the funds themselves. The map is about where capital and
    # companies sit, not only who booked a stand at Slush.
    funds = []
    disputed_funds: list[str] = []
    dom = {}
    # The hand-typed list first, then every investor the cached rounds name -
    # 664 firms that actually appear in this ecosystem rather than 30 someone
    # remembered. Later keys win, so the broader file fills the gaps.
    for fname in ("investor_domains.json", "fund_universe.json"):
        fpath = ROOT / fname
        if not fpath.exists():
            continue
        try:
            for k, v in json.loads(fpath.read_text()).items():
                if v.get("hq") or k not in dom:
                    dom[k] = {**dom.get(k, {}), **v}
        except ValueError:
            pass

    # Third source: the harvest. A fetched entity carries registered_address
    # and headquarters_address as sourced properties, and HAS_HEADQUARTERS_IN
    # as an edge. None of it was ever read here, so funds with a perfectly
    # good address in Cala - Index Ventures, Icebreaker.vc - were simply
    # absent from the map, which reads as "we do not cover them".
    from_cala = overruled = 0
    for name, v in dom.items():
        e = DEPTH.entity(name, types=("Organization", "Company"))
        if not e:
            continue
        props = {f["key"]: f["value"] for f in DEPTH.facts(e)}
        hq_addr = props.get("headquarters_address")
        addr = hq_addr or props.get("registered_address")
        if not addr:
            # No street, but the graph may still name the country.
            where = [x["name"] for x in DEPTH.presence(e)
                     if x["kind"] == "headquarters"]
            addr = where[0] if where else None
        if not addr:
            continue
        if not v.get("hq"):
            v["hq"] = str(addr)
            v["hq_source"] = "cala"
            v.setdefault("description", e.get("description") or "")
            from_cala += 1
        elif addr and str(addr).strip() != str(v["hq"]).strip():
            # Our address for Index Ventures was TENANCY 10, MARINA HOUSE,
            # MAHE, EDEN ISLAND - the Seychelles - because the name-to-LEI
            # join lands on namesakes abroad. Cala holds a headquarters
            # address with the documents it was read from, which is better
            # evidence than a registry string matched on a name. The old one
            # is kept as evidence rather than deleted.
            v["hq_registry"] = v["hq"]
            v["hq"] = str(addr)
            v["hq_source"] = "cala"
            v["hq_note"] = ("The address we had came from a name-to-identifier "
                            "join, which lands on namesakes abroad - it put "
                            "Index Ventures in the Seychelles and Accel in "
                            "France. Cala holds an address for this firm with "
                            "the documents it was read from, so that one is "
                            "used and the registry string is kept as evidence.")
            overruled += 1

    # An individual angel is a real investor and not a firm with an office.
    # Pinning Peter Thiel to a city is a category error, and counting him as
    # a fund we failed to find a website for made two numbers wrong in the
    # same direction.
    people = {k for k, v in dom.items() if (v or {}).get("kind") == "person"}
    notent = {k for k, v in dom.items() if (v or {}).get("kind") == "not an entity"}
    for k in people | notent:
        dom.pop(k, None)

    if True:
        for name, v in dom.items():
            hq = v.get("hq")
            if not hq:
                continue
            fine = geocode.lookup(hq, cache_only=True)
            loc = geo.locate(hq)
            if fine:
                lat, lon, precise = fine["lat"], fine["lon"], True
            elif loc:
                lat, lon, precise = loc[0], loc[1], False
            else:
                continue
            cc = (loc or (0, 0, "??"))[2]
            # The registry address and the firm's own description disagree
            # often enough to matter: the GLEIF name->LEI join lands on a
            # namesake abroad. Believe the description, lose the precision,
            # and say so - a Munich fund pinned to Tampere is worse than a
            # Munich fund pinned to Munich without a street.
            note, hq_registry, why = None, None, None
            alt = geo.claimed_place(v.get("description"))
            if loc is None and alt:
                # We never had a country for this address - the description is
                # the only location we have, not a second opinion overruling
                # a first one. Different situation, different sentence.
                why = "unresolved"
                note = (f"The registry address could not be resolved to a "
                        f"country. Placed from the firm's own description "
                        f"({alt['label']}).")
            elif geo.disputed(v.get("description"), cc) and alt:
                why = "disputed"
                note = (f"Registry address resolves to {cc}; the firm describes "
                        f"itself as based in {alt['label']}. The name-to-LEI "
                        f"join lands on namesakes abroad, so the description "
                        f"wins and the registry string is kept as evidence.")
            if why:
                lat, lon, cc, precise = alt["lat"], alt["lon"], alt["cc"], False
                hq_registry, hq = hq, alt["label"]
                disputed_funds.append({"name": name, "why": why})
            # A fund we know only the country of sits on the capital, which
            # looks exactly as precise as a street address. Say which it is.
            if v.get("hq_precision") == "country":
                precise = False
                note = note or (
                    f"Cala names {hq} as where this firm is, with no address. "
                    f"The pin is the country, not the office.")
            funds.append({"name": name, "id": v.get("id"), "lat": lat, "lon": lon,
                          "cc": cc, "precise": precise,
                          "precision": "country" if v.get("hq_precision") == "country"
                                       else ("street" if precise else "city"),
                          "hq_note": note,
                          "hq_why": why,
                          "hq": hq, "hq_registry": hq_registry,
                          "website": v.get("website"),
                          "description": (v.get("description") or "")[:200],
                          "founded": v.get("founded"), "employees": v.get("employees"),
                          "rounds_seen": v.get("seen"),
                          "source": v.get("hq_source") or v.get("source"),
                          "kind": "fund"})

    # Third layer: the funded universe. Slush 2026 is the only event in Cala
    # with a participant list, so "more events" was a dead end - but the
    # portfolio companies behind the founder screen have all raised, which
    # makes them a better map than a floor of pre-funding exhibitors.
    portfolio = []
    ppath = ROOT / "portfolio_places.json"
    if ppath.exists():
        try:
            for nm, v in json.loads(ppath.read_text()).items():
                if v.get("lat") is None:
                    continue
                rs = _rounds_by_company().get(nm.strip().lower())
                portfolio.append({"name": nm, "id": v.get("entity_id"),
                                  "lat": v["lat"], "lon": v["lon"],
                                  "cc": v.get("cc"), "precise": v.get("precise", False),
                                  "hq": v.get("hq"), "website": v.get("website"),
                                  "source": v.get("source"), "kind": "portfolio",
                                  "rounds": len(rs) if rs is not None else None,
                                  "status": ("multiple" if rs and len(rs) >= 2
                                             else "once" if rs else "unknown")})
        except ValueError:
            pass

    from collections import Counter
    status_counts = Counter(p["status"] for p in pts)
    return {"event": "Slush 2026", "event_date": "2026-11-18",
            "total_exhibitors": len(profs), "profiles_fetched": len(ok),
            "placed": len(pts), "exact": exact, "unplaced": unplaced,
            "walked": len(walked), "status": dict(status_counts),
            "disputed_funds": disputed_funds,
            "points": pts, "funds": funds, "portfolio": portfolio,
            "funds_from_cala": from_cala,
            "funds_corrected_by_cala": overruled,
            # Said out loud so the coverage figure means what it says.
            "individuals_not_mapped": len(people),
            "non_entities_dropped": len(notent)}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-store"})


# Every front-end file used to need its own hand-written route, and adding
# ask.js without one produced a 404 and a blank Ask box. One guarded route
# instead: a flat filename, a known extension, inside web/ and nowhere else.
_WEB_TYPES = {".js": "application/javascript", ".css": "text/css",
              ".json": "application/json", ".svg": "image/svg+xml",
              ".png": "image/png", ".ico": "image/x-icon",
              ".woff2": "font/woff2", ".map": "application/json"}


@app.get("/{filename}.{ext}")
def web_asset(filename: str, ext: str):
    """Static files from web/, by exact name. No directories, no traversal."""
    name = f"{filename}.{ext}"
    media = _WEB_TYPES.get(f".{ext}".lower())
    if media is None or "/" in name or "\\" in name or name.startswith("."):
        return JSONResponse({"error": "not found"}, status_code=404)
    path = (WEB / name).resolve()
    if path.parent != WEB.resolve() or not path.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    # No caching: during a hackathon a stale bundle costs more than a refetch.
    return FileResponse(path, media_type=media,
                        headers={"Cache-Control": "no-store"})


@app.get("/search")
def search(q: str, kind: str = "fund", limit: int = 8):
    """Live entity search for the quick-switcher. Funds are Organizations,
    people are Person. Fast enough to run on keystrokes (~0.25s)."""
    from . import graph
    q = (q or "").strip()
    if len(q) < 2:
        return {"query": q, "kind": kind, "results": []}
    types = ["Person"] if kind == "people" else ["Organization", "Company"]
    from . import cache_index
    offline = False
    try:
        hits = graph.search(q, types=types, limit=max(limit * 3, 20))
    except Exception as e:
        # Live search is the fast path, not the only one. 6,400 entities are
        # already on disk from earlier calls, and a name match over those is
        # a real answer rather than an error message.
        hits = cache_index.search(q, types=types, limit=max(limit * 3, 20))
        offline = True
        if not hits:
            return {"query": q, "kind": kind, "results": [], "offline": True,
                    "error": f"{type(e).__name__}: {str(e)[:90]}"}

    # Raw entity search ranks "LIFELINE PLC" above the Finnish VC. For a fund
    # search, prefer exact name, Organization type, and a venture-ish
    # description - the same disambiguation the metrics layer uses.
    from . import norm
    want = norm.name(q)

    raw_want = q.lower()

    def rank(h):
        nm = norm.name(h.get("name"))
        raw = (h.get("name") or "").strip().lower()
        desc = (h.get("description") or "")
        is_vc = (h.get("entity_type") == "Organization"
                 and bool(graph._VC_WORDS.search(desc)))
        if kind == "fund":
            # norm.name() strips legal suffixes, which makes "NORRSKEN COMPANY
            # LIMITED" an exact match for "Norrsken" and rank it above
            # Norrsken VC. For a fund search, looking like a fund has to beat
            # a match created by the stripper.
            return (not is_vc, raw != raw_want, nm != want,
                    not nm.startswith(want), len(nm))
        return (nm != want, not nm.startswith(want), len(nm))

    ranked = sorted(hits, key=rank)[:limit]
    return {"query": q, "kind": kind, "offline": offline,
            "results": [{"id": h.get("id"), "name": h.get("name"),
                         "type": h.get("entity_type"),
                         "description": (h.get("description") or "")[:160]} for h in ranked]}


# Which relationships to surface, in display order, per entity kind.
PERSON_RELS = ["IS_CEO_OF", "FOUNDED", "WORKS_AT", "IS_MEMBER_OF",
               "INVESTED_IN", "PARTICIPATES_IN_FUNDING_ROUND", "STUDIED_AT",
               "SPOKE_AT", "RECEIVED_AWARD", "FEATURED_IN", "HAS_NATIONALITY"]
FUND_RELS = ["INVESTED_IN", "PARTICIPATES_IN_FUNDING_ROUND", "IS_ULTIMATE_PARENT",
             "HAS_SUBSIDIARY", "OPERATES_IN_INDUSTRY", "PARTICIPATES_IN_EVENT"]
PERSON_PROPS = ["name", "description", "linkedin_url", "birth_date"]
FUND_PROPS = ["name", "description", "website", "headquarters_address",
              "founding_date", "employee_count"]

REL_LABEL = {
    "IS_CEO_OF": "Chief executive", "FOUNDED": "Founded", "WORKS_AT": "Works at",
    "IS_MEMBER_OF": "Board and memberships", "INVESTED_IN": "Investments",
    "PARTICIPATES_IN_FUNDING_ROUND": "Funding rounds", "STUDIED_AT": "Education",
    "SPOKE_AT": "Spoke at", "RECEIVED_AWARD": "Awards",
    "IS_ULTIMATE_PARENT": "Parent of", "HAS_SUBSIDIARY": "Subsidiaries",
    "OPERATES_IN_INDUSTRY": "Industries", "PARTICIPATES_IN_EVENT": "Events",
}


@app.get("/entity/{entity_id}")
def entity_profile(entity_id: str, kind: str = "fund"):
    """One profile card, built from the graph. Relationships are discovered by
    introspection first, so we never ask for an edge this entity does not have."""
    from . import graph
    want = PERSON_RELS if kind == "people" else FUND_RELS
    props = PERSON_PROPS if kind == "people" else FUND_PROPS
    from . import cache_index
    degraded = None
    queried: list[str] = []      # edges we genuinely asked the graph for
    try:
        intro = cala_introspect(entity_id)
        have = set((intro.get("relationships") or {}).get("outgoing") or [])
        rels = [r for r in want if r in have] or want[:4]
        queried = list(rels)
        e = _entity(entity_id, props, rels)
    except Exception as ex:
        # The response cache is keyed by the exact request, so asking for this
        # entity with a different property list misses and goes live. When the
        # network says no, a payload for the same entity is usually already on
        # disk under another key - a degraded profile beats a dead page.
        e = cache_index.get(entity_id)
        if e is None:
            return JSONResponse({"error": f"{type(ex).__name__}: {str(ex)[:120]}"},
                                status_code=200)
        # Only what the cached payload actually carries. Claiming we asked
        # for edges we never requested turns "we did not look" into "there
        # are none", which is the lie this field exists to prevent.
        rels = list(((e.get("relationships") or {}).get("outgoing") or {}).keys())
        queried = list(rels)
        rels = rels or want[:4]
        degraded = ("Live lookup unavailable, so this profile is built from what "
                    "we already hold. Some relationships may be missing."
                    if "402" not in str(ex) and "credits" not in str(ex).lower() else
                    "Cala credits are exhausted, so this profile is built from "
                    "what we already hold. Some relationships may be missing.")

    out_props = {}
    for k in props:
        v, src = graph.prop(e, k)
        if v is not None:
            best = graph.best_source(src)
            out_props[k] = {"value": v, "rank": (best or {}).get("source_rank"),
                            "source": (best or {}).get("document")}

    groups = []
    for r in rels:
        items = []
        for it in graph.rels(e, "outgoing", r):
            ip = it.get("properties") or {}
            best = graph.best_source(ip.get("sources"))
            items.append({"id": it.get("id"), "name": it.get("name"),
                          "type": it.get("entity_type"), "role": ip.get("role"),
                          "rank": (best or {}).get("source_rank"),
                          "source": (best or {}).get("document")})
        if items:
            groups.append({"rel": r, "label": REL_LABEL.get(r, r.title()), "items": items})

    # Enrich every company an edge points at with what that company went on to
    # do. "Founded X" is thin; "Founded X, which raised four rounds" is a
    # profile. The funding data is already cached, so this costs nothing.
    rbc = _rounds_by_company()
    doms = _domains()
    for g in groups:
        for it in g["items"]:
            key = (it.get("name") or "").strip().lower()
            if doms.get(key):
                it["website"] = doms[key]
            rs = rbc.get(key)
            if rs is None:
                continue
            it["rounds"] = len(rs)
            if rs:
                last = rs[-1]
                it["last_round"] = {"stage": last.get("stage"), "date": last.get("date")}
                it["investors"] = (last.get("investors") or [])[:4]

    return {"id": entity_id, "kind": kind, "name": e.get("name"),
            "entity_type": e.get("entity_type"), "properties": out_props,
            "description": e.get("description"),
            # Which edges we actually asked for. Without this the UI cannot
            # tell "we asked and there are none" from "we never asked", and
            # it rendered both as 0 - a false claim about the fund.
            "rels_queried": queried,
            "degraded": degraded, "groups": groups}


def cala_introspect(eid):
    from . import cala_client as cala
    return cala.introspect(eid, allow_live=True, ttl=86400)


def _entity(eid, props, rels):
    from . import cala_client as cala
    return cala.get_entity(eid, properties=props, outgoing=rels, limit=25,
                           allow_live=True, ttl=86400)


@app.get("/evidence")
def evidence(investor: str, company: str, kind: str = "conflict"):
    """Who says so. Returns the cited claims behind a flag we raised."""
    from . import sourcing as SR
    try:
        fn = SR.conflict_evidence if kind == "conflict" else SR.lead_evidence
        return fn(investor, company, allow_live=True, ttl=7 * 86400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:110]}",
                             "claims": [], "docs": []}, status_code=200)


@app.get("/registry")
def registry(name: str, rounds: str = ""):
    """The public paper trail behind a company name.

    These are primary registers, not a search engine: GLEIF for the legal
    entity, PRH and Brreg for Nordic incorporation, SEC Form D for US private
    placements. Form D matters most - a filing with no matching round in Cala
    means a company is raising and has not announced it.
    """
    from . import datasets as D
    n = (name or "").strip()
    if len(n) < 3:
        return {"name": n, "error": "name too short"}
    known = [x for x in rounds.split(",") if x.strip()]
    out = {"name": n}
    for key, fn in (("gleif", D.gleif), ("prh", D.prh), ("brreg", D.brreg)):
        try:
            out[key] = fn(n)
        except Exception as e:
            out[key] = None
            out.setdefault("errors", {})[key] = type(e).__name__
    try:
        out["form_d"] = D.form_d(n)[:5]
        out["silent_round"] = D.silent_round(n, known)
    except Exception as e:
        out["form_d"], out["silent_round"] = [], None
        out.setdefault("errors", {})["sec"] = type(e).__name__

    # The point of all this: a registered identifier is an exact key into
    # Cala's graph. Names collide, identifiers do not.
    from . import resolve as RS
    try:
        out["cala"] = RS.resolve(n, allow_live=True, ttl=7 * 86400)
    except Exception as e:
        out["cala"] = None
        out.setdefault("errors", {})["cala"] = type(e).__name__
    return out


_PIPE = None


def _pipeline():
    """The handoff graph, built once from everything cached."""
    global _PIPE
    if _PIPE is None:
        from . import pipeline as P
        _PIPE = P.build(_rounds_by_company())
    return _PIPE


@app.get("/pipeline")
def pipeline(investor: str):
    """Where does this fund hand companies on to?

    Every other signal scores an investor in isolation. This is a transition
    in the graph - investor on round k, lead of round k+1 - and it answers the
    question a founder is actually deciding: if I take this money, who leads
    my next round?
    """
    from . import pipeline as P
    g = _pipeline()
    return {**P.where_it_takes_you(g, investor),
            "led_into": P.who_leads_into(g, investor),
            "co_investors": P.co_investors(g, investor)}


@app.post("/syndicates")
def syndicates(req: Req):
    """Three-fund syndicates a founder could actually assemble.

    A ranked list of investors is a shopping list. A round is a syndicate: one
    lead and the funds that reliably join when that lead leads - which is a
    different relationship from generic co-investment, and only visible in the
    round graph.

    Each one carries the two-hop route in: your backer, the company you both
    sat on, and the target lead.
    """
    from . import pipeline as P
    g = _pipeline()
    rbc = _rounds_by_company()

    p = PRESETS.get(req.company.strip().lower(), {})
    mine = req.my_investors or p.get("my_investors", [])
    scored = analyze(req)
    out = []
    for x in scored["investors"]:
        s = x["signals"]
        # A lead that is conflicted, dormant or barely leads is not a lead.
        if s["conflict"]["label"] == "🔴" or x["score"] is None:
            continue
        if s["lead_rate"]["label"] in ("🔴", "⚪") or s["dry_powder"]["label"] == "🔴":
            continue
        syn = P.syndicate(g, x["investor"], exclude=set(mine), size=2)
        if not syn["members"]:
            continue
        paths = P.warm_path(g, mine, x["investor"], rbc)
        out.append({"lead": x["investor"], "score": x["score"],
                    "lead_rate": s["lead_rate"]["value"],
                    "lead_text": s["lead_rate"]["text"],
                    "pace": s["dry_powder"]["text"],
                    "rounds_led": syn["rounds_led"], "enough": syn["enough"],
                    "members": syn["members"], "warm_paths": paths[:2]})
        if len(out) >= 5:
            break
    return {"company": req.company, "stage": req.stage,
            "your_backers": mine, "syndicates": out}


@app.post("/outreach")
def outreach(req: Req):
    """What to open with at Slush, and the numbers under every sentence.

    Synthesised from the screen that already ran: lead rate at this stage,
    deployment pace, who follows this fund, whether a warm route exists, and
    which portfolio companies sit in the founder's market. Nothing new is
    fetched, so this answers instantly and works offline.
    """
    from . import outreach as OB, pipeline as P
    want = (req.investor or "").strip()
    if not want:
        return JSONResponse({"error": "No investor named."}, status_code=200)

    scored = analyze(req)
    inv = next((x for x in scored["investors"]
                if norm.name(x["investor"]) == norm.name(want)), None)
    if inv is None:
        return JSONResponse({"error": f"{want} is not in this screen."},
                            status_code=200)

    p = PRESETS.get(req.company.strip().lower(), {})
    mine = req.my_investors or p.get("my_investors", [])
    syn = P.syndicate(_pipeline(), inv["investor"], exclude=set(mine), size=2)
    b = OB.brief(company=req.company, stage=req.stage, investor=inv,
                 syndicate=syn if syn.get("members") else None,
                 competitors=scored.get("competitors") or [])
    b["syndicate"] = syn
    return b


@app.get("/near")
def near(lat: float, lon: float, radius_km: float = 300, limit: int = 40,
         kind: str = "fund", company: str = "", stage: str = "series a"):
    """What is within reach of where the founder is standing.

    The coordinate comes from the browser's own geolocation, with the user's
    consent, and is used for this one request - we never send it anywhere and
    never store it. No IP lookup service sees the founder's address.

    When a company is named, each nearby fund is annotated with whether it
    leads at that stage, so "near me" becomes "near me and worth the walk".
    """
    from . import near as N
    data = map_data()
    if isinstance(data, JSONResponse):
        return data
    kinds = None if kind == "all" else {"fund": {"fund"},
                                        "company": {"portfolio", "exhibitor"},
                                        }.get(kind, {"fund"})
    pts = [{**p, "kind": p.get("kind", "exhibitor")}
           for p in (data["points"] + data["funds"] + data["portfolio"])]
    hits = N.rank(pts, lat, lon, radius_km=radius_km, limit=limit, kinds=kinds)

    # Join the screen onto the map, when one has been run for this company.
    if company:
        try:
            scored = analyze(Req(company=company, stage=stage, limit=30))
            by = {norm.name(x["investor"]): x for x in scored["investors"]}
            for h in hits:
                x = by.get(norm.name(h["name"]))
                if not x:
                    continue
                sg = x["signals"]
                h["screen"] = {"score": x["score"],
                               "lead": sg["lead_rate"].get("text"),
                               "lead_label": sg["lead_rate"]["label"],
                               "conflict": sg["conflict"]["label"] == "\U0001f534",
                               "backs": x.get("backs") or []}
        except Exception:
            pass          # the map still answers without the screen

    return {"lat": lat, "lon": lon, "radius_km": radius_km, "kind": kind,
            "count": len(hits), "results": hits,
            "cities": N.group_by_city(hits)[:12]}


@app.get("/website")
def website(site: str, name: str = ""):
    """What the company says about itself, on its own site.

    Cala is primary and a registry is authoritative, but neither notices that
    a seed company put up a pricing page last month. One GET of the homepage,
    cached for a week, nothing behind a login, and no third-party profile or
    social site - their terms forbid it and it would not be the company's own
    words anyway.
    """
    from . import website as W
    try:
        return W.profile(site, timeout=8)
    except Exception as e:
        return JSONResponse({"ok": False, "site": site, "signals": [],
                             "error": f"{type(e).__name__}: {str(e)[:110]}"},
                            status_code=200)


@app.get("/enrich")
def enrich(name: str, entity_id: str = "", cc: str = ""):
    """Everything we can say about a company when Cala has only its name.

    Three public sources, in order of how much they prove: a registry record
    (GLEIF/PRH/Brreg - an identifier, not a guess), the rounds already in our
    own cached corpus, and the company's own homepage. Each result carries
    how it was obtained, because "we found this by trying andercore.com and
    the page calls itself ANDERCORE" is a weaker claim than an LEI.
    """
    from . import datasets as DS, norm, website as W
    out = {"name": name, "registry": None, "rounds": [], "site": None,
           "site_how": None}

    # 1. Registry: a legal identifier is the strongest thing here.
    try:
        g = DS.gleif(name)
    except Exception:
        g = None
    if g:
        out["registry"] = {**g, "source_name": "GLEIF"}
        cc = cc or g.get("country") or ""

    # 2. Rounds we already hold, keyed on the normalised name. An entity with
    #    no Cala edges can still appear in a cached round.
    rs = _rounds_by_company().get(norm.name(name)) or \
        _rounds_by_company().get((name or "").strip().lower()) or []
    out["rounds"] = [{"date": r.get("date"), "stage": r.get("stage"),
                      "investors": (r.get("investors") or [])[:6]} for r in rs][:8]

    # 3. A website: the one we already know, else one we can verify.
    known = _domains().get((name or "").strip().lower())
    if known:
        out["site"], out["site_how"] = W.normalise(known), "on record"
    else:
        try:
            d = W.discover(name, cc or None)
        except Exception:
            d = None
        if d:
            out["site"] = d["site"]
            out["site_how"] = (f"found by trying {d['domain']}; the page calls "
                               f"itself \u201c{d['title']}\u201d")
    if out["site"]:
        try:
            out["homepage"] = W.profile(out["site"], timeout=8)
        except Exception:
            out["homepage"] = None
    return out


@app.get("/contradictions")
def contradictions(company: str = "", investor: str = ""):
    """Where our sources disagree with each other.

    A product built on a graph inherits the graph's disagreements. Vanta's
    Series B is on record at both 101.2M and 36.8M euro, with different
    leads and dates four months apart. Picking one silently and printing it
    as fact is the easy option and the wrong one.
    """
    from . import contradictions as CX, norm
    rbc = _rounds_by_company()
    if company:
        key = norm.name(company) or company.strip().lower()
        rbc = {k: v for k, v in rbc.items() if k == key}
    if investor:
        # The question a founder asks is not "does this company's record
        # disagree" but "do the rounds behind this fund's numbers disagree".
        rbc = {k: v for k, v in rbc.items()
               if any(norm.matches(investor, r.get("investors") or [])
                      for r in (v or []))}
    return {**CX.summarise(rbc), "investor": investor or None,
            "company": company or None}


@app.get("/progress")
def progress(company: str, stage: str = ""):
    """What the screen is doing right now. Polled while /analyze runs."""
    from . import progress as PG
    return PG.get(PG.key_for(company, stage))


@app.get("/classify")
def classify(q: str):
    """Fund or company? Local files and cache only, so it answers instantly.

    Ask used to send any bare name to the founder screen, which read
    "lifeline ventures" as a company looking for investors.
    """
    from . import classify as CL, norm

    funds = {}
    for name in _investor_pool():
        funds[norm.name(name) or name.lower()] = name
    for fname in ("fund_universe.json", "investor_domains.json"):
        f = ROOT / fname
        if not f.exists():
            continue
        try:
            for k in json.loads(f.read_text()):
                funds.setdefault(norm.name(k) or k.lower(), k)
        except ValueError:
            pass

    companies = {}
    pf = ROOT / "slush_profiles.json"
    if pf.exists():
        try:
            for r in json.loads(pf.read_text()):
                n = r.get("name")
                if n:
                    companies.setdefault(norm.name(n) or n.lower(), n)
        except ValueError:
            pass
    issuers = set(_rounds_by_company().keys())
    out = CL.classify(q, funds=funds, companies=companies, issuers=issuers)

    # Hand back an entity id when we have one, so the UI can open the profile
    # rather than running a search the user did not ask for.
    if out["kind"] == "fund":
        from . import cache_index
        hit = cache_index.search(out["name"], types=["Organization", "Company"], limit=1)
        if hit:
            out["entity_id"] = hit[0]["id"]
    return out


@app.get("/syndicate-evidence")
def syndicate_evidence(lead: str, member: str = "", via: str = ""):
    """The rounds behind a syndicate claim or a warm route.

    "Joins 25% of the rounds they lead" and "ask Voima, they co-invested"
    are the two most distinctive numbers here and the two a founder is most
    likely to repeat out loud. Both now open their rounds.
    """
    from . import pipeline as P
    rbc = _rounds_by_company()
    if via:
        rows = P.shared_rounds(rbc, via, lead)
        return {"kind": "warm", "a": via, "b": lead, "rounds": rows,
                "count": len(rows)}
    rows = P.follow_rounds(rbc, lead, member)
    return {"kind": "syndicate", "lead": lead, "member": member,
            "rounds": rows, "led": len(rows),
            "joined": sum(1 for r in rows if r["joined"])}


@app.get("/team")
def team(site: str = "", name: str = ""):
    """People a company names on its own page, each with the sentence.

    Cala carries relationships for one of the 227 people we hold, so the
    founder signal has almost nothing to read. This is the other half: the
    organisation speaking about itself, on its own domain, with every claim
    quoted back. Names and roles only - contact details are discarded even
    when the page shows them.
    """
    from . import team as TM, website as W
    url = site
    if not url and name:
        d = _domains().get(name.strip().lower())
        if not d:
            try:
                found = W.discover(name)
            except Exception:
                found = None
            d = (found or {}).get("site")
        url = d
    if not url:
        return {"ok": False, "site": None, "people": [],
                "why": "no website on record for this name"}
    try:
        return TM.read_deep(url, timeout=9)
    except Exception as e:
        return {"ok": False, "site": url, "people": [],
                "why": f"{type(e).__name__}: {str(e)[:90]}"}


@app.post("/ask-neo")
def ask_neo(req: Req):
    """Answer a question about what is in Flipside, from what is in Flipside.

    The answer is computed by app/neo.py from the same functions that drew
    the screen, so it cannot state a figure the product does not show. When
    ANTHROPIC_API_KEY is present the model is handed those facts and asked
    only to phrase them, and numbercheck rejects any number the facts do not
    contain. Rules decide, the model only writes.
    """
    from . import neo as NEO
    q = (req.question or "").strip()
    ctx = _neo_context(req)
    out = NEO.answer(q, ctx)
    out["model"] = None

    phrased = _neo_phrase(q, out)
    if phrased:
        out["prose"], out["model"] = phrased["text"], phrased["model"]
    return out


def _neo_context(req: Req) -> dict:
    """Everything Neo is allowed to know: the current screen and the corpus."""
    ctx: dict = {"company": req.company, "stage": req.stage}
    try:
        scored = analyze(req)
        ctx.update({k: scored.get(k) for k in
                    ("investors", "competitors", "edges", "fetched_at")})
    except Exception:
        ctx["investors"] = []
    for key, fn in (("syndicates", lambda: syndicates(req).get("syndicates")),
                    ("backtest", backtest),
                    ("health", health),
                    ("contradictions", lambda: contradictions())):
        try:
            ctx[key] = fn()
        except Exception:
            ctx[key] = None
    return ctx


def _neo_phrase(question: str, computed: dict) -> dict | None:
    """Optional: let a model phrase the computed facts, never add to them."""
    import os
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        return None
    from . import numbercheck as NC
    allowed = " ".join([computed.get("headline", "")] + list(computed.get("bullets") or []))
    prompt = (
        "Rewrite these findings as two short sentences for a founder. Use only "
        "the facts given. Do not add numbers, names or claims that are not "
        "below. Plain English, no preamble.\n\n"
        f"Question: {question}\n\nFindings:\n- "
        + "\n- ".join([computed.get("headline", "")] + list(computed.get("bullets") or [])))
    try:
        import httpx
        r = httpx.post("https://api.anthropic.com/v1/messages",
                       headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                "content-type": "application/json"},
                       json={"model": "claude-sonnet-5", "max_tokens": 300,
                             "messages": [{"role": "user", "content": prompt}]},
                       timeout=20)
        if r.status_code != 200:
            return None
        text = "".join(b.get("text", "") for b in r.json().get("content") or [])
    except Exception:
        return None
    ok, invented = NC.check_against_text(text, allowed)
    if not ok:
        # The model reached past its facts. Drop the prose and keep the
        # computed answer rather than printing a number nothing supports.
        return None
    return {"text": text.strip(), "model": "claude-sonnet-5"}


FUND_TABS_RELS_OUT = ["INVESTED_IN", "PARTICIPATES_IN_FUNDING_ROUND",
                      "PARTICIPATES_IN_CORPORATE_EVENT", "OPERATES_IN_INDUSTRY",
                      "HAS_HEADQUARTERS_IN", "HAS_PRESENCE_IN",
                      "IS_SUBSIDIARY_OF", "IS_REGISTERED_IN"]
# Every way a person can be attached to a firm, not just WORKS_AT. Asking for
# an edge the entity does not have costs nothing and comes back empty, so the
# full list is strictly better than the guess it replaces.
FUND_TABS_RELS_IN = ["INVESTED_IN"] + [e for e, _ in DEPTH.STAFF_EDGES]
# Identifiers and the plain record, which no tab asked for and every reader
# wants: a fund's legal name, age, size and LEI.
FUND_PROPS_FULL = FUND_PROPS + ["registered_address", "legal_name", "aliases",
                                "lei", "cik", "esg_policy"]


@app.get("/fund/{entity_id}")
def fund_profile(entity_id: str):
    """One fund with the tabs a reader actually came for.

    A single entity fetch carries investments, rounds with native is_lead,
    corporate events, industries, headquarters and the people Cala has on
    it. Enriched with the rounds already cached, so a portfolio company
    shows what it went on to do rather than only a name.
    """
    from . import cala_client as cala, cache_index, profile as PR
    degraded = None
    try:
        e = cala.get_entity(entity_id, properties=FUND_PROPS_FULL,
                            outgoing=FUND_TABS_RELS_OUT, incoming=FUND_TABS_RELS_IN,
                            limit=200, allow_live=True, ttl=86400)
    except Exception as ex:
        e = cache_index.get(entity_id)
        if e is None:
            return JSONResponse({"error": f"{type(ex).__name__}: {str(ex)[:120]}"},
                                status_code=200)
        degraded = ("Live lookup unavailable, so this profile is built from "
                    "what we already hold.")
    out = PR.build(e, rounds_by_company=_rounds_by_company(), domains=_domains())
    out["degraded"] = degraded
    # The whole record, read back from what the harvest stored: the plain
    # facts, every way a person is attached to the firm, the portfolio from
    # both edge directions, and an honest count of what we actually hold.
    out["depth"] = {"facts": DEPTH.facts(e), "identifiers": DEPTH.identifiers(e),
                    "staff": DEPTH.staff(e), "presence": DEPTH.presence(e),
                    "portfolio_total": len(DEPTH.portfolio(e)),
                    "coverage": DEPTH.coverage(e)}
    return out


def _with_open_news(out: dict, name: str) -> dict:
    """Fall back to the open index when Cala has nothing written about them.

    Cala's claims are the better answer and come first - each carries the
    document it was read from. But most of the 664 funds have none, and a
    News tab that says "nothing" about a firm with a press page is reporting
    our coverage rather than theirs. The two are kept apart and labelled,
    because nobody has decided an open-index article is about the right
    company and a Cala claim has been sourced.
    """
    if out.get("items"):
        return out

    # Context.dev's news index before GDELT, because it can be asked about an
    # entity rather than a string. Most of these firms are named after
    # ordinary words - Index, Atomico, Creandum - and a keyword index cannot
    # tell the fund from the noun. Matched on the domain when we hold one.
    try:
        from . import newsfeed as NF, cache_index
        site = cache_index.websites().get((name or "").strip().lower())
        n = NF.about(name, website=site, limit=10)
        if n.get("articles"):
            out["open"] = [{"title": a["title"], "url": a["url"],
                            "domain": a["source"], "date": a["published"]}
                           for a in n["articles"]]
            out["open_error"] = None
            out["open_source"] = (
                f"Context.dev's news index, matched on the "
                f"{n.get('matched_on') or 'name'}")
            out["open_outlets"] = n.get("outlets")
            return out
    except Exception as e:
        out["open_error"] = f"{type(e).__name__}: {str(e)[:110]}"

    from . import opennews as ON
    r = ON.search(name, limit=10)
    out["open"] = r.get("items") or []
    out["open_error"] = r.get("error") or out.get("open_error")
    out["open_source"] = "GDELT, an open index of world news"
    return out


@app.get("/news")
def news(name: str, year: str = ""):
    """What has been written about this firm lately, with the documents.

    /knowledge/search returns a sourced answer: each claim carries the
    context it came from and the URL that context was read at. We keep the
    claims and their documents and drop the prose, because a claim with a
    link is checkable and a paragraph is not.

    It takes about fifty seconds cold and nothing warm, so the UI loads it
    on demand rather than with the profile.
    """
    from . import cala_client as cala
    q = (f"Recent funding rounds, investments and news involving {name}"
         f"{' in ' + year if year else ''}")
    try:
        r = cala.search(q, allow_live=True, ttl=7 * 86400, timeout=90)
    except Exception as e:
        # Cala could not answer at all. The open index still can, and a News
        # tab that says "rate limited" is less useful than one that says
        # what was written and where.
        return _with_open_news(
            {"name": name, "items": [],
             "error": f"{type(e).__name__}: {str(e)[:110]}"}, name)

    ctx = {c.get("id"): c for c in (r.get("context") or [])}
    items, seen = [], set()
    for claim in r.get("explainability") or []:
        text = (claim.get("content") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        docs = []
        for ref in claim.get("references") or []:
            for origin in (ctx.get(ref, {}).get("origins") or []):
                doc = (origin or {}).get("document") or {}
                url, nm = doc.get("url"), doc.get("name")
                if url and url not in [d["url"] for d in docs]:
                    docs.append({"url": url, "name": (nm or url)[:90]})
        items.append({"claim": text, "documents": docs[:3]})
    return _with_open_news({"name": name, "items": items,
                            "summary": r.get("content"), "error": None}, name)


@app.get("/moves")
def moves_endpoint(limit: int = 40):
    """Who has just changed seats, from the people we have actually read.

    The earliest signal there is: a founder leaving to start something is
    what an investor wants first, and by the time it is a funding round it
    is not early any more.

    The coverage figures travel with the answer. Reading two moves out of a
    hundred and thirty people is not a finding, and a list of two rows with
    no denominator would read like one.
    """
    from . import cache_index, moves as MV
    idx = cache_index.build()
    people = [e for e in idx.values() if e.get("entity_type") == "Person"]
    def _co(key):
        return idx.get(key) or DEPTH.entity(key, types=("Company", "Organization"))

    out = MV.scan(people, rounds_by_company=_rounds_by_company(),
                  company_lookup=_co)
    out["moves"] = out["moves"][:limit]
    out["new_ventures"] = out["new_ventures"][:limit]
    out["coverage"]["people_in_cache"] = len(people)
    out["window_months"] = MV.RECENT_MONTHS
    return out


@app.get("/scouts")
def scouts(thesis: str = "", limit: int = 50):
    """People who have built before and are sitting in somebody else's seat.

    By the time there is a company and a deck, every fund has the same
    information. The investors who are early knew the person.
    """
    from . import cache_index, scouts as SC
    idx = cache_index.build()
    people = [e for e in idx.values() if e.get("entity_type") == "Person"]
    out = SC.rank(people, thesis=thesis, limit=limit,
                  company_lookup=lambda k: idx.get(k)
                  or DEPTH.entity(k, types=("Company", "Organization")))
    out["coverage"]["people_in_cache"] = len(people)
    return out


@app.post("/watch/{pid}")
def watch_add(pid: str, name: str = ""):
    from . import watchlist as WL
    _start_watch_sweep()
    WL.add(pid, name or pid)
    _check_watched(pid, name or pid)
    return {"watching": WL.watching(), "unread": WL.unread()}


@app.delete("/watch/{pid}")
def watch_remove(pid: str):
    from . import watchlist as WL
    WL.remove(pid)
    return {"watching": WL.watching(), "unread": WL.unread()}


@app.get("/watch")
def watch_list(check: bool = False):
    """Who is watched, and what has happened since you last acknowledged it.

    `check=true` re-reads every watched person now. The background sweep
    does the same thing on a timer, so the page is usually already current.
    """
    from . import watchlist as WL
    _start_watch_sweep()
    if check:
        for w in WL.watching():
            _check_watched(w["id"], w["name"])
    return {"watching": WL.watching(), "unread": WL.unread(),
            "last_sweep": _WATCH_SWEEP.get("at"),
            "sweep_every_minutes": WATCH_EVERY // 60}


@app.post("/watch-ack")
def watch_ack(pid: str = ""):
    from . import watchlist as WL
    return {"cleared": WL.ack(pid or None), "unread": WL.unread()}


def _check_watched(pid: str, name: str) -> list:
    """Read one watched person and store what changed. Never raises."""
    from . import cache_index, moves as MV, opennews as ON, watchlist as WL
    try:
        e = cache_index.get(pid) or DEPTH.entity(name, types=("Person",))
        mv = MV.moves(e, rounds_by_company=_rounds_by_company()) if e else []
        news = (ON.search(name, limit=6) or {}).get("items") or []
        return WL.record(pid, mv, news)
    except Exception:                                 # noqa: BLE001
        return []


# Every twenty minutes. The signals this reads change on the scale of weeks,
# and the open news index rate-limits anonymous callers - sweeping harder
# would find nothing more and be refused for it.
WATCH_EVERY = 20 * 60
_WATCH_SWEEP: dict = {}


def _watch_sweep() -> None:
    import threading
    import time as _t
    from . import watchlist as WL
    while True:
        _t.sleep(WATCH_EVERY)
        try:
            for w in WL.watching():
                _check_watched(w["id"], w["name"])
            _WATCH_SWEEP["at"] = _t.time()
        except Exception:                             # noqa: BLE001
            pass


def _start_watch_sweep() -> None:
    """Start the sweep once, on the first request that needs it.

    FastAPI's on_event("startup") is deprecated and a lifespan handler would
    be the modern hook, but this app has none and adding one to start a
    daemon thread is more machinery than the thread is worth.
    """
    if _WATCH_SWEEP.get("thread"):
        return
    import threading
    t = threading.Thread(target=_watch_sweep, daemon=True, name="watch-sweep")
    t.start()
    _WATCH_SWEEP["thread"] = t


@app.get("/builders")
def builders(limit: int = 60, pages: int = 10, days: int = 180,
             thesis: str = ""):
    """Everyone building in the open, whichever way they chose to say so.

    Two ways of doing one thing. A Show HN post is a person publishing
    something they made under a handle they chose. A demo-day listing is a
    company doing it with a programme's name attached. Both are the public
    act, and splitting them into separate tabs made the product look like it
    had two ideas when it has one.

    Filtered by thesis, because the unfiltered version of this is "the
    internet, this week". The filter reads what the thing says about itself
    - a post title, a company description - and the panel reports how much
    it discarded rather than quietly shrinking.
    """
    from . import builders as BD, accelerators as AC, cache_index
    from . import private_builders as PB
    idx = cache_index.build()
    founders = {norm.name(e.get("name") or "") for e in idx.values()
                if e.get("entity_type") == "Person"
                and ((e.get("relationships") or {}).get("outgoing") or {}).get("FOUNDED")}

    def already_known(handle: str, titles) -> bool:
        # A handle is not a name, so this catches only the obvious case:
        # somebody posting under their own name whom we already hold as a
        # founder. Not a privacy check and it does not pretend to be one.
        return norm.name(handle) in founders

    out = BD.rank(days=days, pages=pages, limit=400, known=already_known)

    cos, by_source = [], {}
    for key in AC.SOURCES:
        try:
            rows = AC.batch(key, "s26")
        except Exception:
            rows = []
        split = AC.against_cala(rows, idx)
        by_source[AC.SOURCES[key]["name"]] = split["counts"]["total"]
        cos += split["rows"]

    # Not PB.queries(): that builds GitHub search strings and drops tokens
    # under three characters, so "ai fintech" went in and "fintech" came
    # out. A filter over text we already hold has no such constraint, and
    # "ai" is the whole point of half these theses.
    words = [w for w in re.findall(r"[a-z0-9+#.]{2,}", thesis.lower())
             if w not in PB._STOP][:4]

    def hits(*fields) -> bool:
        """Every word, not any word.

        "ai fintech" on an any-match returned 167 companies, led by a
        nervous system for physical AI - because half of everything built
        this year mentions AI, so the discriminating word was outvoted by
        the common one. Requiring both is what the user typed two words
        for. Whole words with a plural tolerance, so "agent" finds "agents"
        and "ai" does not find "aiming".
        """
        if not words:
            return True
        blob = " ".join(str(f or "") for f in fields).lower()
        return all(re.search(r"\b" + re.escape(w[:-1] if w.endswith("s") else w)
                             + r"(?:e?s)?\b", blob) for w in words)

    shipped = [b for b in out["builders"]
               if hits(b["handle"], *[s.get("what") for s in b.get("shipped") or []])]
    announced = [c for c in cos if hits(c.get("name"), c.get("description"))]
    # Unknown to the graph first: that is the half an investor cannot buy.
    announced.sort(key=lambda c: (bool(c.get("in_cala")), c.get("name") or ""))

    out["builders"] = shipped[:limit]
    out["companies"] = announced[:limit]
    out["coverage"].update({
        "companies_read": len(cos),
        "companies_new": sum(1 for c in cos if not c.get("in_cala")),
        "by_accelerator": by_source,
        "handles_matching": len(shipped),
        "companies_matching": len(announced),
        "thesis": thesis.strip(),
        "terms": words,
    })
    out["source"] = ("Show HN via the Hacker News API, and published "
                     "accelerator batch lists.")
    return out


@app.get("/builder/{handle}")
def builder(handle: str):
    """One person in the private cohort, read properly.

    The cohort list is built from bulk endpoints and costs nothing per
    person. This is the other half of that bargain: when somebody is worth a
    closer look, it spends the core GitHub budget - sixty calls an hour
    without a token - on the three questions the list cannot answer. Which
    communities they are in, what they have started lately, and whose threads
    they turn up in.

    Cala comes first where Cala knows. If a Person carries a github_url
    naming this account, that is Cala's own claim with Cala's own sources
    behind it, and it is reported as identification rather than as a guess.
    """
    from . import github as GH, private_builders as PB, cache_index
    h = (handle or "").strip()
    if not h:
        return {"error": "no handle"}

    idx = cache_index.build()
    known = PB._people_by_handle(idx).get(h.lower())
    cala_says = None
    if known:
        cala_says = {
            "id": known.get("id"), "name": known.get("name"),
            "claimed": bool(known.get("_claimed")),
            "confidence": ("Cala records this GitHub account as theirs"
                           if known.get("_claimed")
                           else "name matches the handle, unverified"),
        }

    out = {"handle": h, "cala": cala_says, "limited": None}
    try:
        out["profile"] = GH.profile(h)
        out["orgs"] = GH.orgs(h)
        out["activity"] = GH.activity(h)
    except GH.RateLimited as e:
        out["limited"] = str(e)
        out.setdefault("profile", None)
    return out


@app.get("/contacts")
def contacts(limit: int = 24, names: str = ""):
    """Who to contact, without a screen having been run first.

    The call list was built only from the funds that survived a screen, so
    before anyone typed a company into Ask it was a sentence telling them to
    go and do that. The firms are known either way, and so are the people at
    them - a screen changes the ORDER, not whether we hold a contact. This
    answers the version of the question that does not need a raise: who is
    at the funds we track, which the caller can narrow to their own pipeline
    by passing names.

    Nothing here is ranked against a thesis, and the UI says so rather than
    implying this is a shortlist.
    """
    from concurrent.futures import ThreadPoolExecutor
    want = [n.strip() for n in names.split(",") if n.strip()] or _investor_pool()
    want = want[:max(1, min(limit, 40))]
    if not want:
        return {"rows": [], "unranked": True}
    def one(n):
        # _safe returns (result, error). Slicing the tuple instead of the
        # list gave every firm exactly two "people", one of which was None.
        people, err = _safe(_people_for_fund, n)
        return n, (people or []), err

    with ThreadPoolExecutor(max_workers=8) as ex:
        found = list(ex.map(one, want))
    rows = [{"investor": name, "people": people[:6], "named": len(people),
             "error": err} for name, people, err in found]
    # Most-knowable first: a firm we can name somebody at is actionable, one
    # we cannot is a lookup waiting to happen.
    rows.sort(key=lambda r: -r["named"])
    return {"rows": rows, "unranked": True,
            "firms": len(rows),
            "with_a_name": sum(1 for r in rows if r["named"]),
            "people": sum(r["named"] for r in rows)}


@app.get("/batches")
def batches(code: str = "s26", key: str = "yc"):
    """An accelerator batch, split by whether the graph already holds it.

    A demo day list is the earliest public record that a company exists. By
    the time one reaches an investor database it has usually raised, so the
    column worth looking at is not the batch - anyone can read the batch -
    but which rows Cala does not have. Measured on the two most recent YC
    batches: 427 companies, 405 of them absent from the graph.
    """
    from . import accelerators as AC, cache_index
    try:
        rows = AC.batch(key, code)
    except Exception as e:
        return {"rows": [], "error": f"{type(e).__name__}: {str(e)[:200]}"}
    out = AC.against_cala(rows, cache_index.build())
    out["accelerator"] = (AC.SOURCES.get(key) or {}).get("name") or key
    out["batch"] = code.upper()
    out["available"] = (AC.SOURCES.get(key) or {}).get("batches") or []
    out["source"] = ("Published batch lists. The accelerators' own "
                     "directories render client-side and scrape to nothing.")
    return out


_WHEREAMI = {}


@app.get("/whereami")
def whereami():
    """Approximate location when the browser will not give one.

    The map's "Near me" asked the browser and stopped there, so a denied
    permission - or any of the browsers that quietly refuse geolocation on a
    plain-http origin, which is every one of them - left the button dead.

    This resolves the location of THIS MACHINE's outbound IP, not the
    visitor's. For a tool running on a founder's own laptop those are the
    same thing, and saying which one it is matters more than the distinction
    usually does: the answer is a city, never an address, it is used for one
    request, and it is not written to disk or into the page.
    """
    if _WHEREAMI:
        return _WHEREAMI
    import httpx
    sources = [
        ("ipapi.co", "https://ipapi.co/json/",
         lambda d: (d.get("latitude"), d.get("longitude"), d.get("city"),
                    d.get("country_name"))),
        ("ip-api.com", "http://ip-api.com/json/?fields=status,country,city,lat,lon",
         lambda d: (d.get("lat"), d.get("lon"), d.get("city"), d.get("country"))),
    ]
    for name, url, pick in sources:
        try:
            r = httpx.get(url, timeout=6.0,
                          headers={"User-Agent": "Flipside/0.1 (Junction)"})
            if r.status_code != 200:
                continue
            lat, lon, city, country = pick(r.json())
            if lat is None or lon is None:
                continue
            _WHEREAMI.update({
                "lat": float(lat), "lon": float(lon),
                "label": ", ".join(x for x in (city, country) if x) or "your network",
                "source": name, "approximate": True,
                "note": "from this machine's network, not the browser"})
            return _WHEREAMI
        except Exception:
            continue
    return {"lat": None, "error": "No location source answered."}


@app.get("/private-builders")
def private_builders(thesis: str = "", limit: int = 30, months: int = 6):
    """The cohort before "building in public": building, but unannounced.

    Show HN finds people who shipped and said so. This finds the step before
    that - a repository started weeks ago, commits in it this week, almost no
    stars, squarely on the thesis. Nobody sells this list because the thing
    it describes has not happened yet.

    Sources are all bulk and public: GitHub repository search, Devpost
    hackathon submissions, Hacker News comments. GitHub's core API would
    allow eighteen people an hour without a token; repository search is a
    separate budget and returns a hundred at a time, which is why the list
    costs nothing per person and only a drill-down spends the core budget.
    """
    from . import private_builders as PB, cache_index
    idx = cache_index.build()
    try:
        from . import builders as BD
        announced = {r["handle"] for r in (BD.rank(limit=200).get("rows") or [])}
    except Exception:
        announced = set()
    try:
        out = PB.rank(thesis=thesis, limit=limit, months=months,
                      index=idx, announced=announced)
    except PB.Unavailable as e:
        return {"rows": [], "error": str(e), "queries": PB.queries(thesis)}
    out["source"] = ("GitHub repository search, Devpost, Hacker News comments. "
                     "No LinkedIn, by design.")
    return out


@app.post("/deck")
async def deck_put(file: UploadFile = File(...)):
    """Hold the deck so the email can carry a link to it.

    A compose link cannot carry an attachment. It can carry a URL, and this
    is where that URL points - at the machine this is running on, which the
    panel says out loud rather than letting a founder discover it.
    """
    from . import deck as DK
    body = await file.read()
    try:
        rec = DK.put(file.filename or "deck", body)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=200)
    rec["url"] = f"/deck/{rec['id']}"
    rec["outline"] = DK.outline(rec["name"], body)
    return rec


@app.get("/deck/{did}")
def deck_get(did: str, download: int = 0):
    from . import deck as DK
    rec = DK.get(did)
    if not rec:
        return JSONResponse({"error": "That link has expired or never existed."},
                            status_code=404)
    disp = "attachment" if download else "inline"
    return Response(rec["body"], media_type=rec["mime"], headers={
        "Content-Disposition": f'{disp}; filename="{rec["name"]}"',
        "Cache-Control": "private, max-age=3600"})


@app.get("/deck/{did}/outline")
def deck_outline(did: str):
    from . import deck as DK
    rec = DK.get(did)
    if not rec:
        return JSONResponse({"error": "not found"}, status_code=404)
    return {"id": did, "name": rec["name"], **DK.outline(rec["name"], rec["body"])}


@app.get("/scout-signal")
def scout_signal(name: str, id: str = ""):
    """What has happened to one watched person lately.

    Two sources, both of which we are allowed to read: the moves their own
    Cala record supports, and the open news index naming them. Not their
    mail, not their LinkedIn.
    """
    from . import cache_index, moves as MV, opennews as ON
    e = cache_index.get(id) if id else None
    if e is None:
        e = DEPTH.entity(name, types=("Person",))
    out = {"name": name, "moves": [], "news": [], "news_error": None}
    if e:
        out["moves"] = MV.moves(e, rounds_by_company=_rounds_by_company())
    r = ON.search(name, limit=6)
    out["news"] = r.get("items") or []
    out["news_error"] = r.get("error")
    return out


SCOUT_BACKTEST = ROOT / "backtest_scouts.json"


@app.get("/backtest-scouts")
def backtest_scouts():
    """Does "likely to found" predict founding? The attempt, and its verdict."""
    if not SCOUT_BACKTEST.exists():
        return {"ran": False,
                "verdict": "Not run yet."}
    d = json.loads(SCOUT_BACKTEST.read_text())
    d["ran"] = True
    return d


@app.get("/alert-rules")
def alert_rules():
    from . import alerts as AL
    return {"rules": [{"id": k, **v} for k, v in AL.RULES.items()]}


@app.post("/alerts")
def alerts(req: Req):
    """What these rules catch on this screen, right now.

    Not a promise about email. The rules run against the live screen and
    show what they find, plus what running them unattended would take -
    which is a scheduler and somewhere to put the result, and neither
    exists on a hackathon weekend.
    """
    from . import alerts as AL
    scored = analyze(req)
    hits = AL.evaluate(scored["investors"],
                       enabled=set(req.rules) if req.rules is not None else None,
                       stage=req.stage,
                       known_conflicts=set(req.seen_conflicts or []))
    comp = []
    if req.rules is None or "competitor_raised" in (req.rules or []):
        comp = AL.competitor_rounds(scored.get("competitors") or [],
                                    _rounds_by_company())
    # Every investor in a competitor's recent round is tomorrow's exclusion.
    would_exclude = sorted({i for c in comp for i in c["investors"]})
    return {"company": req.company, "stage": req.stage,
            "hits": hits, "competitor_rounds": comp,
            "would_exclude": would_exclude,
            "high": sum(1 for h in hits if h["severity"] == "high") + len(comp),
            "note": ("These ran once, against this screen. Running them "
                     "unattended needs a scheduler and a store; neither is "
                     "here, and saying otherwise would be the only dishonest "
                     "thing in this product.")}


_TITLE_IN_QUOTE = re.compile(
    r"\b((?:founding|general|managing|venture)?\s*partner|co-?founder[^,]{0,24}|"
    r"chief [a-z]+ officer|c[a-z]o|principal|associate|head of [a-z ]{3,20}|"
    r"entrepreneur[- ]in[- ]residence|advisor|director)\b", re.I)


def _role_from_quote(quote: str | None) -> str | None:
    """The title as written, not the bucket we sorted it into.

    "Co-founder & General Partner" is what a founder needs on a call list;
    "founder" is what the classifier reduced it to.
    """
    m = _TITLE_IN_QUOTE.search(quote or "")
    if not m:
        return None
    return " ".join(m.group(1).split()).strip(" ,.&")


def _people_for_fund(name: str) -> list[dict]:
    """Everyone we can name at this firm, best source first.

    Cala first: a Person entity carries a role and a start date from the
    graph. Coverage is thin - one person at Northzone - so the firm's own
    team page fills the rest, and each row says which it was.

    A harvested firm is read from the whole record rather than from the one
    WORKS_AT edge this function used to ask for, which is the difference at
    Creandum between four people who all "work here" and six with their
    actual titles and start dates - including the founder, who is attached
    by FOUNDED and was invisible before.
    """
    from . import cala_client as cala, graph, team as TM, website as W
    out, seen = [], set()

    harvested = DEPTH.entity(name, types=("Organization", "Company"))
    for p in (DEPTH.staff(harvested) if harvested else []):
        key = norm.name(p.get("name") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        out.append({"name": p["name"], "role": p.get("role"), "linkedin": None,
                    "source": "cala", "id": p.get("id"), "since": p.get("since")})

    try:
        f = graph.find_investor(name, allow_live=True, ttl=86400)
    except Exception:
        f = None
    if f and not out:
        try:
            e = cala.get_entity(f["id"], properties=["name"], incoming=["WORKS_AT"],
                                limit=40, allow_live=True, ttl=86400)
            staff = ((e.get("relationships") or {}).get("incoming") or {}).get("WORKS_AT") or []
        except Exception:
            staff = []
        for pr in staff[:12]:
            role = (pr.get("properties") or {}).get("role")
            role = role.get("value") if isinstance(role, dict) else role
            li = None
            try:
                pe = cala.get_entity(pr["id"], properties=["linkedin_url", "personal_website"],
                                     limit=1, allow_live=True, ttl=86400)
                pp = pe.get("properties") or {}
                li = (pp.get("linkedin_url") or {}).get("value") if isinstance(
                    pp.get("linkedin_url"), dict) else pp.get("linkedin_url")
            except Exception:
                pass
            key = norm.name(pr.get("name") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append({"name": pr.get("name"), "role": role, "linkedin": li,
                        "source": "cala", "id": pr.get("id")})

    # The firm's own page, for the firms Cala has nobody at - which is most.
    site = _domains().get((name or "").strip().lower())
    if not site:
        try:
            d = W.discover(name)
            site = (d or {}).get("site")
        except Exception:
            site = None
    if site:
        try:
            read = TM.read_deep(site, timeout=8)
        except Exception:
            read = {"people": []}
        for pr in read.get("people") or []:
            key = norm.name(pr.get("name") or "")
            if not key or key in seen:
                continue
            # A VC's site lists its portfolio's founders too. Those are that
            # company's people, not this firm's, and calling them about a
            # term sheet is the wrong call.
            if pr.get("is_staff") is False:
                continue
            seen.add(key)
            out.append({"name": pr.get("name"),
                        "role": _role_from_quote(pr.get("quote")) or pr.get("role"),
                        "quote": pr.get("quote"), "site": pr.get("source"),
                        "source": "site"})
    return out


@app.post("/call-list")
def call_list(req: Req):
    """Who to contact, in the order to contact them.

    A screen says which firms are worth approaching; it does not say who to
    write to, and a fund is not a person.
    """
    from concurrent.futures import ThreadPoolExecutor
    from . import calllist as CL, progress as PG
    scored = analyze(req)
    want = [x for x in scored["investors"]
            if (x.get("signals") or {}).get("conflict", {}).get("label") != "\U0001f534"][:10]

    # One firm at a time meant ten sequential rounds of discover-the-site,
    # fetch-the-team-page, parse-it: six seconds each, a minute for the list.
    # These are fetches of ten different hosts, not ten hits on one rate
    # limit, so there is no reason to queue them behind each other.
    key = PG.key_for(req.company, req.stage)
    PG.step(key, f"Finding who to contact at {len(want)} firms",
            "Cala first, then each firm's own team page", layer="web",
            because="A fund is not a person. The firm decides most of the "
                    "order, but you cannot send a deck to a firm.")
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(want)))) as ex:
        found = list(ex.map(lambda x: (norm.name(x["investor"]),
                                       _people_for_fund(x["investor"])), want))
    people = dict(found)
    named = sum(1 for v in people.values() if v)
    PG.step(key, f"{sum(len(v) for v in people.values())} people at {named} firms",
            layer="web")
    out = CL.build(scored["investors"], people, stage=req.stage)
    out["company"] = req.company
    out["stage"] = req.stage
    return out


_AFFINITY: dict = {}


def _affinity_index():
    """Who shares a school, a board, an award or a stage with whom.

    Rebuilt when the cache grows, like every other derived index here.
    """
    from . import affinity as AF, cache_index
    idx = cache_index.build()
    if _AFFINITY.get("n") == len(idx):
        return _AFFINITY["net"]
    net = AF.index(e for e in idx.values() if e.get("entity_type") == "Person")
    _AFFINITY.update(n=len(idx), net=net)
    return net


@app.get("/affinity/{entity_id}")
def affinity_routes(entity_id: str, limit: int = 20):
    """Introductions that are not made of money.

    The warm path a founder already has is a shared cap table. This is
    everything else the graph holds about people: the board they sit on
    together, the prize they both won, the school they both went to.
    """
    from . import affinity as AF
    rows = AF.routes(entity_id, _affinity_index(), limit=limit)
    return {"id": entity_id, "routes": rows,
            "sentences": [AF.phrase(r) for r in rows[:6]],
            "weaker_than": "a shared cap table, which means they have done "
                           "business together; these mean they have been in "
                           "the same room."}


@app.get("/registry/country")
def registry_lookup(name: str, cc: str = "", cik: str = ""):
    """One country's register, asked by name.

    /registry answers "what is the paper trail for this name" across every
    source at once, which is the right question when you have a name and
    nothing else. This answers "what does THIS country's register say",
    which is the right question when you know where the company is - and it
    is the one that knows about Denmark, France and Estonia.
    """
    from . import registry as RG
    rec = RG.lookup(name, cc=cc or None, cik=cik or None)
    return {"name": name, "country": cc or None, "record": rec,
            "no_adapter_because": RG.why_not(cc) if cc and not rec else None,
            "countries_covered": sorted(RG.BY_COUNTRY) + ["any (GLEIF)",
                                                          "US (by CIK)"]}


def _reachable_through(card: dict) -> list[dict]:
    """Who already knows this person, from the cap tables of what they built.

    The card could say a great deal about someone and nothing about how to
    reach them. An investor in a company they founded has met them, sat in
    their rounds and can make the introduction - and we hold those rounds.
    """
    rbc = _rounds_by_company()
    out: dict[str, dict] = {}
    for co in (card.get("operator") or {}).get("founded", []):
        for r in rbc.get(norm.name(co.get("name") or "")) or []:
            leads = {norm.name(x) for x in (r.get("leads") or [])}
            for inv in r.get("investors") or []:
                k = norm.name(inv)
                if not k:
                    continue
                row = out.setdefault(k, {"name": inv, "through": [], "led": False})
                if co["name"] not in row["through"]:
                    row["through"].append(co["name"])
                row["led"] = row["led"] or k in leads
    rows = sorted(out.values(), key=lambda x: (not x["led"], -len(x["through"]),
                                               x["name"]))
    return rows[:12]


PERSON_CARD_PROPS = ["name", "description", "linkedin_url", "personal_website",
                     "birth_date", "place_of_birth", "aliases"]
# Surveyed across ten VC people, commonest first, so a thin record costs
# nothing and a full one is complete.
# Every outgoing edge the harvest has actually seen on a Person, commonest
# first. Asking for one an entity does not have comes back empty and costs
# nothing, so the full list is strictly better than the subset this was.
# PARTICIPATES_IN_FUNDING_ROUND is the addition that matters: it is how we
# learn a partner writes their own cheques.
PERSON_CARD_RELS = ["WORKS_AT", "FOUNDED", "INVESTED_IN", "IS_MEMBER_OF",
                    "IS_BOARD_MEMBER_OF", "PARTICIPATES_IN_FUNDING_ROUND",
                    "STUDIED_AT", "IS_CEO_OF", "RECEIVED_AWARD", "SPOKE_AT",
                    "HAS_NATIONALITY", "IS_EXECUTIVE_OF", "IS_CTO_OF",
                    "IS_CFO_OF", "IS_COO_OF", "IS_CSO_OF",
                    "IS_GENERAL_PARTNER_OF", "IS_MANAGING_DIRECTOR_OF",
                    "IS_VICEPRESIDENT_OF"]


@app.get("/person/{entity_id}")
def person_card(entity_id: str, company: str = ""):
    """Who this is, what they have built, and who they can introduce you to."""
    from . import cala_client as cala, cache_index, outreach as OB, person as PS
    degraded = None
    try:
        e = cala.get_entity(entity_id, properties=PERSON_CARD_PROPS,
                            outgoing=PERSON_CARD_RELS, limit=40,
                            allow_live=True, ttl=86400)
    except Exception as ex:
        e = cache_index.get(entity_id)
        if e is None:
            return JSONResponse({"error": f"{type(ex).__name__}: {str(ex)[:120]}"},
                                status_code=200)
        degraded = "Built from what we already hold; the live lookup failed."

    words: set[str] = set()
    if company:
        p = PRESETS.get(company.strip().lower(), {})
        comps, _ = _safe(C.competitors, p.get("query") or company)
        words = OB._sector_words(comps or [], p.get("desc", ""))
    card = PS.build(e, sector_words=words)
    card = PS.enrich_markets(card, lambda eid: _entity_description(eid))
    card["confidence"] = PS.confidence(card)
    card["reachable_through"] = _reachable_through(card)
    try:
        from . import affinity as AF
        rs = AF.routes(entity_id, _affinity_index(), limit=8)
        card["affinity"] = [{**r, "says": AF.phrase(r)} for r in rs]
    except Exception:                                 # noqa: BLE001
        card["affinity"] = []
    card["degraded"] = degraded
    return card


def _entity_description(entity_id: str) -> str | None:
    """One company's description, cached a week. Used to tell what a name is."""
    from . import cala_client as cala
    e = cala.get_entity(entity_id, properties=["name", "description"], limit=1,
                        allow_live=True, ttl=7 * 86400)
    return (e.get("description")
            or ((e.get("properties") or {}).get("description") or {}).get("value"))


def _person_signals(name: str, firm: str, words: set) -> dict | None:
    """The few things about a person that change who to call first.

    Resolving a name to a Person entity is two calls, so this is kept off
    the call list's own load and run afterwards, and everything is cached.
    """
    from . import cala_client as cala, graph, norm, person as PS
    try:
        hits = graph.search(name, types=["Person"], limit=4, interactive=False,
                            allow_live=True, ttl=7 * 86400)
    except Exception:
        return None
    want = norm.name(name)
    hit = next((h for h in hits if norm.name(h.get("name")) == want), None)
    if hit is None:
        return None
    try:
        e = cala.get_entity(hit["id"], properties=PERSON_CARD_PROPS,
                            outgoing=PERSON_CARD_RELS, limit=30,
                            allow_live=True, ttl=7 * 86400)
    except Exception:
        return None
    card = PS.enrich_markets(PS.build(e, sector_words=words), _entity_description)

    # A name alone is not a match. Require the entity to be connected to the
    # firm we found them at, or the card could be a different Sabina.
    firm_key = norm.name(firm)
    linked = any(norm.name(w.get("name")) == firm_key for w in card["works_at"]) \
        or any(norm.name(n["name"]) == firm_key for n in card["network"]["companies"]) \
        or any(norm.name(o["name"]) == firm_key for o in card["operator"]["operated"])

    op = card["operator"]
    ang = card["angel"]
    title = (card.get("titles") or [{}])[0]
    return {"id": hit["id"], "linked_to_firm": linked,
            "angel": ang["is_angel"],
            "angel_rounds": ang["round_count"],
            "angel_companies": ang["company_count"],
            "angel_last_year": ang["last_year"],
            "graph_title": title.get("title"),
            "graph_title_at": title.get("name"),
            "market_match": card["domain"]["matched"],
            "market_via": [v["name"] for v in (card["domain"].get("via") or [])][:2],
            "years_building": op.get("years_building"),
            "operator": bool(op.get("founded") or op.get("operated")),
            "built": [f["name"] for f in op.get("founded", [])][:2],
            "network": card["network"]["count"],
            "linkedin": card.get("linkedin"),
            "verified": True,
            "confidence": PS.confidence(card)["label"]}


@app.post("/call-list/people")
def call_list_people(req: Req):
    """Resolve the call list's contacts to Cala people and re-rank.

    Run after the list is already on screen: resolving fifteen names is
    thirty calls cold and nothing warm.
    """
    from . import calllist as CL, norm, outreach as OB
    scored = analyze(req)
    p = PRESETS.get(req.company.strip().lower(), {})
    comps, _ = _safe(C.competitors, p.get("query") or req.company)
    words = OB._sector_words(comps or [], p.get("desc", ""))

    people = {}
    for x in scored["investors"]:
        if (x.get("signals") or {}).get("conflict", {}).get("label") == "\U0001f534":
            continue
        fund = x["investor"]
        found = _people_for_fund(fund)
        for pr in found[:6]:
            sig = _person_signals(pr["name"], fund, words)
            # A name match that is not connected to this firm is a different
            # person with the same name. Keep the contact, drop the card.
            if sig and sig.get("linked_to_firm"):
                pr["signals"] = sig
                pr.setdefault("id", sig["id"])
                pr["linkedin"] = pr.get("linkedin") or sig.get("linkedin")
        people[norm.name(fund)] = found

    out = CL.build(scored["investors"], people, stage=req.stage)
    out["company"], out["stage"] = req.company, req.stage
    out["enriched"] = sum(1 for r in out["rows"] if r.get("signals"))
    out["market_words"] = sorted(words)[:10]
    return out


@app.get("/connectors")
def connectors(limit: int = 12):
    """Funds whose handoffs spread widest - the bridges in this network."""
    from . import pipeline as P
    return {"connectors": P.connectors(_pipeline(), limit)}


@app.get("/exits")
def exits(entity_id: str, name: str = "", kind: str = "fund", limit: int = 12):
    """Did money ever come out?

    For a company: was it acquired, by whom, when. For a fund: how many of
    its portfolio companies exited - reported with the denominator, because
    "3 exits" is meaningless without "out of how many we could check".
    """
    from . import exits as X
    kw = dict(allow_live=True, ttl=7 * 86400)
    try:
        if kind != "fund":
            xs = X.company_exits(entity_id, name, **kw)
            return {"name": name, "kind": kind, "checked": 1,
                    "exits": [x.__dict__ for x in xs]}

        e = _entity(entity_id, ["name"], ["INVESTED_IN"])
        from . import graph
        port = [c for c in graph.rels(e, "outgoing", "INVESTED_IN") if c.get("id")][:limit]
        results, unknown = [], 0
        for c in port:
            try:
                results.append((c["name"], X.company_exits(c["id"], c["name"], **kw)))
            except Exception:
                unknown += 1
        rec = X.summarise(results, unknown)
        return {"name": name, "kind": kind, "checked": rec.checked,
                "unknown": rec.unknown, "rate": rec.rate,
                "portfolio_seen": len(port),
                "exits": [x.__dict__ for x in rec.exits]}
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:110]}",
                             "exits": [], "checked": 0}, status_code=200)


@app.get("/bio")
def bio(name: str, kind: str = "people"):
    """A sourced narrative. Cheap depth: one search, every claim cited."""
    from . import sourcing as SR
    n = (name or "").strip()
    if len(n) < 3:
        return {"name": n, "claims": [], "docs": []}
    q = (f"Who is {n}? What have they founded, where do they work, what have "
         f"they invested in, and what are they known for? Cite sources."
         if kind == "people" else
         f"What is {n}, what do they invest in, and what are they known for? "
         f"Cite sources.")
    try:
        return SR.explain(q, subjects=(n,), allow_live=True, ttl=7 * 86400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {str(e)[:110]}",
                             "claims": [], "docs": []}, status_code=200)


@app.get("/founder-signal/{entity_id}")
def founder_signal(entity_id: str, name: str = "", github: str = ""):
    """The third reading: does this person look like a founder before they are one?"""
    from . import founder_signal as FS, github as GH
    prof = entity_profile(entity_id, kind="people")
    if isinstance(prof, JSONResponse):
        return prof
    groups = prof.get("groups") or []
    nm = name or prof.get("name") or ""

    gh_profile, gh_err = None, None
    try:
        login = github or GH.find_user(nm)
        if login:
            gh_profile = GH.profile(login)
    except GH.RateLimited as e:
        gh_err = str(e)
    except Exception as e:
        gh_err = f"{type(e).__name__}"

    sig = GH.signal(gh_profile)
    out = FS.assess(nm, groups, gh=sig if gh_profile else None,
                    rounds_by_company=_rounds_by_company())
    return {"name": nm, "id": entity_id, "score": out.score,
            "confidence": out.confidence, "reasons": out.reasons,
            "components": out.components, "evidence_edges": out.evidence_edges,
            "github": gh_profile, "github_signal": sig, "github_error": gh_err,
            "known_companies": len(_rounds_by_company()),
            "groups": [{"rel": g["rel"], "label": g["label"],
                        "items": [i["name"] for i in g["items"][:6]]} for g in groups]}


@app.get("/locate/{entity_id}")
def locate_entity(entity_id: str, kind: str = "people"):
    """Where is this person? Cala holds no location on a Person, so we hop:
    person -> WORKS_AT / IS_CEO_OF / FOUNDED -> company -> headquarters_address.
    The company we used is returned too, so the answer is never unattributed."""
    from . import geo, graph
    try:
        if kind == "people":
            e = _entity(entity_id, PERSON_PROPS, ["WORKS_AT", "IS_CEO_OF", "FOUNDED"])
            cos = []
            for r in ("WORKS_AT", "IS_CEO_OF", "FOUNDED"):
                cos += graph.rels(e, "outgoing", r)
            seen, out = set(), []
            for c in cos:
                if not c.get("id") or c["id"] in seen:
                    continue
                seen.add(c["id"])
                ce = _entity(c["id"], ["name", "headquarters_address", "website"], [])
                hq, hq_src = graph.prop(ce, "headquarters_address")
                loc = geo.locate(hq)
                if loc:
                    out.append({"via": c.get("name"), "hq": hq,
                                "lat": loc[0], "lon": loc[1], "cc": loc[2],
                                "source": (graph.best_source(hq_src) or {}).get("document")})
                if len(out) >= 3:
                    break
            return {"id": entity_id, "name": e.get("name"), "kind": kind, "places": out}

        e = _entity(entity_id, FUND_PROPS, [])
        hq, hq_src = graph.prop(e, "headquarters_address")
        loc = geo.locate(hq)
        return {"id": entity_id, "name": e.get("name"), "kind": kind,
                "places": ([{"via": e.get("name"), "hq": hq, "lat": loc[0], "lon": loc[1],
                             "cc": loc[2],
                             "source": (graph.best_source(hq_src) or {}).get("document")}]
                           if loc else [])}
    except Exception as ex:
        # Same hop, walked over what is already on disk. The relationship that
        # places a person is usually cached with the person.
        out = _locate_from_cache(entity_id, kind)
        if out is not None:
            return out
        return JSONResponse({"error": f"{type(ex).__name__}: {str(ex)[:120]}", "places": []},
                            status_code=200)


def _locate_from_cache(entity_id: str, kind: str):
    from . import cache_index, geo
    e = cache_index.get(entity_id)
    if not e:
        return None
    rel = (e.get("relationships") or {}).get("outgoing") or {}

    def hq_of(node):
        props = node.get("properties") or {}
        for k in ("headquarters_address", "registered_address"):
            v = props.get(k)
            v = v.get("value") if isinstance(v, dict) else v
            if v:
                return v
        return None

    places = []
    if kind == "people":
        for r in ("IS_CEO_OF", "WORKS_AT", "FOUNDED"):
            for c in (rel.get(r) or []):
                full = cache_index.get(c.get("id")) or c
                hq = hq_of(full)
                loc = geo.locate(hq)
                if loc:
                    places.append({"via": c.get("name"), "hq": hq, "lat": loc[0],
                                   "lon": loc[1], "cc": loc[2], "source": None,
                                   "rel": r})
                if len(places) >= 3:
                    break
            if len(places) >= 3:
                break
    else:
        hq = hq_of(e)
        loc = geo.locate(hq)
        if loc:
            places = [{"via": e.get("name"), "hq": hq, "lat": loc[0], "lon": loc[1],
                       "cc": loc[2], "source": None}]
    return {"id": entity_id, "name": e.get("name"), "kind": kind,
            "places": places, "offline": True}


# Calm, desaturated monogram palette - a fallback that looks deliberate.
MONO = ["#8a7f72", "#6f7d8a", "#7d7288", "#6f8a7a", "#8a7472", "#79808a"]


def _monogram(name: str) -> Response:
    letters = "".join(w[0] for w in "".join(
        c if c.isalnum() or c.isspace() else " " for c in (name or "?")).split()[:2]).upper() or "?"
    bg = MONO[sum(map(ord, name or "?")) % len(MONO)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
           f'<rect width="64" height="64" rx="14" fill="{bg}" fill-opacity="0.14"/>'
           f'<text x="32" y="41" text-anchor="middle" fill="{bg}" '
           f'font-family="-apple-system,Segoe UI,Inter,sans-serif" font-size="25" '
           f'font-weight="600">{letters}</text></svg>')
    return Response(svg, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


@app.get("/logo")
def logo(domain: str = "", name: str = ""):
    """Company mark by domain, generated monogram when we have none."""
    from . import logos, norm
    # Almost every call site has a name and no domain - relationship edges do
    # not carry websites - so without this lookup the whole product renders
    # monograms. The domains are already on disk.
    if not domain and name:
        d = _domains()
        hit = d.get(name.strip().lower())
        if not hit:
            want = norm.name(name)
            hit = next((v for k, v in d.items() if norm.name(k) == want), None)
        domain = hit or ""
    body, ct = logos.fetch(domain) if domain else (None, None)
    if body:
        return Response(body, media_type=ct,
                        headers={"Cache-Control": "public, max-age=604800"})
    return _monogram(name or domain)


@app.get("/place")
def place(q: str):
    """Resolve a place name so the map can fly to it. 'espoo' -> bbox."""
    from . import geocode
    r = geocode.lookup(q, timeout=8)
    return r or {"error": "not found"}


@app.get("/maplibre-gl.js")
def mljs():
    return FileResponse(WEB / "maplibre-gl.js", media_type="application/javascript")


@app.get("/maplibre-gl.css")
def mlcss():
    return FileResponse(WEB / "maplibre-gl.css", media_type="text/css")


@app.get("/world.js")
def worldjs():
    return FileResponse(WEB / "world.js", media_type="application/javascript")


@app.get("/conviction")
def conviction():
    """Investor side: insider conviction, precomputed."""
    if not CONVICTION.exists():
        return JSONResponse({"error": "Conviction data not built yet. "
                             "Run precompute_conviction_corpus.py."}, status_code=200)
    d = json.loads(CONVICTION.read_text())
    return _age_conviction(d)


_SLOWING = None


def _slowing_funds() -> set[str]:
    """Investors that have stopped deploying, recomputed from cached rounds.

    The corpus stores each insider's name, kind, baseline and whether they
    returned - but not whether their fund had slowed, and the score applies
    a discount when it had. Without this the breakdown cannot reproduce the
    number it claims to explain, which is worse than having no breakdown.
    """
    global _SLOWING
    if _SLOWING is not None:
        return _SLOWING
    out = set()
    for inv in _investor_pool():
        try:
            rs = investor_rounds(inv)
            if rs and M.dry_powder(inv, M.by_company(rs)).label == "\U0001f534":
                out.add(norm.name(inv))
        except Exception:
            pass
    _SLOWING = out
    return out


def _age_conviction(d: dict) -> dict:
    """Apply recency decay to a precomputed corpus, at serve time.

    The corpus stores each company's rounds, so the age of the evidence is
    already on disk and nothing has to be refetched. Without this, a company
    whose last round closed in 2022 leads a ranking of who is converting
    insider conviction today.
    """
    from . import conviction as CV
    today = CV.TODAY.isoformat()
    out = []
    for c in d.get("companies") or []:
        rounds = c.get("rounds") or []
        last = max((r.get("date") for r in rounds if r.get("date")), default=None)
        months = CV.months_between(last, today)
        rf = CV.recency_factor(months)
        fresh = c.get("score_fresh", c.get("score"))
        # Reattach the slowing flag so the breakdown reproduces the score.
        slow = _slowing_funds()
        insiders = [{**i, "fund_slowing": norm.name(i.get("name")) in slow}
                    for i in (c.get("insiders") or [])]
        # The corpus was scored with the default pool mean, not the observed
        # pool_baseline. Matching it is what makes the breakdown reproduce
        # the score instead of merely resembling it.
        parts = CV.score_parts(insiders, c.get("structure"),
                               c.get("previous_lead_returned"), None)
        w = parts["weights"]
        rebuilt = 100 * (w["participation"] * parts["participation"]
                         + w["lift"] * parts["lift_norm"]
                         + w["lead"] * parts["lead"]
                         + w["structure"] * parts["structure"])
        parts["rebuilt"] = round(rebuilt, 1)
        # Where it still differs, the slowing set we reconstruct from today's
        # cache is not the one the corpus was scored against. Report the gap
        # rather than letting the drawer quietly disagree with the number.
        parts["residual"] = round((c.get("score_fresh") or c.get("score") or 0) - rebuilt, 1)
        c = {**c, "insiders": insiders, "breakdown": parts,
             "last_round": last, "months_since": months,
             "recency": round(rf, 3), "score_fresh": fresh,
             "stale": bool(months is not None and months >= CV.STALE_AFTER_MONTHS)}
        if fresh is not None:
            c["score"] = round(fresh * rf, 1)
        out.append(c)
    out.sort(key=lambda c: (c.get("score") is None, -(c.get("score") or 0)))
    # Why a detector is empty matters as much as the fact. Pre-emption needs
    # two consecutive round sizes and almost no round carries one, so a zero
    # here is starved input, not an absence of pre-emptions in the market.
    records = [r for c in out for r in (c.get("rounds") or [])]
    with_amount = [r for r in records if r.get("amount")]
    pairs = sum(1 for c in out for a, b in zip(c.get("rounds") or [],
                                               (c.get("rounds") or [])[1:])
                if a.get("amount") and b.get("amount"))
    return {**d, "companies": out,
            "coverage": {"round_records": len(records),
                         "with_amount": len(with_amount),
                         "amount_pairs": pairs},
            "recency": {"grace_months": CV.GRACE_MONTHS,
                        "halflife_months": CV.HALFLIFE_MONTHS,
                        "floor": CV.RECENCY_FLOOR,
                        "stale_after_months": CV.STALE_AFTER_MONTHS}}
