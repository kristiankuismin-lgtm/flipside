"""M5 yhteissijoituspolut. Puhdasta laskentaa cachetusta datasta."""
from datetime import date
from app.warmpath import coinvestments, warm_path, index_histories
from app.models import Round


def r(company, y, stage, investors):
    return Round(company=company, date=date(y, 1, 1), stage=stage, amount_eur=None,
                 investors=list(investors), leads=[], lead_is_native=True, sources=[])


H = index_histories([
    r("Wolt", 2016, "Series A", ["EQT Ventures", "Lifeline Ventures"]),
    r("Wolt", 2018, "Series B", ["83North", "EQT Ventures"]),
    r("ICEYE", 2019, "Series B", ["Lifeline Ventures"]),
    r("ICEYE", 2021, "Series C", ["Molten Ventures"]),
    r("Aiven", 2022, "Series D", ["Atomico"]),
])


def test_sama_kierros_on_vahvin_signaali():
    c = coinvestments("EQT Ventures", "Lifeline Ventures", H)
    assert c and c[0]["weight"] == 1.0
    assert "Series A" in c[0]["text"] and "Wolt" in c[0]["text"]


def test_sama_yhtio_eri_kierroksilla_on_heikompi():
    c = coinvestments("Lifeline Ventures", "Molten Ventures", H)
    assert c and c[0]["weight"] == 0.75


def test_ei_yhteytta_tuottaa_tyhjan():
    assert coinvestments("Atomico", "Lifeline Ventures", H) == []


def test_warm_path_valitsee_parhaan_reitin():
    s = warm_path("EQT Ventures", ["Lifeline Ventures"], H)
    assert s.label == "🟢" and "Lifeline Ventures" in s.text
    assert s.evidence


def test_warm_path_ilman_reittia_on_valkoinen():
    s = warm_path("Atomico", ["Lifeline Ventures"], H)
    assert s.label == "⚪" and s.value == 0


def test_warm_path_ilman_omia_sijoittajia():
    assert warm_path("EQT Ventures", [], H).label == "⚪"


def test_sijoittaja_ei_ole_reitti_itseensa():
    s = warm_path("EQT Ventures", ["EQT Ventures"], H)
    assert s.label == "⚪"


def test_nimen_kirjoitusasu_ei_estaa_polkua():
    s = warm_path("EQT Ventures Oy", ["lifeline ventures"], H)
    assert s.label == "🟢"
