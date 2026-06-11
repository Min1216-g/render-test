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
    "통합 시너지": (22, "통합 시너지 기대"),
    "시너지": (16, "통합 시너지 기대"),
    "합병": (14, "합병/통합 효과"),
    "인수": (12, "인수/통합 효과"),
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
    "spacex": (20, "SpaceX 이벤트"),
    "starlink": (24, "Starlink 성장 모멘텀"),
    "starship": (18, "Starship 프로젝트 모멘텀"),
    "falcon 9": (16, "Falcon 9 발사 모멘텀"),
    "launch success": (30, "발사 성공"),
    "successful launch": (30, "발사 성공"),
    "government contract": (34, "정부 계약"),
    "nasa contract": (36, "NASA 계약"),
    "space launch": (16, "우주 발사 이벤트"),
}

NEGATIVE_PATTERNS: dict[str, tuple[int, str]] = {
    "유상증자": (-30, "증자/희석"),
    "주주배정": (-42, "주주배정 증자"),
    "전환사채": (-36, "전환사채/희석"),
    "cb": (-30, "전환사채/희석"),
    "희석": (-38, "지분 희석"),
    "운영자금": (-24, "운영자금 조달"),
    "채무상환": (-32, "채무상환 목적"),
    "차입금": (-26, "차입금 증가"),
    "부채 증가": (-24, "재무부담 증가"),
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
    "launch anomaly": (-40, "발사 이상"),
    "starship failure": (-46, "Starship 실패"),
    "falcon 9 failure": (-42, "Falcon 9 실패"),
    "starship delay": (-30, "Starship 지연"),
    "falcon 9 delay": (-30, "Falcon 9 지연"),
    "downgrade": (-28, "투자의견 하향"),
    "plunge": (-24, "급락 반응"),
    "tumble": (-24, "급락 반응"),
}

CAPITAL_GOOD_TERMS = ("시설투자", "설비투자", "증설", "공장", "인수", "투자", "제3자배정", "전략적")
CAPITAL_BAD_TERMS = ("운영자금", "채무상환", "주주배정", "차입금", "적자", "재무구조")

THEME_CANDIDATES = (
    "관세", "보조금", "AI 데이터센터", "원전", "전력망", "반도체 패키징", "양자컴퓨팅",
    "로봇", "드론", "우주항공", "구리", "전선", "전력", "해운", "의료", "제약",
    "SpaceX", "Starlink", "Starship", "Falcon 9", "NASA Contract",
)

RESULT_NEWS_TERMS = (
    "급등", "급락", "신고가", "신저가", "상승세", "하락세", "거래량 폭증", "거래량 급증",
    "외국인 매수", "기관 매수", "외국인·기관", "수급 집중", "강세 마감", "약세 마감",
    "순매수", "장중 신고가", "52주 신고가", "52주 신저가", "surges", "jumps", "plunge",
    "tumble", "rallies", "record high",
)

B_GRADE_TERMS = (
    "목표주가 상향", "목표가 상향", "투자의견", "애널리스트", "업황 개선", "시장 성장",
    "산업 보고서", "경쟁사", "전망", "report", "analyst", "price target", "outlook",
)

A_GRADE_TERMS = (
    "대형 수주", "장기 공급", "공급 계약", "정부 지원", "정책", "규제 완화", "규제 강화",
    "배당 확대", "자사주", "실적 서프라이즈", "흑자 전환", "적자 전환", "m&a", "인수",
    "합병", "대규모 투자", "증설", "공장", "신사업", "fda", "원전 수주", "방산 계약",
    "ai 투자", "데이터센터", "전력망", "관세", "금리", "환율", "신제품", "고객사",
    "계약 체결", "계약 취소", "소송", "횡령", "배임", "상장폐지", "유상증자", "전환사채",
    "감자", "리콜", "생산 중단", "launch success", "launch failure", "government contract",
    "nasa contract", "starlink", "starship", "falcon 9",
)

POLICY_TERMS = {
    "정책 수혜": ("정부 지원", "보조금", "정책", "국책", "예산 확대"),
    "정책 리스크": ("규제", "제재", "조사", "정책 지연"),
    "환율 영향": ("환율", "원화", "달러", "외환"),
    "금리 영향": ("금리", "인하", "인상", "채권"),
    "원자재 영향": ("구리", "알루미늄", "원자재", "유가", "가스"),
    "관세 영향": ("관세", "무역장벽"),
    "미중 갈등 영향": ("미중", "중국 제재", "수출 통제"),
    "국방 예산 영향": ("국방 예산", "방산", "무기", "군수"),
    "반도체 투자 영향": ("반도체 투자", "hbm", "패키징", "파운드리"),
    "AI 투자 영향": ("ai 투자", "ai 데이터센터", "인공지능"),
    "전력 수요 증가": ("전력 수요", "전력망", "변압기", "데이터센터 전력"),
    "우주 산업 투자": ("우주", "로켓", "위성", "발사체", "spacex", "starlink", "starship", "falcon 9", "nasa contract"),
    "원전 정책 변화": ("원전 정책", "원전 수주", "smr", "원자력"),
}


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

    debt_context = contains_any(lowered, ("차입금", "부채 증가", "재무부담"))
    synergy_context = contains_any(lowered, ("통합 시너지", "시너지", "합병", "인수"))
    repayment_context = contains_any(lowered, ("채무상환", "운영자금", "적자 보전", "유동성 위기"))
    if debt_context and synergy_context and not repayment_context:
        hits.append(("차입금-시너지 상쇄", 20, "통합 시너지로 재무부담 일부 상쇄"))

    return hits


def classify_news_filter(news_text: str, patterns: list[tuple[str, int, str]]) -> dict[str, Any]:
    text = clean_text(news_text)
    lowered = text.lower()
    result_hits = [term for term in RESULT_NEWS_TERMS if term.lower() in lowered]
    b_hits = [term for term in B_GRADE_TERMS if term.lower() in lowered]
    a_hits = [term for term in A_GRADE_TERMS if term.lower() in lowered]
    pattern_cause_hits = [
        keyword
        for keyword, _, _ in patterns
        if keyword not in result_hits and keyword.lower() not in {term.lower() for term in RESULT_NEWS_TERMS}
    ]

    has_cause = bool(a_hits or pattern_cause_hits)
    has_result = bool(result_hits)

    if has_cause and has_result:
        news_type = "혼합 뉴스"
    elif has_cause:
        news_type = "원인 뉴스"
    elif has_result:
        news_type = "결과 뉴스"
    elif b_hits:
        news_type = "보조 뉴스"
    else:
        news_type = "원인 확인 필요"

    if has_cause:
        grade = "A"
    elif b_hits:
        grade = "B"
    elif has_result:
        grade = "C"
    else:
        grade = "C"

    cause_summary = []
    if has_result and not has_cause:
        cause_summary.append("결과 뉴스 감지: 최근 7일 뉴스/공시/정책/섹터에서 원인 재탐색 필요")
    if has_cause:
        cause_summary.append("기업 가치에 직접 영향을 줄 수 있는 원인 뉴스")
    if b_hits and not has_cause:
        cause_summary.append("보조 뉴스: 전망/의견성 자료라 점수 제한")
    if not cause_summary:
        cause_summary.append("원인 뉴스 확인 전까지 낮은 중요도")

    return {
        "news_grade": grade,
        "news_type": news_type,
        "result_hits": result_hits[:4],
        "cause_hits": (a_hits + pattern_cause_hits)[:5],
        "b_hits": b_hits[:4],
        "is_result_only": has_result and not has_cause,
        "cause_summary": " · ".join(cause_summary),
    }


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


def v2_impact_strength(score: int) -> int:
    return max(0, min(10, int(round(abs(score) / 10))))


def v2_market_reaction(score: int) -> str:
    if score >= 70:
        return "매우 긍정적"
    if score >= 20:
        return "긍정적"
    if score <= -70:
        return "매우 부정적"
    if score <= -20:
        return "부정적"
    return "보통"


def v2_duration(patterns: list[tuple[str, int, str]], score: int) -> str:
    pattern_text = " ".join(keyword for keyword, _, _ in patterns).lower()
    if contains_any(pattern_text, ("장기 공급", "원전 수주", "정부 지원", "시설투자", "증설", "ai 데이터센터", "전력망")):
        return "장기 (6개월 이상)" if abs(score) >= 35 else "중기 (1~6개월)"
    if contains_any(pattern_text, ("실적", "어닝", "전망", "목표가", "소송", "조사", "발사 실패", "로켓 폭발")):
        return "단기 (1일~1개월)"
    if abs(score) >= 50:
        return "중기 (1~6개월)"
    return "단기 (1일~1개월)"


def v2_lead_status(change_pct: float, volume_ratio: float, score: int) -> str:
    if abs(change_pct) >= 6 or volume_ratio >= 3.5:
        return "이미 반영"
    if abs(change_pct) >= 2 or volume_ratio >= 1.5:
        return "일부 반영"
    if abs(score) >= 20:
        return "미반영 가능성 높음"
    return "일부 반영"


def v2_lead_status_with_news_type(change_pct: float, volume_ratio: float, score: int, news_type: str) -> str:
    if news_type == "결과 뉴스":
        return "이미 반영"
    if news_type == "원인 뉴스" and abs(change_pct) < 2 and volume_ratio < 1.5 and abs(score) >= 20:
        return "미반영 가능성 높음"
    if news_type == "혼합 뉴스" and (abs(change_pct) >= 3 or volume_ratio >= 2):
        return "일부 반영"
    return v2_lead_status(change_pct, volume_ratio, score)


def v2_signal(label: str, score: int, risk: float, lead_status: str) -> str:
    if score >= 70 and risk < 35 and lead_status != "이미 반영":
        return "강한 매수 관찰"
    if score >= 25 and risk < 45:
        return "매수 관찰"
    if score <= -65 or risk >= 55:
        return "위험"
    if score <= -20:
        return "주의"
    return "관망"


def v2_confidence(score: int, confidence: int, patterns: list[tuple[str, int, str]]) -> str:
    if confidence >= 88 and len(patterns) >= 2 and abs(score) >= 60:
        return "A+"
    if confidence >= 78 and abs(score) >= 35:
        return "A"
    if confidence >= 62:
        return "B"
    return "C"


def v2_sector_impact(sector: str, patterns: list[tuple[str, int, str]], score: int) -> str:
    sector_text = sector or "동일 섹터"
    if score >= 30:
        return f"{sector_text} 내 후행 관련주로 관심이 확산될 수 있습니다. 대장주보다 덜 오른 종목을 우선 확인합니다."
    if score <= -30:
        return f"{sector_text} 전반에 리스크 프리미엄이 붙을 수 있어 같은 테마 종목도 변동성 확대를 경계합니다."
    if patterns:
        return f"{sector_text} 관련 이벤트는 감지됐지만 섹터 전체 확산은 추가 거래량 확인이 필요합니다."
    return f"{sector_text} 영향은 아직 제한적입니다."


def v2_policy_flags(news_text: str) -> list[str]:
    lowered = clean_text(news_text).lower()
    flags = []
    for label, terms in POLICY_TERMS.items():
        if contains_any(lowered, tuple(term.lower() for term in terms)):
            flags.append(label)
    return flags[:4]


def v2_effect_values(score: int, duration: str) -> tuple[int, int, int]:
    short = max(-10, min(10, int(round(score / 10))))
    if duration.startswith("단기"):
        mid = int(round(short * 0.55))
        long = int(round(short * 0.25))
    elif duration.startswith("중기"):
        mid = max(-10, min(10, int(round(score / 9))))
        long = int(round(mid * 0.55))
    else:
        mid = max(-10, min(10, int(round(score / 11))))
        long = max(-10, min(10, int(round(score / 9))))
    return short, mid, long


def impact_strength_label(score: int) -> str:
    value = abs(score)
    if value >= 80:
        return "매우 높음"
    if value >= 50:
        return "높음"
    if value >= 20:
        return "보통"
    if value >= 5:
        return "낮음"
    return "매우 낮음"


def leading_detection_summary(sector: str, filter_info: dict[str, Any], score: int) -> str:
    sector_text = sector or "동일 섹터"
    if filter_info.get("news_type") == "결과 뉴스":
        return f"{sector_text}: 결과 뉴스라 신규 진입 신호로 보지 않고 원인 뉴스/공시 재확인"
    if filter_info.get("news_grade") == "A" and score > 0:
        return f"{sector_text}: 정책/수급/공급망 후행주 탐색 우선 · 1주~1개월 주도 가능성 확인"
    if filter_info.get("news_grade") == "A" and score < 0:
        return f"{sector_text}: 악재 확산 가능성 확인 · 동종 업계 리스크 전이 주의"
    if filter_info.get("news_grade") == "B":
        return f"{sector_text}: 보조 뉴스라 실제 자금 이동 동반 여부 확인"
    return f"{sector_text}: 선행성 낮음 · 원인 뉴스 추가 확인 필요"


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
            "v2_strength": 0,
            "v2_duration": "단기 (1일~1개월)",
            "v2_market_reaction": "보통",
            "v2_positive_factors": "",
            "v2_negative_factors": "2주 초과 뉴스",
            "v2_short_effect": 0,
            "v2_mid_effect": 0,
            "v2_long_effect": 0,
            "v2_sector_impact": "오래된 뉴스라 섹터 영향도 산정에서 제외합니다.",
            "v2_lead_status": "이미 반영",
            "v2_core_signal": "오래된 뉴스 제외 · 최신 기사 재확인 필요",
            "v2_final_signal": "관망",
            "v2_confidence_grade": "C",
            "v2_policy_flags": "",
            "news_grade": "C",
            "news_type": "결과 뉴스",
            "good_score": 0,
            "bad_score": 0,
            "impact_strength_label": "매우 낮음",
            "leading_detection": "2주 초과 뉴스라 선행 탐지에서 제외",
        }
    patterns = extract_patterns(text, sector)
    filter_info = classify_news_filter(text, patterns)
    base_score = sum(weight for _, weight, _ in patterns)
    lowered_text = text.lower()
    debt_context = contains_any(lowered_text, ("차입금", "부채 증가", "재무부담"))
    synergy_context = contains_any(lowered_text, ("통합 시너지", "시너지", "합병", "인수"))
    repayment_context = contains_any(lowered_text, ("채무상환", "운영자금", "적자 보전", "유동성 위기"))
    if debt_context and synergy_context and not repayment_context and -35 <= base_score <= 35:
        base_score = 0
    base_score += int(max(0.0, min(4.0, volume_ratio - 1.0)) * (5 if base_score >= 0 else -5))
    if risk >= 45 and base_score < 0:
        base_score -= 8
    if abs(change_pct) >= 6:
        base_score = int(base_score * 0.86)
    if filter_info["is_result_only"]:
        base_score = max(-3, min(3, base_score))
    elif filter_info["news_grade"] == "B":
        base_score = max(-30, min(30, base_score))

    similar_adjustment, confidence_bonus, similar_summary = similar_case_adjustment(patterns, state)
    if filter_info["is_result_only"]:
        similar_adjustment = 0
        similar_summary = "결과 뉴스라 과거 사례 가중치 제외"
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
    if filter_info["is_result_only"]:
        reasons.insert(0, "결과 뉴스 - 원인 확인 필요")
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
    positive_factors = [reason for _, weight, reason in patterns if weight > 0]
    negative_factors = [reason for _, weight, reason in patterns if weight < 0]
    good_score = max(0, min(100, sum(weight for _, weight, _ in patterns if weight > 0)))
    bad_score = max(0, min(100, abs(sum(weight for _, weight, _ in patterns if weight < 0))))
    if filter_info["is_result_only"]:
        good_score = min(good_score, 3)
        bad_score = min(bad_score, 3)
    duration = v2_duration(patterns, impact_score)
    lead_status = v2_lead_status_with_news_type(change_pct, volume_ratio, impact_score, str(filter_info["news_type"]))
    short_effect, mid_effect, long_effect = v2_effect_values(impact_score, duration)
    market_reaction = v2_market_reaction(impact_score)
    final_signal = v2_signal(label, impact_score, risk, lead_status)
    policy_flags = v2_policy_flags(text)
    core_signal = (
        f"{filter_info['news_grade']}등급/{filter_info['news_type']} · {label} · {market_reaction} · {lead_status} · "
        f"{' / '.join(reasons[:2]) if reasons else '이벤트 방향성 확인 필요'}"
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
        "v2_strength": v2_impact_strength(impact_score),
        "v2_duration": duration,
        "v2_market_reaction": market_reaction,
        "v2_positive_factors": " | ".join(dict.fromkeys(positive_factors)) or "뚜렷한 호재 요인 제한",
        "v2_negative_factors": " | ".join(dict.fromkeys(negative_factors)) or "뚜렷한 악재 요인 제한",
        "v2_short_effect": short_effect,
        "v2_mid_effect": mid_effect,
        "v2_long_effect": long_effect,
        "v2_sector_impact": v2_sector_impact(sector, patterns, impact_score),
        "v2_lead_status": lead_status,
        "v2_core_signal": core_signal,
        "v2_final_signal": final_signal,
        "v2_confidence_grade": v2_confidence(impact_score, confidence, patterns),
        "v2_policy_flags": " | ".join(policy_flags) if policy_flags else "특별 매크로/정책 항목 없음",
        "news_grade": filter_info["news_grade"],
        "news_type": filter_info["news_type"],
        "good_score": good_score,
        "bad_score": bad_score,
        "impact_strength_label": impact_strength_label(impact_score),
        "leading_detection": leading_detection_summary(sector, filter_info, impact_score),
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
