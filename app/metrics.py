"""M1-M5 + Score. Puhdasta Pythonia: syotteena Round-listat, ei API-kutsuja.

Kaksi sääntöä, joista ei jousteta:
  1. Nimivertailu kulkee aina norm.matches():n lapi (ks. app/norm.py).
  2. Datan puute on ⚪, ei 🔴. Punainen on vaite sijoittajasta; valkoinen
     on vaite omasta datasta. Niiden sekoittaminen on valhe tuomarille.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from . import norm
from .models import Round, Signal, Evidence

TODAY = date.today()
WINDOW = TODAY - timedelta(days=36 * 30)

NO_DATA = "⚪"


def _conf(n, native=True):
    if n >= 10 and native:
        return "High"
    if n >= 5:
        return "Medium"
    return "Low"


def by_company(rounds: list[Round]) -> dict[str, list[Round]]:
    d = defaultdict(list)
    for r in rounds:
        d[norm.name(r.company) or r.company].append(r)
    for v in d.values():
        v.sort(key=lambda r: r.date)
    return dict(d)


def _entry_index(inv: str, rs: list[Round]) -> int | None:
    """Ensimmainen kierros, jolla sijoittaja esiintyy."""
    return next((i for i, r in enumerate(rs) if norm.matches(inv, r.investors)), None)


# ---- M1 Liidausosuus ---------------------------------------------------------
def lead_rate(inv: str, inv_rounds: list[Round], stage: str | None = None) -> Signal:
    want = norm.stage(stage) if stage else None
    rs = [r for r in inv_rounds
          if r.date >= WINDOW and (want is None or norm.stage(r.stage) == want)]
    n = len(rs)
    if not n:
        return Signal("lead_rate", None, NO_DATA,
                      f"No {stage or ''} rounds in the 36-month window".strip(),
                      0, "Low")

    led = [r for r in rs if norm.matches(inv, r.leads)]
    v = len(led) / n
    native = all(r.lead_is_native for r in rs)
    lab = "🟢" if v >= .4 else "🟡" if v >= .15 else "🔴"
    txt = f"Led {len(led)} of {n} {stage or ''} rounds ({v:.0%})".replace("  ", " ")
    ev = [Evidence(f"{r.company} {r.stage} {r.date}", (r.sources or [None])[0]) for r in led[:3]]
    # Date the claim: the last time it actually led at this stage, falling
    # back to the last time we saw it in one at all.
    last = max((r.date for r in (led or rs)), default=None)
    return Signal("lead_rate", v, lab, txt, n, _conf(n, native), ev, last_date=last)


# ---- M2 Follow-on ------------------------------------------------------------
def follow_on(inv: str, company_rounds: dict[str, list[Round]]) -> tuple[Signal, Signal]:
    """Osallistuuko sijoittaja portfolioyhtioidensa seuraaviin kierroksiin?

    Mukaan vain yhtiot, joiden sisaantulokierros on >= 18 kk vanha: nuoremmilla
    ei ole viela ollut aikaa nostaa seuraavaa, joten ne vaaristaisivat osuutta.
    """
    cutoff = TODAY - timedelta(days=18 * 30)
    had_next = followed = next24 = entries = 0
    gaps, ev = [], []

    for rs in company_rounds.values():
        idx = _entry_index(inv, rs)
        if idx is None or rs[idx].date > cutoff:
            continue
        entries += 1
        if idx + 1 < len(rs):
            nxt = rs[idx + 1]
            had_next += 1
            gap = (nxt.date - rs[idx].date).days
            gaps.append(gap)
            if gap <= 730:
                next24 += 1
            if norm.matches(inv, nxt.investors):
                followed += 1
                ev.append(Evidence(f"Joined {nxt.company}'s {nxt.stage} round",
                                   (nxt.sources or [None])[0]))

    fo = followed / had_next if had_next else None
    nr = next24 / entries if entries else None
    med = median(gaps) / 30 if gaps else None

    s1 = Signal("follow_on", fo,
                NO_DATA if fo is None else "🟢" if fo >= .6 else "🟡" if fo >= .35 else "🔴",
                (f"Followed on in {followed} of {had_next} next rounds ({fo:.0%})"
                 if fo is not None else "No mature portfolio yet (entry <18 months ago)"),
                had_next, _conf(had_next), ev[:3])

    s2 = Signal("next_round", nr,
                NO_DATA if nr is None else "🟢" if nr >= .55 else "🟡" if nr >= .35 else "🔴",
                ((f"{nr:.0%} of the portfolio raised again within 24 months"
                  + (f", median {med:.0f} months" if med else ""))
                 if nr is not None else "No data"),
                entries, _conf(entries))
    return s1, s2


# ---- M3 Konfliktit -----------------------------------------------------------
def conflict(founder_vec, portfolio: list[dict], named_competitors: set[str]) -> Signal:
    """portfolio: [{'name','vec','source'}]; vec = normalisoitu embedding."""
    import numpy as np

    if not portfolio:
        return Signal("conflict", None, NO_DATA, "Portfolio unavailable", 0, "Low")

    named = {norm.name(c) for c in (named_competitors or set())}
    best, best_p = 0.0, None
    for p in portfolio:
        s = float(np.dot(founder_vec, p["vec"]))
        if norm.name(p["name"]) in named:
            s = max(s, .95)
        if s > best:
            best, best_p = s, p

    if best >= .85:
        lab, t = "🔴", f"Suora konflikti: {best_p['name']}"
    elif best >= .75:
        lab, t = "🟡", f"Laheinen: {best_p['name']}"
    else:
        lab, t = "🟢", "Ei konfliktia portfoliossa"
    ev = [Evidence(t, best_p.get("source"))] if best_p and lab != "🟢" else []
    return Signal("conflict", best, lab, t, len(portfolio), _conf(len(portfolio)), ev)


# ---- M4 Kuiva ruuti ----------------------------------------------------------
def dry_powder(inv: str, company_rounds: dict[str, list[Round]],
               latest_fund: dict | None = None) -> Signal:
    firsts = []
    for rs in company_rounds.values():
        i = _entry_index(inv, rs)
        if i is not None:
            firsts.append(rs[i].date)

    if not firsts:
        return Signal("dry_powder", None, NO_DATA, "No investment history in window", 0, "Low")

    new6 = sum(d >= TODAY - timedelta(days=180) for d in firsts)
    prev = sum(TODAY - timedelta(days=730) <= d < TODAY - timedelta(days=180) for d in firsts)
    base = prev / 3          # 18 kk -> 6 kk:n keskiarvo
    vel = new6 / max(base, 1)
    lab = "🟢" if vel >= 1 else "🟡" if vel >= .5 else "🔴"
    txt = f"{new6} new investments in 6 months (prior pace {base:.1f})"

    if latest_fund and latest_fund.get("vintage"):
        age = TODAY.year - int(latest_fund["vintage"])
        phase = "🟢 deploying" if age <= 3 else "🟡 late in life" if age <= 5 else "🔴 follow-on only"
        txt = f"{latest_fund.get('name', 'Fund')} ({latest_fund['vintage']}): {phase} · " + txt
        if age > 5:
            lab = "🔴"
    return Signal("dry_powder", vel, lab, txt, len(firsts), _conf(len(firsts)),
                  [Evidence("Fund data", latest_fund.get("source"))] if latest_fund else [])


# ---- M5 Lammin reitti --------------------------------------------------------
WEIGHTS = {"coinvest": 1.0, "colleague_portfolio_founder": .9,
           "colleague_partner": .8, "board": .6, "alumni": .5}


def warm_path(paths: list[dict]) -> Signal:
    if not paths:
        return Signal("warm_path", 0, NO_DATA, "No known route", 0, "Low")
    paths = sorted(paths, key=lambda p: WEIGHTS.get(p["type"], 0), reverse=True)
    top = paths[0]
    w = WEIGHTS.get(top["type"], 0)
    return Signal("warm_path", w, "🟢" if w >= .8 else "🟡", top["text"], len(paths),
                  "Medium", [Evidence(p["text"], p.get("source")) for p in paths[:3]])


# ---- Score -------------------------------------------------------------------
# How much of the quality score each signal carries when it is known, and what
# to assume about it before the evidence says otherwise.
QUALITY_WEIGHTS = {"lead_rate": .30, "follow_on": .30,
                   "next_round": .20, "dry_powder": .20}
# Ranking by a rate when sample sizes differ needs a lower confidence bound,
# not a raw rate and not shrinkage toward a prior.
#
# Shrinkage was the first attempt and it failed in a way worth recording:
# pulling toward a prior of 0.25 lifts a fund that led 0 of 2 rounds up to
# 0.17, and Icebreaker.vc - which has never led a Series A in this data -
# ranked first for a founder raising a Series A. A prior that pulls upward
# flatters exactly the funds a founder must not pick as a lead.
#
# The Wilson lower bound only ever penalises small samples. 1-of-1 scores
# below 6-of-9 because one observation proves little, while 0-of-2 stays at
# the bottom, where it belongs.
# z=1.0 leaves 1-of-1 and 6-of-9 tied to three decimal places, which is not
# an ordering so much as a coin flip. At 1.5 the long record wins clearly
# (0.42 against 0.31) and a strong short one still places above both (4-of-5
# scores 0.47), which is the behaviour a founder would expect.
Z = 1.5


def wilson_lower(value: float | None, n: int, z: float = Z) -> float:
    """Lower bound of the confidence interval on a rate."""
    if value is None:
        return 0.0
    n = max(0, int(n or 0))
    if n == 0:
        return 0.0
    p = min(max(float(value), 0.0), 1.0)
    z2 = z * z
    centre = p + z2 / (2 * n)
    margin = z * ((p * (1 - p) + z2 / (4 * n)) / n) ** 0.5
    return max(0.0, (centre - margin) / (1 + z2 / n))


def quality(sig: dict) -> tuple[float, float]:
    """(quality score 0-1, share of the weight that was actually known).

    Unknown signals are left out and the remaining weights renormalised. The
    old version read `sig[k].value or 0`, which scored "we have no follow-on
    data" identically to "this fund never follows on" - the one mistake this
    codebase refuses to make everywhere else.
    """
    num = den = known = 0.0
    for k, w in QUALITY_WEIGHTS.items():
        s = sig.get(k)
        if s is None or s.value is None:
            continue
        v = min(float(s.value), 1.0) if k == "dry_powder" else float(s.value)
        num += w * wilson_lower(v, getattr(s, "n", 0) or 0)
        den += w
        known += w
    if den == 0:
        # Nothing known at all. evidence_depth upstream decides whether this
        # fund is rankable; here it simply earns no quality.
        return 0.0, 0.0
    return num / den, known / sum(QUALITY_WEIGHTS.values())


# Enough stage rounds to conclude something from a zero. Below this, "never
# led" and "we have barely looked" are the same observation.
LEAD_EVIDENCE_N = 3
NON_LEAD_FACTOR = 0.65


def lead_factor(sig: dict[str, Signal]) -> float:
    """Discount a fund that demonstrably does not lead at this stage.

    The founder is ranking candidates to LEAD a round, so "led 0 of 9 Series
    A rounds" is not a weak signal among several - it is close to an answer.
    An unknown lead rate is left alone: unknown is not zero, here as
    everywhere else.
    """
    s = sig.get("lead_rate")
    if s is None or s.value is None:
        return 1.0
    if (getattr(s, "n", 0) or 0) < LEAD_EVIDENCE_N:
        return 1.0           # too few rounds to read anything into a zero
    return NON_LEAD_FACTOR if s.value == 0 else 1.0


# Aging the founder ranking, for the same reason the investor ranking is aged:
# a fund that last led a Series A in 2021 is weaker evidence about who will
# lead one in 2026 than a fund that led one in March. This mirrors
# conviction.recency_factor() deliberately - two halves of the product must
# not disagree about how old is old.
GRACE_MONTHS = 18        # funds move slower than companies; a year and a half
HALFLIFE_MONTHS = 24
RECENCY_FLOOR = 0.55     # a fund with an old record is still a fund
STALE_AFTER_MONTHS = 30


def months_since(d, today: date | None = None) -> int | None:
    """Whole months between a date and today. None when there is no date."""
    if not d:
        return None
    today = today or TODAY
    if isinstance(d, str):
        try:
            parts = [int(x) for x in d[:7].split("-")[:2]]
        except ValueError:
            return None
        if len(parts) < 2:
            return None
        y, m = parts
    else:
        y, m = d.year, d.month
    return max(0, (today.year - y) * 12 + (today.month - m))


def recency_factor(months: int | None) -> float:
    """1.0 while current, halving every HALFLIFE_MONTHS past the grace
    period, floored. Unknown age is treated as current: we do not know that
    it is old, and guessing downward punishes thin coverage twice."""
    if months is None:
        return 1.0
    over = months - GRACE_MONTHS
    if over <= 0:
        return 1.0
    return max(RECENCY_FLOOR, 0.5 ** (over / HALFLIFE_MONTHS))


def last_activity(sig: dict[str, Signal]) -> int | None:
    """Months since this fund last did the thing we are ranking it for.

    Prefers the most recent round it led at the stage, because that is the
    claim the ranking rests on; falls back to any round we saw it in.
    """
    for key in ("lead_rate", "follow_on", "next_round"):
        s = sig.get(key)
        d = getattr(s, "last_date", None) if s else None
        if d:
            return months_since(d)
    return None


def score(fit: dict, sig: dict[str, Signal]) -> float:
    f = .35 * fit["stage"] + .30 * fit["sector"] + .20 * fit["geo"] + .15 * fit["check"]
    q, coverage = quality(sig)
    c = sig.get("conflict")
    cm = 0 if c and c.label == "🔴" else .7 if c and c.label == "🟡" else 1
    warm = sig.get("warm_path")
    wv = (warm.value or 0) if warm and warm.value is not None else 0
    # A score built on one known signal should not sit next to one built on
    # four as though they were the same claim.
    conf = 0.85 + 0.15 * coverage
    rf = recency_factor(last_activity(sig))
    return round(100 * f * (.5 + .5 * q) * cm * lead_factor(sig)
                 * (1 + .15 * wv) * conf * rf, 1)
