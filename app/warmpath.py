"""M5: kuka voi esitella minut?

Lasketaan yhteissijoituksista, jotka ovat jo cachessa: jos nykyinen
sijoittajasi J on ollut samassa yhtiossa kohdesijoittajan I kanssa, J on
luonteva reitti. Tama ei vaadi yhtaan uutta Cala-kutsua - yhtiohistoriat
haettiin jo M2:ta varten.

Painot vastaavat suunnitelman taulukkoa: sama kierros on vahvempi signaali
kuin sama yhtio eri kierroksilla.
"""
from collections import defaultdict

from . import norm
from .models import Round, Signal, Evidence

W_SAME_ROUND = 1.0     # istuivat samassa kierroksessa
W_SAME_COMPANY = 0.75  # sama yhtio, eri kierrokset


def coinvestments(a: str, b: str, histories: dict[str, list[Round]]) -> list[dict]:
    """Yhtiot, joissa molemmat ovat mukana. Vahvin yhteys ensin."""
    out = []
    for company, rounds in histories.items():
        ra = [r for r in rounds if norm.matches(a, r.investors)]
        rb = [r for r in rounds if norm.matches(b, r.investors)]
        if not ra or not rb:
            continue
        same = next((r for r in ra if r in rb), None)
        if same:
            out.append({"company": same.company, "weight": W_SAME_ROUND,
                        "text": f"{a} and {b} both invested in {same.company}'s "
                                f"{same.stage} round ({same.date:%-m/%Y})"})
        else:
            out.append({"company": rounds[0].company, "weight": W_SAME_COMPANY,
                        "text": f"{a} and {b} are both investors in {rounds[0].company}"})
    out.sort(key=lambda x: -x["weight"])
    return out


def warm_path(target: str, my_investors: list[str],
              histories: dict[str, list[Round]]) -> Signal:
    """Paras reitti kohdesijoittajalle omien sijoittajien kautta."""
    if not my_investors:
        return Signal("warm_path", 0, "⚪", "No current investors given", 0, "Low")

    paths = []
    for j in my_investors:
        if norm.name(j) == norm.name(target):
            continue
        for p in coinvestments(j, target, histories):
            paths.append({**p, "via": j})

    if not paths:
        return Signal("warm_path", 0, "⚪",
                      "No co-investment found in known data", 0, "Low")

    paths.sort(key=lambda x: -x["weight"])
    best = paths[0]
    lab = "🟢" if best["weight"] >= W_SAME_ROUND else "🟡"
    return Signal("warm_path", best["weight"], lab,
                  f"via {best['via']}", len(paths), "Medium",
                  [Evidence(p["text"]) for p in paths[:3]])


def index_histories(all_rounds: list[Round]) -> dict[str, list[Round]]:
    d = defaultdict(list)
    for r in all_rounds:
        d[r.company].append(r)
    return dict(d)
