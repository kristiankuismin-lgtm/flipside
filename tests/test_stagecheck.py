"""Is the round you said you are raising the round you are raising?

A founder who types "Series B" off a seed gets a list that costs them the
week: Series B funds will not write the cheque and the Series A funds who
would are not on it. Every assertion here pins something the check is
allowed to say, or refuses to.
"""
from datetime import date

from app import stagecheck as SC

TODAY = date(2026, 11, 15)
SEED = [{"stage": "Seed", "date": "2025-11-01"}]


def test_the_next_stage_is_consistent():
    r = SC.check(SEED, "series a", today=TODAY)
    assert r["verdict"] == "consistent" and r["severity"] == "ok"


def test_skipping_a_stage_is_warned_and_names_what_was_skipped():
    r = SC.check(SEED, "series b", today=TODAY)
    assert r["verdict"] == "ahead" and r["severity"] == "warn"
    assert "skips series a" in r["says"]


def test_the_same_stage_again_is_a_note_not_a_warning():
    """A bridge is a real round, and the funds who lead one differ."""
    r = SC.check(SEED, "seed", today=TODAY)
    assert r["verdict"] == "same stage" and r["severity"] == "note"
    assert "bridge" in r["says"]


def test_asking_for_an_earlier_stage_says_which_is_wrong_is_unknown():
    r = SC.check(SEED, "pre-seed", today=TODAY)
    assert r["verdict"] == "behind"
    assert "if the record is wrong, it is the record" in r["says"]


# ------------------------------------------------- what it must not claim
def test_no_history_is_not_approval():
    """Silence must not read as a yes."""
    r = SC.check([], "series b", today=TODAY)
    assert r["verdict"] == "no history" and r["severity"] == "unknown"
    assert "nothing to check" in r["says"]


def test_rounds_with_no_dates_cannot_be_sequenced():
    r = SC.check([{"stage": "Seed"}, {"stage": "Series A"}], "series b", today=TODAY)
    assert r["verdict"] == "undated" and r["severity"] == "unknown"


def test_a_stage_we_do_not_recognise_is_not_a_disagreement():
    assert SC.check(SEED, "bridge", today=TODAY)["severity"] == "unknown"
    assert SC.check([{"stage": "Venture round", "date": "2025-01-01"}],
                    "series a", today=TODAY)["severity"] == "unknown"


def test_the_latest_dated_round_is_the_one_compared_against():
    rounds = [{"stage": "Series A", "date": "2024-01-01"},
              {"stage": "Seed", "date": "2022-01-01"}]
    assert "Series A" in SC.check(rounds, "series b", today=TODAY)["last"]


def test_an_undated_round_does_not_displace_a_dated_one():
    rounds = [{"stage": "Seed", "date": "2025-11-01"}, {"stage": "Series C"}]
    assert SC.check(rounds, "series a", today=TODAY)["verdict"] == "consistent"


def test_a_round_dated_in_the_future_is_not_counted_as_age():
    r = SC.check([{"stage": "Seed", "date": "2099-01-01"}], "series a", today=TODAY)
    assert "months ago" not in r["says"]


# ------------------------------------------------------------- staleness
def test_an_old_last_round_is_flagged_separately():
    old = [{"stage": "Seed", "date": "2022-01-01"}]
    s = SC.stale(old, today=TODAY)
    assert s and s["months"] > SC.STALE_MONTHS


def test_a_recent_round_is_not_stale():
    assert SC.stale(SEED, today=TODAY) is None


def test_nothing_on_record_is_not_stale():
    assert SC.stale([], today=TODAY) is None
