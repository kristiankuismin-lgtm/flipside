"""Geocoder behaviour. No network: the cache layer is exercised directly."""
import app.geocode as gc


def test_short_queries_are_rejected_without_a_request(monkeypatch):
    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    assert gc.lookup("") is None
    assert gc.lookup("ab") is None


def test_cached_hit_skips_the_network(monkeypatch):
    gc._store("Testikatu 1, Helsinki", {"lat": 60.1, "lon": 24.9, "display": "x", "bbox": None})
    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    assert gc.lookup("Testikatu 1, Helsinki")["lat"] == 60.1


def test_cached_miss_is_remembered_as_none(monkeypatch):
    gc._store("Nowhere at all xyz", {})
    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    assert gc.lookup("Nowhere at all xyz") is None


def test_whitespace_is_normalised():
    gc._store("A B", {"lat": 1.0, "lon": 2.0, "display": "", "bbox": None})
    assert gc.lookup("  A   B  ")["lat"] == 1.0


def test_cache_only_never_calls_the_network(monkeypatch):
    """Request paths must not block on Nominatim's 1-per-second limit."""
    monkeypatch.setattr(gc.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    assert gc.lookup("Some address never seen before 12345", cache_only=True) is None
