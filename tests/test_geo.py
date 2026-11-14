"""Address -> coordinates. Inputs are real Cala headquarters_address strings."""
from app import geo
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


def test_self_contradicting_addresses_are_detected():
    """Cala has a company at "San Fransisco, France"; Nominatim finds a real
    place by that name in Toulon. The geocode is right, the address is not."""
    from app.geo import contradicts
    assert contradicts("San Fransisco, France", "FR") == "US"
    assert contradicts("London, Germany", "DE") == "GB"


def test_consistent_addresses_pass():
    from app.geo import contradicts
    assert contradicts("Espoo, Finland", "FI") is None
    assert contradicts("Keilaniementie 1, Espoo", "FI") is None
    assert contradicts(None, "FI") is None
    assert contradicts("Somewhere", None) is None


# ---- a description is a second opinion on a registry address ----
HV = "German venture capital firm headquartered in Munich"
SPARK = "American venture capital firm based in Boston and San Francisco, founded in 2005."
ALLIANCE = "Czech venture capital firm based in Prague, founded in 2018."
INBOX = "A Swedish venture capital firm headquartered in Stockholm, founded in 1985."


def test_a_named_city_beats_the_nationality_adjective():
    c = geo.claimed_place(HV)
    assert c["cc"] == "DE" and c["label"] == "Munich"
    assert (round(c["lat"]), round(c["lon"])) == (48, 12)      # Munich, not Berlin


def test_description_catches_the_namesake_join():
    """These four are real rows out of fund_universe.json."""
    assert geo.disputed(HV, "FI") == "DE"              # LEI landed in Tampere
    assert geo.disputed(SPARK, "EE") == "US"           # LEI landed in Tallinn
    assert geo.disputed(ALLIANCE, "SE") == "CZ"        # LEI landed in Stockholm


def test_an_agreeing_description_is_not_disputed():
    assert geo.disputed(INBOX, "SE") is None


def test_silence_is_not_disagreement():
    assert geo.disputed("A venture capital firm founded in 2005.", "SE") is None
    assert geo.disputed(None, "SE") is None
    assert geo.disputed(HV, None) is None


def test_a_territory_name_is_not_its_nationality_word():
    """"British Virgin Islands-registered ... headquartered in Road Town"
    is a Caribbean fund, and matching "british" puts it in London."""
    c = geo.claimed_place("A British Virgin Islands-registered venture capital "
                          "firm headquartered in Road Town.")
    assert c["cc"] == "VG" and "Virgin" in c["label"]


def test_an_unlisted_city_still_supplies_the_label():
    """We have no coordinate for Menlo Park, but we should still say it."""
    c = geo.claimed_place("American venture capital firm headquartered in "
                          "Menlo Park, California, founded in 1972.")
    assert c["cc"] == "US"
    assert c["label"] == "Menlo Park" and c["approx_label"] is True
