"""Is this name a fund or a company raising one?"""
from app import classify as CL

FUNDS = {"lifeline ventures": "Lifeline Ventures", "creandum": "Creandum",
         "inventure": "Inventure"}
COMPANIES = {"gosta labs": "Gosta Labs", "wolt": "Wolt"}
ISSUERS = {"wolt", "neko health"}


def c(q):
    return CL.classify(q, funds=FUNDS, companies=COMPANIES, issuers=ISSUERS)


def test_a_known_fund_is_a_fund():
    """The bug: typing this screened investors *for* Lifeline Ventures."""
    r = c("lifeline ventures")
    assert r["kind"] == "fund" and r["name"] == "Lifeline Ventures"


def test_a_known_company_is_a_company():
    assert c("Gosta Labs")["kind"] == "company"


def test_spelling_and_legal_form_do_not_matter():
    assert c("LIFELINE VENTURES OY")["kind"] == "fund"
    assert c("  creandum ")["kind"] == "fund"


def test_a_name_that_has_raised_reads_as_a_company_even_if_we_also_hold_a_fund():
    both = CL.classify("Wolt", funds={"wolt": "Wolt Capital"},
                       companies=COMPANIES, issuers=ISSUERS)
    assert both["kind"] == "company" and "raised" in both["why"]


def test_an_unknown_investor_ish_name_still_reads_as_a_fund():
    r = c("Northstar Capital Partners")
    assert r["kind"] == "fund" and "no record" in r["why"]


def test_an_unknown_plain_name_is_unknown_not_a_guess():
    assert c("Zorblex")["kind"] == "unknown"


def test_too_short_is_not_resolved():
    assert c("a")["kind"] == "unknown"
