"""Exit detection. No network: graph payloads are supplied directly."""
from datetime import date
import app.exits as X
import app.cala_client as cala

EVENT = {
    "properties": {
        "event_type": {"value": "MNA_COMPLETED"},
        "event_date": {"value": "2022-05-31", "sources": [
            {"source_rank": "FILING", "document": "https://sec.gov/x"}]},
        "description": {"value": "DoorDash acquired Wolt."},
    },
    "relationships": {"incoming": {X.EVENT_REL: [
        {"name": "Wolt", "properties": {"role": "TARGET"}},
        {"name": "DoorDash", "properties": {"role": "ACQUIRER"}},
    ]}},
}


def company(events):
    return {"relationships": {"outgoing": {X.EVENT_REL: events}}}


def test_a_completed_acquisition_is_read_end_to_end(monkeypatch):
    monkeypatch.setattr(cala, "get_entity", lambda eid, **k:
                        company([{"id": "ev1", "name": "MNA_COMPLETED",
                                  "entity_type": "CorporateEvent",
                                  "properties": {"role": "TARGET"}}])
                        if eid == "c1" else EVENT)
    xs = X.company_exits("c1", "Wolt")
    assert len(xs) == 1
    x = xs[0]
    assert x.company == "Wolt" and x.acquirer == "DoorDash"
    assert x.date == date(2022, 5, 31) and x.source == "https://sec.gov/x"


def test_being_the_acquirer_is_not_your_own_exit(monkeypatch):
    monkeypatch.setattr(cala, "get_entity", lambda eid, **k:
                        company([{"id": "ev1", "name": "MNA_COMPLETED",
                                  "entity_type": "CorporateEvent",
                                  "properties": {"role": "ACQUIRER"}}])
                        if eid == "c1" else EVENT)
    assert X.company_exits("c1", "DoorDash") == []


def test_non_exit_events_are_ignored(monkeypatch):
    monkeypatch.setattr(cala, "get_entity", lambda eid, **k:
                        company([{"id": "ev1", "name": "FINANCING_RAISED_OR_FACILITY_ENTERED",
                                  "entity_type": "PrivateCompanyFundingRound",
                                  "properties": {"role": "ISSUER"}}]))
    assert X.company_exits("c1", "Wolt") == []


def test_no_events_is_an_answer_not_an_error(monkeypatch):
    monkeypatch.setattr(cala, "get_entity", lambda eid, **k: company([]))
    assert X.company_exits("c1", "Nobody") == []


def test_rate_keeps_its_denominator():
    r = X.summarise([("a", [X.Exit("a", "Buyer", date(2024, 1, 1), "MNA_COMPLETED")]),
                     ("b", []), ("c", []), ("d", [])])
    assert r.checked == 4 and len(r.exits) == 1 and r.rate == 0.25


def test_a_rate_over_nothing_is_unknown_not_zero():
    assert X.summarise([]).rate is None


def test_exits_come_back_newest_first():
    r = X.summarise([
        ("a", [X.Exit("a", "B", date(2019, 5, 1), "MNA_COMPLETED")]),
        ("b", [X.Exit("b", "C", date(2024, 2, 1), "MNA_COMPLETED")]),
    ])
    assert [x.company for x in r.exits] == ["b", "a"]


# --------------------------------- a financing round is not an exit
from app import profile as _PR


def _fund(events):
    return {"id": "f", "name": "Testfund", "entity_type": "Organization",
            "properties": {}, "relationships": {"outgoing": {
                "PARTICIPATES_IN_CORPORATE_EVENT": events}, "incoming": {}}}


def _ev(name, **props):
    return {"id": name.lower(), "name": name, "entity_type": "CorporateEvent",
            "properties": props}


def test_financing_events_are_not_counted_as_exits():
    """Creandum's 69 corporate events are all financings. Counting the edge
    put 69 exits on its headline card when it has none on record."""
    f = _PR.build(_fund([_ev("FINANCING_RAISED_OR_FACILITY_ENTERED", role="INVESTOR")] * 3))
    assert f["stats"]["exits"] == 0
    assert f["stats"]["financing_events"] == 3
    assert f["has"]["exits"] is False


def test_a_completed_acquisition_is_an_exit():
    f = _PR.build(_fund([_ev("MNA_COMPLETED", role="ACQUIRER")]))
    assert f["stats"]["exits"] == 1
    assert f["has"]["exits"] is True


def test_the_two_are_separated_in_the_same_list():
    f = _PR.build(_fund([_ev("FINANCING_RAISED_OR_FACILITY_ENTERED"),
                         _ev("MNA_COMPLETED")]))
    assert f["stats"]["exits"] == 1 and f["stats"]["financing_events"] == 1


def test_headquarters_falls_back_to_where_they_operate():
    """Creandum has no HAS_HEADQUARTERS_IN and three presence countries; a
    blank read as "we do not cover them"."""
    e = {"id": "f", "name": "T", "entity_type": "Organization", "properties": {},
         "relationships": {"outgoing": {"HAS_PRESENCE_IN": [
             {"id": "se", "name": "Sweden", "entity_type": "Country"}]}, "incoming": {}}}
    f = _PR.build(e)
    assert f["country"] == "Sweden" and f["country_is_presence"] is True


def test_a_real_headquarters_is_not_labelled_as_presence():
    e = {"id": "f", "name": "T", "entity_type": "Organization", "properties": {},
         "relationships": {"outgoing": {
             "HAS_HEADQUARTERS_IN": [{"id": "fi", "name": "Finland", "entity_type": "Country"}],
             "HAS_PRESENCE_IN": [{"id": "se", "name": "Sweden", "entity_type": "Country"}],
         }, "incoming": {}}}
    f = _PR.build(e)
    assert f["country"] == "Finland" and f["country_is_presence"] is False
