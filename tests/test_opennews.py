"""The open-web fallback for firms Cala has nothing written about.

Nothing here touches the network: the two tests that need a response hand
one in, because a test that depends on GDELT being up is a test that fails
for reasons that have nothing to do with the code.
"""
from app import opennews as ON


# ----------------------------------------------------------- relevance
def test_a_fuzzy_hit_that_does_not_name_the_firm_is_dropped():
    """HN's search returns a Costa Rican computer lab for "Gosta Labs"."""
    assert ON.relevant("Gosta Labs", "How To Set Up A Costa Rican Computer Lab",
                       "http://ethertontech.com/costa-rican-computer-lab") is False


def test_the_name_in_the_title_counts():
    assert ON.relevant("Creandum", "The Creandum Exits Report", None) is True


def test_the_name_in_the_url_counts_when_the_headline_omits_it():
    assert ON.relevant("Creandum", "Seon raises a $12M Series A",
                       "https://techcrunch.com/seon-series-a-led-by-creandum") is True


def test_the_head_of_a_dotted_name_counts():
    """A headline writes "Icebreaker", not "Icebreaker.vc"."""
    assert ON.relevant("Icebreaker.vc", "Icebreaker backs five new teams", None) is True


def test_a_head_too_short_to_mean_anything_does_not_count():
    """"Lead Edge" must not match every headline containing "lead"."""
    assert ON.relevant("Lead Edge Capital", "Lead times are getting longer", None) is False


def test_a_name_too_short_to_search_on_is_refused():
    assert ON.relevant("AB", "AB testing at scale", None) is False


# -------------------------------------------------------------- shapes
def test_gdelt_stamps_become_dates():
    assert ON._date("20261019T121500Z") == "2026-10-19"
    assert ON._date(None) is None
    assert ON._date("bad") is None


def test_aggregators_are_skipped():
    """Their links work and they are not where anyone should be sent."""
    fake = lambda params: {"articles": [
        {"url": "https://msn.com/x", "title": "Creandum raises", "domain": "msn.com",
         "seendate": "20261019T121500Z"},
        {"url": "https://arcticstartup.com/y", "title": "Creandum raises a fund",
         "domain": "arcticstartup.com", "seendate": "20261018T121500Z"},
    ]}
    out = ON.search("Creandum XYZ unique", limit=5, fetcher=fake)
    assert [i["domain"] for i in out["items"]] == ["arcticstartup.com"]


def test_the_same_story_twice_is_one_row():
    fake = lambda params: {"articles": [
        {"url": "https://a.com/1", "title": "Creandum raises a fund", "domain": "a.com",
         "seendate": "20261019T121500Z"},
        {"url": "https://b.com/2", "title": "Creandum  raises a  fund!", "domain": "b.com",
         "seendate": "20261019T121500Z"},
    ]}
    out = ON.search("Creandum dedupe probe", limit=5, fetcher=fake)
    assert len(out["items"]) == 1


def test_a_short_query_asks_nobody():
    assert ON.search("ab") == {"items": [], "error": None}


def test_every_item_carries_which_index_it_came_from():
    fake = lambda params: {"articles": [
        {"url": "https://a.com/1", "title": "Creandum raises", "domain": "a.com",
         "seendate": "20261019T121500Z"}]}
    out = ON.search("Creandum via probe", limit=3, fetcher=fake)
    assert out["items"][0]["via"] == "GDELT"
