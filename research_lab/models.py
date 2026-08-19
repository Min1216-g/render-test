from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class AnalystResult:
    score: int | None
    direction: str
    reason: str
    status: str = "OK"


@dataclass
class ResearchResult:
    timestamp: str
    ticker: str
    market: str
    name: str
    current_price: float | None
    existing_ai_score: int | None
    existing_ai_decision: str
    research_score: int
    research_decision: str
    technical_score: int | None
    fundamental_score: int | None
    sentiment_score: int | None
    bull_score: int
    bear_score: int
    risk_level: str
    already_risen: bool
    momentum: str
    overheat_risk: str
    continuation_potential: int
    reasoning: dict[str, Any]
    data_timestamp: str
    entry_reference: float | None
    future_returns: dict[str, float | None] = field(default_factory=lambda: {"1D": None, "3D": None, "5D": None, "10D": None})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

