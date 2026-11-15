"""Who the graph says has left, and has not turned up anywhere since.

The moves detector reads start dates: somebody joined a company, somebody
founded one. It finds almost nothing, because a founding is recorded after
it happens and by then the news has it too.

The graph also records the other end. 813 relationship edges carry a
valid_until, and nothing in this product read it. An ended seat with no
later start is a person who is, on the record, unaccounted for - and that
is the earliest signal there is, because the gap comes before the company.

What makes one of these worth a call, in order:

  what they left     A chief executive leaving is not a board seat
                     lapsing, and somebody stepping out of a company they
                     founded themselves is a different event again.
  how long ago       A gap of a few months is interesting. Three years of
                     it means they retired, took a job nobody recorded, or
                     the record is wrong.
  nothing since      The whole premise. One later start and they are
                     employed, not deciding.

Dates in the future are kept rather than filtered. An announced departure
that has not happened yet is the earliest version of this signal, and the
row says which it is instead of implying they have already gone.
"""
from __future__ import annotations

from datetime import date, datetime

# A seat, roughly in the order that leaving it says something.
WEIGHT = {
    "FOUNDED": 1.0,            # left something they started
    "IS_CEO_OF": 0.95,
    "IS_EXECUTIVE_OF": 0.8,
    "WORKS_AT": 0.65,
    "IS_BOARD_MEMBER_OF": 0.4,
    "IS_MEMBER_OF": 0.3,
}
SEAT_EDGES = tuple(WEIGHT)

W_SEAT = 46                    # what they left
W_FRESH = 34                   # how recently
W_SENIOR = 12                  # how senior the record says they were
FRESH_MONTHS = 30              # beyond this the gap stops being news


def _val(v):
    return v.get("value") if isinstance(v, dict) else v


def _day(v) -> date | None:
    s = str(_val(v) or "")[:10]
    if len(s) != 10:
        return None
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def seats(person: dict) -> tuple[list[dict], list[dict]]:
    """(every seat with a start, every seat with an end)."""
    started, ended = [], []
    rel = person.get("relationships") or {}
    for d in ("incoming", "outgoing"):
        for kind, items in (rel.get(d) or {}).items():
            if kind not in WEIGHT:
                continue
            for x in items or []:
                if not isinstance(x, dict):
                    continue
                pr = x.get("properties") or {}
                nm = (x.get("name") or "").strip()
                if not nm:
                    continue
                row = {"kind": kind, "company": nm, "company_id": x.get("id"),
                       "role": _val(pr.get("role")) or _val(pr.get("capacity"))}
                s, u = _day(pr.get("valid_since")), _day(pr.get("valid_until"))
                if s:
                    started.append({**row, "on": s})
                if u:
                    ended.append({**row, "on": u})
    return started, ended


def score(row: dict, *, today: date) -> tuple[float, list[str]]:
    why, pts = [], 0.0
    w = WEIGHT.get(row["kind"], 0.3)
    pts += W_SEAT * w
    verb = "stepped out of the company they founded" if row["kind"] == "FOUNDED" \
        else "left as chief executive" if row["kind"] == "IS_CEO_OF" \
        else "left an executive seat at" if row["kind"] == "IS_EXECUTIVE_OF" \
        else "left a board seat at" if row["kind"] == "IS_BOARD_MEMBER_OF" \
        else "left"
    why.append(f"{verb} {row['company']}" if row["kind"] != "FOUNDED"
               else f"{verb}, {row['company']}")

    months = (today - row["on"]).days / 30.44
    if months < 0:
        # Announced but not yet effective. The earliest the signal can exist.
        pts += W_FRESH
        why.append(f"leaving on {row['on'].isoformat()}, announced already")
    else:
        pts += W_FRESH * max(0.0, 1 - months / FRESH_MONTHS)
        why.append(f"{int(months)} month{'s' if int(months) != 1 else ''} ago"
                   if months >= 1 else "this month")

    if row.get("role"):
        pts += W_SENIOR * 0.5
        why.append(str(row["role"]).replace("_", " ").lower())
    return round(min(100.0, pts), 1), why


def find(index: dict, *, today: date | None = None, limit: int = 30,
         months: int = FRESH_MONTHS) -> dict:
    """People with an ended seat and nothing recorded since."""
    today = today or date.today()
    out, with_end, re_seated = [], 0, 0

    for e in index.values():
        if e.get("entity_type") != "Person":
            continue
        started, ended = seats(e)
        if not ended:
            continue
        with_end += 1
        last = max(ended, key=lambda r: r["on"])
        # Anything that began after they left means they are placed.
        later = [s for s in started if s["on"] > last["on"]]
        if later:
            re_seated += 1
            continue
        if (today - last["on"]).days / 30.44 > months:
            continue
        s, why = score(last, today=today)
        out.append({
            "person": e.get("name"), "person_id": e.get("id"),
            "company": last["company"], "company_id": last.get("company_id"),
            "kind": last["kind"], "on": last["on"].isoformat(),
            "announced_only": last["on"] > today,
            "score": s, "why": why,
            "other_seats": len(started),
        })

    out.sort(key=lambda r: -r["score"])
    return {
        "rows": out[:limit],
        "coverage": {
            "people_with_an_end_date": with_end,
            "placed_since": re_seated,
            "open": len(out),
            "window_months": months,
        },
        "as_of": today.isoformat(),
    }
