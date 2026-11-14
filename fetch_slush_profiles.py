"""Fetch location + industry for every Slush 2026 exhibitor.

Uses the Entities API rather than /knowledge/query: ~0.3s per company
instead of ~45s, and every property arrives with its own sources[].
2000 companies finish in minutes, which is what makes a live map honest
rather than a hand-picked sample.
"""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import cala_client as cala, graph

PROPS = ["name", "headquarters_address", "website", "description", "founding_date"]


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def one(p):
    try:
        e = cala.get_entity(p["id"], properties=PROPS, outgoing=["OPERATES_IN_INDUSTRY"], limit=4)
        hq, hq_src = graph.prop(e, "headquarters_address")
        web, _ = graph.prop(e, "website")
        desc, _ = graph.prop(e, "description")
        founded, _ = graph.prop(e, "founding_date")
        inds = [i.get("name") for i in graph.rels(e, "outgoing", "OPERATES_IN_INDUSTRY")]
        best = graph.best_source(hq_src)
        return {"id": p["id"], "name": p["name"], "hq": hq, "website": web,
                "description": desc, "founded": founded, "industries": inds,
                "hq_source": (best or {}).get("document")}
    except Exception as e:
        return {"id": p["id"], "name": p["name"], "error": f"{type(e).__name__}: {str(e)[:60]}"}


def main():
    parts = json.load(open("slush_participants.json"))
    parts = [p for p in parts if p.get("entity_type") == "Company"]
    workers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    target = int(sys.argv[2]) if len(sys.argv) > 2 else 400

    # Resume: anything already fetched stays, so repeated runs accumulate.
    try:
        done = {r["id"]: r for r in json.load(open("slush_profiles.json"))}
    except (FileNotFoundError, ValueError):
        done = {}
    todo = [p for p in parts if p["id"] not in done or done[p["id"]].get("error")]
    todo = todo[:max(0, target - sum(1 for r in done.values() if not r.get("error")))]
    log(f"{len(done)} already stored, fetching {len(todo)} more "
        f"(target {target} of {len(parts)}), {workers} workers")

    t0, errs, n = time.time(), 0, 0
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, todo):
            done[r["id"]] = r
            n += 1
            errs += bool(r.get("error"))
            if n % 25 == 0:
                ok = sum(1 for x in done.values() if not x.get("error"))
                json.dump(list(done.values()), open("slush_profiles.json", "w"), indent=1)
                log(f"{n}/{len(todo)}  stored_ok={ok}  errors={errs}  {time.time()-t0:.0f}s")

    json.dump(list(done.values()), open("slush_profiles.json", "w"), indent=1)
    ok = [r for r in done.values() if not r.get("error")]
    with_hq = sum(1 for r in ok if r.get("hq"))
    log(f"DONE  stored {len(ok)} profiles, {with_hq} with an address, "
        f"{errs} errors this run, {time.time()-t0:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
