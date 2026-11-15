## Inspiration

Every investor database — PitchBook, Harmonic, Crunchbase — tells you about a
founder *after* they've founded. By then the company has a name, a round, a
valuation, and eleven other funds already in the inbox. The moment that's
actually worth money to a VC is earlier than that, and nobody sells it,
because on paper it hasn't happened yet. Cala's knowledge graph holds the
relationships that come before a founding — who left what, who worked where,
who's building something nobody's announced — and almost none of it gets
read by products built on top of it. We built Flipside to read it.

## What it does

Flipside is a sourcing tool for the people who haven't founded anything yet.
Instead of one ranked list, it's four cohorts — four moments in one person's
life, from latest to earliest:

- **Founded before** — people who've already done it. The strongest, latest,
  and most visible signal; everyone else can see this one too.
- **Building in public** — shipped something and said so: Show HN launches,
  plus accelerator batches (YC, Techstars, Entrepreneur First, Antler, a16z
  Speedrun) merged into one pool rather than kept as a separate category,
  since a batch company *is* building in public. 498 companies tracked; 470
  of them aren't in Cala's graph at all.
- **Building in private** — a repository started weeks ago, commits this
  week, almost no stars yet. Pulled from GitHub, GitLab, Hugging Face,
  arXiv and Devpost, scored on depth and momentum rather than popularity,
  because popularity is exactly the signal that arrives too late.
- **Not started yet** — a senior person at a company, no company of their
  own, scored on the tenure window people actually leave in (two to five
  years — the longest-serving person is statistically the *least* likely to
  go, not the most).

On top of the cohorts: a departures view built from something nobody else
reads off Cala's graph — 813 relationship edges carry a `valid_until`, the
date a role *ended*, and every other product built on this graph reads only
`valid_since`. An ended seat with nothing started since is a person who is,
on the record, unaccounted for, and that gap comes before the company
exists. 88 such people, scored by what they left and how recently, labelled
"announced" when the end date is still in the future.

A pipeline and call list modeled on tools VCs already use (Folk, Clay), a
map with company logos and country flags instead of generic pins, warm-path
and co-investor views, and a thesis search ("fintech payments") that
surfaces the regulation that actually governs a sector, pulled from 3,777
`AFFECTS_INDUSTRY` edges nobody had queried before.

## How we built it

Python/FastAPI backend, a single-file HTML/CSS/JS frontend with MapLibre GL
for the map. Six bulk question templates hit Cala's `/knowledge/query`
endpoint directly instead of walking entities one at a time — one query
returns a structured table of 10–40 rows for roughly the cost of one entity
fetch, which turned questions like "who did this fund's founders work for
before founding" from an anecdote (one employer with three known leavers)
into 31 named employers with real founder counts, in the same afternoon.
Open data — GDELT, HN Algolia, GitHub/GitLab/Hugging Face/arXiv/Devpost,
GLEIF, Nominatim — fills in what Cala doesn't carry. 695 automated tests and
an 18-path rehearsal script gate every change.

## Challenges we ran into

Cala's rate limiter is a token bucket with no rate-limit headers, so the
real ceiling had to be measured rather than assumed — our first estimate
was 10x too conservative because it was measured while our own unthrottled
harvester was starving it. A silent failure mode cost us a full harvest
run: a refused question and an answered-but-empty one both returned zero,
so a 868-question run reported "complete" while 554 of those had never
reached the server. Fixed by raising a distinct exception on refusal and
retrying instead of moving on quietly.

## What we're proud of

Every number on screen is computed, sourced, and says what it can't do —
including a backtest on our own round-prediction model that says it
failed, left in the product rather than removed. We didn't add data to
Cala. We asked it questions nobody had asked yet.

## What's next

The bulk-query trick scales to more questions per entity type — exits,
board composition, prior education, angel participation are already
wired in and filling as the harvest runs. A public-comparables layer
(`LISTED_ON`/`TRADED_ON` edges, 200 of them, currently untouched) is the
next unused corner of the graph worth reading.
