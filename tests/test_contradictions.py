"""Sources disagreeing with each other, said out loud."""
from datetime import date

from app import contradictions as C
from app.models import Round


def R(co, d, stage, amount=None, investors=(), leads=(), sources=()):
    return Round(company=co, date=date.fromisoformat(d), stage=stage,
                 amount_eur=amount, investors=list(investors),
                 leads=list(leads), sources=list(sources))


def test_two_dates_for_the_same_round_are_a_contradiction():
    rs = [R("Wolt", "2016-04-15", "Series A", sources=["https://a"]),
          R("Wolt", "2016-06-01", "Series A", sources=["https://b"])]
    hits = C.find("Wolt", rs)
    assert any(h["field"] == "date" for h in hits)
    d = next(h for h in hits if h["field"] == "date")
    assert d["a"] == "2016-04-15" and d["b"] == "2016-06-01"
    assert d["sources"] == ["https://a", "https://b"]


def test_rounds_far_apart_are_two_rounds_not_a_dispute():
    rs = [R("Wolt", "2016-04-15", "Series A"), R("Wolt", "2018-01-01", "Series A")]
    assert C.find("Wolt", rs) == []


def test_a_different_stage_is_not_the_same_round():
    rs = [R("Wolt", "2016-04-15", "Series A"), R("Wolt", "2016-05-01", "Seed")]
    assert C.find("Wolt", rs) == []


def test_small_amount_differences_are_rounding_not_disagreement():
    rs = [R("Wolt", "2016-04-15", "Series A", 12_500_000),
          R("Wolt", "2016-04-20", "Series A", 13_000_000)]
    assert not any(h["field"] == "amount" for h in C.find("Wolt", rs))


def test_a_large_amount_difference_is_reported_with_both_readings():
    rs = [R("Wolt", "2016-04-15", "Series A", 12_500_000),
          R("Wolt", "2016-04-20", "Series A", 30_000_000)]
    a = next(h for h in C.find("Wolt", rs) if h["field"] == "amount")
    assert "12.5M" in a["detail"] and "30.0M" in a["detail"]


def test_different_leads_on_the_same_round():
    rs = [R("Wolt", "2016-04-15", "Series A", leads=["EQT Ventures"]),
          R("Wolt", "2016-04-20", "Series A", leads=["Index Ventures"])]
    assert any(h["field"] == "lead" for h in C.find("Wolt", rs))


def test_the_same_lead_spelled_differently_is_not_a_disagreement():
    """Name normalisation already knows these are one firm."""
    rs = [R("Wolt", "2016-04-15", "Series A", leads=["EQT Ventures AB"]),
          R("Wolt", "2016-04-20", "Series A", leads=["EQT Ventures"])]
    assert not any(h["field"] == "lead" and not h.get("soft")
                   for h in C.find("Wolt", rs))


def test_co_leads_are_flagged_softly_not_as_an_error():
    rs = [R("Wolt", "2016-04-15", "Series A", leads=["EQT Ventures", "Index Ventures"])]
    hits = C.find("Wolt", rs)
    assert len(hits) == 1 and hits[0]["soft"] is True


def test_summarise_counts_hard_and_soft_separately():
    s = C.summarise({
        "Wolt": [R("Wolt", "2016-04-15", "Series A", leads=["A"]),
                 R("Wolt", "2016-06-01", "Series A", leads=["B"])],
        "Quiet": [R("Quiet", "2020-01-01", "Seed")],
    })
    assert s["companies"] == 1 and s["hard"] >= 2 and s["count"] >= s["hard"]
