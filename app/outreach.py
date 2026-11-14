"""The Slush outreach brief: what to say to this fund, and why it is true.

A ranked list tells a founder who to talk to. It does not tell them what to
open with, and a generic opener is the reason most Slush conversations die in
the first thirty seconds.

Everything here is synthesised from facts already computed - lead rate at the
founder's stage, deployment pace, who follows this fund into rounds, whether
a warm route exists, which portfolio companies sit in the founder's sector.
Nothing is invented, and every sentence carries the numbers it came from, so
the founder can check a claim before repeating it to the person it is about.

The brief refuses to write itself when the fund backs a competitor. That is
not an error state - it is the most useful thing we can say about that fund.
"""
from __future__ import annotations

import re

from . import norm

# Sector words worth matching on. A founder's competitor list is the best
# description of their market that we have without asking them.
_STOP = re.compile(r"\b(and|the|of|for|&|/|,)\b", re.I)


def _sector_words(competitors: list[dict], description: str = "") -> set[str]:
    """What market is this founder in, in words a portfolio sector can match."""
    words = set()
    for c in competitors or []:
        for part in re.split(r"[/,&]| and ", (c.get("what") or "")):
            for w in _STOP.sub(" ", part).split():
                if len(w) > 3:
                    words.add(w.lower())
    for w in _STOP.sub(" ", description or "").split():
        if len(w) > 3:
            words.add(w.lower())
    return words


def sector_overlap(portfolio: list[dict], words: set[str], limit: int = 3) -> list[dict]:
    """Portfolio companies whose sector text overlaps the founder's market."""
    out = []
    for c in portfolio or []:
        sec = (c.get("sector") or "").lower()
        if not sec:
            continue
        hit = [w for w in words if w in sec]
        if hit:
            out.append({"name": c.get("name"), "sector": c.get("sector"),
                        "matched": sorted(hit)[:2]})
        if len(out) >= limit:
            break
    return out


def _quote(txt: str) -> str:
    """Drop a computed phrase into mid-sentence without a stray capital.

    Signal text is written to start a line ("Led 6 of 9 ..."), and "You Led"
    is the tell that a machine assembled the sentence.
    """
    t = (txt or "").strip()
    if t[:2].isupper():            # an acronym like "EU" keeps its case
        return t
    return t[:1].lower() + t[1:]


def _plain(txt: str) -> str:
    """Strip the working parenthetical: an email is not a debug line."""
    return re.sub(r"\s*\((?:prior|previous)[^)]*\)", "", txt or "").strip()


def _pct(v) -> str:
    return "—" if v is None else f"{round(v * 100)}%"


def brief(*, company: str, stage: str, investor: dict, syndicate: dict | None = None,
          competitors: list[dict] | None = None, event: str = "Slush 2026",
          event_date: str = "18 Nov") -> dict:
    """Three sentences and the evidence under each.

    Returns {blocked, reason, sentences[], evidence[], subject, body} so the
    caller can render it as a card and as a sendable email without composing
    the text twice.
    """
    name = investor.get("investor") or investor.get("name") or "this fund"
    sig = investor.get("signals") or {}
    lead, pace = sig.get("lead_rate") or {}, sig.get("dry_powder") or {}
    warm, conflict = sig.get("warm_path") or {}, sig.get("conflict") or {}

    # A fund that backs a direct competitor is not an outreach target. Saying
    # so is the brief.
    backs = investor.get("backs") or []
    if conflict.get("label") == "🔴" or backs:
        return {
            "investor": name, "blocked": True,
            "reason": f"{name} backs {', '.join(backs) or 'a direct competitor'}.",
            "sentences": [], "evidence": [
                {"claim": f"{name} backs {b}", "detail": conflict.get("text") or "",
                 "kind": "conflict"} for b in (backs or ["a competitor"])],
            "subject": "", "body": "",
        }

    sentences, evidence = [], []

    # 1. Why them - the one number that makes this fund the right lead.
    if lead.get("value") is not None:
        # lead["text"] already reads "led 6 of 9 series a rounds (67%)", so it
        # is quoted, not re-narrated: "You led led ..." is how that goes wrong.
        txt = _quote(lead.get("text") or f"led {_pct(lead['value'])} of rounds")
        sentences.append(
            f"You {txt} — that is exactly the round {company} is putting together.")
        evidence.append({"claim": "Leads at this stage", "detail": lead.get("text"),
                         "kind": "lead_rate", "value": lead.get("value")})
    else:
        sentences.append(
            f"{company} is raising a {stage} and {name} is on the shortlist.")

    # 2. The specific hook. Priority: a warm route beats a pattern, a pattern
    #    beats a sector, a sector beats nothing.
    hook = None
    if warm.get("label") not in (None, "⚪") and warm.get("text"):
        via = re.sub(r"^via ", "", warm["text"])
        hook = (f"{via} has sat on a cap table with you, so this is one "
                f"introduction away rather than a cold approach.")
        evidence.append({"claim": "Warm route", "detail": warm.get("text"),
                         "kind": "warm_path"})
    elif syndicate and syndicate.get("members"):
        m = syndicate["members"][0]
        share = _pct(m.get("share"))
        hook = (f"When you lead, {m['name']} comes in with you — "
                f"{m['joined']} of the {syndicate.get('rounds_led')} rounds you led "
                f"({share}) — so we are approaching the two of you as one round, not two.")
        evidence.append({"claim": f"{m['name']} follows {name}",
                         "detail": f"{m['joined']} of {syndicate.get('rounds_led')} led rounds",
                         "kind": "syndicate", "value": m.get("share")})
    else:
        overlap = sector_overlap(investor.get("portfolio") or [],
                                 _sector_words(competitors or []))
        if overlap:
            names = ", ".join(o["name"] for o in overlap[:2])
            hook = (f"You already back {names} in this market, so you know the "
                    f"buyer we are selling to.")
            evidence.append({"claim": "Sector overlap",
                             "detail": "; ".join(f"{o['name']} — {o['sector']}" for o in overlap),
                             "kind": "portfolio"})
    if hook:
        sentences.append(hook)

    # 3. The ask, anchored to something checkable: are they still deploying?
    if pace.get("label") not in (None, "⚪") and pace.get("text"):
        sentences.append(
            f"You are still deploying ({_plain(pace['text'])}) — can we take 20 minutes "
            f"at {event} on {event_date}?")
        evidence.append({"claim": "Still deploying", "detail": pace.get("text"),
                         "kind": "dry_powder"})
    else:
        sentences.append(f"Can we take 20 minutes at {event} on {event_date}?")

    subject = f"{company} × {name} — {stage} at {event}"
    body = " ".join(sentences)
    return {"investor": name, "blocked": False, "reason": None,
            "sentences": sentences, "evidence": evidence,
            "subject": subject, "body": body}
