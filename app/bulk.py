"""Cala's query endpoint as a bulk source, not a lookup.

The entity walker reads one record per request and each request asks for
every property and every relationship it declares, which costs three to
five seconds of server time and more than one token of a bucket that
refills about every 1.5 seconds. Measured end to end that is six entities a
minute, and most of the attempts come back 429.

/knowledge/query answers in about the same time and returns forty-four
structured rows: a name, a role and an employer, for people the graph holds
no WORKS_AT edge for in our cache. Same cost, an order of magnitude more
facts, and they are the facts the product is short of - people with roles
at firms, and investors attached to rounds.

So this is the other half of the harvest. The walker keeps collecting whole
entities, because a card needs an entity; this collects the rows a list
needs, and it does it per firm so the answers stay specific enough to be
true. "Who works at Creandum" returns Creandum's people. "Who works at a
venture firm" returns whoever the index reaches for first.

Rows are stored as they arrive and deduplicated on the triple they assert,
because the same person turns up in several answers and a list that counts
them twice is wrong in the direction that flatters us.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from . import cala_client as cala, norm

DB = "bulk.sqlite"

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("""CREATE TABLE IF NOT EXISTS people (
    k TEXT PRIMARY KEY, person TEXT, role TEXT, employer TEXT,
    source TEXT, ts REAL)""")
_conn.execute("""CREATE TABLE IF NOT EXISTS asked (
    q TEXT PRIMARY KEY, rows INT, ts REAL)""")
_conn.commit()
_lock = threading.Lock()

# What to ask about one firm. The wording matters: naming the firm keeps the
# answer about the firm, and asking for the fields by name is what makes the
# result a table rather than a paragraph.
PEOPLE_AT = ("List the people who work at {firm}, with their full name, "
             "their role or job title, and the firm they work at.")


def _key(person: str, employer: str, role: str) -> str:
    return "|".join((norm.name(person) or person.lower(),
                     norm.name(employer) or (employer or "").lower(),
                     (role or "").strip().lower()[:40]))


def store_people(rows: list[dict], *, source: str) -> int:
    """Rows of {name, role, employer} -> the table. Returns how many are new."""
    new = 0
    with _lock:
        for r in rows or []:
            if not isinstance(r, dict):
                continue
            person = str(r.get("name") or r.get("person") or "").strip()
            employer = str(r.get("employer") or r.get("company")
                           or r.get("firm") or "").strip()
            role = str(r.get("role") or r.get("title") or "").strip()
            if not person or not employer:
                continue
            k = _key(person, employer, role)
            cur = _conn.execute("SELECT 1 FROM people WHERE k=?", (k,)).fetchone()
            if cur:
                continue
            _conn.execute("INSERT INTO people VALUES (?,?,?,?,?,?)",
                          (k, person, role, employer, source, time.time()))
            new += 1
        _conn.commit()
    return new


def asked(q: str) -> bool:
    return bool(_conn.execute("SELECT 1 FROM asked WHERE q=?", (q,)).fetchone())


def mark(q: str, n: int) -> None:
    with _lock:
        _conn.execute("REPLACE INTO asked VALUES (?,?,?)", (q, n, time.time()))
        _conn.commit()


def people_at(firm: str, *, timeout: float = 200.0) -> int:
    """Ask who works at one firm and keep what comes back."""
    q = PEOPLE_AT.format(firm=firm)
    if asked(q):
        return 0
    try:
        r = cala.query(q, return_entities=False, allow_live=True,
                       ttl=30 * 86400, timeout=timeout, retries=1)
    except Exception:
        return 0
    rows = (r or {}).get("results") or []
    n = store_people(rows, source=firm)
    mark(q, len(rows))
    return n


def stats() -> dict:
    c = _conn.execute("SELECT count(*), count(DISTINCT employer) FROM people").fetchone()
    q = _conn.execute("SELECT count(*) FROM asked").fetchone()
    return {"people": c[0], "firms": c[1], "queries_asked": q[0]}


def for_firm(firm: str, limit: int = 20) -> list[dict]:
    key = norm.name(firm) or (firm or "").lower()
    out = []
    for p, role, emp, src in _conn.execute(
            "SELECT person, role, employer, source FROM people"):
        if (norm.name(emp) or emp.lower()) == key or (norm.name(src or "") == key):
            out.append({"name": p, "role": role or None, "employer": emp,
                        "source": "cala query"})
    return out[:limit]


def everyone(limit: int = 5000) -> list[dict]:
    return [{"name": p, "role": r, "employer": e, "source": "cala query"}
            for p, r, e in _conn.execute(
                "SELECT person, role, employer FROM people LIMIT ?", (limit,))]
