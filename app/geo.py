"""Turn Cala's headquarters_address strings into map coordinates.

Cala gives addresses as free text ("Messukeskus Helsinki Expo and Convention
Centre", "Espoo, Finland"), not coordinates. Rather than call a geocoding
service - which would add a dependency and put a third party between the
graph and the map - we resolve against a built-in table of the cities and
countries that actually appear in European startup data.

Anything we cannot place is reported as unplaced rather than dropped or
guessed onto a country centroid.
"""
import re

# city -> (lat, lon, country)
CITIES = {
    "helsinki": (60.17, 24.94, "FI"), "espoo": (60.21, 24.66, "FI"),
    "tampere": (61.50, 23.79, "FI"), "turku": (60.45, 22.27, "FI"),
    "oulu": (65.01, 25.47, "FI"), "vantaa": (60.29, 25.04, "FI"),
    "stockholm": (59.33, 18.07, "SE"), "gothenburg": (57.71, 11.97, "SE"),
    "goteborg": (57.71, 11.97, "SE"), "malmo": (55.60, 13.00, "SE"),
    "uppsala": (59.86, 17.64, "SE"), "lund": (55.70, 13.19, "SE"),
    "oslo": (59.91, 10.75, "NO"), "bergen": (60.39, 5.32, "NO"),
    "trondheim": (63.43, 10.39, "NO"),
    "copenhagen": (55.68, 12.57, "DK"), "kobenhavn": (55.68, 12.57, "DK"),
    "aarhus": (56.16, 10.20, "DK"), "odense": (55.40, 10.39, "DK"),
    "reykjavik": (64.15, -21.94, "IS"),
    "tallinn": (59.44, 24.75, "EE"), "tartu": (58.38, 26.72, "EE"),
    "riga": (56.95, 24.11, "LV"), "vilnius": (54.69, 25.28, "LT"),
    "kaunas": (54.90, 23.90, "LT"),
    "london": (51.51, -0.13, "GB"), "cambridge": (52.21, 0.12, "GB"),
    "oxford": (51.75, -1.26, "GB"), "manchester": (53.48, -2.24, "GB"),
    "edinburgh": (55.95, -3.19, "GB"), "bristol": (51.45, -2.59, "GB"),
    "leeds": (53.80, -1.55, "GB"), "glasgow": (55.86, -4.25, "GB"),
    "dublin": (53.35, -6.26, "IE"), "cork": (51.90, -8.47, "IE"),
    "paris": (48.86, 2.35, "FR"), "lyon": (45.76, 4.84, "FR"),
    "toulouse": (43.60, 1.44, "FR"), "marseille": (43.30, 5.37, "FR"),
    "bordeaux": (44.84, -0.58, "FR"), "lille": (50.63, 3.06, "FR"),
    "nantes": (47.22, -1.55, "FR"), "grenoble": (45.19, 5.72, "FR"),
    "berlin": (52.52, 13.40, "DE"), "munich": (48.14, 11.58, "DE"),
    "munchen": (48.14, 11.58, "DE"), "hamburg": (53.55, 9.99, "DE"),
    "frankfurt": (50.11, 8.68, "DE"), "cologne": (50.94, 6.96, "DE"),
    "koln": (50.94, 6.96, "DE"), "stuttgart": (48.78, 9.18, "DE"),
    "dusseldorf": (51.23, 6.78, "DE"), "leipzig": (51.34, 12.37, "DE"),
    "karlsruhe": (49.01, 8.40, "DE"), "dresden": (51.05, 13.74, "DE"),
    "amsterdam": (52.37, 4.90, "NL"), "rotterdam": (51.92, 4.48, "NL"),
    "utrecht": (52.09, 5.12, "NL"), "eindhoven": (51.44, 5.48, "NL"),
    "delft": (52.01, 4.36, "NL"), "the hague": (52.08, 4.31, "NL"),
    "brussels": (50.85, 4.35, "BE"), "antwerp": (51.22, 4.40, "BE"),
    "ghent": (51.05, 3.72, "BE"), "leuven": (50.88, 4.70, "BE"),
    "zurich": (47.38, 8.54, "CH"), "geneva": (46.20, 6.14, "CH"),
    "lausanne": (46.52, 6.63, "CH"), "basel": (47.56, 7.59, "CH"),
    "zug": (47.17, 8.52, "CH"),
    "vienna": (48.21, 16.37, "AT"), "wien": (48.21, 16.37, "AT"),
    "graz": (47.07, 15.44, "AT"), "linz": (48.31, 14.29, "AT"),
    "madrid": (40.42, -3.70, "ES"), "barcelona": (41.39, 2.17, "ES"),
    "valencia": (39.47, -0.38, "ES"), "bilbao": (43.26, -2.93, "ES"),
    "malaga": (36.72, -4.42, "ES"), "seville": (37.39, -6.00, "ES"),
    "lisbon": (38.72, -9.14, "PT"), "porto": (41.15, -8.61, "PT"),
    "milan": (45.46, 9.19, "IT"), "rome": (41.90, 12.50, "IT"),
    "turin": (45.07, 7.69, "IT"), "bologna": (44.49, 11.34, "IT"),
    "naples": (40.85, 14.27, "IT"), "florence": (43.77, 11.26, "IT"),
    "warsaw": (52.23, 21.01, "PL"), "krakow": (50.06, 19.94, "PL"),
    "wroclaw": (51.11, 17.04, "PL"), "poznan": (52.41, 16.93, "PL"),
    "gdansk": (54.35, 18.65, "PL"),
    "prague": (50.08, 14.44, "CZ"), "brno": (49.20, 16.61, "CZ"),
    "budapest": (47.50, 19.04, "HU"), "bratislava": (48.15, 17.11, "SK"),
    "bucharest": (44.43, 26.10, "RO"), "cluj-napoca": (46.77, 23.60, "RO"),
    "sofia": (42.70, 23.32, "BG"), "zagreb": (45.81, 15.98, "HR"),
    "ljubljana": (46.06, 14.51, "SI"), "belgrade": (44.79, 20.45, "RS"),
    "athens": (37.98, 23.73, "GR"), "istanbul": (41.01, 28.98, "TR"),
    "ankara": (39.93, 32.86, "TR"), "izmir": (38.42, 27.14, "TR"),
    "kyiv": (50.45, 30.52, "UA"), "kiev": (50.45, 30.52, "UA"),
    "lviv": (49.84, 24.03, "UA"), "tel aviv": (32.09, 34.78, "IL"),
    "san francisco": (37.77, -122.42, "US"), "new york": (40.71, -74.01, "US"),
    "boston": (42.36, -71.06, "US"), "palo alto": (37.44, -122.14, "US"),
    "mountain view": (37.39, -122.08, "US"), "seattle": (47.61, -122.33, "US"),
    "austin": (30.27, -97.74, "US"), "los angeles": (34.05, -118.24, "US"),
    "chicago": (41.88, -87.63, "US"), "miami": (25.76, -80.19, "US"),
    "toronto": (43.65, -79.38, "CA"), "montreal": (45.50, -73.57, "CA"),
    "vancouver": (49.28, -123.12, "CA"),
    "singapore": (1.35, 103.82, "SG"), "tokyo": (35.68, 139.69, "JP"),
    "bangalore": (12.97, 77.59, "IN"), "bengaluru": (12.97, 77.59, "IN"),
    "mumbai": (19.08, 72.88, "IN"), "delhi": (28.61, 77.21, "IN"),
    "sydney": (-33.87, 151.21, "AU"), "melbourne": (-37.81, 144.96, "AU"),
    "dubai": (25.20, 55.27, "AE"), "sao paulo": (-23.55, -46.63, "BR"),
    "mexico city": (19.43, -99.13, "MX"), "cape town": (-33.92, 18.42, "ZA"),
    "nairobi": (-1.29, 36.82, "KE"), "lagos": (6.52, 3.38, "NG"),
    "hong kong": (22.32, 114.17, "HK"), "seoul": (37.57, 126.98, "KR"),
}

# Fallback: country name -> a representative point (used only when no city hits)
COUNTRIES = {
    "finland": (60.17, 24.94, "FI"), "sweden": (59.33, 18.07, "SE"),
    "norway": (59.91, 10.75, "NO"), "denmark": (55.68, 12.57, "DK"),
    "estonia": (59.44, 24.75, "EE"), "latvia": (56.95, 24.11, "LV"),
    "lithuania": (54.69, 25.28, "LT"), "iceland": (64.15, -21.94, "IS"),
    "united kingdom": (51.51, -0.13, "GB"), "england": (51.51, -0.13, "GB"),
    "ireland": (53.35, -6.26, "IE"), "france": (48.86, 2.35, "FR"),
    "germany": (52.52, 13.40, "DE"), "netherlands": (52.37, 4.90, "NL"),
    "belgium": (50.85, 4.35, "BE"), "switzerland": (47.38, 8.54, "CH"),
    "austria": (48.21, 16.37, "AT"), "spain": (40.42, -3.70, "ES"),
    "portugal": (38.72, -9.14, "PT"), "italy": (45.46, 9.19, "IT"),
    "poland": (52.23, 21.01, "PL"), "czechia": (50.08, 14.44, "CZ"),
    "czech republic": (50.08, 14.44, "CZ"), "hungary": (47.50, 19.04, "HU"),
    "slovakia": (48.15, 17.11, "SK"), "romania": (44.43, 26.10, "RO"),
    "bulgaria": (42.70, 23.32, "BG"), "croatia": (45.81, 15.98, "HR"),
    "slovenia": (46.06, 14.51, "SI"), "serbia": (44.79, 20.45, "RS"),
    "greece": (37.98, 23.73, "GR"), "turkey": (41.01, 28.98, "TR"),
    "ukraine": (50.45, 30.52, "UA"), "israel": (32.09, 34.78, "IL"),
    "united states": (37.77, -122.42, "US"), "usa": (37.77, -122.42, "US"),
    "canada": (43.65, -79.38, "CA"), "singapore": (1.35, 103.82, "SG"),
    "japan": (35.68, 139.69, "JP"), "india": (12.97, 77.59, "IN"),
    "australia": (-33.87, 151.21, "AU"), "brazil": (-23.55, -46.63, "BR"),
    "luxembourg": (49.61, 6.13, "LU"), "malta": (35.90, 14.51, "MT"),
    "cyprus": (35.17, 33.36, "CY"),
}

_SPLIT = re.compile(r"[,;/|]| - ")


def locate(address: str | None) -> tuple[float, float, str] | None:
    """(lat, lon, country) or None when the address cannot be placed."""
    if not address:
        return None
    text = address.lower()
    # City match wins: it is more specific than the country it sits in.
    for part in reversed([p.strip() for p in _SPLIT.split(text) if p.strip()]):
        if part in CITIES:
            return CITIES[part]
    for city, v in CITIES.items():
        if re.search(rf"\b{re.escape(city)}\b", text):
            return v
    for country, v in COUNTRIES.items():
        if re.search(rf"\b{re.escape(country)}\b", text):
            return v
    return None


# A city whose name is strongly associated with one country. Used to catch
# addresses that contradict themselves: Cala has a company at "San Fransisco,
# France", and Nominatim obligingly found a place by that name near Toulon.
# The geocode is right; the address is wrong, and plotting it confidently
# would put a US company in Provence.
CITY_COUNTRY = {
    "san francisco": "US", "san fransisco": "US", "new york": "US",
    "palo alto": "US", "mountain view": "US", "boston": "US", "seattle": "US",
    "austin": "US", "los angeles": "US", "chicago": "US", "miami": "US",
    "london": "GB", "cambridge": "GB", "oxford": "GB", "manchester": "GB",
    "paris": "FR", "berlin": "DE", "munich": "DE", "hamburg": "DE",
    "amsterdam": "NL", "stockholm": "SE", "helsinki": "FI", "espoo": "FI",
    "oslo": "NO", "copenhagen": "DK", "zurich": "CH", "vienna": "AT",
    "madrid": "ES", "barcelona": "ES", "lisbon": "PT", "milan": "IT",
    "dublin": "IE", "warsaw": "PL", "tallinn": "EE", "singapore": "SG",
}


def contradicts(address: str | None, resolved_cc: str | None) -> str | None:
    """Return the expected country code when the address contradicts itself.

    None means no contradiction detected - which is not the same as correct.
    """
    if not address or not resolved_cc:
        return None
    text = address.lower()
    for city, cc in CITY_COUNTRY.items():
        if re.search(rf"\b{re.escape(city)}\b", text) and cc != resolved_cc:
            return cc
    return None
