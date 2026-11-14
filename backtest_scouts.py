"""Does "likely to found" predict founding?

The scout list ranks people on a score with no backtest behind it, which the
page says out loud. This is the attempt to replace that sentence with a
number - and it is also the attempt to find out whether the number can
exist at all on the record we hold.

The method is the only honest one available: pick a cutoff year, score each
person using ONLY the evidence dated before it, and then look at who
actually founded something after it. Anything undated is excluded rather
than assumed early, because including it would let the future leak into the
prediction - a FOUNDED edge with no date might be from 2004 or from last
month, and guessing would mean grading our own homework.

    uv run python backtest_scouts.py --cutoff 2015
"""
from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from app import cache_index, metrics, scouts as SC

OUT = Path("backtest_scouts.json")
# The weights worth testing separately: each is a claim on its own.
SIGNALS = [
    ("founded before", lambda p: p["prior_foundings"] >= 1),
    ("founded twice before", lambda p: p["prior_foundings"] >= 2),
    ("ran something", lambda p: p["prior_operator"]),
    ("invests personally", lambda p: p["angel"]),
]


def _val(props, key):
    v = (props or {}).get(key)
    return v.get("value") if isinstance(v, dict) else v


def _year(it) -> int | None:
    v = _val(it.get("properties"), "valid_since")
    try:
        y = int(str(v)[:4])
    except (TypeError, ValueError):
        return None
    return y if 1900 < y < 2100 else None


def _rel(e, name):
    return ((e.get("relationships") or {}).get("outgoing") or {}).get(name) or []


def split(e: dict, cutoff: int, lookup) -> dict | None:
    """One person's evidence, cut at the year, with the outcome held back."""
    founded = [f for f in _rel(e, "FOUNDED") if not SC.is_a_firm(f, lookup)]
    dated = [(f, _year(f)) for f in founded]
    if not any(y for _, y in dated):
        return None             # nothing datable: this person cannot be graded

    prior = [f for f, y in dated if y is not None and y <= cutoff]
    after = [f for f, y in dated if y is not None and y > cutoff]

    ops = [it for k in ("IS_CEO_OF", "IS_CTO_OF", "IS_COO_OF", "IS_CFO_OF")
           for it in _rel(e, k)]
    prior_ops = [it for it in ops if (_year(it) or 9999) <= cutoff]
    angel = [it for it in _rel(e, "INVESTED_IN") + _rel(e, "PARTICIPATES_IN_FUNDING_ROUND")
             if (_year(it) or 9999) <= cutoff]

    return {
        "name": e.get("name"),
        "prior_foundings": len(prior),
        "prior_operator": bool(prior_ops),
        "angel": bool(angel),
        "founded_after": bool(after),
        # The score as the product would have computed it that day.
        "score": SC.WEIGHTS["founded"] * bool(prior)
                 + SC.WEIGHTS["serial"] * min(len(prior), SC.SERIAL_FULL) / SC.SERIAL_FULL
                 + (SC.WEIGHTS["operator"] if prior_ops and not prior else 0)
                 + (SC.WEIGHTS["angel"] if angel else 0),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", type=int, default=2015)
    ap.add_argument("--min-n", type=int, default=30,
                    help="sample below which no claim is made either way")
    a = ap.parse_args()

    idx = cache_index.build()
    lookup = idx.get
    rows = []
    for e in idx.values():
        if e.get("entity_type") != "Person":
            continue
        r = split(e, a.cutoff, lookup)
        if r:
            rows.append(r)

    base = sum(1 for r in rows if r["founded_after"])
    report = {
        "cutoff": a.cutoff,
        "people_graded": len(rows),
        "founded_after": base,
        "base_rate": round(base / len(rows), 3) if rows else None,
        "signals": [],
        "verdict": None,
    }

    for label, test in SIGNALS:
        hit = [r for r in rows if test(r)]
        miss = [r for r in rows if not test(r)]
        h = sum(1 for r in hit if r["founded_after"])
        m = sum(1 for r in miss if r["founded_after"])
        report["signals"].append({
            "signal": label,
            "with": {"n": len(hit), "founded": h,
                     "rate": round(h / len(hit), 3) if hit else None,
                     "lower": round(metrics.wilson_lower(h / len(hit), len(hit)), 3)
                              if hit else None},
            "without": {"n": len(miss), "founded": m,
                        "rate": round(m / len(miss), 3) if miss else None},
        })

    if len(rows) < a.min_n:
        report["verdict"] = (
            f"Cannot tell. {len(rows)} people carry a dated founding, and a "
            f"difference in rates is not readable below about {a.min_n}. This "
            f"is a statement about the record, not about the signal: the "
            f"scores are computed from edges that mostly have no date on them, "
            f"and a prediction cannot be graded against evidence it cannot "
            f"place in time.")
    else:
        best = max(report["signals"], key=lambda s: s["with"]["lower"] or 0)
        report["verdict"] = (
            f"{best['signal']}: {best['with']['rate']:.0%} founded again against "
            f"{best['without']['rate']:.0%} who did not have it "
            f"(n={best['with']['n']} and {best['without']['n']}).")

    OUT.write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
