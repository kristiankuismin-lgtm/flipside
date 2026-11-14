"""GitHub signal. No network: cache and scoring are exercised directly."""
import time
import app.github as G


def test_ambiguous_names_return_none_rather_than_a_guess(monkeypatch):
    """Two people share a name -> we must not attribute someone else's work."""
    monkeypatch.setattr(G, "_get", lambda p, **k: {"items": [{"login": "a"}, {"login": "b"}]})
    assert G.find_user("Common Name") is None
    monkeypatch.setattr(G, "_get", lambda p, **k: {"items": [{"login": "only"}]})
    assert G.find_user("Rare Name") == "only"


def test_short_queries_never_hit_the_api(monkeypatch):
    monkeypatch.setattr(G, "_get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the API")))
    assert G.find_user("ab") is None


def test_missing_profile_is_unknown_not_zero():
    s = G.signal(None)
    assert s["value"] is None and s["label"] == "unknown"


def test_signal_is_bounded_and_log_scaled():
    yr = time.gmtime().tm_year
    big = G.signal({"stars": 50000, "own_repos": 300, "since": yr - 20,
                    "languages": [("C", 9)]})
    small = G.signal({"stars": 40, "own_repos": 6, "since": yr - 2,
                      "languages": [("Python", 3)]})
    assert 0 <= small["value"] < big["value"] <= 1.0
    # log scaling: 50k stars must not be 1000x a 50-star account
    assert big["value"] < small["value"] * 6


def test_empty_account_scores_low_but_not_none():
    s = G.signal({"stars": 0, "own_repos": 0, "since": time.gmtime().tm_year,
                  "languages": []})
    assert s["value"] == 0.0 and s["label"] == "light"


def test_cached_calls_skip_the_network(monkeypatch):
    G._store("/users/cached", {"login": "cached"})
    monkeypatch.setattr(G.httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not call the API")))
    assert G._get("/users/cached")["login"] == "cached"
