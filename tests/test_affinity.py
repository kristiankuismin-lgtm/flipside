"""Warm routes that are not made of money."""
from app import affinity as A


def person(pid, name, **rels):
    return {"id": pid, "name": name, "entity_type": "Person",
            "properties": {}, "relationships": {"outgoing": rels}}


def node(name, **props):
    return {"id": name.lower(), "name": name, "entity_type": "Organization",
            "properties": props}


def test_two_people_at_the_same_school_are_a_route():
    idx = A.index([person("a", "A", STUDIED_AT=[node("Aalto University")]),
                   person("b", "B", STUDIED_AT=[node("Aalto University")])])
    r = A.routes("a", idx)
    assert [x["name"] for x in r] == ["B"]
    assert r[0]["via"][0]["kind"] == "school"


def test_one_person_alone_at_a_school_is_not_a_route():
    idx = A.index([person("a", "A", STUDIED_AT=[node("Aalto University")])])
    assert A.routes("a", idx) == []


def test_a_board_outranks_a_school():
    """Sitting on the same board is doing business together; the same
    university may be forty years apart."""
    idx = A.index([
        person("a", "A", IS_BOARD_MEMBER_OF=[node("Co")], STUDIED_AT=[node("Uni")]),
        person("b", "B", IS_BOARD_MEMBER_OF=[node("Co")]),
        person("c", "C", STUDIED_AT=[node("Uni")])])
    names = [x["name"] for x in A.routes("a", idx)]
    assert names.index("B") < names.index("C")


def test_overlapping_in_time_is_worth_more_than_sharing_the_name():
    idx = A.index([
        person("a", "A", STUDIED_AT=[node("Uni", valid_since="2010-01-01")]),
        person("same", "Same", STUDIED_AT=[node("Uni", valid_since="2010-01-01")]),
        person("far", "Far", STUDIED_AT=[node("Uni", valid_since="1975-01-01")])])
    r = {x["name"]: x for x in A.routes("a", idx)}
    assert r["Same"]["strength"] > r["Far"]["strength"]
    assert r["Same"]["via"][0]["overlapped"] is True
    assert r["Far"]["via"][0]["overlapped"] is False


def test_an_institution_shared_by_hundreds_is_not_an_introduction():
    crowd = [person(str(i), f"P{i}", IS_MEMBER_OF=[node("Huge Org")])
             for i in range(A._TOO_BIG + 5)]
    idx = A.index(crowd)
    assert A.routes("0", idx) == []


def test_sharing_several_things_beats_sharing_one():
    idx = A.index([
        person("a", "A", STUDIED_AT=[node("Uni")], RECEIVED_AWARD=[node("Prize")]),
        person("both", "Both", STUDIED_AT=[node("Uni")], RECEIVED_AWARD=[node("Prize")]),
        person("one", "One", STUDIED_AT=[node("Uni")])])
    r = {x["name"]: x for x in A.routes("a", idx)}
    assert r["Both"]["strength"] > r["One"]["strength"]
    assert len(r["Both"]["via"]) == 2


def test_the_sentence_names_the_strongest_link_and_counts_the_rest():
    idx = A.index([
        person("a", "A", RECEIVED_AWARD=[node("Prize", year="2020")],
               STUDIED_AT=[node("Uni")]),
        person("b", "B", RECEIVED_AWARD=[node("Prize", year="2020")],
               STUDIED_AT=[node("Uni")])])
    s = A.phrase(A.routes("a", idx)[0])
    assert "Prize" in s and "the same year" in s and "1 other thing" in s


def test_a_single_link_does_not_claim_others():
    idx = A.index([person("a", "A", STUDIED_AT=[node("Uni")]),
                   person("b", "B", STUDIED_AT=[node("Uni")])])
    assert "other thing" not in A.phrase(A.routes("a", idx)[0])


def test_someone_with_nothing_shared_produces_nothing():
    idx = A.index([person("a", "A", STUDIED_AT=[node("Uni")]),
                   person("b", "B", STUDIED_AT=[node("Other")])])
    assert A.routes("a", idx) == []


def test_non_people_are_ignored():
    idx = A.index([{"id": "c", "name": "A Company", "entity_type": "Company",
                    "relationships": {"outgoing": {"STUDIED_AT": [node("Uni")]}}}])
    assert idx == {}


def test_a_node_whose_whole_name_is_a_legal_suffix_still_exists():
    """norm.name("Co") is empty, and the node vanished with its key."""
    idx = A.index([person("a", "A", IS_BOARD_MEMBER_OF=[node("Co")]),
                   person("b", "B", IS_BOARD_MEMBER_OF=[node("Co")])])
    assert [x["name"] for x in A.routes("a", idx)] == ["B"]
