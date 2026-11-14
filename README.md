# Flipside

**Investors run diligence on you before they invest. Flipside runs it on them.**

One funding graph, read three ways. Built on [Cala](https://cala.ai) for
Junction 2026.

| | Question | Who asks it |
|---|---|---|
| **Founder** | Which investors actually lead, still deploy, and already back my competitor? | raising a round |
| **Investor** | When this company raised again, did the people already on the cap table come back — and was that unusual for them? | writing a cheque |
| **Third** | Who looks like a founder before they are one? | looking early |

---

## Why this needs a graph

Every metric here is an aggregate over *connections*: investor → rounds →
companies → later rounds → co-investors. A web search returns articles. None of
these numbers can be looked up; they have to be computed over the edges.

```
Gosta Labs ──competes with──▶ Tandem Health ──backed by──▶ Northzone
```

That two-hop path is the product's central claim, and it is one query in a
graph and impossible in a search engine.

## Founder side

| | Signal | Thresholds |
|---|---|---|
| **M1** | Share of rounds the firm **led** | 🟢 ≥40% · 🟡 15–40% · 🔴 <15% |
| **M2** | Follow-on into the *next* round | 🟢 ≥60% · 🟡 35–60% · 🔴 <35% |
| **M3** | Backs a company Cala names as your competitor | 🔴 direct · 🟡 adjacent · 🟢 clear |
| **M4** | New investments per 6 months vs prior pace | 🟢 ≥1.0 · 🟡 0.5–1.0 · 🔴 <0.5 |
| **M5** | Warm route through a shared investor | from the co-investment graph |

M2 counts only companies whose entry round is 18+ months old — younger ones
have not had time to raise again.

## Investor side — insider conviction

Insiders know the most, and their own cheque is the one signal that cannot be
marketed. Four things separate this from "insiders returned, good":

1. **A return is only informative against that investor's own habit.** Coming
   back when you usually return 25% of the time says something; always
   returning says almost nothing. Habits are shrunk toward the pool mean so a
   single observation cannot swing a score.
2. **Who skipped matters more than how many.** A seed fund skipping a Series A
   is noise — small reserves. The round's **previous lead** skipping is the
   loudest silence in venture, and is scored as its own term.
3. **An insider-only round means two opposite things.** Pre-emption (lead back
   inside 12 months at ≥2×) is the strongest positive signal there is; a bridge
   is negative. Without round sizes we report *unknown* rather than guess.
4. **A late-life fund explains its own absence** — which is exactly what the
   founder-side pace metric already measures. One engine, read twice.

## Does it work? A controlled backtest

The first version asked whether a company *"raised again within 24 months"* and
conviction looked mildly **anti**-predictive. That was the outcome variable's
fault: how often a company needs money is not a measure of doing well.

Re-run against **stage progression** — seed→A→B rather than a bridge:

| | Progressed within 36 months |
|---|---|
| Insiders ≥50% back | **48.8%** (n=203) |
| Base rate | 38.6% (n=498) |
| Naive "back whoever the most active funds back" | 41.4% (n=348) |
| Insiders <50% back | 31.5% (n=295) |

**+17.2pp spread, +7.4pp over the naive baseline.** Previous lead returns →
42.1%; walks away → 29.4%.

Controls: no look-ahead (habits recomputed from rounds closed before each
observation), a maturity filter, and every comparison repeated inside fixed
cap-table-size buckets — because return *fraction* is mechanically tied to how
many investors were already on the register. It holds at +32.7pp, +12.7pp and
+13.2pp in the 2–3, 4–6 and 7+ buckets, and **reverses at −4.9pp in
single-investor cap tables.** That row is in the product, not filtered out.

## Three rules the code enforces

**Unknown is not zero.** ⚪ means we lack data. 🔴 is a claim about an investor;
⚪ is a claim about us. Conflating them would be a lie.

**Fewer than three rounds → never ranked.** A firm we know nothing about must
not look mediocre. It is shown, labelled, and excluded from the ranking.

**Rules decide, the model only writes.** `numbercheck.py` rejects generated text
containing any figure the metrics do not support.

## Sourcing

A conflict flag is a serious thing to put in front of a founder, so it does not
rest on our arithmetic. `/knowledge/search` returns the individual claims behind
an answer, each pointing at its source document.

> **Did Northzone invest in Tandem Health?**
> Yes — led a ~$9.5M seed.
> `PRIMARY` Northzone's own portfolio page · `PRESS` MAQS · `PRESS` Nordic9

Ranked by who published it: a regulator's filing, then a party speaking for
itself, then commentary about them.

## Public registers are the index, Cala is the graph

Names collide. "Abridge" matches a Swedish company in Älvsjö; "Lifeline
Ventures" matches a British healthcare provider, a Swedish namesake and the
Finnish VC. Registered identifiers do not collide, and `/entities/lookup` takes
exactly those:

```
GLEIF       name → LEI → Cala entity     (verified: Supercell Oy)
SEC Form D  name → CIK → Cala entity
Companies House / SIREN                  (UK / France)
```

So the public sources are not an alternative to Cala — they are how you enter it
without guessing. **SEC Form D** also stands alone: a US private placement must
be filed within 15 days of first sale, so a filing with no matching round in the
graph means a company is raising and has not said so. Abridge filed 2026-09-11.

## The map

376 entities: Slush 2026 exhibitors, funded companies, and funds, shown together
with distinct marker shapes. MapLibre GL over OpenFreeMap vector tiles, library
vendored so only tiles need the network.

Addresses are geocoded against Nominatim and cached. City-centroid fallbacks are
drawn hollow and counted — the earlier version scattered them with jitter, which
invented positions and dropped companies into the Gulf of Finland.

Colour is **funding status**, not conviction. The graph walk showed Slush's floor
is overwhelmingly pre-funding — of the first 156 checked, most have never raised
— so conviction would have produced a map of grey dots. The map answers what the
data supports.

## What we learned about Cala

**Cala QL is LLM-interpreted and not deterministic in *schema*.** The same query
returned different fields per investor — dates for one, none for another, a bare
portfolio list for a third. Naming the fields explicitly in natural language
stabilises it and took coverage from 3/8 to 28/30 European funds.

**Introspect, never guess.** Every expensive mistake here was a guessed field
name. Companies store `headquarters_address`; investor Organizations store
`registered_address` — guessing the first returned nothing for every fund.
`/entities/lookup` 422s on `{"input": name}` because it is identifier-only,
which cost a day of name-matching heuristics before we read the error properly.

## Running it

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
echo "CALA_API_KEY=..." > .env          # GITHUB_TOKEN optional, raises 60/hr to 5000

.venv/bin/python recon.py                       # what this Cala account exposes
.venv/bin/python precompute.py investors.txt    # fill the cache
.venv/bin/python precompute_conviction_corpus.py
.venv/bin/python backtest.py

CALA_CACHE_ONLY=1 .venv/bin/python -m uvicorn app.api:app --port 8077
```

`CALA_CACHE_ONLY=1` is the demo guard: a cache miss is reported as missing data
rather than waiting 45s on a live query. Every long job is paced and resumable,
because Cala's quota is a budget over time — waiting beats aborting.

## Tests

```bash
.venv/bin/python -m pytest tests/ -q      # 145, none of which call Cala
```

Every bug found along the way has a regression test: name normalisation
(`Index Ventures` ≠ `Index Ventures LLP` silently zeroed every metric), schema
variation, a donut that drew nothing at 100%, a conviction score that saturated
so a dozen companies tied at exactly 100.0, and a 1-of-1 insider outranking 6-of-6.
