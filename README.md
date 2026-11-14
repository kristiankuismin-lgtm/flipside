# Flipside

**Every tool tells a founder who to pitch. None tells them who not to.**

You send your deck, your metrics and your customer pipeline to a fund that is
already funding your competitor. They keep it. They are allowed to. Flipside
answers the question first — *who is out* — and only then *who is left*.

One audience: a founder raising a round. Built on [Cala](https://cala.ai) for
Junction 2026.

| | The question | Where it is answered |
|---|---|---|
| **Who is out** | Which funds already fund my competitor? | Your round |
| **Who is left** | Of the rest, who actually leads at my stage and is still deploying? | Your round |
| **Who do I call** | Which named person at each one, and in what order? | Call list |
| **What changes it** | Which competitor round makes another fund un-pitchable? | Watch |

The investor-side reading was cut on purpose. Two audiences is two products,
and the brief asks for one need solved well.

The product opens on the exclusion:

> **3 of 14 funds on this list already fund Corti or Tandem Health.
> Do not send them your deck.**
> Byfounders → Corti · Nordic Makers → Corti · Northzone → Tandem Health
>
> *10 funds are left. 3 of them lead at Series A. 1 can be reached through
> someone you know.*

That is two hops in a graph — `you → competes with → company → raised → investor` —
and it is the one claim here that cannot be looked up, only computed.

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

## Round architect

A ranked list is a shopping list; a round is a syndicate. For each fund that
genuinely leads at the founder's stage, we propose the two funds that show up
**when that fund leads** — which is a different edge from generic
co-investment, and the one a founder can actually assemble:

| Lead | Rounds led | Who follows them in |
|---|---|---|
| Balderton Capital | 11 | Creandum (3×, 27%) · Coparion (2×, 18%) |
| Atomico | 8 | World Innovation Lab (2×, 25%) · Lightspeed (1×, 13%) |
| Creandum | 7 | Index Ventures (2×, 29%) · EQT Ventures (1×, 14%) |

Every one of those numbers opens the rounds behind it — **all** the rounds the
lead led, not only the ones the member joined, because "2 of 8" cannot be read
unless the other six are on screen.

Where no warm route exists we say so once, plainly, and name the route that
does: for Gosta Labs, Voima Ventures reaches Icebreaker.vc, which does not
lead at this stage. A door in, not a lead.

## Every figure opens its evidence

Fifty-eight figures on the founder screen are buttons. Each opens the claim,
its observation count and confidence, the rounds underneath with dates and
amounts, any cited document URLs, and the UTC time the screen was retrieved —
a number with no retrieval time can be believed but not checked.

The scores open their own arithmetic rather than rounds: fit, signal quality
with the share of signals actually known, lead factor, conflict, warm route
and recency, ending in the expression that produces the number. The conviction
score does the same, and a test pins the breakdown to the scorer so the drawer
cannot disagree with the figure it explains.

## Where the sources disagree

A product built on a graph inherits the graph's disagreements. Vanta's Series B
is on record at both €101.2M and €36.8M, with different leads, dated four
months apart. We used to pick one and print it as fact.

151 disagreements across 80 companies, 35 of them hard. Both readings are
shown, no winner is chosen, and the founder table carries the count per fund —
before you repeat one of these figures to the fund itself, know that our own
sources do not agree on it.

Deliberately **not** flagged: amounts within 15% (rounding and currency), the
same lead spelled two ways (normalisation already knows), and co-leads, which
are real and are counted separately rather than shown as errors.

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

## Evidence ages

Conviction is evidence that insiders chose to put more money in. A four-year-old
instance of that is still a fact and much weaker evidence about this week.
Ankorstore's last round closed in January 2022 and it ranked **#1**; it now
ranks #53, 84.1 → 33.6.

Flat inside a grace period, halving after it, floored — discounted, never
erased, and an unknown date is treated as current because we do not know that
it is old. Both halves of the product age their evidence, with constants that
differ on purpose: funds age more slowly than companies (18-month grace, 24-month
half-life, 0.55 floor) than rounds do (12, 18, 0.40). A test pins the two apart
so they cannot quietly converge.

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

1,242 placed entities: Slush 2026 exhibitors, funded companies, and funds, shown
together with distinct marker shapes. Exhibitors are off by default — 676
pre-funding stands drown out 173 funds, and "where is the ecosystem" is not
answered by a conference floorplan. MapLibre GL over OpenFreeMap vector tiles, library
vendored so only tiles need the network.

Addresses are geocoded against Nominatim and cached. City-centroid fallbacks are
drawn hollow and counted — the earlier version scattered them with jitter, which
invented positions and dropped companies into the Gulf of Finland.

A registry address and the firm's own description are cross-checked, because
the GLEIF name-to-LEI join lands on namesakes abroad: HV Capital (Munich) was
pinned to Tampere, Spark Capital (Boston) to Tallinn, Alliance Venture (Prague)
to Stockholm. Eleven funds were disputed and re-placed by description, fifteen
had no resolvable address at all, and the registry string is kept as evidence
rather than as a location.

"Near me" ranks the graph by great-circle distance from the browser's own
geolocation, asked for with consent and used for one request. No IP lookup —
that means telling a third party where you are in order to find out where you
are.

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
cp .env.example .env                    # CALA_API_KEY required; GITHUB_TOKEN optional

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
.venv/bin/python -m pytest tests/ -q      # 259, none of which call Cala
node tests/test_ask_routing.mjs           # 29 more, for the Ask router
CALA_CACHE_ONLY=1 .venv/bin/python rehearse.py   # walk the demo, timed
```

`rehearse.py` walks the three-minute demo end to end — every endpoint it
touches, with a time budget and a check on what came back, because a 200
carrying an error payload is the failure that looks fine until you are standing
in front of judges. **15/15 clean, 2s end to end** with no network at all.

Every bug found along the way has a regression test: name normalisation
(`Index Ventures` ≠ `Index Ventures LLP` silently zeroed every metric), schema
variation, a donut that drew nothing at 100%, a conviction score that saturated
so a dozen companies tied at exactly 100.0, and a 1-of-1 insider outranking 6-of-6.
