"""Investor side: insider conviction.

One matrix, two reading directions. The founder reads it by investor —
"does this fund come back to its companies?" The investor reads it by
company — "did THIS company's existing backers come back with their own
money?" Insiders know the most and their cheque is the one signal that
cannot be marketed.

Four things separate this from the naive "insiders returned, good" model:

  1. A return is only informative against that investor's own habit.
     Returning when you usually return 25% of the time is a strong signal.
     Returning when you always return says almost nothing.
  2. Who skipped matters more than how many. A seed fund skipping a
     Series A is noise - small reserves. The round's previous LEAD
     skipping is the loudest silence in venture.
  3. An insider-only round means two opposite things. Pre-emption (lead
     comes back inside 12 months at >=2x) is the strongest positive
     signal there is. A bridge (smaller, "extension"/"Seed+", or >18
     months later) is negative.
  4. A late-life fund explains absence. If the insider's fund has stopped
     deploying, its absence is neutral, not negative - which is exactly
     what the founder-side pace metric already measures. One engine.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from . import norm
from .models import Round

TODAY = date.today()

# Round structure
PREEMPTION = "pre-emption"
HEALTHY = "healthy"
BRIDGE = "bridge"
UNKNOWN = "unknown"

BRIDGE_WORDS = ("extension", "bridge", "seed+", "seed plus", "pre-a", "a-1", "safe", "note")

ANGEL, SEED_FUND, MULTISTAGE = "angel", "seed fund", "multi-stage"

# How much weight a given investor type's absence carries.
ABSENCE_WEIGHT = {MULTISTAGE: 1.0, SEED_FUND: 0.35, ANGEL: 0.15, UNKNOWN: 0.5}


@dataclass
class Insider:
    name: str
    returned: bool
    was_lead: bool
    kind: str = UNKNOWN
    baseline: float | None = None      # how often this investor usually returns
    fund_slowing: bool = False
    def lift(self) -> float | None:
        """Return above the investor's own habit. None when habit unknown."""
        if self.baseline is None:
            return None
        return (1.0 if self.returned else 0.0) - self.baseline


@dataclass
class Conviction:
    company: str
    score: float | None
    structure: str
    insiders: list[Insider] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    confidence: str = "Low"
    previous_lead_returned: bool | None = None
    n_insiders: int = 0


def classify_structure(prev: Round, latest: Round) -> str:
    """Pre-emption, bridge or healthy round."""
    label = f"{latest.stage}".lower()
    gap_days = (latest.date - prev.date).days
    bigger = None
    if prev.amount_eur and latest.amount_eur:
        bigger = latest.amount_eur >= 2 * prev.amount_eur

    if any(w in label for w in BRIDGE_WORDS):
        return BRIDGE
    insider_only = bool(latest.investors) and all(
        norm.matches(i, prev.investors) for i in latest.investors)

    if insider_only:
        if gap_days <= 365 and bigger:
            return PREEMPTION
        if gap_days > 548 or bigger is False:
            return BRIDGE
        return UNKNOWN          # insider-only but size unknown: do not guess
    return HEALTHY


def _conf(n: int, known_baselines: int) -> str:
    if n >= 4 and known_baselines >= 2:
        return "High"
    if n >= 2:
        return "Medium"
    return "Low"


def assess(company: str, rounds: list[Round],
           baselines: dict[str, float] | None = None,
           kinds: dict[str, str] | None = None,
           slowing: set[str] | None = None,
           pool_mean: float | None = None) -> Conviction:
    """Score one company's latest round by who came back.

    rounds must be chronological. Needs at least two rounds.
    """
    baselines, kinds, slowing = baselines or {}, kinds or {}, slowing or set()
    rs = sorted(rounds, key=lambda r: r.date)
    if len(rs) < 2:
        return Conviction(company, None, UNKNOWN, [],
                          ["Fewer than two rounds in Cala — nothing to compare"], "Low")

    latest, prev = rs[-1], rs[-2]
    prior_investors = {i for r in rs[:-1] for i in r.investors}
    if not prior_investors:
        return Conviction(company, None, UNKNOWN, [],
                          ["No investors recorded on earlier rounds"], "Low")

    prev_leads = {norm.name(x) for x in prev.leads}
    ins: list[Insider] = []
    for name in sorted(prior_investors):
        key = norm.name(name)
        ins.append(Insider(
            name=name,
            returned=norm.matches(name, latest.investors),
            was_lead=key in prev_leads,
            kind=kinds.get(key, UNKNOWN),
            baseline=baselines.get(key),
            fund_slowing=key in slowing,
        ))

    structure = classify_structure(prev, latest)

    # The previous lead is a first-class signal, not one vote among many.
    leads = [i for i in ins if i.was_lead]
    lead_returned = None if not leads else any(i.returned for i in leads)

    # Weighted participation: absence counts for more when the investor is a
    # multi-stage fund, for less when it is an angel or a fund that has stopped.
    num = den = 0.0
    for i in ins:
        w = ABSENCE_WEIGHT.get(i.kind, 0.5)
        if i.fund_slowing and not i.returned:
            w *= 0.25            # late-life fund: absence explained, near-neutral
        den += w
        if i.returned:
            num += w
    participation = num / den if den else None

    # Lift above habit, averaged over insiders whose habit we know.
    lifts = [i.lift() for i in ins if i.lift() is not None]
    lift = sum(lifts) / len(lifts) if lifts else None

    # Weighted blend rather than additive bonuses. The earlier version added
    # bonuses onto 100*participation and clipped, so a dozen companies tied at
    # exactly 100 and the ranking carried no information at the top.
    #
    # Participation is also shrunk toward the pool mean, so "1 of 1 insider
    # returned" cannot outrank "6 of 6" the way a raw ratio would.
    reasons: list[str] = []
    # Shrink on the NUMBER of insiders, not on the weight sum: weights are
    # fractions (an angel counts 0.15), so a weight-scaled prior would swamp
    # every small cap table.
    PRIOR = 1.5
    pool = pool_mean if pool_mean is not None else 0.45
    n_ins = len(ins)
    raw_part = (num / den) if den else pool
    part = (raw_part * n_ins + pool * PRIOR) / (n_ins + PRIOR)
    if participation is not None:
        reasons.append(f"{sum(i.returned for i in ins)}/{len(ins)} prior investors returned")

    lift_norm = 0.5 if lift is None else max(0.0, min(1.0, (lift + 1) / 2))
    if lift is not None:
        reasons.append(f"{'above' if lift > 0 else 'below'} their usual follow-on habit "
                       f"({lift:+.0%})")

    if lead_returned is True:
        lead_c = 1.0
        reasons.append(f"previous lead ({leads[0].name}) came back")
    elif lead_returned is False:
        lead_c = 0.0
        reasons.append(f"previous lead ({leads[0].name}) did not return")
    else:
        lead_c = 0.5

    struct_c = {PREEMPTION: 1.0, HEALTHY: 0.6, BRIDGE: 0.1, UNKNOWN: 0.5}[structure]
    if structure == PREEMPTION:
        reasons.append("insider-only round at >=2x within 12 months - pre-emption")
    elif structure == BRIDGE:
        reasons.append("bridge/extension rather than a priced up-round")

    score = 100 * (0.45 * part + 0.25 * lift_norm + 0.20 * lead_c + 0.10 * struct_c)

    slow = [i.name for i in ins if i.fund_slowing and not i.returned]
    if slow:
        reasons.append(f"absence discounted for {', '.join(slow[:2])} — fund has slowed")

    return Conviction(company, round(max(0.0, min(100.0, score)), 1), structure, ins,
                      reasons, _conf(len(ins), len(lifts)), lead_returned, len(ins))


def is_orphan(company: str, rounds: list[Round], headcount_growth: float | None,
              lead_fund_slowing: bool, still_operating: bool = True) -> tuple[bool, list[str]]:
    """A good company whose lead can no longer follow. Not the company's fault.

    Nobody lists these, which is exactly why they are worth finding.
    """
    rs = sorted(rounds, key=lambda r: r.date)
    if not rs:
        return False, ["no rounds"]
    months = (TODAY - rs[-1].date).days / 30.4
    why = []
    if not lead_fund_slowing:
        return False, ["lead's fund still deploying"]
    why.append("lead's fund has stopped deploying")
    if months < 15:
        return False, [f"last round only {months:.0f} months ago"]
    why.append(f"{months:.0f} months since last round")
    if headcount_growth is None:
        return False, why + ["headcount trend unknown — unknown is not zero"]
    if headcount_growth <= 0:
        return False, why + [f"headcount {headcount_growth:+.0%}, not growing"]
    why.append(f"headcount {headcount_growth:+.0%}")
    if not still_operating:
        return False, why + ["not operating"]
    return True, why
