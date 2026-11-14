"""Logo resolution. No network: cache and domain parsing are tested directly."""
import app.logos as L


def test_domain_parsing():
    assert L.domain_of("https://www.Supercell.com/games") == "supercell.com"
    assert L.domain_of("gostalabs.com") == "gostalabs.com"
    assert L.domain_of("http://sub.example.co.uk") == "sub.example.co.uk"
    assert L.domain_of(None) is None
    assert L.domain_of("not a domain") is None


def test_cached_bytes_skip_the_network(monkeypatch):
    L._store("cached.com", b"\x89PNGabcdefghij", "image/png")
    monkeypatch.setattr(L.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    body, ct = L.fetch("https://cached.com/x")
    assert body.startswith(b"\x89PNG") and ct == "image/png"


def test_cached_miss_is_remembered(monkeypatch):
    L._store("missing.com", b"", "")
    monkeypatch.setattr(L.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    assert L.fetch("missing.com") == (None, None)


def test_cache_only_never_fetches(monkeypatch):
    monkeypatch.setattr(L.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the network")))
    assert L.fetch("brand-new-domain-xyz.com", cache_only=True) == (None, None)
