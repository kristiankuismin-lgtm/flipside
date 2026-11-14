"""What the screen is doing while it takes ninety seconds.

/analyze walks the graph: competitors, then every fund's rounds, then every
portfolio company's history, then five signals per fund. That is a minute and
a half behind a single spinner, and a spinner says nothing about how much
Cala data is being read.

This is a progress log keyed by what is being analysed, written by the
analysis and polled by the browser. Deliberately not a queue or a websocket:
the steps are small, the reader is one browser, and a dict with a lock is the
whole requirement.
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
_RUNS: dict[str, dict] = {}
MAX_RUNS = 12          # a hackathon demo does not need unbounded history


def key_for(company: str, stage: str = "") -> str:
    return f"{(company or '').strip().lower()}|{(stage or '').strip().lower()}"


def start(key: str, label: str = "") -> None:
    with _LOCK:
        _RUNS[key] = {"started": time.time(), "label": label,
                      "steps": [], "done": False}
        # Drop the oldest runs rather than growing forever.
        if len(_RUNS) > MAX_RUNS:
            for k in sorted(_RUNS, key=lambda k: _RUNS[k]["started"])[:-MAX_RUNS]:
                _RUNS.pop(k, None)


def step(key: str, text: str, detail: str = "") -> None:
    """Record one line. Never raises: progress must not break the analysis."""
    try:
        with _LOCK:
            run = _RUNS.get(key)
            if run is None or run["done"]:
                return
            run["steps"].append({"t": round(time.time() - run["started"], 1),
                                 "text": text, "detail": detail})
    except Exception:
        pass


def done(key: str, text: str = "") -> None:
    try:
        with _LOCK:
            run = _RUNS.get(key)
            if run is None:
                return
            if text:
                run["steps"].append({"t": round(time.time() - run["started"], 1),
                                     "text": text, "detail": ""})
            run["done"] = True
    except Exception:
        pass


def get(key: str) -> dict:
    with _LOCK:
        run = _RUNS.get(key)
        if run is None:
            return {"found": False, "steps": [], "done": False, "elapsed": 0}
        return {"found": True, "done": run["done"], "label": run["label"],
                "elapsed": round(time.time() - run["started"], 1),
                "steps": list(run["steps"])}
