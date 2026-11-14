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
