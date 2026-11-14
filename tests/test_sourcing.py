"""Per-claim sourcing. No network: the search payload is supplied directly."""
import app.sourcing as S
import app.cala_client as cala

PAYLOAD = {
    "content": "Yes, Northzone invested in Tandem Health.",
    "explainability": [
        {"content": "Northzone is listed on Tandem Health's portfolio page.",
         "references": ["d1"]},
        {"content": "MAQS states Northzone led the round.", "references": ["d2"]},
        {"content": "Unreferenced remark.", "references": []},
    ],
    "context": [
        {"id": "d1", "content": "Portfolio listing",
         "origins": [{"source": {"name": "portfolio.northzone.com",
                                 "url": "https://portfolio.northzone.com/companies/x"},
                      "document": {"name": "Tandem Health | Northzone",
                                   "url": "https://portfolio.northzone.com/companies/x"}}]},
        {"id": "d2", "content": "MAQS advises Northzone",
         "origins": [{"source": {"name": "MAQS", "url": "https://maqs.com/en/news/a"},
                      "document": {"name": "MAQS advises Northzone",
                                   "url": "https://maqs.com/en/news/a"}}]},
    ],
}


def test_claims_carry_their_own_documents(monkeypatch):
    monkeypatch.setattr(cala, "search", lambda q, **k: PAYLOAD)
    r = S.explain("q")
    assert len(r["claims"]) == 3
    assert r["claims"][0]["docs"][0]["url"].startswith("https://portfolio.northzone.com")
    assert r["claims"][2]["docs"] == []      # unreferenced claim gets nothing


def test_the_funds_own_page_outranks_commentary(monkeypatch):
    """Northzone's own portfolio page is primary; a law firm's news page is not."""
    monkeypatch.setattr(cala, "search", lambda q, **k: PAYLOAD)
    r = S.conflict_evidence("Northzone", "Tandem Health")
    assert r["docs"][0]["rank"] == "PRIMARY"
    assert r["docs"][0]["source"] == "portfolio.northzone.com"
    maqs = [d for d in r["docs"] if d["source"] == "MAQS"][0]
    assert maqs["rank"] == "PRESS"


def test_a_news_path_alone_is_not_primary(monkeypatch):
    monkeypatch.setattr(cala, "search", lambda q, **k: PAYLOAD)
    assert all(d["rank"] != "PRIMARY" for d in S.explain("q")["docs"])


def test_sec_filings_rank_above_everything(monkeypatch):
    p = dict(PAYLOAD)
    p["context"] = PAYLOAD["context"] + [{"id": "d3", "content": "Form D",
        "origins": [{"source": {"name": "SEC", "url": "https://www.sec.gov/x"},
                     "document": {"name": "Form D", "url": "https://www.sec.gov/x"}}]}]
    p["explainability"] = PAYLOAD["explainability"] + [{"content": "Filed", "references": ["d3"]}]
    monkeypatch.setattr(cala, "search", lambda q, **k: p)
    assert S.conflict_evidence("Northzone", "Tandem Health")["docs"][0]["rank"] == "FILING"


def test_documents_are_deduplicated(monkeypatch):
    p = dict(PAYLOAD)
    p["explainability"] = PAYLOAD["explainability"] + [
        {"content": "Same source again", "references": ["d1"]}]
    monkeypatch.setattr(cala, "search", lambda q, **k: p)
    urls = [d["url"] for d in S.explain("q")["docs"]]
    assert len(urls) == len(set(urls))


def test_an_empty_answer_does_not_crash(monkeypatch):
    monkeypatch.setattr(cala, "search", lambda q, **k: {})
    r = S.explain("q")
    assert r["claims"] == [] and r["docs"] == [] and r["answer"] == ""
