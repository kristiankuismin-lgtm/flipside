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
# One table for every other kind of answer, because they are all the same
# shape - somebody, something they are to it, and the thing - and keeping
# them apart by kind means a new question needs no migration.
_conn.execute("""CREATE TABLE IF NOT EXISTS rows (
    k TEXT PRIMARY KEY, kind TEXT, person TEXT, role TEXT, org TEXT,
    year TEXT, subject TEXT, ts REAL)""")
_conn.execute("CREATE INDEX IF NOT EXISTS rows_kind ON rows(kind)")
_conn.execute("""CREATE TABLE IF NOT EXISTS asked (
    q TEXT PRIMARY KEY, rows INT, ts REAL)""")
_conn.commit()
_lock = threading.Lock()

# What to ask, and what each answer is a table of. The wording matters
# twice over: naming the subject keeps the answer about the subject, and
# asking for the fields by name is what turns a paragraph into rows.
#
# Each kind declares the columns it expects and the aliases the model
# actually returns for them, because "full_name", "person" and "name" all
# come back depending on how the question was phrased.
KINDS: dict[str, dict] = {
    "people": {
        "q": ("List the people who work at {s}, with their full name, their "
              "role or job title, and the firm they work at."),
        "cols": {"person": ("full_name", "person", "name"),
                 "role": ("role", "title", "job_title"),
                 "org": ("firm", "employer", "company", "organisation")},
    },
    "founders": {
        "q": ("List the founders of {s}, with their full name, their role, "
              "and the company they founded."),
        "cols": {"person": ("full_name", "person", "name", "founder"),
                 "role": ("role", "title"),
                 "org": ("company_founded", "company", "startup")},
    },
    "left": {
        "q": ("List the people who have left {s}, with their full name, the "
              "role they held, and the year they left."),
        "cols": {"person": ("full_name", "person", "name"),
                 "role": ("role", "title"),
                 "org": ("company", "employer", "firm"),
                 "year": ("year_left", "year", "departed")},
    },
    "priors": {
        "q": ("List the founders of companies backed by {s} and the companies "
              "they worked at before founding, with the person, the previous "
              "employer, and the company they founded."),
        "cols": {"person": ("person", "full_name", "name", "founder"),
                 "role": ("previous_employer", "prior_employer"),
                 "org": ("company_founded", "company")},
    },
    "board": {
        "q": ("List the board members of {s}'s portfolio companies, with the "
              "person, their role, and the company."),
        "cols": {"person": ("person", "full_name", "name"),
                 "role": ("role", "title"),
                 "org": ("company", "organisation")},
    },
    "rounds": {
        "q": ("List the funding rounds of {s}, with the round name, the date, "
              "the amount, and each investor who participated."),
        "cols": {"person": ("investors", "investor"),
                 "role": ("round", "stage"),
                 "org": ("company",),
                 "year": ("date",)},
    },
}

PEOPLE_AT = KINDS["people"]["q"]


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


def _pick(row: dict, names) -> str:
    for n in names:
        v = row.get(n)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def ask(kind: str, subject: str, *, timeout: float = 240.0) -> int:
    """Put one question about one subject and keep the rows."""
    spec = KINDS.get(kind)
    if not spec:
        return 0
    q = spec["q"].format(s=subject)
    if asked(q):
        return 0
    try:
        r = cala.query(q, return_entities=False, allow_live=True,
                       ttl=30 * 86400, timeout=timeout, retries=1)
    except Exception:
        return 0
    rows = (r or {}).get("results") or []
    cols = spec["cols"]
    new = 0
    with _lock:
        for row in rows:
            if not isinstance(row, dict):
                continue
            person = _pick(row, cols.get("person", ()))
            if not person:
                continue
            role = _pick(row, cols.get("role", ()))
            org = _pick(row, cols.get("org", ())) or subject
            year = _pick(row, cols.get("year", ()))
            k = "|".join((kind, (norm.name(person) or person.lower())[:60],
                          (norm.name(org) or org.lower())[:60], role.lower()[:40]))
            if _conn.execute("SELECT 1 FROM rows WHERE k=?", (k,)).fetchone():
                continue
            _conn.execute("INSERT INTO rows VALUES (?,?,?,?,?,?,?,?)",
                          (k, kind, person, role, org, year, subject, time.time()))
            new += 1
        _conn.commit()
    mark(q, len(rows))
    # "people" also feeds the older table the call list reads.
    if kind == "people":
        store_people([{"name": _pick(r2, cols["person"]),
                       "role": _pick(r2, cols["role"]),
                       "employer": _pick(r2, cols["org"]) or subject}
                      for r2 in rows if isinstance(r2, dict)], source=subject)
    return new


def rows_of(kind: str, limit: int = 4000) -> list[dict]:
    return [{"person": p, "role": r, "org": o, "year": y, "subject": s2}
            for p, r, o, y, s2 in _conn.execute(
                "SELECT person, role, org, year, subject FROM rows "
                "WHERE kind=? LIMIT ?", (kind, limit))]


def kind_stats() -> dict:
    out = {}
    for kind, n in _conn.execute("SELECT kind, count(*) FROM rows GROUP BY kind"):
        out[kind] = n
    return out
