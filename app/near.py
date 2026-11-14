"""What is around the founder, ranked by how far away it actually is.

A founder at Slush does not need the whole European map. They need the funds
within reach of where they are standing - and, once the screen has run, which
of those actually lead at their stage.

Distance is computed on the great circle rather than on degrees, because a
degree of longitude in Helsinki is 55km and in Lagos it is 111km, and a naive
sort by |dlat| + |dlon| quietly puts the wrong fund first at Nordic latitudes.
"""
from __future__ import annotations

import re
from math import asin, cos, radians, sin, sqrt

EARTH_KM = 6371.0088


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = p2 - p1, radians(lon2 - lon1)
    h = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_KM * asin(sqrt(min(1.0, h)))


def rank(points: list[dict], lat: float, lon: float, *, radius_km: float = 300,
         limit: int = 40, kinds: set[str] | None = None) -> list[dict]:
    """Points inside the radius, nearest first, each carrying its distance.

    A point placed on a city centroid is kept but marked: "4km away" is a
    promise the geocode cannot keep when all we know is the city.
    """
    out = []
    for p in points or []:
        if kinds and (p.get("kind") or "exhibitor") not in kinds:
            continue
        if p.get("lat") is None or p.get("lon") is None:
            continue
        d = haversine(lat, lon, p["lat"], p["lon"])
        if d > radius_km:
            continue
        out.append({**p, "km": round(d, 1), "approx": not p.get("precise")})
    out.sort(key=lambda x: x["km"])
    return out[:limit]


# "Lapinlahdenkatu 16 5, 00180, Helsinki, Finland" and
# "PL 358, 00181 HELSINKI, FI-001" are the same city. Splitting on the first
# comma says they are "Lapinlahdenkatu 16 5" and "PL 358".
_POSTCODE = re.compile(r"^(?:[A-Z]{1,2}[-\s]?)?\d[\d\s-]*")
_COUNTRYISH = re.compile(r"^[A-Z]{2,3}(?:-\d+)?$")
_STREETISH = re.compile(r"\d")
_BOX = re.compile(r"\b(p\.?o\.?\s*box|pl|box|postboks|postfach)\b", re.I)


def city_of(address: str | None) -> str | None:
    """The city inside a postal address, read from the end backwards.

    Addresses arrive in half a dozen national layouts, but they almost all
    put the city after the street and before the country, so scanning from
    the end and skipping postcodes, PO boxes and country names beats trying
    to match a layout. A known city wins outright; otherwise the last
    plausible token stands, because an unlisted city is still a city.
    """
    from . import geo
    parts = [x.strip() for x in (address or "").split(",") if x and x.strip()]
    fallback = None
    for part in reversed(parts):
        if _COUNTRYISH.match(part) or _BOX.search(part):
            continue
        cand = _POSTCODE.sub("", part).strip(" -,")
        if not cand or len(cand) < 2 or _STREETISH.search(cand):
            continue
        if cand.lower() in geo.COUNTRIES:
            continue
        pretty = cand.title() if (cand.isupper() or cand.islower()) else cand
        if cand.lower() in geo.CITIES:
            return pretty
        fallback = fallback or pretty
    return fallback


def group_by_city(points: list[dict]) -> list[dict]:
    """Collapse to the places themselves, nearest first.

    Twelve pins in Helsinki is not twelve answers to "what is near me".
    """
    seen: dict[str, dict] = {}
    for p in points:
        city = city_of(p.get("hq")) or "Unknown"
        g = seen.setdefault(city.lower(), {"city": city, "km": p["km"], "items": []})
        g["items"].append(p)
        g["km"] = min(g["km"], p["km"])
    return sorted(seen.values(), key=lambda g: g["km"])
