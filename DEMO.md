# Flipside — 3-minute demo

**One line:** investors run diligence on founders; Flipside runs it on them —
and then tells you who to put in the round, who can introduce you, and what to say.

**Demo company:** Gosta Labs (Finnish clinical AI, €7.5M seed Nov 2025 led by
Voima Ventures; Terveystalo and Reaktor on the cap table). Raising Series A.
Slush 2026 opens 18 November.

---

## 0:00 — The question (15s)

> "A founder at Slush has two days and a thousand funds. The question is not
> 'who exists' — it's *which ten do I meet, why them, who introduces me, and
> what do I open with.*"

Type **Gosta Labs**, Series A, Run diligence.

## 0:20 — The answer, not the data (35s)

The hero card answers in one sentence:

> **Build the round around Atomico, with World Innovation Lab and Lightspeed
> Venture Partners following them in.**

Three actions underneath. Click **1 — Open with Atomico**.

> "This is the part you can't get from a list. Atomico leads at Series A.
> World Innovation Lab joins a quarter of the rounds Atomico leads. That's
> not co-investment — plenty of funds share cap tables without ever
> following each other. It's who shows up *when this fund leads*."

## 0:55 — The brief writes itself (35s)

The drawer shows three sentences, each with the number under it:

- *You led 6 of 9 Series A rounds (67%)* → LEAD RATE
- *When you lead, Creandum comes in with you — 3 of the 11 rounds you led* → SYNDICATE
- *You are still deploying (13 new investments in 6 months)* → DRY POWDER

> "Every sentence carries its evidence. Nothing here is a vibe."

Now close it and click **Brief** on **Northzone**.

> "No brief. Northzone backs Tandem Health — a direct competitor. Refusing to
> write the pitch *is* the finding; pitching them hands over your numbers."

## 1:30 — Honesty about what we don't know (25s)

Scroll to the Round architect note:

> "No warm route reaches any of these leads. We say so once, plainly, and we
> name the route that *does* exist — Voima Ventures reaches Icebreaker.vc,
> which doesn't lead at this stage. A door in, not a lead. Most tools would
> have shown an empty state or, worse, invented a path."

## 1:55 — The same graph, read backwards (35s)

Switch to **Investor → Insider conviction**.

> "The founder side asks 'who should back me'. The investor side asks the same
> graph 'who are insiders doubling down on' — who's converting conviction into
> a second cheque."

Point at the **Age** column.

> "Ankorstore used to rank #1 here. Its last round closed in January 2022.
> Conviction is evidence that insiders put more money in — a four-year-old
> instance of that is a weaker claim about this week. We halve it every 18
> months after a one-year grace period, floored, never erased. Ankorstore
> went from 84 to 34, #1 to #53. The top is now 2026 rounds."

Click the **Bridges** card — the list filters to 20.

## 2:15 — Does it actually work? (20s)

Click **Does it work? · 498** in the sidebar.

> "Companies where at least half the prior investors came back progressed to a
> later stage 49% of the time, against a 39% base rate. Ranking instead by
> 'whoever invests most' — the first thing anyone would try — gets 41%. Our
> 10.2 points of lift against their 2.8, on 498 companies.
>
> And the row where it reverses, in single-investor cap tables, is in the
> product. We did not filter it out."

## 2:35 — Where the data comes from (15s)

Open any fund profile.

> "This is built on Cala's knowledge graph: 2,545 funding-round observations,
> every claim traceable. Two things we added on top — we check each firm's
> registry address against what the firm says about itself, which caught
> eleven funds pinned to the wrong country by a name-to-LEI collision; and we
> read each company's own homepage for what no database notices between
> rounds — a pricing page, a careers page."

## 2:50 — Close (10s)

> "One graph, three readings: who should back you, who insiders are backing,
> and who looks like a founder before they are one. The part nobody else can
> copy is the round architecture — because it isn't a list, it's the
> relationships between the funds."

---

## If asked

**Why not just use a VC database?** A list tells you Atomico exists. It does
not tell you that World Innovation Lab follows Atomico into a quarter of the
rounds it leads, or that your seed investor sat on a cap table with a target.
That lives in the edges, which is what a knowledge graph is for.

**What's the hardest thing you fixed?** Name collisions, three times over.
Exact string matching made every metric silently return 0%. The GLEIF
name-to-LEI join put a Munich fund in Tampere. And `norm.name()` strips legal
suffixes, which turned "NORRSKEN COMPANY LIMITED" into an exact match for
"Norrsken" and ranked a British construction firm above Norrsken VC.

**What doesn't work?** Cala credits ran out mid-build, so live lookups return
402. Everything demoed above runs from the 6,418 entities already cached —
`CALA_CACHE_ONLY=1 python rehearse.py` walks the whole demo path in 2 seconds
with no network at all, which is how we know the pitch cannot stall.

Three things the product says about itself rather than hiding: pre-emption
detection is starved, not absent (of 837 round records only 58 carry an
amount); the orphan detector can never fire, because Cala has no headcount
series for private companies; and the founder signal has no backtest, unlike
the other two readings.
