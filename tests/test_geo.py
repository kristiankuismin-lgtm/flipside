"""Address -> coordinates. Inputs are real Cala headquarters_address strings."""
from app.geo import locate


def test_city_in_a_comma_address():
    assert locate("Keilaniementie 1, Espoo, Finland")[2] == "FI"
    assert locate("Espoo, Finland")[:2] == (60.21, 24.66)


def test_city_beats_the_country_it_is_in():
    """'Munich, Germany' must land on Munich, not on Berlin."""
    assert locate("Munich, Germany")[:2] == (48.14, 11.58)


def test_country_only_falls_back():
    assert locate("Sweden")[2] == "SE"


def test_venue_text_still_resolves():
    """Cala stores Slush's address as a venue name."""
    assert locate("Messukeskus Helsinki Expo and Convention Centre")[2] == "FI"


def test_unplaceable_returns_none_not_a_guess():
    assert locate(None) is None
    assert locate("") is None
    assert locate("Somewhere nice") is None


def test_diacritic_free_aliases():
    assert locate("Göteborg, Sweden")[2] == "SE"
    assert locate("Køge, Denmark")[2] == "DK"
