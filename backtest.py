"""Does insider conviction predict anything? A controlled test.

The first version of this script asked whether a company "raised again
within 24 months" and found conviction was mildly ANTI-predictive. That
was the outcome variable's fault, not the metric's: how often a company
needs money is not a measure of whether it is doing well. A company that
raised a large round and does not come back for three years looks like a
failure under that definition.

The right question is whether the company PROGRESSED - seed to A, A to B -
rather than taking a bridge, an extension, or nothing.

Controls that keep this honest:
  * No look-ahead: each investor's habit is recomputed from rounds closed
    strictly before the observation date.
  * Maturity: a round is only judged once it is old enough for the outcome
    to be observable.
  * Cap-table size: insider return FRACTION is mechanically tied to how
    many investors were already on the register, so every comparison is
    repeated inside fixed size buckets. A result that only appears in the
    pooled numbers is a confound, not a signal.
  * A baseline to beat: "backed by a top-decile most-active investor" is
    the naive strategy, and is reported alongside.
"""
import json, os, sys
from collections import Counter

os.environ.setdefault("CALA_CACHE_ONLY", "1")

from app import conviction as K, norm                       # noqa: E402
from app.cala_client import CacheMiss, CalaError            # noqa: E402
from app.company_rounds import company_history              # noqa: E402
from app.extract import investor_rounds                     # noqa: E402

STAGES = ["pre-seed", "seed", "series a", "series b", "series c",
          "series d", "series e", "growth"]
PROGRESS_WINDOW = 1095      # 36 months to reach a later stage
MATURITY = 730              # a round must be this old to be judged


def stage_rank(s):
    s = norm.stage(s)
    return STAGES.index(s) if s in STAGES else None


def corpus():
    names, out = set(), {}
    for inv in [l.strip() for l in open("investors.txt") if l.strip()]:
        try:
            for r in investor_rounds(inv):
                names.add(r.company)
        except (CacheMiss, CalaError):
            pass
    for n in sorted(names):
        try:
            h = sorted(company_history(n), key=lambda r: r.date)
            if len(h) >= 2:
                out[n] = h
        except (CacheMiss, CalaError):
            pass
    return out


def activity_as_of(hist, cutoff):
    c = Counter()
    for rs in hist.values():
        for r in rs:
            if r.date < cutoff:
                for inv in r.investors:
                    c[norm.name(inv)] += 1
    return c


def build(hist):
    rows = []
    for name, rs in hist.items():
        for i in range(1, len(rs)):
            obs = rs[i]
            if (K.TODAY - obs.date).days < MATURITY:
                continue
            prior = {norm.name(x) for r in rs[:i] for x in r.investors}
            cur = {norm.name(x) for x in obs.investors}
            if not prior or not cur:
                continue
            prior_leads = {norm.name(l) for r in rs[:i] for l in r.leads}
            nxt = rs[i + 1] if i + 1 < len(rs) else None
            r0 = stage_rank(obs.stage)
            r1 = stage_rank(nxt.stage) if nxt else None
            progressed = bool(nxt and r0 is not None and r1 is not None and r1 > r0
                              and (nxt.date - obs.date).days <= PROGRESS_WINDOW)
            act = activity_as_of(hist, obs.date)
            cut = sorted(act.values())[int(len(act) * .9)] if act else 1e9
            rows.append({
                "company": name, "date": str(obs.date), "stage": obs.stage,
                "n_prior": len(prior),
                "ret_frac": len(prior & cur) / len(prior),
                "lead_back": (any(l in cur for l in prior_leads) if prior_leads else None),
                "naive_active": any(act.get(x, 0) >= cut for x in cur),
                "progressed": progressed,
            })
    return rows


def rate(sub):
    return len(sub), (sum(r["progressed"] for r in sub) / len(sub) if sub else 0.0)


def main():
    hist = corpus()
    rows = build(hist)
    if not rows:
        print("no mature samples")
        return 1

    n, base = rate(rows)
    hi = [r for r in rows if r["ret_frac"] >= .5]
    lo = [r for r in rows if r["ret_frac"] < .5]
    nh, ph = rate(hi)
    nl, pl = rate(lo)

    naive = [r for r in rows if r["naive_active"]]
    nn, pn = rate(naive)

    lb = [r for r in rows if r["lead_back"] is True]
    la = [r for r in rows if r["lead_back"] is False]
    nlb, plb = rate(lb)
    nla, pla = rate(la)

    buckets = []
    for a, b, lbl in [(1, 2, "1"), (2, 4, "2-3"), (4, 7, "4-6"), (7, 999, "7+")]:
        sub = [r for r in rows if a <= r["n_prior"] < b]
        x = rate([r for r in sub if r["ret_frac"] < .5])
        y = rate([r for r in sub if r["ret_frac"] >= .5])
        buckets.append({"cap_table": lbl, "low_n": x[0], "low": round(x[1], 4),
                        "high_n": y[0], "high": round(y[1], 4),
                        "spread_pp": round(100 * (y[1] - x[1]), 1)})

    out = {
        "outcome": "progressed to a later stage within 36 months",
        "samples": n, "base_rate": round(base, 4),
        "high_insider_return": {"n": nh, "rate": round(ph, 4), "lift_pp": round(100 * (ph - base), 1)},
        "low_insider_return": {"n": nl, "rate": round(pl, 4), "lift_pp": round(100 * (pl - base), 1)},
        "spread_pp": round(100 * (ph - pl), 1),
        "naive_most_active": {"n": nn, "rate": round(pn, 4), "lift_pp": round(100 * (pn - base), 1)},
        "previous_lead_returned": {"n": nlb, "rate": round(plb, 4)},
        "previous_lead_absent": {"n": nla, "rate": round(pla, 4)},
        "lead_spread_pp": round(100 * (plb - pla), 1),
        "by_cap_table_size": buckets,
        "rows": rows,
    }
    json.dump(out, open("backtest.json", "w"), indent=1)

    print(f"outcome: {out['outcome']}")
    print(f"samples {n}, base rate {base:.1%}\n")
    print(f"insiders back >=50%   n={nh:4d}  {ph:.1%}   {100*(ph-base):+.1f}pp vs base")
    print(f"insiders back  <50%   n={nl:4d}  {pl:.1%}   {100*(pl-base):+.1f}pp vs base")
    print(f"spread                       {100*(ph-pl):+.1f}pp\n")
    print(f"naive 'most active'   n={nn:4d}  {pn:.1%}   {100*(pn-base):+.1f}pp vs base\n")
    print(f"previous lead back    n={nlb:4d}  {plb:.1%}")
    print(f"previous lead absent  n={nla:4d}  {pla:.1%}   spread {100*(plb-pla):+.1f}pp\n")
    print("controlled for cap-table size:")
    for b in buckets:
        print(f"  {b['cap_table']:>4s} prior  low n={b['low_n']:3d} {b['low']:.1%}"
              f"   high n={b['high_n']:3d} {b['high']:.1%}   {b['spread_pp']:+.1f}pp")
    return 0


if __name__ == "__main__":
    sys.exit(main())
