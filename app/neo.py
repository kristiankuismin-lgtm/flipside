"""Ask Neo: answers about what is actually in Flipside.

Two halves, and the split is the point.

The answer is **computed**, never generated: every figure comes from the
same functions that drew the screen, so Neo cannot say something the product
does not already show. When no model key is set it answers in its own plain
sentences and loses nothing but polish. When ANTHROPIC_API_KEY is set, the
model is handed the computed facts and asked only to phrase them, and
numbercheck rejects any figure the facts do not contain.

That is the rule this codebase already states: rules decide, the model only
writes. An assistant on top of a diligence tool that could hallucinate a
lead rate would be worse than no assistant.
"""
from __future__ import annotations

import re

from . import norm

# --- what is this question about? -------------------------------------------
# Scored, not first-match, for the reason ask.js is: one incidental word
# must not outvote a phrase.
TOPICS = [
    ("conflict", [(r"\b(?:conflict|competitor|compet\w+|avoid|do not pitch|don't pitch)\b", 5),
                  (r"\bback\w*\s+(?:a\s+)?competitor\b", 6)]),
    ("warm", [(r"\b(?:warm|intro|introduction|who can introduce|connect\w*)\b", 5),
              (r"\broute\b", 3)]),
    ("syndicate", [(r"\b(?:syndicate|co-?invest\w*|follows?\b|who else|round architect)\b", 5),
                   (r"\bwho comes? (?:in|with)\b", 6)]),
    ("rank", [(r"\b(?:who should i (?:meet|pitch|talk)|best|top|first|shortlist|rank\w*)\b", 5),
              (r"\bwho leads?\b", 4)]),
    ("evidence", [(r"\b(?:evidence|source|sources|where (?:does|did) .*(?:come|from)|prove|citation)\b", 5),
                  (r"\bhow do you know\b", 6)]),
    ("accuracy", [(r"\b(?:backtest|accurate|accuracy|validated?|predictive)\b", 6),
                  # "does this actually work" — an adverb must not break it
                  (r"\bdoes (?:it|this|that)\s+(?:\w+\s+)?work\b", 6),
                  (r"\b(?:is (?:it|this) any good|can i trust)\b", 6)]),
    ("coverage", [(r"\b(?:how (?:much|many)|coverage|data\b|cached|entities|rounds on record)\b", 4)]),
    ("disagree", [(r"\b(?:disagree|contradict\w*|conflicting sources|unreliable)\b", 6)]),
    ("stale", [(r"\b(?:stale|old|recent|recency|fresh|out of date|up to date)\b", 5)]),
    ("method", [(r"\b(?:how (?:is|do you) .*(?:score|comput|calculat|work)|methodolog\w*|"
                 r"what does .* mean|why is .* (?:ranked|scored))\b", 5)]),
]


def topic(q: str) -> str:
    low = (q or "").lower()
    best, score = "rank", 0
    for name, pats in TOPICS:
        for rx, w in pats:
            if re.search(rx, low) and w > score:
                best, score = name, w
    return best if score else "rank"


def named_investor(q: str, investors: list[dict]) -> dict | None:
    """Which fund, if any, is this question about?

    Longest name first, so "Index Ventures" is not matched as "Index".
    """
    low = (q or "").lower()
    for x in sorted(investors or [], key=lambda i: -len(i.get("investor") or "")):
        name = (x.get("investor") or "").lower()
        if len(name) >= 4 and name in low:
            return x
        bare = re.sub(r"\b(ventures?|capital|partners?|fund)\b", "", name).strip()
        if len(bare) >= 5 and bare in low:
            return x
    return None


def _pct(v) -> str:
    return "unknown" if v is None else f"{round(v * 100)}%"


# --- the answers ------------------------------------------------------------
def answer(question: str, ctx: dict) -> dict:
    """{headline, bullets, facts, followups} computed from the live context.

    `facts` is the numeric ground truth the phrasing must stay inside; it is
    what numbercheck validates a model's prose against.
    """
    q = (question or "").strip()
    if not q:
        return {"headline": "Ask me about anything on this screen.",
                "bullets": [], "facts": {}, "followups": _followups(ctx)}

    inv = ctx.get("investors") or []
    t = topic(q)
    who = named_investor(q, inv)
    if who is not None and t == "rank":
        t = "fund"          # a named fund turns a ranking question into a profile

    fn = {
        "fund": _about_fund, "conflict": _about_conflicts, "warm": _about_warm,
        "syndicate": _about_syndicate, "rank": _about_rank,
        "evidence": _about_evidence, "accuracy": _about_accuracy,
        "coverage": _about_coverage, "disagree": _about_disagree,
        "stale": _about_stale, "method": _about_method,
    }[t]
    out = fn(q, ctx, who)
    out.setdefault("followups", _followups(ctx, t))
    out["topic"] = t
    return out


def _about_fund(q, ctx, who):
    if who is None:
        return _about_rank(q, ctx, who)
    s = who.get("signals") or {}
    b = who.get("breakdown") or {}
    facts = {"score": who.get("score"), "lead_rate": (s.get("lead_rate") or {}).get("value"),
             "follow_on": (s.get("follow_on") or {}).get("value"),
             "rounds_seen": who.get("rounds_seen"),
             "months_since": b.get("months_since_activity")}
    conflicted = (s.get("conflict") or {}).get("label") == "\U0001f534"
    bullets = []
    if (s.get("lead_rate") or {}).get("text"):
        bullets.append(s["lead_rate"]["text"])
    if (s.get("follow_on") or {}).get("text"):
        bullets.append(s["follow_on"]["text"])
    if (s.get("dry_powder") or {}).get("text"):
        bullets.append(s["dry_powder"]["text"])
    if b.get("months_since_activity") is not None:
        bullets.append(f"last active {b['months_since_activity']} months ago"
                       + (" — stale" if b.get("stale") else ""))
    route = (s.get("warm_path") or {})
    bullets.append(route["text"] if route.get("label") != "⚪" and route.get("text")
                   else "no warm route reaches them")
    syn = next((y for y in (ctx.get("syndicates") or [])
                if norm.name(y["lead"]) == norm.name(who["investor"])), None)
    if syn and syn.get("members"):
        bullets.append("when they lead, "
                       + " and ".join(f"{m['name']} comes in "
                                      f"({round((m.get('share') or 0) * 100)}% of their led rounds)"
                                      for m in syn["members"][:2]))
    head = (f"{who['investor']} backs {', '.join(who.get('backs') or ['a competitor'])} — "
            f"do not pitch them." if conflicted
            else f"{who['investor']} scores {who.get('score')} out of 100 on this screen.")
    return {"headline": head, "bullets": bullets, "facts": facts,
            "open": {"kind": "investor", "name": who["investor"]}}


def _about_conflicts(q, ctx, who):
    inv = ctx.get("investors") or []
    red = [x for x in inv if (x.get("signals") or {}).get("conflict", {}).get("label") == "\U0001f534"]
    if not red:
        return {"headline": "No fund on this list backs a named competitor.",
                "bullets": [f"{len(inv)} funds screened against "
                            f"{len(ctx.get('competitors') or [])} competitors Cala names"],
                "facts": {"conflicted": 0, "screened": len(inv)}}
    return {"headline": f"{len(red)} of {len(inv)} funds already back a competitor.",
            "bullets": [f"{x['investor']} backs {', '.join(x.get('backs') or [])}" for x in red],
            "facts": {"conflicted": len(red), "screened": len(inv)},
            "open": {"kind": "filter", "name": "conflict"}}


def _about_warm(q, ctx, who):
    inv = ctx.get("investors") or []
    warm = [x for x in inv if (x.get("signals") or {}).get("warm_path", {}).get("label") != "⚪"]
    if not warm:
        return {"headline": "No warm route reaches any fund on this list.",
                "bullets": ["nothing in the cached graph puts your backers and these "
                            "funds on the same cap table",
                            "every introduction here starts cold, which is what the "
                            "Slush floor is for"],
                "facts": {"warm": 0, "screened": len(inv)}}
    return {"headline": f"{len(warm)} of {len(inv)} funds are one introduction away.",
            "bullets": [f"{x['investor']} — {x['signals']['warm_path']['text']}" for x in warm],
            "facts": {"warm": len(warm), "screened": len(inv)},
            "open": {"kind": "filter", "name": "warm"}}


def _about_syndicate(q, ctx, who):
    syns = ctx.get("syndicates") or []
    if not syns:
        return {"headline": "No assemblable syndicate on this list.",
                "bullets": ["a syndicate needs a fund that leads at this stage and "
                            "other funds that repeatedly follow it"],
                "facts": {"syndicates": 0}}
    pick = next((s for s in syns if who and norm.name(s["lead"]) == norm.name(who["investor"])),
                syns[0])
    return {"headline": f"Build the round around {pick['lead']}, "
                        f"with {' and '.join(m['name'] for m in pick['members'])} following.",
            "bullets": [f"{m['name']} joined {m['joined']} of the {pick['rounds_led']} rounds "
                        f"{pick['lead']} led ({round((m.get('share') or 0) * 100)}%)"
                        for m in pick["members"]]
                       + ([f"{len(syns)} syndicates are assemblable from this list"]
                          if len(syns) > 1 else []),
            "facts": {"syndicates": len(syns), "rounds_led": pick["rounds_led"]},
            "open": {"kind": "investor", "name": pick["lead"]}}


def _about_rank(q, ctx, who):
    inv = [x for x in (ctx.get("investors") or []) if x.get("score") is not None]
    clean = [x for x in inv
             if (x.get("signals") or {}).get("conflict", {}).get("label") != "\U0001f534"]
    if not clean:
        return {"headline": "Nothing on this list is rankable yet.",
                "bullets": ["run a screen first, or every fund is conflicted"],
                "facts": {}}
    top = clean[:3]
    return {"headline": f"Meet {top[0]['investor']} first.",
            "bullets": [f"{x['investor']} — {x.get('score')}/100, "
                        f"{(x['signals'].get('lead_rate') or {}).get('text') or 'lead rate unknown'}"
                        for x in top]
                       + [f"{len(clean)} of {len(inv)} scored funds have no competitor conflict"],
            "facts": {"top": top[0].get("score"), "clean": len(clean), "scored": len(inv)},
            "open": {"kind": "investor", "name": top[0]["investor"]}}


def _about_evidence(q, ctx, who):
    return {"headline": "Every figure on screen opens the rounds behind it.",
            "bullets": [
                "click any number — lead rate, follow-on, pace, score — and it shows "
                "the rounds it was computed over, with dates, amounts and any "
                "document URLs",
                f"the screen was retrieved {ctx.get('fetched_at') or 'this session'}, "
                "and that timestamp is on every drawer",
                "a score opens its own arithmetic instead: fit, signal quality, "
                "lead factor, conflict, warm route and recency",
            ],
            "facts": {}}


def _about_accuracy(q, ctx, who):
    bt = ctx.get("backtest") or {}
    if not bt:
        return {"headline": "The backtest is in the sidebar under “Does it work?”.",
                "bullets": [], "facts": {}}
    hi = (bt.get("high_insider_return") or {})
    naive = (bt.get("naive_most_active") or {})
    return {"headline": f"Measured on {bt.get('samples')} companies: the signal lifts "
                        f"progression by {round(hi.get('lift_pp', 0), 1)} points, the "
                        f"obvious alternative by {round(naive.get('lift_pp', 0), 1)}.",
            "bullets": [
                f"companies where at least half the prior investors came back "
                f"progressed {_pct(hi.get('rate'))} of the time",
                f"base rate across all {bt.get('samples')} is {_pct(bt.get('base_rate'))}",
                f"ranking by “whoever invests most” instead gets {_pct(naive.get('rate'))}",
                "the cap-table-size control where the signal reverses is shown, not filtered out",
            ],
            "facts": {"samples": bt.get("samples"), "spread_pp": bt.get("spread_pp")},
            "open": {"kind": "view", "name": "accuracy"}}


def _about_coverage(q, ctx, who):
    h = ctx.get("health") or {}
    return {"headline": f"{h.get('entities_cached', 0):,} entities and "
                        f"{h.get('rounds_cached', 0):,} rounds are cached locally.",
            "bullets": [
                f"{h.get('conviction_n', 0)} companies scored on the investor side",
                f"{h.get('people_cached', 0)} people, of which very few carry the "
                f"relationships the founder signal needs",
                "live lookups are "
                + ("off — everything here is local" if h.get("cache_only") else "enabled"),
            ],
            "facts": {"entities": h.get("entities_cached"), "rounds": h.get("rounds_cached")}}


def _about_disagree(q, ctx, who):
    cx = ctx.get("contradictions") or {}
    if not cx.get("hard"):
        return {"headline": "No hard disagreements in the rounds behind this screen.",
                "bullets": [], "facts": {"hard": 0}}
    items = [i for i in (cx.get("items") or []) if not i.get("soft")][:4]
    return {"headline": f"{cx['hard']} places where two records of the same round disagree.",
            "bullets": [f"{i['company']}: {i['field']} — “{i.get('a')}” against "
                        f"“{i.get('b')}”" for i in items]
                       + ["no winner is picked; both readings are shown"],
            "facts": {"hard": cx["hard"], "companies": cx.get("companies")}}


def _about_stale(q, ctx, who):
    inv = ctx.get("investors") or []
    stale = [x for x in inv if (x.get("breakdown") or {}).get("stale")]
    ages = [x["breakdown"]["months_since_activity"] for x in inv
            if (x.get("breakdown") or {}).get("months_since_activity") is not None]
    return {"headline": (f"{len(stale)} of {len(inv)} funds have stale evidence."
                         if stale else "Every fund on this list is currently active."),
            "bullets": ([f"{x['investor']} — last active "
                         f"{x['breakdown']['months_since_activity']} months ago"
                         for x in stale[:4]] if stale else [])
                       + ([f"the oldest on the list last acted {max(ages)} months ago"]
                          if ages else [])
                       + ["scores are discounted with age, never erased, and an unknown "
                          "date is treated as current"],
            "facts": {"stale": len(stale), "screened": len(inv)}}


def _about_method(q, ctx, who):
    if who is not None:
        return _about_fund(q, ctx, who)
    return {"headline": "The score is fit × signal quality, then discounted.",
            "bullets": [
                "fit is stage, sector, geography and cheque size",
                "signal quality is a Wilson lower bound on each rate, so one "
                "observation at 100% never beats six at 67%",
                "a fund that has led none of at least three rounds at your stage is "
                "discounted; an unknown lead rate never is",
                "a competitor conflict multiplies the score to zero by construction",
                "and the whole thing is aged by how long ago the fund last acted",
            ],
            "facts": {}}


def _followups(ctx, t: str = "") -> list[str]:
    base = ["Who should I meet first?", "Who backs a competitor?",
            "Who can introduce me?", "Does this actually work?"]
    extra = {"rank": "Why is that one first?", "conflict": "Who is safe to pitch?",
             "warm": "What do I say to them?", "accuracy": "How much data is this on?",
             "fund": "Who comes in when they lead?"}.get(t)
    out = ([extra] if extra else []) + [b for b in base]
    return out[:4]
