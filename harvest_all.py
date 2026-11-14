"""Harvest everything Cala will give us, one entity at a time.

The rule the rest of this codebase follows - introspect, never guess - has so
far been applied one relationship at a time: we asked for the edges a feature
needed. That leaves the graph half-read. An entity knows its own schema, so
the complete read is two calls:

    GET  /entities/{id}/introspection   -> every property, every edge, both ways
    POST /entities/{id}                 -> ask for all of them at once

Everything lands in the same response cache the app already reads through
cache_index, which prefers the richest payload it holds for an id. So a
harvested entity silently upgrades every page that mentions it, and nothing
downstream has to change.

Neighbours come back with ids and types, which makes this a frontier walk:
seeds are what we already know, and the graph tells us what else exists.

    uv run python harvest_all.py --max 400
    uv run python harvest_all.py --max 2000 --types Person,Organization
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import threading
import time
from collections import Counter, deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

from app import cala_client as cala, cache_index

DB = "cache.sqlite"
TTL = 30 * 86400
PAGE = 200

# Which types are worth a round trip, best first. A Country or an Industry is
# a label we already have from the edge itself; spending a call on it buys
# nothing. Everything not listed is recorded as discovered and left unvisited.
WORTH_VISITING = [
    "Person",
    "Organization",
    "Company",
    "PrivateCompanyFundingRound",
    "FundingRound",
    "CorporateEvent",
    # Four organisation-ish types our fund search has always been blind to:
    # a public funder typed GovernmentalInstitution returned nothing, silently.
    "GovernmentalInstitution",
    "NonprofitOrganization",
    "IntergovernmentalOrganization",
    "ResearchInstitution",
    "EducationalInstitution",
    "Event",
]
RANK = {t: i for i, t in enumerate(WORTH_VISITING)}


# How many entities of a type to introspect before trusting its vocabulary.
# Introspection is per entity, so the only way to know a type's full schema is
# to ask a few of them and take the union. After that the harvest is one call
# per entity instead of two, which doubles the reach of a fixed budget.
SAMPLE = 8


def _db():
    # Workers learn the vocabulary as they go, so this connection is written
    # from several threads. Every write goes through a lock; sqlite's own
    # thread check would otherwise reject them one entity at a time, which is
    # how eleven entities went missing before anyone looked at the error column.
    con = sqlite3.connect(DB, check_same_thread=False)
    con.execute("PRAGMA busy_timeout=20000")
    con.execute("""CREATE TABLE IF NOT EXISTS harvest (
        id TEXT PRIMARY KEY, name TEXT, entity_type TEXT, ts REAL,
        props INT, edges INT, rels TEXT, numeric TEXT, err TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS harvest_vocab (
        entity_type TEXT PRIMARY KEY, seen INT, props TEXT,
        outgoing TEXT, incoming TEXT)""")
    con.commit()
    return con


class Vocab:
    """What each entity type is known to carry, learned and then reused."""

    def __init__(self, con):
        self.con = con
        self.v: dict[str, dict] = {}
        self.lock = threading.Lock()
        for t, seen, pr, out, inc in con.execute(
                "SELECT entity_type, seen, props, outgoing, incoming FROM harvest_vocab"):
            self.v[t] = {"seen": seen, "props": set(json.loads(pr)),
                         "out": set(json.loads(out)), "in": set(json.loads(inc))}

    def known(self, t) -> dict | None:
        with self.lock:
            e = self.v.get(t)
            return dict(e) if e and e["seen"] >= SAMPLE else None

    def learn(self, t, props, out, inc) -> None:
        with self.lock:
            e = self.v.setdefault(t, {"seen": 0, "props": set(), "out": set(), "in": set()})
            e["seen"] += 1
            e["props"] |= set(props or [])
            e["out"] |= set(out or [])
            e["in"] |= set(inc or [])
            self.con.execute("REPLACE INTO harvest_vocab VALUES (?,?,?,?,?)",
                             (t, e["seen"], json.dumps(sorted(e["props"])),
                              json.dumps(sorted(e["out"])), json.dumps(sorted(e["in"]))))
            self.con.commit()

    def report(self) -> str:
        with self.lock:
            return "\n".join(
                f"  {t:32} {e['seen']:4d} seen  {len(e['props']):3d} props  "
                f"{len(e['out'])} out / {len(e['in'])} in"
                for t, e in sorted(self.v.items()))


def done_ids(con) -> set[str]:
    return {r[0] for r in con.execute("SELECT id FROM harvest WHERE err IS NULL")}


def harvest_one(eid: str, etype: str, vocab) -> dict:
    """Ask for everything this kind of entity is known to carry.

    Asking for a relationship an entity does not have is not an error - it
    comes back empty - so once a type's vocabulary is known the introspection
    call can be skipped entirely.
    """
    known = vocab.known(etype)
    if known is None:
        i = cala.introspect(eid, ttl=TTL) or {}
        rel = i.get("relationships") or {}
        props = i.get("properties") or []
        out_rels = list(rel.get("outgoing") or [])
        in_rels = list(rel.get("incoming") or [])
        vocab.learn(etype, props, out_rels, in_rels)
    else:
        props = sorted(known["props"])
        out_rels = sorted(known["out"])
        in_rels = sorted(known["in"])
    return cala.get_entity(eid, properties=props or None,
                           incoming=in_rels or None, outgoing=out_rels or None,
                           limit=PAGE, ttl=TTL) or {}


def neighbours(e: dict):
    """(id, type, name) for every entity on the far end of an edge."""
    for block in (e.get("relationships") or {}).values():
        if not isinstance(block, dict):
            continue
        for items in block.values():
            for it in (items or []):
                if isinstance(it, dict) and it.get("id") and it.get("entity_type"):
                    yield it["id"], it["entity_type"], it.get("name")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=300, help="entities to visit")
    ap.add_argument("--types", default="", help="restrict visits to these types")
    ap.add_argument("--seeds", default="", help="file of entity ids, one per line")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    only = {t.strip() for t in a.types.split(",") if t.strip()}
    con = _db()
    vocab = Vocab(con)
    seen = done_ids(con)

    # Seeds: everything we already hold, best types first, so a short run
    # spends its calls on people and firms rather than on country labels.
    idx = cache_index.build(DB)
    if a.seeds:
        # A seed file is an explicit priority order - the product's own spine
        # first - so it must not be re-sorted by type.
        order = [ln.strip() for ln in open(a.seeds) if ln.strip()]
        frontier = deque((i, (idx.get(i) or {}).get("entity_type"),
                          (idx.get(i) or {}).get("name")) for i in order)
    else:
        pool = sorted((RANK.get(v.get("entity_type"), 99), k, v.get("entity_type"),
                       v.get("name")) for k, v in idx.items())
        frontier = deque((k, t, n) for _, k, t, n in pool)
    queued = {x[0] for x in frontier}

    stats = Counter()
    found_rels = Counter()
    numeric_hits = []
    visited = 0
    t0 = time.time()
    pool_ex = ThreadPoolExecutor(max_workers=a.workers)
    stop = False

    def record(eid, name, etype, e=None, err=None):
        num = (e or {}).get("numerical_observations") or {}
        rel = (e or {}).get("relationships") or {}
        names = sorted({f"{d}:{r}" for d, b in rel.items() if isinstance(b, dict)
                        for r in b})
        con.execute("REPLACE INTO harvest VALUES (?,?,?,?,?,?,?,?,?)",
                    (eid, (e or {}).get("name") or name,
                     (e or {}).get("entity_type") or etype, time.time(),
                     len((e or {}).get("properties") or {}),
                     sum(1 for _ in neighbours(e or {})),
                     json.dumps(names), json.dumps(list(num))[:400], err))
        con.commit()

    def take(n):
        """Pull the next n unvisited entities off the frontier."""
        batch = []
        while frontier and len(batch) < n:
            eid, etype, name = frontier.popleft()
            if eid in seen:
                continue
            if etype not in RANK or (only and etype not in only):
                stats["skip:" + str(etype)] += 1
                continue
            seen.add(eid)
            batch.append((eid, etype, name))
        return batch

    # A rolling pool, not batches. Entity fetches range from 2s to 60s, so
    # waiting for a whole batch means every round trip costs the slowest one;
    # keeping the pool topped up is the difference between 16s and 2s each.
    inflight: dict = {}

    def top_up():
        for eid, etype, name in take(a.workers - len(inflight)):
            inflight[pool_ex.submit(harvest_one, eid, etype, vocab)] = (eid, etype, name)

    top_up()
    while inflight and not stop and visited < a.max:
        done, _ = wait(list(inflight), return_when=FIRST_COMPLETED)
        for fut in done:
            eid, etype, name = inflight.pop(fut)
            try:
                e = fut.result()
            except cala.CalaError as ex:
                stats["error"] += 1
                if ex.status == 429:
                    # Transient: the entity is fine, we were simply too fast.
                    # Putting it back is the difference between a gap in the
                    # graph and a slower run.
                    seen.discard(eid)
                    frontier.appendleft((eid, etype, name))
                    stats["requeued"] += 1
                    continue
                record(eid, name, etype, err=f"{ex.status}: {ex}")
                if ex.status == 402:
                    print("! credits exhausted - stopping", file=sys.stderr)
                    stop = True
                continue
            except Exception as ex:                   # noqa: BLE001
                stats["error"] += 1
                record(eid, name, etype, err=str(ex)[:200])
                continue

            rel = e.get("relationships") or {}
            for r in sorted({f"{d}:{r}" for d, b in rel.items()
                             if isinstance(b, dict) for r in b}):
                found_rels[r] += 1
            for d, t, n in neighbours(e):
                stats["neighbour:" + t] += 1
                if d not in queued and d not in seen:
                    queued.add(d)
                    frontier.append((d, t, n))
            num = e.get("numerical_observations") or {}
            if num:
                numeric_hits.append((name, etype, list(num)[:6]))
            record(eid, name, etype, e=e)
            visited += 1
            stats["visited:" + (e.get("entity_type") or etype)] += 1
            if not a.quiet and visited % 20 == 0:
                rate = visited / max(0.1, time.time() - t0)
                print(f"  {visited}/{a.max}  {rate:.2f}/s  frontier={len(frontier)}  "
                      f"requeued={stats['requeued']}  err={stats['error']}", flush=True)
        if not stop and visited < a.max:
            top_up()

    pool_ex.shutdown(wait=False)
    print("\nvocabulary learned per entity type:")
    print(vocab.report())
    print(f"\nvisited {visited} in {time.time()-t0:.0f}s, frontier left {len(frontier)}")
    print("\nrelationships actually seen:")
    for r, c in found_rels.most_common():
        print(f"  {c:5d}  {r}")
    print("\nneighbour types discovered:")
    for k, c in stats.most_common():
        if k.startswith("neighbour:"):
            print(f"  {c:6d}  {k.split(':',1)[1]}")
    if numeric_hits:
        print("\nnumerical_observations found on:")
        for n, t, keys in numeric_hits[:20]:
            print(f"  {n} ({t}): {keys}")
    else:
        print("\nnumerical_observations: none on any entity visited")
    print(f"\nerrors: {stats['error']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
