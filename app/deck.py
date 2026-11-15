"""The deck a founder is sending, held somewhere it can be linked to.

A compose link cannot carry an attachment, which left the drawer able to
hand the file back and nothing more. A link it can carry - so the deck is
stored here, served at a URL, and the email contains that.

What a link from this server is, said plainly because the alternative is a
founder discovering it on the other end: it is served by the machine this is
running on. Anyone who can reach that machine can open it; anyone who cannot,
cannot. On a laptop at a demo that is the room. It is not a public URL and
this module does not pretend to be a file host.

The id is random and unguessable, so the link is not discoverable by walking
ids - but it is also not a password. Someone forwarded the link can open it.
That is what a link is for, and it is what the panel says.

Previews: a PDF the browser renders itself. A PowerPoint it cannot, and
nothing here rasterises slides - what it does is read the text out, slide by
slide, which is the same reading the intake already does and is honest about
being an outline rather than a picture.
"""
from __future__ import annotations

import os
import re
import secrets
import sqlite3
import threading
import time

DB = os.getenv("DECK_DB", "decks.sqlite")
MAX_BYTES = 25 * 1024 * 1024
TTL = 7 * 86400          # a deck is for one raise, not forever

TYPES = {
    "pdf": "application/pdf",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "ppt": "application/vnd.ms-powerpoint",
    "key": "application/octet-stream",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "txt": "text/plain",
    "md": "text/markdown",
}

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("PRAGMA busy_timeout=10000")
_conn.execute("""CREATE TABLE IF NOT EXISTS d (
    id TEXT PRIMARY KEY, name TEXT, mime TEXT, body BLOB, ts REAL)""")
_conn.commit()
_lock = threading.Lock()


def ext_of(name: str) -> str:
    return (name.rsplit(".", 1)[-1] if "." in (name or "") else "").lower()


def mime_of(name: str) -> str:
    return TYPES.get(ext_of(name), "application/octet-stream")


def safe_name(name: str) -> str:
    """A filename safe to put in a Content-Disposition header."""
    base = re.sub(r"[^\w .()-]+", "_", (name or "deck").strip())[:80]
    return base or "deck"


def put(name: str, body: bytes) -> dict:
    if not body:
        raise ValueError("empty file")
    if len(body) > MAX_BYTES:
        raise ValueError(f"{len(body) // 1048576} MB is over the "
                         f"{MAX_BYTES // 1048576} MB limit")
    did = secrets.token_urlsafe(12)
    with _lock:
        _conn.execute("INSERT INTO d VALUES (?,?,?,?,?)",
                      (did, safe_name(name), mime_of(name), body, time.time()))
        _conn.commit()
    _sweep()
    return {"id": did, "name": safe_name(name), "mime": mime_of(name),
            "bytes": len(body)}


def get(did: str) -> dict | None:
    row = _conn.execute("SELECT id, name, mime, body, ts FROM d WHERE id=?",
                        (did,)).fetchone()
    if not row:
        return None
    if time.time() - row[4] > TTL:
        return None
    return {"id": row[0], "name": row[1], "mime": row[2], "body": row[3],
            "ts": row[4]}


def _sweep() -> None:
    """A deck is for one raise. Old ones go rather than accumulating."""
    try:
        with _lock:
            _conn.execute("DELETE FROM d WHERE ts < ?", (time.time() - TTL,))
            _conn.commit()
    except sqlite3.Error:
        pass


def outline(name: str, body: bytes) -> dict:
    """What the deck says, for the formats a browser will not render.

    Not a rendering. A PowerPoint is read slide by slide and a spreadsheet
    row by row, which is the same reading the intake does - so the preview
    and the fields we extracted come from one pass over the same text.
    """
    from . import intake as IN
    ext = ext_of(name)
    if ext == "pdf":
        return {"kind": "pdf", "render": "browser", "pages": []}
    doc = IN.read(body, name)
    if doc.error:
        return {"kind": doc.kind, "render": "none", "pages": [],
                "error": doc.error}
    pages: dict[str, list[str]] = {}
    for where, text in doc.lines:
        pages.setdefault(where, []).append(text)
    return {
        "kind": doc.kind,
        "render": "outline",
        "pages": [{"where": w, "lines": ls[:14]} for w, ls in list(pages.items())[:40]],
        "page_count": len(pages),
    }
