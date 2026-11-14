"""M1-M5 + Score. Puhdasta Pythonia: syotteena Round-listat, ei API-kutsuja.

Kaksi sääntöä, joista ei jousteta:
  1. Nimivertailu kulkee aina norm.matches():n lapi (ks. app/norm.py).
  2. Datan puute on ⚪, ei 🔴. Punainen on vaite sijoittajasta; valkoinen
     on vaite omasta datasta. Niiden sekoittaminen on valhe tuomarille.
"""
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from . import norm
from .models import Round, Signal, Evidence

TODAY = date.today()
WINDOW = TODAY - timedelta(days=36 * 30)

NO_DATA = "⚪"


def _conf(n, native=True):
    if n >= 10 and native:
        return "High"
    if n >= 5:
        return "Medium"
    return "Low"


def by_company(rounds: list[Round]) -> dict[str, list[Round]]:
    d = defaultdict(list)
    for r in rounds:
        d[norm.name(r.company) or r.company].append(r)
    for v in d.values():
        v.sort(key=lambda r: r.date)
    return dict(d)


def _entry_index(inv: str, rs: list[Round]) -> int | None:
    """Ensimmainen kierros, jolla sijoittaja esiintyy."""
    return next((i for i, r in enumerate(rs) if norm.matches(inv, r.investors)), None)


# ---- M1 Liidausosuus ---------------------------------------------------------
def lead_rate(inv: str, inv_rounds: list[Round], stage: str | None = None) -> Signal:
    want = norm.stage(stage) if stage else None
    rs = [r for r in inv_rounds
          if r.date >= WINDOW and (want is None or norm.stage(r.stage) == want)]
    n = len(rs)
    if not n:
        return Signal("lead_rate", None, NO_DATA,
                      f"No {stage or ''} rounds in the 36-month window".strip(),
                      0, "Low")

    led = [r for r in rs if norm.matches(inv, r.leads)]
    v = len(led) / n
    native = all(r.lead_is_native for r in rs)
    lab = "🟢" if v >= .4 else "🟡" if v >= .15 else "🔴"
    txt = f"Led {len(led)} of {n} {stage or ''} rounds ({v:.0%})".replace("  ", " ")
    ev = [Evidence(f"{r.company} {r.stage} {r.date}", (r.sources or [None])[0]) for r in led[:3]]
    return Signal("lead_rate", v, lab, txt, n, _conf(n, native), ev)


# ---- M2 Follow-on ------------------------------------------------------------
def follow_on(inv: str, company_rounds: dict[str, list[Round]]) -> tuple[Signal, Signal]:
    """Osallistuuko sijoittaja portfolioyhtioidensa seuraaviin kierroksiin?

    Mukaan vain yhtiot, joiden sisaantulokierros on >= 18 kk vanha: nuoremmilla
    ei ole viela ollut aikaa nostaa seuraavaa, joten ne vaaristaisivat osuutta.
    """
    cutoff = TODAY - timedelta(days=18 * 30)
    had_next = followed = next24 = entries = 0
    gaps, ev = [], []

    for rs in company_rounds.values():
        idx = _entry_index(inv, rs)
        if idx is None or rs[idx].date > cutoff:
            continue
        entries += 1
        if idx + 1 < len(rs):
            nxt = rs[idx + 1]
            had_next += 1
            gap = (nxt.date - rs[idx].date).days
            gaps.append(gap)
            if gap <= 730:
                next24 += 1
            if norm.matches(inv, nxt.investors):
                followed += 1
                ev.append(Evidence(f"Joined {nxt.company}'s {nxt.stage} round",
                                   (nxt.sources or [None])[0]))

    fo = followed / had_next if had_next else None
    nr = next24 / entries if entries else None
    med = median(gaps) / 30 if gaps else None

    s1 = Signal("follow_on", fo,
                NO_DATA if fo is None else "🟢" if fo >= .6 else "🟡" if fo >= .35 else "🔴",
                (f"Followed on in {followed} of {had_next} next rounds ({fo:.0%})"
                 if fo is not None else "No mature portfolio yet (entry <18 months ago)"),
                had_next, _conf(had_next), ev[:3])

    s2 = Signal("next_round", nr,
                NO_DATA if nr is None else "🟢" if nr >= .55 else "🟡" if nr >= .35 else "🔴",
                ((f"{nr:.0%} of the portfolio raised again within 24 months"
                  + (f", median {med:.0f} months" if med else ""))
                 if nr is not None else "No data"),
                entries, _conf(entries))
    return s1, s2


# ---- M3 Konfliktit -----------------------------------------------------------
def conflict(founder_vec, portfolio: list[dict], named_competitors: set[str]) -> Signal:
    """portfolio: [{'name','vec','source'}]; vec = normalisoitu embedding."""
    import numpy as np

    if not portfolio:
        return Signal("conflict", None, NO_DATA, "Portfolio unavailable", 0, "Low")

    named = {norm.name(c) for c in (named_competitors or set())}
    best, best_p = 0.0, None
    for p in portfolio:
        s = float(np.dot(founder_vec, p["vec"]))
        if norm.name(p["name"]) in named:
            s = max(s, .95)
        if s > best:
            best, best_p = s, p

    if best >= .85:
        lab, t = "🔴", f"Suora konflikti: {best_p['name']}"
    elif best >= .75:
        lab, t = "🟡", f"Laheinen: {best_p['name']}"
    else:
        lab, t = "🟢", "Ei konfliktia portfoliossa"
    ev = [Evidence(t, best_p.get("source"))] if best_p and lab != "🟢" else []
    return Signal("conflict", best, lab, t, len(portfolio), _conf(len(portfolio)), ev)


# ---- M4 Kuiva ruuti ----------------------------------------------------------
def dry_powder(inv: str, company_rounds: dict[str, list[Round]],
               latest_fund: dict | None = None) -> Signal:
    firsts = []
    for rs in company_rounds.values():
        i = _entry_index(inv, rs)
        if i is not None:
            firsts.append(rs[i].date)

    if not firsts:
        return Signal("dry_powder", None, NO_DATA, "No investment history in window", 0, "Low")

    new6 = sum(d >= TODAY - timedelta(days=180) for d in firsts)
    prev = sum(TODAY - timedelta(days=730) <= d < TODAY - timedelta(days=180) for d in firsts)
    base = prev / 3          # 18 kk -> 6 kk:n keskiarvo
    vel = new6 / max(base, 1)
    lab = "🟢" if vel >= 1 else "🟡" if vel >= .5 else "🔴"
    txt = f"{new6} new investments in 6 months (prior pace {base:.1f})"

    if latest_fund and latest_fund.get("vintage"):
        age = TODAY.year - int(latest_fund["vintage"])
        phase = "🟢 deploying" if age <= 3 else "🟡 late in life" if age <= 5 else "🔴 follow-on only"
        txt = f"{latest_fund.get('name', 'Fund')} ({latest_fund['vintage']}): {phase} · " + txt
        if age > 5:
            lab = "🔴"
    return Signal("dry_powder", vel, lab, txt, len(firsts), _conf(len(firsts)),
                  [Evidence("Fund data", latest_fund.get("source"))] if latest_fund else [])


# ---- M5 Lammin reitti --------------------------------------------------------
WEIGHTS = {"coinvest": 1.0, "colleague_portfolio_founder": .9,
           "colleague_partner": .8, "board": .6, "alumni": .5}


def warm_path(paths: list[dict]) -> Signal:
    if not paths:
        return Signal("warm_path", 0, NO_DATA, "No known route", 0, "Low")
    paths = sorted(paths, key=lambda p: WEIGHTS.get(p["type"], 0), reverse=True)
    top = paths[0]
    w = WEIGHTS.get(top["type"], 0)
    return Signal("warm_path", w, "🟢" if w >= .8 else "🟡", top["text"], len(paths),
                  "Medium", [Evidence(p["text"], p.get("source")) for p in paths[:3]])


# ---- Score -------------------------------------------------------------------
def score(fit: dict, sig: dict[str, Signal]) -> float:
    f = .35 * fit["stage"] + .30 * fit["sector"] + .20 * fit["geo"] + .15 * fit["check"]
    g = lambda k: (sig[k].value or 0) if k in sig else 0
    q = .3 * g("lead_rate") + .3 * g("follow_on") + .2 * g("next_round") + .2 * min(g("dry_powder"), 1)
    c = sig.get("conflict")
    cm = 0 if c and c.label == "🔴" else .7 if c and c.label == "🟡" else 1
    return round(100 * f * (.5 + .5 * q) * cm * (1 + .15 * g("warm_path")), 1)
