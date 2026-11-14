"""Cala API -recon: vastaa viiteen mentorikysymykseen empiirisesti.

Aja heti kun CALA_API_KEY on olemassa:
    export CALA_API_KEY=...
    python recon.py

Tulostaa konsoliin ja kirjoittaa recon_report.md. Ei kaadu yhteenkaan probeen:
jokainen kysymys on erillinen, ja epaonnistuminen on itsessaan tulos.
"""
import json, os, sys, traceback
from app import cala_client as cala

OUT = []          # raportin rivit
FINDINGS = {}     # koneluettavat paatokset extract.py:ta varten


def say(s=""):
    print(s)
    OUT.append(s)


def head(n, title):
    say()
    say(f"## {n}. {title}")
    say()


def probe(label, fn):
    """Aja yksi koe. Palauttaa (ok, tulos). Ei koskaan heita."""
    try:
        v = fn()
        meta = cala.last_meta
        tag = "cache" if meta.get("cached") else f"{meta.get('elapsed_s', '?')}s"
        say(f"  [OK]   {label}  ({tag})")
        return True, v
    except cala.CalaError as e:
        say(f"  [FAIL] {label}  -> {e.status or ''} {str(e)[:160]}")
        if e.body:
            say(f"         body: {e.body[:300]}")
        return False, None
    except Exception as e:
        say(f"  [ERR]  {label}  -> {type(e).__name__}: {str(e)[:160]}")
        return False, None


def jdump(o, limit=1200):
    s = json.dumps(o, indent=2, ensure_ascii=False, default=str)
    return s if len(s) <= limit else s[:limit] + "\n  ... (katkaistu)"


# Demokandidaatit. Wolt/Supercell = tunnettuja, Lifeline/Maki = eurooppalainen siemenvaihe.
TEST_COMPANY = os.getenv("RECON_COMPANY", "Wolt")
TEST_INVESTORS = ["Index Ventures", "Lifeline Ventures", "Maki.vc",
                  "Inventure", "Icebreaker.vc", "Byfounders", "Creandum"]


def main():
    say("# Cala API recon")
    say()
    say(f"BASE={cala.BASE}  avain={'ON' if cala.KEY else 'PUUTTUU'}")
    if not cala.KEY:
        say()
        say("> CALA_API_KEY puuttuu. export CALA_API_KEY=... ja aja uudelleen.")
        return 1

    # --- 0. Yhteys ja autentikointi -----------------------------------------
    head(0, "Yhteys toimii?")
    ok, _ = probe("POST /knowledge/query (yksinkertainen)",
                  lambda: cala.query("companies.industry=fintech.founded_year>=2020"))
    if not ok:
        say()
        say("> Yhteys ei toimi. Tarkista avain ja BASE-url ennen kuin jatkat.")
        return 1

    # --- 1. Entiteetti ja sen skeema ----------------------------------------
    head(1, f"Entiteetti ja kentat: {TEST_COMPANY}")
    ok, look = probe(f"POST /entities/lookup '{TEST_COMPANY}'",
                     lambda: cala.lookup(TEST_COMPANY))
    if not ok:
        ok, look = probe(f"POST /entities '{TEST_COMPANY}'",
                         lambda: cala.entities_search(TEST_COMPANY))

    eid = None
    if look:
        say()
        say("```json")
        say(jdump(look, 900))
        say("```")
        eid = _first_entity_id(look)
        FINDINGS["lookup_shape"] = list(look.keys()) if isinstance(look, dict) else type(look).__name__

    if eid:
        say(f"\n  entity_id = {eid}")
        ok, intro = probe(f"GET /entities/{{id}}/introspection", lambda: cala.introspect(eid))
        if intro:
            props = intro.get("properties") or intro.get("fields") or []
            rels = intro.get("relationships") or {}
            say()
            say(f"  properties ({len(props)}): {_names(props)[:40]}")
            say(f"  relationships: {jdump(_rel_names(rels), 600)}")
            FINDINGS["company_properties"] = _names(props)
            FINDINGS["company_relationships"] = _rel_names(rels)
            # Loytyyko rahoituskierros-relaatiota?
            fr = [r for r in _rel_names(rels) if "fund" in r.lower() or "invest" in r.lower()]
            say(f"\n  >>> rahoitukseen liittyvat relaatiot: {fr or 'EI LOYTYNYT'}")
            FINDINGS["funding_relationships"] = fr
    else:
        say("\n  >>> entity_id ei irronnut vastauksesta - katso rakenne yllä ja korjaa _first_entity_id()")

    # --- 2. KRIITTINEN: onko rahoituskierroksella lead-kentta? --------------
    head(2, "Onko FundingRound-entiteetilla lead investor -kentta?  (mentorikysymys #1)")
    say("Haetaan yksi rahoituskierros-entiteetti ja introspektoidaan se.")
    say()
    round_eid = None
    for probe_name in [f"{TEST_COMPANY} Series A funding round",
                       f"{TEST_COMPANY} funding round"]:
        ok, r = probe(f"lookup '{probe_name}'", lambda p=probe_name: cala.lookup(p))
        if r:
            cand = _first_entity_id(r, want_type_substr="fund")
            if cand:
                round_eid = cand
                break

    if not round_eid and eid:
        # Vaihtoehto: hae kierrokset QL:lla ja poimi entities[]-listasta.
        ok, q = probe(f"query '{TEST_COMPANY}.funding_rounds'",
                      lambda: cala.query(f"{TEST_COMPANY}.funding_rounds"))
        if q:
            round_eid = _first_entity_id(q, want_type_substr="fund")

    if round_eid:
        say(f"\n  funding round entity_id = {round_eid}")
        ok, intro = probe("GET introspection", lambda: cala.introspect(round_eid))
        if intro:
            props = _names(intro.get("properties") or intro.get("fields") or [])
            rels = _rel_names(intro.get("relationships") or {})
            say()
            say(f"  properties: {props}")
            say(f"  relationships: {rels}")
            lead = [x for x in props + rels if "lead" in x.lower()]
            FINDINGS["round_properties"] = props
            FINDINGS["round_relationships"] = rels
            FINDINGS["lead_field"] = lead
            say()
            if lead:
                say(f"  >>> LEAD-KENTTA LOYTYI: {lead}")
                say("  >>> M1 on CALA-NATIIVI. Luottamus = Korkea.")
            else:
                say("  >>> EI LEAD-KENTTAA. M1 jaa heuristiikaksi (b: 'led by' search-tekstista,")
                say("  >>> c: ainoa institutionaalinen sijoittaja). Merkitse luottamus = Keski.")
    else:
        say("\n  >>> Rahoituskierrosta ei saatu entiteettina. Kysy mentorilta miten")
        say("  >>> PrivateCompanyFundingRound haetaan, tai kayta search-fallbackia.")

    # --- 3. Investor -> kierrokset: mika QL-syntaksi toimii? ----------------
    head(3, "Investor -> kierrokset: toimiva QL-syntaksi  (mentorikysymys #3)")
    say("Kokeillaan syntakseja. Ensimmainen joka palauttaa rivejä voittaa.")
    say()
    inv = TEST_INVESTORS[0]
    candidates = [
        f'funding_rounds.investors="{inv}"',
        f'funding_rounds.investor="{inv}"',
        f'{inv}.investments',
        f'{inv}.portfolio',
        f'{inv}.funding_rounds',
        f'investors.name="{inv}".funding_rounds',
        f'companies.investors="{inv}"',
        f'companies.funding_rounds.investors="{inv}"',
        f"Which funding rounds has {inv} participated in since 2022?",
    ]
    working = []
    for q in candidates:
        ok, res = probe(f'query: {q}', lambda q=q: cala.query(q))
        n = len(((res or {}).get("results")) or [])
        if ok and n:
            working.append((q, n))
            say(f"         -> {n} rivia")
            if len(working) == 1:
                say()
                say("```json")
                say(jdump((res or {}).get("results", [])[:3], 1400))
                say("```")
    FINDINGS["working_round_queries"] = working
    say()
    if working:
        say(f"  >>> TOIMII: {working[0][0]}  ({working[0][1]} rivia)")
        say("  >>> Kirjoita tama extract.investor_rounds():iin.")
    else:
        say("  >>> Mikaan syntaksi ei palauttanut rivejä. Kayta search-fallbackia")
        say("  >>> ja LLM-parsintaa, TAI kysy mentorilta oikea muoto. TAMA ON P0-BLOKKERI.")

    # --- 4. Lahteistys: saako riveille lahde-URL:t? -------------------------
    head(4, "Lahteistys riveittain  (mentorikysymys #4)")
    ok, q = probe("query + return_entities=True",
                  lambda: cala.query("companies.industry=fintech.founded_year>=2020"))
    if q:
        ents = q.get("entities") or []
        res = q.get("results") or []
        say()
        say(f"  results-rivin kentat:  {sorted(res[0].keys()) if res else '(ei rivejä)'}")
        say(f"  entities-kentat:       {sorted(ents[0].keys()) if ents else '(ei entiteetteja)'}")
        has_src = any(k in (res[0] if res else {}) for k in ("source", "sources", "source_url", "citations"))
        FINDINGS["row_level_sources"] = has_src
        if ents:
            say()
            say("  entities[0]:")
            say("```json")
            say(jdump(ents[0], 700))
            say("```")
            m = ents[0].get("mentions")
            FINDINGS["mentions_shape"] = type(m).__name__ if m is not None else None
            if m:
                say(f"  >>> mentions loytyi ({type(m).__name__}) - TAMA on lahteistyksen kiinnekohta.")
        say()
        say(f"  >>> rivitason lahteet: {'KYLLA' if has_src else 'EI'}")
        if not has_src:
            say("  >>> Lahteistys rakennetaan entities[].id -> GET /entities/{id} kautta,")
            say("  >>> ja narratiiviset vaitteet haetaan /knowledge/search-endpointista.")

    ok, s = probe("POST /knowledge/search (sisaltaako lahteet?)",
                  lambda: cala.search(f"Who led {TEST_COMPANY}'s Series A and when? Cite sources."))
    if s:
        say()
        say("  search-vastauksen kentat: " + str(sorted(s.keys()) if isinstance(s, dict) else type(s)))
        say("```json")
        say(jdump(s, 1000))
        say("```")
        FINDINGS["search_shape"] = sorted(s.keys()) if isinstance(s, dict) else None

    # --- 5. Kattavuus: onko eurooppalainen siemenvaihe mukana? --------------
    head(5, "Kattavuus: eurooppalaiset siemenrahastot  (riski #2)")
    say("Jos nama puuttuvat, tuote pitaa kallistaa kasvuvaiheeseen.")
    say()
    cov = {}
    for name in TEST_INVESTORS:
        ok, r = probe(f"lookup '{name}'", lambda n=name: cala.lookup(n))
        cov[name] = bool(r and _first_entity_id(r))
    FINDINGS["investor_coverage"] = cov
    hit = sum(cov.values())
    say()
    say(f"  >>> {hit}/{len(TEST_INVESTORS)} sijoittajaa loytyi entiteetteina.")
    if hit < len(TEST_INVESTORS) // 2:
        say("  >>> VAROITUS: kattavuus heikko. Harkitse kasvuvaihetta tai US-sijoittajia.")

    # --- 6. Rate limitit ----------------------------------------------------
    head(6, "Rate limit -headerit  (mentorikysymys #5)")
    say(f"  viimeisin kutsu: {jdump(cala.last_meta, 400)}")
    rl = cala.last_meta.get("ratelimit")
    say(f"  >>> {'Rate limit -headerit nakyvat: ' + str(rl) if rl else 'Ei rate limit -headereita vastauksessa.'}")

    # --- Yhteenveto ---------------------------------------------------------
    head("", "Yhteenveto extract.py:ta varten")
    say("```json")
    say(json.dumps(FINDINGS, indent=2, ensure_ascii=False, default=str))
    say("```")
    return 0


# ---- apurit ----------------------------------------------------------------
def _names(props):
    out = []
    for p in props or []:
        out.append(p if isinstance(p, str) else (p.get("name") or p.get("field") or str(p)))
    return out


def _rel_names(rels):
    if isinstance(rels, dict):
        out = []
        for direction, items in rels.items():
            for it in items or []:
                nm = it if isinstance(it, str) else (it.get("name") or it.get("type") or str(it))
                out.append(f"{direction}:{nm}")
        return out
    return _names(rels)


def _first_entity_id(obj, want_type_substr=None):
    """Kaiva ensimmainen uuid-nakoinen id vastauksesta, valinnaisesti tyypin mukaan."""
    import re
    UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)

    best = None
    def walk(o):
        nonlocal best
        if best:
            return
        if isinstance(o, dict):
            i = o.get("id") or o.get("entity_id")
            t = str(o.get("entity_type") or o.get("type") or "")
            if isinstance(i, str) and UUID.match(i):
                if want_type_substr is None or want_type_substr.lower() in t.lower():
                    best = i
                    return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(obj)
    return best


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        say("\n!!! recon kaatui:")
        say(traceback.format_exc())
        code = 1
    with open("recon_report.md", "w") as f:
        f.write("\n".join(OUT) + "\n")
    print(f"\n--- raportti kirjoitettu: recon_report.md ({len(OUT)} rivia) ---")
    sys.exit(code)
