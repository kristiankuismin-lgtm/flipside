"""FastAPI: founderin syote -> jarjestetty sijoittajalista kortteineen.

Demo ajetaan CALA_CACHE_ONLY=1, jolloin yksikaan pyynto ei odota Calaa
(kyselyt kestavat 20-60 s). Puuttuva data raportoidaan rehellisesti
sen sijaan etta se peitettaisiin nollana.
"""
import json
import os
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from . import metrics as M, conflict as C, warmpath as W
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


_DOMAINS = None


def _domains() -> dict:
    """company (lowercased) -> website, from everything already fetched.

    Relationship edges carry no website, so a logo would always fall back to a
    monogram. These files already hold the domains.
    """
    global _DOMAINS
    if _DOMAINS is not None:
        return _DOMAINS
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


@app.post("/analyze")
def analyze(req: Req):
    from . import progress as PG
    key = PG.key_for(req.company, req.stage)
    PG.start(key, req.company)

    p = PRESETS.get(req.company.strip().lower(), {})
    cq = p.get("query") or req.company
    desc = req.description or p.get("desc", "")

    PG.step(key, f"Resolving {req.company} in Cala's graph")
    comps, cerr = _safe(C.competitors, cq)
    PG.step(key, f"Found {len(comps or [])} named competitors",
            ", ".join(c.get("name", "") for c in (comps or [])[:4]))
    pool = req.investors or _investor_pool()[: req.limit]
    mine = req.my_investors or p.get("my_investors", [])
    PG.step(key, f"Screening {len(pool)} funds")

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
                    f"{len(all_rounds)} rounds so far")
    histories = W.index_histories(all_rounds)
    PG.step(key, f"Indexed {len(all_rounds)} rounds for warm routes")

    out = []
    for n, i in enumerate(pool, 1):
        out.append(analyze_one(i, req.company, desc, req.stage, comps, histories, mine))
        if n % 4 == 0 or n == len(pool):
            PG.step(key, f"Scored {n} of {len(pool)} funds")
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
            # Every claim in the UI is datable: a number with no retrieval
            # time cannot be checked, only believed.
            "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "competitors": comps or [], "competitors_error": cerr,
            "edges": edges, "investors": out}


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


@app.get("/map")
def map_data():
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
            funds.append({"name": name, "id": v.get("id"), "lat": lat, "lon": lon,
                          "cc": cc, "precise": precise, "hq_note": note,
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
            "points": pts, "funds": funds, "portfolio": portfolio}


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
        return TM.read(url, timeout=9)
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
