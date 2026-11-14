"""What a founder can learn about the person they are about to call."""
from datetime import date

from app import person as P


def E(**rels):
    out = {"id": "p1", "name": "Sabina Partner", "description": "Partner at a VC.",
           "properties": {"linkedin_url": {"value": "https://li/sw"}},
           "relationships": {"outgoing": {}}}
    for k, v in rels.items():
        out["relationships"]["outgoing"][k] = v
    return out


def item(name, **props):
    return {"id": name.lower(), "name": name,
            "properties": {k: {"value": v} for k, v in props.items()}}


def test_founding_year_becomes_years_building():
    c = P.build(E(FOUNDED=[item("Supercell", valid_since="2010-01-01")]),
                today=date(2026, 11, 14))
    assert c["operator"]["building_since"] == 2010
    assert c["operator"]["years_building"] == 16


def test_the_earliest_operating_role_counts_too():
    c = P.build(E(IS_CEO_OF=[item("Early Co", valid_since="2005-06-01")],
                  FOUNDED=[item("Later Co", valid_since="2018-01-01")]),
                today=date(2026, 1, 1))
    assert c["operator"]["building_since"] == 2005


def test_someone_who_has_never_operated_says_so_rather_than_zero():
    c = P.build(E())
    assert c["operator"]["founded"] == [] and c["operator"]["years_building"] is None


def test_boards_and_personal_cheques_are_one_intro_surface():
    c = P.build(E(IS_MEMBER_OF=[item("Linear")],
                  INVESTED_IN=[item("Revyze"), item("Arctic Security")]))
    assert c["network"]["count"] == 3
    assert c["network"]["boards"] == 1 and c["network"]["personal_cheques"] == 2


def test_the_same_company_on_a_board_and_in_a_cheque_is_one_door():
    c = P.build(E(IS_MEMBER_OF=[item("Linear")], INVESTED_IN=[item("linear")]))
    assert c["network"]["count"] == 1 and c["network"]["boards"] == 1


def test_markets_are_compared_not_words():
    """A founder writing "clinical documentation for doctors" and a company
    described as a "digital health care provider" share no word at all."""
    assert P.markets_in("digital health care provider") == {"health"}
    assert "health" in P.markets_in("clinical documentation for doctors")
    # A payments-infrastructure company is genuinely both, and overlapping
    # markets are a feature: it widens what can match, never narrows it.
    assert "fintech" in P.markets_in("payment infrastructure for banks")


def test_domain_matches_through_anything_they_have_touched():
    c = P.build(E(IS_CSO_OF=[item("Kry International")],
                  INVESTED_IN=[item("Some Clinic Co")]),
                sector_words={"clinical", "doctors", "hospitals"})
    assert c["domain"]["wanted"] == ["health"]
    assert "health" in c["domain"]["matched"]      # via the clinic in the name


def test_a_different_market_does_not_match():
    c = P.build(E(INVESTED_IN=[item("Payment Rails Oy")]),
                sector_words={"clinical", "doctors"})
    assert c["domain"]["matched"] == []
    assert c["domain"]["markets"] == ["fintech"]


def test_the_legal_gap_is_stated_not_implied():
    """No record is not a clean record, and a reader will assume we checked."""
    c = P.build(E())
    assert "no record" in c["unchecked"]["legal"]
    assert "SANCTIONED_BY" in c["unchecked"]["edges_we_looked_for"]


def test_confidence_scores_our_evidence_not_the_person():
    thin = P.confidence(P.build({"id": "x", "name": "Unknown", "properties": {},
                                 "relationships": {}}))
    assert thin["label"] == "Low" and thin["known"] == 0

    full = P.confidence(P.build(E(
        FOUNDED=[item("Co", valid_since="2012-01-01")],
        IS_MEMBER_OF=[item("Board Co")],
        WORKS_AT=[item("The Fund", role="Partner")],
        INVESTED_IN=[item("Clinical Thing")]), sector_words={"clinical"}))
    assert full["label"] == "High" and full["known"] == 5
