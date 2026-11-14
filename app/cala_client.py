"""Ohut Cala-client: search / query / entities + SQLite-cache + retry.

Endpointit varmistettu docs.cala.ai/llms.txt -indeksista:
  POST /v1/knowledge/search          lähteistetty luonnollisen kielen vastaus
  POST /v1/knowledge/query           Cala QL -> {results[], entities[]}
  POST /v1/entities                  entiteettihaku nimella
  POST /v1/entities/lookup           tarkka nimi -> entiteetti
  GET  /v1/entities/{id}             entiteetin profiili
  GET  /v1/entities/{id}/introspection   kentat + relaatiot
"""
import hashlib, json, os, sqlite3, time
import httpx

BASE = os.getenv("CALA_BASE", "https://api.cala.ai/v1")
KEY = os.getenv("CALA_API_KEY", "")
DB = os.getenv("CACHE_DB", "cache.sqlite")
# Demoturva: 1 = cache-miss nostaa virheen eika tee 50 s kestavaa live-kutsua.
CACHE_ONLY = os.getenv("CALA_CACHE_ONLY", "") not in ("", "0", "false")

# Viimeisimman kutsun metatiedot: rate limit -headerit, status, kesto.
last_meta: dict = {}

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, ts REAL)")


class CacheMiss(RuntimeError):
    """Pyydettya dataa ei ollut cachessa ja CACHE_ONLY on paalla."""


class CalaError(RuntimeError):
    """API palautti virheen. .status ja .body kertovat mita tapahtui."""

    def __init__(self, msg, status=None, body=None):
        super().__init__(msg)
        self.status = status
        self.body = body


def _key(kind: str, payload) -> str:
    blob = kind + json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha1(blob.encode()).hexdigest()


def _cached(k: str, ttl: float):
    row = _conn.execute("SELECT v, ts FROM cache WHERE k=?", (k,)).fetchone()
    if row and time.time() - row[1] < ttl:
        return json.loads(row[0])
    return None


def _store(k: str, v) -> None:
    _conn.execute("REPLACE INTO cache VALUES (?,?,?)", (k, json.dumps(v), time.time()))
    _conn.commit()


def _request(method: str, path: str, payload=None, *, ttl=7 * 86400,
             retries=4, use_cache=True, allow_live=False, timeout=90,
             interactive=False):
    global last_meta
    if not KEY:
        raise CalaError("CALA_API_KEY is not set. Get a key at console.cala.ai -> API keys.")

    k = _key(f"{method} {path}", payload)
    if use_cache:
        hit = _cached(k, ttl)
        if hit is not None:
            last_meta = {"cached": True, "path": path}
            return hit

    # allow_live is for the interactive search box: it is fast (~0.25s) and
    # typing into a dead search field is worse than a slow one.
    if CACHE_ONLY and not allow_live:
        raise CacheMiss(f"CACHE_ONLY: {path} {json.dumps(payload, default=str)[:120]}")

    url = f"{BASE}{path}"
    headers = {"X-API-KEY": KEY, "Content-Type": "application/json"}
    last_err = None

    for i in range(retries):
        t0 = time.time()
        try:
            r = httpx.request(method, url, json=payload, headers=headers, timeout=timeout)
        except httpx.HTTPError as e:
            last_err = CalaError(f"Network error: {e}")
            if interactive:
                raise last_err
            time.sleep(2 ** i)
            continue

        last_meta = {
            "cached": False,
            "path": path,
            "status": r.status_code,
            "elapsed_s": round(time.time() - t0, 2),
            # Rate limit -headerit talteen: mentorikysymys #5.
            "ratelimit": {h: v for h, v in r.headers.items()
                          if "ratelimit" in h.lower() or "retry-after" in h.lower()},
        }

        if r.status_code == 429:
            # Cala's limiter is a budget over time, not a concurrency cap: a
            # short retry just spends the next token. Back off properly - but
            # an INTERACTIVE caller must fail fast rather than leave a spinner
            # running for a minute. Batch jobs are not interactive and should
            # wait: allow_live only means "may hit the network", not "give up".
            if interactive:
                raise CalaError("Rate limit", 429, r.text[:300])
            wait = float(r.headers.get("retry-after", max(5.0, 4 * (2 ** i))))
            last_err = CalaError("Rate limit", 429, r.text[:500])
            time.sleep(wait)
            continue

        if r.status_code >= 400:
            # 4xx ei parane uudelleenyrittamalla -> keskeyta heti.
            raise CalaError(f"{r.status_code} {path}", r.status_code, r.text[:1000])

        data = r.json()
        if use_cache:
            _store(k, data)
        return data

    raise last_err or CalaError("Tuntematon virhe")


def search(question: str, **kw) -> dict:
    """Lahteistetty luonnollisen kielen vastaus (markdown + lahteet)."""
    return _request("POST", "/knowledge/search", {"input": question}, **kw)


def query(cala_ql: str, return_entities: bool = True, **kw) -> dict:
    """Cala QL -> {'results': [...], 'entities': [...]}. Palauttaa koko vastauksen."""
    return _request("POST", "/knowledge/query",
                    {"input": cala_ql, "return_entities": return_entities}, **kw)


def rows(cala_ql: str, **kw) -> list:
    """query():n results-lista suoraan."""
    return (query(cala_ql, **kw) or {}).get("results") or []


def entities_search(name: str, entity_types=None, limit: int = 20, **kw) -> list:
    """GET /v1/entities?name=...&entity_types=... -> [{id,name,entity_type,description}].

    HUOM: POST /entities palauttaa 405. Haku on GET + query-parametrit.
    """
    from urllib.parse import urlencode
    qs = [("name", name), ("limit", str(limit))]
    for t in (entity_types or []):
        qs.append(("entity_types", t))
    r = _request("GET", f"/entities?{urlencode(qs)}", None, **kw) or {}
    return r.get("entities") or []


# /entities/lookup resolves an entity by a REGISTERED IDENTIFIER, not by name.
# This is the most precise entrance to the graph there is: names collide
# ("Abridge" matches a Swedish company in Alvsjo), identifiers do not.
LOOKUP_SCHEMES = ("lei", "cik", "companies_house_uk_company_number", "siren", "rssd_id")


def lookup(scheme: str, value: str, **kw) -> dict | None:
    """Resolve by LEI / CIK / Companies House number / SIREN / RSSD ID.

    Returns the entity stub {id, name, entity_type, description} or None.
    """
    if scheme not in LOOKUP_SCHEMES:
        raise ValueError(f"unsupported scheme {scheme!r}; use one of {LOOKUP_SCHEMES}")
    v = str(value or "").strip()
    if not v:
        return None
    try:
        r = _request("POST", "/entities/lookup", {"id": {scheme: v}}, **kw)
    except CalaError as e:
        if e.status in (404, 422):
            return None
        raise
    return r or None


def get_entity(entity_id: str, properties=None, incoming=None, outgoing=None,
               limit: int = 200, offset: int = 0, **kw) -> dict:
    """POST /v1/entities/{id}. Tyhja body = oletuskentat ilman relaatioita.

    Ominaisuudet palautuvat muodossa {"value": x, "sources": [{document, name, date}]},
    joten tama on ainoa reitti rivitason lahteistykseen.
    """
    body: dict = {}
    if properties:
        body["properties"] = list(properties)
    page = {"limit": limit, "offset": offset}
    rel: dict = {}
    if incoming:
        rel["incoming"] = {r: dict(page) for r in incoming}
    if outgoing:
        rel["outgoing"] = {r: dict(page) for r in outgoing}
    if rel:
        body["relationships"] = rel
    return _request("POST", f"/entities/{entity_id}", body or None, **kw)


def introspect(entity_id: str, **kw) -> dict:
    """Entiteetin kentat ja relaatiot. Nain selviaa onko lead-investor mallinnettu."""
    return _request("GET", f"/entities/{entity_id}/introspection", None, **kw)


def get_relations(entity_id: str, rel: str, direction: str = "incoming",
                  page: int = 500, max_items: int = 5000, **kw) -> list:
    """Hae relaation kaikki kohteet sivuttaen. Calan yla-raja on 500 per kutsu."""
    out, offset = [], 0
    while offset < max_items:
        kwargs = {("incoming" if direction == "incoming" else "outgoing"): [rel]}
        r = get_entity(entity_id, limit=page, offset=offset, **kwargs, **kw)
        items = ((r.get("relationships") or {}).get(direction, {}) or {}).get(rel) or []
        out.extend(items)
        if len(items) < page:
            break
        offset += page
    return out
