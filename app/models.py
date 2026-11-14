from dataclasses import dataclass, field
from datetime import date
from typing import Optional


@dataclass
class Evidence:
    claim: str
    source_url: Optional[str] = None
    cala_id: Optional[str] = None


@dataclass
class Round:
    company: str
    date: date
    stage: str                       # pre-seed | seed | series a | ...
    amount_eur: Optional[float]
    investors: list[str]
    leads: list[str] = field(default_factory=list)   # natiivi tai heuristinen
    lead_is_native: bool = False
    sources: list[str] = field(default_factory=list)


@dataclass
class Signal:
    name: str
    value: Optional[float]
    label: str          # 🟢 / 🟡 / 🔴 / ⚪
    text: str           # "Liidasi 7/19 seed-kierrosta (37 %)"
    n: int
    confidence: str     # Korkea / Keski / Matala
    evidence: list[Evidence] = field(default_factory=list)
