"""The handoff graph. Pure computation over round lists."""
from app import pipeline as P


def R(date, investors, leads=()):
    return {"date": date, "investors": list(investors), "leads": list(leads)}


CORPUS = {
    "A": [R("2020-01", ["Seedy"]), R("2022-01", ["Seedy", "BigFund"], ["BigFund"])],
    "B": [R("2020-06", ["Seedy"]), R("2022-06", ["Seedy", "BigFund"], ["BigFund"])],
    "C": [R("2021-01", ["Seedy"]), R("2023-01", ["Other"], ["Other"])],
    "D": [R("2021-01", ["Lonely"]), R("2023-01", ["Lonely"], [])],   # no lead named
}
G = P.build(CORPUS)


def test_handoffs_point_at_the_next_rounds_lead():
    w = P.where_it_takes_you(G, "Seedy")
    assert w["observations"] == 3
    assert w["next_leads"][0]["name"] == "BigFund" and w["next_leads"][0]["count"] == 2


def test_a_round_with_no_named_lead_contributes_nothing():
    assert P.where_it_takes_you(G, "Lonely")["observations"] == 0


def test_a_fund_never_hands_off_to_itself():
    assert all(r["name"] != "BigFund"
               for r in P.where_it_takes_you(G, "BigFund")["next_leads"])


def test_thin_patterns_are_flagged_not_hidden():
    assert P.where_it_takes_you(G, "Lonely")["enough"] is False
    assert P.where_it_takes_you(G, "Seedy")["enough"] is True


def test_concentration_separates_one_path_from_many():
    narrow = P.build({"X": [R("2020-01", ["Narrow"]), R("2021-01", ["Narrow", "Lead One"], ["Lead One"])],
                      "Y": [R("2020-01", ["Narrow"]), R("2021-01", ["Narrow", "Lead One"], ["Lead One"])]})
    wide = P.build({"X": [R("2020-01", ["Wide"]), R("2021-01", ["Wide", "Lead One"], ["Lead One"])],
                    "Y": [R("2020-01", ["Wide"]), R("2021-01", ["Wide", "Lead Two"], ["Lead Two"])]})
    assert P.where_it_takes_you(narrow, "Narrow")["concentration"] == 1.0
    assert P.where_it_takes_you(wide, "Wide")["concentration"] == 0.5


def test_names_shorter_than_three_characters_are_dropped():
    """Single letters are noise in investor lists, not funds."""
    g = P.build({"X": [R("2020-01", ["A"]), R("2021-01", ["A", "Real Fund"], ["Real Fund"])]})
    assert P.where_it_takes_you(g, "A")["observations"] == 0


def test_the_reverse_direction_works():
    r = P.who_leads_into(G, "BigFund")
    assert r["from"][0]["name"] == "Seedy" and r["from"][0]["count"] == 2


def test_co_investors_exclude_the_fund_itself():
    names = [c["name"] for c in P.co_investors(G, "Seedy")]
    assert "Seedy" not in names and "BigFund" in names


def test_name_variants_are_one_fund():
    g = P.build({"X": [R("2020-01", ["Index Ventures LLP"]),
                       R("2021-01", ["index ventures"], ["Accel"])]})
    assert P.where_it_takes_you(g, "Index Ventures")["observations"] == 1
