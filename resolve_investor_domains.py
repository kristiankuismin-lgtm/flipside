"""Resolve website + headquarters for each screened investor.

The website gives the UI a real logo; the address puts funds on the map, so
the map stops being only about Slush exhibitors."""
import json, time
from app import cala_client as cala, graph

out = {}
names = [l.strip() for l in open("investors.txt") if l.strip() and not l.startswith("#")]
for i, n in enumerate(names, 1):
    try:
        e = graph.find_investor(n)
        if not e:
            print(f"{i}/{len(names)} {n}: no entity"); continue
        full = cala.get_entity(e["id"], properties=["name", "website",
                               "headquarters_address", "description"],
                               allow_live=True, ttl=86400)
        w, _ = graph.prop(full, "website")
        hq, hq_src = graph.prop(full, "headquarters_address")
        desc, _ = graph.prop(full, "description")
        out[n] = {"website": w, "hq": hq, "description": desc,
                  "id": e["id"], "entity_type": e.get("entity_type"),
                  "hq_source": (graph.best_source(hq_src) or {}).get("document")}
        print(f"{i}/{len(names)} {n}: {w or '—'} | {str(hq)[:42]}", flush=True)
    except Exception as ex:
        print(f"{i}/{len(names)} {n}: {type(ex).__name__}", flush=True)
json.dump(out, open("investor_domains.json", "w"), indent=1)
print(f"\n{len(out)}/{len(names)} resolved -> investor_domains.json")
