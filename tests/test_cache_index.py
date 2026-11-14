"""The index the response cache does not keep: entity id -> payload."""
import json
import sqlite3

from app import cache_index as C


def _db(tmp_path, rows, name="c.sqlite"):
    tmp_path.mkdir(parents=True, exist_ok=True)
    p = tmp_path / name
    con = sqlite3.connect(str(p))
    con.execute("create table cache (k text primary key, v text, ts real)")
    for i, r in enumerate(rows):
        con.execute("insert into cache values (?,?,?)", (str(i), json.dumps(r), 0))
    con.commit(); con.close()
    return p


STUB = {"id": "e1", "name": "Creandum", "entity_type": "Organization"}
FULL = {"id": "e1", "name": "Creandum", "entity_type": "Organization",
        "properties": {"website": {"value": "creandum.com"}},
        "relationships": {"outgoing": {"INVESTED_IN": [{"id": "c1", "name": "Klarna"}]}}}


def test_a_full_payload_beats_a_search_stub(tmp_path):
    """A search result mentions the entity with a name and nothing else. It
    must never displace the payload that carries properties and edges."""
    p = _db(tmp_path, [{"entities": [STUB]}, FULL])
    assert C.get("e1", p)["properties"]["website"]["value"] == "creandum.com"


def test_order_does_not_decide_the_winner(tmp_path):
    """Richness wins, not whichever row the scan happened to read last."""
    stub_last = _db(tmp_path, [FULL, {"entities": [STUB]}], "a.sqlite")
    assert C.get("e1", stub_last).get("properties")
    full_last = _db(tmp_path, [{"entities": [STUB]}, FULL], "b.sqlite")
    assert C.get("e1", full_last).get("properties")


def test_entities_nested_anywhere_are_found(tmp_path):
    p = _db(tmp_path, [{"results": [{"deep": {"entities": [FULL]}}]}])
    assert C.get("e1", p)["name"] == "Creandum"


def test_a_missing_entity_is_none_not_an_error(tmp_path):
    p = _db(tmp_path, [FULL])
    assert C.get("nope", p) is None


def test_a_missing_database_is_empty_not_a_crash(tmp_path):
    assert C.build(tmp_path / "absent.sqlite") == {}


def test_legal_suffix_stripping_must_not_win_a_fund_search():
    """norm.name() turns "NORRSKEN COMPANY LIMITED" into "norrsken", an exact
    match for the query, which ranked a British construction firm above
    Norrsken VC. Looking like a fund has to beat that."""
    from app import api

    hits = [
        {"id": "a", "name": "NORRSKEN COMPANY LIMITED", "entity_type": "Company",
         "description": "British construction and engineering company."},
        {"id": "b", "name": "Norrsken VC", "entity_type": "Organization",
         "description": "A venture capital organization based in Stockholm."},
    ]
    import unittest.mock as m
    with m.patch("app.graph.search", return_value=hits):
        out = api.search("Norrsken", kind="fund", limit=5)
    assert out["results"][0]["name"] == "Norrsken VC"
