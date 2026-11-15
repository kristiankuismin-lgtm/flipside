"""Which law touches the market you are raising into.

The largest unused thing in the graph. 3,777 AFFECTS_INDUSTRY edges run from
1,528 Law entities into 40 industries, and nothing in this product had ever
read one - every Law we held was a bare id, because the walker had never
been asked to fetch one.

Fetched, they are good: a name, a sentence of description, and the
industries the law applies to. "Bank Secrecy Act - a United States law
enacted in 1970 that governs anti-money-laundering compliance" against
FINANCIAL_INSURANCE, FINTECH and BANKING. "Article 45 GDPR" against FINTECH
and SOFTWARE_AND_SERVICES.

Why it belongs in this product. Every other signal here is about people and
money: who leads, who follows, who is about to start something. The
regulatory surface of a market is the question a partner asks in the second
meeting and no investor database answers from a graph - and for a founder
it is the slide they are asked for and usually guess at.

The join is deliberately one step, not two. Thesis words match industry
names; industries carry their laws. Going thesis -> company -> industry
would let one badly tagged company drag in a whole body of law, and the
chain would be longer than the claim.
"""
from __future__ import annotations

import re

from . import cache_index

# Industry labels are SCREAMING_SNAKE in the graph. A thesis is a sentence.
_SPLIT = re.compile(r"[^a-z0-9]+")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "into", "are",
         "you", "your", "our", "software", "platform", "company", "startup",
         "based", "tools", "tool", "app", "apps", "new", "using", "built"}


def _words(text: str) -> list[str]:
    return [w for w in _SPLIT.split((text or "").lower())
            if len(w) > 2 and w not in _STOP]


# Industry labels are the graph's vocabulary, not a founder's. "clinical
# software for hospitals" matched nothing at all until these existed, which
# is the usual shape of the problem: the words a market is described in and
# the words a taxonomy files it under rarely overlap.
_SYNONYM = {
    "HEALTHCARE_PROVIDERS": "clinic clinical clinician clinicians hospital "
                            "patient doctor physician care health medical "
                            "nurse scribe ehr emr",
    "PHARMACEUTICALS": "drug drugs pharma pharmaceutical therapeutics trial trials",
    "MEDICAL_DEVICES": "device devices diagnostic diagnostics imaging implant",
    "BIOTECHNOLOGY": "bio biotech genomics protein molecular lab",
    "HEALTH_INSURANCE": "insurer payer reimbursement claims",
    "SOFTWARE_AND_SERVICES": "ai agent agents llm saas developer developers api "
                             "infrastructure data analytics automation cloud model models",
    "INTERNET_AND_WEB_SERVICES": "web marketplace consumer social search browser",
    "FINTECH": "payment payments lending credit banking wallet neobank "
               "invoicing treasury compliance kyc",
    "BANKING": "bank banks deposit mortgage",
    "ASSET_MANAGEMENT": "fund funds portfolio wealth",
    "RENEWABLE_ENERGY": "climate carbon solar wind battery energy emission "
                        "emissions decarbonisation decarbonization grid",
    "TRANSPORTATION_AND_LOGISTICS": "logistics freight shipping fleet mobility "
                                    "delivery supply",
    "MANUFACTURING_AUTOMOTIVE": "factory robotics robot automotive vehicle "
                                "industrial manufacturing",
    "AEROSPACE_AND_DEFENSE": "space satellite defence defense drone aerospace",
    "EDUCATION": "learning student students school teaching edtech",
    "REAL_ESTATE": "property housing construction tenant rent proptech",
    "RETAIL": "commerce ecommerce shopper shop store merchandising",
    "FOOD_AND_BEVERAGE": "food beverage grocery agriculture farming agri",
    "LEGAL": "legal law contract contracts compliance regtech",
    "TELECOMMUNICATIONS": "telecom network connectivity spectrum",
    "ADVERTISING_AND_MARKETING": "advertising marketing adtech brand campaign",
    "HOSPITALITY_AND_TOURISM": "travel hotel booking tourism restaurant",
    "VENTURE_CAPITAL": "venture investor fund investing",
}


def _label(industry: str) -> str:
    return (industry or "").replace("_", " ").strip().lower()


def industries(index: dict | None = None) -> dict[str, dict]:
    """industry name -> {laws: [...]} from the edges we already hold."""
    index = index if index is not None else cache_index.build()
    out: dict[str, dict] = {}
    for e in index.values():
        if e.get("entity_type") != "Industry":
            continue
        name = (e.get("name") or "").strip()
        if not name:
            continue
        rel = e.get("relationships") or {}
        laws = []
        for d in ("incoming", "outgoing"):
            for x in ((rel.get(d) or {}).get("AFFECTS_INDUSTRY") or []):
                if isinstance(x, dict) and x.get("id"):
                    laws.append(x["id"])
        out[name] = {"id": e.get("id"), "law_ids": laws}
    return out


def _law(index: dict, law_id: str) -> dict | None:
    e = index.get(law_id)
    if not e or e.get("entity_type") != "Law":
        return None
    name = (e.get("name") or "").strip()
    if not name:
        return None            # a stub we have not fetched yet
    p = e.get("properties") or {}
    d = p.get("description")
    return {"id": law_id, "name": name,
            "what": (d.get("value") if isinstance(d, dict) else d) or ""}


def for_thesis(thesis: str, *, index: dict | None = None,
               limit: int = 24) -> dict:
    """The laws attached to the industries a thesis names."""
    index = index if index is not None else cache_index.build()
    ind = industries(index)
    want = _words(thesis)

    matched = []
    for name, v in ind.items():
        if not want or not v["law_ids"]:
            continue
        lab = _label(name)
        toks = set(_SPLIT.split(lab)) | set(_SYNONYM.get(name, "").split())
        # Stems, because a thesis says "clinicians" and the synonym list
        # says "clinical". Matching whole words only lost that entirely.
        stems = {t.rstrip("s") for t in toks}
        if any(w in toks or w.rstrip("s") in stems for w in want):
            matched.append((name, v))

    seen, laws = {}, []
    for name, v in matched:
        for lid in v["law_ids"]:
            if lid in seen:
                seen[lid]["also"].append(name)
                continue
            row = _law(index, lid)
            if row:
                row["industry"] = name
                row["also"] = []
                seen[lid] = row
                laws.append(row)

    # There is no importance score on a Law, so ordering has to come from
    # something real: a law whose name carries one of the thesis words, then
    # one that reaches more than one of the matched industries, then the
    # rest. Alphabetical put "2003 Dividend Tax Cut" at the top of a search
    # for AI agents, which is true and useless.
    # The only honest ordering available. A Law carries no importance
    # score, but it does carry how many industries it reaches, and a law
    # that touches one is specific to that one while a law that touches
    # twenty is the weather. The AI Act applies to almost everything here;
    # 5AMLD does not, and for a fintech founder 5AMLD is the finding.
    reach = {}
    for v in ind.values():
        for lid in v["law_ids"]:
            reach[lid] = reach.get(lid, 0) + 1
    for r in laws:
        r["industries_touched"] = reach.get(r["id"], 1)

    def rank(r):
        nm = r["name"].lower()
        return (0 if any(w in nm for w in want) else 1,
                r["industries_touched"], nm)
    laws.sort(key=rank)

    # Stubs are the honest denominator: the edge exists, the law has not
    # been fetched, and a panel that silently showed four of ninety would be
    # reporting our harvest rather than the regulation.
    held = sum(len(v["law_ids"]) for _, v in matched)
    return {
        "thesis": (thesis or "").strip(),
        "industries": [n for n, _ in matched],
        "laws": laws[:limit],
        "named": len(laws),
        "edges": held,
        "unfetched": held - len(laws),
        "all_industries": sorted(ind),
    }


def coverage(index: dict | None = None) -> dict:
    index = index if index is not None else cache_index.build()
    laws = [e for e in index.values() if e.get("entity_type") == "Law"]
    named = sum(1 for e in laws if (e.get("name") or "").strip())
    return {"law_entities": len(laws), "named": named,
            "industries": len(industries(index))}
