"""Give every exhibitor a real coordinate instead of a city centroid.

Nominatim allows one request per second, so this is slow by design and
resumable: results are cached on disk and re-runs skip what is done.
"""
import json, sys, time
from app import geocode, geo

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

profs = [p for p in json.load(open("slush_profiles.json")) if not p.get("error") and p.get("hq")]
limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(profs)
profs = profs[:limit]
log(f"{len(profs)} addresses to resolve (≈1/s, cached)")

exact = approx = miss = 0
for i, p in enumerate(profs, 1):
    r = geocode.lookup(p["hq"])
    if r:
        exact += 1
    elif geo.locate(p["hq"]):
        approx += 1
    else:
        miss += 1
    if i % 25 == 0:
        log(f"{i}/{len(profs)}  exact={exact} approx={approx} unplaced={miss}")
log(f"DONE exact={exact} approx={approx} unplaced={miss}")
