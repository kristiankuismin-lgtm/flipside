"""Ask Cala for the websites and whereabouts of funds we cannot guess.

Guessing reaches a domain that is built out of the name. It cannot reach
a16z.com from "Andreessen Horowitz" or bvp.com from "Bessemer Venture
Partners", and no amount of candidate shapes will - those are not spellings
of the name, they are nicknames.

Cala holds `website` as a sourced property on the entity, and the same call
can carry the addresses and the country edges - so a fund that has no street
address anywhere can still be placed on the map by country, honestly
labelled as country-only rather than pretended to be precise.

The firms' own sites were tried for this first and do not carry it: a16z.com,
icebreaker.vc and nordicmakers.vc are JS-rendered and their HTML contains no
city at all.

Everything lands in investor_domains.json beside the guessed ones, labelled
by where it came from.

    uv run python resolve_fund_websites.py --limit 200
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app import api, cala_client as cala, depth as D, graph

OUT = Path("investor_domains.json")
# Entries in fund_universe that are not funds. They come from round records
# where the investor was not named, and no lookup will ever resolve them.
JUNK = {"not publicly disclosed", "undisclosed", "n/a", "unknown",
        "not disclosed", "private investors", "angel investors", "others"}


LOC_PROPS = ["website", "name", "headquarters_address", "registered_address",
             "description"]
LOC_OUT = ["HAS_HEADQUARTERS_IN", "HAS_PRESENCE_IN"]


def _website_of(e: dict) -> str | None:
    props = (e or {}).get("properties") or {}
    v = props.get("website")
    v = v.get("value") if isinstance(v, dict) else v
    return str(v).strip() if v else None


def _where_of(e: dict) -> dict:
    """Whatever this entity says about where it is, strongest first."""
    if not e:
        return {}
    facts = {f["key"]: f["value"] for f in D.facts(e)}
    out: dict = {}
    addr = facts.get("headquarters_address") or facts.get("registered_address")
    if addr:
        out["hq"] = str(addr)
        out["hq_source"] = "cala"
    else:
        pres = D.presence(e)
        hq = [p["name"] for p in pres if p["kind"] == "headquarters"]
        any_ = [p["name"] for p in pres]
        if hq or any_:
            # A country is not an address. It is still the difference between
            # a fund on the map and a fund that looks uncovered, so it is
            # used and said out loud rather than dressed up as a street.
            out["hq"] = (hq or any_)[0]
            out["hq_source"] = "cala country"
            out["hq_precision"] = "country"
    if e.get("description"):
        out.setdefault("description", e["description"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--live", action="store_true",
                    help="also resolve funds we hold no entity for")
    a = ap.parse_args()

    try:
        out = json.loads(OUT.read_text())
    except (FileNotFoundError, ValueError):
        out = {}
    universe = json.loads(Path("fund_universe.json").read_text())
    known = api._domains()

    todo, skipped_junk = [], 0
    for name in universe:
        if name.strip().lower() in JUNK:
            out[name] = {"website": None, "source": "not a fund"}
            skipped_junk += 1
            continue
        if known.get(name.strip().lower()) or (out.get(name) or {}).get("website"):
            continue
        todo.append(name)

    # Funds we already hold an entity for cost one call and usually answer;
    # the rest cost two and usually do not. Order by that, so a run cut short
    # by the rate limit is cut short at the cheap end.
    todo.sort(key=lambda n: D.entity(n, types=("Organization", "Company")) is None)
    have = sum(1 for n in todo
               if D.entity(n, types=("Organization", "Company")) is not None)
    print(f"{len(todo)} funds with no domain · {have} of them already have a "
          f"Cala entity · {skipped_junk} entries that are not funds at all",
          flush=True)

    from_cache = found = missed = placed = 0
    for i, name in enumerate(todo[:a.limit], 1):
        e = D.entity(name, types=("Organization", "Company"))
        w = _website_of(e) if e else None
        src = "cala (cached)"

        if not w and e and not e.get("relationships"):
            # We hold a stub. One fetch for one property is cheap and is the
            # whole reason this script exists.
            try:
                full = cala.get_entity(e["id"], properties=LOC_PROPS,
                                       outgoing=LOC_OUT, limit=20,
                                       allow_live=True, ttl=30 * 86400,
                                       timeout=25, retries=2)
                w, src, e = _website_of(full), "cala", full
            except cala.CalaError as ex:
                if ex.status == 402:
                    print("! credits exhausted - stopping", flush=True)
                    break
            except Exception:                         # noqa: BLE001
                pass

        if not w and a.live and not e:
            try:
                hit = graph.find_investor(name, allow_live=True, ttl=30 * 86400,
                                          interactive=False, timeout=25, retries=2)
            except Exception:                         # noqa: BLE001
                hit = None
            if hit:
                try:
                    full = cala.get_entity(hit["id"], properties=LOC_PROPS,
                                           outgoing=LOC_OUT, limit=20,
                                           allow_live=True, ttl=30 * 86400,
                                           timeout=25, retries=2)
                    w, src, e = _website_of(full), "cala", full
                except Exception:                     # noqa: BLE001
                    pass

        where = _where_of(e)
        if where.get("hq"):
            placed += 1
        if w:
            out[name] = {**where, "website": w, "source": src}
            found += 1
            if src == "cala (cached)":
                from_cache += 1
        else:
            prev = (out.get(name) or {}).get("source")
            out[name] = {**where, "website": None,
                         "source": prev if prev and "verified" not in str(prev)
                                   else "no website in Cala either"}
            missed += 1
        if i % 10 == 0:
            OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
            print(f"  {i}/{min(len(todo), a.limit)}  websites {found} "
                  f"({from_cache} cached)  placed {placed}  missed {missed}",
                  flush=True)

    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    total = sum(1 for v in out.values() if v.get("website"))
    print(f"\n{found} websites from Cala, {missed} with none. "
          f"{placed} funds got a location.")
    print(f"investor_domains.json now holds {total} domains.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
