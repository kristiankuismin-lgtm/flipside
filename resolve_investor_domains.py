"""Resolve website + headquarters for each screened investor.

The website gives the UI a real logo; the address puts funds on the map, so
the map stops being only about Slush exhibitors."""
import json, time

PACE = 1.2   # seconds between calls: the quota is a budget over time
from app import cala_client as cala, graph

# Merge with what previous runs resolved: the quota means a single pass
# rarely finishes, so runs must accumulate rather than overwrite.
try:
    out = json.load(open("investor_domains.json"))
except (FileNotFoundError, ValueError):
    out = {}
names = [l.strip() for l in open("investors.txt") if l.strip() and not l.startswith("#")]
names = [n for n in names if not (out.get(n) or {}).get("hq")]   # retry only gaps
print(f"{len(out)} already resolved, {len(names)} to try", flush=True)
for i, n in enumerate(names, 1):
    try:
        e = graph.find_investor(n)
        if not e:
            print(f"{i}/{len(names)} {n}: no entity"); continue
        # Ask the entity which of these it actually has, then request those.
        want = ["name", "description", "founding_date", "employee_count"] \
            + graph.ADDRESS_PROPS + graph.SITE_PROPS
        props = graph.pick_props(e["id"], want, allow_live=True, ttl=86400) or ["name"]
        full = cala.get_entity(e["id"], properties=props, allow_live=True, ttl=86400)
        w, _, _ = graph.first_prop(full, graph.SITE_PROPS)
        hq, hq_src, hq_key = graph.first_prop(full, graph.ADDRESS_PROPS)
        desc, _ = graph.prop(full, "description")
        founded, _ = graph.prop(full, "founding_date")
        staff, _ = graph.prop(full, "employee_count")
        out[n] = {"website": w, "hq": hq, "hq_field": hq_key, "description": desc,
                  "founded": founded, "employees": staff,
                  "id": e["id"], "entity_type": e.get("entity_type"),
                  "hq_source": (graph.best_source(hq_src) or {}).get("document")}
        print(f"{i}/{len(names)} {n}: {w or '—'} | {str(hq)[:42]}", flush=True)
    except Exception as ex:
        print(f"{i}/{len(names)} {n}: {type(ex).__name__}", flush=True)
    time.sleep(PACE)
json.dump(out, open("investor_domains.json", "w"), indent=1)
print(f"\n{len(out)}/{len(names)} resolved -> investor_domains.json")
