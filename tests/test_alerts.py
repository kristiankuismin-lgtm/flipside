"""Rules that run against a screen, not promises about email."""
from app import alerts as A

INV = [
    {"investor": "Northzone", "backs": ["Tandem Health"],
     "breakdown": {"months_since_activity": 3},
     "signals": {"dry_powder": {"label": "🟢"}, "lead_rate": {"label": "🟡"}}},
    {"investor": "Maki.vc", "backs": [],
     "breakdown": {"months_since_activity": 40},
     "signals": {"dry_powder": {"label": "🔴", "text": "1 new investment in 6 months"},
                 "lead_rate": {"label": "🟡"}}},
    {"investor": "Atomico", "backs": [],
     "breakdown": {"months_since_activity": 2},
     "signals": {"dry_powder": {"label": "🟢"},
                 "lead_rate": {"label": "🟢", "text": "Led 4 of 5 series a rounds"}}},
]


def test_a_conflict_already_seen_is_not_news():
    fresh = A.evaluate(INV, enabled={"new_conflict"})
    assert fresh[0]["new"] is True and fresh[0]["severity"] == "high"
    old = A.evaluate(INV, enabled={"new_conflict"}, known_conflicts={"Northzone"})
    assert old[0]["new"] is False and old[0]["severity"] == "seen"


def test_name_spelling_does_not_resurface_a_known_conflict():
    old = A.evaluate(INV, enabled={"new_conflict"}, known_conflicts={"Northzone AB"})
    assert old[0]["new"] is False


def test_a_slowed_fund_fires_with_its_numbers():
    got = A.evaluate(INV, enabled={"fund_slowed"})
    assert [g["investor"] for g in got] == ["Maki.vc"]
    assert "1 new investment" in got[0]["detail"]


def test_a_quiet_fund_fires_only_past_the_threshold():
    assert [g["investor"] for g in A.evaluate(INV, enabled={"stale"})] == ["Maki.vc"]
    assert A.evaluate(INV, enabled={"stale"}, stale_months=60) == []


def test_high_severity_sorts_first():
    got = A.evaluate(INV)
    assert got[0]["severity"] == "high"
    assert [g["severity"] for g in got] == sorted(
        [g["severity"] for g in got], key=lambda s: {"high": 0, "medium": 1, "low": 2, "seen": 3}[s])


def test_disabled_rules_do_not_fire():
    assert A.evaluate(INV, enabled=set()) == []


def test_a_competitor_round_names_every_investor_in_it():
    """Each one is a fund the founder can no longer pitch."""
    rbc = {"tandem health": [
        {"date": "2026-09-01", "stage": "Series A",
         "investors": ["Northzone", "Creandum"]},
        {"date": "2019-01-01", "stage": "Seed", "investors": ["Old Fund"]}]}
    got = A.competitor_rounds([{"name": "Tandem Health"}], rbc, today="2026-11-14")
    assert len(got) == 1                       # the 2019 round is long past
    assert got[0]["investors"] == ["Northzone", "Creandum"]
    assert got[0]["months_ago"] == 2
