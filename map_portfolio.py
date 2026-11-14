"""Put the funded universe on the map, not just the Slush floor.

Slush 2026 is the only event in Cala with a participant list - Web Summit,
TechCrunch Disrupt, VivaTech and even Slush 2025 all return zero - so more
events is a dead end. The 851 portfolio companies already cached for the
founder screen are a better universe anyway: every one of them has raised.

Public registers were tried first and only covered about a fifth (GLEIF needs
an LEI, PRH is Finland only), so this resolves the rest through Cala, patiently
and resumably: the quota is a budget over time, so waiting beats aborting.
"""
import json, os, sys, time

os.environ.setdefault("CALA_CACHE_ONLY", "1")

from app import cala_client as cala, datasets as D, geo, geocode, graph
from app.cala_client import CacheMiss, CalaError
from app.extract import investor_rounds

STATE = "portfolio_places.json"
PACE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.8
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 400


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def corpus():
    names, sector = set(), {}
    for inv in [l.strip() for l in open("investors.txt") if l.strip()]:
        try:
            for r in investor_rounds(inv):
                names.add(r.company)
        except (CacheMiss, CalaError):
            pass
    return sorted(names)


def main():
    names = corpus()
    try:
        state = json.load(open(STATE))
    except (FileNotFoundError, ValueError):
        state = {}

    todo = [n for n in names if n not in state][:LIMIT]
    log(f"{len(names)} companies, {len(state)} resolved, trying {len(todo)}")

    backoff, placed, fails = 45.0, 0, 0
    os.environ["CALA_CACHE_ONLY"] = ""          # this job is allowed to fetch
    cala.CACHE_ONLY = False

    for i, n in enumerate(todo, 1):
        # Public registers first: free, and they never touch Cala's budget.
        hq = src = None
        g = D.gleif(n)
        if g and g.get("address"):
            hq, src = g["address"], "GLEIF"

        if not hq:
            try:
                e = graph.find_company(n, interactive=False, retries=3, timeout=45)
                if e:
                    props = graph.pick_props(e["id"], ["name", "website", "description"]
                                             + graph.ADDRESS_PROPS,
                                             allow_live=True, ttl=7 * 86400) or ["name"]
                    full = cala.get_entity(e["id"], properties=props,
                                           allow_live=True, ttl=7 * 86400)
                    hq, _, key = graph.first_prop(full, graph.ADDRESS_PROPS)
                    web, _ = graph.prop(full, "website")
                    src = f"Cala.{key}" if hq else None
                    state.setdefault(n, {})["website"] = web
                backoff = 45.0
            except CalaError as ex:
                if "Rate limit" in str(ex):
                    json.dump(state, open(STATE, "w"))
                    log(f"{i}/{len(todo)} quota wall — sleeping {backoff:.0f}s "
                        f"({len(state)} resolved)")
                    time.sleep(backoff)
                    backoff = min(backoff * 1.4, 480)
                    continue
                fails += 1
            except Exception:
                fails += 1

        rec = state.setdefault(n, {})
        rec["hq"] = hq
        rec["source"] = src
        if hq:
            fine = geocode.lookup(hq)
            loc = geo.locate(hq)
            if fine:
                rec.update(lat=fine["lat"], lon=fine["lon"], precise=True,
                           cc=(loc or (0, 0, "??"))[2])
                placed += 1
            elif loc:
                rec.update(lat=loc[0], lon=loc[1], precise=False, cc=loc[2])
                placed += 1
        time.sleep(PACE)
        if i % 25 == 0:
            json.dump(state, open(STATE, "w"))
            log(f"{i}/{len(todo)} placed={placed} fails={fails}")

    json.dump(state, open(STATE, "w"))
    total = sum(1 for v in state.values() if v.get("lat"))
    log(f"DONE {len(state)} looked up, {total} on the map, {fails} failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
