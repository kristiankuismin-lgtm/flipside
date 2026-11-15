"""Whose money is already in the company, read rather than configured.

Warm paths are computed from the founder's existing cap table, and that list
was a hardcoded preset - so the feature worked for exactly one company and
looked like it worked for all of them.
"""
import pytest

from app import api


def _wire(monkeypatch, names):
    monkeypatch.setattr(api, "_resolve_company", lambda n: {"id": "c1", "name": n})
    import app.cala_client as cala
    monkeypatch.setattr(cala, "get_entity", lambda *a, **k: {
        "id": "c1", "relationships": {"incoming": {
            "INVESTED_IN": [{"id": str(i), "name": n}
                            for i, n in enumerate(names)]}}})


def test_the_investors_already_in_the_company_come_back(monkeypatch):
    _wire(monkeypatch, ["Voima Ventures", "Reaktor AB"])
    assert api._own_backers("Gosta Labs") == ["Voima Ventures", "Reaktor AB"]


def test_the_same_fund_under_two_entities_is_one_backer(monkeypatch):
    """Cala holds "Voima Ventures" and "Voima Ventures Oy" separately, and a
    founder reading "two of your backers" when it is one fund twice would be
    right not to trust the rest."""
    _wire(monkeypatch, ["Voima Ventures Oy", "Voima Ventures", "Reaktor AB"])
    assert api._own_backers("Gosta Labs") == ["Voima Ventures Oy", "Reaktor AB"]


def test_a_company_nobody_has_invested_in_gives_an_empty_list(monkeypatch):
    _wire(monkeypatch, [])
    assert api._own_backers("Newthing") == []


def test_a_company_cala_cannot_resolve_is_not_an_error(monkeypatch):
    monkeypatch.setattr(api, "_resolve_company", lambda n: None)
    assert api._own_backers("No Such Company") == []


def test_a_failed_lookup_falls_back_to_what_we_hold(monkeypatch):
    """A rate limit must not empty a founder's cap table."""
    monkeypatch.setattr(api, "_resolve_company", lambda n: {
        "id": "c1", "relationships": {"incoming": {
            "INVESTED_IN": [{"id": "1", "name": "Cached Backer"}]}}})
    import app.cala_client as cala
    monkeypatch.setattr(cala, "get_entity", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("rate limited")))
    assert api._own_backers("Gosta Labs") == ["Cached Backer"]


def test_a_nameless_edge_is_skipped(monkeypatch):
    _wire(monkeypatch, ["", "  ", "Real Fund"])
    assert api._own_backers("X") == ["Real Fund"]
