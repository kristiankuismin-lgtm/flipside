"""Collect everything, in the order that yields the most per call.

Cala's quota is a budget over time, so this is one patient sequential pass
rather than parallel jobs competing for the same window. Each stage is
resumable and writes incrementally, so stopping and restarting loses nothing.

Order is deliberate:
  1. Slush profiles   ~0.3s/company on the Entities API, and everything else
                      keys off having the profile. Cheapest data per call.
  2. Portfolio places  the funded universe - where conviction, rounds and
                      conflict data actually exist. Public registers are
                      tried first and cost no Cala quota at all.
  3. Exhibitor rounds  lowest yield (~93% of the Slush floor has never
                      raised) so it runs last.
"""
import json, os, subprocess, sys, time

STAGES = [
    ("Slush profiles",   ["fetch_slush_profiles.py", "2", "2000"]),
    ("Portfolio places", ["map_portfolio.py", "900", "1.5"]),
    ("Exhibitor rounds", ["score_exhibitors.py", "2000", "1.2"]),
]
PY = ".venv/bin/python"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def counts():
    out = {}
    for name, path, fn in (
        ("profiles", "slush_profiles.json", lambda d: sum(1 for r in d if not r.get("error"))),
        ("placed", "portfolio_places.json", lambda d: sum(1 for v in d.values() if v.get("lat"))),
        ("walked", "exhibitor_rounds.json", len),
    ):
        try:
            out[name] = fn(json.load(open(path)))
        except Exception:
            out[name] = 0
    return out


def main():
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    for lap in range(1, rounds + 1):
        log(f"--- pass {lap}/{rounds} --- {counts()}")
        for name, cmd in STAGES:
            log(f"stage: {name}")
            try:
                subprocess.run([PY] + cmd, check=False, timeout=3600)
            except subprocess.TimeoutExpired:
                log(f"{name}: hit the hour cap, moving on")
            log(f"after {name}: {counts()}")
    log(f"HARVEST DONE {counts()}")


if __name__ == "__main__":
    sys.exit(main())
