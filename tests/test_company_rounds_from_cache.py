"""Harvested FundingRound entities as a rounds source.

The syndicate graph was built from two JSON files covering a few hundred
companies, each of which cost a natural-language query. Every round we have
ever fetched as an entity was sitting unused in the same cache.
"""
from app import company_rounds as CR


def round_entity(issuer, investors, *, stage="SEED", date="2024-01-01",
                 amount=1000000.0, units="USD", leads=()):
    parts = [{"id": "c", "name": issuer, "properties": {"role": "ISSUER"}}]
    parts += [{"id": f"i{n}", "name": nm,
               "properties": {"role": "INVESTOR",
                              **({"is_lead": True} if nm in leads else {})}}
              for n, nm in enumerate(investors)]
    return {"id": "r1", "entity_type": "FundingRound", "name": stage,
            "properties": {"round_label": stage, "announcement_date": date,
                           "transaction_value": amount,
                           "transaction_value_units": units},
            "relationships": {"incoming": {"PARTICIPATES_IN_FUNDING_ROUND": parts}}}


def test_reads_the_issuer_and_the_investors_apart():
    out = CR.from_cache({"r1": round_entity("Acme", ["Tesi", "Inventure"])})
    assert list(out) == ["acme"]
    r = out["acme"][0]
    assert r["investors"] == ["Tesi", "Inventure"]
    assert r["amount"] == 1000000.0 and r["currency"] == "USD"
    assert r["stage"] == "SEED" and r["date"] == "2024-01-01"


def test_the_lead_is_read_from_the_edge_properties_not_the_edge():
    """is_lead sits beside role on the edge's own properties, one level below
    where a first scan looked for it - which nearly lost lead attribution
    entirely while reporting that the graph did not have it."""
    out = CR.from_cache({"r1": round_entity("Acme", ["Tesi", "Inventure"],
                                            leads=["Inventure"])})
    assert out["acme"][0]["leads"] == ["Inventure"]


def test_a_round_nobody_is_marked_leading_has_no_lead_invented():
    out = CR.from_cache({"r1": round_entity("Acme", ["Tesi", "Inventure"])})
    assert out["acme"][0]["leads"] == []


def test_a_round_with_no_investors_is_not_a_round():
    e = round_entity("Acme", [])
    assert CR.from_cache({"r1": e}) == {}


def test_a_round_with_no_issuer_is_dropped():
    e = round_entity("Acme", ["Tesi"])
    for p in e["relationships"]["incoming"]["PARTICIPATES_IN_FUNDING_ROUND"]:
        if p["properties"]["role"] == "ISSUER":
            p["properties"]["role"] = "INVESTOR"
    assert CR.from_cache({"r1": e}) == {}


def test_duplicate_investors_collapse_on_the_normalised_name():
    e = round_entity("Acme", ["Tesi", "Tesi Oy", "Inventure"])
    assert len(CR.from_cache({"r1": e})["acme"][0]["investors"]) <= 3


def test_properties_wrapped_in_value_and_sources_are_unwrapped():
    e = round_entity("Acme", ["Tesi"])
    e["properties"] = {k: {"value": v, "sources": []}
                       for k, v in e["properties"].items()}
    for p in e["relationships"]["incoming"]["PARTICIPATES_IN_FUNDING_ROUND"]:
        p["properties"] = {"role": {"value": p["properties"]["role"],
                                    "sources": []}}
    r = CR.from_cache({"r1": e})["acme"][0]
    assert r["investors"] == ["Tesi"] and r["amount"] == 1000000.0


def test_an_unparseable_amount_is_unknown_not_zero():
    e = round_entity("Acme", ["Tesi"], amount="undisclosed")
    assert CR.from_cache({"r1": e})["acme"][0]["amount"] is None


def test_other_entity_types_are_ignored():
    e = round_entity("Acme", ["Tesi"])
    e["entity_type"] = "PrivateCompanyFundingRound"
    assert CR.from_cache({"r1": e}) == {}
