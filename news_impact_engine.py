#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, timedelta
from typing import Any


POSITIVE_PATTERNS: dict[str, tuple[int, str]] = {
    "대형 수주": (34, "대형 계약/수주"),
    "수주": (26, "계약/수주"),
    "계약": (23, "계약 체결"),
    "공급": (22, "공급 계약"),
    "장기 공급": (32, "장기 공급 계약"),
    "승인": (25, "허가/승인"),
    "허가": (24, "허가/승인"),
    "흑자": (28, "실적 개선"),
    "호실적": (30, "실적 개선"),
    "서프라이즈": (34, "실적 서프라이즈"),
    "증설": (18, "성장 투자"),
    "시설투자": (18, "성장 투자"),
    "설비투자": (18, "성장 투자"),
    "제3자배정": (12, "전략 투자 가능성"),
    "전략적 투자": (20, "전략 투자"),
    "정부 지원": (22, "정책 지원"),
    "보조금": (20, "정책 지원"),
    "관세 완화": (18, "정책 부담 완화"),
    "원전 수주": (38, "원전 수주"),
    "플랜트 수주": (32, "플랜트 수주"),
    "ai 데이터센터": (24, "AI 데이터센터 수요"),
    "전력망": (22, "전력망 투자"),
    "반도체 패키징": (21, "반도체 패키징 수요"),
    "양자컴퓨팅": (19, "신규 테마 확산"),
}

NEGATIVE_PATTERNS: dict[str, tuple[int, str]] = {
    "유상증자": (-30, "증자/희석"),
    "주주배정": (-42, "주주배정 증자"),
    "전환사채": (-36, "전환사채/희석"),
    "cb": (-30, "전환사채/희석"),
    "희석": (-38, "지분 희석"),
    "운영자금": (-24, "운영자금 조달"),
    "채무상환": (-32, "채무상환 목적"),
    "적자": (-34, "실적 악화"),
    "어닝쇼크": (-44, "어닝 쇼크"),
    "실적쇼크": (-44, "실적 쇼크"),
    "컨센서스 하회": (-38, "실적 기대 하회"),
    "전망 하향": (-34, "전망 하향"),
    "목표가 하향": (-28, "목표가 하향"),
    "소송": (-30, "소송 리스크"),
    "조사": (-26, "조사/규제 리스크"),
    "제재": (-31, "제재 리스크"),
    "거래정지": (-55, "거래정지 리스크"),
    "영업정지": (-48, "영업정지 리스크"),
    "철근": (-46, "건설 품질 리스크"),
    "누락": (-42, "품질/안전 리스크"),
    "부실시공": (-50, "부실시공"),
    "붕괴": (-58, "안전사고"),
    "발사 실패": (-45, "발사 실패"),
    "로켓 폭발": (-52, "로켓 폭발"),
    "발사 지연": (-32, "발사 지연"),
    "rocket explosion": (-52, "로켓 폭발"),
    "launch failure": (-45, "발사 실패"),
    "launch delay": (-32, "발사 지연"),
    "downgrade": (-28, "투자의견 하향"),
    "plunge": (-24, "급락 반응"),
    "tumble": (-24, "급락 반응"),
}

CAPITAL_GOOD_TERMS = ("시설투자", "설비투자", "증설", "공장", "인수", "투자", "제3자배정", "전략적")
CAPITAL_BAD_TERMS = ("운영자금", "채무상환", "주주배정", "차입금", "적자", "재무구조")

THEME_CANDIDATES = (
    "관세", "보조금", "AI 데이터센터", "원전", "전력망", "반도체 패키징", "양자컴퓨팅",
    "로봇", "드론", "우주항공", "구리", "전선", "전력", "해운", "의료", "제약",
)


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:18]


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def contains_any(lowered: str, words: tuple[str, ...]) -> bool:
    return any(word.lower() in lowered for word in words)


def extract_patterns(news_text: str, sector: str = "") -> list[tuple[str, int, str]]:
    text = clean_text(f"{sector} {news_text}")
    lowered = text.lower()
    hits: list[tuple[str, int, str]] = []

    capital_raise = "유상증자" in text or "증자" in text
    capital_good = contains_any(lowered, tuple(term.lower() for term in CAPITAL_GOOD_TERMS))
    capital_bad = contains_any(lowered, tuple(term.lower() for term in CAPITAL_BAD_TERMS))

    for keyword, (weight, reason) in POSITIVE_PATTERNS.items():
        if keyword.lower() in lowered:
            if keyword in {"제3자배정", "전략적 투자"} or not capital_raise or capital_good:
                hits.append((keyword, weight, reason))

    for keyword, (weight, reason) in NEGATIVE_PATTERNS.items():
        if keyword.lower() in lowered:
            if keyword == "유상증자" and capital_good and not capital_bad:
                hits.append(("성장형 유증", 14, "시설/성장 투자 목적"))
                continue
            hits.append((keyword, weight, reason))

    if capital_raise and not any(hit[0] in {"유상증자", "성장형 유증", "주주배정"} for hit in hits):
        if capital_good and not capital_bad:
            hits.append(("성장형 유증", 14, "시설/성장 투자 목적"))
        elif capital_bad:
            hits.append(("부담형 유증", -34, "운영자금/채무상환 목적"))
        else:
            hits.append(("유증 목적 확인", -12, "자금조달 목적 불명확"))

    return hits


def latest_embedded_news_date(news_text: str, now: datetime) -> datetime | None:
    dates = []
    for year, month, day in re.findall(r"(20\d{2})[-./](\d{1,2})[-./](\d{1,2})", str(news_text or "")):
        try:
            dates.append(datetime(int(year), int(month), int(day)))
        except ValueError:
            continue
    if not dates:
        return None
    return max(dates)


def similar_case_adjustment(patterns: list[tuple[str, int, str]], state: dict[str, Any]) -> tuple[int, int, str]:
    pattern_db = state.setdefault("patterns", {})
    if not patterns:
        return 0, 0, "과거 유사 사례 부족"

    adjustments = []
    confidence_bonus = 0
    summaries = []
    for keyword, weight, _ in patterns[:5]:
        item = pattern_db.get(keyword, {})
        samples = int(item.get("samples", 0) or 0)
        avg_return = float(item.get("avg_return_5d", item.get("avg_return_3d", 0)) or 0)
        positive_rate = float(item.get("positive_rate", 0.5) or 0.5)
        if samples <= 0:
            continue
        direction = 1 if weight > 0 else -1
        adjustment = int(max(-15, min(15, avg_return * 2.2 * direction + (positive_rate - 0.5) * 18 * direction)))
        adjustments.append(adjustment)
        confidence_bonus += min(10, samples * 2)
        summaries.append(f"{keyword} 유사 {samples}건 · 평균 {avg_return:+.1f}%")

    if not adjustments:
        return 0, 0, "과거 유사 사례 누적 대기"
    return int(sum(adjustments) / len(adjustments)), min(confidence_bonus, 18), " / ".join(summaries[:2])


def classify_score(score: int) -> str:
    if score >= 90:
        return "강한 호재"
    if score >= 50:
        return "호재"
    if score >= 10:
        return "약한 호재"
    if score <= -90:
        return "강한 악재"
    if score <= -50:
        return "악재"
    if score <= -10:
        return "약한 악재"
    return "중립"


def expectation_for(score: int) -> str:
    if score >= 70:
        return "1주일 내 긍정 반응 가능성 높음"
    if score >= 20:
        return "단기 긍정 반응 가능성 있음"
    if score <= -70:
        return "1주일 내 하락 압력 가능성 높음"
    if score <= -20:
        return "단기 변동성/하락 압력 주의"
    return "가격 반응 확인 전까지 중립"


def analyze_news_impact(
    *,
    name: str,
    ticker: str,
    market: str,
    sector: str,
    news_text: str,
    price: float = 0.0,
    change_pct: float = 0.0,
    volume_ratio: float = 1.0,
    risk: float = 0.0,
    now: datetime | None = None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = now or datetime.now()
    state = state if state is not None else {}
    text = clean_text(news_text)
    embedded_date = latest_embedded_news_date(text, now.replace(tzinfo=None))
    if embedded_date and embedded_date < now.replace(tzinfo=None) - timedelta(days=14):
        return {
            "label": "중립",
            "impact_score": 0,
            "confidence": 52,
            "basis": "2주 초과 뉴스 제외",
            "similar": "과거 뉴스는 영향도 산정 제외",
            "expectation": "최신 뉴스 재확인 필요",
            "summary": "중립 · 영향도 +0 · 신뢰도 52% · 근거: 2주 초과 뉴스 제외",
            "patterns": [],
            "observation_key": stable_hash(f"{ticker}|stale-news|{text[:120]}"),
        }
    patterns = extract_patterns(text, sector)
    base_score = sum(weight for _, weight, _ in patterns)
    base_score += int(max(0.0, min(4.0, volume_ratio - 1.0)) * (5 if base_score >= 0 else -5))
    if risk >= 45 and base_score < 0:
        base_score -= 8
    if abs(change_pct) >= 6:
        base_score = int(base_score * 0.86)

    similar_adjustment, confidence_bonus, similar_summary = similar_case_adjustment(patterns, state)
    impact_score = max(-100, min(100, base_score + similar_adjustment))
    label = classify_score(impact_score)
    confidence = min(
        96,
        max(
            45,
            52
            + len(patterns) * 8
            + confidence_bonus
            + min(12, int(max(0.0, volume_ratio - 1.0) * 4))
            - (10 if label == "중립" else 0),
        ),
    )
    reasons = []
    for _, _, reason in patterns:
        if reason not in reasons:
            reasons.append(reason)
    if similar_adjustment:
        reasons.append("과거 유사 사례 반영")
    if volume_ratio >= 1.8:
        reasons.append("거래량 동반")
    if not reasons:
        reasons.append("뚜렷한 방향성 키워드 부족")

    headline_key = stable_hash(f"{ticker}|{text[:220]}")
    observations = state.setdefault("observations", {})
    if headline_key not in observations and text:
        observations[headline_key] = {
            "name": name,
            "ticker": ticker,
            "market": market,
            "sector": sector,
            "headline": text[:240],
            "base_price": round(float(price or 0), 4),
            "impact_score": impact_score,
            "label": label,
            "patterns": [keyword for keyword, _, _ in patterns],
            "created_at": now.isoformat(),
            "returns": {},
        }

    for keyword, _, _ in patterns:
        state.setdefault("keyword_counts", {})
        state["keyword_counts"][keyword] = int(state["keyword_counts"].get(keyword, 0) or 0) + 1

    summary = (
        f"{label} · 영향도 {impact_score:+d} · 신뢰도 {confidence}% · "
        f"근거: {', '.join(reasons[:3])} · 유사사례: {similar_summary}"
    )
    return {
        "label": label,
        "impact_score": impact_score,
        "confidence": confidence,
        "basis": ", ".join(reasons[:4]),
        "similar": similar_summary,
        "expectation": expectation_for(impact_score),
        "summary": summary,
        "patterns": [keyword for keyword, _, _ in patterns],
        "observation_key": headline_key,
    }


def update_news_outcomes(rows: list[dict[str, Any]], state: dict[str, Any], now: datetime | None = None) -> None:
    now = now or datetime.now()
    observations = state.setdefault("observations", {})
    pattern_db = state.setdefault("patterns", {})
    price_map = {
        str(row.get("ticker", "") or ""): float(row.get("price", 0) or 0)
        for row in rows
        if str(row.get("ticker", "") or "")
    }
    for item in observations.values():
        ticker = str(item.get("ticker", ""))
        base_price = float(item.get("base_price", 0) or 0)
        current = price_map.get(ticker, 0)
        if base_price <= 0 or current <= 0:
            continue
        created_at = item.get("created_at")
        try:
            created = datetime.fromisoformat(str(created_at))
        except Exception:
            continue
        age_days = max(0, (now - created.replace(tzinfo=None)).days)
        ret = ((current / base_price) - 1) * 100
        for day in (1, 3, 5, 20):
            if age_days < day:
                continue
            returns = item.setdefault("returns", {})
            key = f"{day}d"
            if key in returns:
                continue
            returns[key] = round(ret, 2)
            for pattern in item.get("patterns", []):
                stats = pattern_db.setdefault(pattern, {"samples": 0, "avg_return_1d": 0, "avg_return_3d": 0, "avg_return_5d": 0, "avg_return_20d": 0, "positive_hits": 0})
                samples = int(stats.get("samples", 0) or 0) + 1
                avg_key = f"avg_return_{key}"
                prev_avg = float(stats.get(avg_key, 0) or 0)
                stats[avg_key] = round(prev_avg + (ret - prev_avg) / samples, 3)
                stats["samples"] = samples
                if ret > 0:
                    stats["positive_hits"] = int(stats.get("positive_hits", 0) or 0) + 1
                stats["positive_rate"] = round(int(stats.get("positive_hits", 0) or 0) / max(samples, 1), 3)


def learned_keyword_summary(state: dict[str, Any], limit: int = 8) -> str:
    counts = state.get("keyword_counts", {})
    if not isinstance(counts, dict) or not counts:
        return "자동 확장 키워드 대기"
    known = {key.lower() for key in list(POSITIVE_PATTERNS) + list(NEGATIVE_PATTERNS)}
    ranked = sorted(counts.items(), key=lambda item: int(item[1] or 0), reverse=True)
    candidates = [key for key, _ in ranked if str(key).lower() not in known]
    base_themes = [theme for theme in THEME_CANDIDATES if theme in counts]
    result = list(dict.fromkeys(base_themes + candidates))[:limit]
    return ", ".join(result) if result else "자동 확장 키워드 대기"
