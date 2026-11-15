"""Ask Cala every question we have, about everything we track.

One /knowledge/query returns a table instead of a record, so this is the
half of the harvest that collects rows rather than entities.

Two things this got wrong before and no longer does.

A refused question used to be indistinguishable from an answered one with
nothing in it: ask() returned 0 for both and the driver only printed
non-zero, so a run reported 868 of 868 complete while 554 of those had been
turned away by the rate limiter and never recorded. "priors" was asked zero
times and looked like a question the graph could not answer. It answers it
fine - 16 rows for the first firm tried. So Unanswered is now raised,
retried, and counted separately in the summary.

And a question takes twenty to forty seconds, not the two the old rate
implied. The earlier "171 a minute" was the speed of failing. Real
throughput is roughly two per worker per minute, and the ceiling is server
concurrency rather than the token bucket.
"""
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from app import api, bulk, cache_index

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 8
ATTEMPTS = 3

# Emptiest first. priors, education, coinvest, exits and angels have never
# landed a row; bio is the only question that is about a person rather than
# about an institution they appear inside.
PLAN = [
    ("priors",    90),
    ("bio",      220),
    ("coinvest",  70),
    ("education", 70),
    ("exits",     70),
    ("angels",   110),
    ("founders", 200),
    ("left",     160),
    ("rounds",   140),
    ("board",     60),
    ("people",   260),
]


def funds() -> list[str]:
    out, seen = [], set()
    for n in api._investor_pool():
        k = n.strip().lower()
        if k and k not in seen:
            seen.add(k)
            out.append(n.strip())
    idx = cache_index.build()
    for e in idx.values():
        if e.get("entity_type") not in ("Organization", "Company"):
            continue
        n = (e.get("name") or "").strip()
        if not n or n.lower() in seen:
            continue
        rel = e.get("relationships") or {}
        if sum(len(((rel.get(d) or {}).get("INVESTED_IN") or []))
               for d in ("incoming", "outgoing")) >= 2:
            seen.add(n.lower())
            out.append(n)
    return out


def companies() -> list[str]:
    idx = cache_index.build()
    scored = []
    for e in idx.values():
        if e.get("entity_type") != "Company":
            continue
        n = (e.get("name") or "").strip()
        if not n:
            continue
        rel = e.get("relationships") or {}
        weight = sum(len(((rel.get(d) or {}).get(k) or []))
                     for d in ("incoming", "outgoing")
                     for k in ("INVESTED_IN", "PARTICIPATES_IN_FUNDING_ROUND",
                               "WORKS_AT", "FOUNDED"))
        if weight:
            scored.append((weight, n))
    scored.sort(reverse=True)
    return [n for _, n in scored]


def people() -> list[str]:
    """The names worth another round: seniority first, then the graph's own.

    Everything else here asks about an institution and gets a person back as
    a cell. These are the people that produced, asked about directly.
    """
    senior = ("founder", "ceo", "chief", "partner", "president", "head",
              "chair", "director", "vp", "managing")
    scored, seen = [], set()
    for r in bulk.everyone():
        nm = (r.get("name") or "").strip()
        k = nm.lower()
        if not nm or " " not in nm or k in seen or len(nm) > 48:
            continue
        seen.add(k)
        role = (r.get("role") or "").lower()
        scored.append((2 if any(w in role for w in senior) else 1, nm))
    idx = cache_index.build()
    for e in idx.values():
        if e.get("entity_type") != "Person":
            continue
        nm = (e.get("name") or "").strip()
        k = nm.lower()
        if not nm or " " not in nm or k in seen:
            continue
        seen.add(k)
        rel = e.get("relationships") or {}
        edges = sum(len(v or ()) for d in ("incoming", "outgoing")
                    for v in (rel.get(d) or {}).values())
        scored.append((3 if edges >= 3 else 1, nm))
    scored.sort(key=lambda t: -t[0])
    return [n for _, n in scored]


def main() -> int:
    fs, cs, ps = funds(), companies(), people()
    subjects = {"people": fs, "priors": fs, "board": fs, "coinvest": fs,
                "education": fs, "exits": fs,
                "left": cs, "founders": cs, "rounds": cs, "angels": cs,
                "bio": ps}
    jobs = [(kind, s) for kind, n in PLAN for s in subjects[kind][:n]]
    print(f"# {len(jobs)} questions over {len(fs)} firms, {len(cs)} companies "
          f"and {len(ps)} people, {WORKERS} workers", flush=True)
    t0 = time.time()
    tally = {"rows": 0, "answered": 0, "empty": 0, "refused": 0}

    def one(job):
        kind, subject = job
        for i in range(ATTEMPTS):
            try:
                return kind, subject, bulk.ask(kind, subject), None
            except bulk.Unanswered as e:
                # The bucket refills on a timer; sleeping is the whole fix.
                time.sleep(min(30.0, 4.0 * (i + 1)) + random.random() * 3)
                last = str(e)
            except Exception as e:
                return kind, subject, 0, str(e)[:80]
        return kind, subject, 0, last

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (kind, subject, n, err) in enumerate(ex.map(one, jobs), 1):
            if err:
                tally["refused"] += 1
            elif n:
                tally["answered"] += 1
                tally["rows"] += n
            else:
                tally["empty"] += 1
            if n or i % 25 == 0:
                print(f"  {i:4}/{len(jobs)} {kind:9} +{n:3} {subject[:28]:<28} "
                      f"{tally} {i / max(1e-9, time.time() - t0) * 60:.1f}/min",
                      flush=True)
    print("#", tally, bulk.kind_stats(), bulk.stats(), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
