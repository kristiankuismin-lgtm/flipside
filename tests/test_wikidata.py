"""The open encyclopaedia, for domains that cannot be guessed.

Nothing here touches the network: the searcher and the entity getter are
injected, because a test that depends on Wikidata being up fails for reasons
that have nothing to do with this code.
"""
from app import wikidata as W


def ent(qid, *, p31=(), site=None, hq=None, desc=None, founded=None):
    claims = {}
    if p31:
        claims["P31"] = [{"mainsnak": {"datavalue": {"value": {"id": q}}}} for q in p31]
    if site:
        claims["P856"] = [{"mainsnak": {"datavalue": {"value": site}}}]
    if hq:
        claims["P159"] = [{"mainsnak": {"datavalue": {"value": {"id": hq}}}}]
    if founded:
        claims["P571"] = [{"mainsnak": {"datavalue": {"value": {"time": founded}}}}]
    e = {"claims": claims, "labels": {"en": {"value": qid}}}
    if desc is not None:
        e["descriptions"] = {"en": {"value": desc}}
    return {"entities": {qid: e}}


def wire(hits, entities, labels=None):
    labels = labels or {}

    def searcher(url, params=None, timeout=20):
        return {"search": [{"id": q} for q in hits]}

    def getter(url, params=None, timeout=20):
        qid = url.rstrip(".json").rsplit("/", 1)[-1]
        if qid in labels:
            return {"entities": {qid: {"labels": {"en": {"value": labels[qid]}}}}}
        return entities[qid]
    return searcher, getter


# -------------------------------------------------- is this even a firm
def test_a_family_name_is_never_a_fund():
    """"Alven" is a French venture firm and also a surname, and Wikidata's
    search returns the surname first."""
    assert W.looks_like_an_organisation({"Q101352"}, "family name") is False


def test_a_human_is_never_a_fund():
    assert W.looks_like_an_organisation({"Q5"}, "American investor") is False


def test_an_instance_of_claim_decides_it():
    assert W.looks_like_an_organisation({"Q4830453"}, None) is True


def test_an_unrecognised_kind_falls_back_to_the_description():
    assert W.looks_like_an_organisation({"Q999999"},
                                        "venture capital firm") is True


def test_no_evidence_is_not_evidence_of_a_firm():
    """Absence of a description must not be read as a yes."""
    assert W.looks_like_an_organisation(set(), None) is False
    assert W.looks_like_an_organisation(set(), "a place in Norway") is False


# --------------------------------------------------------- the lookup
def test_the_website_and_headquarters_come_back(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "_cached", lambda k: None)
    monkeypatch.setattr(W, "_store", lambda k, v: None)
    s, g = wire(["Q1"], {"Q1": ent("Q1", p31=("Q4830453",),
                                   site="https://www.a16z.com/", hq="Q74195",
                                   founded="+2009-07-06T00:00:00Z",
                                   desc="venture capital firm")},
                labels={"Q74195": "Menlo Park"})
    r = W.lookup("Andreessen Horowitz", searcher=s, getter=g)
    assert r["website"] == "a16z.com"          # scheme and www stripped
    assert r["hq"] == "Menlo Park"
    assert r["founded"] == "2009-07-06"


def test_the_first_hit_is_skipped_when_it_is_not_a_firm(monkeypatch):
    """The surname comes first; the firm is behind it."""
    monkeypatch.setattr(W, "_cached", lambda k: None)
    monkeypatch.setattr(W, "_store", lambda k, v: None)
    s, g = wire(["Q1", "Q2"], {
        "Q1": ent("Q1", p31=("Q101352",), desc="family name"),
        "Q2": ent("Q2", p31=("Q4830453",), site="https://alven.co",
                  desc="French venture capital firm")})
    assert W.lookup("Alven", searcher=s, getter=g)["website"] == "alven.co"


def test_nothing_matching_returns_none(monkeypatch):
    monkeypatch.setattr(W, "_cached", lambda k: None)
    monkeypatch.setattr(W, "_store", lambda k, v: None)
    s, g = wire(["Q1"], {"Q1": ent("Q1", p31=("Q5",), desc="American investor")})
    assert W.lookup("Someone", searcher=s, getter=g) is None


def test_a_firm_with_no_website_still_returns_its_headquarters(monkeypatch):
    """"No website on record" and "not a firm" are different answers."""
    monkeypatch.setattr(W, "_cached", lambda k: None)
    monkeypatch.setattr(W, "_store", lambda k, v: None)
    s, g = wire(["Q1"], {"Q1": ent("Q1", p31=("Q4830453",), hq="Q84",
                                   desc="venture capital firm")},
                labels={"Q84": "London"})
    r = W.lookup("Somefund", searcher=s, getter=g)
    assert r["website"] is None and r["hq"] == "London"


def test_a_name_too_short_asks_nobody():
    assert W.lookup("AB") is None
