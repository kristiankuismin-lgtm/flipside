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
