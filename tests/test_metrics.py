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
