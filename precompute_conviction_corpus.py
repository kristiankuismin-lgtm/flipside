"""Build the investor-side dataset from everything already cached.

The 245 company histories fetched for the founder side are all funded
companies with multi-round histories — exactly the corpus insider
conviction needs, at zero additional API cost. Slush 2026 attendance is
layered on top as an overlay, not as the universe: Cala's Slush list is
the exhibiting startups, most of which have not raised twice yet.
"""
import json, sys, time
from collections import Counter

from app import conviction as K, norm
from app.cala_client import CacheMiss, CalaError
from app.company_rounds import company_history
from app.extract import investor_rounds
from app import metrics as M

import os
os.environ.setdefault("CALA_CACHE_ONLY", "1")


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def corpus() -> dict[str, list]:
    """Every company history sitting in the cache."""
    names, out = set(), {}
    for inv in [l.strip() for l in open("investors.txt") if l.strip()]:
        try:
            for r in investor_rounds(inv):
                names.add(r.company)
        except (CacheMiss, CalaError):
            pass
    for n in sorted(names):
        h = None
        # Prefer the priced history when one was fetched: round size is what
        # separates a pre-emption from a bridge. Fall back to the unpriced
        # version rather than dropping the company.
        for with_amount in (True, False):
            try:
                cand = company_history(n, with_amount=with_amount)
                if len(cand) >= 2:
                    h = cand
                    break
            except (CacheMiss, CalaError):
                continue
        if h:
            out[n] = h
    return out


def main():
    hist = corpus()
    log(f"corpus: {len(hist)} companies with 2+ rounds (all from cache)")

    # Habit baselines from the same corpus, shrunk toward the pool mean.
    appear, back = Counter(), Counter()
    for rs in hist.values():
        rs = sorted(rs, key=lambda r: r.date)
        for i in range(len(rs) - 1):
            for inv in rs[i].investors:
                k = norm.name(inv)
                appear[k] += 1
                if norm.matches(inv, rs[i + 1].investors):
                    back[k] += 1
    pool = sum(back.values()) / sum(appear.values()) if appear else .5
    PRIOR = 3.0
    baselines = {k: (back[k] + pool * PRIOR) / (n + PRIOR) for k, n in appear.items()}
    log(f"pool follow-on rate {pool:.1%} over {sum(appear.values())} observations")

    # Investor kind from the stages they appear at.
    stages: dict[str, set] = {}
    for rs in hist.values():
        for r in rs:
            for inv in r.investors:
                stages.setdefault(norm.name(inv), set()).add(norm.stage(r.stage))
    kinds = {}
    for k, st in stages.items():
        late = any(s in st for s in ("series b", "series c", "series d", "growth"))
        early = any(s in st for s in ("pre-seed", "seed"))
        kinds[k] = K.MULTISTAGE if (late and early) else K.SEED_FUND if early else K.UNKNOWN

    # Which investors have stopped deploying? Reuse the founder-side pace metric.
    slowing = set()
    for inv in [l.strip() for l in open("investors.txt") if l.strip()]:
        try:
            rs = investor_rounds(inv)
            if rs and M.dry_powder(inv, M.by_company(rs)).label == "🔴":
                slowing.add(norm.name(inv))
        except (CacheMiss, CalaError):
            pass
    log(f"{len(slowing)} investors flagged as no longer deploying")

    # Slush overlay
    try:
        slush = {norm.name(p["name"]) for p in json.load(open("slush_participants.json"))}
    except FileNotFoundError:
        slush = set()
    log(f"Slush 2026 overlay: {len(slush)} exhibiting companies")

    out, orphans = [], []
    for n, rs in hist.items():
        c = K.assess(n, rs, baselines=baselines, kinds=kinds, slowing=slowing)
        if c.score is None:
            continue
        rs_sorted = sorted(rs, key=lambda r: r.date)
        lead_slowing = any(norm.name(l) in slowing for r in rs_sorted for l in r.leads)
        out.append({
            "company": n, "score": c.score, "structure": c.structure,
            "confidence": c.confidence, "reasons": c.reasons,
            "previous_lead_returned": c.previous_lead_returned,
            "n_insiders": c.n_insiders, "at_slush": norm.name(n) in slush,
            "rounds": [{"stage": r.stage, "date": str(r.date), "amount": r.amount_eur,
                        "investors": r.investors, "leads": r.leads} for r in rs_sorted],
            "insiders": [{"name": i.name, "returned": i.returned, "was_lead": i.was_lead,
                          "kind": i.kind, "baseline": i.baseline} for i in c.insiders],
        })
        # Orphan check. Headcount series is not in our cache, so this stays
        # honest: without it no company qualifies, and the UI says so.
        ok, why = K.is_orphan(n, rs_sorted, headcount_growth=None,
                              lead_fund_slowing=lead_slowing)
        if ok:
            orphans.append({"company": n, "why": why,
                            "months": int((K.TODAY - rs_sorted[-1].date).days / 30.4)})

    out.sort(key=lambda x: -x["score"])
    json.dump({"source": "Cala knowledge graph", "corpus": len(hist), "scored": len(out),
               "pool_baseline": round(pool, 4), "slush_overlay": len(slush),
               "companies": out, "orphans": orphans},
              open("conviction.json", "w"), indent=1)

    log(f"scored {len(out)} companies, {len(orphans)} orphans")
    log(f"structures: {dict(Counter(c['structure'] for c in out))}")
    log(f"at Slush 2026: {sum(1 for c in out if c['at_slush'])}")
    for c in out[:12]:
        log(f"  {c['score']:5.1f} {c['structure']:12s} {c['company'][:30]:32s} "
            f"{c['insiders'] and sum(i['returned'] for i in c['insiders'])}/{c['n_insiders']} back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
