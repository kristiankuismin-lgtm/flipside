"""Saannot paattavat, malli vain kirjoittaa.

Kielimalli kirjoittaa korttien perustelut, mutta se ei saa keksia lukuja.
Tama hylkaa tekstin, jossa on luku jota ei loydy lasketuista metriikoista.
Pitchiin: "Rules decide, the model only writes" - ja tama on sen toteutus,
ei lupaus.
"""
import re

# Luvut tekstista: 48%, 7/19, 2026, €2M, 1.5, 17 kk
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
# Vuosiluvut ja jarjestysluvut ovat sallittuja ilman metriikkavastinetta,
# koska ne tulevat kierrosten paivamaarista.
_ALLOW_BARE = re.compile(r"^(19|20)\d{2}$")


def _nums(text: str) -> list[str]:
    return _NUM.findall(text or "")


def _canon(x) -> set[str]:
    """Luku -> sallitut kirjoitusasut. 0.48 -> {'0.48','48','0,48'}."""
    out = set()
    if x is None:
        return out
    try:
        f = float(x)
    except (TypeError, ValueError):
        return out
    for v in (f, f * 100):
        for s in (f"{v:.0f}", f"{v:.1f}", f"{v:.2f}"):
            out.add(s)
            out.add(s.replace(".", ","))
            if "." in s:
                out.add(s.rstrip("0").rstrip("."))
    return out


def allowed_numbers(signals: dict) -> set[str]:
    """Kaikki luvut, joihin teksti saa viitata: arvot, n:t ja signaalien tekstit."""
    ok: set[str] = set()
    for s in (signals or {}).values():
        val = s.get("value") if isinstance(s, dict) else getattr(s, "value", None)
        n = s.get("n") if isinstance(s, dict) else getattr(s, "n", None)
        txt = s.get("text") if isinstance(s, dict) else getattr(s, "text", "")
        ok |= _canon(val) | _canon(n)
        # Signaalin oma teksti on laskettu, joten sen luvut ovat sallittuja
        # ("Liidasi 7/19 seed-kierrosta (37 %)" -> 7, 19, 37).
        ok |= set(_nums(txt or ""))
    return ok


def check(text: str, signals: dict) -> tuple[bool, list[str]]:
    """(hyvaksytty, keksityt_luvut)."""
    ok = allowed_numbers(signals)
    invented = [n for n in _nums(text)
                if n not in ok and not _ALLOW_BARE.match(n)]
    return (not invented), invented


def check_against_text(text: str, source: str) -> tuple[bool, list[str]]:
    """Same rule, when the ground truth is prose rather than signal objects.

    Ask Neo computes its findings as sentences, so the numbers a model may
    use are the numbers already in those sentences.
    """
    ok = set(_nums(source or ""))
    invented = [n for n in _nums(text)
                if n not in ok and not _ALLOW_BARE.match(n)]
    return (not invented), invented


def enforce(text: str, signals: dict, fallback: str = "") -> str:
    """Palauta teksti vain jos se lapaisee. Muuten fallback."""
    passed, _ = check(text, signals)
    return text if passed else fallback
