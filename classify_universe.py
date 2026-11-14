"""Say which entries in the fund universe are funds.

664 names came out of round records, and a round record names whoever was in
the round - which includes Peter Thiel, Taavet Hinrikus, Mario Gotze, and
three strings that are not entities at all ("Undisclosed angel investors").

They were being counted as funds with no logo and no address, which made
both numbers wrong in the same direction: we looked like we had failed to
find a website for a person who does not have one.

They are not a bug in the data either. An individual angel in a round is a
real investor and a real route - the point is that a founder approaches one
differently, and a map pin for a person is a category error.

    uv run python classify_universe.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app import depth as D, pipeline as PL

OUT = Path("fund_universe.json")
NOT_AN_ENTITY = re.compile(
    r"not publicly disclosed|undisclosed|^unknown$|^n/?a$|^others?$|"
    r"angel investors$|^private investors$", re.I)


# A word that only a firm has in its name. "European Investment Bank" is a
# firm however little it looks like one.
FIRM_WORD = re.compile(
    r"\b(ventures?|capital|partners?|fund|funds|invest\w*|equity|advisors?|"
    r"associates|holdings?|group|bank|management|collective|labs?|studio|"
    r"accelerator|incubator|combinator|oy|ab|gmbh|ltd|llc|inc|plc|sa|bv|nv)\b",
    re.I)


def classify(name: str) -> str:
    """fund | person | not an entity, strongest evidence first."""
    if NOT_AN_ENTITY.search(name or ""):
        return "not an entity"
    # A firm word settles it before anything else looks at the shape.
    if FIRM_WORD.search(name or ""):
        return "fund"
    # Cala typing the name as a human is the next best evidence. An angel
    # usually has an Organization entity too - that is their investment
    # vehicle - so requiring the absence of one classified Taavet Hinrikus
    # as a fund.
    if D.entity(name, types=("Person",)):
        return "person"
    # Last, the shape rule built for the syndicate graph: a given name plus
    # a surname and no company word. It is what catches the people Cala has
    # no Person entity for.
    if not PL.looks_like_a_fund(name):
        return "person"
    return "fund"


def main() -> int:
    data = json.loads(OUT.read_text())
    counts = {"fund": 0, "person": 0, "not an entity": 0}
    for name, rec in data.items():
        kind = classify(name)
        counts[kind] += 1
        if kind == "fund":
            rec.pop("kind", None)
        else:
            rec["kind"] = kind
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False))
    print(json.dumps(counts, indent=1))
    print("\npeople now labelled:",
          [n for n, r in data.items() if r.get("kind") == "person"][:12])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
