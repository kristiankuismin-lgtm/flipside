"""Is the round you said you are raising the round you are raising?

A founder types "Series B" and the screen obediently ranks Series B funds.
If their last round was a seed eighteen months ago, that list is wrong in a
way that costs them the week: Series B funds will not write the cheque, and
the Series A funds who would have are not on it.

Nothing clever here. We hold the rounds; the stage order is known; the
comparison is arithmetic. What matters is what it is allowed to say:

  - With no funding history for them we cannot check, and we say that
    rather than letting silence read as approval.
  - A stage we do not recognise is not a disagreement.
  - The check is advice, never a correction. A founder raising a Series A
    off a seed that was really a large pre-seed knows something the round
    records do not, and the screen still runs on what they asked for.
"""
from __future__ import annotations

from datetime import date

from . import norm

ORDER = ["pre-seed", "seed", "series a", "series b", "series c",
         "series d", "series e", "growth"]
INDEX = {s: i for i, s in enumerate(ORDER)}

# A round this old stops being "your last round" and starts being history.
STALE_MONTHS = 30


def _months(d, today: date) -> int | None:
    if not d:
        return None
    t = str(d)[:10]
    try:
        p = date.fromisoformat(t)
    except ValueError:
        try:
            p = date(int(t[:4]), 1, 1)
        except (TypeError, ValueError):
            return None
    if p > today:
        return None
    return (today.year - p.year) * 12 + (today.month - p.month)


def last_round(rounds) -> dict | None:
    """The most recent dated round, or None when none of them carry a date."""
    dated = [r for r in (rounds or []) if r.get("date")]
    if not dated:
        return None
    return max(dated, key=lambda r: str(r.get("date")))


def check(rounds, claimed: str, *, today: date | None = None) -> dict:
    """{verdict, severity, says, last} - never raises, never corrects."""
    today = today or date.today()
    want = norm.stage(claimed or "")
    last = last_round(rounds)

    if not rounds:
        return {"verdict": "no history", "severity": "unknown", "last": None,
                "says": "We hold no funding history for you, so there is "
                        "nothing to check the stage against."}
    if last is None:
        return {"verdict": "undated", "severity": "unknown", "last": None,
                "says": f"We hold {len(rounds)} round"
                        f"{'' if len(rounds) == 1 else 's'} for you and none "
                        f"of them carry a date, so the stage cannot be placed "
                        f"in sequence."}

    prev = norm.stage(last.get("stage") or "")
    age = _months(last.get("date"), today)
    when = (f"{last.get('stage')} in {str(last.get('date'))[:7]}"
            + (f", {age} months ago" if age is not None else ""))

    if want not in INDEX or prev not in INDEX:
        return {"verdict": "unknown stage", "severity": "unknown", "last": when,
                "says": f"Your last round on record is {when}. We cannot place "
                        f"{'that' if prev not in INDEX else claimed} in the "
                        f"usual sequence, so there is nothing to compare."}

    gap = INDEX[want] - INDEX[prev]
    if gap == 1:
        return {"verdict": "consistent", "severity": "ok", "last": when,
                "says": f"Your last round on record is {when}, so {claimed} "
                        f"is the next one."}
    if gap == 0:
        return {"verdict": "same stage", "severity": "note", "last": when,
                "says": f"Your last round on record is {when} — the same "
                        f"stage you are raising now. That is a bridge or a "
                        f"second tranche, and the funds who lead one are not "
                        f"always the funds who lead a first."}
    if gap > 1:
        skipped = ORDER[INDEX[prev] + 1:INDEX[want]]
        return {"verdict": "ahead", "severity": "warn", "last": when,
                "says": f"Your last round on record is {when}, so {claimed} "
                        f"skips {', '.join(skipped)}. Funds that only write "
                        f"{claimed} cheques will not start with yours, and "
                        f"the {skipped[0]} funds that would are not on this "
                        f"list."}
    return {"verdict": "behind", "severity": "note", "last": when,
            "says": f"Your last round on record is {when}, which is later "
                    f"than the {claimed} you asked for. If that is a "
                    f"correction the screen should be re-run; if the record "
                    f"is wrong, it is the record."}


def stale(rounds, *, today: date | None = None) -> dict | None:
    """A last round old enough that the stage question has moved on."""
    last = last_round(rounds)
    if not last:
        return None
    age = _months(last.get("date"), today or date.today())
    if age is None or age < STALE_MONTHS:
        return None
    return {"months": age, "stage": last.get("stage"),
            "says": f"Your last round on record is {age} months old. Either "
                    f"you have raised since and we do not hold it, or this "
                    f"raise is further from the last one than the usual gap."}
