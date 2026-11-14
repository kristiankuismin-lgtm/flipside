"""Put the harvest budget where the product actually looks.

A full walk of the graph takes longer than we have, so the order matters more
than the ambition. The spine of the product is a founder's call list: the funds
we rank, the people at those funds, and the companies those funds backed. Those
go first; the long tail goes last and may not go at all.

    uv run python harvest_seeds.py > seeds.txt
"""
from __future__ import annotations

import json
import sys

from app import api, cache_index, norm


def main() -> int:
    idx = cache_index.build()
    by_name: dict[str, list[str]] = {}
    for eid, e in idx.items():
        by_name.setdefault(norm.name(e.get("name") or ""), []).append(eid)

    tiers: list[tuple[str, list[str]]] = []
    seen: set[str] = set()

    def tier(label: str, ids) -> None:
        # Dedupe within the tier as well as against earlier ones: the one-hop
        # tier reads the same entity off several funds' edges, and a count
        # that disagrees with the file it describes is not worth printing.
        fresh = []
        for i in ids:
            if i and i not in seen:
                seen.add(i)
                fresh.append(i)
        tiers.append((label, fresh))

    # 1. The funds we rank.
    funds = [i for n in api._investor_pool() for i in by_name.get(norm.name(n), [])]
    tier("funds we rank", funds)

    # 2. The portfolio companies of the funds we rank. Their own records
    # carry HAS_HEADQUARTERS_IN and OPERATES_IN_INDUSTRY, which is what the
    # sector and geography donuts on a fund profile are counted from - and
    # with none of them read, those two charts can only say so.
    port = []
    for fid in funds:
        block = (idx.get(fid, {}).get("relationships") or {})
        for d in ("outgoing", "incoming"):
            for x in ((block.get(d) or {}).get("INVESTED_IN") or []):
                if isinstance(x, dict) and x.get("id"):
                    port.append(x["id"])
    tier("portfolio of the funds we rank", port)

    # 3. Funding rounds, for their amounts.
    #
    # The product has been telling people that pre-emption detection is
    # starved because only 58 of 837 round records carry an amount. That
    # measured our own requests: those records are stubs picked up off a
    # PARTICIPATES_IN_CORPORATE_EVENT edge, and an edge does not carry the
    # far entity's properties. Ten rounds fetched in full came back ten for
    # ten with transaction_value and its currency.
    tier("funding rounds, for their amounts",
         [k for k, v in idx.items()
          if v.get("entity_type") == "PrivateCompanyFundingRound"])

    # 3. Every person we hold: a person is a contact, and contacts are the point.
    tier("people", [k for k, v in idx.items() if v.get("entity_type") == "Person"])

    # 5. Whoever else those funds are connected to. Harvested funds carry
    # hundreds of edges each, so this tier is thousands wide and has to come
    # after the narrow tiers or it swallows them.
    near: list[str] = []
    for fid in funds:
        for block in (idx.get(fid, {}).get("relationships") or {}).values():
            if isinstance(block, dict):
                for items in block.values():
                    near += [x.get("id") for x in (items or []) if isinstance(x, dict)]
    tier("one hop from those funds", near)

    # 5. Companies that appear in rounds - the evidence behind a ranking.
    rounds = api._rounds_by_company()
    tier("companies in rounds",
         [i for n in rounds for i in by_name.get(norm.name(n), [])])

    # 6. The rest, organisations before companies.
    for t in ("Organization", "GovernmentalInstitution", "NonprofitOrganization",
              "ResearchInstitution", "Company", "PrivateCompanyFundingRound"):
        tier(f"remaining {t}", [k for k, v in idx.items() if v.get("entity_type") == t])

    for label, ids in tiers:
        print(f"# {len(ids):5d}  {label}", file=sys.stderr)
    print(f"# {len(seen):5d}  total", file=sys.stderr)
    for _, ids in tiers:
        for i in ids:
            print(i)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
