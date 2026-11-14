"""Discover the investors who already back your competitors.

A fixed list of funds is arbitrary. The funds that matter are the ones that
already wrote cheques in your exact category: they understand it, and some of
them are conflicted. Both facts are useful, and both come from the same hop.

    competitors(you) -> their funding rounds -> the investors on those rounds
"""
import json, sys, time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.company_rounds import company_history
from app.conflict import competitors
from app import norm

QUERY = ("Gosta Labs (gostalabs.com), the Finnish healthtech startup whose "
         "AI assistant Gosta Aide writes clinical documentation for doctors")

comps = competitors(sys.argv[1] if len(sys.argv) > 1 else QUERY)
print(f"[{time.strftime('%H:%M:%S')}] {len(comps)} competitors", flush=True)

backers: dict[str, set] = defaultdict(set)
counts = Counter()


def go(c):
    try:
        return c, company_history(c["name"])
    except Exception as e:
        return c, f"FAIL {type(e).__name__}: {str(e)[:70]}"


with ThreadPoolExecutor(4) as ex:
    for i, f in enumerate(as_completed([ex.submit(go, c) for c in comps]), 1):
        c, rounds = f.result()
        if isinstance(rounds, str):
            print(f"[{time.strftime('%H:%M:%S')}] {i}/{len(comps)} {c['name']}: {rounds}", flush=True)
            continue
        inv = {i2 for r in rounds for i2 in r.investors}
        for name in inv:
            backers[norm.name(name)].add(c["name"])
            counts[name] += 1
        print(f"[{time.strftime('%H:%M:%S')}] {i}/{len(comps)} {c['name']}: "
              f"{len(rounds)} rounds, {len(inv)} investors", flush=True)

rows = sorted(counts.items(), key=lambda kv: -kv[1])
print(f"\n{len(rows)} distinct investors back your competitors\n")
for name, n in rows[:40]:
    who = sorted(backers[norm.name(name)])
    print(f"  {n}x  {name:34s} {', '.join(who[:3])}")

with open("competitor_investors.json", "w") as fh:
    json.dump({"competitors": [c["name"] for c in comps],
               "investors": [{"name": n, "backs": sorted(backers[norm.name(n)])}
                             for n, _ in rows]}, fh, indent=2)
print("\n-> competitor_investors.json")
