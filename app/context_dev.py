"""Context.dev: a people, company and news layer Cala does not have.

Cala is a knowledge graph of firms, rounds and the people attached to them by
an edge. It is very good at what it holds and it does not hold the cohort
this product keeps reaching for: the engineer three years into a job at a
company that produces founders, who has not founded anything yet.

Context.dev sells that as an API. Three things here matter more than the
endpoint list:

  people/search returns is_founder, seniority, started_on and the schools,
  which is the first time this product can ask "who works here, how long
  have they been there, and have they started anything" in one call.

  It is a licensed database with a query interface. That is categorically
  different from pointing a scraper at a social network, and the difference
  is not a technicality: the provider has the relationship with the source,
  the result is a record rather than a page, and nothing here fetches
  linkedin.com. A profile URL that comes back is an identifier to show the
  user, not something this code reads.

  The generic web endpoints - scrape, crawl, search, answers - are a
  scraper. They are pointed at accelerator batch pages and news, which are
  published to be read. They are not pointed at sites whose terms forbid it,
  and routing a prohibited fetch through a vendor would not make it allowed.

Schemas are read from the API's own validation errors rather than from the
docs: every field name below was confirmed by sending something wrong and
being told the right shape, which is the same discipline the Cala client
uses.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

import httpx

BASE = "https://api.context.dev/v1"
KEY = os.getenv("CONTEXT_DEV_API_KEY", "")
DB = os.getenv("CTX_DB", "context.sqlite")
TTL = 14 * 86400

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS c (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
_lock = threading.Lock()

# What the last call cost, so the UI can say it rather than guess.
last_meta: dict = {}


class NoKey(RuntimeError):
    """CONTEXT_DEV_API_KEY is not set."""


class CtxError(RuntimeError):
    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        self.status, self.body = status, body


def _cached(k, ttl=TTL):
    row = _conn.execute("SELECT v, ts FROM c WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < ttl:
        return json.loads(row[0])
    return None


def _store(k, v):
    with _lock:
        _conn.execute("REPLACE INTO c VALUES (?,?,?)", (k, json.dumps(v), time.time()))
        _conn.commit()


def call(path: str, payload: dict | None = None, *, method: str = "POST",
         ttl: float = TTL, cache_only: bool = False, timeout: float = 90.0):
    """One request, cached on the exact payload. Credits are not free."""
    global last_meta
    k = f"{method} {path} " + json.dumps(payload or {}, sort_keys=True)
    hit = _cached(k, ttl)
    if hit is not None:
        last_meta = {"cached": True, "path": path}
        return hit
    if cache_only:
        return None
    if not KEY:
        raise NoKey("CONTEXT_DEV_API_KEY is not set.")
    try:
        r = httpx.request(method, BASE + path, json=payload,
                          headers={"Authorization": f"Bearer {KEY}",
                                   "Content-Type": "application/json"},
                          timeout=timeout)
    except httpx.HTTPError as e:
        raise CtxError(f"Network error: {e}")
    try:
        body = r.json()
    except ValueError:
        raise CtxError(f"{r.status_code} {path}: not JSON", r.status_code,
                       r.text[:300])
    meta = body.get("key_metadata") or {}
    last_meta = {"cached": False, "path": path, "status": r.status_code,
                 "credits_used": meta.get("credits_consumed"),
                 "credits_left": meta.get("credits_remaining")}
    if r.status_code >= 400:
        # The validation errors name the field they wanted, which is how the
        # shapes in this module were established. Keep them readable.
        raise CtxError(f"{r.status_code} {path}: "
                       f"{json.dumps(body.get('message') or body)[:400]}",
                       r.status_code, body)
    _store(k, body)
    return body


def credits() -> dict:
    return {"left": last_meta.get("credits_left"),
            "used": last_meta.get("credits_used")}
