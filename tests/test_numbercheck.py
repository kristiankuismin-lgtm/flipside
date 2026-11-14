"""Lukutarkistus: malli ei saa keksia lukuja."""
from app.numbercheck import check, allowed_numbers, enforce
from app.models import Signal

SIG = {
    "lead_rate": Signal("lead_rate", 0.48, "🟢", "Liidasi 20/42 seed-kierrosta (48%)", 42, "Korkea"),
    "follow_on": Signal("follow_on", 0.69, "🟢", "Osallistui 11/16 seuraavaan kierrokseen (69%)", 16, "Korkea"),
}


def test_laskettu_luku_hyvaksytaan():
    ok, bad = check("He liidaavat 48% kierroksistaan ja jatkavat 69% tapauksista.", SIG)
    assert ok and bad == []


def test_murtoluku_signaalin_tekstista_hyvaksytaan():
    ok, bad = check("Liidasi 20/42 kierrosta.", SIG)
    assert ok, f"keksityiksi luultiin: {bad}"


def test_keksitty_luku_hylataan():
    ok, bad = check("He sijoittavat tyypillisesti 2,5 miljoonaa euroa.", SIG)
    assert not ok and "2,5" in bad


def test_vuosiluku_on_sallittu():
    ok, bad = check("Rahasto perustettiin 2021 ja on aktiivinen.", SIG)
    assert ok and bad == []


def test_enforce_palauttaa_fallbackin():
    assert enforce("Keskikoko on 3,7 M€.", SIG, "(ei perustelua)") == "(ei perustelua)"
    assert enforce("Liidasi 48% kierroksista.", SIG, "x").startswith("Liidasi")


def test_n_arvo_on_sallittu():
    assert "42" in allowed_numbers(SIG) and "16" in allowed_numbers(SIG)


def test_tyhja_teksti_lapaisee():
    assert check("", SIG)[0] and check("Vahva liidi omalla alallasi.", SIG)[0]
