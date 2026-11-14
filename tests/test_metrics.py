"""Metriikkatestit synteettisella datalla. Ei API-kutsuja, ajettavissa ilman avainta."""
from datetime import timedelta
import pytest

from app import metrics as M
from app.models import Round

T = M.TODAY


def r(company, days_ago, stage, investors, leads=(), native=True):
    return Round(company=company, date=T - timedelta(days=days_ago), stage=stage,
                 amount_eur=1e6, investors=list(investors), leads=list(leads),
                 lead_is_native=native, sources=[f"https://src/{company}"])


# ---- M1 ---------------------------------------------------------------------
def test_lead_rate_laskee_osuuden_ja_antaa_vihrean():
    inv = "Index Ventures"
    rounds = [
        r("A", 100, "seed", [inv, "Accel"], [inv]),
        r("B", 200, "seed", [inv, "Accel"], [inv]),
        r("C", 300, "seed", [inv, "Accel"], ["Accel"]),
        r("D", 400, "seed", [inv, "Accel"], ["Accel"]),
    ]
    s = M.lead_rate(inv, rounds, "seed")
    assert s.n == 4
    assert s.value == 0.5
    assert s.label == "🟢"
    assert "2 of 4" in s.text


def test_lead_rate_normalisoi_yhtiomuodon_REGRESSIO():
    """Calassa sama toimija esiintyy eri kirjoitusasuissa.

    Ennen norm.matches()-korjausta tama palautti 0/3 ja punaisen valon:
    'Index Ventures' != 'Index Ventures LLP'. Juuri tama bugi olisi
    nollannut jokaisen sijoittajan demossa.
    """
    s = M.lead_rate("Index Ventures", [
        r("A", 100, "seed", ["Index Ventures LLP"], ["Index Ventures LLP"]),
        r("B", 200, "seed", ["index ventures"],     ["index ventures"]),
        r("C", 300, "seed", ["Index Ventures."],    ["Accel"]),
    ], "seed")
    assert s.n == 3, "kaikkien kolmen kierroksen pitaa osua ikkunaan"
    assert s.value == pytest.approx(2 / 3)
    assert s.label == "🟢"


def test_lead_rate_normalisoi_vaiheen():
    """'Series A Round' ja 'series-a' ovat sama vaihe."""
    rounds = [r("A", 100, "Series A Round", ["X"], ["X"]),
              r("B", 200, "series-a",       ["X"], ["X"])]
    assert M.lead_rate("X", rounds, "Series A").n == 2


def test_lead_rate_ilman_dataa_on_valkoinen_ei_punainen():
    s = M.lead_rate("X", [], "seed")
    assert s.label == M.NO_DATA
    assert s.value is None
    assert s.n == 0


def test_lead_rate_ei_laske_ikkunan_ulkopuolisia():
    old = r("Vanha", 40 * 30, "seed", ["X"], ["X"])     # ~40 kk sitten
    assert M.lead_rate("X", [old], "seed").n == 0


# ---- M2 ---------------------------------------------------------------------
def test_follow_on_laskee_osallistumisen_seuraavaan_kierrokseen():
    inv = "Lifeline Ventures"
    rounds = [
        # Mukana seuraavalla kierroksella
        r("A", 900, "seed", [inv]), r("A", 300, "series a", [inv, "Accel"]),
        # Ei mukana seuraavalla
        r("B", 900, "seed", [inv]), r("B", 300, "series a", ["Accel"]),
        # Ei seuraavaa kierrosta lainkaan
        r("C", 900, "seed", [inv]),
    ]
    fo, nr = M.follow_on(inv, M.by_company(rounds))
    assert fo.n == 2 and fo.value == 0.5          # 1/2 niista joilla oli seuraava
    assert nr.n == 3 and nr.value == pytest.approx(2 / 3)   # 2/3 nosti 24 kk:ssa


def test_follow_on_jattaa_kypsymattomat_pois():
    """Alle 18 kk vanha sisaantulo ei kelpaa: yhtiolla ei ole ollut aikaa."""
    inv = "X"
    fo, nr = M.follow_on(inv, M.by_company([r("Tuore", 60, "seed", [inv])]))
    assert nr.n == 0
    assert fo.label == M.NO_DATA


# ---- M4 ---------------------------------------------------------------------
def test_dry_powder_tunnistaa_hidastumisen():
    """6 sijoitusta 18 kk:ssa (tahti 2.0/6kk), nyt 0 -> hyytynyt."""
    inv = "Zombie Capital"
    rounds = [r(f"C{i}", 200 + i * 60, "seed", [inv]) for i in range(6)]
    s = M.dry_powder(inv, M.by_company(rounds))
    assert s.value == 0.0
    assert s.label == "🔴"


def test_dry_powder_ilman_dataa_on_valkoinen():
    s = M.dry_powder("X", {})
    assert s.label == M.NO_DATA and s.value is None


# ---- Score ------------------------------------------------------------------
def test_konflikti_nollaa_pisteet():
    from app.models import Signal
    fit = {"stage": 1.0, "sector": 1.0, "geo": 1.0, "check": 1.0}
    sig = {"lead_rate": Signal("lead_rate", .8, "🟢", "", 10, "Korkea")}
    puhdas = M.score(fit, sig)
    sig["conflict"] = Signal("conflict", .9, "🔴", "", 10, "Korkea")
    assert puhdas > 0
    assert M.score(fit, sig) == 0.0


def test_score_ei_kaadu_puuttuviin_signaaleihin():
    assert M.score({"stage": 1, "sector": 1, "geo": 1, "check": 1}, {}) > 0


# ---- score robustness -------------------------------------------------------
def _sig(name, value, n, label="🟢"):
    return M.Signal(name, value, label, "", n, "Medium")


FIT = {"stage": 1.0, "sector": 1.0, "geo": 1.0, "check": 1.0}


def test_a_single_observation_does_not_beat_a_long_record():
    """1-of-1 is a 100% lead rate and almost no evidence."""
    lucky = {"lead_rate": _sig("lead_rate", 1.0, 1)}
    proven = {"lead_rate": _sig("lead_rate", 0.667, 9)}
    assert M.score(FIT, proven) > M.score(FIT, lucky)


def test_the_bound_penalises_small_samples_and_never_flatters_a_zero():
    """Why not shrinkage: a prior of 0.25 lifted 0-of-2 to 0.17, and a fund
    that has never led a Series A ranked first for a Series A."""
    assert M.wilson_lower(1.0, 1) < M.wilson_lower(0.667, 9)   # 1-of-1 < 6-of-9
    assert M.wilson_lower(0.0, 2) == 0.0                       # a zero stays a zero
    assert M.wilson_lower(1.0, 1000) == pytest.approx(1.0, abs=0.02)
    assert M.wilson_lower(None, 10) == 0.0 and M.wilson_lower(0.5, 0) == 0.0


def test_a_fund_that_never_leads_does_not_outrank_one_that_does():
    never = {"lead_rate": _sig("lead_rate", 0.0, 2, "🔴")}
    often = {"lead_rate": _sig("lead_rate", 0.8, 5)}
    assert M.score(FIT, often) > M.score(FIT, never)


def test_an_unknown_signal_is_not_scored_as_zero():
    """The mistake this codebase refuses to make: "no follow-on data" and
    "never follows on" are different claims."""
    unknown = {"lead_rate": _sig("lead_rate", 0.6, 10),
               "follow_on": M.Signal("follow_on", None, M.NO_DATA, "", 0, "Low")}
    zero = {"lead_rate": _sig("lead_rate", 0.6, 10),
            "follow_on": _sig("follow_on", 0.0, 10, "🔴")}
    assert M.score(FIT, unknown) > M.score(FIT, zero)


def test_coverage_discounts_a_score_built_on_one_signal():
    thin = {"lead_rate": _sig("lead_rate", 0.6, 10)}
    full = {"lead_rate": _sig("lead_rate", 0.6, 10),
            "follow_on": _sig("follow_on", 0.6, 10),
            "next_round": _sig("next_round", 0.6, 10),
            "dry_powder": _sig("dry_powder", 0.6, 10)}
    assert M.score(FIT, full) > M.score(FIT, thin)


def test_quality_reports_how_much_was_known():
    q, cov = M.quality({"lead_rate": _sig("lead_rate", 0.6, 10)})
    assert cov == pytest.approx(0.30)
    q2, cov2 = M.quality({})
    assert cov2 == 0.0 and q2 == 0.0      # nothing known earns no quality


def test_a_conflict_still_zeroes_the_score():
    sig = {"lead_rate": _sig("lead_rate", 0.9, 20),
           "conflict": M.Signal("conflict", None, "🔴", "backs a competitor", 1, "High")}
    assert M.score(FIT, sig) == 0


def test_a_fund_that_has_never_led_at_this_stage_is_discounted():
    """The founder is ranking candidates to LEAD. "Led 0 of 9 Series A
    rounds" is close to an answer, not one weak signal among several."""
    never = {"lead_rate": _sig("lead_rate", 0.0, 9, "🔴")}
    assert M.lead_factor(never) == M.NON_LEAD_FACTOR
    some = {"lead_rate": _sig("lead_rate", 0.2, 9, "🟡")}
    assert M.lead_factor(some) == 1.0


def test_too_few_rounds_is_not_evidence_of_not_leading():
    """0 of 2 and "we have barely looked" are the same observation."""
    assert M.lead_factor({"lead_rate": _sig("lead_rate", 0.0, 2, "🔴")}) == 1.0


def test_an_unknown_lead_rate_is_never_penalised():
    unknown = {"lead_rate": M.Signal("lead_rate", None, M.NO_DATA, "", 0, "Low")}
    assert M.lead_factor(unknown) == 1.0
    assert M.lead_factor({}) == 1.0


# ---- recency on the founder side --------------------------------------------
def test_the_founder_ranking_ages_its_evidence_too():
    """The same defect that put a 2022 round at the top of the investor view
    was live here: a fund whose last Series A lead was years ago scored
    identically to one that led one in March."""
    old = {"lead_rate": M.Signal("lead_rate", 0.8, "🟢", "", 5, "Medium",
                                 last_date=T - timedelta(days=5 * 365))}
    fresh = {"lead_rate": M.Signal("lead_rate", 0.8, "🟢", "", 5, "Medium",
                                   last_date=T - timedelta(days=60))}
    assert M.score(FIT, old) < M.score(FIT, fresh)


def test_an_undated_signal_is_treated_as_current():
    """Unknown age must not be punished - that penalises thin coverage twice."""
    assert M.recency_factor(None) == 1.0
    undated = {"lead_rate": M.Signal("lead_rate", 0.8, "🟢", "", 5, "Medium")}
    fresh = {"lead_rate": M.Signal("lead_rate", 0.8, "🟢", "", 5, "Medium",
                                   last_date=T)}
    assert M.score(FIT, undated) == M.score(FIT, fresh)


def test_funds_age_more_slowly_than_companies():
    """A fund with an old record is still a fund; a stale round is weaker
    evidence about a company. The two floors differ on purpose."""
    from app import conviction as K
    assert M.RECENCY_FLOOR > K.RECENCY_FLOOR
    assert M.GRACE_MONTHS > K.GRACE_MONTHS


def test_lead_rate_dates_its_own_claim():
    rs = [r("A", 900, "Series A", ["Fund X"], ["Fund X"]),
          r("B", 100, "Series A", ["Fund X"], ["Fund X"])]
    s = M.lead_rate("Fund X", rs, "series a")
    assert s.last_date == (T - timedelta(days=100))


def test_the_evidence_set_is_the_set_the_rate_is_computed_over():
    """The drawer showed nine rounds including a pre-seed under a claim about
    "6 of 9 series a rounds". Evidence that does not match its claim is worse
    than no evidence. This pins the API's filter to the metric's."""
    rounds = [
        r("A", 100, "Series A", ["Fund X"], ["Fund X"]),
        r("B", 200, "Series A", ["Fund X"], []),
        r("C", 300, "Pre-Seed", ["Fund X"], ["Fund X"]),     # wrong stage
        r("D", 36 * 31, "Series A", ["Fund X"], ["Fund X"]),  # outside window
    ]
    sig = M.lead_rate("Fund X", rounds, "series a")
    # The API builds its evidence rows with exactly this expression.
    evidence = [x for x in rounds
                if x.date >= M.WINDOW and M.norm.stage(x.stage) == M.norm.stage("series a")]
    assert len(evidence) == sig.n == 2
    assert sum(1 for x in evidence if M.norm.matches("Fund X", x.leads)) == 1
    assert sig.value == 0.5
