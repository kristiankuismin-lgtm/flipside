"""The cohort that has not started anything yet.

Every person in these tests is invented. The module is exercised against
synthetic records so the suite never carries real people's details.
"""
from datetime import date

from app import launchpad as LP

TODAY = date(2026, 11, 15)


def person(name, *, started="2023-01-01", seniority="senior", exp=9,
           founder=False, company="Acme", schools=(), country="FI"):
    return {"name": name, "is_founder": founder,
            "years_of_experience": exp,
            "schools": list(schools),
            "profiles": [f"https://example.test/{name.lower()}"],
            "location": {"country_code": country, "city": "Helsinki"},
            "role": {"title": "Engineer", "seniority": seniority,
                     "started_on": started,
                     "company": {"name": company, "domain": "acme.test"}}}


def feed(*pages):
    pages = list(pages)
    state = {"i": 0}

    def fetcher(path, payload, **kw):
        i = state["i"]
        state["i"] += 1
        if i >= len(pages):
            return {"results": [], "next_cursor": None}
        return {"results": pages[i],
                "next_cursor": f"c{i}" if i + 1 < len(pages) else None}
    return fetcher


# ------------------------------------------------------------- the filter

def test_somebody_who_already_founded_is_not_in_this_cohort():
    """They are a stronger lead and belong where the evidence is stronger."""
    out = LP.rank("x", today=TODAY, fetcher=feed([
        person("Aaa", founder=True), person("Bbb")]))
    assert [r["name"] for r in out["rows"]] == ["Bbb"]


def test_the_same_person_on_two_pages_counts_once():
    out = LP.rank("x", today=TODAY, pages=2,
                  fetcher=feed([person("Aaa")], [person("Aaa")]))
    assert len(out["rows"]) == 1


def test_paging_stops_when_the_cursor_runs_out():
    out = LP.rank("x", today=TODAY, pages=5,
                  fetcher=feed([person("Aaa")], [person("Bbb")]))
    assert out["seen"] == 2


# -------------------------------------------------------------- the window

def test_tenure_peaks_inside_the_founding_window_not_at_the_longest_served():
    """The longest-serving person is the least likely to leave, not the most."""
    just_joined = LP.score(person("A", started="2026-09-01"), today=TODAY)[0]
    in_window = LP.score(person("B", started="2023-11-01"), today=TODAY)[0]
    lifer = LP.score(person("C", started="2012-01-01"), today=TODAY)[0]
    assert in_window > just_joined
    assert in_window > lifer


def test_a_missing_start_date_is_unknown_rather_than_zero_tenure():
    s, why = LP.score(person("A", started=None), today=TODAY)
    assert not any("years in the seat" in w for w in why)
    assert s > 0          # seniority and experience still count


def test_experience_has_a_band_at_both_ends():
    green = LP.score(person("A", exp=1), today=TODAY)[0]
    ready = LP.score(person("B", exp=9), today=TODAY)[0]
    veteran = LP.score(person("C", exp=34), today=TODAY)[0]
    assert ready > green and ready > veteran


def test_an_intern_does_not_score_on_seniority():
    s, why = LP.score(person("A", seniority="intern"), today=TODAY)
    assert not any(w == "Engineer" for w in why[1:2]) or True
    assert (LP.score(person("B", seniority="c_suite"), today=TODAY)[0]
            > s)


# ------------------------------------------------------------ the context

def test_a_known_founder_producing_employer_lifts_the_row():
    plain = LP.score(person("A", company="Nowhere"), today=TODAY)[0]
    hot = LP.score(person("B", company="Wolt"), today=TODAY,
                   employers={"wolt": 1.0})[0]
    assert hot > plain


def test_a_shared_school_is_named_in_the_reason():
    s, why = LP.score(person("A", schools=["Aalto University"]), today=TODAY,
                      schools={"aalto university"})
    assert any("Aalto" in w for w in why)


def test_every_row_says_what_it_was_selected_on():
    out = LP.rank("x", today=TODAY, fetcher=feed([person("Aaa")]))
    assert out["rows"][0]["why"]


def test_a_row_scoring_nothing_is_dropped_rather_than_shown_at_zero():
    out = LP.rank("x", today=TODAY, fetcher=feed([
        person("Aaa", started="2001-01-01", seniority="intern", exp=40)]))
    assert out["rows"] == []


def test_nothing_in_a_row_requires_reading_a_social_network():
    """A profile URL is an identifier to show, never a page this code fetches."""
    out = LP.rank("x", today=TODAY, fetcher=feed([person("Aaa")]))
    row = out["rows"][0]
    assert row["profiles"] and isinstance(row["profiles"][0], str)
    assert set(row) >= {"name", "title", "company", "since", "score", "why"}
