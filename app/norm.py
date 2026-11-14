"""Nimien ja vaiheiden normalisointi.

Ilman tata jokainen metriikka hajoaa hiljaa: Calan data sisaltaa
"Index Ventures", "Index Ventures LLP" ja "index ventures" samasta
toimijasta, ja `inv in r.investors` palauttaa False -> n=0 -> punainen valo.
"""
import re

# Yhtiomuodot ja muut hannat, jotka eivat erota toimijoita toisistaan.
_SUFFIXES = {
    "ltd", "limited", "llp", "llc", "lp", "inc", "incorporated", "corp",
    "corporation", "plc", "oy", "oyj", "ab", "as", "asa", "a/s", "aps",
    "gmbh", "ag", "bv", "nv", "sarl", "sas", "sa", "srl", "spa", "kft",
    "co", "company", "the",
}

_STAGE_CANON = [
    (r"\bpre[\s\-_]?seed\b",            "pre-seed"),
    (r"\bangel\b",                      "pre-seed"),
    (r"\bseed\b",                       "seed"),
    (r"\bseries[\s\-_]?a\b|\bround a\b", "series a"),
    (r"\bseries[\s\-_]?b\b",            "series b"),
    (r"\bseries[\s\-_]?c\b",            "series c"),
    (r"\bseries[\s\-_]?d\b",            "series d"),
    (r"\bseries[\s\-_]?e\b",            "series e"),
    (r"\bgrowth\b|\blate stage\b",      "growth"),
    (r"\bventure round\b|\bventure\b",  "venture"),
]


def name(s: str | None) -> str:
    """Normalisoi toimijan nimi vertailua varten.

    >>> name("Index Ventures LLP") == name("index ventures")
    True
    >>> name("Maki.vc") == name("Maki VC")
    True
    """
    if not s:
        return ""
    s = s.lower().strip()
    s = s.replace("&", " and ")
    # Pisteet ja valimerkit valilyonneiksi: "Maki.vc" -> "maki vc"
    s = re.sub(r"[^\w\s]", " ", s)
    toks = [t for t in s.split() if t and t not in _SUFFIXES]
    return " ".join(toks)


def stage(s: str | None) -> str:
    """Normalisoi rahoitusvaihe kanoniseen muotoon.

    >>> stage("Series A Round")
    'series a'
    >>> stage("Pre-Seed")
    'pre-seed'
    """
    if not s:
        return ""
    t = s.lower().strip()
    for pat, canon in _STAGE_CANON:
        if re.search(pat, t):
            return canon
    return t


def matches(target: str, candidates) -> bool:
    """Onko `target` normalisoituna jossain `candidates`-listassa?"""
    t = name(target)
    if not t:
        return False
    return any(name(c) == t for c in (candidates or []))
