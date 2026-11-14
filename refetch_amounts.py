"""Re-fetch the most interesting companies WITH round sizes.

Pre-emption (insiders back at >=2x inside 12 months) is the strongest
positive signal conviction can produce, and it needs amounts. The cached
corpus was fetched without them, so the engine honestly reports
"structure unknown". This fills that gap for the companies where it matters:
the top of the ranking, plus everything currently flagged as a bridge.
"""
import json, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.company_rounds import company_history

d = json.load(open("conviction.json"))
top = [c["company"] for c in d["companies"][:40]]
odd = [c["company"] for c in d["companies"] if c["structure"] in ("bridge", "unknown")]
names = list(dict.fromkeys(top + odd))
w = int(sys.argv[1]) if len(sys.argv) > 1 else 5
print(f"[{time.strftime('%H:%M:%S')}] refetching {len(names)} companies with amounts, {w} workers", flush=True)

def go(n):
    try:
        h = company_history(n, with_amount=True)
        return n, sum(1 for r in h if r.amount_eur is not None), len(h)
    except Exception as e:
        return n, f"FAIL {type(e).__name__}", 0

done = 0
with ThreadPoolExecutor(w) as ex:
    for f in as_completed([ex.submit(go, n) for n in names]):
        n, amt, tot = f.result(); done += 1
        print(f"[{time.strftime('%H:%M:%S')}] {done}/{len(names)} {n}: {amt}/{tot} rounds priced", flush=True)
