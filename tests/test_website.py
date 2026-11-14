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
