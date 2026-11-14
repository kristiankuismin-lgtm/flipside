"""People from a company's own page, and only what it literally says."""
from app import team as T

HOME = """<html><body>
  <a href="/product">Product</a>
  <a href="/about">About us</a>
  <a href="/team">Meet the team</a>
  <a href="https://linkedin.com/company/x">LinkedIn</a>
</body></html>"""

TEAM = """<html><body>
  <li><h3>Jane Smith</h3><p>Co-founder and CEO. Previously at Supercell.</p></li>
  <li><h3>Erik Lindqvist</h3><p>CTO. Jane Smith hired him in 2024.</p></li>
  <li><h3>Priya Raman</h3><p>Head of Clinical Partnerships</p></li>
  <li><p>Contact us at hello@example.com or +358 40 123 4567</p></li>
  <footer>Tomas Berg</footer>
</body></html>"""


def test_the_team_page_is_found_on_the_companys_own_domain():
    assert T.team_url(HOME, "https://gosta.fi") == "https://gosta.fi/team"


def test_an_off_domain_link_is_never_followed():
    """A social profile is someone else's data about a person."""
    only_social = '<a href="https://linkedin.com/company/x">Our team</a>'
    assert T.team_url(only_social, "https://gosta.fi") is None


def test_a_dedicated_team_page_beats_a_general_about_page():
    both = '<a href="/about">About us</a><a href="/team">Team</a>'
    assert T.team_url(both, "https://g.fi").endswith("/team")


def test_names_come_back_with_their_roles():
    got = {p["name"]: p["role"] for p in T.people(TEAM, "https://gosta.fi/team")}
    assert got["Jane Smith"] == "founder"
    assert got["Erik Lindqvist"] == "cto"
    assert got["Priya Raman"] == "head"


def test_founder_wins_over_the_operating_title():
    """"Co-founder and CEO" records that they founded it."""
    p = T.people("<li>Jane Smith — Co-founder and CEO</li>", "u")[0]
    assert p["role"] == "founder"


def test_every_person_carries_the_sentence_that_says_so():
    p = next(x for x in T.people(TEAM, "u") if x["name"] == "Jane Smith")
    assert "Co-founder and CEO" in p["quote"]
    assert p["source"] == "u"


def test_contact_details_are_dropped_even_when_the_page_shows_them():
    page = "<li>Jane Smith, CEO — jane@gosta.fi, +358 40 123 4567</li>"
    q = T.people(page, "u")[0]["quote"]
    assert "@" not in q and "358" not in q


def test_a_name_without_a_role_in_the_same_sentence_is_not_a_claim():
    """A name in a footer and a role in a heading must never combine."""
    page = "<div><h2>Leadership</h2></div><footer>Tomas Berg</footer>"
    assert T.people(page, "u") == []


def test_page_furniture_is_not_mistaken_for_a_person():
    page = "<li>Privacy Policy — our CEO approved it</li><li>New York, CTO office</li>"
    assert T.people(page, "u") == []


def test_nothing_is_claimed_about_a_page_we_could_not_read():
    assert T.people(None, "u") == [] and T.team_url(None, "u") is None


def test_a_title_fragment_is_not_a_second_person():
    """"Teddie Wardi Co-founder & Special Advisor" is one person, and
    "Special Advisor" is not the other one."""
    got = [p["name"] for p in
           T.people("<li>Teddie Wardi Co-founder & Special Advisor</li>", "u")]
    assert got == ["Teddie Wardi"]


def test_an_organisation_name_fragment_is_rejected():
    got = T.people("<li>Voima Ventures’ New Chief Financial Officer</li>", "u")
    assert all("Ventures" not in p["name"] for p in got)


# ---- every source the site actually offers ----
LD = """<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Organization","name":"Gosta",
 "employee":[{"@type":"Person","name":"Mara Linnard","jobTitle":"Co-founder and CTO"},
             {"@type":"Person","name":"Solo"}]}
</script></head><body></body></html>"""

MICRO = """<ul>
<li itemscope itemtype="https://schema.org/Person">
  <span itemprop="name">Ola Nystrom</span>
  <span itemprop="jobTitle">Chief Executive Officer</span>
</li></ul>"""


def test_structured_data_is_read_when_a_site_publishes_it():
    got = T.from_jsonld(LD, "https://g.fi")
    assert [p["name"] for p in got] == ["Mara Linnard"]   # one-word name dropped
    assert got[0]["role"] == "founder" and got[0]["via"] == "json-ld"


def test_microdata_is_read_too():
    got = T.from_microdata(MICRO, "u")
    assert got[0]["name"] == "Ola Nystrom" and got[0]["role"] == "ceo"


def test_candidate_pages_are_ranked_and_capped():
    html = """<a href="/about">About</a><a href="/team">Team</a>
              <a href="/leadership">Leadership</a><a href="/company">Company</a>"""
    got = T.candidate_pages(html, "https://g.fi")
    assert got[0].endswith("/team") or got[0].endswith("/leadership")
    assert all(u.startswith("https://g.fi") for u in got)
    assert len(got) <= T.MAX_PAGES


def test_a_richer_reading_wins_the_merge():
    """The same person from two readers keeps the one that says more."""
    thin = [{"name": "Mara Linnard", "role": "person", "quote": "Mara Linnard", "via": "a"}]
    rich = [{"name": "Mara Linnard", "role": "founder",
             "quote": "Mara Linnard, Co-founder and CTO", "via": "b"}]
    merged = T._merge([thin, rich])
    assert len(merged) == 1 and merged[0]["role"] == "founder"


def test_the_same_person_spelled_with_a_title_is_not_two_people():
    merged = T._merge([[{"name": "Mara Linnard Co-founder", "role": "founder",
                         "quote": "x", "via": "a"}],
                       [{"name": "Mara Linnard", "role": "founder",
                         "quote": "xx", "via": "b"}]])
    assert len(merged) == 1


def test_read_deep_reports_what_each_page_yielded(monkeypatch):
    """An empty result has to be attributable, not merely empty."""
    pages = {"https://g.fi": '<a href="/team">Team</a>',
             "https://g.fi/team": "<li>Mara Linnard — Co-founder</li>"}
    monkeypatch.setattr(T.W, "fetch", lambda u, **k: pages.get(T.W.normalise(u) if u in pages else u))
    monkeypatch.setattr(T.W, "normalise", lambda u: u if str(u).startswith("http") else "https://g.fi")
    got = T.read_deep("https://g.fi", follow_bios=False)
    assert [p["name"] for p in got["people"]] == ["Mara Linnard"]
    assert any(pg["url"].endswith("/team") and pg["people"] == 1 for pg in got["pages"])


def test_a_label_before_a_colon_is_not_the_person_after_it():
    """A portfolio listing reads "Company CEO: Person". Taking the first
    capitalised run turns 24 portfolio companies into 24 staff."""
    block = "<li>Coherence Quantum CEO: Aashish Sah Founders: Aashish Sah</li>"
    names = [p["name"] for p in T.people(block, "u")]
    assert "Coherence Quantum" not in names
    assert "CRACI Corporation" not in [n for n in names]


def test_the_plural_founders_heading_is_not_a_surname():
    got = [p["name"] for p in T.people("<li>Founders Founder Wellbeing</li>", "u")]
    assert got == []


def test_an_organisation_in_a_persons_title_is_not_a_second_person():
    """"Hélène Huby Cofounder and CEO of The Exploration Company" names one
    person and one company."""
    got = [p["name"] for p in
           T.people("<li>Hélène Huby Cofounder and CEO of The Exploration Company</li>", "u")]
    assert got == ["Hélène Huby"]


def test_a_person_named_before_a_title_survives_the_label_rule():
    """"Meet Anni Harju: ... Chief Financial Officer" is a person then a
    title. An earlier version of the label rule threw her away."""
    got = [p["name"] for p in T.people(
        "<li>Meet Anni Harju: Voima Ventures’ New Chief Financial Officer</li>", "u")]
    assert got == ["Anni Harju"]


# ---- is this person staff, or someone on the firm's portfolio page? ----
def test_a_portfolio_founder_is_not_staff():
    """balderton.com lists "Alex Kendall Co-founder and CEO, Wayve". A call
    list that cannot tell has you phoning Wayve about a term sheet."""
    assert T.affiliation("Alex Kendall Co-founder and CEO, Wayve", "balderton") == "Wayve"
    assert T.affiliation("Jan Goetz Co-Founder and CEO, IQM", "maki") == "IQM"
    assert T.affiliation("Marit Rødevand Founder & CEO at Strise", "maki") == "Strise"


def test_the_firms_own_partners_have_no_other_affiliation():
    assert T.affiliation("Lasse Lehtinen Co-founder & General Partner", "icebreaker") is None
    assert T.affiliation("Sabina Wizander Partner", "creandum") is None


def test_being_named_with_the_firm_itself_is_not_an_affiliation():
    assert T.affiliation("Anni Harju, CFO at Voima Ventures", "voimaventures") is None
