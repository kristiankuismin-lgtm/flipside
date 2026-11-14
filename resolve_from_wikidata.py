"""Fill the last gaps from the open encyclopaedia, with no Cala credits.

Two numbers this closes on:

  231 funds with no logo, because their domain is not a spelling of their
      name - a16z.com, bvp.com, project-a.com.
  231 funds with no address anywhere, so they are absent from the map and
      that absence reads as "not covered".

Wikidata has both, maintained by the firms themselves, under CC0 and behind
a keyless public API. It is also the only source left: Cala returns 402.

    uv run python resolve_from_wikidata.py --limit 250
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app import api, wikidata as WD

OUT = Path("investor_domains.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--pace", type=float, default=0.7,
                    help="seconds between lookups; Wikidata asks for politeness")
    a = ap.parse_args()

    try:
        out = json.loads(OUT.read_text())
    except (FileNotFoundError, ValueError):
        out = {}
    universe = json.loads(Path("fund_universe.json").read_text())
    known = api._domains()

    todo = []
    for name, rec in universe.items():
        have_site = (rec or {}).get("website") or known.get(name.strip().lower()) \
            or (out.get(name) or {}).get("website")
        have_hq = (rec or {}).get("hq") or (out.get(name) or {}).get("hq")
        if have_site and have_hq:
            continue
        if (out.get(name) or {}).get("source") == "not a fund":
            continue
        todo.append((name, bool(have_site), bool(have_hq)))

    print(f"{len(todo)} funds missing a website, an address, or both", flush=True)

    sites = places = miss = 0
    for i, (name, have_site, have_hq) in enumerate(todo[:a.limit], 1):
        r = WD.lookup(name)
        if not r:
            miss += 1
        else:
            rec = dict(out.get(name) or {})
            if r.get("website") and not have_site:
                rec["website"] = r["website"]
                rec["source"] = "wikidata"
                sites += 1
            if r.get("hq") and not have_hq:
                rec["hq"] = r["hq"]
                rec["hq_source"] = "wikidata"
                # A city name is not a street. The map draws it as a city
                # pin and says so rather than implying an office door.
                rec["hq_precision"] = "city"
                places += 1
            if r.get("founded"):
                rec.setdefault("founded", r["founded"])
            rec.setdefault("wikidata", r["qid"])
            if rec:
                out[name] = rec
        if i % 10 == 0:
            OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
            print(f"  {i}/{min(len(todo), a.limit)}  websites {sites}  "
                  f"addresses {places}  not established {miss}", flush=True)
        time.sleep(a.pace)

    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    total_site = sum(1 for v in out.values() if v.get("website"))
    total_hq = sum(1 for v in out.values() if v.get("hq"))
    print(f"\n{sites} websites and {places} addresses from Wikidata; "
          f"{miss} names it could not establish as a firm.")
    print(f"investor_domains.json now holds {total_site} domains, {total_hq} addresses.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
