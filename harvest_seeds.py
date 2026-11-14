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
        fresh = [i for i in ids if i and i not in seen]
        seen.update(fresh)
        tiers.append((label, fresh))

    # 1. The funds we rank.
    funds = [i for n in api._investor_pool() for i in by_name.get(norm.name(n), [])]
    tier("funds we rank", funds)

    # 2. Whoever those funds are connected to - the people are the call list.
    near: list[str] = []
    for fid in funds:
        for block in (idx.get(fid, {}).get("relationships") or {}).values():
            if isinstance(block, dict):
                for items in block.values():
                    near += [x.get("id") for x in (items or []) if isinstance(x, dict)]
    tier("one hop from those funds", near)

    # 3. Every person we hold: a person is a contact, and contacts are the point.
    tier("people", [k for k, v in idx.items() if v.get("entity_type") == "Person"])

    # 4. Companies that appear in rounds - the evidence behind a ranking.
    rounds = api._rounds_by_company()
    tier("companies in rounds",
         [i for n in rounds for i in by_name.get(norm.name(n), [])])

    # 5. The rest, organisations before companies.
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
