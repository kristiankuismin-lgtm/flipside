"""The open encyclopaedia, for the firms whose domain cannot be guessed.

Guessing builds a domain out of the name and reaches "creandum.com". It
cannot reach a16z.com from "Andreessen Horowitz" or project-a.com from
"Project A Ventures" - those are not spellings of the name. Cala knows them
and Cala now returns 402.

Wikidata does too, and it is open: a public API, no key, CC0 data, and the
property we want is the one the firm itself maintains - P856, official
website. P159 is where they are headquartered, which is the other thing 231
of our funds are missing.

The trap is the same one every name lookup has: "Alven" is a French venture
firm and also a family name, and Wikidata's search returns the family name
first. So an entity is only used when it says it is an organisation - by its
instance-of claims, or failing that by a description that reads like one.
A surname is never a fund.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time

import httpx

API = "https://www.wikidata.org/w/api.php"
ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"
UA = "Flipside/0.1 (Junction hackathon; github.com/kristiankuismin-lgtm)"
DB = os.getenv("WIKIDATA_DB", "wikidata.sqlite")
TTL = 30 * 86400

# instance-of values that mean "this is a thing with a website", loosely.
ORG_KINDS = {
    "Q4830453",    # business
    "Q783794",     # company
    "Q891723",     # public company
    "Q6881511",    # enterprise
    "Q1589009",    # privately held company
    "Q5621421",    # venture capital firm
    "Q1633025",    # investment company / fund
    "Q18388277",   # technology company
    "Q43229",      # organization
    "Q167037",     # corporation
    "Q219577",     # holding company
    "Q1125711",    # investment fund
}
# instance-of values that mean "this is not a firm at all".
NOT_ORG = {"Q5",          # human
           "Q101352",     # family name
           "Q202444",     # given name
           "Q4167410",    # disambiguation page
           "Q11266439"}   # Wikimedia template

_NOT_ORG_TEXT = re.compile(
    r"\b(family name|given name|surname|disambiguation|first name|"
    r"municipalit|village|river|commune|footballer|singer|actor)\b", re.I)
_ORG_TEXT = re.compile(
    r"\b(company|firm|corporation|business|venture|capital|investor|"
    r"fund|bank|enterprise|startup|organisation|organization)\b", re.I)

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("PRAGMA busy_timeout=10000")
_conn.execute("CREATE TABLE IF NOT EXISTS w (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()


def _cached(k: str):
    row = _conn.execute("SELECT v, ts FROM w WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < TTL:
        return json.loads(row[0])
    return None


def _store(k: str, v) -> None:
    with _lock:
        _conn.execute("REPLACE INTO w VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


def _get(url, params=None, timeout=20):
    r = httpx.get(url, params=params, headers={"User-Agent": UA}, timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f"wikidata {r.status_code}")
    return r.json()


def looks_like_an_organisation(kinds: set[str], description: str | None) -> bool:
    """Is this entity a firm, rather than a surname that spells like one?

    The instance-of claims decide it when they say anything we recognise.
    When they do not, the English description is the fallback, and it has to
    positively read like an organisation - absence of evidence is not an
    organisation.
    """
    if kinds & NOT_ORG:
        return False
    if kinds & ORG_KINDS:
        return True
    text = description or ""
    if _NOT_ORG_TEXT.search(text):
        return False
    return bool(_ORG_TEXT.search(text))


def _claims(entity: dict) -> dict:
    return entity.get("claims") or {}


def _first_value(claims: dict, prop: str):
    for c in claims.get(prop) or []:
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if v:
            return v
    return None


def _ids(claims: dict, prop: str) -> set[str]:
    out = set()
    for c in claims.get(prop) or []:
        v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.add(v["id"])
    return out


def label_of(qid: str, *, getter=None) -> str | None:
    """The English label of one entity, for turning a P159 QID into a city."""
    if not qid:
        return None
    key = f"label:{qid}"
    hit = _cached(key)
    if hit is not None:
        return hit or None
    try:
        data = (getter or _get)(ENTITY.format(qid=qid))
        ent = (data.get("entities") or {}).get(qid) or {}
        lab = ((ent.get("labels") or {}).get("en") or {}).get("value")
    except Exception:                                 # noqa: BLE001
        return None
    _store(key, lab or "")
    return lab


def lookup(name: str, *, searcher=None, getter=None, limit: int = 3) -> dict | None:
    """{website, hq, hq_qid, qid, description} for a firm, or None.

    None means "we could not establish this is a firm", which is different
    from "this firm has no website" - the caller gets `found: False` only
    when nothing matched at all.
    """
    q = (name or "").strip()
    if len(q) < 3:
        return None
    key = f"lookup:{q.lower()}"
    hit = _cached(key)
    if hit is not None:
        return hit or None

    try:
        res = (searcher or _get)(API, {
            "action": "wbsearchentities", "search": q, "language": "en",
            "format": "json", "limit": limit, "type": "item"})
    except Exception:                                 # noqa: BLE001
        return None

    for h in (res.get("search") or [])[:limit]:
        qid = h.get("id")
        if not qid:
            continue
        try:
            data = (getter or _get)(ENTITY.format(qid=qid))
        except Exception:                             # noqa: BLE001
            continue
        ent = (data.get("entities") or {}).get(qid) or {}
        cl = _claims(ent)
        desc = ((ent.get("descriptions") or {}).get("en") or {}).get("value")
        if not looks_like_an_organisation(_ids(cl, "P31"), desc):
            continue
        site = _first_value(cl, "P856")
        hq_v = _first_value(cl, "P159")
        hq_qid = hq_v.get("id") if isinstance(hq_v, dict) else None
        founded = _first_value(cl, "P571")
        out = {
            "qid": qid,
            "website": re.sub(r"^https?://(www\.)?|/$", "", site) if site else None,
            "hq_qid": hq_qid,
            "hq": label_of(hq_qid, getter=getter) if hq_qid else None,
            "founded": (founded or {}).get("time", "")[1:11] if isinstance(founded, dict) else None,
            "description": desc,
        }
        _store(key, out)
        return out

    _store(key, "")      # remember the miss; do not re-ask every page load
    return None
