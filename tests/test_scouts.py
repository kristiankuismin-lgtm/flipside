"""Finding founders before they found again.

The ranking is an opinion with no backtest, which is exactly why each claim
it makes has to be traceable to an edge. These tests pin what each signal is
allowed to assert.
"""
from datetime import date

from app import scouts as S

TODAY = date(2026, 11, 15)


def person(name="A Person", **rels):
    return {"id": name.lower().replace(" ", "-"), "name": name,
            "entity_type": "Person", "properties": {},
            "relationships": {"outgoing": rels}}


def co(name, **props):
    return {"id": name.lower(), "name": name, "entity_type": "Company",
            "properties": props}


# ------------------------------------------------------ who is a candidate
def test_someone_who_has_never_built_anything_is_not_a_candidate():
    assert S.build(person(STUDIED_AT=[co("Aalto")], RECEIVED_AWARD=[co("A prize")]),
                   today=TODAY) is None


def test_having_founded_once_is_enough_to_be_on_the_list():
    c = S.build(person(FOUNDED=[co("Firstthing")]), today=TODAY)
    assert c is not None and c["score"] >= S.WEIGHTS["founded"]


def test_having_only_run_something_is_a_weaker_claim():
    ran = S.build(person(IS_CEO_OF=[co("Bigco")]), today=TODAY)["score"]
    made = S.build(person(FOUNDED=[co("Firstthing")]), today=TODAY)["score"]
    assert ran < made


# ------------------------------------------------------------- the signals
def test_a_serial_founder_outranks_a_first_timer():
    one = S.build(person(FOUNDED=[co("A")]), today=TODAY)["score"]
    two = S.build(person(FOUNDED=[co("A"), co("B")]), today=TODAY)["score"]
    assert two > one


def test_serial_founding_saturates():
    many = S.build(person(FOUNDED=[co(f"C{i}") for i in range(20)]), today=TODAY)
    full = S.build(person(FOUNDED=[co(f"C{i}") for i in range(S.SERIAL_FULL)]), today=TODAY)
    assert many["score"] == full["score"]


def test_every_point_scored_says_why():
    c = S.build(person(FOUNDED=[co("A"), co("B")],
                       INVESTED_IN=[co("X")],
                       WORKS_AT=[co("Bigco", valid_since="2020-01-01")]), today=TODAY)
    assert any("founded" in w for w in c["why"])
    assert any("companies founded" in w for w in c["why"])
    assert any("invests personally" in w for w in c["why"])
    assert any("years in the current seat" in w for w in c["why"])


# --------------------------------------------------------------- tenure
def test_tenure_rises_to_a_peak_and_then_holds():
    """We have no backtest for the shape of this, so it must not claim a
    cliff - a twenty-year veteran is not scored below a six-year one."""
    assert S.tenure_points(3) < S.tenure_points(S.TENURE_PEAK)
    assert S.tenure_points(20) == S.tenure_points(S.TENURE_PEAK)


def test_no_dated_role_scores_no_tenure_rather_than_zero_years():
    assert S.tenure_points(None) == 0.0
    c = S.build(person(FOUNDED=[co("A")], WORKS_AT=[co("Bigco")]), today=TODAY)
    assert c["years_in_seat"] is None
    assert not any("seat" in w for w in c["why"])


def test_a_future_start_date_is_ignored():
    c = S.build(person(FOUNDED=[co("A")],
                       WORKS_AT=[co("Bigco", valid_since="2099-01-01")]), today=TODAY)
    assert c["years_in_seat"] is None


def test_the_earliest_dated_role_is_the_one_counted():
    c = S.build(person(FOUNDED=[co("A")],
                       WORKS_AT=[co("Bigco", valid_since="2018-01-01"),
                                 co("Bigco", valid_since="2024-01-01")]), today=TODAY)
    assert c["years_in_seat"] == 8


# ----------------------------------------------------------- the thesis
def test_a_thesis_match_is_flagged():
    c = S.build(person(FOUNDED=[co("A health diagnostics company")]),
                thesis_markets={"health"}, today=TODAY)
    assert c["match"] == ["health"]


def test_a_thesis_match_outranks_a_higher_score_without_one():
    strong = person("Strong", FOUNDED=[co("A"), co("B"), co("C")],
                    INVESTED_IN=[co("X")])
    weak = person("Weak", FOUNDED=[co("A clinical health company")])
    out = S.rank([strong, weak], thesis="digital health", today=TODAY)
    assert out["candidates"][0]["name"] == "Weak"
    assert out["coverage"]["matched_thesis"] == 1


# --------------------------------------------------------------- triggers
def test_every_candidate_says_what_would_change():
    c = S.build(person(FOUNDED=[co("A")], WORKS_AT=[co("Bigco")]), today=TODAY)
    assert "a FOUNDED edge appears on their record" in c["watch_for"]
    assert any("leave Bigco" in t for t in c["watch_for"])


def test_the_same_person_under_two_entities_is_one_row():
    a = person("Naval Ravikant", FOUNDED=[co("AngelList")])
    b = dict(a, id="other")
    assert len(S.rank([a, b], today=TODAY)["candidates"]) == 1


def test_coverage_counts_what_it_read():
    people = [person("A", FOUNDED=[co("X")]),
              person("B", STUDIED_AT=[co("Aalto")]),
              {"id": "c", "name": "C", "entity_type": "Person",
               "properties": {}, "relationships": {}}]
    cov = S.rank(people, today=TODAY)["coverage"]
    assert cov["people_with_edges"] == 2 and cov["candidates"] == 1


def test_founding_a_fund_is_not_founding_a_company():
    """Mattias Ljungman founded Atomico and Moonfire. That makes him a
    co-investor, not a lead for a list of people who might start something."""
    # Atomico has no fund-ish word in its name; the graph settles it.
    atomico = {"id": "atomico", "relationships": {"outgoing": {
        "INVESTED_IN": [co("A"), co("B"), co("C")]}}}
    c = S.build(person("Mattias", FOUNDED=[co("Atomico"), co("Moonfire Ventures")]),
                company_lookup=lambda k: atomico if k == "atomico" else None,
                today=TODAY)
    assert c is None or c["founded"] == []
    if c:
        assert [f["name"] for f in c["founded_firms"]] == ["Atomico", "Moonfire Ventures"]


def test_a_company_founder_who_also_started_a_fund_keeps_the_company():
    c = S.build(person("A", FOUNDED=[co("Unity Technologies"), co("Some Capital")]),
                company_lookup=lambda k: None, today=TODAY)
    assert [f["name"] for f in c["founded"]] == ["Unity Technologies"]
    assert [f["name"] for f in c["founded_firms"]] == ["Some Capital"]


def test_a_broad_market_match_is_not_a_specific_one():
    """Nearly every technology description contains "platform"."""
    c = S.build(person(FOUNDED=[co("A software platform company")]),
                thesis_markets={"software"}, today=TODAY)
    assert c["match"] == ["software"] and c["match_specific"] == []


def test_a_specific_match_outranks_a_broad_one():
    broad = person("Broad", FOUNDED=[co("A software platform"), co("B platform"),
                                     co("C platform")])
    exact = person("Exact", FOUNDED=[co("A clinical patient records company")])
    out = S.rank([broad, exact], thesis="clinical software", today=TODAY)
    assert out["candidates"][0]["name"] == "Exact"
    assert out["coverage"]["matched_specifically"] == 1


def test_a_startup_that_made_one_investment_is_still_a_startup():
    """Plenty of operating companies have made an investment. Two is the
    bar, because one does not make you a fund."""
    angel_ish = {"id": "unity", "relationships": {"outgoing": {
        "INVESTED_IN": [co("A")]}}}
    c = S.build(person("A", FOUNDED=[co("Unity Technologies")]),
                company_lookup=lambda k: angel_ish, today=TODAY)
    assert [f["name"] for f in c["founded"]] == ["Unity Technologies"]
