"""Grading the scout score against what people actually did next."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "backtest_scouts", Path(__file__).resolve().parents[1] / "backtest_scouts.py")
BT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(BT)


def person(name, **rels):
    return {"id": name, "name": name, "entity_type": "Person",
            "properties": {}, "relationships": {"outgoing": rels}}


def co(name, since=None):
    p = {"valid_since": since} if since else {}
    return {"id": name.lower(), "name": name, "entity_type": "Company",
            "properties": p}


def test_someone_with_no_dated_founding_cannot_be_graded():
    """A FOUNDED edge with no date might be 2004 or last month. Guessing
    would mean grading our own homework."""
    assert BT.split(person("A", FOUNDED=[co("Undated")]), 2015, lambda k: None) is None


def test_the_outcome_is_what_happened_after_the_cutoff():
    p = person("A", FOUNDED=[co("First", "2010-01-01"), co("Second", "2019-01-01")])
    r = BT.split(p, 2015, lambda k: None)
    assert r["prior_foundings"] == 1 and r["founded_after"] is True


def test_nothing_after_the_cutoff_is_a_miss_not_a_gap():
    p = person("A", FOUNDED=[co("First", "2010-01-01")])
    r = BT.split(p, 2015, lambda k: None)
    assert r["prior_foundings"] == 1 and r["founded_after"] is False


def test_evidence_after_the_cutoff_does_not_count_towards_the_score():
    """The score must be the one the product would have computed that day."""
    early = BT.split(person("A", FOUNDED=[co("First", "2010-01-01")]),
                     2015, lambda k: None)
    late = BT.split(person("B", FOUNDED=[co("First", "2010-01-01"),
                                         co("Second", "2019-01-01"),
                                         co("Third", "2020-01-01")]),
                    2015, lambda k: None)
    assert early["score"] == late["score"]


def test_an_undated_operator_role_is_not_assumed_to_be_early():
    r = BT.split(person("A", FOUNDED=[co("First", "2019-01-01")],
                        IS_CEO_OF=[co("Bigco")]), 2015, lambda k: None)
    assert r["prior_operator"] is False


def test_a_fund_founding_is_excluded_from_both_sides():
    lookup = lambda k: {"relationships": {"outgoing": {
        "INVESTED_IN": [co("x"), co("y"), co("z")]}}} if k == "atomico" else None
    r = BT.split(person("A", FOUNDED=[co("Atomico", "2006-01-01"),
                                      co("Realthing", "2019-01-01")]), 2015, lookup)
    assert r["prior_foundings"] == 0 and r["founded_after"] is True
