"""Give every fund a real logo instead of a monogram.

77 of 664 funds in the universe had a website, so nine pages in ten rendered
a coloured square with two letters in it. A logo is not decoration here: a
list of forty funds is scanned, not read, and the mark is how a founder finds
the one they were looking for.

Three sources, cheapest first, and none of them guesses:

  1. The harvest. A fetched entity carries `website` as a sourced property.
  2. The files we already have - exhibitor profiles, portfolio places.
  3. website.discover(), which builds candidate domains from the name and
     then fetches each one, keeping it only if the company's own name is in
     the page. Guessing "andercore.com" is not evidence; reading it is.

Results accumulate into investor_domains.json, so a run that is interrupted
is not a run that is wasted.

    uv run python resolve_fund_domains.py --limit 200
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app import api, cache_index, norm, website as W

OUT = Path("investor_domains.json")

# A stem match found "coatue.com" from "Coatue Management" by matching only
# the head of the name, which is also how it could find a plumbing firm
# called Lifeline from "Lifeline Ventures". For a fund we can ask one more
# question of the page: does it say it invests in anything? A full-name match
# needs no such help.
import re
_VCISH = re.compile(
    r"venture|capital|invest|portfolio|founders?|early[- ]stage|seed|"
    r"fund|backing|we back", re.I)


def plausible_for_a_fund(d: dict) -> bool:
    if (d.get("match") or "full") == "full":
        return True
    try:
        html = W.fetch(d["domain"], timeout=6) or ""
    except Exception:                                 # noqa: BLE001
        return False
    return bool(_VCISH.search(W._clean(html)[:6000]))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--verify-pace", type=float, default=0.4,
                    help="seconds between homepage fetches")
    a = ap.parse_args()

    try:
        out = json.loads(OUT.read_text())
    except (FileNotFoundError, ValueError):
        out = {}

    universe = json.loads(Path("fund_universe.json").read_text())
    known = api._domains()
    idx = cache_index.build()
    by_name: dict[str, dict] = {}
    for e in idx.values():
        if e.get("entity_type") in ("Organization", "Company"):
            by_name.setdefault(norm.name(e.get("name") or ""), e)

    todo = []
    from_cala = 0
    for name, rec in universe.items():
        key = name.strip().lower()
        if (rec or {}).get("website") or known.get(key) or (out.get(name) or {}).get("website"):
            continue
        # 1. The harvest may already hold it.
        e = by_name.get(norm.name(name))
        props = (e or {}).get("properties") or {}
        w = props.get("website")
        w = w.get("value") if isinstance(w, dict) else w
        if w:
            out[name] = {"website": str(w), "source": "cala"}
            from_cala += 1
            continue
        todo.append(name)

    print(f"{len(universe)} funds · {from_cala} filled from the harvest · "
          f"{len(todo)} left to verify", flush=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))

    found = missed = 0
    for i, name in enumerate(todo[:a.limit], 1):
        try:
            d = W.discover(name)
        except Exception as e:                        # noqa: BLE001
            d = None
            print(f"  ! {name}: {type(e).__name__}", flush=True)
        if d and d.get("domain") and plausible_for_a_fund(d):
            out[name] = {"website": d["domain"],
                         "source": f"verified ({d.get('match', 'full')})",
                         "title": (d.get("title") or "")[:120]}
            found += 1
        elif d and d.get("domain"):
            out[name] = {"website": None,
                         "source": f"rejected {d['domain']}: reads as a "
                                   f"namesake, not an investor"}
            missed += 1
        else:
            # Record the miss so the next run does not retry it from scratch.
            out[name] = {"website": None, "source": "no verified match"}
            missed += 1
        if i % 10 == 0:
            OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
            print(f"  {i}/{min(len(todo), a.limit)}  found {found}  missed {missed}",
                  flush=True)
        time.sleep(a.verify_pace)

    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    total = sum(1 for v in out.values() if v.get("website"))
    print(f"\n{found} verified this run, {missed} with no verified match.")
    print(f"investor_domains.json now holds {total} domains.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
