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


# --- syndicates and warm paths ------------------------------------------------
SYN = P.build({
    "A": [R("2021-01", ["Big Lead", "Follower One", "Follower Two"], ["Big Lead"])],
    "B": [R("2021-06", ["Big Lead", "Follower One"], ["Big Lead"])],
    "C": [R("2022-01", ["Big Lead", "Follower One", "Follower Two"], ["Big Lead"])],
    # Near Fund shares cap tables with Big Lead but never joins a round it leads
    "D": [R("2022-06", ["Near Fund", "Big Lead"], ["Near Fund"])],
    "E": [R("2023-01", ["Voima Ventures", "Big Lead"], ["Big Lead"])],
})


def test_syndicate_picks_who_joins_rounds_this_fund_leads():
    s = P.syndicate(SYN, "Big Lead")
    names = [m["name"] for m in s["members"]]
    assert s["rounds_led"] == 4 and s["enough"] is True
    assert names[0] == "Follower One"          # 3 of 4 led rounds
    assert s["members"][0]["joined"] == 3


def test_a_fund_that_only_shares_cap_tables_is_not_a_syndicate_member():
    """Near Fund co-invests with Big Lead but never follows its lead."""
    s = P.syndicate(SYN, "Big Lead", size=3)
    assert "Near Fund" not in [m["name"] for m in s["members"]]


def test_existing_backers_can_be_excluded():
    s = P.syndicate(SYN, "Big Lead", exclude={"Follower One"})
    assert "Follower One" not in [m["name"] for m in s["members"]]


def test_a_fund_that_has_barely_led_is_flagged():
    thin = P.build({"X": [R("2021-01", ["Quiet Fund", "Someone Else"], ["Quiet Fund"])]})
    assert P.syndicate(thin, "Quiet Fund")["enough"] is False


def test_warm_path_names_the_company_that_connects_them():
    rbc = {"E": [R("2023-01", ["Voima Ventures", "Big Lead"], ["Big Lead"])]}
    paths = P.warm_path(SYN, ["Voima Ventures"], "Big Lead", rbc)
    assert len(paths) == 1
    assert paths[0]["via"] == "Voima Ventures"
    assert paths[0]["through"][0]["company"] == "E"


def test_no_shared_company_means_no_path():
    rbc = {"Z": [R("2023-01", ["Someone", "Another"], ["Someone"])]}
    assert P.warm_path(SYN, ["Voima Ventures"], "Big Lead", rbc) == []


def test_a_fund_is_not_a_route_to_itself():
    rbc = {"E": [R("2023-01", ["Big Lead"], ["Big Lead"])]}
    assert P.warm_path(SYN, ["Big Lead"], "Big Lead", rbc) == []


def test_angels_are_not_syndicate_members():
    """An angel is a real investor but not a fund a founder can assemble."""
    from app.pipeline import looks_like_a_fund as f
    assert f("Index Ventures") and f("Coparion") and f("Picus Capital")
    assert f("Supercell Oy") and f("Y Combinator")
    assert not f("Christian Grobe (co-founder of Billie)")
    assert not f("Ilkka Paananen")
    assert not f("Niklas Zennstrom")
    assert f("Follower One")   # a shape rule would wrongly call this a person
    assert not f("Kai-Uwe Mokros (MD of Zalando Payments)")
    assert not f("Jane Doe (Head of Product)")
    assert not f("Dr. Hans Mueller")
    assert not f("Philippe Teixeira da Mota")   # particle, not a fourth name


def test_syndicate_members_exclude_people():
    g = P.build({"A": [R("2021-01", ["Big Lead", "Real Capital", "Jane Smith"], ["Big Lead"])],
                 "B": [R("2021-06", ["Big Lead", "Real Capital", "Jane Smith"], ["Big Lead"])]})
    names = [m["name"] for m in P.syndicate(g, "Big Lead", size=3)["members"]]
    assert "Real Capital" in names and "Jane Smith" not in names


def test_follow_rounds_shows_the_denominator_not_just_the_hits():
    """"2 of 8" cannot be read unless the other six are on screen."""
    rbc = {
        "A": [{"date": "2025-01", "stage": "Series A",
               "investors": ["Big Lead", "Follower"], "leads": ["Big Lead"]}],
        "B": [{"date": "2024-06", "stage": "Series A",
               "investors": ["Big Lead", "Someone Else"], "leads": ["Big Lead"]}],
        "C": [{"date": "2024-01", "stage": "Seed",
               "investors": ["Other Fund", "Follower"], "leads": ["Other Fund"]}],
    }
    got = P.follow_rounds(rbc, "Big Lead", "Follower")
    assert [g["company"] for g in got] == ["A", "B"]      # only rounds the lead led
    assert [g["joined"] for g in got] == [True, False]    # newest first, both shown


def test_shared_rounds_is_the_evidence_for_a_warm_route():
    rbc = {"A": [{"date": "2025-01", "stage": "Series A",
                  "investors": ["Voima Ventures", "Target Fund"], "leads": []}],
           "B": [{"date": "2024-01", "stage": "Seed",
                  "investors": ["Voima Ventures"], "leads": []}]}
    got = P.shared_rounds(rbc, "Voima Ventures", "Target Fund")
    assert [g["company"] for g in got] == ["A"]


def test_name_spelling_does_not_hide_a_round():
    rbc = {"A": [{"date": "2025-01", "stage": "Series A",
                  "investors": ["EQT Ventures AB", "Follower Oy"], "leads": ["EQT Ventures"]}]}
    assert P.follow_rounds(rbc, "EQT Ventures", "Follower")[0]["joined"] is True
