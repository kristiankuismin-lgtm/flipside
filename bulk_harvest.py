"""Ask Cala who works at every firm we track, and keep the answers.

One query returns tens of people with their roles. The entity walker returns
one entity. Both cost about the same, so this runs alongside it.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from app import api, bulk, cache_index

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 3


def firms() -> list[str]:
    """Every firm worth asking about, most useful first."""
    out, seen = [], set()
    for n in api._investor_pool():
        k = n.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(n.strip())
    # Then every fund-ish organisation the graph already holds.
    idx = cache_index.build()
    for e in idx.values():
        if e.get("entity_type") not in ("Organization", "Company"):
            continue
        n = (e.get("name") or "").strip()
        k = n.lower()
        if not n or k in seen:
            continue
        rel = e.get("relationships") or {}
        inv = sum(len(((rel.get(d) or {}).get("INVESTED_IN") or []))
                  for d in ("incoming", "outgoing"))
        if inv >= 2:                       # it behaves like an investor
            seen.add(k)
            out.append(n)
    return out


def main() -> int:
    todo = firms()
    print(f"# {len(todo)} firms to ask about, {WORKERS} at a time")
    t0, done = time.time(), 0

    def one(f):
        try:
            return f, bulk.people_at(f)
        except Exception:
            return f, 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for f, n in ex.map(one, todo):
            done += 1
            if n:
                s = bulk.stats()
                print(f"  {done:4}/{len(todo)}  +{n:3} from {f[:34]:<34} "
                      f"total {s['people']} people at {s['firms']} firms "
                      f"({done/max(1e-9, time.time()-t0)*60:.1f} firms/min)",
                      flush=True)
    print("#", bulk.stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
