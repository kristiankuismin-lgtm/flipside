import math

from app import near as N

HELSINKI = (60.1699, 24.9384)
TAMPERE = (61.4978, 23.7610)
STOCKHOLM = (59.3293, 18.0686)
LONDON = (51.5074, -0.1278)


def test_distance_matches_the_known_great_circle():
    d = N.haversine(*HELSINKI, *STOCKHOLM)
    assert 390 < d < 405          # Helsinki-Stockholm is ~396km


def test_a_degree_is_not_a_distance():
    """The reason this module does not sort on |dlat| + |dlon|.

    One degree north and one degree east are the same number of degrees from
    Helsinki, so the naive metric calls them equally close. In kilometres the
    eastern one is roughly half as far, because a longitude degree at 60N is
    about 55km against 111km for latitude.
    """
    north = (HELSINKI[0] + 1, HELSINKI[1])
    east = (HELSINKI[0], HELSINKI[1] + 1)
    deg = lambda a: abs(a[0] - HELSINKI[0]) + abs(a[1] - HELSINKI[1])
    assert deg(north) == deg(east)                      # a tie under the naive rule
    dn, de = N.haversine(*HELSINKI, *north), N.haversine(*HELSINKI, *east)
    assert de < dn and dn / de > 1.9                    # and a 2x difference in fact

    pts = [{"name": "north", "lat": north[0], "lon": north[1], "precise": True},
           {"name": "east", "lat": east[0], "lon": east[1], "precise": True}]
    assert [p["name"] for p in N.rank(pts, *HELSINKI)] == ["east", "north"]


def test_radius_excludes_and_keeps_order():
    pts = [{"name": "far", "lat": LONDON[0], "lon": LONDON[1], "precise": True},
           {"name": "mid", "lat": STOCKHOLM[0], "lon": STOCKHOLM[1], "precise": True},
           {"name": "near", "lat": TAMPERE[0], "lon": TAMPERE[1], "precise": True}]
    got = N.rank(pts, *HELSINKI, radius_km=500)
    assert [p["name"] for p in got] == ["near", "mid"]
    assert got[0]["km"] < got[1]["km"]


def test_a_city_centroid_is_kept_but_flagged():
    pts = [{"name": "vague", "lat": TAMPERE[0], "lon": TAMPERE[1], "precise": False}]
    got = N.rank(pts, *HELSINKI, radius_km=500)
    assert got[0]["approx"] is True


def test_kind_filter():
    pts = [{"name": "f", "kind": "fund", "lat": TAMPERE[0], "lon": TAMPERE[1]},
           {"name": "c", "kind": "portfolio", "lat": TAMPERE[0], "lon": TAMPERE[1]}]
    assert [p["name"] for p in N.rank(pts, *HELSINKI, kinds={"fund"})] == ["f"]


def test_city_is_read_from_the_end_not_the_first_comma():
    """Real addresses out of the fund file, which is where this broke."""
    assert N.city_of("PL 358, 00181 HELSINKI, FI-001") == "Helsinki"
    assert N.city_of("Lapinlahdenkatu 16 5, 00180, Helsinki") == "Helsinki"
    assert N.city_of("Hamngatan 11, 111 47, Stockholm, Sweden") == "Stockholm"
    assert N.city_of("Box 7068, 103 86, Stockholm") == "Stockholm"
    assert N.city_of("SKEPPSBRON 18, P.O. BOX 2094, 103 13 STOCKHOLM") == "Stockholm"
    assert N.city_of("Pikk tn 48-4, 10133, Tallinn") == "Tallinn"
    assert N.city_of("") is None


def test_cities_collapse_and_keep_the_nearest_first():
    pts = [{"name": "a", "hq": "Tampere, Finland", "lat": TAMPERE[0], "lon": TAMPERE[1], "precise": True},
           {"name": "b", "hq": "Tampere, Finland", "lat": TAMPERE[0], "lon": TAMPERE[1], "precise": True},
           {"name": "c", "hq": "Stockholm, Sweden", "lat": STOCKHOLM[0], "lon": STOCKHOLM[1], "precise": True}]
    g = N.group_by_city(N.rank(pts, *HELSINKI, radius_km=600))
    assert [x["city"] for x in g] == ["Tampere", "Stockholm"]
    assert len(g[0]["items"]) == 2
