"""The cohort before anyone has built anything: people at the places founders leave.

The product already finds people who have founded, people who shipped and
posted it, and people with a live unannounced repository. This is the step
before all three - somebody with a job, no company, no side project visible
on any code host, who is sitting where founders tend to come from and has
been sitting there about as long as they usually sit before they go.

Nothing here is a prediction about a person. The claim is only that this is
a sensible place to look, and every row says what it was selected on.

Where the signal comes from. Context.dev's people search is a licensed
database with a query interface; this module calls that API and never
fetches a social network. A profile URL in a result is an identifier to
show the user, not a page this code reads.

What makes a row interesting, in the order it matters:

  tenure      The founding window is real and it is not "the longest
              serving". People leave to start things roughly two to five
              years in; before that they are still learning the job, after
              about eight they have usually chosen not to.
  seniority   Enough rope to have seen how the company works.
  experience  Five to fifteen years overall. A first-year engineer and a
              thirty-year veteran are both unlikely, for opposite reasons.
  not yet     is_founder must be false. Someone who has already founded
              belongs in the first cohort, where the evidence is stronger.

The weights saturate rather than add without limit, the same as every other
ranking here, so that one extreme value cannot carry a row on its own.
"""
from __future__ import annotations

from datetime import date, datetime

from . import context_dev as cx

W_TENURE = 38          # how long they have been where they are
W_SENIORITY = 20       # enough rope to have seen the whole machine
W_EXPERIENCE = 18      # deep enough to build, early enough to risk it
W_EMPLOYER = 14        # the employer itself is a signal, when we know it
W_SCHOOL = 10          # a school the graph already connects to founders

# The founding window, in years at the current employer.
TENURE_MIN, TENURE_PEAK, TENURE_MAX = 1.5, 3.0, 8.0
EXP_MIN, EXP_PEAK, EXP_MAX = 4.0, 9.0, 20.0

# The provider's own vocabulary, read off live results rather than guessed.
# mid_senior_level and associate were missing, so every Spotify row scored
# zero on seniority while its tenure and experience counted - which quietly
# ranked a whole employer below another for a reason that was not real.
SENIORITY = {"c_suite": 1.0, "owner": 1.0, "executive": 0.9, "partner": 0.95, "vp": 0.95,
             "director": 0.9, "head": 0.85, "principal": 0.8, "lead": 0.8,
             "staff": 0.8, "senior": 0.7, "mid_senior_level": 0.7,
             "manager": 0.6, "mid_level": 0.5, "associate": 0.4,
             "entry_level": 0.25, "junior": 0.2,
             "intern": 0.0, "internship": 0.0, "training": 0.0, "unpaid": 0.0}


def _years_since(iso: str | None, *, today: date) -> float | None:
    if not iso:
        return None
    try:
        d = datetime.fromisoformat(str(iso)[:10]).date()
    except ValueError:
        return None
    return max(0.0, (today - d).days / 365.25)


def _window(v: float | None, lo: float, peak: float, hi: float) -> float:
    """1.0 at the peak, falling to 0 at either edge. None is not zero."""
    if v is None:
        return 0.0
    if v <= lo or v >= hi:
        return 0.0
    return (v - lo) / (peak - lo) if v < peak else (hi - v) / (hi - peak)


def search(query: str, *, cursor: str | None = None, fetcher=None) -> dict:
    payload = {"query": query}
    if cursor:
        payload["cursor"] = cursor
    return (fetcher or cx.call)("/people/search", payload, timeout=90) or {}


def score(p: dict, *, today: date, employers: dict[str, float] | None = None,
          schools: set[str] | None = None) -> tuple[float, list[str]]:
    role = p.get("role") or {}
    why, pts = [], 0.0

    tenure = _years_since(role.get("started_on"), today=today)
    t = _window(tenure, TENURE_MIN, TENURE_PEAK, TENURE_MAX)
    if t:
        pts += W_TENURE * t
        why.append(f"{tenure:.1f} years in the seat, inside the window people "
                   "usually leave in")
    elif tenure is not None:
        why.append(f"{tenure:.1f} years in the seat, outside the usual window")

    sen = SENIORITY.get((role.get("seniority") or "").lower())
    if sen:
        pts += W_SENIORITY * sen
        why.append(f"{(role.get('title') or role.get('seniority') or '').strip()}")

    exp = p.get("years_of_experience")
    e = _window(float(exp) if exp is not None else None,
                EXP_MIN, EXP_PEAK, EXP_MAX)
    if e:
        pts += W_EXPERIENCE * e
        why.append(f"{int(exp)} years in the industry")

    co = (role.get("company") or {}).get("name") or ""
    rate = (employers or {}).get(co.lower())
    if rate:
        pts += W_EMPLOYER * min(1.0, rate)
        why.append(f"{co} is a place this graph has seen founders come from")
    elif co:
        why.append(f"at {co}")

    if schools:
        hit = [s for s in (p.get("schools") or [])
               if (s or "").strip().lower() in schools]
        if hit:
            pts += W_SCHOOL
            why.append(f"studied at {hit[0]}")

    return round(min(100.0, pts), 1), why


def rank(query: str, *, today: date | None = None, limit: int = 25,
         pages: int = 2, employers: dict | None = None,
         schools: set[str] | None = None, fetcher=None) -> dict:
    """People matching the query who have not founded anything yet."""
    today = today or datetime.now().date()
    seen, rows, cursor, pulled = set(), [], None, 0
    for _ in range(max(1, pages)):
        r = search(query, cursor=cursor, fetcher=fetcher)
        got = r.get("results") or []
        pulled += len(got)
        for p in got:
            # The defining filter. Someone who has already founded is a
            # stronger lead and belongs in the cohort built for that.
            if p.get("is_founder"):
                continue
            key = (p.get("name") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            s, why = score(p, today=today, employers=employers, schools=schools)
            if s <= 0:
                continue
            role = p.get("role") or {}
            loc = p.get("location") or {}
            rows.append({
                "name": p.get("name"),
                "title": role.get("title"),
                "company": (role.get("company") or {}).get("name"),
                "domain": (role.get("company") or {}).get("domain"),
                "since": role.get("started_on"),
                "seniority": role.get("seniority"),
                "experience_years": p.get("years_of_experience"),
                "country": loc.get("country_code"),
                "city": loc.get("city"),
                "schools": (p.get("schools") or [])[:2],
                "profiles": (p.get("profiles") or [])[:1],
                "score": s,
                "why": why,
            })
        cursor = r.get("next_cursor")
        if not cursor:
            break
    rows.sort(key=lambda r: -r["score"])
    return {
        "rows": rows[:limit],
        "query": query,
        "seen": pulled,
        "already_founded": pulled - len(rows) if pulled >= len(rows) else 0,
        "as_of": today.isoformat(),
    }
