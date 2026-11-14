#!/usr/bin/env python
"""Does "who follows this lead" predict who actually shows up?

The round architect's claim is that funds which have joined rounds a given
lead led will do so again. That is the most distinctive thing in the
product and it was the only reading with no evidence behind it.

Method, the same shape as the conviction backtest:

  - Split every round by date at a cutoff.
  - Build the follows-graph from rounds BEFORE the cutoff only.
  - For each round led by fund L AFTER the cutoff, ask whether our top
    predicted follower was actually in it.
  - Compare against the obvious baseline anyone would try first: that
    fund's most frequent co-investors overall, ignoring who led.

No look-ahead: the graph never sees a round at or after the cutoff.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict

from app import api, norm


def split(rbc: dict, cutoff: str):
    before, after = defaultdict(list), defaultdict(list)
    for company, rounds in rbc.items():
        for r in rounds or []:
            d = str(r.get("date") or "")
            if not d:
                continue
            (before if d < cutoff else after)[company].append(r)
    return dict(before), dict(after)


def follows_graph(rbc: dict):
    """lead -> Counter(other funds that were in rounds it led)."""
    follows, led = defaultdict(Counter), Counter()
    for rounds in rbc.values():
        for r in rounds or []:
            leads = {norm.name(x) for x in (r.get("leads") or []) if norm.name(x)}
            names = {norm.name(i) for i in (r.get("investors") or []) if norm.name(i)}
            for lead in leads:
                led[lead] += 1
                for other in names - {lead}:
                    follows[lead][other] += 1
    return follows, led


def coinvestors(rbc: dict):
    """The baseline: who this fund appears alongside, regardless of who led."""
    co = defaultdict(Counter)
    for rounds in rbc.values():
        for r in rounds or []:
            names = [norm.name(i) for i in (r.get("investors") or []) if norm.name(i)]
            for a in names:
                for b in names:
                    if a != b:
                        co[a][b] += 1
    return co


def run(cutoff: str, min_led: int = 3, k: int = 1) -> dict:
    rbc = api._rounds_by_company()
    before, after = split(rbc, cutoff)
    follows, led = follows_graph(before)
    co = coinvestors(before)

    hits = base_hits = trials = 0
    rate_sum = 0.0
    for rounds in after.values():
        for r in rounds or []:
            leads = {norm.name(x) for x in (r.get("leads") or []) if norm.name(x)}
            names = {norm.name(i) for i in (r.get("investors") or []) if norm.name(i)}
            for lead in leads:
                if led.get(lead, 0) < min_led or not follows.get(lead):
                    continue
                others = names - {lead}
                if not others:
                    continue
                trials += 1
                pred = [n for n, _ in follows[lead].most_common(k)]
                bl = [n for n, _ in co[lead].most_common(k) if n != lead][:k]
                hits += any(p in others for p in pred)
                base_hits += any(b in others for b in bl)
                # How much of the round did we name?
                rate_sum += len(set(pred) & others) / max(len(pred), 1)

    return {"cutoff": cutoff, "trials": trials, "k": k,
            "architect": round(100 * hits / trials, 1) if trials else None,
            "coinvest_baseline": round(100 * base_hits / trials, 1) if trials else None,
            "precision_at_k": round(100 * rate_sum / trials, 1) if trials else None}


if __name__ == "__main__":
    print("Does the round architect predict who shows up?\n")
    print(f"{'cutoff':>10} {'rounds':>7} {'k':>3} {'architect':>10} {'baseline':>9} {'lift':>7}")
    for cutoff in ("2023-01", "2024-01", "2025-01"):
        for k in (1, 2):
            r = run(cutoff, k=k)
            if not r["trials"]:
                print(f"{cutoff:>10} {0:>7}   — not enough held-out rounds")
                continue
            lift = round(r["architect"] - r["coinvest_baseline"], 1)
            print(f"{r['cutoff']:>10} {r['trials']:>7} {k:>3} "
                  f"{r['architect']:>9}% {r['coinvest_baseline']:>8}% "
                  f"{lift:>+6}pp")
