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


def assess(name: str, groups: list[dict], gh: dict | None = None) -> FounderSignal:
    """groups: the relationship groups from the entity endpoint."""
    c = _counts(groups)
    edges = sum(c.values())
    gh_val = (gh or {}).get("value")

    if edges < MIN_EDGES and gh_val is None:
        return FounderSignal(name, None, "Low",
                             [f"Cala holds {edges} connection(s) for this person — "
                              "too thin to read. Unknown is not zero."],
                             [], edges)

    total = 0.0
    comps = []
    for rel, (w, sat) in WEIGHTS.items():
        n = c.get(rel, 0)
        if not n or w == 0:
            if n:
                comps.append({"rel": rel, "label": LABEL.get(rel, rel.title()),
                              "n": n, "contribution": 0.0, "counted": False})
            continue
        part = min(1.0, n / sat)
        total += w * part
        comps.append({"rel": rel, "label": LABEL.get(rel, rel.title()), "n": n,
                      "contribution": round(100 * w * part, 1), "counted": True})

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
    if c.get("FEATURED_IN"):
        reasons.append(f"{c['FEATURED_IN']} press mention(s) — noted, not scored")

    # Confidence is about how much we could see, not how high the score is.
    conf = "High" if edges >= 6 and gh_val is not None else \
           "Medium" if edges >= 4 or gh_val is not None else "Low"
    return FounderSignal(name, round(100 * min(1.0, total), 1), conf,
                         reasons, comps, edges)
