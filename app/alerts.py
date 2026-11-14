"""Alerts, evaluated against a screen rather than promised for later.

An alert product normally says "we will email you when this happens". We
cannot run a cron on a hackathon weekend and pretending otherwise would be
the one dishonest thing in this codebase, so an alert here is a rule that
runs against the current screen and shows what it catches now, plus exactly
what it would need to run unattended.

The rules are written for the question the product is about: who became
un-pitchable since you last looked.
"""
from __future__ import annotations

from . import norm

RULES = {
    "new_conflict": {
        "label": "A fund on my list starts backing a competitor",
        "why": "the one that changes whether you can pitch them at all",
        "severity": "high",
    },
    "competitor_raised": {
        "label": "A competitor raises a round",
        "why": "who funded it is your next exclusion",
        "severity": "high",
    },
    "fund_slowed": {
        "label": "A fund I am targeting stops deploying",
        "why": "a fund at the end of its cycle will take the meeting and not the deal",
        "severity": "medium",
    },
    "fund_leads_my_stage": {
        "label": "A fund leads a round at my stage",
        "why": "evidence they still lead, not just participate",
        "severity": "low",
    },
    "stale": {
        "label": "A fund on my list goes quiet",
        "why": "no recorded activity for a long time",
        "severity": "low",
    },
}


def _sig(x, key):
    return (x.get("signals") or {}).get(key) or {}


def evaluate(investors: list[dict], *, enabled: set[str] | None = None,
             stage: str = "", stale_months: int = 18,
             known_conflicts: set[str] | None = None) -> list[dict]:
    """Which rules fire on this screen, and on whom.

    `known_conflicts` is what the founder had already seen; anything outside
    it is new, which is the only part of a conflict that is news.
    """
    on = enabled if enabled is not None else set(RULES)
    seen = {norm.name(x) for x in (known_conflicts or set())}
    out = []

    for x in investors or []:
        name = x.get("investor")
        key = norm.name(name)
        backs = x.get("backs") or []
        b = x.get("breakdown") or {}

        if "new_conflict" in on and backs:
            out.append({"rule": "new_conflict", "investor": name,
                        "new": key not in seen,
                        "detail": f"backs {', '.join(backs)}",
                        "severity": "high" if key not in seen else "seen"})

        if "fund_slowed" in on and _sig(x, "dry_powder").get("label") == "\U0001f534":
            out.append({"rule": "fund_slowed", "investor": name, "new": True,
                        "detail": _sig(x, "dry_powder").get("text") or "pace has dropped",
                        "severity": "medium"})

        if "fund_leads_my_stage" in on and _sig(x, "lead_rate").get("label") == "\U0001f7e2":
            out.append({"rule": "fund_leads_my_stage", "investor": name, "new": True,
                        "detail": _sig(x, "lead_rate").get("text") or f"leads at {stage}",
                        "severity": "low"})

        months = b.get("months_since_activity")
        if "stale" in on and months is not None and months >= stale_months:
            out.append({"rule": "stale", "investor": name, "new": True,
                        "detail": f"no recorded activity for {months} months",
                        "severity": "low"})

    order = {"high": 0, "medium": 1, "low": 2, "seen": 3}
    out.sort(key=lambda a: (order.get(a["severity"], 9), a["investor"] or ""))
    return out


def competitor_rounds(competitors: list[dict], rounds_by_company: dict,
                      months: int = 18, today: str = "") -> list[dict]:
    """Competitors that raised recently, and who funded them.

    This is the rule that generates tomorrow's exclusions: every investor in
    a competitor's new round is a fund you can no longer pitch.
    """
    from datetime import date
    today = today or date.today().isoformat()
    cut_y, cut_m = int(today[:4]), int(today[5:7])
    out = []
    for c in competitors or []:
        name = c.get("name") if isinstance(c, dict) else c
        for r in (rounds_by_company.get(norm.name(name)) or []):
            d = str(r.get("date") or "")
            if len(d) < 7:
                continue
            age = (cut_y - int(d[:4])) * 12 + (cut_m - int(d[5:7]))
            if 0 <= age <= months:
                out.append({"rule": "competitor_raised", "competitor": name,
                            "date": d, "stage": r.get("stage"),
                            "investors": r.get("investors") or [],
                            "months_ago": age, "severity": "high", "new": True})
    out.sort(key=lambda x: x["date"], reverse=True)
    return out
