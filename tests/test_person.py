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


def test_enrich_markets_matches_through_a_fetched_description():
    """"Kry International AB" says nothing; its description says health."""
    c = P.build(E(IS_CSO_OF=[item("Kry International AB")]),
                sector_words={"clinical", "doctors"})
    assert c["domain"]["matched"] == []
    c = P.enrich_markets(c, lambda _id: "Swedish digital health care provider")
    assert c["domain"]["matched"] == ["health"]
    assert c["domain"]["via"][0]["name"] == "Kry International AB"


def test_enrich_markets_is_a_no_op_when_no_market_was_asked_for():
    c = P.build(E(INVESTED_IN=[item("Anything")]))
    before = dict(c["domain"])
    assert P.enrich_markets(c, lambda _id: "health care")["domain"] == before


def test_a_company_that_cannot_be_fetched_is_skipped_not_fatal():
    c = P.build(E(INVESTED_IN=[item("Broken")]), sector_words={"clinical"})
    def boom(_id):
        raise RuntimeError("no")
    assert P.enrich_markets(c, boom)["domain"]["matched"] == []


# ------------------------------------------------ does this person angel?
def _p(**rels):
    return {"id": "x", "name": "A Person", "entity_type": "Person",
            "properties": {}, "relationships": {"outgoing": rels}}


def _co(name, **props):
    return {"id": name.lower(), "name": name, "entity_type": "Company",
            "properties": props}


def test_a_partner_who_has_never_invested_personally_is_not_an_angel():
    card = P.build(_p(WORKS_AT=[_co("Creandum", role="Partner")]))
    assert card["angel"]["is_angel"] is False
    assert card["angel"]["round_count"] == 0


def test_personal_rounds_make_someone_an_angel():
    """A partner who has put their own money in has decided alone before."""
    card = P.build(_p(PARTICIPATES_IN_FUNDING_ROUND=[
        _co("Seed round", event_date="2024-03-01"),
        _co("Series A", event_date="2025-06-02")]))
    a = card["angel"]
    assert a["is_angel"] and a["round_count"] == 2
    assert a["last_year"] == "2025"
    assert a["active_years"] == ["2024", "2025"]


def test_personal_cheques_count_even_with_no_dated_rounds():
    card = P.build(_p(INVESTED_IN=[_co("Wolt"), _co("Oura")]))
    a = card["angel"]
    assert a["is_angel"] and a["company_count"] == 2
    assert set(a["companies"]) == {"Wolt", "Oura"}
    assert a["last_year"] is None          # no dates, and we do not invent one


def test_a_title_held_in_the_graph_is_kept_with_its_start_date():
    """A scraped page says "Partner". This says it with a date behind it."""
    card = P.build(_p(IS_GENERAL_PARTNER_OF=[
        _co("Northzone", valid_since="2018-01-01")]))
    t = card["titles"][0]
    assert t["title"] == "General Partner" and t["name"] == "Northzone"
    assert t["since"] == "2018-01-01"


def test_titles_are_ordered_strongest_first():
    card = P.build(_p(IS_VICEPRESIDENT_OF=[_co("B")],
                       IS_GENERAL_PARTNER_OF=[_co("A")]))
    assert [t["title"] for t in card["titles"]] == ["General Partner", "Vice President"]


# ------------------------- one company, one row; founding is not a seat
def _E(**rels):
    return {"id": "p", "name": "P", "properties": {},
            "relationships": {"outgoing": rels}}


def _it(n, **props):
    return {"id": n.lower(), "name": n, "entity_type": "Company", "properties": props}


def test_a_company_founded_and_run_is_one_row():
    """Gustav Soderstrom's card listed Kenet Works twice."""
    c = P.build(_E(FOUNDED=[_it("Kenet Works")],
                   IS_CEO_OF=[_it("Kenet Works", valid_since="2003-01-01")]))
    assert [x["name"] for x in c["operator"]["founded"]] == ["Kenet Works"]
    assert c["operator"]["operated"] == []
    assert c["operator"]["founded"][0]["roles"] == ["ceo"]


def test_a_role_at_a_company_they_did_not_found_is_not_under_founded():
    """He became co-CEO of a twenty-year-old Spotify. He did not build it."""
    c = P.build(_E(FOUNDED=[_it("13th Lab")],
                   IS_CEO_OF=[_it("Spotify AB", valid_since="2026-01-01")]))
    assert [x["name"] for x in c["operator"]["founded"]] == ["13th Lab"]
    assert [x["name"] for x in c["operator"]["operated"]] == ["Spotify AB"]


def test_a_company_whose_whole_name_is_a_legal_suffix_still_gets_a_row():
    """norm.name("Co") is empty, and the row vanished with the key."""
    c = P.build(_E(FOUNDED=[_it("Co")]))
    assert [x["name"] for x in c["operator"]["founded"]] == ["Co"]


def test_the_timeline_is_newest_first_and_only_dated_roles():
    c = P.build(_E(FOUNDED=[_it("Early", valid_since="2003-01-01")],
                   IS_CEO_OF=[_it("Later", valid_since="2019-01-01"),
                              _it("Undated")]))
    assert [x["name"] for x in c["timeline"]] == ["Later", "Early"]


def test_not_checked_is_not_the_same_as_no():
    """The card showed "no" under the words "not checked"."""
    unchecked = P.build(_E(FOUNDED=[_it("Health Clinic Co")]))
    assert unchecked["domain"]["checked"] is False
    checked = P.build(_E(FOUNDED=[_it("A gaming studio")]), sector_words={"clinical"})
    assert checked["domain"]["checked"] is True and checked["domain"]["matched"] == []


def test_the_headline_role_is_one_they_founded_not_one_they_left():
    """Josefin Landgard, co-founder of KRY, was introduced as "Head of
    Client Relations + Marketing, Videoplaza" because works_at comes back in
    id order."""
    c = P.build(_E(
        FOUNDED=[_it("MANTLE", valid_since="2020-01-01")],
        WORKS_AT=[_it("Videoplaza", role="Head of Client Relations + Marketing"),
                  _it("MANTLE", role="Founder & CEO")]))
    assert c["headline_role"]["name"] == "MANTLE"


def test_seniority_decides_when_they_founded_none_of_them():
    c = P.build(_E(WORKS_AT=[_it("Acme", role="Analyst"),
                             _it("Bigco", role="Chief Executive Officer")]))
    assert c["headline_role"]["name"] == "Bigco"


def test_a_person_with_no_roles_has_no_headline():
    assert P.build(_E(FOUNDED=[_it("Thing")]))["headline_role"] is None
