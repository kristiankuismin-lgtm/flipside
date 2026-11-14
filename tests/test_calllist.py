"""Who to call, in what order, and where the name came from."""
from app import calllist as C


def inv(name, score, conflict=False, lead="Led 4 of 5", warm=None):
    return {"investor": name, "score": score, "backs": ["Corti"] if conflict else [],
            "signals": {"conflict": {"label": "🔴" if conflict else "🟢"},
                        "lead_rate": {"text": lead},
                        "dry_powder": {"text": "7 new investments in 6 months (prior 4)"},
                        "warm_path": {"label": "🟢" if warm else "⚪", "text": warm}}}


PEOPLE = {
    "atomico": [{"name": "Ana Partner", "role": "Partner", "linkedin": "https://li/a",
                 "source": "cala"},
                {"name": "Bo Analyst", "role": "Associate", "source": "site"}],
    "northzone": [{"name": "Cal Lead", "role": "Partner", "source": "cala"}],
}


def test_seniority_puts_the_cheque_writer_first():
    assert C.seniority("Founding Partner") > C.seniority("Partner")
    assert C.seniority("Partner") > C.seniority("Associate")
    assert C.seniority("Entrepreneur in Residence") > C.seniority(None)


def test_a_conflicted_fund_contributes_no_contacts():
    out = C.build([inv("Northzone", 60, conflict=True)], PEOPLE)
    assert out["rows"] == []
    assert out["skipped"][0]["why"] == "backs a competitor"


def test_a_fund_with_no_contact_is_reported_not_dropped_silently():
    out = C.build([inv("Creandum", 70)], PEOPLE)
    assert out["rows"] == [] and out["skipped"][0]["why"] == "no contact found"


def test_cala_outranks_a_scraped_page_at_equal_seniority():
    people = {"atomico": [{"name": "Site Partner", "role": "Partner", "source": "site"},
                          {"name": "Cala Partner", "role": "Partner", "source": "cala"}]}
    out = C.build([inv("Atomico", 72)], people)
    assert [r["person"] for r in out["rows"]] == ["Cala Partner", "Site Partner"]


def test_a_warm_route_comes_before_a_cold_one_at_the_same_firm():
    out = C.build([inv("Atomico", 72, warm="via Voima Ventures")], PEOPLE)
    assert out["rows"][0]["warm"] == "via Voima Ventures"


def test_the_better_firm_comes_first_whatever_the_title():
    out = C.build([inv("Atomico", 40), inv("Northzone", 90)], PEOPLE)
    assert out["rows"][0]["fund"] == "Northzone"


def test_every_row_says_why_the_firm_is_on_the_list():
    out = C.build([inv("Atomico", 72)], PEOPLE, stage="series a")
    assert "led 4 of 5" in out["rows"][0]["reason"]
    assert "7 new investments" in out["rows"][0]["reason"]


def test_sources_are_counted_so_coverage_is_visible():
    out = C.build([inv("Atomico", 72)], PEOPLE)
    assert out["by_source"] == {"cala": 1, "site": 1}


# ---- what the person adds, once we know anything about them ----
def test_knowing_nothing_adds_nothing_and_is_not_a_penalty():
    assert C.person_bonus(None) == (0.0, [])
    assert C.person_bonus({}) == (0.0, [])


def test_being_in_your_market_is_the_strongest_person_signal():
    market, _ = C.person_bonus({"market_match": ["health"]})
    operator, _ = C.person_bonus({"years_building": 10})
    network, _ = C.person_bonus({"network": 8})
    assert market > operator > network


def test_an_operator_without_a_year_still_counts_but_counts_less():
    dated, _ = C.person_bonus({"years_building": 12})
    undated, _ = C.person_bonus({"operator": True})
    assert 0 < undated < dated


def test_the_intro_surface_saturates():
    small, _ = C.person_bonus({"network": 2})
    full, _ = C.person_bonus({"network": C.NETWORK_FULL})
    huge, _ = C.person_bonus({"network": 200})
    assert small < full == huge


def test_every_bonus_carries_its_reason():
    _, why = C.person_bonus({"market_match": ["health"], "years_building": 9,
                             "network": 4})
    assert any("market" in w for w in why)
    assert any("9 year" in w for w in why)
    assert any("4 compan" in w for w in why)


def test_the_fund_still_decides_most_of_the_order():
    """A brilliant partner at a fund that cannot lead is still the wrong call."""
    great_person_weak_fund = {"atomico": [
        {"name": "Star", "role": "Partner", "source": "cala",
         "signals": {"market_match": ["health"], "years_building": 20,
                     "network": 20, "verified": True}}]}
    plain_person_strong_fund = {"northzone": [
        {"name": "Plain", "role": "Partner", "source": "site"}]}
    out = C.build([inv("Atomico", 30), inv("Northzone", 90)],
                  {**great_person_weak_fund, **plain_person_strong_fund})
    assert out["rows"][0]["person"] == "Plain"


def test_a_person_signal_breaks_a_tie_between_equal_firms():
    people = {"atomico": [
        {"name": "Knows Health", "role": "Partner", "source": "cala",
         "signals": {"market_match": ["health"]}},
        {"name": "Knows Nothing", "role": "Partner", "source": "cala"}]}
    out = C.build([inv("Atomico", 70)], people)
    assert out["rows"][0]["person"] == "Knows Health"
    assert "market" in " ".join(out["rows"][0]["bonus_why"])


# ---------------------------------------------------- tenure at the firm
import datetime as _dt

from app import calllist as _C


def test_years_at_firm_handles_the_three_shapes_cala_returns():
    today = _dt.date(2026, 11, 14)
    assert _C.years_at_firm("2021-05-18", today) == 5.5
    assert _C.years_at_firm("2023", today) == 3.9          # year only
    assert _C.years_at_firm("2023-01-01T00:00:00", today) == 3.9


def test_unknown_start_date_is_none_not_zero():
    """A partner whose start date Cala does not hold is not a new partner."""
    assert _C.years_at_firm(None) is None
    assert _C.years_at_firm("") is None
    assert _C.years_at_firm("not a date") is None


def test_a_start_date_in_the_future_is_not_negative_tenure():
    assert _C.years_at_firm("2099-01-01", _dt.date(2026, 11, 14)) is None


def test_tenure_saturates_so_a_long_serving_partner_cannot_dominate():
    long_ = _C.person_bonus({"years_at_firm": 30})[0]
    full = _C.person_bonus({"years_at_firm": _C.TENURE_FULL})[0]
    assert long_ == full == _C.PERSON_WEIGHTS["tenure"]


def test_tenure_is_worth_less_than_market_fit():
    assert _C.PERSON_WEIGHTS["tenure"] < _C.PERSON_WEIGHTS["market"]


def test_unknown_tenure_scores_nothing_and_says_nothing():
    assert _C.person_bonus({"market_match": True})[1] == ["has been in your market"]


def test_build_reads_tenure_off_the_person_row():
    inv = [{"investor": "Creandum", "score": 50, "signals": {}}]
    people = {"creandum": [{"name": "Sabina Wizander", "role": "Partner",
                            "since": "2021-05-18", "source": "cala"}]}
    row = _C.build(inv, people)["rows"][0]
    assert row["signals"]["years_at_firm"] > 5
    assert any("at the firm" in w for w in row["bonus_why"])
