"""People who just changed seats.

Every assertion here is a claim the investor side would make out loud, and
three of them exist because the first version of this would have made a
claim the data does not support: Cala dates Gustav Soderstrom at Spotify AB
from 2026, which is a role field, not a founding.
"""
from datetime import date

from app import moves as M

TODAY = date(2026, 11, 15)


def person(name="A Founder", **rels):
    return {"id": "p1", "name": name, "entity_type": "Person",
            "properties": {}, "relationships": {"outgoing": rels}}


def co(name, **props):
    return {"id": name.lower(), "name": name, "entity_type": "Company",
            "properties": props}


# ------------------------------------------------------------- dates
def test_a_start_date_in_the_future_is_a_bad_record_not_news():
    """Spotify AB was not founded in 2026, and reporting it as a move
    would be our error, not Cala's."""
    assert M.months_between("2027-01-01", TODAY) is None


def test_a_year_only_date_still_counts():
    assert M.months_between("2026", TODAY) == 10


def test_an_undatable_role_is_not_a_move():
    assert M.months_between(None, TODAY) is None
    assert M.months_between("recently", TODAY) is None


def test_an_undated_founding_is_not_reported():
    """Without a date there is no "just" in "just founded"."""
    assert M.moves(person(FOUNDED=[co("Newthing")]), today=TODAY) == []


def test_a_founding_older_than_the_window_is_not_a_move():
    assert M.moves(person(FOUNDED=[co("Oldthing", valid_since="2015-01-01")]),
                   today=TODAY) == []


# --------------------------------------------------------- new venture
def test_a_recent_founding_with_no_rounds_is_the_lead():
    m = M.moves(person(FOUNDED=[co("Newthing", valid_since="2026-06-01")]),
                today=TODAY)[0]
    assert m["kind"] == "new_venture"
    assert m["company"] == "Newthing" and m["months_ago"] == 5
    assert m["rounds"] == 0 and m["why"] == "has not raised on record"


def test_a_recent_founding_that_has_already_raised_says_so():
    m = M.moves(person(FOUNDED=[co("Newthing", valid_since="2026-06-01")]),
                rounds_by_company={"newthing": [{"stage": "Seed"}]},
                today=TODAY)[0]
    assert m["rounds"] == 1 and "already on record" in m["why"]


def test_a_company_that_says_it_is_in_stealth_is_flagged():
    m = M.moves(person(FOUNDED=[co("Stealth Co", valid_since="2026-09-01")]),
                today=TODAY)[0]
    assert m["stealth"] is True


def test_an_ordinary_company_is_not_flagged_as_stealth():
    m = M.moves(person(FOUNDED=[co("Newthing", valid_since="2026-09-01")]),
                today=TODAY)[0]
    assert m["stealth"] is False


# ------------------------------------------------------------ new seat
def test_founding_a_fund_is_a_seat_change_not_a_startup():
    """A partner starting their own vehicle has not gone building."""
    m = M.moves(person(FOUNDED=[co("Always Summer Asset Management",
                                   valid_since="2026-02-01")]), today=TODAY)[0]
    assert m["kind"] == "new_seat" and m["why"] == "started their own firm"


def test_recently_joining_a_firm_is_a_seat_change():
    m = M.moves(person(WORKS_AT=[co("Creandum", valid_since="2026-01-01",
                                    role="Partner")]), today=TODAY)[0]
    assert m["kind"] == "new_seat" and m["role"] == "Partner"


def test_the_same_company_is_not_reported_twice():
    p = person(FOUNDED=[co("Newthing", valid_since="2026-06-01")],
               IS_CEO_OF=[co("Newthing", valid_since="2026-06-01")],
               WORKS_AT=[co("Newthing", valid_since="2026-06-01")])
    assert len({m["company"] for m in M.moves(p, today=TODAY)}) == 1


def test_moves_are_newest_first():
    p = person(FOUNDED=[co("Older", valid_since="2025-10-01"),
                        co("Newer", valid_since="2026-09-01")])
    assert [m["company"] for m in M.moves(p, today=TODAY)] == ["Newer", "Older"]


# ------------------------------------------------------------ coverage
def test_scan_reports_how_little_it_could_see():
    """Two rows out of a hundred people is not an answer, and the number of
    people we could not date has to travel with it."""
    people = [person("A", FOUNDED=[co("Newthing", valid_since="2026-06-01")]),
              person("B", FOUNDED=[co("Undated")]),
              {"id": "c", "name": "C", "entity_type": "Person",
               "properties": {}, "relationships": {}}]
    out = M.scan(people, today=TODAY)
    c = out["coverage"]
    assert c["people_with_edges"] == 2        # C has no edges at all
    assert c["people_with_a_dated_role"] == 1
    assert c["ventures_found"] == 1


# ------------------------- a role at an old company is not a founding
def test_a_role_at_a_company_that_already_existed_is_a_seat():
    """Cala dates Gustav Soderstrom at Spotify AB from 2026. Spotify was
    founded in 2006, so the date is when a role began."""
    spotify = {"id": "spotify ab", "name": "Spotify AB",
               "properties": {"founding_date": {"value": "2006-04-23"}}}
    m = M.moves(person("Gustav", FOUNDED=[co("Spotify AB", valid_since="2026-01-01")]),
                company_lookup=lambda k: spotify, today=TODAY)[0]
    assert m["kind"] == "new_seat"
    assert "older than this role" in m["why"]


def test_a_genuinely_new_company_survives_the_check():
    newco = {"id": "newthing", "name": "Newthing",
             "properties": {"founding_date": {"value": "2026-05-01"}}}
    m = M.moves(person("A", FOUNDED=[co("Newthing", valid_since="2026-06-01")]),
                company_lookup=lambda k: newco, today=TODAY)[0]
    assert m["kind"] == "new_venture"


def test_no_founding_date_means_the_check_cannot_object():
    """Absence of a founding date is not evidence the company is old."""
    m = M.moves(person("A", FOUNDED=[co("Newthing", valid_since="2026-06-01")]),
                company_lookup=lambda k: {"id": "x", "properties": {}},
                today=TODAY)[0]
    assert m["kind"] == "new_venture"


def test_the_same_move_under_two_person_entities_is_one_row():
    """Cala holds some people twice; the move is still one move."""
    a = person("Sabina Wizander", FOUNDED=[co("Always Summer Asset Management",
                                              valid_since="2026-04-01")])
    b = dict(a, id="p2")
    out = M.scan([a, b], today=TODAY)
    assert len(out["moves"]) == 1


def test_becoming_chief_executive_of_an_existing_company_is_a_seat():
    """Cala has Gustav Soderstrom as IS_CEO_OF Spotify AB from 2026. True,
    and a promotion - treating it as a founding made it a lead."""
    m = M.moves(person("Gustav", IS_CEO_OF=[co("Spotify AB", valid_since="2026-01-01")]),
                today=TODAY)[0]
    assert m["kind"] == "new_seat"


def test_only_a_founding_edge_can_make_a_new_venture():
    assert M.FOUNDER_EDGES == ["FOUNDED"]
