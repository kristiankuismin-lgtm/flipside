"""The person card's own claims about what it is showing."""
from app import person as P


def test_a_round_with_a_known_issuer_names_the_company(monkeypatch):
    """The edge carries the round's stage, not the investment."""
    monkeypatch.setattr(P, "_round_issuer", lambda rid: "Acme" if rid else None)
    assert P._round_issuer("r1") == "Acme"


def test_a_round_we_have_not_fetched_says_round_not_a_company_name():
    """"Seed" alone read as a company called Seed."""
    assert P._round_issuer(None) is None


def test_the_issuer_lookup_reads_the_role_on_the_edge_properties():
    rid = "r1"
    entity = {"id": rid, "entity_type": "FundingRound",
              "relationships": {"incoming": {"PARTICIPATES_IN_FUNDING_ROUND": [
                  {"name": "Someone VC", "properties": {"role": "INVESTOR"}},
                  {"name": "Acme", "properties": {"role": {"value": "ISSUER"}}}]}}}
    import app.cache_index as CI
    real = CI.get
    CI.get = lambda i, path="cache.sqlite": entity if i == rid else None
    try:
        assert P._round_issuer(rid) == "Acme"
    finally:
        CI.get = real
