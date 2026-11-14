"""What the harvest is allowed to claim.

Every assertion here is a claim the UI makes out loud, and two of them exist
because the first version of this module made a claim the data did not
support: it called a fund's incoming INVESTED_IN edge "backers" and listed
Figma under Index Ventures.
"""
import pytest

from app import depth


def org(**kw):
    """A harvested organisation payload, shaped like Cala returns one."""
    base = {"id": "f1", "name": "Testfund", "entity_type": "Organization",
            "properties": {}, "relationships": {"incoming": {}, "outgoing": {}}}
    base.update(kw)
    return base


def person(name, pid=None, **props):
    return {"id": pid or name.lower().replace(" ", "-"), "name": name,
            "entity_type": "Person", "properties": props}


def company(name, **props):
    return {"id": name.lower(), "name": name, "entity_type": "Company",
            "properties": props}


# ---------------------------------------------------------------- facts
def test_facts_unwrap_values_and_keep_sources():
    e = org(properties={
        "founding_date": {"value": "1996-01-01",
                          "sources": [{"document": "https://x.com/a", "name": "x"}]},
        "website": {"value": "indexventures.com", "sources": []},
    })
    f = {x["key"]: x for x in depth.facts(e)}
    assert f["founding_date"]["value"] == "1996-01-01"
    assert f["founding_date"]["label"] == "Founded"
    assert f["founding_date"]["sources"][0]["document"] == "https://x.com/a"
    assert f["website"]["sources"] == []


def test_facts_drop_empty_values():
    e = org(properties={"legal_name": {"value": ""}, "employee_count": {"value": 0}})
    assert [x["key"] for x in depth.facts(e)] == []


def test_identifiers_are_strings():
    e = org(properties={"lei": {"value": 5493001}, "cik": {"value": "0000320193"}})
    assert depth.identifiers(e) == {"lei": "5493001", "cik": "0000320193"}


# ---------------------------------------------------------------- staff
def test_staff_merges_one_person_across_edges_keeping_strongest_claim():
    """Paul Murphy is WORKS_AT twice at Northzone, once with a title."""
    e = org(relationships={"incoming": {
        "WORKS_AT": [person("Paul Murphy", role="Partner", valid_since="2020-01-01"),
                     person("Paul Murphy", role="General Partner")],
        "FOUNDED": [person("Paul Murphy")],
    }, "outgoing": {}})
    s = depth.staff(e)
    assert len(s) == 1
    row = s[0]
    assert row["name"] == "Paul Murphy"
    assert row["role"] == "Founder"          # FOUNDED outranks WORKS_AT
    assert row["since"] == "2020-01-01"      # earliest date we hold
    assert set(row["edges"]) == {"WORKS_AT", "FOUNDED"}


def test_staff_orders_founders_before_staff():
    e = org(relationships={"incoming": {
        "WORKS_AT": [person("Anna Analyst", role="Analyst")],
        "FOUNDED": [person("Fiona Founder")],
    }, "outgoing": {}})
    assert [p["name"] for p in depth.staff(e)] == ["Fiona Founder", "Anna Analyst"]


def test_staff_excludes_things_that_are_not_people():
    """IS_MEMBER_OF carries programmes: Accel's members include Accel-KKR."""
    e = org(relationships={"incoming": {"IS_MEMBER_OF": [
        person("Luciana Lixandru"),
        {"id": "p1", "name": "Accel Starter Programme", "entity_type": "Organization",
         "properties": {"role": "program"}},
    ]}, "outgoing": {}})
    assert [p["name"] for p in depth.staff(e)] == ["Luciana Lixandru"]


def test_staff_gives_a_default_role_from_the_edge():
    e = org(relationships={"incoming": {
        "IS_GENERAL_PARTNER_OF": [person("Gp Person")]}, "outgoing": {}})
    assert depth.staff(e)[0]["role"] == "General Partner"


# ------------------------------------------------------------- portfolio
def test_portfolio_unions_both_edge_directions():
    """INVESTED_IN points both ways and the direction is not reliable, so
    reading one side loses companies that are really in the portfolio."""
    e = org(relationships={
        "outgoing": {"INVESTED_IN": [company("Personio"), company("Figma")]},
        "incoming": {"INVESTED_IN": [company("Figma"), company("Klaviyo")]},
    })
    p = depth.portfolio(e)
    assert {x["name"] for x in p} == {"Personio", "Figma", "Klaviyo"}
    both = [x for x in p if len(x["directions"]) == 2]
    assert [x["name"] for x in both] == ["Figma"]


def test_portfolio_is_not_called_backers():
    """A fund's incoming INVESTED_IN is portfolio, not its own investors.
    This module must not grow a backers() again without new evidence."""
    assert not hasattr(depth, "backers")


# -------------------------------------------------------------- coverage
def test_coverage_separates_never_asked_from_genuinely_empty():
    never = org(relationships={})
    empty = org(relationships={"incoming": {}, "outgoing": {}},
                properties={"name": {"value": "Testfund"}})
    assert depth.coverage(never)["harvested"] is False
    assert depth.coverage(empty)["harvested"] is True
    assert depth.coverage(empty)["edges"] == 0


def test_coverage_counts_sourced_properties_separately():
    e = org(properties={"website": {"value": "a.com", "sources": [{"document": "u"}]},
                        "legal_name": {"value": "A Oy", "sources": []}})
    c = depth.coverage(e)
    assert c["properties"] == 2 and c["sourced_properties"] == 1


def test_profile_of_an_unknown_name_is_not_an_error():
    p = depth.profile("No Such Fund Anywhere 12345")
    assert p["found"] is False
    assert p["coverage"]["harvested"] is False


# -------------------------------------------------------------- presence
def test_presence_puts_headquarters_first_and_dedupes():
    e = org(relationships={"outgoing": {
        "HAS_HEADQUARTERS_IN": [{"id": "c1", "name": "Sweden", "entity_type": "Country"}],
        "HAS_PRESENCE_IN": [{"id": "c1", "name": "Sweden", "entity_type": "Country"},
                            {"id": "c2", "name": "Germany", "entity_type": "Country"}],
    }, "incoming": {}})
    p = depth.presence(e)
    assert [(x["name"], x["kind"]) for x in p] == [
        ("Sweden", "headquarters"), ("Germany", "presence")]


# ------------------------------------------------------- name lookup
def test_a_name_lookup_respects_the_type_asked_for(monkeypatch):
    """Cala holds "Ilkka Paananen" as a Person and as an Organization. A
    caller asking for the organisation must not be handed the person just
    because the person's payload is longer."""
    person = {"id": "p1", "name": "Ilkka Paananen", "entity_type": "Person",
              "properties": {"a": 1, "b": 2, "c": 3}, "relationships": {}}
    org = {"id": "o1", "name": "Ilkka Paananen", "entity_type": "Organization",
           "properties": {}, "relationships": {}}
    monkeypatch.setattr(depth.cache_index, "build",
                        lambda *a, **k: {"p1": person, "o1": org})
    depth._BY_NAME_FOR = None
    assert depth.entity("Ilkka Paananen", types=("Organization",))["id"] == "o1"
    assert depth.entity("Ilkka Paananen", types=("Person",))["id"] == "p1"
    depth._BY_NAME_FOR = None


def test_a_name_lookup_with_no_type_takes_the_richest(monkeypatch):
    thin = {"id": "a", "name": "Creandum", "entity_type": "Company",
            "properties": {}, "relationships": {}}
    full = {"id": "b", "name": "Creandum", "entity_type": "Organization",
            "properties": {"website": {"value": "creandum.com"}},
            "relationships": {"incoming": {"WORKS_AT": [{"id": "x", "name": "A",
                                                         "entity_type": "Person"}]}}}
    monkeypatch.setattr(depth.cache_index, "build",
                        lambda *a, **k: {"a": thin, "b": full})
    depth._BY_NAME_FOR = None
    assert depth.entity("Creandum")["id"] == "b"
    depth._BY_NAME_FOR = None
