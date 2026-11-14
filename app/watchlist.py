"""A watchlist that remembers, so a change is a change and not a reread.

The first version checked a watched person when the page opened and showed
whatever it found. That is a search, not an alert: it cannot tell you what
is new because it has nothing to compare against, and everything looks the
same on the second visit as on the first.

So the state lives on disk. Each watched person has a snapshot of what we
last saw - the moves on their record and the news that named them - and the
next check diffs against it. What comes back is what changed, with the date
we first saw it.

No mail is sent. There is no mail to send it from, and saying "we will
email you" would be the easiest sentence here to write and the least true.
What this gives is a watchlist that can say "three things since Tuesday"
rather than showing the same three things every time.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time

DB = os.getenv("WATCH_DB", "watchlist.sqlite")

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("PRAGMA busy_timeout=10000")
_conn.execute("""CREATE TABLE IF NOT EXISTS watch (
    id TEXT PRIMARY KEY, name TEXT, added REAL, checked REAL, seen TEXT)""")
_conn.execute("""CREATE TABLE IF NOT EXISTS events (
    id TEXT, key TEXT, kind TEXT, text TEXT, url TEXT, first_seen REAL,
    acked INT DEFAULT 0, PRIMARY KEY (id, key))""")
_conn.commit()
_lock = threading.Lock()


def _key(kind: str, payload: dict) -> str:
    """What makes two observations the same observation.

    A move is the person plus the company; a story is its link. Using the
    text would make an edited headline a new event.
    """
    if kind == "move":
        return f"move:{payload.get('company', '')}".lower()
    return f"news:{payload.get('url', '')}".lower()


def watching() -> list[dict]:
    rows = _conn.execute(
        "SELECT id, name, added, checked FROM watch ORDER BY added").fetchall()
    return [{"id": r[0], "name": r[1], "added": r[2], "checked": r[3]} for r in rows]


def add(pid: str, name: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR IGNORE INTO watch (id, name, added, checked, seen) "
            "VALUES (?,?,?,?,?)", (pid, name, time.time(), None, "[]"))
        _conn.commit()


def remove(pid: str) -> None:
    with _lock:
        _conn.execute("DELETE FROM watch WHERE id=?", (pid,))
        _conn.execute("DELETE FROM events WHERE id=?", (pid,))
        _conn.commit()


def record(pid: str, moves: list[dict], news: list[dict]) -> list[dict]:
    """Store what we just saw and return only what is new since last time.

    The first check of a newly watched person is the baseline, not a pile of
    alerts: everything about them is new to us and none of it is new to the
    world. It is stored silently and the next change is the first alert.
    """
    now = time.time()
    with _lock:
        row = _conn.execute("SELECT checked FROM watch WHERE id=?", (pid,)).fetchone()
        if row is None:
            return []
        first_check = row[0] is None

        fresh = []
        for kind, items in (("move", moves or []), ("news", news or [])):
            for it in items:
                k = _key(kind, it)
                text = (f"{'founded' if it.get('kind') == 'new_venture' else 'moved to'} "
                        f"{it.get('company')}" if kind == "move" else it.get("title", ""))
                seen = _conn.execute(
                    "SELECT 1 FROM events WHERE id=? AND key=?", (pid, k)).fetchone()
                _conn.execute(
                    "INSERT OR IGNORE INTO events (id,key,kind,text,url,first_seen,acked)"
                    " VALUES (?,?,?,?,?,?,?)",
                    (pid, k, kind, text[:300], it.get("url"), now,
                     1 if first_check else 0))
                if not seen and not first_check:
                    fresh.append({"kind": kind, "text": text, "url": it.get("url"),
                                  "first_seen": now})
        _conn.execute("UPDATE watch SET checked=? WHERE id=?", (now, pid))
        _conn.commit()
    return fresh


def unread(pid: str | None = None) -> list[dict]:
    """Everything seen since the baseline that has not been acknowledged."""
    q = ("SELECT id, key, kind, text, url, first_seen FROM events "
         "WHERE acked=0" + (" AND id=?" if pid else "") + " ORDER BY first_seen DESC")
    rows = _conn.execute(q, (pid,) if pid else ()).fetchall()
    return [{"id": r[0], "key": r[1], "kind": r[2], "text": r[3],
             "url": r[4], "first_seen": r[5]} for r in rows]


def ack(pid: str | None = None) -> int:
    with _lock:
        cur = _conn.execute(
            "UPDATE events SET acked=1 WHERE acked=0" + (" AND id=?" if pid else ""),
            (pid,) if pid else ())
        _conn.commit()
        return cur.rowcount
