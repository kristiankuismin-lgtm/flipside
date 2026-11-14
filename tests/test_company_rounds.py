"""Kierrosten ryhmittely (round, investor) -pareista. Syotteet aitoja Calan vastauksia."""
from datetime import date
from unittest.mock import patch

from app.company_rounds import company_history

WOLT_ROWS = [
    {"round_name": "Seed", "date": "November 2014", "investor": "Lifeline Ventures", "lead": True},
    {"round_name": "Seed", "date": "November 2014", "investor": "Inventure", "lead": True},
    {"round_name": "Seed", "date": "November 2014", "investor": "First Fellow Partners", "lead": False},
    {"round_name": "Seed", "date": "November 10, 2015", "investor": "Lifeline Ventures", "lead": True},
    {"round_name": "Seed", "date": "November 10, 2015", "investor": "Inventure", "lead": False},
    {"round_name": "Series A", "date": "April 15, 2016", "investor": "EQT Ventures", "lead": True},
    {"round_name": "Series A", "date": "April 15, 2016", "investor": "Niklas Zennström", "lead": False},
    {"round_name": "Series B", "date": "January 2018", "investor": "83North", "lead": True},
    {"round_name": "Series B", "date": "January 2018", "investor": "EQT Ventures", "lead": False},
]


def _history(rows):
    with patch("app.company_rounds.cala.query", return_value={"results": rows}):
        return company_history("Wolt")


def test_parit_ryhmittyvat_kierroksiksi():
    rs = _history(WOLT_ROWS)
    assert [r.stage for r in rs] == ["Seed", "Seed", "Series A", "Series B"]
    assert rs[0].date == date(2014, 11, 1)
    assert rs[0].investors == ["Lifeline Ventures", "Inventure", "First Fellow Partners"]
    assert rs[0].leads == ["Lifeline Ventures", "Inventure"]


def test_kierrokset_ovat_aikajarjestyksessa():
    rs = _history(list(reversed(WOLT_ROWS)))
    assert [r.date for r in rs] == sorted(r.date for r in rs)


def test_tarkempi_paivamaara_voittaa():
    """Sama kierros voi tulla muodossa 'November 2015' ja 'November 10, 2015'."""
    rs = _history([
        {"round_name": "Seed", "date": "November 2015", "investor": "A", "lead": False},
        {"round_name": "Seed", "date": "November 10, 2015", "investor": "B", "lead": False},
    ])
    assert len(rs) == 1 and rs[0].date == date(2015, 11, 10)


def test_follow_on_laskee_oikein_aidosta_datasta():
    """EQT tuli A-kierroksella ja osallistui B:hen -> 100 %."""
    from app import metrics as M
    byco = M.by_company(_history(WOLT_ROWS))
    fo, _ = M.follow_on("EQT Ventures", byco)
    assert fo.value == 1.0 and fo.n == 1

    # Lifeline tuli Seed 2014:ssa ja oli mukana myos Seed 2015:ssa -> 100 %
    assert M.follow_on("Lifeline Ventures", byco)[0].value == 1.0

    # First Fellow Partners tuli Seed 2014:ssa muttei jatkanut Seed 2015:een -> 0 %
    fo2, _ = M.follow_on("First Fellow Partners", byco)
    assert fo2.value == 0.0 and fo2.n == 1


def test_kelvottomat_rivit_sivuutetaan():
    rs = _history([{"round_name": "Seed", "date": "?", "investor": "A"},
                   {"round_name": "Seed", "investor": ""}, "roska"])
    assert rs == []
