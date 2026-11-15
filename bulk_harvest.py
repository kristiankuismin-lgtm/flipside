"""Ask Cala the same six questions about everything we track.

One /knowledge/query answers in about the time one entity fetch takes and
returns a table instead of a record. The walker still collects whole
entities, because a profile page needs one; this collects the rows the
lists need, and it asks per subject so the answers stay specific.

Order matters when the clock is the constraint. People and departures feed
cohorts that are visibly thin; founders and priors feed the two rankings
that currently have almost no evidence behind them; rounds and boards are
depth on things that already work.
"""
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from app import api, bulk, cache_index

WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 3

# (kind, how many subjects to ask it about). The subject list is the same
# for all of them - the firms we track - except "left", which is about
# operating companies rather than funds.
# The new questions first. "people" is already 1,088 rows deep and most of
# its subjects are cache hits; "left" and "priors" have none at all, and
# they feed the two things with the least evidence behind them - the
# departures cohort and the founder-factory rate.
PLAN = [
    ("left", 140),
    ("priors", 90),
    ("founders", 180),
    ("people", 260),
    ("rounds", 140),
    ("board", 60),
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
    """Operating companies: who founded them, and who has left them."""
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


def main() -> int:
    fs, cs = funds(), companies()
    subjects = {"people": fs, "priors": fs, "board": fs,
                "left": cs, "founders": cs, "rounds": cs}
    jobs = [(kind, s) for kind, n in PLAN for s in subjects[kind][:n]]
    print(f"# {len(jobs)} questions over {len(fs)} firms and {len(cs)} companies",
          flush=True)
    t0, done = time.time(), 0

    def one(job):
        kind, subject = job
        try:
            return kind, subject, bulk.ask(kind, subject)
        except Exception:
            return kind, subject, 0

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for kind, subject, n in ex.map(one, jobs):
            done += 1
            if n:
                print(f"  {done:4}/{len(jobs)} {kind:9} +{n:3} {subject[:30]:<30} "
                      f"{bulk.kind_stats()} "
                      f"({done / max(1e-9, time.time() - t0) * 60:.1f}/min)",
                      flush=True)
    print("#", bulk.kind_stats(), bulk.stats())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
