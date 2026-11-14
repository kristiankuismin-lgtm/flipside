"""What the screen is doing while it takes ninety seconds.

/analyze walks the graph: competitors, then every fund's rounds, then every
portfolio company's history, then five signals per fund. That is a minute and
a half behind a single spinner, and a spinner says nothing about how much
Cala data is being read.

This is a progress log keyed by what is being analysed, written by the
analysis and polled by the browser. Deliberately not a queue or a websocket:
the steps are small, the reader is one browser, and a dict with a lock is the
whole requirement.

Each step also says which layer it came from and what it lets us conclude.
A founder watching a spinner learns nothing; a founder watching "Cala has
Creandum in 16 Series A rounds, led 6 - that is a lead rate worth ranking
on" learns whether to trust the answer. The layers are deliberately
separate, because they are not equally strong:

  you      what the founder typed or uploaded
  cala     the knowledge graph - the thing the ranking stands on
  web      the firm's own pages, read live
  derived  our arithmetic on top of the two above
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


LAYERS = ("you", "cala", "web", "derived")


def step(key: str, text: str, detail: str = "", *,
         layer: str = "derived", because: str = "") -> None:
    """Record one line. Never raises: progress must not break the analysis.

    `because` is the inference, not the action: "read 16 rounds" is the step,
    "six of them led, so they can carry your round" is the because.
    """
    try:
        with _LOCK:
            run = _RUNS.get(key)
            if run is None or run["done"]:
                return
            run["steps"].append({
                "t": round(time.time() - run["started"], 1),
                "text": text, "detail": detail,
                "layer": layer if layer in LAYERS else "derived",
                "because": because})
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
                                     "text": text, "detail": "",
                                     "layer": "derived", "because": ""})
            run["done"] = True
    except Exception:
        pass


def get(key: str) -> dict:
    with _LOCK:
        run = _RUNS.get(key)
        if run is None:
            return {"found": False, "steps": [], "done": False, "elapsed": 0}
        steps = list(run["steps"])
        by_layer: dict[str, int] = {}
        for st in steps:
            lay = st.get("layer") or "derived"
            by_layer[lay] = by_layer.get(lay, 0) + 1
        return {"found": True, "done": run["done"], "label": run["label"],
                "elapsed": round(time.time() - run["started"], 1),
                "steps": steps, "by_layer": by_layer}
