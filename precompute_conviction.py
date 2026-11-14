"""Investor side: run insider conviction over the Slush 2026 floor.

Cala holds Slush 2026 as an event with ~2000 sourced attendee companies.
That is the investor's universe on Tuesday: everyone exhibiting, in one
list, with a date on the source. We score the ones that have raised twice.

    python precompute_conviction.py --limit 60 --workers 5
"""
import argparse, json, re, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import cala_client as cala, conviction as K, norm
from app.company_rounds import company_history

SLUSH = "bc844d56-6ab4-452b-96bf-2661e86e592b"
_JUNK = re.compile(r"\b(gmbh|ltd|oy|ab|inc|llc|bv|as)\b", re.I)


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def slush_companies(limit):
    """Attendees, newest-looking first. Cached after the first call."""
    try:
        parts = json.load(open("slush_participants.json"))
    except FileNotFoundError:
        parts = cala.get_relations(SLUSH, "PARTICIPATES_IN_EVENT", max_items=2000)
        json.dump(parts, open("slush_participants.json", "w"))
    names = [p["name"] for p in parts
             if p.get("entity_type") == "Company" and len(p.get("name", "")) > 2]
    return names[:limit]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--workers", type=int, default=5)
    a = ap.parse_args()

    names = slush_companies(a.limit)
    log(f"Slush 2026: scoring {len(names)} exhibiting companies")

    def fetch(n):
        try:
            return n, company_history(n, with_amount=True)
        except Exception as e:
            return n, f"FAIL {type(e).__name__}: {str(e)[:70]}"

    hist, fails = {}, 0
    with ThreadPoolExecutor(a.workers) as ex:
        for i, f in enumerate(as_completed([ex.submit(fetch, n) for n in names]), 1):
            n, rs = f.result()
            if isinstance(rs, str):
                fails += 1
                log(f"{i}/{len(names)} {n}: {rs}")
                continue
            hist[n] = rs
            log(f"{i}/{len(names)} {n}: {len(rs)} rounds")

    # Baselines: how often does each insider usually return? Computed from the
    # same corpus, so no extra calls. Shrunk toward the pool mean when thin.
    appear, came_back = Counter(), Counter()
    for rs in hist.values():
        rs = sorted(rs, key=lambda r: r.date)
        for idx in range(len(rs) - 1):
            for inv in rs[idx].investors:
                k = norm.name(inv)
                appear[k] += 1
                if norm.matches(inv, rs[idx + 1].investors):
                    came_back[k] += 1
    pool = (sum(came_back.values()) / sum(appear.values())) if appear else 0.5
    PRIOR = 3.0   # pseudo-observations pulling thin baselines to the pool mean
    baselines = {k: (came_back[k] + pool * PRIOR) / (n + PRIOR) for k, n in appear.items()}

    # Investor kind, inferred from the stages they appear at.
    stages = {}
    for rs in hist.values():
        for r in rs:
            for inv in r.investors:
                stages.setdefault(norm.name(inv), set()).add(norm.stage(r.stage))
    kinds = {}
    for k, st in stages.items():
        late = any(s in st for s in ("series b", "series c", "series d", "growth"))
        early = any(s in st for s in ("pre-seed", "seed"))
        kinds[k] = K.MULTISTAGE if (late and early) else K.SEED_FUND if early else K.UNKNOWN

    out = []
    for n, rs in hist.items():
        c = K.assess(n, rs, baselines=baselines, kinds=kinds)
        if c.score is None:
            continue
        out.append({
            "company": n, "score": c.score, "structure": c.structure,
            "confidence": c.confidence, "reasons": c.reasons,
            "previous_lead_returned": c.previous_lead_returned,
            "n_insiders": c.n_insiders,
            "rounds": [{"stage": r.stage, "date": str(r.date), "amount": r.amount_eur,
                        "investors": r.investors, "leads": r.leads} for r in
                       sorted(rs, key=lambda x: x.date)],
            "insiders": [{"name": i.name, "returned": i.returned, "was_lead": i.was_lead,
                          "kind": i.kind, "baseline": i.baseline} for i in c.insiders],
        })
    out.sort(key=lambda x: -x["score"])

    json.dump({"event": "Slush 2026", "event_date": "2026-11-18",
               "screened": len(names), "scored": len(out),
               "pool_baseline": round(pool, 3), "companies": out},
              open("conviction.json", "w"), indent=1)

    log(f"DONE: screened {len(names)}, scored {len(out)}, fetch failures {fails}")
    log(f"structures: {dict(Counter(c['structure'] for c in out))}")
    for c in out[:10]:
        log(f"  {c['score']:5.1f} {c['structure']:12s} {c['company'][:34]:36s} {c['reasons'][0] if c['reasons'] else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
