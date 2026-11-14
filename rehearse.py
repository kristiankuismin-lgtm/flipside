#!/usr/bin/env python
"""Walk the demo path and time it, so the stage is not the first rehearsal.

Every endpoint the three-minute script touches, in order, with a budget. A
run that passes here will not stall in front of judges; a run that fails
here fails now, when there is time to do something about it.

    uv run python rehearse.py                 # against a running server
    CALA_CACHE_ONLY=1 uv run python rehearse.py   # prove it needs no network
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.getenv("FLIPSIDE_URL", "http://localhost:8077")
COMPANY, STAGE = "Gosta Labs", "series a"

# (label, method, path, body, seconds we are willing to stand there)
STEPS = [
    ("Home page loads", "GET", "/", None, 2),
    ("Ask classifies a fund", "GET", f"/classify?q={urllib.parse.quote('lifeline ventures')}", None, 3),
    ("Ask classifies a company", "GET", f"/classify?q={urllib.parse.quote(COMPANY)}", None, 3),
    ("Founder screen", "POST", "/analyze",
     {"company": COMPANY, "stage": STAGE, "limit": 14}, 150),
    ("Round architect", "POST", "/syndicates",
     {"company": COMPANY, "stage": STAGE, "limit": 14}, 60),
    ("Outreach brief", "POST", "/outreach",
     {"company": COMPANY, "stage": STAGE, "limit": 14, "investor": "Balderton Capital"}, 60),
    ("Conflicted fund refuses a brief", "POST", "/outreach",
     {"company": COMPANY, "stage": STAGE, "limit": 14, "investor": "Northzone"}, 60),
    ("Insider conviction", "GET", "/conviction", None, 20),
    ("Contradictions", "GET", "/contradictions", None, 30),
    ("Backtest", "GET", "/backtest", None, 10),
    ("Map", "GET", "/map", None, 40),
    ("Near me (Helsinki)", "GET", "/near?lat=60.17&lon=24.94&radius_km=400&kind=fund", None, 30),
    ("Founder signal", "GET",
     "/founder-signal/af1c7427-b685-4e0c-b03a-7efb074bc3ff?name=Ilkka%20Paananen", None, 40),
    ("Fund profile from cache", "GET",
     "/entity/c0d5bf8c-3f43-4531-8ef6-8c8d1f0dcf5a?kind=fund", None, 20),
    ("Harvested record (Creandum)", "GET",
     "/fund/6ba00a20-2cb4-4559-8fe2-f39484a9e5f6", None, 30),
    ("Public record on a bare stub", "GET",
     f"/enrich?name={urllib.parse.quote('Andercore GmbH')}", None, 40),
]

# What each step must actually contain. A 200 that returns an error payload
# is the failure mode this catches.
def _checks(label: str, d):
    if label == "Founder screen":
        yield len(d.get("investors") or []) >= 8, "fewer than 8 investors scored"
        yield any(x.get("score") for x in d["investors"]), "every score is null"
        yield bool(d.get("fetched_at")), "no retrieval timestamp"
    elif label == "Round architect":
        yield len(d.get("syndicates") or []) >= 1, "no assemblable syndicate"
    elif label == "Outreach brief":
        yield len(d.get("sentences") or []) >= 2, "brief has under two sentences"
        yield not d.get("blocked"), "clean fund was refused a brief"
    elif label == "Conflicted fund refuses a brief":
        yield bool(d.get("blocked")), "a fund backing a competitor got a brief"
    elif label == "Insider conviction":
        yield len(d.get("companies") or []) > 50, "conviction corpus is thin"
        yield (d["companies"][0].get("months_since") or 0) < 24, "top row is stale data"
    elif label == "Contradictions":
        yield d.get("count", 0) > 0, "no contradictions found at all"
    elif label == "Backtest":
        yield d.get("samples", 0) > 100, "backtest sample too small"
    elif label == "Map":
        yield d.get("placed", 0) > 100, "almost nothing placed"
    elif label == "Near me (Helsinki)":
        yield d.get("count", 0) > 0, "nothing near Helsinki"
    elif label == "Harvested record (Creandum)":
        dep = d.get("depth") or {}
        cov = dep.get("coverage") or {}
        yield cov.get("harvested"), "the record tab would say 'not harvested yet'"
        yield cov.get("edge_types", 0) >= 5, "too few relationship kinds to be worth a tab"
        yield len(dep.get("staff") or []) >= 4, "the people this tab is for are missing"
        yield any(s.get("since") for s in dep.get("staff") or []), \
            "nobody has a start date, so the tenure signal has nothing to read"
    elif label == "Founder signal":
        yield d.get("score") is not None, "signal unreadable for the demo person"
    elif label == "Fund profile from cache":
        yield bool(d.get("name")), "profile has no name"
    elif label == "Public record on a bare stub":
        yield bool(d.get("registry") or d.get("site")), "no public record found"


def call(method, path, body, timeout):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Content-Type": "application/json"} if data else {})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return round(time.time() - t0, 1), raw


def main() -> int:
    print(f"Rehearsing {BASE}"
          f"{'  (CALA_CACHE_ONLY)' if os.getenv('CALA_CACHE_ONLY') else ''}\n")
    failures, total = [], 0.0
    for label, method, path, body, budget in STEPS:
        try:
            secs, raw = call(method, path, body, budget + 15)
        except Exception as e:
            print(f"  FAIL  {label:36s} {type(e).__name__}: {str(e)[:50]}")
            failures.append(label)
            continue
        total += secs

        problems = []
        if path != "/":
            try:
                d = json.loads(raw)
            except ValueError:
                d = None
            if isinstance(d, dict) and d.get("error"):
                problems.append(f"error payload: {str(d['error'])[:46]}")
            elif isinstance(d, dict):
                problems += [why for ok, why in _checks(label, d) if not ok]
        if secs > budget:
            problems.append(f"slow: {secs}s over a {budget}s budget")

        mark = "ok  " if not problems else "WARN"
        if problems:
            failures.append(label)
        print(f"  {mark}  {label:36s} {secs:6.1f}s"
              + ("" if not problems else "\n        " + "\n        ".join(problems)))

    print(f"\n  {len(STEPS) - len(failures)}/{len(STEPS)} clean, {total:.0f}s end to end")
    if failures:
        print("  needs attention: " + ", ".join(failures))
        return 1
    print("  demo path is clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
