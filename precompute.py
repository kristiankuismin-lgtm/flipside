"""Tayttaa cachen demoa varten. Cala-kyselyt kestavat 20-60 s, joten
live-demo EI voi tehda niita lennossa. Tama on siksi pakollinen, ei optimointi.

Kaksi vaihetta:
  Tier 1  sijoittaja -> kierrokset  (M1 liidausosuus, M4 tahti, portfoliolista)
  Tier 2  yhtio      -> kierroshistoria sijoittajineen  (M2 follow-on)

Tier 2 on jaettu: sama yhtio haetaan kerran, vaikka se olisi monen
sijoittajan portfoliossa. Cache tekee ajosta myos jatkettavan - keskeytyksen
jalkeen uudelleenajo ohittaa jo haetut.

    python precompute.py investors.txt --workers 6 --companies 10
"""
import argparse, sys, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.conflict import portfolio
from app.extract import investor_rounds
from app.company_rounds import company_history

_lock = threading.Lock()
_done = 0


def _log(msg):
    with _lock:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _tick(total, label):
    global _done
    with _lock:
        _done += 1
        print(f"[{time.strftime('%H:%M:%S')}] {_done}/{total} {label}", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("investors", help="tiedosto, yksi sijoittaja per rivi")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--companies", type=int, default=10,
                    help="montako portfolioyhtiota per sijoittaja Tier 2:een")
    a = ap.parse_args()

    names = [l.strip() for l in open(a.investors) if l.strip() and not l.startswith("#")]
    t0 = time.time()

    # ---- Tier 1 -------------------------------------------------------------
    global _done
    _done = 0
    _log(f"TIER 1: {len(names)} sijoittajaa, {a.workers} saietta")
    portfolios: dict[str, list] = {}

    def t1(n):
        try:
            return n, investor_rounds(n)
        except Exception as e:
            _log(f"  FAIL {n}: {type(e).__name__} {str(e)[:120]}")
            return n, []

    with ThreadPoolExecutor(a.workers) as ex:
        for fut in as_completed([ex.submit(t1, n) for n in names]):
            n, rounds = fut.result()
            portfolios[n] = rounds
            _tick(len(names), f"{n}: {len(rounds)} kierrosta")

    ok1 = sum(1 for v in portfolios.values() if v)
    _log(f"TIER 1 valmis: {ok1}/{len(names)} sijoittajalla dataa  ({time.time()-t0:.0f}s)")

    # ---- Tier 2 -------------------------------------------------------------
    # Vanhimmat sisaantulot ensin: M2 vaatii >=18 kk kypsyneen kohortin.
    wanted: list[str] = []
    for rounds in portfolios.values():
        for r in sorted(rounds, key=lambda x: x.date)[:a.companies]:
            if r.company not in wanted:
                wanted.append(r.company)

    _done = 0
    _log(f"TIER 2: {len(wanted)} uniikkia yhtiota "
         f"(~{len(wanted)*45/a.workers/60:.0f} min arvio)")

    def t2(c):
        try:
            return c, len(company_history(c))
        except Exception as e:
            _log(f"  FAIL {c}: {type(e).__name__} {str(e)[:120]}")
            return c, 0

    ok2 = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for fut in as_completed([ex.submit(t2, c) for c in wanted]):
            c, n = fut.result()
            ok2 += bool(n)
            _tick(len(wanted), f"{c}: {n} kierrosta")

    # ---- Tier 3: portfoliot (M3 konfliktitarkistus) -------------------------
    _done = 0
    have = [n for n, v in portfolios.items() if v] or names
    _log(f"TIER 3: {len(have)} portfoliota")

    def t3(n):
        try:
            return n, len(portfolio(n))
        except Exception as e:
            _log(f"  FAIL {n}: {type(e).__name__} {str(e)[:120]}")
            return n, 0

    ok3 = 0
    with ThreadPoolExecutor(a.workers) as ex:
        for fut in as_completed([ex.submit(t3, n) for n in have]):
            n, c = fut.result()
            ok3 += bool(c)
            _tick(len(have), f"{n}: {c} portfolioyhtiota")

    _log(f"VALMIS: tier1 {ok1}/{len(names)}, tier2 {ok2}/{len(wanted)}, "
         f"tier3 {ok3}/{len(have)}, "
         f"kesto {(time.time()-t0)/60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
