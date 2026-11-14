"""Tier 3 erikseen: portfoliot M3-konfliktitarkistusta varten.

Pieni saiemaara tarkoituksella - Calassa on rate limit, josta ei kerrota
headereissa. Epaonnistuneet eivat tallennu cacheen, joten uusinta-ajo korjaa.
Jarjestys on tarkea: konfliktin kannalta kiinnostavimmat ensin.
"""
import sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from app.conflict import portfolio

PRIORITY = ["Northzone", "Atomico", "EQT Ventures", "Highland Europe",
            "Creandum", "Balderton Capital", "Index Ventures", "Lifeline Ventures",
            "Inventure", "Maki.vc", "Icebreaker.vc", "Byfounders"]

names = [l.strip() for l in open("investors.txt") if l.strip() and not l.startswith("#")]
names.sort(key=lambda n: (PRIORITY.index(n) if n in PRIORITY else 99, n))

workers = int(sys.argv[1]) if len(sys.argv) > 1 else 2
print(f"[{time.strftime('%H:%M:%S')}] {len(names)} portfoliota, {workers} saietta", flush=True)

def go(n):
    try:
        return n, len(portfolio(n))
    except Exception as e:
        return n, f"FAIL {type(e).__name__}: {str(e)[:70]}"

done = 0
with ThreadPoolExecutor(workers) as ex:
    for f in as_completed([ex.submit(go, n) for n in names]):
        n, r = f.result(); done += 1
        print(f"[{time.strftime('%H:%M:%S')}] {done}/{len(names)} {n}: {r}", flush=True)
