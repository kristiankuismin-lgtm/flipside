"""Parsereiden testit. Syotteet ovat aitoja arvoja Calan vastauksista."""
from datetime import date
import pytest
from app.extract import parse_amount, parse_date, is_lead, row_to_round


@pytest.mark.parametrize("s,expected", [
    ("$7.9M", 7.9e6 * 0.92), ("$1.0B", 1.0e9 * 0.92),
    ("€15 million", 1.5e7), ("$250M", 250e6 * 0.92),
    (None, None), ("null", None), ("undisclosed", None), ("", None),
])
def test_parse_amount(s, expected):
    got = parse_amount(s)
    assert got is None if expected is None else got == pytest.approx(expected, rel=1e-6)


@pytest.mark.parametrize("s,expected", [
    ("Oct 2026", date(2026, 10, 1)),
    ("Oct 21, 2026", date(2026, 10, 21)),
    ("Aug 2026", date(2026, 8, 1)),
    ("2026-04-15", date(2026, 4, 15)),
    (2026, date(2026, 1, 1)),
    (None, None), ("", None), ("joskus", None),
])
def test_parse_date(s, expected):
    assert parse_date(s) == expected


@pytest.mark.parametrize("role,expected", [
    ("Lead", True), ("Led", True), ("lead investor", True), ("Co-Lead", True),
    ("Participant", False), ("", False), (None, False),
])
def test_is_lead_sietaa_sanastovaihtelua(role, expected):
    """Calan roolisanasto vaihtelee kyselysta toiseen: Lead / Led / Participant."""
    assert is_lead(role) is expected


def test_row_to_round_aito_rivi():
    r = row_to_round(
        {"company": "DesignArena", "round": "Seed", "amount": "$7.9M",
         "date": "Aug 2026", "role": "Lead"}, "Index Ventures")
    assert r.company == "DesignArena"
    assert r.date == date(2026, 8, 1)
    assert r.stage == "Seed"
    assert r.leads == ["Index Ventures"]
    assert r.lead_is_native is True


def test_row_to_round_sietaa_stage_kenttaa_ja_participanttia():
    r = row_to_round(
        {"company": "Alta Finance", "stage": "Series A", "amount": None,
         "year": 2026, "role": "Participant"}, "X")
    assert r.stage == "Series A" and r.amount_eur is None
    assert r.leads == [] and r.date == date(2026, 1, 1)


def test_row_to_round_hylkaa_kelvottoman():
    assert row_to_round({"round": "Seed"}, "X") is None            # ei yhtiota
    assert row_to_round({"company": "X", "date": "?"}, "X") is None  # ei paivamaaraa


@pytest.mark.parametrize("s,expected", [
    ("2022-03", date(2022, 3, 1)),      # Calan rajattu kysely palauttaa YYYY-MM
    ("2023-04", date(2023, 4, 1)),
    ("2022-2023", date(2022, 1, 1)),    # epavarma vali -> alkuvuosi
])
def test_parse_date_lisamuodot(s, expected):
    assert parse_date(s) == expected


# --- Skeemavaihtelu: samat tiedot, kolme eri muotoa -------------------------
# Cala palauttaa eri kenttanimet eri sijoittajille. Nama ovat aitoja rivejä.
from app.extract import find_lead_value, MISSING

SKEEMAT = [
    # Index Ventures -tyyli: role-merkkijono
    ({"company": "DesignArena", "round": "Seed", "amount": "$7.9M",
      "date": "Aug 2026", "role": "Lead"}, True),
    ({"company": "Instinct", "round": "Series B", "amount": "$250M",
      "date": "Sep 2026", "role": None}, False),
    # Lifeline-tyyli: led_by_<nimi> booleanina
    ({"company": "CurifyLabs", "round": "Seed (equity)", "date": "Apr 2022",
      "amount": "€2M", "led_by_lifeline": True}, True),
    ({"company": "Mjuk", "round": "Seed", "date": "Apr 2022",
      "amount": "$4.2M", "led_by_lifeline": False}, False),
    # Northzone-tyyli: <nimi>_led merkkijonona Yes/No
    ({"company": "Heygo", "round": "Series A", "date": "Feb 2022",
      "amount": "$20M", "northzone_led": "Yes"}, True),
    ({"company": "Personio", "round": "Series E", "date": "Jun 2022",
      "amount": "$200M", "northzone_led": "No"}, False),
]


@pytest.mark.parametrize("row,expect_lead", SKEEMAT)
def test_row_to_round_sietaa_skeemavaihtelua(row, expect_lead):
    """Liidikentan nimi JA arvotyyppi vaihtelevat sijoittajittain."""
    r = row_to_round(row, "X")
    assert r is not None, "rivin pitaa parsiutua"
    assert bool(r.leads) is expect_lead
    assert r.lead_is_native is True
    assert r.stage, "vaihe pitaa loytya kentasta round/round_name/stage/round_type"


def test_find_lead_value_loytaa_kentan_nimesta_riippumatta():
    assert find_lead_value({"role": "Lead"}) == "Lead"
    assert find_lead_value({"led_by_lifeline": True}) is True
    assert find_lead_value({"northzone_led": "Yes"}) == "Yes"
    assert find_lead_value({"lead": False}) is False
    assert find_lead_value({"company": "X", "amount": "$1M"}) is MISSING


def test_round_type_kentta_kelpaa_vaiheeksi():
    r = row_to_round({"company": "Wolt", "round_type": "Series E",
                      "date": "Jan 2021", "amount": "$530M"}, "X")
    assert r.stage == "Series E"
