"""M3-konfliktitunnistus. detect() on puhdas funktio -> ei API-kutsuja."""
from app.conflict import detect, _tokens

OURA_COMPS = [
    {"name": "Ultrahuman", "what": "Indian metabolism-tracking platform and smart ring maker"},
    {"name": "RingConn", "what": "Smart ring developer specializing in health monitoring"},
    {"name": "Movano", "what": "Health technology company creating medical-grade smart rings"},
]


def test_suora_konflikti_kun_portfoliossa_on_kilpailija():
    port = [{"name": "Figma", "sector": "Design"},
            {"name": "Ultrahuman", "sector": "Health & Wellness"}]
    s = detect("Oura", "smart ring for sleep tracking", OURA_COMPS, port)
    assert s.label == "🔴"
    assert "Ultrahuman" in s.text
    assert s.evidence and "metabolism" in s.evidence[0].claim


def test_nimen_kirjoitusasu_ei_estaa_osumaa():
    """'Ultrahuman Inc.' ja 'Ultrahuman' ovat sama yhtio."""
    s = detect("Oura", "smart ring", OURA_COMPS,
               [{"name": "Ultrahuman Inc.", "sector": "Health"}])
    assert s.label == "🔴"


def test_ei_konfliktia_eri_alalla():
    port = [{"name": "Figma", "sector": "Design Software"},
            {"name": "Anrok", "sector": "Fintech"}]
    s = detect("Oura", "smart ring for sleep tracking", OURA_COMPS, port)
    assert s.label == "🟢" and s.value == 0.0


def test_tyhja_portfolio_on_valkoinen_ei_vihrea():
    """Datan puute ei ole sama asia kuin puhdas portfolio."""
    s = detect("Oura", "smart ring", OURA_COMPS, [])
    assert s.label == "⚪" and s.n == 0


def test_konflikti_nollaa_kokonaispisteet():
    from app import metrics as M
    from app.models import Signal
    fit = {"stage": 1.0, "sector": 1.0, "geo": 1.0, "check": 1.0}
    sig = {"lead_rate": Signal("lead_rate", .8, "🟢", "", 10, "Korkea"),
           "conflict": detect("Oura", "smart ring", OURA_COMPS,
                              [{"name": "Ultrahuman", "sector": "Health"}])}
    assert M.score(fit, sig) == 0.0


def test_tokens_siivoaa_yleissanat():
    assert "platform" not in _tokens("Fintech platform for payments")
    assert "fintech" in _tokens("Fintech platform for payments")


def test_portfolio_kysely_ei_kayta_dot_notaatiota():
    """Regressio: '{investor}.portfolio' palautti Atomicolle ja a16z:lle nolla
    riviä, vaikka Northzonelle 58. Dot-notaation skeema on arvauksen varassa."""
    from app.conflict import PORTFOLIO_Q
    q = PORTFOLIO_Q.format(investor="Atomico")
    assert not q.endswith(".portfolio"), "dot-notaatio on epavakaa"
    assert "company name" in q and "sector" in q, "kentat pitaa nimeta eksplisiittisesti"


def test_gosta_labs_konflikti_northzone():
    """Aito tapaus Calan datasta: Northzonen portfoliossa on Tandem Health,
    joka on Calan nimeama Gosta Labsin suora kilpailija."""
    comps = [{"name": "Tandem Health", "what": "AI clinical documentation, Sweden"},
             {"name": "Abridge", "what": "AI medical scribe, US"}]
    port = [{"name": "Spotify", "sector": "Music"},
            {"name": "Tandem Health", "sector": "Healthcare AI"},
            {"name": "Klarna", "sector": "Fintech"}]
    s = detect("Gosta Labs", "AI clinical documentation for doctors", comps, port)
    assert s.label == "🔴" and "Tandem Health" in s.text
