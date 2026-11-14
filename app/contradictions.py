"""Where our sources disagree with each other.

A product built on a knowledge graph inherits the graph's disagreements. Two
documents date the same round four months apart; two name different leads;
one reports a round size the other does not mention. Today we silently pick
one and render it as fact.

Showing the disagreement is more useful than hiding it, and it is the part a
founder most needs before repeating a number to the person it is about. None
of this guesses who is right - it says the sources differ, and shows both.
"""
from __future__ import annotations

from datetime import date, timedelta

from . import norm
from .models import Round

# Two records of the same company and stage this close together are almost
# certainly the same round reported twice, not two rounds.
SAME_ROUND_DAYS = 150
# Below this, two amounts are rounding or currency conversion, not a dispute.
AMOUNT_TOLERANCE = 0.15


def _f(r, name, default=None):
    """Read a field from a Round or from the plain dict the cache holds.

    Two shapes carry rounds in this codebase: the dataclass the metrics use
    and the dicts the cached corpus stores. Making the caller convert is how
    a checker like this ends up only ever running on one of them.
    """
    if isinstance(r, dict):
        v = r.get(name, default)
    else:
        v = getattr(r, name, default)
    return default if v is None else v


def _as_date(d) -> date | None:
    if isinstance(d, date):
        return d
    try:
        y, m, dd = (str(d)[:10].split("-") + ["1", "1"])[:3]
        return date(int(y), int(m), int(dd))
    except (ValueError, TypeError):
        return None


def _amount(r):
    """Cached rounds spell the amount differently from the dataclass."""
    for k in ("amount_eur", "amount", "amount_usd"):
        v = _f(r, k)
        if v:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _amounts_disagree(a: float | None, b: float | None) -> bool:
    if not a or not b:
        return False
    lo, hi = sorted((float(a), float(b)))
    return hi > 0 and (hi - lo) / hi > AMOUNT_TOLERANCE


def _fmt_m(v: float | None) -> str:
    return "unknown" if not v else f"€{round(v / 1e6, 1)}M"


def duplicate_pairs(rounds: list[Round]) -> list[tuple[Round, Round]]:
    """Records that look like the same round seen twice."""
    rs = [r for r in rounds if _as_date(_f(r, "date"))]
    rs.sort(key=lambda r: _as_date(_f(r, "date")))
    out = []
    for i, a in enumerate(rs):
        for b in rs[i + 1:]:
            da, db = _as_date(_f(a, "date")), _as_date(_f(b, "date"))
            if db - da > timedelta(days=SAME_ROUND_DAYS):
                break
            if norm.stage(_f(a, "stage", "")) == norm.stage(_f(b, "stage", "")):
                out.append((a, b))
    return out


def find(company: str, rounds: list[Round]) -> list[dict]:
    """Every disagreement we can see in one company's rounds.

    Each item names the field in dispute, both readings, and the documents
    behind them where we have any.
    """
    out: list[dict] = []

    for a, b in duplicate_pairs(rounds):
        da, db = _as_date(_f(a, "date")), _as_date(_f(b, "date"))
        srcs = sorted({*(_f(a, "sources", []) or []), *(_f(b, "sources", []) or [])})

        if da != db:
            out.append({
                "company": company, "field": "date", "stage": _f(a, "stage", ""),
                "a": str(da), "b": str(db),
                "detail": (f"Two records of a {_f(a, "stage", "")} round dated {da} and "
                           f"{db} — {abs((db - da).days)} days apart."),
                "sources": srcs,
            })
        if _amounts_disagree(_amount(a), _amount(b)):
            out.append({
                "company": company, "field": "amount", "stage": _f(a, "stage", ""),
                "a": _fmt_m(_amount(a)), "b": _fmt_m(_amount(b)),
                "detail": (f"The same {_f(a, "stage", "")} round is reported at "
                           f"{_fmt_m(_amount(a))} and {_fmt_m(_amount(b))}."),
                "sources": srcs,
            })
        la = {norm.name(x) for x in (_f(a, "leads", []) or [])}
        lb = {norm.name(x) for x in (_f(b, "leads", []) or [])}
        if la and lb and la != lb:
            out.append({
                "company": company, "field": "lead", "stage": _f(a, "stage", ""),
                "a": ", ".join(sorted(_f(a, "leads", []))), "b": ", ".join(sorted(_f(b, "leads", []))),
                "detail": (f"Two records of the same {_f(a, "stage", "")} round name "
                           f"different leads."),
                "sources": srcs,
            })

    # A single round naming several leads is not always a contradiction -
    # co-leads are real - but it changes what "led by" means, so say so.
    for r in rounds:
        leads = {norm.name(x) for x in (_f(r, "leads", []) or []) if norm.name(x)}
        if len(leads) > 1:
            out.append({
                "company": company, "field": "lead", "stage": _f(r, "stage", ""),
                "a": ", ".join(sorted(_f(r, "leads", []))), "b": None,
                "detail": (f"{len(leads)} investors are recorded as leading the "
                           f"same {_f(r, "stage", "")} round. Co-leads happen; so do "
                           f"sources disagreeing."),
                "sources": sorted(set(_f(r, "sources", []) or [])),
                "soft": True,
            })
    return out


def summarise(by_company: dict[str, list[Round]]) -> dict:
    """All disagreements across a screen, newest companies first."""
    items, companies = [], 0
    for name, rs in (by_company or {}).items():
        hits = find(name, rs or [])
        if hits:
            companies += 1
            items.extend(hits)
    hard = [i for i in items if not i.get("soft")]
    return {"count": len(items), "hard": len(hard), "companies": companies,
            "items": items}
