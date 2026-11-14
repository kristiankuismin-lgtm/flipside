"""Insider conviction. Pure scoring over round lists — no API calls."""
from datetime import timedelta
import pytest

from app import conviction as K
from app.models import Round

T = K.TODAY


def r(co, days_ago, stage, investors, leads=(), amount=None):
    return Round(company=co, date=T - timedelta(days=days_ago), stage=stage,
                 amount_eur=amount, investors=list(investors), leads=list(leads),
                 lead_is_native=True, sources=[])


def test_preemption_is_the_strongest_positive():
    """Insider-only, inside 12 months, at >=2x — the lead bought the round."""
    rs = [r("A", 500, "Seed", ["Lifeline", "Inventure"], ["Lifeline"], 3e6),
          r("A", 200, "Series A", ["Lifeline", "Inventure"], ["Lifeline"], 9e6)]
    c = K.assess("A", rs)
    assert c.structure == K.PREEMPTION
    assert c.previous_lead_returned is True
    assert c.score > 75


def test_bridge_is_penalised_even_when_everyone_returns():
    """Same insiders, but a smaller 'extension' two years later is bad news."""
    rs = [r("B", 1200, "Seed", ["Lifeline", "Inventure"], ["Lifeline"], 5e6),
          r("B", 100, "Seed Extension", ["Lifeline", "Inventure"], ["Lifeline"], 1e6)]
    c = K.assess("B", rs)
    assert c.structure == K.BRIDGE
    pre = K.assess("A", [r("A", 500, "Seed", ["Lifeline"], ["Lifeline"], 3e6),
                         r("A", 200, "Series A", ["Lifeline"], ["Lifeline"], 9e6)])
    assert c.score < pre.score


def test_previous_lead_absence_outweighs_headcount_of_followers():
    """Three small followers returning does not offset the lead walking away."""
    rs = [r("C", 900, "Seed", ["BigFund", "A1", "A2", "A3"], ["BigFund"]),
          r("C", 200, "Series A", ["A1", "A2", "A3", "NewLead"], ["NewLead"])]
    c = K.assess("C", rs, kinds={"bigfund": K.MULTISTAGE, "a1": K.ANGEL,
                                 "a2": K.ANGEL, "a3": K.ANGEL})
    assert c.previous_lead_returned is False
    assert any("did not return" in x for x in c.reasons)
    assert c.score < 50


def test_late_life_fund_absence_is_near_neutral():
    """A fund that stopped deploying explains its own absence."""
    rs = [r("D", 900, "Seed", ["TiredFund", "Active"], ["Active"]),
          r("D", 200, "Series A", ["Active", "New"], ["Active"])]
    harsh = K.assess("D", rs, kinds={"tiredfund": K.MULTISTAGE})
    kind = K.assess("D", rs, kinds={"tiredfund": K.MULTISTAGE}, slowing={"tiredfund"})
    assert kind.score > harsh.score
    assert any("fund has slowed" in x for x in kind.reasons)


def test_return_is_scored_against_the_investors_own_habit():
    """Returning when you usually don't is worth more than always returning."""
    rs = [r("E", 900, "Seed", ["Rare"], ["Rare"]),
          r("E", 200, "Series A", ["Rare"], ["Rare"])]
    rare = K.assess("E", rs, baselines={"rare": 0.20})
    always = K.assess("E", rs, baselines={"rare": 0.95})
    assert rare.score > always.score


def test_thin_evidence_cannot_outrank_thick():
    """1-of-1 insider must not beat 6-of-6. Shrinkage toward the pool mean."""
    thin = K.assess("thin", [r("thin", 900, "Seed", ["Solo"], ["Solo"]),
                             r("thin", 200, "Series A", ["Solo"], ["Solo"], 9e6)])
    many = ["I1", "I2", "I3", "I4", "I5", "I6"]
    thick = K.assess("thick", [r("thick", 900, "Seed", many, ["I1"]),
                               r("thick", 200, "Series A", many, ["I1"], 9e6)])
    assert thick.score > thin.score


def test_scores_do_not_saturate_at_100():
    """A perfect case must leave headroom, or the ranking carries no signal."""
    rs = [r("P", 500, "Seed", ["A", "B"], ["A"], 3e6),
          r("P", 200, "Series A", ["A", "B"], ["A"], 9e6)]
    assert K.assess("P", rs, baselines={"a": .1, "b": .1}).score < 100


def test_unknown_is_not_zero():
    """One round, or no prior investors, scores None — never a bad score."""
    assert K.assess("F", [r("F", 100, "Seed", ["X"])]).score is None
    two = [r("G", 500, "Seed", []), r("G", 100, "Series A", ["X"])]
    assert K.assess("G", two).score is None


def test_insider_only_without_amounts_is_not_guessed():
    """No amounts means we cannot tell pre-emption from bridge. Say unknown."""
    rs = [r("H", 500, "Seed", ["L"], ["L"]), r("H", 200, "Series A", ["L"], ["L"])]
    assert K.assess("H", rs).structure == K.UNKNOWN


def test_orphan_requires_every_condition():
    rs = [r("I", 600, "Seed", ["TiredLead"], ["TiredLead"])]
    ok, why = K.is_orphan("I", rs, headcount_growth=0.35, lead_fund_slowing=True)
    assert ok and any("headcount" in w for w in why)

    # Fund still deploying -> not an orphan, it is just a normal company
    assert not K.is_orphan("I", rs, 0.35, lead_fund_slowing=False)[0]
    # Too recent
    assert not K.is_orphan("I", [r("I", 200, "Seed", ["X"], ["X"])], 0.35, True)[0]
    # Unknown headcount is not treated as growth
    ok2, why2 = K.is_orphan("I", rs, headcount_growth=None, lead_fund_slowing=True)
    assert not ok2 and any("unknown is not zero" in w for w in why2)


def test_confidence_reflects_sample_and_known_habits():
    rs = [r("J", 900, "Seed", ["A", "B", "C", "D"], ["A"]),
          r("J", 200, "Series A", ["A", "B"], ["A"])]
    assert K.assess("J", rs).confidence in {"Medium", "High"}
    assert K.assess("J", rs, baselines={"a": .3, "b": .4}).confidence == "High"


# ---- recency: conviction is evidence about now ----
def test_recency_is_flat_inside_the_grace_year_then_decays():
    assert K.recency_factor(0) == 1.0
    assert K.recency_factor(12) == 1.0
    assert K.recency_factor(30) < K.recency_factor(18) < 1.0
    assert K.recency_factor(600) == K.RECENCY_FLOOR     # discounted, not erased


def test_unknown_age_is_not_punished():
    """We do not know the round is old, so we must not act as if we do."""
    assert K.recency_factor(None) == 1.0


def test_months_between_handles_partial_and_missing_dates():
    assert K.months_between("2022-01", "2026-11") == 58
    assert K.months_between("2026-09-15", "2026-11-02") == 2
    assert K.months_between(None, "2026-11") is None
    assert K.months_between("2026-11", "2022-01") == 0     # never negative


def _pair(co, old_days, new_days):
    return [r(co, old_days, "Series B", ["Ins A", "Ins B"], ["Ins A"]),
            r(co, new_days, "Series C", ["Ins A", "Ins B"], ["Ins A"])]


def test_a_stale_round_cannot_outrank_the_same_round_today():
    """The complaint that produced this: a 2022 Series C ranked #1 today."""
    old = K.assess("Old Co", _pair("Old Co", 2500, 1700))
    new = K.assess("New Co", _pair("New Co", 800, 60))
    assert old.score_fresh == new.score_fresh          # identical evidence
    assert old.score < new.score                       # but not identical weight
    assert old.stale is True and new.stale is False
    assert any("discounted" in x for x in old.reasons)


def test_the_undecayed_score_is_kept_for_display():
    c = K.assess("Old Co", _pair("Old Co", 2500, 1700))
    assert c.score_fresh > c.score
    assert c.months_since and c.months_since > 24
    assert 0 < c.recency < 1
