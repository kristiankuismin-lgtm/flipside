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
        return "hyva"
    if n >= MIN_ROUNDS_TO_RANK:
        return "ohut"
    return "riittamaton"


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
    sig["conflict"] = C.detect(company, desc, comps or [], port or [])
    edges = C.matches(comps or [], port or [])

    fit = {"stage": 1.0, "sector": 0.8, "geo": 0.9, "check": 0.8}
    depth = evidence_depth(len(rounds))
    # Ilman riittavaa otosta pisteet olisivat harhaanjohtavia: nayta se.
    score = None if depth == "riittamaton" else M.score(fit, sig)
    return {"investor": inv, "score": score, "rounds_seen": len(rounds),
            "evidence_depth": depth, "portfolio_size": len(port or []),
            "backs": [e["competitor"] for e in edges],
            "signals": {k: asdict(v) for k, v in sig.items()}, "notes": notes}


@app.post("/analyze")
def analyze(req: Req):
    p = PRESETS.get(req.company.strip().lower(), {})
    cq = p.get("query") or req.company
    desc = req.description or p.get("desc", "")

    comps, cerr = _safe(C.competitors, cq)
    pool = req.investors or _investor_pool()[: req.limit]
    mine = req.my_investors or p.get("my_investors", [])

    # Yhteinen yhtiohistoria-indeksi lampimia reitteja varten. Kootaan kerran
    # kaikkien sijoittajien portfolioyhtioista - vain cachesta.
    all_rounds = []
    for i in pool:
        rs, _ = _safe(investor_rounds, i)
        for r in sorted(rs or [], key=lambda x: x.date)[:10]:
            h, _ = _safe(company_history, r.company)
            if h:
                all_rounds.extend(h)
    histories = W.index_histories(all_rounds)

    out = [analyze_one(i, req.company, desc, req.stage, comps, histories, mine)
           for i in pool]
    # Rankkaamattomat (riittamaton data) aina loppuun, ei sekaan.
    out.sort(key=lambda x: (x["score"] is None, -(x["score"] or 0), x["investor"]))
    # Kilpailija <-> rahasto -kaaret konfliktikarttaa varten.
    edges = [{"investor": x["investor"], "competitor": c}
             for x in out for c in x.get("backs") or []]
    return {"company": req.company, "stage": req.stage,
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
    return {"ok": True, "cache_only": cala.CACHE_ONLY, "has_key": bool(cala.KEY),
            "pool": len(_investor_pool()), "conviction_n": n}


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
        pts.append({"name": p["name"], "lat": lat, "lon": lon, "cc": cc,
                    "precise": precise, "hq": hq, "website": p.get("website"),
                    "industries": (p.get("industries") or [])[:2],
                    "score": conv.get(p["name"].lower()),
                    "source": p.get("hq_source")})
    return {"event": "Slush 2026", "event_date": "2026-11-18",
            "total_exhibitors": len(profs), "profiles_fetched": len(ok),
            "placed": len(pts), "exact": exact, "unplaced": unplaced, "points": pts}


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


@app.get("/app.js")
def appjs():
    # No caching: during a hackathon a stale bundle costs more than a refetch.
    return FileResponse(WEB / "app.js", media_type="application/javascript",
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
    try:
        hits = graph.search(q, types=types, limit=max(limit * 3, 20))
    except Exception as e:
        return {"query": q, "kind": kind, "results": [],
                "error": f"{type(e).__name__}: {str(e)[:90]}"}

    # Raw entity search ranks "LIFELINE PLC" above the Finnish VC. For a fund
    # search, prefer exact name, Organization type, and a venture-ish
    # description - the same disambiguation the metrics layer uses.
    from . import norm
    want = norm.name(q)

    def rank(h):
        nm = norm.name(h.get("name"))
        desc = (h.get("description") or "")
        return (
            nm != want,                                   # exact name first
            not nm.startswith(want),                      # then prefix
            kind == "fund" and h.get("entity_type") != "Organization",
            kind == "fund" and not graph._VC_WORDS.search(desc),
            len(nm),
        )

    ranked = sorted(hits, key=rank)[:limit]
    return {"query": q, "kind": kind,
            "results": [{"id": h.get("id"), "name": h.get("name"),
                         "type": h.get("entity_type"),
                         "description": (h.get("description") or "")[:160]} for h in ranked]}


# Which relationships to surface, in display order, per entity kind.
PERSON_RELS = ["IS_CEO_OF", "FOUNDED", "WORKS_AT", "IS_MEMBER_OF",
               "INVESTED_IN", "PARTICIPATES_IN_FUNDING_ROUND", "STUDIED_AT",
               "SPOKE_AT", "RECEIVED_AWARD"]
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
    try:
        intro = cala_introspect(entity_id)
        have = set((intro.get("relationships") or {}).get("outgoing") or [])
        rels = [r for r in want if r in have] or want[:4]
        e = _entity(entity_id, props, rels)
    except Exception as ex:
        return JSONResponse({"error": f"{type(ex).__name__}: {str(ex)[:120]}"}, status_code=200)

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

    return {"id": entity_id, "kind": kind, "name": e.get("name"),
            "entity_type": e.get("entity_type"), "properties": out_props, "groups": groups}


def cala_introspect(eid):
    from . import cala_client as cala
    return cala.introspect(eid, allow_live=True, ttl=86400)


def _entity(eid, props, rels):
    from . import cala_client as cala
    return cala.get_entity(eid, properties=props, outgoing=rels, limit=25,
                           allow_live=True, ttl=86400)


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
        return JSONResponse({"error": f"{type(ex).__name__}: {str(ex)[:120]}", "places": []},
                            status_code=200)


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
    from . import logos
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
    return json.loads(CONVICTION.read_text())
