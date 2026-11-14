"""Score Slush exhibitors for insider conviction, straight from the graph.

The query endpoint takes ~45s per company. The Entities API answers in ~0.3s,
so this walks the graph instead:

    company -> PARTICIPATES_IN_CORPORATE_EVENT -> PrivateCompanyFundingRound
    round   -> PARTICIPATES_IN_FUNDING_ROUND   -> investors (with is_lead)

Paced and resumable: Cala's quota is a budget over time, so a single pass
rarely finishes and reruns must accumulate rather than restart.
"""
import json, sys, time
from datetime import date

from app import cala_client as cala, conviction as K, graph, norm
from app.models import Round

PACE = float(sys.argv[2]) if len(sys.argv) > 2 else 0.5
LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 150
STATE = "exhibitor_rounds.json"


def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def company_rounds(eid):
    """[(round_id, label)] for the funding rounds this company issued."""
    e = cala.get_entity(eid, properties=["name"],
                        outgoing=["PARTICIPATES_IN_CORPORATE_EVENT"], limit=25,
                        allow_live=True, ttl=7 * 86400)
    out = []
    for it in graph.rels(e, "outgoing", "PARTICIPATES_IN_CORPORATE_EVENT"):
        if "funding" in str(it.get("entity_type", "")).lower() \
           and str((it.get("properties") or {}).get("role", "")).upper() == "ISSUER":
            out.append(it["id"])
    return out


def round_detail(rid, company):
    e = cala.get_entity(rid, properties=graph.ROUND_PROPS,
                        incoming=["PARTICIPATES_IN_FUNDING_ROUND"], limit=40,
                        allow_live=True, ttl=7 * 86400)
    parts = graph.rels(e, "incoming", "PARTICIPATES_IN_FUNDING_ROUND")
    invs, leads = [], []
    for p in parts:
        role = str((p.get("properties") or {}).get("role", "")).upper()
        if role == "ISSUER":
            continue
        nm = p.get("name")
        if not nm:
            continue
        invs.append(nm)
        if graph._is_lead(p.get("properties") or {}):
            leads.append(nm)
    d = graph._as_date(graph.prop(e, "event_date")[0]) or \
        graph._as_date(graph.prop(e, "announcement_date")[0])
    if not d:
        return None
    label, _ = graph.prop(e, "round_label")
    amt, _ = graph.prop(e, "transaction_value")
    return Round(company=company, date=d, stage=str(label or ""),
                 amount_eur=float(amt) if isinstance(amt, (int, float)) else None,
                 investors=invs, leads=leads, lead_is_native=True, sources=[])


def main():
    profs = [p for p in json.load(open("slush_profiles.json")) if not p.get("error")]
    try:
        state = json.load(open(STATE))
    except (FileNotFoundError, ValueError):
        state = {}

    todo = [p for p in profs if p["id"] not in state][:LIMIT]
    log(f"{len(state)} already walked, trying {len(todo)} more")

    done = fails = 0
    backoff = 60.0
    for i, p in enumerate(todo, 1):
        try:
            rids = company_rounds(p["id"])
            time.sleep(PACE)
            rounds = []
            for rid in rids[:8]:
                r = round_detail(rid, p["name"])
                time.sleep(PACE)
                if r:
                    rounds.append(r)
            backoff = 60.0        # a success means the budget refilled
            state[p["id"]] = {"name": p["name"],
                              "rounds": [{"stage": r.stage, "date": str(r.date),
                                          "amount": r.amount_eur,
                                          "investors": r.investors, "leads": r.leads}
                                         for r in sorted(rounds, key=lambda x: x.date)]}
            done += 1
            if len(rounds) >= 2:
                log(f"{i}/{len(todo)} {p['name'][:30]}: {len(rounds)} rounds")
        except cala.CalaError as e:
            fails += 1
            if "Rate limit" in str(e):
                # The quota is a budget over time, so waiting is the fix, not
                # stopping. Save what we have and sleep it off.
                json.dump(state, open(STATE, "w"))
                log(f"{i}/{len(todo)} quota wall — sleeping {backoff:.0f}s "
                    f"(walked {len(state)} so far)")
                time.sleep(backoff)
                backoff = min(backoff * 1.4, 600)
                continue
            if fails % 10 == 1:
                log(f"{i}/{len(todo)} {p['name'][:26]}: {str(e)[:50]}")
        except Exception as e:
            fails += 1
            if fails % 10 == 1:
                log(f"{i}/{len(todo)} {p['name'][:26]}: {type(e).__name__}")
        if i % 25 == 0:
            json.dump(state, open(STATE, "w"))
            log(f"{i}/{len(todo)} walked={done} failed={fails}")

    json.dump(state, open(STATE, "w"))
    multi = sum(1 for v in state.values() if len(v["rounds"]) >= 2)
    log(f"DONE walked={len(state)} with 2+ rounds={multi} failures={fails}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
