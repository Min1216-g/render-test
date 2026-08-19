from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .comparison import ComparisonLab, RETURN_WINDOWS
from .config import ResearchLabConfig
from .engine import _num
from .models import utc_now_iso
from .storage import JsonlStore


MARKET_CONFIG = {
    "KOREA": {
        "labels": {"국장", "한국", "KOREA"},
        "timezone": "Asia/Seoul",
        "close": time(15, 30),
        "report_delay_minutes": 20,
        "emoji": "🇰🇷",
        "title": "KOREA",
    },
    "US": {
        "labels": {"미장", "US", "USA", "미국"},
        "timezone": "America/New_York",
        "close": time(16, 0),
        "report_delay_minutes": 20,
        "emoji": "🇺🇸",
        "title": "US",
    },
}


@dataclass
class DailyStockResult:
    ticker: str
    name: str
    market: str
    category: str
    reference_price: float | None
    close_price: float | None
    intraday_high_return: float | None
    intraday_low_return: float | None
    close_return: float | None
    existing_direction: str
    research_direction: str
    existing_correct: bool | None
    research_correct: bool | None
    existing_score: float | None
    research_score: float | None
    existing_daily_score: float | None
    research_daily_score: float | None
    existing_decision: str
    research_decision: str
    existing_risk: str
    research_risk: str
    existing_reason: str
    research_reason: str
    winner: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DailyComparisonResult:
    result_id: str
    date: str
    market: str
    generated_at: str
    reference_count: int
    total_tested: int
    existing_correct: int
    research_correct: int
    existing_accuracy: float | None
    research_accuracy: float | None
    existing_average_return: float | None
    research_average_return: float | None
    existing_daily_score: float | None
    research_daily_score: float | None
    both_correct: int
    existing_only: int
    research_only: int
    both_wrong: int
    daily_winner: str
    score_difference: float | None
    conflict_cases: list[dict[str, Any]] = field(default_factory=list)
    both_correct_cases: list[dict[str, Any]] = field(default_factory=list)
    both_wrong_cases: list[dict[str, Any]] = field(default_factory=list)
    best_research_call: dict[str, Any] | None = None
    worst_research_call: dict[str, Any] | None = None
    stock_results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DailyComparisonLab:
    def __init__(self, config: ResearchLabConfig):
        self.config = config
        self.comparison = ComparisonLab(config)
        self.daily_store = JsonlStore(config.history_file.with_name("daily_comparison_results.jsonl"))

    def due_markets(self, now: datetime | None = None) -> list[tuple[str, date]]:
        now = now or datetime.now(timezone.utc)
        due: list[tuple[str, date]] = []
        for market_key, cfg in MARKET_CONFIG.items():
            tz = ZoneInfo(str(cfg["timezone"]))
            local_now = now.astimezone(tz)
            close_dt = datetime.combine(local_now.date(), cfg["close"], tzinfo=tz) + timedelta(
                minutes=int(cfg["report_delay_minutes"])
            )
            if local_now >= close_dt:
                due.append((market_key, local_now.date()))
        return due

    def run_due(self, *, send_telegram: bool = False) -> list[DailyComparisonResult]:
        results = []
        for market_key, market_date in self.due_markets():
            result = self.calculate(market_key, market_date) or self._load_result(self._result_id(market_key, market_date))
            if result:
                results.append(result)
                if send_telegram:
                    self._send_once(result)
        for _, market_date in self.due_markets():
            global_result = self.calculate_global(market_date)
            if global_result:
                results.append(global_result)
                if send_telegram:
                    self._send_once(global_result)
        return results

    def calculate(self, market_key: str, market_date: date | str, *, force: bool = False) -> DailyComparisonResult | None:
        if isinstance(market_date, str):
            market_date = date.fromisoformat(market_date)
        result_id = self._result_id(market_key, market_date)
        if not force and self._result_exists(result_id):
            return None
        records = self._records_for_market_day(market_key, market_date)
        if not records:
            return None
        price_map = self._fetch_market_day_prices(records, market_date)
        stock_results = [self._score_record(record, price_map.get(str(record.get("ticker", "")).upper())) for record in records]
        evaluated = [item for item in stock_results if item.close_return is not None]
        if not evaluated:
            return None
        existing_correct = sum(1 for item in evaluated if item.existing_correct is True)
        research_correct = sum(1 for item in evaluated if item.research_correct is True)
        both_correct = sum(1 for item in evaluated if item.existing_correct is True and item.research_correct is True)
        existing_only = sum(1 for item in evaluated if item.existing_correct is True and item.research_correct is False)
        research_only = sum(1 for item in evaluated if item.existing_correct is False and item.research_correct is True)
        both_wrong = sum(1 for item in evaluated if item.existing_correct is False and item.research_correct is False)
        existing_scores = [item.existing_daily_score for item in evaluated if item.existing_daily_score is not None]
        research_scores = [item.research_daily_score for item in evaluated if item.research_daily_score is not None]
        existing_daily_score = self._avg(existing_scores)
        research_daily_score = self._avg(research_scores)
        winner = self._winner(existing_daily_score, research_daily_score)
        result = DailyComparisonResult(
            result_id=result_id,
            date=market_date.isoformat(),
            market=market_key,
            generated_at=utc_now_iso(),
            reference_count=len(records),
            total_tested=len(evaluated),
            existing_correct=existing_correct,
            research_correct=research_correct,
            existing_accuracy=self._pct(existing_correct, len(evaluated)),
            research_accuracy=self._pct(research_correct, len(evaluated)),
            existing_average_return=self._avg([item.close_return for item in evaluated if self._positive_call(item.existing_direction)]),
            research_average_return=self._avg([item.close_return for item in evaluated if self._positive_call(item.research_direction)]),
            existing_daily_score=existing_daily_score,
            research_daily_score=research_daily_score,
            both_correct=both_correct,
            existing_only=existing_only,
            research_only=research_only,
            both_wrong=both_wrong,
            daily_winner=winner,
            score_difference=None if existing_daily_score is None or research_daily_score is None else round(research_daily_score - existing_daily_score, 1),
            conflict_cases=[item.to_dict() for item in evaluated if item.existing_direction != item.research_direction],
            both_correct_cases=[item.to_dict() for item in evaluated if item.existing_correct is True and item.research_correct is True],
            both_wrong_cases=[item.to_dict() for item in evaluated if item.existing_correct is False and item.research_correct is False],
            best_research_call=self._best_research(evaluated),
            worst_research_call=self._worst_research(evaluated),
            stock_results=[item.to_dict() for item in stock_results],
        )
        self.daily_store.append(result.to_dict())
        self._mark_records_close_returns(result)
        return result

    def calculate_global(self, market_date: date | str, *, force: bool = False) -> DailyComparisonResult | None:
        if isinstance(market_date, str):
            market_date = date.fromisoformat(market_date)
        result_id = f"GLOBAL_DAILY_RESULT_{market_date.isoformat()}"
        if not force and self._result_exists(result_id):
            return None
        market_results = [
            record
            for record in self.daily_store.read_all()
            if record.get("date") == market_date.isoformat() and record.get("market") in {"KOREA", "US"}
        ]
        if len({record.get("market") for record in market_results}) < 2:
            return None
        stock_results = []
        for record in market_results:
            stock_results.extend(record.get("stock_results") or [])
        evaluated = [item for item in stock_results if item.get("close_return") is not None]
        if not evaluated:
            return None
        existing_scores = [_num(item.get("existing_daily_score")) for item in evaluated if item.get("existing_daily_score") is not None]
        research_scores = [_num(item.get("research_daily_score")) for item in evaluated if item.get("research_daily_score") is not None]
        existing_daily_score = self._avg(existing_scores)
        research_daily_score = self._avg(research_scores)
        result = DailyComparisonResult(
            result_id=result_id,
            date=market_date.isoformat(),
            market="GLOBAL",
            generated_at=utc_now_iso(),
            reference_count=sum(int(record.get("reference_count") or 0) for record in market_results),
            total_tested=len(evaluated),
            existing_correct=sum(1 for item in evaluated if item.get("existing_correct") is True),
            research_correct=sum(1 for item in evaluated if item.get("research_correct") is True),
            existing_accuracy=self._pct(sum(1 for item in evaluated if item.get("existing_correct") is True), len(evaluated)),
            research_accuracy=self._pct(sum(1 for item in evaluated if item.get("research_correct") is True), len(evaluated)),
            existing_average_return=self._avg([_num(item.get("close_return")) for item in evaluated if self._positive_call(str(item.get("existing_direction")))]),
            research_average_return=self._avg([_num(item.get("close_return")) for item in evaluated if self._positive_call(str(item.get("research_direction")))]),
            existing_daily_score=existing_daily_score,
            research_daily_score=research_daily_score,
            both_correct=sum(1 for item in evaluated if item.get("existing_correct") is True and item.get("research_correct") is True),
            existing_only=sum(1 for item in evaluated if item.get("existing_correct") is True and item.get("research_correct") is False),
            research_only=sum(1 for item in evaluated if item.get("existing_correct") is False and item.get("research_correct") is True),
            both_wrong=sum(1 for item in evaluated if item.get("existing_correct") is False and item.get("research_correct") is False),
            daily_winner=self._winner(existing_daily_score, research_daily_score),
            score_difference=None if existing_daily_score is None or research_daily_score is None else round(research_daily_score - existing_daily_score, 1),
            conflict_cases=[item for item in evaluated if item.get("existing_direction") != item.get("research_direction")],
            both_correct_cases=[item for item in evaluated if item.get("existing_correct") is True and item.get("research_correct") is True],
            both_wrong_cases=[item for item in evaluated if item.get("existing_correct") is False and item.get("research_correct") is False],
            best_research_call=max(
                [item for item in evaluated if item.get("research_direction") == "UP"],
                key=lambda item: _num(item.get("close_return"), -999) or -999,
                default=None,
            ),
            worst_research_call=min(
                [item for item in evaluated if item.get("research_direction") == "UP"],
                key=lambda item: _num(item.get("close_return"), 999) or 999,
                default=None,
            ),
            stock_results=evaluated,
        )
        self.daily_store.append(result.to_dict())
        return result

    def cumulative(self, days: int = 30) -> dict[str, Any]:
        records = self.daily_store.read_all()
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
        recent = [
            r
            for r in records
            if r.get("market") != "GLOBAL" and date.fromisoformat(str(r.get("date"))) >= cutoff
        ]
        if not recent:
            return {"status": "DATA_UNAVAILABLE", "days": days, "daily_results": 0}
        existing_scores = [r.get("existing_daily_score") for r in recent if r.get("existing_daily_score") is not None]
        research_scores = [r.get("research_daily_score") for r in recent if r.get("research_daily_score") is not None]
        wins = {"Existing AI": 0, "Research AI": 0, "Tie": 0}
        for record in recent:
            winner = str(record.get("daily_winner"))
            if winner in wins:
                wins[winner] += 1
        return {
            "status": "OK",
            "days": days,
            "daily_results": len(recent),
            "existing_daily_score": self._avg(existing_scores),
            "research_daily_score": self._avg(research_scores),
            "daily_wins": wins,
            "overall_winner": self._winner(self._avg(existing_scores), self._avg(research_scores)),
        }

    def send_telegram_report(self, result: DailyComparisonResult) -> bool:
        token = self.config.telegram_bot_token
        chat_id = self.config.allowed_chat_id
        if not token:
            return False
        import requests

        response = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": daily_result_message(result.to_dict())},
            timeout=self.config.request_timeout,
        )
        response.raise_for_status()
        return True

    def _send_once(self, result: DailyComparisonResult) -> None:
        stored = self._find_raw_result(result.result_id) or result.to_dict()
        if stored.get("telegram_sent_at"):
            return
        try:
            self.send_telegram_report(result)
            self._mark_telegram(result.result_id, sent=True)
        except Exception as exc:
            self._mark_telegram(result.result_id, sent=False, error=f"{type(exc).__name__}: {exc}")
            raise

    def _records_for_market_day(self, market_key: str, market_date: date) -> list[dict]:
        labels = MARKET_CONFIG[market_key]["labels"]
        tz = ZoneInfo(str(MARKET_CONFIG[market_key]["timezone"]))
        records = []
        for record in self.comparison.store.read_all():
            if str(record.get("market")) not in labels:
                continue
            try:
                reference_time = datetime.fromisoformat(str(record.get("reference_timestamp")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if reference_time.astimezone(tz).date() == market_date:
                records.append(record)
        primary_records = [
            record
            for record in records
            if record.get("snapshot_type") == "PRIMARY_TEST" or record.get("official_evaluation") is True
        ]
        if any(record.get("snapshot_type") or "official_evaluation" in record for record in records):
            return primary_records
        return primary_records or records

    def _fetch_market_day_prices(self, records: list[dict], market_date: date) -> dict[str, dict[str, float | None]]:
        result = {}
        for record in records:
            ticker = str(record.get("ticker", "")).upper()
            if not ticker:
                continue
            result[ticker] = self._fetch_one_day(ticker, market_date)
        return result

    def _fetch_one_day(self, ticker: str, market_date: date) -> dict[str, float | None]:
        try:
            import yfinance as yf

            data = yf.download(
                ticker,
                start=market_date.isoformat(),
                end=(market_date + timedelta(days=1)).isoformat(),
                interval="5m",
                progress=False,
                auto_adjust=False,
                threads=False,
            )
            if data.empty:
                data = yf.download(
                    ticker,
                    start=market_date.isoformat(),
                    end=(market_date + timedelta(days=1)).isoformat(),
                    interval="1d",
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
            if data.empty:
                return {"close": None, "high": None, "low": None}
            close = self._last_float(data["Close"])
            high = self._max_float(data["High"])
            low = self._min_float(data["Low"])
            return {"close": close, "high": high, "low": low}
        except Exception:
            return {"close": None, "high": None, "low": None}

    def _score_record(self, record: dict, prices: dict[str, float | None] | None) -> DailyStockResult:
        prices = prices or {}
        reference = _num(record.get("reference_price"))
        close = prices.get("close")
        high = prices.get("high")
        low = prices.get("low")
        close_return = self._return_pct(reference, close)
        high_return = self._return_pct(reference, high)
        low_return = self._return_pct(reference, low)
        existing_correct = self.comparison._direction_correct(record.get("existing_direction"), close_return) if close_return is not None else None
        research_correct = self.comparison._direction_correct(record.get("research_direction"), close_return) if close_return is not None else None
        volatility = self._intraday_range(high_return, low_return)
        existing_daily_score = self._daily_score(record, close_return, volatility, "existing")
        research_daily_score = self._daily_score(record, close_return, volatility, "research")
        winner = self._stock_winner(existing_daily_score, research_daily_score)
        return DailyStockResult(
            ticker=str(record.get("ticker")),
            name=str(record.get("name")),
            market=str(record.get("market")),
            category=str(record.get("category")),
            reference_price=reference,
            close_price=close,
            intraday_high_return=high_return,
            intraday_low_return=low_return,
            close_return=close_return,
            existing_direction=str(record.get("existing_direction")),
            research_direction=str(record.get("research_direction")),
            existing_correct=existing_correct,
            research_correct=research_correct,
            existing_score=_num(record.get("existing_ai_score")),
            research_score=_num(record.get("research_score")),
            existing_daily_score=existing_daily_score,
            research_daily_score=research_daily_score,
            existing_decision=str(record.get("existing_ai_decision")),
            research_decision=str(record.get("research_decision")),
            existing_risk=str(record.get("existing_risk")),
            research_risk=str(record.get("research_risk")),
            existing_reason=str(record.get("existing_reason")),
            research_reason=self._research_reason(record),
            winner=winner,
        )

    def _daily_score(self, record: dict, close_return: float | None, volatility: float | None, side: str) -> float | None:
        if close_return is None:
            return None
        direction = str(record.get(f"{side}_direction" if side == "research" else "existing_direction"))
        risk = str(record.get(f"{side}_risk" if side == "research" else "existing_risk"))
        strength = str(record.get(f"{side}_strength" if side == "research" else "existing_strength"))
        score_items = []
        direction_ok = self.comparison._direction_correct(direction, close_return)
        if direction_ok is not None:
            score_items.append((40.0, 40.0 if direction_ok else 0.0))
        score_items.append((25.0, self._return_score(direction, close_return)))
        if volatility is not None:
            score_items.append((15.0, self._risk_score(risk, volatility)))
        score_items.append((10.0, self._momentum_score(strength, close_return)))
        news_status = self._news_score(record, close_return, side)
        if news_status is not None:
            score_items.append((5.0, news_status))
        continuation = self._continuation_score(record, close_return, side)
        if continuation is not None:
            score_items.append((5.0, continuation))
        total_weight = sum(weight for weight, _ in score_items)
        if total_weight <= 0:
            return None
        return round(sum(score for _, score in score_items) / total_weight * 100, 1)

    def _return_score(self, direction: str, return_pct: float) -> float:
        if direction == "UP":
            return max(0.0, min(25.0, 12.5 + return_pct * 4))
        if direction == "DOWN":
            return max(0.0, min(25.0, 12.5 - return_pct * 4))
        return max(0.0, min(25.0, 25.0 - abs(return_pct) * 10))

    def _risk_score(self, risk: str, volatility: float) -> float:
        actual = "HIGH" if volatility >= 6 else "MEDIUM" if volatility >= 2.5 else "LOW"
        if risk == actual:
            return 15.0
        if {risk, actual} == {"LOW", "HIGH"}:
            return 0.0
        return 7.5

    def _momentum_score(self, strength: str, return_pct: float) -> float:
        strong = abs(return_pct) >= 3
        if "강한" in strength:
            return 10.0 if strong and return_pct > 0 else 3.0
        if "보통" in strength:
            return 10.0 if 1 <= abs(return_pct) < 4 else 5.0
        if "약한" in strength:
            return 10.0 if abs(return_pct) < 2 else 5.0
        return 8.0 if return_pct <= 0 else 4.0

    def _news_score(self, record: dict, close_return: float, side: str) -> float | None:
        if side == "existing":
            text = str(record.get("existing_reason", ""))
            if "뉴스" not in text and "호재" not in text and "악재" not in text:
                return None
        else:
            sentiment = record.get("sentiment_analysis") or {}
            if sentiment.get("status") == "NEWS_UNAVAILABLE":
                return None
            text = str(sentiment.get("direction", ""))
        positive = "호재" in text or "Bullish" in text
        negative = "악재" in text or "Bearish" in text
        if positive:
            return 5.0 if close_return > 0 else 0.0
        if negative:
            return 5.0 if close_return < 0 else 0.0
        return 2.5

    def _continuation_score(self, record: dict, close_return: float, side: str) -> float | None:
        focus = (record.get("insight_comparison") or {}).get("test_focus")
        if focus != "already_risen_continuation":
            return None
        if side == "research":
            potential = _num(record.get("continuation_potential"), 0) or 0
            expects_up = potential >= 65
        else:
            expects_up = str(record.get("existing_direction")) == "UP"
        return 5.0 if expects_up == (close_return > 0) else 0.0

    def _mark_records_close_returns(self, result: DailyComparisonResult) -> None:
        records = self.comparison.store.read_all()
        result_by_ticker = {item["ticker"]: item for item in result.stock_results}
        changed = False
        for record in records:
            if record.get("ticker") not in result_by_ticker:
                continue
            stock = result_by_ticker[str(record.get("ticker"))]
            if stock.get("close_return") is None:
                continue
            returns = record.setdefault("returns", {key: None for key in RETURN_WINDOWS})
            correctness = record.setdefault("correctness", {key: {"existing": None, "research": None} for key in RETURN_WINDOWS})
            if returns.get("CLOSE") is None:
                returns["CLOSE"] = stock.get("close_return")
                correctness["CLOSE"] = {
                    "existing": stock.get("existing_correct"),
                    "research": stock.get("research_correct"),
                }
                record["last_evaluated_at"] = result.generated_at
                changed = True
        if changed:
            self.comparison.store.replace_all(records)

    def _result_id(self, market_key: str, market_date: date) -> str:
        return f"{market_key}_DAILY_RESULT_{market_date.isoformat()}"

    def _result_exists(self, result_id: str) -> bool:
        return any(record.get("result_id") == result_id for record in self.daily_store.read_all())

    def _find_raw_result(self, result_id: str) -> dict[str, Any] | None:
        for record in self.daily_store.read_all():
            if record.get("result_id") == result_id:
                return record
        return None

    def _load_result(self, result_id: str) -> DailyComparisonResult | None:
        record = self._find_raw_result(result_id)
        if not record:
            return None
        allowed = set(DailyComparisonResult.__dataclass_fields__)
        return DailyComparisonResult(**{key: value for key, value in record.items() if key in allowed})

    def _mark_telegram(self, result_id: str, *, sent: bool, error: str | None = None) -> None:
        records = self.daily_store.read_all()
        changed = False
        for record in records:
            if record.get("result_id") != result_id:
                continue
            if sent:
                record["telegram_sent_at"] = utc_now_iso()
                record.pop("telegram_error", None)
            else:
                record["telegram_error"] = error or "TELEGRAM_SEND_FAILED"
                record["telegram_last_attempt_at"] = utc_now_iso()
            changed = True
        if changed:
            self.daily_store.replace_all(records)

    def _winner(self, existing: float | None, research: float | None) -> str:
        if existing is None and research is None:
            return "DATA_UNAVAILABLE"
        if existing is None:
            return "Research AI"
        if research is None:
            return "Existing AI"
        if abs(existing - research) < 1:
            return "Tie"
        return "Research AI" if research > existing else "Existing AI"

    def _stock_winner(self, existing: float | None, research: float | None) -> str:
        return self._winner(existing, research)

    def _positive_call(self, direction: str) -> bool:
        return direction == "UP"

    def _return_pct(self, reference: float | None, value: float | None) -> float | None:
        if not reference or value is None:
            return None
        return round((value - reference) / reference * 100, 2)

    def _intraday_range(self, high_return: float | None, low_return: float | None) -> float | None:
        if high_return is None or low_return is None:
            return None
        return abs(high_return - low_return)

    def _research_reason(self, record: dict) -> str:
        reasons = (record.get("bull_case") or {}).get("reasons") or []
        return str(reasons[0]) if reasons else "DATA_UNAVAILABLE"

    def _best_research(self, items: list[DailyStockResult]) -> dict[str, Any] | None:
        candidates = [item for item in items if item.research_direction == "UP" and item.close_return is not None]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.close_return or -999).to_dict()

    def _worst_research(self, items: list[DailyStockResult]) -> dict[str, Any] | None:
        candidates = [item for item in items if item.research_direction == "UP" and item.close_return is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda item: item.close_return or 999).to_dict()

    def _pct(self, value: int, total: int) -> float | None:
        return None if total == 0 else round(value / total * 100, 1)

    def _avg(self, values: list[float | None]) -> float | None:
        known = [value for value in values if value is not None and not math.isnan(value)]
        return None if not known else round(sum(known) / len(known), 2)

    def _last_float(self, series: Any) -> float | None:
        try:
            if hasattr(series, "columns"):
                series = series.iloc[:, 0]
            values = series.dropna()
            return None if values.empty else float(values.iloc[-1])
        except Exception:
            return None

    def _max_float(self, series: Any) -> float | None:
        try:
            if hasattr(series, "columns"):
                series = series.iloc[:, 0]
            values = series.dropna()
            return None if values.empty else float(values.max())
        except Exception:
            return None

    def _min_float(self, series: Any) -> float | None:
        try:
            if hasattr(series, "columns"):
                series = series.iloc[:, 0]
            values = series.dropna()
            return None if values.empty else float(values.min())
        except Exception:
            return None


def daily_result_message(result: dict[str, Any]) -> str:
    cfg = MARKET_CONFIG.get(str(result.get("market")), {"emoji": "🌎", "title": "GLOBAL"})
    winner = result.get("daily_winner")
    diff = result.get("score_difference")
    lines = [
        "📊 DAILY AI COMPARISON",
        "",
        f"{cfg['emoji']} {cfg['title']} MARKET",
        str(result.get("date")),
        "",
        "━━━━━━━━━━━━━━",
        "",
        f"Tested: {result.get('total_tested')} stocks",
        "",
        "Existing AI",
        f"Accuracy: {result.get('existing_accuracy')}%",
        f"Avg Return: {result.get('existing_average_return')}%",
        f"Daily Score: {result.get('existing_daily_score')}",
        "",
        "Research AI",
        f"Accuracy: {result.get('research_accuracy')}%",
        f"Avg Return: {result.get('research_average_return')}%",
        f"Daily Score: {result.get('research_daily_score')}",
        "",
        "━━━━━━━━━━━━━━",
        "",
        "🏆 WINNER",
        "",
        str(winner).upper(),
        "",
        f"Difference: {diff:+.1f} points" if isinstance(diff, (int, float)) else "Difference: N/A",
        "",
        "━━━━━━━━━━━━━━",
        "",
        f"Both Correct: {result.get('both_correct')}",
        f"Existing Only: {result.get('existing_only')}",
        f"Research Only: {result.get('research_only')}",
        f"Both Wrong: {result.get('both_wrong')}",
    ]
    best = result.get("best_research_call")
    worst = result.get("worst_research_call")
    if best:
        lines.extend(["", "🔥 BEST RESEARCH CALL", "", f"{best.get('ticker')} · {best.get('close_return')}%"])
    if worst:
        lines.extend(["", "⚠️ WORST RESEARCH CALL", "", f"{worst.get('ticker')} · {worst.get('close_return')}%"])
    lines.extend(["", "━━━━━━━━━━━━━━", "", f"{winner} performed better today." if winner not in {"Tie", "DATA_UNAVAILABLE"} else "No clear winner today."])
    return "\n".join(lines)


def cumulative_message(result: dict[str, Any]) -> str:
    if result.get("status") != "OK":
        return f"🏆 {result.get('days')} DAY PERFORMANCE\n\nDATA_UNAVAILABLE"
    wins = result.get("daily_wins") or {}
    return "\n".join(
        [
            f"🏆 {result.get('days')} DAY PERFORMANCE",
            "",
            "Existing AI:",
            f"Daily Score {result.get('existing_daily_score')}",
            "",
            "Research AI:",
            f"Daily Score {result.get('research_daily_score')}",
            "",
            "Daily Wins:",
            f"Existing AI: {wins.get('Existing AI', 0)} days",
            f"Research AI: {wins.get('Research AI', 0)} days",
            f"Tie: {wins.get('Tie', 0)} days",
            "",
            f"Overall Winner: {result.get('overall_winner')}",
        ]
    )


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
