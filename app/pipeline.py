"""Where a fund takes you.

Everything else in this product scores an investor in isolation: do they lead,
do they follow on, are they still deploying. None of that answers the question
a founder is actually deciding - if I take this money now, who leads my next
round?

That is a transition in the graph, not an attribute of a node:

    investor on round k  ->  lead of round k+1

Across the rounds already cached it yields 2,545 observations and needs no
further Cala calls. Index Ventures hands off 48 times, most often to Tiger
Global, Accel and Spark. Creandum to Valar, Index and Accel.

It also exposes who the connectors are. A fund that hands off to many distinct
leads sits between clusters; one that always hands to the same two does not.
Both facts are useful and neither is on anybody's website.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import norm

import re

MIN_OBS = 3          # below this a handoff pattern is an anecdote

# Angels sit on cap tables and are named like people. They are real investors
# but they are not syndicate members a founder can go and assemble, so they
# are excluded from syndicate construction (not from co-investment counts).
# A parenthetical gloss is the tell: funds do not introduce themselves as
# "(MD of Zalando Payments)". Match any role word, or the "<role> of <org>"
# shape, rather than enumerating every title.
PERSONISH = re.compile(
    r"\((?:[^)]*\b(?:co-?founder|founder|ceo|cto|coo|cfo|cmo|md|vp|svp|evp|"
    r"chair(?:man|woman)?|president|director|head|owner|partner|angel|"
    r"investor|former|ex|board|advisor|adviser)\b|[^)]*\bof\b)"
    r"|\b(?:mr|ms|mrs|dr|prof)\b\.?\s", re.I)
FUNDISH = re.compile(
    r"\b(ventures?|capital|partners?|fund|invest|equity|holdings?|management|"
    r"associates|group|labs?|bank|collective|syndicate|accelerator|"
    r"ab|oy|oyj|gmbh|ltd|llp|llc|inc|plc|sa|bv|kb|ky)\b", re.I)


# A name is a person when it opens with a given name and carries no fund word.
# A bounded list beats a shape rule: "Y Combinator" and "Follower One" are two
# capitalised words too, and a shape rule throws them out with the angels.
GIVEN = set("""
ilkka niklas christian jane john james robert michael william david richard
thomas charles daniel matthew anthony mark steven paul andrew joshua kevin
brian george timothy ronald jason edward jeffrey ryan jacob gary nicholas
eric stephen jonathan larry justin scott brandon benjamin samuel gregory
alexander patrick frank raymond jack dennis jerry tyler aaron henry douglas
peter adam nathan zachary walter kyle harold carl jeremy keith roger gerald
mary patricia jennifer linda elizabeth barbara susan jessica sarah karen
nancy lisa margaret betty sandra ashley dorothy kimberly emily donna michelle
carol amanda melissa deborah stephanie rebecca laura helen sharon cynthia
kathleen amy shirley angela anna ruth brenda pamela nicole katherine samantha
christine emma catherine virginia rachel carolyn janet maria heather diane
julie joyce victoria kelly christina joan evelyn lauren judith olivia frances
martha cheryl megan andrea hannah jacqueline ann jean alice kathryn gloria
teresa doris sara janice julia marie madison grace judy theresa beverly
denise marilyn amber danielle rose brittany diana abigail natalie jane lori
mikko matti jussi antti juha pekka timo kari heikki seppo hannu jari markku
esa petri jorma mika veikko lasse olli tuomas ville sami joni eero aleksi
anni laura johanna anne tiina sanna katja minna satu paivi riitta leena
erik lars anders per johan karl magnus fredrik gustav sven bjorn olof hans
jonas martin stefan daniel jens mads lasse soren claus henrik rasmus kasper
morten thomas kristian steffen frode geir trond arne knut rune tor oddvar
pierre jean luc michel philippe olivier nicolas francois laurent sebastien
julien vincent antoine maxime hugo lucas theo arthur louis gabriel raphael
hans klaus jurgen wolfgang dieter manfred helmut gerhard rainer bernd uwe
felix lukas jonas leon finn emil moritz oskar till jan bas sander joost
marco luca andrea giuseppe francesco antonio matteo lorenzo alessandro
carlos juan jose luis miguel pedro javier antonio manuel francisco rafael
""".split())


PARTICLES = {"da", "de", "del", "della", "di", "du", "la", "le", "van", "von",
             "der", "den", "ter", "ten", "af", "av", "al", "bin", "dos", "das"}


def looks_like_a_fund(name: str) -> bool:
    """A fund, not a person. Errs toward keeping anything ambiguous."""
    n = (name or "").strip()
    if not n or PERSONISH.search(n):
        return False
    if FUNDISH.search(n):
        return True
    # "Philippe Teixeira da Mota" is three name words and a particle, not four.
    words = [w for w in re.split(r"[\s,]+", n) if w and w.lower() not in PARTICLES]
    if 2 <= len(words) <= 4 and words[0].lower().strip(".") in GIVEN:
        if all(w.replace("-", "").replace("'", "").isalpha() for w in words):
            return False
    return True


def build(rounds_by_company: dict[str, list[dict]]) -> dict:
    """{handoffs, co_invest, led_by, totals} keyed on normalised names."""
    handoff: dict[str, Counter] = defaultdict(Counter)
    co: dict[str, Counter] = defaultdict(Counter)
    led_by: dict[str, Counter] = defaultdict(Counter)   # who led INTO this fund's companies
    # Who shows up on a round that THIS fund led. Co-investment in general is
    # not the same thing: a syndicate needs funds that follow a given lead,
    # not funds that merely appear somewhere near them.
    follows: dict[str, Counter] = defaultdict(Counter)
    led_rounds: Counter = Counter()
    display: dict[str, str] = {}

    def remember(name: str) -> str | None:
        k = norm.name(name)
        if len(k) < 3:
            return None
        if len(name) > len(display.get(k, "")):
            display[k] = name.strip()
        return k

    for rs in rounds_by_company.values():
        rs = sorted(rs or [], key=lambda r: r.get("date") or "")
        for i, r in enumerate(rs):
            invs = [k for k in (remember(x) for x in (r.get("investors") or [])) if k]
            # who sits on a cap table together
            for a in invs:
                for b in invs:
                    if a != b:
                        co[a][b] += 1
            for L in (k for k in (remember(x) for x in (r.get("leads") or [])) if k):
                led_rounds[L] += 1
                for other in invs:
                    if other != L:
                        follows[L][other] += 1

            if i + 1 >= len(rs):
                continue
            leads = [k for k in (remember(x) for x in (rs[i + 1].get("leads") or [])) if k]
            for a in invs:
                for L in leads:
                    if L != a:
                        handoff[a][L] += 1
                        led_by[L][a] += 1

    return {"handoff": handoff, "co": co, "led_by": led_by,
            "follows": follows, "led_rounds": led_rounds, "display": display}


def where_it_takes_you(graph: dict, investor: str, top: int = 6) -> dict:
    """Who leads the next round after this fund is on the cap table."""
    k = norm.name(investor)
    c: Counter = graph["handoff"].get(k) or Counter()
    total = sum(c.values())
    disp = graph["display"]
    rows = [{"name": disp.get(n, n), "count": v,
             "share": round(v / total, 3) if total else None}
            for n, v in c.most_common(top)]
    return {"investor": disp.get(k, investor), "observations": total,
            "distinct_leads": len(c), "next_leads": rows,
            # Many distinct leads from the same base means this fund connects
            # clusters rather than feeding one. Concentration is the inverse.
            "concentration": round(c.most_common(1)[0][1] / total, 3) if total else None,
            "enough": total >= MIN_OBS}


def who_leads_into(graph: dict, investor: str, top: int = 6) -> dict:
    """The reverse: whose companies does this fund end up leading?"""
    k = norm.name(investor)
    c: Counter = graph["led_by"].get(k) or Counter()
    disp = graph["display"]
    return {"investor": disp.get(k, investor), "observations": sum(c.values()),
            "from": [{"name": disp.get(n, n), "count": v} for n, v in c.most_common(top)]}


def co_investors(graph: dict, investor: str, top: int = 8) -> list[dict]:
    k = norm.name(investor)
    c: Counter = graph["co"].get(k) or Counter()
    disp = graph["display"]
    return [{"name": disp.get(n, n), "count": v} for n, v in c.most_common(top)]


def connectors(graph: dict, top: int = 12) -> list[dict]:
    """Funds whose handoffs spread widest - the bridges in the network."""
    out = []
    for k, c in graph["handoff"].items():
        total = sum(c.values())
        if total < MIN_OBS * 2:
            continue
        out.append({"name": graph["display"].get(k, k), "handoffs": total,
                    "distinct_leads": len(c),
                    "spread": round(len(c) / total, 3)})
    out.sort(key=lambda x: (-x["distinct_leads"], -x["handoffs"]))
    return out[:top]


# ---------------------------------------------------------------- syndicates
def syndicate(graph: dict, lead: str, *, exclude: set[str] | None = None,
              size: int = 2, min_rounds: int = 2) -> dict:
    """A lead plus the funds that actually show up when that lead leads.

    Generic co-investment is the wrong signal here: two funds can appear on
    many of the same cap tables without one ever following the other. What a
    founder needs is who joins rounds THIS fund leads, and how reliably.
    """
    k = norm.name(lead)
    disp, follows = graph["display"], graph["follows"].get(k) or Counter()
    led = graph["led_rounds"].get(k, 0)
    ex = {norm.name(x) for x in (exclude or set())} | {k}

    members = []
    for name, n in follows.most_common(60):
        if name in ex or n < 1:
            continue
        if not looks_like_a_fund(disp.get(name, name)):
            continue
        members.append({"name": disp.get(name, name), "joined": n,
                        "share": round(n / led, 3) if led else None})
        if len(members) >= size:
            break

    return {"lead": disp.get(k, lead), "rounds_led": led, "members": members,
            # Below a couple of led rounds this is one anecdote, not a pattern.
            "enough": led >= min_rounds and bool(members)}


def warm_path(graph: dict, backers: list[str], target: str,
              rounds_by_company: dict[str, list[dict]] | None = None) -> list[dict]:
    """Two hops: your backer -> a company you both sat on -> the target fund.

    Returns the connecting company by name, because "ask Voima" is advice and
    "ask Voima, who co-invested with them in X" is an introduction.
    """
    t = norm.name(target)
    out = []
    for b in backers or []:
        kb = norm.name(b)
        if not kb or kb == t:
            continue
        shared = []
        for company, rs in (rounds_by_company or {}).items():
            names = {norm.name(i) for r in (rs or []) for i in (r.get("investors") or [])}
            if kb in names and t in names:
                dated = sorted((r for r in rs if r.get("date")), key=lambda r: r["date"])
                shared.append({"company": company,
                               "when": (dated[-1]["date"] if dated else None),
                               "stage": (dated[-1].get("stage") if dated else None)})
        if shared:
            shared.sort(key=lambda x: x["when"] or "", reverse=True)
            out.append({"via": graph["display"].get(kb, b),
                        "target": graph["display"].get(t, target),
                        "through": shared[:3], "strength": len(shared)})
    out.sort(key=lambda x: -x["strength"])
    return out


def follow_rounds(rounds_by_company: dict, lead: str, member: str) -> list[dict]:
    """The actual rounds behind "joins 25% of the rounds they lead".

    The graph stores the count; a founder about to say that number out loud
    needs the list. Returns every round this lead led, flagged with whether
    the member was in it, newest first - so the denominator is visible too
    and "2 of 8" can be read rather than taken.
    """
    kl, km = norm.name(lead), norm.name(member)
    out = []
    for company, rs in (rounds_by_company or {}).items():
        for r in rs or []:
            leads = {norm.name(x) for x in (r.get("leads") or [])}
            if kl not in leads:
                continue
            names = {norm.name(i) for i in (r.get("investors") or [])}
            out.append({"company": company, "date": r.get("date"),
                        "stage": r.get("stage"),
                        "joined": km in names,
                        "investors": [i for i in (r.get("investors") or [])][:8]})
    out.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
    return out


def shared_rounds(rounds_by_company: dict, a: str, b: str) -> list[dict]:
    """Rounds both of these investors were in - the evidence for a warm route."""
    ka, kb = norm.name(a), norm.name(b)
    out = []
    for company, rs in (rounds_by_company or {}).items():
        for r in rs or []:
            names = {norm.name(i) for i in (r.get("investors") or [])}
            if ka in names and kb in names:
                out.append({"company": company, "date": r.get("date"),
                            "stage": r.get("stage"),
                            "investors": (r.get("investors") or [])[:8]})
    out.sort(key=lambda x: str(x.get("date") or ""), reverse=True)
    return out
