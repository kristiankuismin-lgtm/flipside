"""The call list: who to actually contact, in the order to contact them.

A screen tells a founder which firms are worth approaching. It does not
tell them who to write to, and a fund is not a person. This merges the two
sources we have and says which one each name came from, because they are
not equally strong:

  Cala        a Person entity with a role and often a start date, read off
              the firm's whole record rather than one edge. Authoritative,
              and still thin - one person at Northzone, six at Creandum.
  Their site  a name and a role quoted from the firm's own team page.
              Plentiful, and only as good as the page.

Ranked by whether the founder should call at all, not by who is most
senior: a conflicted fund has no contact worth making.
"""
from __future__ import annotations

import re

from . import norm

# Who to call first at a firm. A partner writes cheques; an analyst does not.
SENIORITY = [
    (re.compile(r"\b(?:founding|general|managing)\s+partner\b", re.I), 100),
    (re.compile(r"\bpartner\b", re.I), 90),
    (re.compile(r"\b(?:co-?founder|founder)\b", re.I), 88),
    (re.compile(r"\b(?:ceo|chief executive)\b", re.I), 85),
    (re.compile(r"\bprincipal\b", re.I), 70),
    (re.compile(r"\b(?:investment\s+)?director\b", re.I), 65),
    (re.compile(r"\bventure\s+partner\b", re.I), 60),
    (re.compile(r"\b(?:entrepreneur|data scientist)[- ]in[- ]residence\b", re.I), 45),
    (re.compile(r"\b(?:associate|analyst)\b", re.I), 35),
    (re.compile(r"\b(?:advisor|adviser)\b", re.I), 30),
]
SOURCE_RANK = {"cala": 0, "site": 1}


def seniority(role: str | None) -> int:
    for rx, score in SENIORITY:
        if rx.search(role or ""):
            return score
    return 50 if role else 20          # a named role beats none


def _reason(inv: dict, stage: str) -> str:
    """Why this firm is on the list at all, in the founder's words."""
    s = inv.get("signals") or {}
    bits = []
    lead = (s.get("lead_rate") or {}).get("text")
    if lead:
        bits.append(lead.lower())
    pace = (s.get("dry_powder") or {}).get("text")
    if pace:
        bits.append(re.sub(r"\s*\(.*", "", pace))
    warm = s.get("warm_path") or {}
    if warm.get("label") not in (None, "⚪") and warm.get("text"):
        bits.append(warm["text"])
    return " · ".join(bits) or f"on your {stage} list"


# What moves a person up the list, and by how much. Weights are small on
# purpose: the fund still decides most of it, because a brilliant partner at
# a fund that cannot lead your round is still the wrong call. These break
# ties between people at firms worth calling.
PERSON_WEIGHTS = {
    "market": 14,     # they have been in your market - the strongest of these
    "angel": 11,      # they have written their own cheque, not only the fund's
    "operator": 10,   # they have built or run something themselves
    "tenure": 8,      # how long they have been at this firm
    "network": 6,     # doors they can open beyond their own cheque
    "verified": 4,    # a Cala Person entity rather than a name on a page
}
# Personal rounds above which more stops counting. Someone with four is an
# active angel; someone with forty is a fund of one, and not more reachable
# for it.
ANGEL_FULL = 4
NETWORK_FULL = 8      # intro surface above which more stops counting
# Years at the firm above which more stops counting. A partner of six years
# has whatever standing the firm gives; a partner of sixteen has no more say
# in one deal than they did at six. Someone three months in may not be able
# to champion a cheque at all, which is what this is really measuring.
TENURE_FULL = 6


def years_at_firm(since, today=None) -> float | None:
    """Years between a start date and today, or None if we have no date.

    Returns None rather than 0 for an unknown start, because a partner whose
    start date Cala does not hold is not a partner who started today.
    """
    import datetime as _dt
    if not since:
        return None
    text = str(since)[:10]
    try:
        d = _dt.date.fromisoformat(text)
    except ValueError:
        try:
            d = _dt.date(int(text[:4]), 1, 1)
        except (ValueError, TypeError):
            return None
    now = today or _dt.date.today()
    if d > now:
        return None
    return round((now - d).days / 365.25, 1)


_TWO_PEOPLE = __import__("re").compile(r"\s(?:&|and)\s", __import__("re").I)


def names_two_people(name: str | None) -> bool:
    """Cala holds one Index Ventures entity called "Lauren & Vlad Loktev".

    A call list exists to tell a founder who to ring, and that row cannot be
    rung. Splitting it would invent a person, so the row stays and says what
    it is.
    """
    return bool(_TWO_PEOPLE.search(name or ""))


def person_bonus(signals: dict | None) -> tuple[float, list[str]]:
    """Points and the reasons for them. Returns (0, []) when we know nothing,
    which is different from knowing the person has none of these."""
    if not signals:
        return 0.0, []
    pts, why = 0.0, []
    if signals.get("market_match"):
        pts += PERSON_WEIGHTS["market"]
        why.append("has been in your market")
    if signals.get("years_building"):
        yrs = signals["years_building"]
        pts += PERSON_WEIGHTS["operator"]
        why.append(f"operating {yrs} year{'s' if yrs != 1 else ''}")
    elif signals.get("operator"):
        pts += PERSON_WEIGHTS["operator"] * 0.6
        why.append("has operated, year unknown")
    # A partner who invests personally has decided alone before, and can
    # again. It is the difference between needing a partnership to say yes
    # and needing one person to.
    ar = signals.get("angel_rounds") or 0
    ac = signals.get("angel_companies") or 0
    if signals.get("angel") and (ar or ac):
        n = max(ar, ac)
        pts += PERSON_WEIGHTS["angel"] * min(n, ANGEL_FULL) / ANGEL_FULL
        # Say which evidence it is. A round we can date; a company on their
        # INVESTED_IN edge we usually cannot, and calling that "a round"
        # claims a precision the edge does not carry.
        unit = "round" if ar else "company" if n == 1 else "companies"
        last = signals.get("angel_last_year")
        why.append(f"invests personally — {n} {unit}"
                   + ("s" if ar and n != 1 else "")
                   + (f", last in {last}" if last else ""))
    yrs = signals.get("years_at_firm")
    if yrs is not None:
        pts += PERSON_WEIGHTS["tenure"] * min(yrs, TENURE_FULL) / TENURE_FULL
        why.append(f"{yrs:g} year{'s' if yrs != 1 else ''} at the firm")
    n = signals.get("network") or 0
    if n:
        pts += PERSON_WEIGHTS["network"] * min(n, NETWORK_FULL) / NETWORK_FULL
        why.append(f"can reach {n} compan{'ies' if n != 1 else 'y'}")
    if signals.get("verified"):
        pts += PERSON_WEIGHTS["verified"]
    return round(pts, 1), why


def build(investors: list[dict], people_by_fund: dict[str, list[dict]],
          *, stage: str = "", limit: int = 40) -> dict:
    """One row per person, best firm first, best contact within it first."""
    rows, skipped = [], []
    for inv in investors or []:
        name = inv.get("investor")
        sig = inv.get("signals") or {}
        if (sig.get("conflict") or {}).get("label") == "\U0001f534":
            skipped.append({"fund": name, "why": "backs a competitor",
                            "backs": inv.get("backs") or []})
            continue
        people = people_by_fund.get(norm.name(name)) or []
        if not people:
            skipped.append({"fund": name, "why": "no contact found",
                            "score": inv.get("score")})
            continue
        warm = (sig.get("warm_path") or {})
        for p in people:
            sigs = dict(p.get("signals") or {})
            # Tenure comes from the firm's own record, not from the person's,
            # so it is attached here rather than in the person card.
            yrs = years_at_firm(p.get("since"))
            if yrs is not None:
                sigs["years_at_firm"] = yrs
            p = {**p, "signals": sigs or None}
            bonus, why = person_bonus(p.get("signals"))
            rows.append({
                "person": p.get("name"), "role": p.get("role"),
                "ambiguous": names_two_people(p.get("name")),
                "person_id": p.get("id"),
                "signals": p.get("signals"),
                "bonus": bonus, "bonus_why": why,
                "linkedin": p.get("linkedin"), "site": p.get("site"),
                "source": p.get("source", "site"),
                "quote": p.get("quote"),
                "fund": name, "fund_score": inv.get("score"),
                "reason": _reason(inv, stage),
                "warm": warm.get("text") if warm.get("label") not in (None, "⚪") else None,
                "seniority": seniority(p.get("role")),
            })

    # One number per row so the order can be explained in a sentence: the
    # firm carries most of it, the person breaks the tie.
    for r in rows:
        r["call_score"] = round(
            (r["fund_score"] or 0)
            + (12 if r["warm"] else 0)       # an introduction beats a title
            + r["seniority"] * 0.12          # a partner over an analyst
            + r["bonus"], 1)
    rows.sort(key=lambda r: (-r["call_score"], SOURCE_RANK.get(r["source"], 9),
                             r["person"] or ""))
    return {"rows": rows[:limit], "total": len(rows),
            "funds_with_a_contact": len({r["fund"] for r in rows}),
            "skipped": skipped,
            "by_source": {s: sum(1 for r in rows if r["source"] == s)
                          for s in ("cala", "site")}}
