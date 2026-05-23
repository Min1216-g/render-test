#!/usr/bin/env python3

from __future__ import annotations


SECTOR_KEYWORD_PROFILES = {
    "건설": {
        "positive": ["대형 수주", "해외 수주", "정비사업 수주", "분양 완판", "PF 정상화", "흑자 전환"],
        "negative": ["철근 누락", "부실시공", "붕괴", "하자", "국토부 감사", "영업정지", "PF 부실"],
    },
    "반도체": {
        "positive": ["HBM 수주", "엔비디아 공급", "장비 발주", "수율 개선", "실적 서프라이즈", "AI 투자 확대"],
        "negative": ["어닝 쇼크", "컨센서스 하회", "수출 통제", "재고 급증", "고객사 발주 축소", "마진 하락"],
    },
    "전력": {
        "positive": ["전력망 투자", "변압기 수주", "데이터센터 전력", "송전망 증설", "해외 공급계약"],
        "negative": ["정책 지연", "원가 상승", "납기 지연", "안전사고", "수주 취소"],
    },
    "원전": {
        "positive": ["SMR 수주", "원전 수출", "신규 원전", "정부 지원", "정책 승인"],
        "negative": ["정책 지연", "인허가 지연", "안전 규제", "수주 취소", "원전 사고"],
    },
    "전선": {
        "positive": ["해저케이블 수주", "전력망 투자", "구리 가격 상승 수혜", "북미 수주", "데이터센터 전력"],
        "negative": ["구리 원가 급등", "공급 지연", "마진 하락", "수주 취소", "납기 지연"],
    },
    "로봇": {
        "positive": ["대기업 투자", "로봇 공급계약", "자동화 수요", "감속기 수주", "휴머노이드"],
        "negative": ["실적 부진", "수주 지연", "경쟁 심화", "적자 확대", "투자 축소"],
    },
    "의료": {
        "positive": ["FDA 승인", "임상 성공", "기술수출", "품목허가", "보험급여"],
        "negative": ["임상 실패", "허가 지연", "부작용", "소송", "판매 중단"],
    },
    "제약": {
        "positive": ["FDA 승인", "임상 성공", "기술수출", "신약 허가", "마일스톤 수령"],
        "negative": ["임상 실패", "허가 반려", "부작용", "특허 소송", "약가 인하"],
    },
    "조선": {
        "positive": ["LNG선 수주", "선가 상승", "흑자 전환", "해양플랜트 수주", "수주잔고 증가"],
        "negative": ["인도 지연", "원가 상승", "노사 갈등", "수주 취소", "충당금"],
    },
    "해운": {
        "positive": ["운임 상승", "물동량 증가", "홍해 리스크", "컨테이너 강세", "장기계약"],
        "negative": ["운임 하락", "물동량 감소", "선복 과잉", "제재", "항만 지연"],
    },
    "증권": {
        "positive": ["거래대금 증가", "금리 인하", "IB 회복", "자사주", "배당 확대"],
        "negative": ["부동산PF 손실", "충당금", "순매도", "IB 부진", "규제"],
    },
    "은행": {
        "positive": ["금리 수혜", "배당 확대", "자사주", "충당금 감소", "NIM 개선"],
        "negative": ["연체율 상승", "충당금 증가", "부실채권", "규제", "PF 손실"],
    },
    "자동차": {
        "positive": ["판매 증가", "환율 수혜", "신차 효과", "전기차 보조금", "미국 판매 호조"],
        "negative": ["리콜", "파업", "관세", "판매 부진", "원가 상승"],
    },
    "2차전지": {
        "positive": ["수주", "IRA 수혜", "리튬 가격 안정", "흑자 전환", "공장 가동률 상승"],
        "negative": ["화재", "리콜", "수요 둔화", "적자 확대", "공급과잉", "가동률 하락"],
    },
    "통신": {
        "positive": ["요금제 개편", "AI 데이터센터", "주주환원", "5G 투자", "자회사 상장"],
        "negative": ["과징금", "해킹", "통신 장애", "규제", "가입자 감소"],
    },
    "에너지": {
        "positive": ["유가 상승", "가스 가격 상승", "정책 지원", "수소 투자", "전력 수요 증가"],
        "negative": ["유가 급락", "정제마진 하락", "환경 규제", "사고", "수요 둔화"],
    },
    "음식료": {
        "positive": ["가격 인상", "수출 증가", "K푸드", "마진 개선", "실적 서프라이즈"],
        "negative": ["원가 상승", "리콜", "식품 사고", "소비 둔화", "환율 부담"],
    },
    "게임": {
        "positive": ["신작 흥행", "중국 판호", "글로벌 출시", "매출 순위 상승", "IP 확장"],
        "negative": ["신작 부진", "출시 연기", "규제", "매출 하락", "운영 논란"],
    },
    "금융": {
        "positive": ["금리 수혜", "주주환원", "배당 확대", "자사주", "실적 개선"],
        "negative": ["PF 손실", "충당금", "연체율", "규제", "순매도"],
    },
}


def normalize_sector_name(sector: str) -> str:
    clean = str(sector or "").strip()
    for prefix in ["국장/", "미장/", "캐나다/", "KR/", "US/", "CA/"]:
        clean = clean.replace(prefix, "")
    first = clean.replace("·", "/").replace(",", "/").split("/")[0].strip()
    return first or "기타"


def get_sector_keyword_profile(sector: str) -> dict[str, list[str]]:
    base = normalize_sector_name(sector)
    if base in SECTOR_KEYWORD_PROFILES:
        return SECTOR_KEYWORD_PROFILES[base]
    for key, profile in SECTOR_KEYWORD_PROFILES.items():
        if key in base or base in key:
            return profile
    return {"positive": ["수주", "계약", "실적 개선", "정책 수혜"], "negative": ["실적 부진", "규제", "원가 상승", "수요 둔화"]}


def sector_keyword_text(sector: str) -> str:
    profile = get_sector_keyword_profile(sector)
    positive = ", ".join(profile["positive"][:4])
    negative = ", ".join(profile["negative"][:4])
    return f"최대 호재: {positive} / 최대 악재: {negative}"


def classify_sector_keyword_impact(sector: str, value: str) -> tuple[str, str]:
    profile = get_sector_keyword_profile(sector)
    text = str(value or "").lower()
    positive_hits = [word for word in profile["positive"] if word.lower() in text]
    negative_hits = [word for word in profile["negative"] if word.lower() in text]
    if negative_hits:
        return "sector_critical_bad", "섹터 최대 악재: " + ", ".join(negative_hits[:3])
    if positive_hits:
        return "sector_major_good", "섹터 최대 호재: " + ", ".join(positive_hits[:3])
    return "sector_neutral", sector_keyword_text(sector)
