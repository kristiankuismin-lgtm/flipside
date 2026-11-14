"""The call list: who to actually contact, in the order to contact them.

A screen tells a founder which firms are worth approaching. It does not
tell them who to write to, and a fund is not a person. This merges the two
sources we have and says which one each name came from, because they are
not equally strong:

  Cala        a Person entity with a verified LinkedIn and a role from the
              graph. Authoritative, and rare - 5 people across 7 funds.
  Their site  a name and a role quoted from the firm's own team page.
              Plentiful, and only as good as the page.

Ranked by whether the founder should call at all, not by who is most
senior: a conflicted fund has no contact worth making.
"""
from __future__ import annotations

import re

from . import norm

# Who to call first at a firm. A partner writes cheques; an analyst does not.
SENIORITY = [
    (re.compile(r"\b(?:founding|general|managing)\s+partner\b", re.I), 100),
    (re.compile(r"\bpartner\b", re.I), 90),
    (re.compile(r"\b(?:co-?founder|founder)\b", re.I), 88),
    (re.compile(r"\b(?:ceo|chief executive)\b", re.I), 85),
    (re.compile(r"\bprincipal\b", re.I), 70),
    (re.compile(r"\b(?:investment\s+)?director\b", re.I), 65),
    (re.compile(r"\bventure\s+partner\b", re.I), 60),
    (re.compile(r"\b(?:entrepreneur|data scientist)[- ]in[- ]residence\b", re.I), 45),
    (re.compile(r"\b(?:associate|analyst)\b", re.I), 35),
    (re.compile(r"\b(?:advisor|adviser)\b", re.I), 30),
]
SOURCE_RANK = {"cala": 0, "site": 1}


def seniority(role: str | None) -> int:
    for rx, score in SENIORITY:
        if rx.search(role or ""):
            return score
    return 50 if role else 20          # a named role beats none


def _reason(inv: dict, stage: str) -> str:
    """Why this firm is on the list at all, in the founder's words."""
    s = inv.get("signals") or {}
    bits = []
    lead = (s.get("lead_rate") or {}).get("text")
    if lead:
        bits.append(lead.lower())
    pace = (s.get("dry_powder") or {}).get("text")
    if pace:
        bits.append(re.sub(r"\s*\(.*", "", pace))
    warm = s.get("warm_path") or {}
    if warm.get("label") not in (None, "⚪") and warm.get("text"):
        bits.append(warm["text"])
    return " · ".join(bits) or f"on your {stage} list"


def build(investors: list[dict], people_by_fund: dict[str, list[dict]],
          *, stage: str = "", limit: int = 40) -> dict:
    """One row per person, best firm first, best contact within it first."""
    rows, skipped = [], []
    for inv in investors or []:
        name = inv.get("investor")
        sig = inv.get("signals") or {}
        if (sig.get("conflict") or {}).get("label") == "\U0001f534":
            skipped.append({"fund": name, "why": "backs a competitor",
                            "backs": inv.get("backs") or []})
            continue
        people = people_by_fund.get(norm.name(name)) or []
        if not people:
            skipped.append({"fund": name, "why": "no contact found",
                            "score": inv.get("score")})
            continue
        warm = (sig.get("warm_path") or {})
        for p in people:
            rows.append({
                "person": p.get("name"), "role": p.get("role"),
                "linkedin": p.get("linkedin"), "site": p.get("site"),
                "source": p.get("source", "site"),
                "quote": p.get("quote"),
                "fund": name, "fund_score": inv.get("score"),
                "reason": _reason(inv, stage),
                "warm": warm.get("text") if warm.get("label") not in (None, "⚪") else None,
                "seniority": seniority(p.get("role")),
            })

    rows.sort(key=lambda r: (
        -(r["fund_score"] or 0),            # the firm worth calling
        r["warm"] is None,                  # a warm route first
        SOURCE_RANK.get(r["source"], 9),    # Cala before a scraped page
        -r["seniority"],                    # a partner before an analyst
        r["person"] or "",
    ))
    return {"rows": rows[:limit], "total": len(rows),
            "funds_with_a_contact": len({r["fund"] for r in rows}),
            "skipped": skipped,
            "by_source": {s: sum(1 for r in rows if r["source"] == s)
                          for s in ("cala", "site")}}
