"""Identifier-based entry into Cala's graph. No network anywhere."""
import pytest
import app.resolve as R
import app.cala_client as cala
import app.datasets as D


def test_unsupported_scheme_is_rejected_loudly():
    with pytest.raises(ValueError):
        cala.lookup("vat_number", "FI123")


def test_empty_identifier_never_calls_the_api(monkeypatch):
    monkeypatch.setattr(cala, "_request", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the API")))
    assert cala.lookup("lei", "") is None


def test_lookup_sends_the_documented_payload(monkeypatch):
    seen = {}

    def fake(method, path, payload=None, **kw):
        seen.update(method=method, path=path, payload=payload)
        return {"id": "uuid-1", "name": "Supercell Oy", "entity_type": "Company"}

    monkeypatch.setattr(cala, "_request", fake)
    r = cala.lookup("lei", "743700MSCHABJ4XW2532")
    assert seen["path"] == "/entities/lookup"
    assert seen["payload"] == {"id": {"lei": "743700MSCHABJ4XW2532"}}
    assert r["id"] == "uuid-1"


def test_a_missing_identifier_returns_none_not_an_error(monkeypatch):
    def fake(*a, **k):
        raise cala.CalaError("404 not found", 404, "")
    monkeypatch.setattr(cala, "_request", fake)
    assert cala.lookup("cik", "999999") is None


def test_resolve_prefers_lei_and_reports_how_it_got_there(monkeypatch):
    monkeypatch.setattr(D, "gleif", lambda n, **k: {"lei": "LEI123"})
    monkeypatch.setattr(D, "form_d", lambda n, **k: [])
    monkeypatch.setattr(cala, "lookup",
                        lambda s, v, **k: {"id": "e1", "name": "Acme"} if s == "lei" else None)
    r = R.resolve("Acme")
    assert r["scheme"] == "lei" and r["identifier"] == "LEI123" and r["via"] == "GLEIF"


def test_resolve_falls_back_to_a_sec_cik(monkeypatch):
    monkeypatch.setattr(D, "gleif", lambda n, **k: None)
    monkeypatch.setattr(D, "form_d", lambda n, **k: [{"cik": "0000320193", "filed": "2026-01-01"}])
    seen = {}

    def lk(scheme, value, **k):
        seen[scheme] = value
        return {"id": "e2", "name": "Apple"} if scheme == "cik" else None

    monkeypatch.setattr(cala, "lookup", lk)
    r = R.resolve("Apple")
    assert r["scheme"] == "cik" and r["via"] == "SEC EDGAR"
    # Cala wants the CIK unpadded, not the zero-filled EDGAR form
    assert seen["cik"] == "320193"


def test_resolve_returns_none_when_no_register_has_a_key(monkeypatch):
    monkeypatch.setattr(D, "gleif", lambda n, **k: None)
    monkeypatch.setattr(D, "form_d", lambda n, **k: [])
    assert R.resolve("Nobody At All") is None


def test_observations_reports_nothing_without_crashing(monkeypatch):
    monkeypatch.setattr(cala, "introspect", lambda e, **k: {})
    assert R.observations("e1") == {"available": [], "series": {}}


def test_observations_lists_what_introspection_advertises(monkeypatch):
    monkeypatch.setattr(cala, "introspect",
                        lambda e, **k: {"numerical_observations": {"employee_count": {}}})
    monkeypatch.setattr(cala, "get_entity",
                        lambda e, **k: {"numerical_observations": {"employee_count": [1, 2]}})
    o = R.observations("e1")
    assert o["available"] == ["employee_count"] and o["series"]["employee_count"] == [1, 2]
