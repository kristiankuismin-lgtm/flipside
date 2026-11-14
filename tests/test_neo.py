"""Ask Neo answers from computed facts, or says it cannot."""
from app import neo as N

CTX = {
    "company": "Gosta Labs", "stage": "series a", "fetched_at": "2026-11-14T17:00:00+00:00",
    "competitors": [{"name": "Corti"}, {"name": "Tandem Health"}],
    "investors": [
        {"investor": "Atomico", "score": 72.8, "rounds_seen": 40, "backs": [],
         "breakdown": {"months_since_activity": 8, "stale": False},
         "signals": {"lead_rate": {"label": "🟢", "value": .8, "text": "Led 4 of 5 series a rounds (80%)"},
                     "follow_on": {"label": "🟢", "value": .88, "text": "Followed on in 7 of 8"},
                     "dry_powder": {"label": "🟢", "text": "7 new investments in 6 months"},
                     "warm_path": {"label": "⚪", "text": None},
                     "conflict": {"label": "🟢", "text": "clear"}}},
        {"investor": "Northzone", "score": 0, "rounds_seen": 30, "backs": ["Tandem Health"],
         "breakdown": {"months_since_activity": 40, "stale": True},
         "signals": {"lead_rate": {"label": "🟡", "value": .3, "text": "Led 3 of 10"},
                     "follow_on": {"label": "🟡", "value": .5, "text": "Followed on in 5 of 10"},
                     "dry_powder": {"label": "🟡", "text": "2 new investments in 6 months"},
                     "warm_path": {"label": "🟢", "text": "via Voima Ventures"},
                     "conflict": {"label": "🔴", "text": "backs Tandem Health"}}},
    ],
    "syndicates": [{"lead": "Atomico", "rounds_led": 8,
                    "members": [{"name": "World Innovation Lab", "joined": 2, "share": .25}]}],
    "backtest": {"samples": 498, "base_rate": .386, "spread_pp": 17.2,
                 "high_insider_return": {"rate": .488, "lift_pp": 10.2},
                 "naive_most_active": {"rate": .414, "lift_pp": 2.8}},
    "health": {"entities_cached": 6418, "rounds_cached": 854, "conviction_n": 197,
               "people_cached": 227, "cache_only": True},
    "contradictions": {"hard": 35, "companies": 80,
                       "items": [{"company": "vanta", "field": "amount",
                                  "a": "€101.2M", "b": "€36.8M"}]},
}


def ask(q):
    return N.answer(q, CTX)


def test_a_named_fund_turns_a_ranking_question_into_a_profile():
    a = ask("what about Atomico?")
    assert a["topic"] == "fund" and "Atomico" in a["headline"]
    assert any("80%" in b for b in a["bullets"])


def test_the_longest_matching_name_wins():
    """"Index" must not match inside "Index Ventures" and pick the wrong row."""
    ctx = {**CTX, "investors": CTX["investors"] + [
        {"investor": "Index Ventures", "score": 65, "backs": [], "signals":
         {"lead_rate": {"label": "🟢", "value": .5, "text": "Led 6 of 12"},
          "follow_on": {}, "dry_powder": {}, "warm_path": {"label": "⚪"},
          "conflict": {"label": "🟢"}}}]}
    assert N.named_investor("tell me about Index Ventures", ctx["investors"])["investor"] \
        == "Index Ventures"


def test_a_conflicted_fund_leads_with_the_refusal():
    a = ask("should I pitch Northzone?")
    assert "do not pitch" in a["headline"].lower()
    assert "Tandem Health" in a["headline"]


def test_conflicts_are_counted_and_named():
    a = ask("who backs a competitor?")
    assert a["topic"] == "conflict" and a["facts"]["conflicted"] == 1
    assert any("Northzone" in b for b in a["bullets"])


def test_warm_routes_are_named_not_counted_only():
    a = ask("who can introduce me?")
    assert a["topic"] == "warm" and a["facts"]["warm"] == 1
    assert any("Voima Ventures" in b for b in a["bullets"])


def test_no_warm_route_says_so_rather_than_returning_nothing():
    ctx = {**CTX, "investors": [CTX["investors"][0]]}
    a = N.answer("who can introduce me?", ctx)
    assert a["facts"]["warm"] == 0 and "cold" in " ".join(a["bullets"])


def test_the_backtest_answer_carries_both_numbers():
    a = ask("does this actually work?")
    assert a["topic"] == "accuracy" and a["facts"]["samples"] == 498
    joined = a["headline"] + " ".join(a["bullets"])
    assert "10.2" in joined and "2.8" in joined     # ours and the naive baseline


def test_ranking_skips_the_conflicted_fund():
    a = ask("who should I meet first?")
    assert "Atomico" in a["headline"] and "Northzone" not in a["headline"]


def test_syndicate_question_names_who_follows():
    a = ask("who comes in when Atomico leads?")
    assert a["topic"] in ("syndicate", "fund")
    assert "World Innovation Lab" in (a["headline"] + " ".join(a["bullets"]))


def test_stale_evidence_is_reported_with_the_age():
    a = ask("is any of this out of date?")
    assert a["topic"] == "stale" and a["facts"]["stale"] == 1
    assert any("40 months" in b for b in a["bullets"])


def test_disagreements_quote_both_readings():
    a = ask("do your sources contradict each other?")
    assert a["topic"] == "disagree"
    assert "101.2M" in " ".join(a["bullets"]) and "36.8M" in " ".join(a["bullets"])


def test_coverage_answers_with_what_is_actually_held():
    a = ask("how much data is behind this?")
    assert "6,418" in a["headline"]


def test_an_empty_question_offers_somewhere_to_start():
    a = N.answer("", CTX)
    assert a["bullets"] == [] and len(a["followups"]) >= 3


def test_every_answer_carries_followups():
    for q in ("who should I meet first?", "who backs a competitor?",
              "does this work?", "what about Atomico?"):
        assert ask(q)["followups"], q


# ---- rules decide, the model only writes ----
def test_a_model_may_not_reach_past_the_computed_facts():
    from app import numbercheck as NC
    facts = ("Atomico scores 72.8 out of 100. Led 4 of 5 series a rounds (80%).")
    good = "Atomico leads 80% of the time and scores 72.8 here."
    bad = "Atomico leads 80% of the time and has returned 3.4x on 12 exits."
    assert NC.check_against_text(good, facts)[0] is True
    ok, invented = NC.check_against_text(bad, facts)
    assert ok is False and "3.4" in invented and "12" in invented


def test_years_pass_without_a_matching_metric():
    from app import numbercheck as NC
    assert NC.check_against_text("They led a round in 2026.", "no numbers here")[0] is True
