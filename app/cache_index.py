"""Every entity we have ever fetched, addressable by id, without the network.

The response cache is keyed by a hash of the exact request, so asking for the
same entity with a different property list is a cache miss and goes live. When
Cala returns 402 that miss becomes a dead profile page - even though a perfectly
good payload for that entity is sitting in the same database under another key.

This builds the obvious index the cache does not keep: entity id -> the richest
payload we hold for it. It is rebuilt only when the cache file changes, so the
scan costs nothing on a warm process.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

_LOCK = threading.Lock()
_INDEX: dict[str, dict] = {}
_STAMP: tuple[float, int] | None = None


def _richer(a: dict, b: dict) -> dict:
    """Prefer the payload that actually carries properties and edges."""
    def weight(x):
        rel = (x.get("relationships") or {})
        edges = sum(len(v or []) for d in rel.values() if isinstance(d, dict)
                    for v in d.values())
        return (len(x.get("properties") or {}), edges, len(json.dumps(x, default=str)))
    return a if weight(a) >= weight(b) else b


def _collect(node, out: dict, depth: int = 0):
    if depth > 6:
        return
    if isinstance(node, list):
        for x in node[:600]:
            _collect(x, out, depth + 1)
        return
    if not isinstance(node, dict):
        return
    eid, et = node.get("id"), node.get("entity_type")
    # A stub from a search result has a name and nothing else; it is still
    # worth indexing, but it must never displace a full payload.
    if eid and et and node.get("name"):
        out[eid] = _richer(out[eid], node) if eid in out else node
    for v in node.values():
        if isinstance(v, (dict, list)):
            _collect(v, out, depth + 1)


def build(path: str | Path = "cache.sqlite") -> dict[str, dict]:
    global _INDEX, _STAMP
    p = Path(path)
    if not p.exists():
        return {}
    stamp = (p.stat().st_mtime, p.stat().st_size)
    with _LOCK:
        if _STAMP == stamp and _INDEX:
            return _INDEX
        out: dict[str, dict] = {}
        con = sqlite3.connect(str(p))
        try:
            for (v,) in con.execute("select v from cache"):
                try:
                    _collect(json.loads(v), out)
                except (ValueError, TypeError):
                    continue
        finally:
            con.close()
        _INDEX, _STAMP = out, stamp
        return _INDEX


def get(entity_id: str, path: str | Path = "cache.sqlite") -> dict | None:
    return build(path).get(entity_id)


def stats(path: str | Path = "cache.sqlite") -> dict:
    idx = build(path)
    kinds: dict[str, int] = {}
    for e in idx.values():
        kinds[e.get("entity_type") or "?"] = kinds.get(e.get("entity_type") or "?", 0) + 1
    return {"entities": len(idx), "by_type": kinds}


def search(q: str, types: list[str] | None = None, limit: int = 20,
           path: str | Path = "cache.sqlite") -> list[dict]:
    """Name search over everything already cached.

    Not a replacement for Cala's search - it only knows entities we have
    touched before - but when the network is unavailable it is the difference
    between an answer and an error message.
    """
    want = (q or "").strip().lower()
    if len(want) < 2:
        return []
    allow = set(types or [])
    out = []
    for e in build(path).values():
        if allow and e.get("entity_type") not in allow:
            continue
        name = (e.get("name") or "")
        low = name.lower()
        if want not in low:
            continue
        out.append({"id": e.get("id"), "name": name,
                    "entity_type": e.get("entity_type"),
                    "description": e.get("description") or ""})
        # Rank exactly as a caller would expect before truncating.
    out.sort(key=lambda h: (h["name"].lower() != want,
                            not h["name"].lower().startswith(want),
                            len(h["name"])))
    return out[:limit]


def websites(path: str | Path = "cache.sqlite") -> dict[str, str]:
    """name (lowercased) -> website, for everything cached.

    The hand-built domain files cover 49 of 664 funds. Cached entities carry
    a website property for far more, and a logo is the difference between a
    product and a wireframe.
    """
    out: dict[str, str] = {}
    for e in build(path).values():
        name = (e.get("name") or "").strip().lower()
        if not name or name in out:
            continue
        v = (e.get("properties") or {}).get("website")
        v = v.get("value") if isinstance(v, dict) else v
        if v:
            out[name] = v
    return out
