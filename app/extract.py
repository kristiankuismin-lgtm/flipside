"""Calan vastaukset -> Round-objekteiksi.

Kanoninen kysely on lukittu recon-vertailulla (ks. recon_report.md):

    funding_rounds.investors="<nimi>"

Se oli ainoa muoto, joka antoi yhta aikaa role-kentan JOKAISELLE riville,
kuukauden tarkkuuden paivamaarassa ja summat. Vaihtoehdot havisivat:
  funding_rounds.investor=  -> vain vuosi, summat usein null
  investors.name=X.funding_rounds -> 24 rivia, suppeampi
  X.portfolio / companies.investors= -> ei roolia eika paivamaaraa

VAROITUS: Cala QL on LLM-tulkittu, ei deterministinen. Sama sijoittaja eri
muotoiluilla palautti 18-54 rivia. Siksi KAYTA AINA SAMAA KYSELYA: vain
silloin sijoittajien vertailu keskenaan on reilu. n on otos, ei kokonaisluku.
"""
import re
from datetime import date

from . import cala_client as cala
from .models import Round

# Eksplisiittinen kenttaluettelo, EI dot-notaatiota. Syy on mitattu:
# dot-notaatio 'funding_rounds.investors="X"' palautti eri skeeman joka
# sijoittajalle - Index Venturesille {company,round,amount,date,role},
# Lifelinelle {company,round_type,amount,notes} (ei paivamaaraa) ja
# Northzonelle {company,sector} (pelkka portfoliolista). Kun kentat
# nimetaan kyselyssa, skeema vakautuu ja paivamaarat tulevat mukaan.
CANONICAL = ("List every funding round that {inv} participated in since 2022. "
             "For each round give: the portfolio company name, the round name, "
             "the date, the amount, and whether {inv} led that round.")

# Roolisanasto vaihtelee vastauksesta toiseen: Lead / Led / Lead investor / Co-lead.
_LEAD_WORDS = re.compile(r"^(lead|led|co[\s\-]?lead|yes|true)", re.I)
# Liidikentan NIMI vaihtelee myos: role, led_by_lifeline, northzone_led, lead.
_LEAD_KEY = re.compile(r"\b(lead|led|role)\b|_led|led_", re.I)
# Erottaa puuttuvan kentan nullista: {"role": None} on natiivi tieto
# "ei liidannut", kun taas kentan puuttuminen tarkoittaa ettei dataa ole.
MISSING = object()
_NOT_LEAD = {"no", "false", "none", "null", "participant", "participated", ""}

_MULT = {"k": 1e3, "m": 1e6, "b": 1e9, "bn": 1e9, "million": 1e6,
         "billion": 1e9, "thousand": 1e3}

# Karkea muunnos vertailukelpoisuutta varten. Nayta UI:ssa alkuperainen merkkijono.
_FX_TO_EUR = {"$": 0.92, "€": 1.0, "£": 1.17, "": 0.92}

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def parse_amount(s) -> float | None:
    """'$7.9M' -> 7.9e6*fx, '€15 million' -> 1.5e7, None -> None."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)
    t = str(s).strip()
    if not t or t.lower() in {"null", "none", "undisclosed", "n/a", "-"}:
        return None
    cur = next((c for c in ("$", "€", "£") if c in t), "")
    m = re.search(r"([\d]+(?:[.,]\d+)?)\s*(bn|b|m|k|million|billion|thousand)?", t, re.I)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", "."))
    except ValueError:
        return None
    val *= _MULT.get((m.group(2) or "").lower(), 1.0)
    return round(val * _FX_TO_EUR.get(cur, 0.92), 2)


def parse_date(s) -> date | None:
    """'Oct 2026' | 'Oct 21, 2026' | '2026-04-15' | 2026 -> date (paiva puuttuessa 1.)."""
    if s is None:
        return None
    if isinstance(s, int):
        return date(s, 1, 1) if 1900 < s < 2100 else None
    t = str(s).strip()
    if not t:
        return None
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", t):
        return date(int(m[1]), int(m[2]), int(m[3]))
    # "2022-03" = vuosi-kuukausi (Calan rajatut kyselyt palauttavat tata)
    if m := re.fullmatch(r"(\d{4})-(\d{1,2})", t):
        return date(int(m[1]), min(max(int(m[2]), 1), 12), 1)
    # "2022-2023" = epavarma vali -> ota alkuvuosi
    if m := re.fullmatch(r"(\d{4})\s*[-\u2013]\s*(\d{4})", t):
        return date(int(m[1]), 1, 1)
    if m := re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),?\s*(\d{4})", t):
        return date(int(m[3]), _MONTHS.get(m[1][:3].lower(), 1), int(m[2]))
    if m := re.search(r"([A-Za-z]{3})[a-z]*\s+(\d{4})", t):
        return date(int(m[2]), _MONTHS.get(m[1][:3].lower(), 1), 1)
    if m := re.fullmatch(r"(\d{4})", t):
        return date(int(m[1]), 1, 1)
    return None


def is_lead(role) -> bool:
    """Siettaa kaikki havaitut muodot: True, 'Yes', 'Lead', 'Led', 'Co-lead'."""
    if role is True:
        return True
    if role is False or role is None or role is MISSING:
        return False
    t = str(role).strip()
    if t.lower() in _NOT_LEAD:
        return False
    return bool(_LEAD_WORDS.match(t))


def find_lead_value(r: dict):
    """Etsi liidikentta nimesta riippumatta: role / led_by_x / x_led / lead.

    Palauttaa MISSING jos kenttaa ei ole lainkaan.
    """
    for k, v in r.items():
        if _LEAD_KEY.search(k):
            return v
    return MISSING


def row_to_round(r: dict, inv: str) -> Round | None:
    """Yksi Calan rivi -> Round. None jos rivi on kayttokelvoton."""
    company = r.get("company") or r.get("portfolio_company") or r.get("name")
    d = parse_date(r.get("date") or r.get("year"))
    if not company or not d:
        return None
    raw_lead = find_lead_value(r)
    lead = is_lead(raw_lead)
    return Round(
        company=str(company).strip(),
        date=d,
        # Kentta on joskus 'round', joskus 'stage'.
        stage=str(r.get("round") or r.get("round_name")
                  or r.get("stage") or r.get("round_type") or "").strip(),
        amount_eur=parse_amount(r.get("amount")),
        investors=[inv],          # kysely palauttaa vain haetun sijoittajan rivit
        leads=[inv] if lead else [],
        lead_is_native=raw_lead is not MISSING,
        sources=[],               # query ei anna lahteita; ks. sourcing.py
    )


def investor_rounds(inv: str, **kw) -> list[Round]:
    """Sijoittajan kierrokset kanonisella kyselylla. Hitaita: ~50 s per sijoittaja."""
    resp = cala.query(CANONICAL.format(inv=inv), **kw) or {}
    out = []
    for r in resp.get("results") or []:
        if isinstance(r, dict) and (rd := row_to_round(r, inv)):
            out.append(rd)
    return out
