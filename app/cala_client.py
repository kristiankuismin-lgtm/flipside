"""Ohut Cala-client: search / query / entities + SQLite-cache + retry.

Endpointit varmistettu docs.cala.ai/llms.txt -indeksista:
  POST /v1/knowledge/search          lähteistetty luonnollisen kielen vastaus
  POST /v1/knowledge/query           Cala QL -> {results[], entities[]}
  POST /v1/entities                  entiteettihaku nimella
  POST /v1/entities/lookup           tarkka nimi -> entiteetti
  GET  /v1/entities/{id}             entiteetin profiili
  GET  /v1/entities/{id}/introspection   kentat + relaatiot
"""
import hashlib, json, os, sqlite3, threading, time
import httpx

BASE = os.getenv("CALA_BASE", "https://api.cala.ai/v1")
KEY = os.getenv("CALA_API_KEY", "")
DB = os.getenv("CACHE_DB", "cache.sqlite")
# Demoturva: 1 = cache-miss nostaa virheen eika tee 50 s kestavaa live-kutsua.
CACHE_ONLY = os.getenv("CALA_CACHE_ONLY", "") not in ("", "0", "false")

# Viimeisimman kutsun metatiedot: rate limit -headerit, status, kesto.
last_meta: dict = {}

# Cala's limiter allows a short burst and then refuses, and it sends no
# ratelimit headers to read the budget from. Retrying into a closed window
# spends attempts and learns nothing, so the client paces itself instead:
# every 429 widens the gap between requests, every success narrows it. A batch
# job sets CALA_MIN_INTERVAL and converges on whatever the budget actually is;
# interactive callers leave it at 0 and are not slowed down at all.
_pace_lock = threading.Lock()
_pace = {"interval": float(os.getenv("CALA_MIN_INTERVAL", "0") or 0), "next": 0.0}
# Measured against the live API with nothing else running: the limiter is a
# token bucket of roughly ten, refilling one token every 1.3 to 2.4 seconds.
# A ceiling of twenty seconds was therefore self-defeating - it paced us an
# order of magnitude below what the budget allows, and the only way back
# down was a 10% decay per success that a starved job never earns.
PACE_MAX = 4.0
PACE_MIN = 0.3


def pace_state() -> dict:
    with _pace_lock:
        return dict(_pace)


def _wait_turn() -> None:
    with _pace_lock:
        if _pace["interval"] <= 0:
            return
        now = time.time()
        slot = max(now, _pace["next"])
        _pace["next"] = slot + _pace["interval"]
    delay = slot - time.time()
    if delay > 0:
        time.sleep(delay)


def _pace_slower() -> None:
    with _pace_lock:
        if _pace["interval"] <= 0:
            return
        _pace["interval"] = min(PACE_MAX, _pace["interval"] * 1.25)
        _pace["next"] = max(_pace["next"], time.time() + _pace["interval"])


def _pace_faster() -> None:
    """Come back down at a rate that can actually recover.

    Backing off 1.7x per 429 and recovering 2% per success is not symmetric:
    once a burst of refusals pushed the interval to the 20s ceiling, every
    worker queued behind one global slot every 20 seconds and a batch run
    fell to one entity every ninety. Climbing out needed a hundred and fifty
    successes at one request per twenty seconds, which is never. Backing off
    fast and recovering slowly is right; recovering imperceptibly is a stall
    that looks like a rate limit.
    """
    with _pace_lock:
        if _pace["interval"] > PACE_MIN:
            _pace["interval"] = max(PACE_MIN, _pace["interval"] * 0.9)
            _pace["next"] = min(_pace["next"], time.time() + _pace["interval"])

_conn = sqlite3.connect(DB, check_same_thread=False)
_conn.execute("PRAGMA busy_timeout=20000")
_conn.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
# The batch harvester runs several fetches at once; one writer at a time keeps
# sqlite from raising "database is locked" into the middle of a long run.
_write_lock = threading.Lock()


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
    with _write_lock:
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
        _wait_turn()
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
            # Keep the rate-limit headers: mentor question #5.
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
            _pace_slower()
            # Sleep for about one refill, not for an exponential backoff.
            # max(5, 4*2^i) meant a single entity that hit the limit four
            # times burned sixty-one seconds and dragged the shared pace up
            # with it, which is how a 40/min budget became 6/min.
            wait = float(r.headers.get("retry-after", min(6.0, 1.5 * (i + 1))))
            last_err = CalaError("Rate limit", 429, r.text[:500])
            time.sleep(wait)
            continue

        if r.status_code == 402:
            # Out of credits, not a bug and not a rate limit. Retrying spends
            # nothing and fixes nothing, and the distinction matters: a 429
            # clears by waiting, a 402 clears only by topping up.
            raise CalaError(
                "Cala credits exhausted. Everything already cached still "
                "works; new lookups need a top-up at console.cala.ai.",
                402, r.text[:300])

        if r.status_code >= 400:
            # A 4xx does not improve on retry -> stop immediately.
            raise CalaError(f"{r.status_code} {path}", r.status_code, r.text[:1000])

        _pace_faster()
        data = r.json()
        if use_cache:
            _store(k, data)
        return data

    raise last_err or CalaError("Unknown error")


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
    """POST /v1/entities/{id}. An empty body gives default fields, no relations.

    Properties come back as {"value": x, "sources": [{document, name, date}]},
    which makes this the only route to per-claim sourcing.
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
    """An entity's fields and relationships - how we learn whether lead
    investor is modelled at all, rather than guessing a schema."""
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
