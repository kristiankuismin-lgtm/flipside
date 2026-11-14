"""FastAPI: POST /analyze {company, stage, amount, investors?: [..]} -> järjestetty sijoittajalista."""
from fastapi import FastAPI
from pydantic import BaseModel
from dataclasses import asdict
from . import metrics as M
from .extract import investor_rounds

app = FastAPI(title="Flipside")


class Req(BaseModel):
    company: str
    stage: str = "seed"
    amount_eur: float | None = None
    investors: list[str] | None = None   # Slush-tila: liitetyt nimet


@app.post("/analyze")
def analyze(req: Req):
    investors = req.investors or candidate_investors(req)
    out = []
    for inv in investors:
        rounds = investor_rounds(inv)
        byco = M.by_company(rounds)
        sig = {"lead_rate": M.lead_rate(inv, rounds, req.stage)}
        sig["follow_on"], sig["next_round"] = M.follow_on(inv, byco)
        sig["dry_powder"] = M.dry_powder(inv, byco)
        # conflict + warm_path: kytke embedding- ja graafimoduulit tähän
        fit = {"stage": 1.0, "sector": .7, "geo": 1.0, "check": .8}  # TODO: laske Calasta
        out.append({"investor": inv, "score": M.score(fit, sig),
                    "signals": {k: asdict(v) for k, v in sig.items()}})
    return sorted(out, key=lambda x: x["score"], reverse=True)


def candidate_investors(req: Req) -> list[str]:
    # TODO: Cala QL / search: aktiiviset sijoittajat, jotka sijoittivat founderin sektoriin ja vaiheeseen 24 kk:n aikana
    return []
