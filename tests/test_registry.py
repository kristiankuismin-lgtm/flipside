"""Company registries, asked directly, one per country.

No network: every adapter is handed the shape its register actually returns,
captured from the live endpoint. These tests pin what each one is allowed to
claim, and three of them exist because a register answers whatever is
closest, and closest is sometimes a different company.
"""
from app import registry as R


# ------------------------------------------------------------- dates
def test_every_register_s_date_format_comes_out_the_same():
    """cvrapi writes "12/12 - 2025". A reader comparing two founding dates
    should not have to notice which country each came from."""
    assert R._date("12/12 - 2025") == "2025-12-12"
    assert R._date("2023-10-25") == "2023-10-25"
    assert R._date("2023-10-25T00:00:00Z") == "2023-10-25"
    assert R._date(None) is None


# ------------------------------------------------------------ Finland
FI = {"companies": [{
    "businessId": {"value": "3399380-3", "registrationDate": "2023-10-25"},
    "names": [{"name": "Gosta Labs Oy", "registrationDate": "2023-11-03"}],
    "companySituations": [],
    "companyForms": [{"descriptions": [
        {"languageCode": "1", "description": "Osakeyhtiö"},
        {"languageCode": "3", "description": "Limited company"}]}],
    "mainBusinessLine": {"descriptions": [
        {"languageCode": "3", "description": "Computer programming activities"}]},
    "website": {"url": "www.gostalabs.com"},
    "addresses": [{"street": "Otakaari", "buildingNumber": 5, "postCode": "02150",
                   "postOffices": [{"city": "ESBO"}]}]}]}


def test_finland_registers_the_business_id_not_the_current_name():
    """The company was registered when its business ID was, not when its
    current name was."""
    r = R.finland("Gosta Labs", getter=lambda *a, **k: FI)
    assert r["registered"] == "2023-10-25"


def test_finland_reads_the_english_description():
    r = R.finland("Gosta Labs", getter=lambda *a, **k: FI)
    assert r["form"] == "Limited company"
    assert r["business_line"] == "Computer programming activities"


def test_an_empty_situations_list_is_a_real_answer():
    """PRH's numeric status is undocumented and not decoded. The field that
    carries bankruptcy and liquidation is companySituations, and empty means
    nothing adverse - which is information."""
    r = R.finland("Gosta Labs", getter=lambda *a, **k: FI)
    assert r["status"] == "nothing adverse on record"


def test_a_situation_on_record_is_reported():
    doc = {"companies": [dict(FI["companies"][0], companySituations=[
        {"descriptions": [{"languageCode": "3", "description": "Bankruptcy"}]}])]}
    assert R.finland("X", getter=lambda *a, **k: doc)["status"] == "Bankruptcy"


# ------------------------------------------------------- match grading
def test_a_register_answering_about_somebody_else_is_not_a_match():
    assert R.grade("Creandum", "Norrsken VC AB") == "none"


def test_a_legal_suffix_does_not_make_it_a_different_company():
    assert R.grade("Gosta Labs", "Gosta Labs Oy") == "exact"
    assert R.grade("Creandum", "Creandum AB") == "exact"


def test_a_fund_vehicle_is_a_partial_match_not_an_exact_one():
    """"Northzone" asked for; "NORTHZONE VII L.P." answered. Related, and
    not the same entity."""
    assert R.grade("Northzone", "NORTHZONE VII L.P.") == "partial"
    assert R.grade("Lifeline Ventures", "Lifeline Ventures GP II Oy") == "partial"


def test_lookup_refuses_an_answer_about_somebody_else(monkeypatch):
    monkeypatch.setattr(R, "_cached", lambda k: None)
    monkeypatch.setattr(R, "_store", lambda k, v: None)
    out = R.lookup("Creandum", cc="FI", getters={
        "FI": lambda *a, **k: {"companies": [{
            "businessId": {"value": "1", "registrationDate": "2001-01-01"},
            "names": [{"name": "Totally Different Oy"}]}]},
        "gleif": lambda *a, **k: {"data": []}})
    assert out is None


def test_lookup_keeps_a_partial_match_and_labels_it(monkeypatch):
    monkeypatch.setattr(R, "_cached", lambda k: None)
    monkeypatch.setattr(R, "_store", lambda k, v: None)
    out = R.lookup("Northzone", cc="NO", getters={"NO": lambda *a, **k: {
        "_embedded": {"enheter": [{"navn": "NORTHZONE VII L.P.",
                                   "organisasjonsnummer": "913585763",
                                   "registreringsdatoEnhetsregisteret": "2014-06-19"}]}}})
    assert out["match"] == "partial" and out["registered"] == "2014-06-19"


# -------------------------------------------------------- the gaps
def test_a_country_with_no_adapter_says_why():
    assert "key" in R.why_not("GB").lower()
    assert R.why_not("DE") and "no API" in R.why_not("DE")


def test_a_country_we_simply_have_not_reached_is_not_claimed_as_closed():
    assert R.why_not("PT") is None


def test_sec_needs_digits_not_a_name():
    assert R.sec("") is None and R.sec("Spotify") is None
