"""Founder signal. Pure scoring over relationship counts - no API calls."""
from app import founder_signal as FS


def g(**rels):
    return [{"rel": k, "items": [{} for _ in range(v)]} for k, v in rels.items()]


def test_prior_founding_dominates_credentials():
    founder = FS.assess("A", g(FOUNDED=1, STUDIED_AT=1))
    scholar = FS.assess("B", g(STUDIED_AT=2, SPOKE_AT=3, RECEIVED_AWARD=3))
    assert founder.score > scholar.score


def test_a_second_company_adds_less_than_the_first():
    one = FS.assess("A", g(FOUNDED=1, WORKS_AT=1)).score
    two = FS.assess("A", g(FOUNDED=2, WORKS_AT=1)).score
    three = FS.assess("A", g(FOUNDED=3, WORKS_AT=1)).score
    assert two > one
    assert (three - two) < (two - one)      # saturating, not linear


def test_press_is_counted_but_never_scored():
    quiet = FS.assess("A", g(FOUNDED=1, WORKS_AT=1))
    loud = FS.assess("B", g(FOUNDED=1, WORKS_AT=1, FEATURED_IN=40))
    assert loud.score == quiet.score
    feat = [c for c in loud.components if c["rel"] == "FEATURED_IN"][0]
    assert feat["counted"] is False and feat["n"] == 40


def test_thin_people_are_unknown_not_weak():
    s = FS.assess("Nobody", g(STUDIED_AT=1))
    assert s.score is None and s.confidence == "Low"
    assert any("Unknown is not zero" in r for r in s.reasons)


def test_github_alone_is_enough_to_score():
    s = FS.assess("Builder", [], gh={"value": 0.8, "why": ["1200 stars"]})
    assert s.score is not None and s.score > 0


def test_github_lifts_an_otherwise_equal_person():
    base = FS.assess("A", g(FOUNDED=1, WORKS_AT=2))
    with_gh = FS.assess("A", g(FOUNDED=1, WORKS_AT=2), gh={"value": 0.9, "why": []})
    assert with_gh.score > base.score


def test_score_is_bounded():
    s = FS.assess("Everything", g(FOUNDED=9, IS_CEO_OF=9, WORKS_AT=9, INVESTED_IN=9,
                                  IS_MEMBER_OF=9, STUDIED_AT=9, SPOKE_AT=9,
                                  RECEIVED_AWARD=9), gh={"value": 1.0, "why": []})
    assert 0 < s.score <= 100


def test_confidence_reflects_visibility_not_score():
    thin = FS.assess("A", g(FOUNDED=1, STUDIED_AT=1))
    thick = FS.assess("B", g(FOUNDED=1, WORKS_AT=2, STUDIED_AT=1, IS_MEMBER_OF=1,
                             SPOKE_AT=2), gh={"value": 0.3, "why": []})
    assert thick.confidence == "High" and thin.confidence in {"Low", "Medium"}


# --- second-order weighting ---------------------------------------------------
def gi(rel, names, roles=None):
    return [{"rel": rel, "items": [{"name": n, "role": (roles or {}).get(n)} for n in names]}]


ROUNDS = {
    "rocketco": [{}, {}, {}],      # raised three times
    "okayco": [{}],                # raised once
    "deadco": [],                  # never raised
}


def test_founding_something_that_raised_beats_founding_something_that_did_not():
    hot = FS.assess("A", gi("FOUNDED", ["RocketCo"]) + g(STUDIED_AT=1),
                    rounds_by_company=ROUNDS)
    cold = FS.assess("B", gi("FOUNDED", ["DeadCo"]) + g(STUDIED_AT=1),
                     rounds_by_company=ROUNDS)
    assert hot.score > cold.score
    assert any("RocketCo raised more than once" in r for r in hot.reasons)


def test_unknown_companies_sit_between_raised_and_never_raised():
    base = g(STUDIED_AT=1)
    hot = FS.assess("A", gi("FOUNDED", ["RocketCo"]) + base, rounds_by_company=ROUNDS).score
    unk = FS.assess("B", gi("FOUNDED", ["WhoKnows"]) + base, rounds_by_company=ROUNDS).score
    cold = FS.assess("C", gi("FOUNDED", ["DeadCo"]) + base, rounds_by_company=ROUNDS).score
    assert cold < unk < hot


def test_senior_role_text_counts_for_more_than_any_job():
    boss = FS.assess("A", gi("WORKS_AT", ["X"], {"X": "CEO and co-founder"}) + g(STUDIED_AT=1))
    staff = FS.assess("B", gi("WORKS_AT", ["X"], {"X": "Software Engineer"}) + g(STUDIED_AT=1))
    assert boss.score > staff.score
    assert any("senior operating role" in r for r in boss.reasons)


def test_weighting_is_flagged_so_the_ui_can_say_so():
    s = FS.assess("A", gi("FOUNDED", ["RocketCo"]) + g(STUDIED_AT=1), rounds_by_company=ROUNDS)
    founded = [c for c in s.components if c["rel"] == "FOUNDED"][0]
    assert founded.get("weighted") is True


def test_without_round_data_scoring_is_unchanged():
    """No funding corpus must not silently penalise everyone."""
    a = FS.assess("A", gi("FOUNDED", ["RocketCo"]) + g(STUDIED_AT=1))
    b = FS.assess("B", gi("FOUNDED", ["DeadCo"]) + g(STUDIED_AT=1))
    assert a.score == b.score
