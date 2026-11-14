"""A company's own homepage, read without a network."""
from app import website as W

PAGE = """
<html><head><title>Gosta Labs — clinical documentation, automatically</title>
<meta name="description" content="Gosta Labs writes the note while you see the patient.">
</head><body>
  <a href="/product">Product</a>
  <a href="/pricing">Pricing</a>
  <a href="https://jobs.lever.co/gosta">Join us</a>
  <a href="/customers">Case studies</a>
  <a href="/docs/api">API</a>
  <a href="mailto:hi@gosta.fi">Contact</a>
  <a href="#top">Back to top</a>
</body></html>
"""


def test_title_and_tagline_come_out_clean():
    r = W.read(PAGE, base="https://gosta.fi")
    assert r["title"].startswith("Gosta Labs")
    assert r["tagline"] == "Gosta Labs writes the note while you see the patient."


def test_intent_is_read_from_href_or_label():
    r = W.read(PAGE, base="https://gosta.fi")
    # "Join us" carries no career word in the label... it does in neither href
    # nor text except "Join us", which the careers pattern matches.
    assert r["links"]["careers"] == "https://jobs.lever.co/gosta"
    assert r["links"]["pricing"] == "https://gosta.fi/pricing"
    assert r["links"]["customers"] == "https://gosta.fi/customers"
    assert r["links"]["docs"] == "https://gosta.fi/docs/api"


def test_junk_links_are_skipped():
    r = W.read(PAGE, base="https://gosta.fi")
    assert all(not v.startswith(("mailto:", "#")) for v in r["links"].values())


def test_signals_say_what_they_counted():
    r = W.read(PAGE, base="https://gosta.fi")
    hiring = next(s for s in r["signals"] if s["k"] == "hiring")
    assert "not a headcount" in hiring["why"]


def test_nothing_is_claimed_about_a_page_we_could_not_read():
    r = W.read(None)
    assert r["ok"] is False and r["signals"] == [] and r["title"] is None


def test_url_normalisation():
    assert W.normalise("humanpath.si") == "https://humanpath.si"
    assert W.normalise("https://gosta.fi/about?x=1") == "https://gosta.fi"
    assert W.normalise("") is None and W.normalise(None) is None
    assert W.normalise("not a url") is None


# ---- finding a site when no source carries one ----
def test_slug_drops_the_legal_form():
    assert W.slug("Andercore GmbH") == "andercore"
    assert W.slug("Planhat AB") == "planhat"
    assert W.slug("Gosta Labs Oy") == "gostalabs"


def test_candidates_put_the_country_tld_first():
    c = W.candidates("Andercore GmbH", "DE")
    assert c[0] == "andercore.de" and "andercore.com" in c
    assert W.candidates("AB", "SE") == []          # too short to guess on
    # A four-letter name matches too many unrelated domains for a title check
    # to prove anything: "Bliq" found bliq.ai, a different company.
    assert W.candidates("Bliq", "DE") == []


def test_a_candidate_is_only_used_when_the_page_claims_the_name():
    pages = {
        "andercore.de": "<html><head><title>Domain parked</title></head></html>",
        "andercore.com": "<html><head><title>ANDERCORE | Solar wholesale</title></head></html>",
    }
    got = W.discover("Andercore GmbH", "DE", fetcher=lambda d: pages.get(d),
                     use_cache=False)
    assert got["domain"] == "andercore.com" and got["verified"] is True


def test_an_unverified_guess_is_never_returned():
    """A wrong logo and a wrong description are worse than none."""
    pages = {d: "<html><head><title>Buy this domain</title></head></html>"
             for d in W.candidates("Andercore GmbH", "DE")}
    assert W.discover("Andercore GmbH", "DE", fetcher=lambda d: pages.get(d),
                      use_cache=False) is None


def test_a_parked_domain_is_not_a_homepage():
    """bliq.com carries the name "bliq" in its title and is a page selling
    the domain. The name check alone accepts it, so it cannot be alone."""
    parked = ("<html><head><title>blickfeld.com&nbsp;-&nbsp;T\u00e4m\u00e4 WWW-sivu on "
              "myynniss\u00e4.&nbsp;-&nbsp;blickfeld L\u00e4hteet ja tiedot.</title></head>"
              "<body>osta t\u00e4m\u00e4 verkkotunnus</body></html>")
    assert W.is_parked(parked) is True
    assert W.discover("Blickfeld", "DE", fetcher=lambda d: parked, use_cache=False) is None


def test_english_and_german_parking_pages_are_caught():
    for t in ("Buy this domain", "This domain is for sale",
              "Diese Domain zu verkaufen", "Parked free at Sedoparking"):
        html = f"<html><head><title>{t}</title></head><body>{t} {'x' * 300}</body></html>"
        assert W.is_parked(html) is True, t


def test_a_real_homepage_is_not_parked():
    assert W.is_parked(PAGE) is False


def test_profile_shows_one_row_per_company():
    """The graph can carry the same company under two ids."""
    from app import profile as PR
    e = {"id": "f", "name": "Fund", "properties": {},
         "relationships": {"outgoing": {"INVESTED_IN": [
             {"id": "a", "name": "Inven"}, {"id": "b", "name": "Inven Oy"},
             {"id": "c", "name": "Aiven"}]}}}
    got = PR.build(e)
    assert [c["name"] for c in got["portfolio"]] == ["Aiven", "Inven"]


def test_a_tab_with_nothing_in_it_says_so():
    from app import profile as PR
    got = PR.build({"id": "f", "name": "Fund", "properties": {}, "relationships": {}})
    assert got["has"] == {"portfolio": False, "rounds": False,
                          "exits": False, "people": False}


def test_lead_rate_comes_from_the_native_flag():
    from app import profile as PR
    e = {"id": "f", "name": "F", "properties": {}, "relationships": {"outgoing": {
        "PARTICIPATES_IN_FUNDING_ROUND": [
            {"id": "1", "name": "Seed", "properties": {"is_lead": True}},
            {"id": "2", "name": "Seed", "properties": {}},
        ]}}}
    got = PR.build(e)
    assert got["stats"]["led"] == 1 and got["stats"]["lead_rate"] == 0.5


# ------------------------------------------------- names funds actually use
def test_stems_drop_the_fund_ish_tail():
    """coatue.com is Coatue Management's site; coatuemanagement.com is not."""
    assert W.stems("Coatue Management") == ["coatuemanagement", "coatue"]
    assert W.stems("Bessemer Venture Partners")[-1] == "bessemer"


def test_stems_keep_a_name_that_has_no_tail():
    assert W.stems("Creandum") == ["creandum"]


def test_stems_never_return_something_too_short_to_be_evidence():
    """"Lead Edge Capital" must not be matched on "lead"."""
    assert all(len(s) >= W.MIN_SLUG for s in W.stems("Lead Edge Capital"))
    assert W.stems("AB Ventures") == []


def test_candidates_try_the_hyphenated_shape():
    """Project A Ventures is project-a.com."""
    assert "project-a.com" in W.candidates("Project A Ventures")


def test_candidates_go_breadth_first_by_tld_not_by_name_shape():
    """Every shape at .com before any shape at the next TLD. Depth-first
    would spend the whole budget on one shape's long TLD tail."""
    c = W.candidates("Coatue Management")
    first_non_com = next(i for i, d in enumerate(c) if not d.endswith(".com"))
    assert all(d.endswith(".com") for d in c[:first_non_com])
    assert first_non_com >= 2        # more than one shape was tried at .com


def test_the_vc_tld_is_reached_for_a_name_with_several_shapes():
    """fabric.vc is Fabric Ventures. With .vc fifth in the list and a cap of
    eight, it was never fetched."""
    assert "fabric.vc" in W.candidates("Fabric Ventures")


def test_the_full_name_is_tried_before_the_short_stem():
    """lifelineventures.com must be fetched before lifeline.com, or a
    namesake wins on a shorter string."""
    c = W.candidates("Lifeline Ventures")
    assert c.index("lifelineventures.com") < c.index("lifeline.com")


def test_a_full_title_match_is_reported_as_full():
    html = "<title>Creandum | Venture capital</title>"
    assert W._mentions(html, "Creandum") == "full"


def test_a_stem_only_title_match_is_reported_as_stem():
    """The caller needs to know it got the weaker kind of evidence."""
    html = "<title>Coatue</title>"
    assert W._mentions(html, "Coatue Management") == "stem"


def test_an_unrelated_page_matches_nothing():
    assert W._mentions("<title>Acme Plumbing</title>", "Coatue Management") is None


def test_discover_labels_how_it_matched():
    pages = {"coatue.com": "<title>Coatue</title>"}
    d = W.discover("Coatue Management", fetcher=lambda x: pages.get(x), use_cache=False)
    assert d["domain"] == "coatue.com" and d["match"] == "stem"
