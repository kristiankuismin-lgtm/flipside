"""An ended seat with nothing since.

The graph records when roles end and nothing in the product read it. These
check the two things that make the signal mean anything: that a later start
cancels it, and that what was left is weighed rather than counted.
"""
from datetime import date

from app import departures as DP

TODAY = date(2026, 11, 15)


def person(name, seats_, pid="p1"):
    out = {}
    for kind, company, since, until, role in seats_:
        pr = {}
        if since:
            pr["valid_since"] = since
        if until:
            pr["valid_until"] = {"value": until, "sources": []}
        if role:
            pr["role"] = role
        out.setdefault(kind, []).append(
            {"id": company.lower(), "name": company, "properties": pr})
    return {"id": pid, "entity_type": "Person", "name": name,
            "relationships": {"outgoing": out}}


def idx(*people):
    return {p["id"]: p for p in people}


# ------------------------------------------------------------ the premise

def test_a_later_start_means_they_are_placed_not_deciding():
    p = person("A", [("IS_CEO_OF", "Old", "2018-01-01", "2026-01-01", None),
                     ("WORKS_AT", "New", "2026-03-01", None, None)])
    out = DP.find(idx(p), today=TODAY, queried=[])
    assert out["rows"] == []
    assert out["coverage"]["placed_since"] == 1


def test_an_ended_seat_with_nothing_since_is_the_cohort():
    p = person("A", [("IS_CEO_OF", "Old", "2018-01-01", "2026-09-01", None)])
    out = DP.find(idx(p), today=TODAY, queried=[])
    assert [r["person"] for r in out["rows"]] == ["A"]
    assert out["rows"][0]["company"] == "Old"


def test_somebody_with_no_end_date_is_not_in_it_at_all():
    p = person("A", [("WORKS_AT", "Still", "2020-01-01", None, None)])
    out = DP.find(idx(p), today=TODAY, queried=[])
    assert out["rows"] == [] and out["coverage"]["people_with_an_end_date"] == 0


def test_an_old_departure_falls_out_of_the_window():
    p = person("A", [("IS_CEO_OF", "Old", "2000-01-01", "2019-01-01", None)])
    assert DP.find(idx(p), today=TODAY, queried=[])["rows"] == []


# -------------------------------------------------------------- weighting

def test_leaving_what_you_founded_outranks_a_board_seat_lapsing():
    f = person("F", [("FOUNDED", "Mine", "2015-01-01", "2026-09-01", None)], "p1")
    b = person("B", [("IS_BOARD_MEMBER_OF", "Other", "2015-01-01",
                      "2026-09-01", None)], "p2")
    rows = {r["person"]: r for r in DP.find(idx(f, b), today=TODAY, queried=[])["rows"]}
    assert rows["F"]["score"] > rows["B"]["score"]


def test_a_recent_exit_outranks_an_older_one_of_the_same_kind():
    a = person("A", [("IS_CEO_OF", "X", "2015-01-01", "2026-10-01", None)], "p1")
    b = person("B", [("IS_CEO_OF", "Y", "2015-01-01", "2025-02-01", None)], "p2")
    rows = {r["person"]: r for r in DP.find(idx(a, b), today=TODAY, queried=[])["rows"]}
    assert rows["A"]["score"] > rows["B"]["score"]


def test_an_announced_future_departure_is_kept_and_labelled():
    """The earliest the signal can exist, so it is not filtered as a bad date."""
    p = person("A", [("IS_CEO_OF", "X", "2015-01-01", "2027-01-03", None)])
    r = DP.find(idx(p), today=TODAY, queried=[])["rows"][0]
    assert r["announced_only"] is True
    assert any("announced already" in w for w in r["why"])


def test_the_most_recent_end_is_the_one_reported():
    p = person("A", [("IS_BOARD_MEMBER_OF", "Early", "2010-01-01", "2024-01-01", None),
                     ("IS_CEO_OF", "Late", "2015-01-01", "2026-09-01", None)])
    assert DP.find(idx(p), today=TODAY, queried=[])["rows"][0]["company"] == "Late"


def test_every_row_says_what_it_was_selected_on():
    p = person("A", [("IS_CEO_OF", "X", "2015-01-01", "2026-09-01", "CHAIR")])
    r = DP.find(idx(p), today=TODAY, queried=[])["rows"][0]
    assert r["why"] and any("X" in w for w in r["why"])


def test_a_malformed_date_does_not_raise():
    p = person("A", [("IS_CEO_OF", "X", "2015-01-01", "not-a-date", None)])
    assert DP.find(idx(p), today=TODAY, queried=[])["rows"] == []


def test_a_company_without_a_name_is_not_a_seat():
    p = {"id": "p1", "entity_type": "Person", "name": "A",
         "relationships": {"outgoing": {"IS_CEO_OF": [
             {"id": "c", "name": "  ", "properties": {"valid_until": "2026-09-01"}}]}}}
    assert DP.find(idx(p), today=TODAY, queried=[])["rows"] == []


# ------------------------------------------- the half that was never edged

def test_a_queried_row_is_scored_below_an_edged_one(monkeypatch):
    """An edge carries a date; an answer carries a year. Both are kept and
    the weaker one says which it is."""
    rows = [
        {"person": "Queried", "person_id": None, "company": "X",
         "company_id": None, "kind": "IS_CEO_OF", "on": "2026",
         "announced_only": False, "score": 60.0,
         "why": ["left as chief executive X", "year only, from a Cala answer"],
         "other_seats": 0, "from_query": True}]
    p = person("Edged", [("IS_CEO_OF", "Y", "2015-01-01", "2026-09-01", None)])
    out = DP.find(idx(p), today=TODAY, queried=rows)
    assert [r["person"] for r in out["rows"]] == ["Edged", "Queried"]
    assert out["coverage"]["from_edges"] == 1
    assert out["coverage"]["from_queries"] == 1


def test_an_edged_person_is_not_listed_twice_by_a_query():
    rows = [
        {"person": "Edged", "person_id": None, "company": "X",
         "company_id": None, "kind": "IS_CEO_OF", "on": "2026",
         "announced_only": False, "score": 99.0, "why": ["x"],
         "other_seats": 0, "from_query": True}]
    p = person("Edged", [("IS_CEO_OF", "Y", "2015-01-01", "2026-09-01", None)])
    out = DP.find(idx(p), today=TODAY, queried=rows)
    assert len(out["rows"]) == 1 and out["coverage"]["from_queries"] == 0


def test_a_row_with_no_usable_year_is_dropped(monkeypatch):
    import app.bulk as B
    monkeypatch.setattr(B, "rows_of", lambda kind, limit=4000: [
        {"person": "A", "role": "CEO", "org": "X", "year": "recently"},
        {"person": "B", "role": "CEO", "org": "X", "year": "2026"}])
    got = DP.from_bulk(today=TODAY, months=30)
    assert [r["person"] for r in got] == ["B"]
