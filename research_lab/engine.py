from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ResearchLabConfig
from .models import AnalystResult, ResearchResult, utc_now_iso
from .storage import JsonlStore


POSITIVE_WORDS = ("호재", "상향", "성장", "수주", "계약", "실적", "투자", "돌파", "확대", "beat")
NEGATIVE_WORDS = ("악재", "하향", "소송", "감소", "손실", "miss", "리콜", "규제", "부진", "위험")
SCANNER_TEXT_FIELDS = {"ai_reason", "action_reason", "risks", "sector_summary"}
STALE_NEWS_PATTERNS = (
    re.compile(r"2026-0[1-7]-"),
    re.compile(r"2026-08-0[1-9]"),
    re.compile(r"2026-08-1[0-7]"),
)
GENERIC_NEWS_MARKERS = (
    "오늘 기준 회사 관련 뉴스 없음",
    "엉뚱한 뉴스는 제외",
    "최근 7일 내 공식/신뢰 캐나다 뉴스 없음",
    "ETF 경량 모드",
    "해외 종목: 해외 주요 뉴스",
    "뉴스 확인 전",
    "뉴스 확인 실패",
)


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return default
        text = str(value).replace(",", "").strip()
        if text == "":
            return default
        return float(text)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int | None = None) -> int | None:
    number = _num(value)
    return default if number is None else int(round(number))


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    return str(value).strip()


def _clamp(value: float, low: int = 0, high: int = 100) -> int:
    return int(max(low, min(high, round(value))))


def validate_market_row(row: pd.Series) -> dict[str, Any]:
    ticker = _text(row.get("ticker")).upper()
    market = _text(row.get("market"))
    name = _text(row.get("name"), ticker)
    price = _num(row.get("price"))
    change = _num(row.get("change_pct"))
    volume_ratio = _num(row.get("volume_ratio"))
    data_timestamp = _text(row.get("mobile_intel_generated_at"), _text(row.get("data_generated_at"), _text(row.get("file_updated_at"))))
    issues = []
    if not ticker:
        issues.append("ticker_missing")
    if not market:
        issues.append("market_missing")
    if not name:
        issues.append("company_missing")
    if price is None or price <= 0:
        issues.append("reference_price_invalid")
    if change is None:
        issues.append("change_pct_missing")
    if volume_ratio is None:
        issues.append("volume_ratio_missing")
    if not data_timestamp:
        issues.append("reference_timestamp_missing")
    return {
        "status": "VALID" if not issues else "DATA_INVALID",
        "issues": issues,
        "ticker": ticker,
        "market": market,
        "company": name,
        "reference_price": price,
        "change_pct": change,
        "volume_ratio": volume_ratio,
        "sector": _text(row.get("sector")),
        "reference_timestamp": data_timestamp,
    }


def validate_news_row(row: pd.Series) -> dict[str, Any]:
    title = " ".join([_text(row.get("news")), _text(row.get("news_one_line")), _text(row.get("headlines"))]).strip()
    source = _text(row.get("news_source"), "unknown")
    if not title or "NO_RECENT_NEWS" in title or "뉴스 없음" in title:
        status = "NEWS_MISSING"
    elif any(marker in title for marker in GENERIC_NEWS_MARKERS):
        status = "NEWS_MISSING"
    elif any(pattern.search(title) for pattern in STALE_NEWS_PATTERNS):
        status = "NEWS_STALE"
    else:
        status = "NEWS_AVAILABLE"
    return {
        "status": status,
        "source": source,
        "title": title if status == "NEWS_AVAILABLE" else "",
    }


class ResearchEngine:
    """Read-only research engine inspired by TradingAgents role separation."""

    def __init__(self, config: ResearchLabConfig):
        self.config = config
        self.store = JsonlStore(config.history_file)

    def load_market_data(self) -> pd.DataFrame:
        path = self.config.market_results_file
        if not path.exists():
            raise FileNotFoundError(f"DATA_UNAVAILABLE: {path}")
        return pd.read_csv(path, encoding="utf-8-sig")

    def find_ticker(self, ticker: str) -> pd.Series:
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("DATA_UNAVAILABLE: ticker is empty")
        df = self.load_market_data()
        if "ticker" not in df.columns:
            raise ValueError("DATA_UNAVAILABLE: ticker column is missing")
        matches = df[df["ticker"].astype(str).str.upper() == normalized]
        if matches.empty:
            matches = df[df["ticker"].astype(str).str.upper().str.replace(".KS", "", regex=False).str.replace(".KQ", "", regex=False) == normalized]
        if matches.empty:
            raise LookupError(f"DATA_UNAVAILABLE: {normalized} not found")
        return matches.iloc[0]

    def research(self, ticker: str, *, save: bool = True) -> ResearchResult:
        row = self.find_ticker(ticker)
        result = self._build_result(row)
        if save:
            self.store.append(result.to_dict())
        return result

    def hot(self, limit: int | None = None) -> list[ResearchResult]:
        df = self.load_market_data()
        limit = limit or self.config.hot_limit
        scored: list[tuple[float, pd.Series]] = []
        for _, row in df.iterrows():
            change = abs(_num(row.get("change_pct"), 0) or 0)
            volume = _num(row.get("volume_ratio"), 0) or 0
            trade = _num(row.get("trade_value_ratio"), 0) or 0
            news = 12 if _text(row.get("news_one_line")) and "뉴스 없음" not in _text(row.get("news_one_line")) else 0
            ai_score = _num(row.get("ai_score"), _num(row.get("score"), 0)) or 0
            scored.append((change * 2.2 + volume * 7 + trade * 4 + news + ai_score * 0.08, row))
        picked = [row for _, row in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]]
        results = [self._build_result(row) for row in picked]
        for result in results:
            self.store.append(result.to_dict())
        return results

    def history(self, limit: int = 10, ticker: str | None = None) -> list[dict]:
        records = self.store.read_all()
        if ticker:
            target = ticker.strip().upper()
            records = [r for r in records if str(r.get("ticker", "")).upper() == target]
        return records[-limit:]

    def stats(self) -> dict[str, Any]:
        records = [r for r in self.store.read_all() if r.get("research_decision")]
        completed = []
        for record in records:
            returns = record.get("future_returns") or {}
            value = returns.get("5D")
            if value is not None:
                completed.append(record)
        if len(completed) < 5:
            return {"status": "DATA_UNAVAILABLE", "total_signals": len(records), "completed_5d": len(completed)}
        buy = [r for r in completed if r.get("research_decision") == "BUY CANDIDATE"]
        wins = [r for r in buy if (r.get("future_returns") or {}).get("5D", 0) > 0]
        avg = sum((r.get("future_returns") or {}).get("5D", 0) for r in completed) / len(completed)
        return {
            "status": "OK",
            "total_signals": len(records),
            "completed_5d": len(completed),
            "buy_candidate_win_rate": round(len(wins) / len(buy) * 100, 1) if buy else None,
            "average_5d_return": round(avg, 2),
        }

    def update_paper_returns(self) -> int:
        df = self.load_market_data()
        price_by_ticker = {
            str(row.get("ticker", "")).upper(): _num(row.get("price"))
            for _, row in df.iterrows()
        }
        now = datetime.now(timezone.utc)
        changed = 0
        records = self.store.read_all()
        for record in records:
            entry = _num(record.get("entry_reference"))
            ticker = str(record.get("ticker", "")).upper()
            latest = price_by_ticker.get(ticker)
            if not entry or not latest:
                continue
            try:
                ts = datetime.fromisoformat(str(record.get("timestamp")).replace("Z", "+00:00"))
            except ValueError:
                continue
            days = max(0, (now - ts).days)
            returns = record.setdefault("future_returns", {"1D": None, "3D": None, "5D": None, "10D": None})
            for label, required_days in (("1D", 1), ("3D", 3), ("5D", 5), ("10D", 10)):
                if days >= required_days and returns.get(label) is None:
                    returns[label] = round((latest - entry) / entry * 100, 2)
                    changed += 1
        if changed:
            self.store.replace_all(records)
        return changed

    def _build_result(self, row: pd.Series) -> ResearchResult:
        data_quality = validate_market_row(row)
        news_quality = validate_news_row(row)
        technical = self._technical(row)
        fundamental = self._fundamental(row)
        sentiment = self._sentiment(row, news_quality)
        bull = self._bull(row, technical, sentiment)
        bear = self._bear(row, technical, sentiment)
        risk_level, overheat = self._risk(row)
        continuation = self._continuation(row, technical, sentiment, risk_level)
        existing_ai_score = _int(row.get("ai_score"), _int(row.get("score")))
        existing_decision = self._existing_decision(row)
        research_score = self._final_score(technical, fundamental, sentiment, bull, bear, risk_level, continuation)
        research_decision = self._decision(research_score, risk_level, continuation)
        change = _num(row.get("change_pct"), 0) or 0
        already_risen = change >= 5 or (_num(row.get("rsi"), 0) or 0) >= 70
        reasoning = {
            "technical": technical.__dict__,
            "fundamental": fundamental.__dict__,
            "sentiment": sentiment.__dict__,
            "bull_case": bull,
            "bear_case": bear,
            "risk": {"level": risk_level, "overheat_risk": overheat},
            "data_quality": data_quality,
            "news_quality": news_quality,
            "score_inputs": {
                "price": "VALID" if data_quality["reference_price"] is not None and data_quality["reference_price"] > 0 else "INVALID",
                "momentum": "VALID" if data_quality["change_pct"] is not None else "MISSING",
                "volume": "VALID" if data_quality["volume_ratio"] is not None else "MISSING",
                "technical": technical.status,
                "news": news_quality["status"],
                "risk": "VALID" if risk_level in {"LOW", "MEDIUM", "HIGH"} else "INVALID",
                "continuation": "VALID",
            },
            "comparison": self._comparison(existing_ai_score, existing_decision, research_score, research_decision),
        }
        return ResearchResult(
            timestamp=utc_now_iso(),
            ticker=_text(row.get("ticker")).upper(),
            market=_text(row.get("market"), "UNKNOWN"),
            name=_text(row.get("name"), _text(row.get("ticker"))),
            current_price=_num(row.get("price")),
            existing_ai_score=existing_ai_score,
            existing_ai_decision=existing_decision,
            research_score=research_score,
            research_decision=research_decision,
            technical_score=technical.score,
            fundamental_score=fundamental.score,
            sentiment_score=sentiment.score,
            bull_score=bull["score"],
            bear_score=bear["score"],
            risk_level=risk_level,
            already_risen=already_risen,
            momentum=self._momentum(row),
            overheat_risk=overheat,
            continuation_potential=continuation,
            reasoning=reasoning,
            data_timestamp=_text(row.get("mobile_intel_generated_at"), _text(row.get("data_generated_at"), _text(row.get("file_updated_at")))),
            entry_reference=_num(row.get("price")),
        )

    def _technical(self, row: pd.Series) -> AnalystResult:
        score = _num(row.get("technical_score"), _num(row.get("score"), 50)) or 50
        rsi = _num(row.get("rsi"), 50) or 50
        change = _num(row.get("change_pct"), 0) or 0
        volume = _num(row.get("volume_ratio"), 1) or 1
        ma20 = _num(row.get("ma20_gap_pct"), 0) or 0
        if change > 2:
            score += 8
        if volume > 1.5:
            score += 8
        if 45 <= rsi <= 68:
            score += 6
        elif rsi >= 78:
            score -= 8
        if ma20 > 0:
            score += 4
        final = _clamp(score)
        direction = "Bullish" if final >= 68 else "Bearish" if final <= 42 else "Neutral"
        return AnalystResult(final, direction, f"change={change:.2f}%, volume={volume:.2f}x, RSI={rsi:.1f}, MA20 gap={ma20:.1f}%")

    def _fundamental(self, row: pd.Series) -> AnalystResult:
        available = [
            _text(row.get("dividend_summary")),
            _text(row.get("etf_summary")),
        ]
        if not any(text and text not in {"해당 없음", "섹터 확인 부족"} for text in available):
            return AnalystResult(None, "DATA_UNAVAILABLE", "Fundamental fields are not available in the current scanner dataset.", "DATA_UNAVAILABLE")
        base = 50
        if "배당" in " ".join(available):
            base += 5
        return AnalystResult(_clamp(base), "Neutral", "Limited scanner-level fundamental context only.")

    def _sentiment(self, row: pd.Series, news_quality: dict[str, Any] | None = None) -> AnalystResult:
        news_quality = news_quality or validate_news_row(row)
        news = _text(news_quality.get("title"))
        if news_quality.get("status") != "NEWS_AVAILABLE" or not news:
            return AnalystResult(None, "NO_RECENT_NEWS", str(news_quality.get("status") or "NEWS_MISSING"), "NEWS_UNAVAILABLE")
        positives = sum(1 for word in POSITIVE_WORDS if word.lower() in news.lower())
        negatives = sum(1 for word in NEGATIVE_WORDS if word.lower() in news.lower())
        score = _clamp(50 + positives * 10 - negatives * 12 + (_num(row.get("news_score"), 0) or 0) * 0.5)
        direction = "Bullish" if score >= 65 else "Bearish" if score <= 40 else "Neutral"
        return AnalystResult(score, direction, f"positive_keywords={positives}, negative_keywords={negatives}, source={_text(row.get('news_source'), 'unknown')}")

    def _bull(self, row: pd.Series, technical: AnalystResult, sentiment: AnalystResult) -> dict[str, Any]:
        reasons = []
        if technical.direction == "Bullish":
            reasons.append("기술적 흐름이 상승 쪽입니다.")
        if sentiment.direction == "Bullish":
            reasons.append("최근 뉴스/심리가 우호적입니다.")
        if (_num(row.get("volume_ratio"), 0) or 0) >= 1.5:
            reasons.append("평소보다 거래량이 강합니다.")
        if (_num(row.get("trade_value_ratio"), 0) or 0) >= 1.3:
            reasons.append("거래대금 유입이 커졌습니다.")
        if not reasons:
            reasons.append("강한 상승 근거는 제한적입니다.")
        score = _clamp((technical.score or 50) * 0.55 + (sentiment.score or 45) * 0.3 + min((_num(row.get("volume_ratio"), 1) or 1) * 8, 18))
        return {"score": score, "reasons": reasons[:5]}

    def _bear(self, row: pd.Series, technical: AnalystResult, sentiment: AnalystResult) -> dict[str, Any]:
        reasons = []
        rsi = _num(row.get("rsi"), 50) or 50
        change = _num(row.get("change_pct"), 0) or 0
        if rsi >= 75:
            reasons.append("RSI 과열 구간입니다.")
        if change >= 7:
            reasons.append("당일 상승폭이 커 추격 위험이 있습니다.")
        if sentiment.direction == "Bearish":
            reasons.append("뉴스/심리 쪽 위험 신호가 있습니다.")
        atr = _num(row.get("atr_pct"), 0) or 0
        volume = _num(row.get("volume_ratio"), 1) or 1
        trade = _num(row.get("trade_value_ratio"), 1) or 1
        if atr >= 6:
            reasons.append("변동성이 높아 손실 위험이 큽니다.")
        if volume < 0.7 or trade < 0.7:
            reasons.append("거래 확인이 약해 신호 신뢰도가 낮습니다.")
        if not reasons:
            reasons.append("뚜렷한 하락 근거는 제한적입니다.")
        score = _clamp(35 + max(0, rsi - 65) * 1.4 + max(0, change - 4) * 3 + (15 if sentiment.direction == "Bearish" else 0))
        return {"score": score, "reasons": reasons[:5]}

    def _risk(self, row: pd.Series) -> tuple[str, str]:
        rsi = _num(row.get("rsi"), 50) or 50
        atr = _num(row.get("atr_pct"), 0) or 0
        change = abs(_num(row.get("change_pct"), 0) or 0)
        chase = _text(row.get("chase_risk")).lower() == "true" or _text(row.get("chase_risk_note")) == "있음"
        points = 0
        points += 2 if rsi >= 75 else 1 if rsi >= 68 else 0
        points += 2 if atr >= 6 else 1 if atr >= 3 else 0
        points += 2 if change >= 8 else 1 if change >= 4 else 0
        points += 1 if chase else 0
        level = "HIGH" if points >= 5 else "MEDIUM" if points >= 2 else "LOW"
        overheat = "HIGH" if rsi >= 75 or change >= 8 else "MEDIUM" if rsi >= 68 or change >= 4 else "LOW"
        return level, overheat

    def _continuation(self, row: pd.Series, technical: AnalystResult, sentiment: AnalystResult, risk: str) -> int:
        change = _num(row.get("change_pct"), 0) or 0
        volume = _num(row.get("volume_ratio"), 1) or 1
        trade = _num(row.get("trade_value_ratio"), 1) or 1
        base = (technical.score or 50) * 0.4 + (sentiment.score or 45) * 0.25
        base += min(volume * 8, 22) + min(trade * 5, 14)
        if change >= 5:
            base += 7
        if risk == "HIGH":
            base -= 8
        return _clamp(base)

    def _final_score(self, technical: AnalystResult, fundamental: AnalystResult, sentiment: AnalystResult, bull: dict[str, Any], bear: dict[str, Any], risk: str, continuation: int) -> int:
        score = (technical.score or 50) * 0.28 + (sentiment.score or 45) * 0.2 + bull["score"] * 0.22 + continuation * 0.22 - bear["score"] * 0.12
        if fundamental.score is not None:
            score += fundamental.score * 0.1
        if risk == "HIGH":
            score -= 8
        elif risk == "LOW":
            score += 4
        return _clamp(score)

    def _decision(self, score: int, risk: str, continuation: int) -> str:
        if score >= 78 and risk != "HIGH" and continuation >= 72:
            return "BUY CANDIDATE"
        if score >= 62:
            return "WATCH"
        if score >= 45:
            return "WAIT"
        return "AVOID"

    def _existing_decision(self, row: pd.Series) -> str:
        text = " ".join([_text(row.get("ai_label")), _text(row.get("action")), _text(row.get("recommendation_type"))])
        if any(word in text for word in ("매수", "BUY")):
            return "BUY CANDIDATE"
        if "관찰" in text or "WATCH" in text:
            return "WATCH"
        if "대기" in text or "WAIT" in text:
            return "WAIT"
        if "위험" in text or "AVOID" in text:
            return "AVOID"
        return "WATCH"

    def _momentum(self, row: pd.Series) -> str:
        change = _num(row.get("change_pct"), 0) or 0
        volume = _num(row.get("volume_ratio"), 1) or 1
        if change >= 5 and volume >= 1.5:
            return "STRONG"
        if change >= 2 or volume >= 1.2:
            return "MEDIUM"
        return "LOW"

    def _comparison(self, existing_score: int | None, existing_decision: str, research_score: int, research_decision: str) -> dict[str, Any]:
        existing_positive = existing_decision in {"BUY CANDIDATE", "WATCH"}
        research_positive = research_decision in {"BUY CANDIDATE", "WATCH"}
        return {
            "difference": None if existing_score is None else research_score - existing_score,
            "alignment": "CONFIRMED" if existing_positive == research_positive else "CONFLICT",
        }
