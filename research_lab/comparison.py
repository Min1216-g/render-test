from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import pandas as pd

from .config import ResearchLabConfig
from .engine import ResearchEngine, _num, _text
from .models import ResearchResult, utc_now_iso
from .storage import JsonlStore


RETURN_WINDOWS = {
    "1H": 1 / 24,
    "CLOSE": 0.33,
    "1D": 1,
    "3D": 3,
    "5D": 5,
}


@dataclass
class ComparisonRecord:
    comparison_id: str
    ticker: str
    name: str
    market: str
    category: str
    reference_timestamp: str
    reference_data_timestamp: str
    reference_price: float | None
    existing_ai_score: int | None
    existing_ai_decision: str
    existing_direction: str
    existing_strength: str
    existing_risk: str
    existing_reason: str
    research_score: int
    research_decision: str
    research_direction: str
    research_strength: str
    research_risk: str
    continuation_potential: int
    technical_analysis: dict[str, Any]
    fundamental_analysis: dict[str, Any]
    sentiment_analysis: dict[str, Any]
    bull_case: dict[str, Any]
    bear_case: dict[str, Any]
    insight_comparison: dict[str, Any]
    returns: dict[str, float | None] = field(default_factory=lambda: {key: None for key in RETURN_WINDOWS})
    correctness: dict[str, dict[str, bool | None]] = field(
        default_factory=lambda: {key: {"existing": None, "research": None} for key in RETURN_WINDOWS}
    )
    last_evaluated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ComparisonLab:
    """Paper-test comparison between the existing scanner output and Research AI."""

    def __init__(self, config: ResearchLabConfig):
        self.config = config
        self.engine = ResearchEngine(config)
        self.store = JsonlStore(config.history_file.with_name("comparison_history.jsonl"))

    def start(self, limit: int = 40, *, save: bool = True) -> list[ComparisonRecord]:
        df = self.engine.load_market_data()
        selected = self._select_sample(df, limit)
        reference_timestamp = utc_now_iso()
        comparison_id = f"cmp-{reference_timestamp}"
        records: list[ComparisonRecord] = []
        for category, row in selected:
            research = self.engine._build_result(row)
            records.append(self._build_record(comparison_id, category, row, research, reference_timestamp))
        if save:
            for record in records:
                self.store.append(record.to_dict())
        return records

    def update_returns(self) -> int:
        df = self.engine.load_market_data()
        price_by_ticker = {
            str(row.get("ticker", "")).upper(): _num(row.get("price"))
            for _, row in df.iterrows()
        }
        now = datetime.now(timezone.utc)
        changed = 0
        records = self.store.read_all()
        for record in records:
            reference_price = _num(record.get("reference_price"))
            latest = price_by_ticker.get(str(record.get("ticker", "")).upper())
            if not reference_price or not latest:
                continue
            try:
                reference_time = datetime.fromisoformat(str(record.get("reference_timestamp")).replace("Z", "+00:00"))
            except ValueError:
                continue
            age_days = max(0.0, (now - reference_time).total_seconds() / 86400)
            returns = record.setdefault("returns", {key: None for key in RETURN_WINDOWS})
            correctness = record.setdefault(
                "correctness",
                {key: {"existing": None, "research": None} for key in RETURN_WINDOWS},
            )
            for label, required_days in RETURN_WINDOWS.items():
                if age_days < required_days or returns.get(label) is not None:
                    continue
                return_pct = round((latest - reference_price) / reference_price * 100, 2)
                returns[label] = return_pct
                correctness[label] = {
                    "existing": self._direction_correct(record.get("existing_direction"), return_pct),
                    "research": self._direction_correct(record.get("research_direction"), return_pct),
                }
                changed += 1
            if changed:
                record["last_evaluated_at"] = utc_now_iso()
        if changed:
            self.store.replace_all(records)
        return changed

    def history(self, limit: int = 20) -> list[dict]:
        return self.store.read_all()[-limit:]

    def report(self) -> dict[str, Any]:
        records = self.store.read_all()
        completed = [record for record in records if (record.get("returns") or {}).get("5D") is not None]
        partial = [record for record in records if any(value is not None for value in (record.get("returns") or {}).values())]
        basis = completed or partial
        if not basis:
            return {
                "status": "DATA_UNAVAILABLE",
                "total_samples": len(records),
                "completed_5d": len(completed),
                "message": "아직 평가 가능한 이후 수익률이 충분하지 않습니다.",
            }
        return {
            "status": "OK",
            "total_samples": len(records),
            "evaluated_samples": len(basis),
            "completed_5d": len(completed),
            "metrics": self._metrics(basis),
            "category_metrics": self._category_metrics(basis),
            "top_differences": self._top_differences(basis),
        }

    def _build_record(
        self,
        comparison_id: str,
        category: str,
        row: pd.Series,
        research: ResearchResult,
        reference_timestamp: str,
    ) -> ComparisonRecord:
        existing_score = research.existing_ai_score
        existing_decision = research.existing_ai_decision
        existing_direction = self._direction_from_decision(existing_decision, _num(row.get("change_pct"), 0) or 0)
        research_direction = self._direction_from_decision(research.research_decision, _num(row.get("change_pct"), 0) or 0)
        return ComparisonRecord(
            comparison_id=comparison_id,
            ticker=research.ticker,
            name=research.name,
            market=research.market,
            category=category,
            reference_timestamp=reference_timestamp,
            reference_data_timestamp=research.data_timestamp,
            reference_price=research.current_price,
            existing_ai_score=existing_score,
            existing_ai_decision=existing_decision,
            existing_direction=existing_direction,
            existing_strength=self._strength(existing_score),
            existing_risk=self._existing_risk(row),
            existing_reason=_text(row.get("ai_reason"), _text(row.get("action_reason"), "DATA_UNAVAILABLE")),
            research_score=research.research_score,
            research_decision=research.research_decision,
            research_direction=research_direction,
            research_strength=self._strength(research.research_score),
            research_risk=research.risk_level,
            continuation_potential=research.continuation_potential,
            technical_analysis=research.reasoning.get("technical", {}),
            fundamental_analysis=research.reasoning.get("fundamental", {}),
            sentiment_analysis=research.reasoning.get("sentiment", {}),
            bull_case=research.reasoning.get("bull_case", {}),
            bear_case=research.reasoning.get("bear_case", {}),
            insight_comparison={
                "alignment": research.reasoning.get("comparison", {}).get("alignment"),
                "score_difference": research.reasoning.get("comparison", {}).get("difference"),
                "test_focus": "already_risen_continuation" if research.already_risen else category,
                "lookahead_guard": "same_snapshot_reference_only",
            },
        )

    def _select_sample(self, df: pd.DataFrame, limit: int) -> list[tuple[str, pd.Series]]:
        buckets: list[tuple[str, pd.DataFrame]] = []
        change = df.get("change_pct", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
        volume = df.get("volume_ratio", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
        news = df.get("news_one_line", pd.Series([""] * len(df))).astype(str)
        rsi = df.get("rsi", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
        buckets.append(("gainer", df.assign(_rank=change).sort_values("_rank", ascending=False).head(10)))
        buckets.append(("decliner", df.assign(_rank=change).sort_values("_rank", ascending=True).head(10)))
        buckets.append(("volume_spike", df.assign(_rank=volume).sort_values("_rank", ascending=False).head(10)))
        buckets.append(("news", df[news.ne("") & ~news.str.contains("뉴스 없음|NO_RECENT_NEWS", na=False)].head(10)))
        buckets.append(("already_risen", df[(change >= 5) | (rsi >= 70)].head(10)))
        buckets.append(("general", df.head(10)))
        seen: set[str] = set()
        selected: list[tuple[str, pd.Series]] = []
        per_bucket = max(2, math.ceil(limit / max(1, len(buckets))))
        for category, bucket in buckets:
            for _, row in bucket.head(per_bucket).iterrows():
                ticker = str(row.get("ticker", "")).upper()
                if not ticker or ticker in seen:
                    continue
                seen.add(ticker)
                selected.append((category, row.drop(labels=["_rank"], errors="ignore")))
                if len(selected) >= limit:
                    return selected
        if len(selected) < limit:
            for _, row in df.iterrows():
                ticker = str(row.get("ticker", "")).upper()
                if ticker and ticker not in seen:
                    seen.add(ticker)
                    selected.append(("fill", row))
                    if len(selected) >= limit:
                        break
        return selected

    def _direction_from_decision(self, decision: str, current_change: float) -> str:
        if decision == "BUY CANDIDATE":
            return "UP"
        if decision == "AVOID":
            return "DOWN"
        if decision == "WAIT":
            return "SIDEWAYS" if abs(current_change) < 2 else "DOWN"
        return "UP" if current_change >= 0 else "SIDEWAYS"

    def _direction_correct(self, direction: str | None, return_pct: float) -> bool | None:
        if direction == "UP":
            return return_pct > 0
        if direction == "DOWN":
            return return_pct < 0
        if direction == "SIDEWAYS":
            return abs(return_pct) <= 1
        return None

    def _strength(self, score: int | None) -> str:
        if score is None:
            return "DATA_UNAVAILABLE"
        if score >= 78:
            return "강한 상승"
        if score >= 62:
            return "보통 상승"
        if score >= 45:
            return "약한 상승"
        return "하락/관망"

    def _existing_risk(self, row: pd.Series) -> str:
        risk = _num(row.get("risk"), 0) or 0
        if risk >= 20:
            return "HIGH"
        if risk >= 10:
            return "MEDIUM"
        return "LOW"

    def _metrics(self, records: list[dict]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for window in RETURN_WINDOWS:
            window_records = [r for r in records if (r.get("returns") or {}).get(window) is not None]
            if not window_records:
                continue
            returns = [(r.get("returns") or {}).get(window, 0) for r in window_records]
            existing = [(r.get("correctness") or {}).get(window, {}).get("existing") for r in window_records]
            research = [(r.get("correctness") or {}).get(window, {}).get("research") for r in window_records]
            existing_known = [v for v in existing if v is not None]
            research_known = [v for v in research if v is not None]
            result[window] = {
                "samples": len(window_records),
                "average_return": round(sum(returns) / len(returns), 2),
                "existing_accuracy": round(sum(existing_known) / len(existing_known) * 100, 1) if existing_known else None,
                "research_accuracy": round(sum(research_known) / len(research_known) * 100, 1) if research_known else None,
            }
        return result

    def _category_metrics(self, records: list[dict]) -> dict[str, Any]:
        grouped: dict[str, list[dict]] = {}
        for record in records:
            grouped.setdefault(str(record.get("category", "unknown")), []).append(record)
        return {category: self._metrics(items) for category, items in grouped.items()}

    def _top_differences(self, records: list[dict]) -> list[dict[str, Any]]:
        ranked = sorted(
            records,
            key=lambda record: abs((record.get("research_score") or 0) - (record.get("existing_ai_score") or 0)),
            reverse=True,
        )
        return [
            {
                "ticker": record.get("ticker"),
                "existing_score": record.get("existing_ai_score"),
                "research_score": record.get("research_score"),
                "existing_decision": record.get("existing_ai_decision"),
                "research_decision": record.get("research_decision"),
                "category": record.get("category"),
            }
            for record in ranked[:10]
        ]


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)

