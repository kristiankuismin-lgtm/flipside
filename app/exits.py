"""Exits: the outcome the investor side never measured.

Insider conviction asks whether money comes back into a company. It never
asked whether money ever comes out. For an investor that is the only outcome
that matters, and Cala carries it:

    company -> PARTICIPATES_IN_CORPORATE_EVENT -> CorporateEvent(MNA_COMPLETED)
    event   -> participants with role TARGET / ACQUIRER

Wolt's reads: "DoorDash acquired Wolt by issuing 46,224,932 Class A shares on
May 31, 2022", 2022-05-31, target Wolt, acquirer DoorDash.

A fund's exit rate is deliberately reported with its denominator. "3 exits"
means nothing without "out of how many, and over what period" - and a young
fund with no exits yet is not the same as an old one with none.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from . import cala_client as cala, graph

EVENT_REL = "PARTICIPATES_IN_CORPORATE_EVENT"
EXIT_TYPES = ("MNA_COMPLETED", "IPO", "ACQUISITION", "MERGER")
EVENT_PROPS = ["name", "event_type", "event_date", "description"]


@dataclass
class Exit:
    company: str
    acquirer: str | None
    date: date | None
    event_type: str
    description: str = ""
    source: str | None = None
    event_id: str | None = None


@dataclass
class ExitRecord:
    exits: list[Exit] = field(default_factory=list)
    checked: int = 0
    unknown: int = 0

    @property
    def rate(self) -> float | None:
        """Exits over companies we could actually check. None when we checked none."""
        return (len(self.exits) / self.checked) if self.checked else None


def _is_exit(name: str, etype: str) -> bool:
    blob = f"{name} {etype}".upper()
    return any(t in blob for t in EXIT_TYPES)


def company_exits(entity_id: str, company: str = "", **kw) -> list[Exit]:
    """Completed exits for one company. Empty list is a real answer."""
    e = cala.get_entity(entity_id, properties=["name"], outgoing=[EVENT_REL],
                        limit=25, **kw) or {}
    out = []
    for ev in graph.rels(e, "outgoing", EVENT_REL):
        etype = str(ev.get("entity_type") or "")
        if "corporateevent" not in etype.lower().replace(" ", ""):
            continue
        if not _is_exit(str(ev.get("name") or ""), etype):
            continue
        # Only the target's exit is this company's exit. An acquirer taking
        # someone over is not an exit for the acquirer.
        role = str((ev.get("properties") or {}).get("role") or "").upper()
        if role and role != "TARGET":
            continue
        out.append(exit_detail(ev["id"], company or ev.get("name") or "", **kw))
    return [x for x in out if x]


def exit_detail(event_id: str, fallback_company: str = "", **kw) -> Exit | None:
    ev = cala.get_entity(event_id, properties=EVENT_PROPS,
                         incoming=[EVENT_REL], limit=25, **kw) or {}
    etype, _ = graph.prop(ev, "event_type")
    when, src = graph.prop(ev, "event_date")
    desc, dsrc = graph.prop(ev, "description")

    target = acquirer = None
    for p in graph.rels(ev, "incoming", EVENT_REL):
        role = str((p.get("properties") or {}).get("role") or "").upper()
        if role == "TARGET":
            target = p.get("name")
        elif role == "ACQUIRER":
            acquirer = p.get("name")

    best = graph.best_source(src or dsrc)
    return Exit(company=target or fallback_company, acquirer=acquirer,
                date=graph._as_date(when), event_type=str(etype or "exit"),
                description=str(desc or "")[:280],
                source=(best or {}).get("document"), event_id=event_id)


def summarise(records: list[tuple[str, list[Exit]]], unknown: int = 0) -> ExitRecord:
    """Fold per-company results into a fund-level record, denominator intact."""
    r = ExitRecord(checked=len(records), unknown=unknown)
    for _, xs in records:
        r.exits.extend(xs)
    r.exits.sort(key=lambda x: x.date or date.min, reverse=True)
    return r
