"""Build the fund universe from the rounds we already hold.

investors.txt was thirty names typed by hand. The cached rounds name 2,010
distinct investors - every firm that appears on any round of any company we
have fetched. That is the real universe, and it costs nothing to enumerate.

This resolves them into Cala entities and addresses, most-seen first, so the
map fills with the funds that actually show up in this ecosystem rather than
the ones someone remembered.

Public registers are tried before Cala for the address, because they are free.
"""
import json, os, sys, time
from collections import Counter

os.environ.setdefault("CALA_CACHE_ONLY", "1")

from app import cala_client as cala, datasets as D, geo, geocode, graph, norm
from app.cala_client import CalaError

STATE = "fund_universe.json"
MIN_SEEN = int(os.getenv("FUND_MIN_SEEN", "2"))


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def candidates() -> list[tuple[str, int]]:
    """Investor names seen on cached rounds, by how often they appear."""
    seen, best = Counter(), {}
    def add(name):
        n = (name or "").strip()
        k = norm.name(n)
        if len(k) < 3:
            return
        seen[k] += 1
        # keep the longest spelling - "Index Ventures" over "Index"
        if len(n) > len(best.get(k, "")):
            best[k] = n

    for path, rows in (("conviction.json", lambda d: d["companies"]),
                       ("exhibitor_rounds.json", lambda d: list(d.values()))):
        try:
            d = json.load(open(path))
        except (FileNotFoundError, ValueError):
            continue
        for c in rows(d):
            for r in c.get("rounds") or []:
                for inv in r.get("investors") or []:
                    add(inv)
    try:
        for i in json.load(open("competitor_investors.json"))["investors"]:
            add(i["name"])
    except (FileNotFoundError, ValueError, KeyError):
        pass

    out = [(best[k], n) for k, n in seen.items() if n >= MIN_SEEN and k in best]
    out.sort(key=lambda kv: -kv[1])
    return out


def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    pace = float(sys.argv[2]) if len(sys.argv) > 2 else 1.5

    cands = candidates()
    try:
        state = json.load(open(STATE))
    except (FileNotFoundError, ValueError):
        state = {}

    todo = [(n, c) for n, c in cands if n not in state][:limit]
    log(f"{len(cands)} candidates seen {MIN_SEEN}+ times, {len(state)} done, "
        f"trying {len(todo)}")

    cala.CACHE_ONLY = False
    backoff, placed = 45.0, 0

    for i, (name, count) in enumerate(todo, 1):
        rec = {"seen": count}
        hq = src = None

        g = D.gleif(name)
        if g and g.get("address"):
            hq, src = g["address"], "GLEIF"
            rec["lei"] = g["lei"]

        try:
            e = graph.find_investor(name, interactive=False, retries=3, timeout=45)
            if e:
                rec["id"] = e["id"]
                rec["entity_type"] = e.get("entity_type")
                rec["description"] = (e.get("description") or "")[:240]
                if not hq:
                    props = graph.pick_props(e["id"], ["name", "description",
                                                       "founding_date", "employee_count"]
                                             + graph.ADDRESS_PROPS + graph.SITE_PROPS,
                                             allow_live=True, ttl=7 * 86400) or ["name"]
                    full = cala.get_entity(e["id"], properties=props,
                                           allow_live=True, ttl=7 * 86400)
                    hq, _, key = graph.first_prop(full, graph.ADDRESS_PROPS)
                    web, _, _ = graph.first_prop(full, graph.SITE_PROPS)
                    rec["website"] = web
                    rec["founded"] = graph.prop(full, "founding_date")[0]
                    rec["employees"] = graph.prop(full, "employee_count")[0]
                    src = f"Cala.{key}" if hq else None
            backoff = 45.0
        except CalaError as ex:
            if "Rate limit" in str(ex):
                json.dump(state, open(STATE, "w"))
                log(f"{i}/{len(todo)} quota wall — sleeping {backoff:.0f}s ({len(state)} done)")
                time.sleep(backoff)
                backoff = min(backoff * 1.4, 480)
                continue
        except Exception:
            pass

        rec["hq"], rec["source"] = hq, src
        if hq:
            fine = geocode.lookup(hq)
            loc = geo.locate(hq)
            if fine:
                rec.update(lat=fine["lat"], lon=fine["lon"], precise=True,
                           cc=(loc or (0, 0, "??"))[2]); placed += 1
            elif loc:
                rec.update(lat=loc[0], lon=loc[1], precise=False, cc=loc[2]); placed += 1
        state[name] = rec
        time.sleep(pace)
        if i % 20 == 0:
            json.dump(state, open(STATE, "w"))
            log(f"{i}/{len(todo)} placed={placed}")

    json.dump(state, open(STATE, "w"))
    total = sum(1 for v in state.values() if v.get("lat"))
    log(f"DONE {len(state)} resolved, {total} on the map")
    return 0


if __name__ == "__main__":
    sys.exit(main())
