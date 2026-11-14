"""The third reading: who looks like a founder before they are one.

Flipside reads one funding graph in three directions.
  Founder side  - which investors should I pitch?
  Investor side - whose insiders came back?
  This          - which people look like they are about to start something?

Every input is already on Cala's Person entity: FOUNDED, WORKS_AT (with role
text), STUDIED_AT, IS_MEMBER_OF, SPOKE_AT, RECEIVED_AWARD, FEATURED_IN,
INVESTED_IN. GitHub is the only external source, because it is the one public
record of what someone has actually built that has an API and no terms problem.

Weighting follows what the evidence in venture actually supports rather than
what is easiest to count:

  * Prior founding dominates. Repeat founders outperform first-timers, and a
    company that did not work still counts - the experience is the signal, not
    the outcome. We cannot see outcomes here anyway, so we do not pretend to.
  * Operating roles beat credentials. Having run something is worth more than
    where someone studied.
  * Press and awards are weighted lightly. They measure visibility, which
    correlates with being already known rather than with being about to build.
  * Nothing is inferred from an absent edge. A person Cala holds thinly scores
    "unknown", never "weak".
"""
from dataclasses import dataclass, field

# relationship -> (weight, saturation point)
# Saturation: the second prior company matters far less than the first.
WEIGHTS = {
    "FOUNDED":        (0.34, 2),
    "IS_CEO_OF":      (0.16, 2),
    "WORKS_AT":       (0.14, 3),
    "INVESTED_IN":    (0.12, 4),
    "IS_MEMBER_OF":   (0.10, 3),
    "STUDIED_AT":     (0.06, 2),
    "SPOKE_AT":       (0.05, 3),
    "RECEIVED_AWARD": (0.03, 3),
    "FEATURED_IN":    (0.00, 3),   # visibility, not intent - counted, not scored
}
GITHUB_WEIGHT = 0.18

LABEL = {"FOUNDED": "founded a company before",
         "IS_CEO_OF": "has run a company",
         "WORKS_AT": "operating experience",
         "INVESTED_IN": "invests privately",
         "IS_MEMBER_OF": "sits on boards",
         "STUDIED_AT": "education on record",
         "SPOKE_AT": "speaks publicly",
         "RECEIVED_AWARD": "recognised"}

MIN_EDGES = 2          # below this we decline to score

# Role seniority from the role string Cala carries on WORKS_AT. Running
# something is a different signal from being employed somewhere.
import re
SENIOR = re.compile(r"\b(founder|co-?founder|ceo|cto|coo|cfo|chair|president|"
                    r"partner|head of|vp|vice president|director|lead)\b", re.I)

# Second-order weighting. An edge to a company that went on to raise is worth
# more than an edge to one that never did - "early at a company that became
# something" is the signal people actually mean by pedigree.
TRACTION_BONUS = {"multi": 1.0, "once": 0.55, "none": 0.15, "unknown": 0.35}


def company_traction(name: str, rounds_by_company: dict | None) -> str:
    """multi | once | none | unknown, from the funding data we already hold."""
    if not rounds_by_company:
        return "unknown"
    key = name.strip().lower()
    rs = rounds_by_company.get(key)
    if rs is None:
        return "unknown"
    n = len(rs)
    return "multi" if n >= 2 else "once" if n == 1 else "none"


@dataclass
class FounderSignal:
    name: str
    score: float | None
    confidence: str
    reasons: list[str] = field(default_factory=list)
    components: list[dict] = field(default_factory=list)
    evidence_edges: int = 0


def _counts(groups: list[dict]) -> dict[str, int]:
    return {g["rel"]: len(g.get("items") or []) for g in (groups or [])}


def _quality(items: list[dict], rounds_by_company: dict | None) -> tuple[float, list[str]]:
    """Average traction of the companies behind a set of edges, 0-1."""
    if not items:
        return 0.0, []
    vals, notes = [], []
    for it in items:
        t = company_traction(it.get("name", ""), rounds_by_company)
        vals.append(TRACTION_BONUS[t])
        if t == "multi":
            notes.append(f"{it.get('name')} raised more than once")
    return sum(vals) / len(vals), notes[:2]


def assess(name: str, groups: list[dict], gh: dict | None = None,
           rounds_by_company: dict | None = None) -> FounderSignal:
    """groups: the relationship groups from the entity endpoint.

    rounds_by_company maps a lowercased company name to its known rounds. When
    given, edges are weighted by what those companies went on to do rather than
    counted flat.
    """
    c = _counts(groups)
    by_rel = {g["rel"]: (g.get("items") or []) for g in (groups or [])}
    edges = sum(c.values())
    gh_val = (gh or {}).get("value")

    if edges < MIN_EDGES and gh_val is None:
        return FounderSignal(name, None, "Low",
                             [f"Cala holds {edges} connection(s) for this person — "
                              "too thin to read. Unknown is not zero."],
                             [], edges)

    total = 0.0
    comps = []
    quality_notes = []
    for rel, (w, sat) in WEIGHTS.items():
        n = c.get(rel, 0)
        if not n or w == 0:
            if n:
                comps.append({"rel": rel, "label": LABEL.get(rel, rel.title()),
                              "n": n, "contribution": 0.0, "counted": False})
            continue
        part = min(1.0, n / sat)

        # Second-order: what did those companies actually do?
        qmul, notes = 1.0, []
        if rel in ("FOUNDED", "IS_CEO_OF", "WORKS_AT", "INVESTED_IN") and rounds_by_company:
            q, notes = _quality(by_rel.get(rel, []), rounds_by_company)
            qmul = 0.6 + 0.8 * q          # 0.6x for nothing, up to 1.4x
            quality_notes += notes

        # Seniority: WORKS_AT carries a role string worth reading.
        smul = 1.0
        if rel == "WORKS_AT":
            roles = [str((i.get("role") or "")) for i in by_rel.get(rel, [])]
            if any(SENIOR.search(r) for r in roles):
                smul = 1.25

        contrib = w * part * qmul * smul
        total += contrib
        comps.append({"rel": rel, "label": LABEL.get(rel, rel.title()), "n": n,
                      "contribution": round(100 * contrib, 1), "counted": True,
                      "weighted": qmul != 1.0 or smul != 1.0})

    if gh_val is not None:
        total += GITHUB_WEIGHT * gh_val
        comps.append({"rel": "GITHUB", "label": "ships code publicly", "n": 1,
                      "contribution": round(100 * GITHUB_WEIGHT * gh_val, 1),
                      "counted": True})

    comps.sort(key=lambda x: -x["contribution"])
    reasons = []
    if c.get("FOUNDED"):
        reasons.append(f"has founded {c['FOUNDED']} compan{'y' if c['FOUNDED'] == 1 else 'ies'} "
                       "— the strongest signal available")
    if c.get("IS_CEO_OF"):
        reasons.append(f"has run {c['IS_CEO_OF']}")
    if c.get("WORKS_AT"):
        reasons.append(f"{c['WORKS_AT']} operating role(s) on record")
    if c.get("INVESTED_IN"):
        reasons.append(f"angel cheques into {c['INVESTED_IN']} compan"
                       f"{'y' if c['INVESTED_IN'] == 1 else 'ies'}")
    if gh_val is not None:
        reasons += (gh or {}).get("why", [])[:2]
    reasons += quality_notes
    senior_roles = [str(i.get("role") or "") for i in by_rel.get("WORKS_AT", [])]
    hit = next((r for r in senior_roles if SENIOR.search(r)), None)
    if hit:
        reasons.append(f"senior operating role: {hit}")
    if c.get("FEATURED_IN"):
        reasons.append(f"{c['FEATURED_IN']} press mention(s) — noted, not scored")

    # Confidence is about how much we could see, not how high the score is.
    conf = "High" if edges >= 6 and gh_val is not None else \
           "Medium" if edges >= 4 or gh_val is not None else "Low"
    return FounderSignal(name, round(100 * min(1.0, total), 1), conf,
                         reasons, comps, edges)
