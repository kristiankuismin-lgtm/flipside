"""Public dataset connectors. No network: cache and logic are tested directly."""
from datetime import date, timedelta
import app.datasets as D


def _nonet(monkeypatch):
    monkeypatch.setattr(D.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))


def test_short_names_never_hit_the_network(monkeypatch):
    _nonet(monkeypatch)
    assert D.form_d("ab") == []
    assert D.gleif("ab") is None
    assert D.prh("") is None
    assert D.brreg("x") is None


def test_cached_results_skip_the_network(monkeypatch):
    D._store("gleif:supercell", {"data": [{"attributes": {
        "lei": "L1", "entity": {"legalName": {"name": "Supercell Oy"}, "status": "ACTIVE",
                                "legalAddress": {"city": "Helsinki", "country": "FI"}}}}]})
    _nonet(monkeypatch)
    g = D.gleif("Supercell")
    assert g["lei"] == "L1" and g["city"] == "Helsinki"


def test_silent_round_ignores_a_filing_that_matches_a_known_round(monkeypatch):
    """A Form D filed beside a round we already know is just its paperwork."""
    filed = (date.today() - timedelta(days=30)).isoformat()
    D._store(f'formd:acme', {"hits": {"hits": [
        {"_source": {"display_names": ["Acme Inc  (CIK 0001)"], "file_date": filed}}]}})
    _nonet(monkeypatch)
    known = [(date.today() - timedelta(days=45)).isoformat()]
    assert D.silent_round("Acme", known) is None


def test_silent_round_flags_a_filing_with_nothing_near_it(monkeypatch):
    filed = (date.today() - timedelta(days=20)).isoformat()
    D._store("formd:quietco", {"hits": {"hits": [
        {"_source": {"display_names": ["QuietCo  (CIK 0009)"], "file_date": filed}}]}})
    _nonet(monkeypatch)
    r = D.silent_round("QuietCo", [(date.today() - timedelta(days=900)).isoformat()])
    assert r and r["filed"] == filed and r["cik"] == "0009"


def test_stale_filings_are_not_news(monkeypatch):
    filed = (date.today() - timedelta(days=800)).isoformat()
    D._store("formd:oldco", {"hits": {"hits": [
        {"_source": {"display_names": ["OldCo  (CIK 2)"], "file_date": filed}}]}})
    _nonet(monkeypatch)
    assert D.silent_round("OldCo", []) is None


def test_unparseable_round_dates_do_not_crash(monkeypatch):
    filed = (date.today() - timedelta(days=10)).isoformat()
    D._store("formd:oddco", {"hits": {"hits": [
        {"_source": {"display_names": ["OddCo  (CIK 3)"], "file_date": filed}}]}})
    _nonet(monkeypatch)
    assert D.silent_round("OddCo", ["not-a-date", ""]) is not None


def test_empty_api_payloads_return_none(monkeypatch):
    """The cache these read moved into registry.raw when the duplicate
    implementations were merged; the thing being tested did not."""
    import app.registry as R
    R._store('raw:gleif:{"filter[entity.legalName]": "nothing", "page[size]": 5}:', {})
    R._store('raw:prh:{"name": "nothing"}:', {})
    R._store('raw:brreg:{"navn": "nothing", "size": 1}:', {})
    _nonet(monkeypatch)
    monkeypatch.setattr(R.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    assert D.gleif("nothing") is None and D.prh("nothing") is None and D.brreg("nothing") is None


def test_gleif_refuses_a_loose_name_match(monkeypatch):
    """'Abridge' once matched a Swedish entity in Alvsjo. Wrong legal entity
    is worse than none."""
    D._store("gleif:abridge", {"data": [{"attributes": {
        "lei": "WRONG", "entity": {"legalName": {"name": "Abridgement Holding AB"},
                                   "legalAddress": {"city": "Alvsjo"}}}}]})
    _nonet(monkeypatch)
    assert D.gleif("Abridge") is None


def test_gleif_accepts_a_legal_suffix_match(monkeypatch):
    D._store("gleif:supercell", {"data": [{"attributes": {
        "lei": "RIGHT", "entity": {"legalName": {"name": "Supercell Oy"},
                                   "legalAddress": {"city": "Helsinki"}}}}]})
    _nonet(monkeypatch)
    assert D.gleif("Supercell")["lei"] == "RIGHT"
