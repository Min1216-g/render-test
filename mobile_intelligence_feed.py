#!/usr/bin/env python3

from __future__ import annotations

import json
import math
import hashlib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ops_guard import enforce_runtime_security
from news_impact_engine import analyze_news_impact, learned_keyword_summary, update_news_outcomes
from sector_keyword_profiles import classify_sector_keyword_impact, sector_keyword_text

try:
    from ai_failure_memory import failure_adjustment_for
except Exception:
    def failure_adjustment_for(name, ticker, market, sector):
        return 0, ""


BASE_DIR = Path(__file__).resolve().parent
MARKET_RESULTS = BASE_DIR / "market_scanner_results.csv"
QUIET_RESULTS = BASE_DIR / "quiet_money_results.csv"
NEWS_RESULTS = BASE_DIR / "news_pulse_results.csv"
IOS_RESULTS = BASE_DIR / "MarketScannerIOS" / "MarketScannerIOS" / "market_scanner_results.csv"
TRENDLINE_STATE_FILE = BASE_DIR / "mobile_trendline_state.json"
NEWS_IMPACT_STATE_FILE = BASE_DIR / "mobile_news_impact_state.json"
ADAPTIVE_NEWS_STATE_FILE = BASE_DIR / "adaptive_news_impact_state.json"
VANCOUVER_TZ = ZoneInfo("America/Vancouver")
MIN_TOTAL_ROWS_FOR_APP_SYNC = 500
MIN_OK_ROWS_FOR_APP_SYNC = 50


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig").fillna("")
    except Exception:
        return pd.DataFrame()


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()[:16]


def number(value, default: float = 0.0) -> float:
    try:
        if value == "":
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except Exception:
        return default


def text(row: pd.Series, key: str) -> str:
    return str(row.get(key, "") or "").strip()


def market_text(row: pd.Series) -> str:
    market = text(row, "market")
    ticker = text(row, "ticker")
    if market:
        return market
    if ticker.endswith((".KS", ".KQ")):
        return "국장"
    if ticker.endswith((".TO", ".V")):
        return "캐나다"
    return "미장"


def sector_key(value: str) -> str:
    clean = str(value or "").strip()
    for prefix in ["국장/", "미장/", "캐나다/", "KR/", "US/", "CA/"]:
        clean = clean.replace(prefix, "")
    return clean or "기타"


def contains_any(value: str, words: list[str]) -> bool:
    lower = value.lower()
    return any(word.lower() in lower for word in words)


def looks_mostly_english(value: str) -> bool:
    letters = [char for char in str(value or "") if char.isalpha()]
    if not letters:
        return False
    latin_count = sum(1 for char in letters if "A" <= char.upper() <= "Z")
    return latin_count / max(len(letters), 1) >= 0.55


def localize_news_text(value: str) -> str:
    text_value = str(value or "").strip()
    if not looks_mostly_english(text_value):
        return text_value

    lowered = text_value.lower()
    subjects = []
    for label, keys in [
        ("AST SpaceMobile", ["ast spacemobile", "asts"]),
        ("Rocket Lab", ["rocket lab", "rklb"]),
        ("Blue Origin", ["blue origin"]),
        ("SpaceX", ["spacex"]),
        ("Oracle", ["oracle", "orcl"]),
        ("Broadcom", ["broadcom", "avgo"]),
        ("Microsoft", ["microsoft", "msft"]),
        ("Nvidia", ["nvidia", "nvda"]),
    ]:
        if any(key in lowered for key in keys):
            subjects.append(label)
    subject_text = "/".join(subjects[:3]) if subjects else "해외 종목"

    signals = []
    if contains_any(lowered, ["rocket explosion", "blows up", "explosion"]):
        signals.append("로켓 폭발 여파")
    if contains_any(lowered, ["launch delay", "launch failure", "setback", "wrong orbit"]):
        signals.append("발사 지연/실패 우려")
    if contains_any(lowered, ["launch success", "successful launch", "nasa contract", "government contract", "starlink deal"]):
        signals.append("우주 계약/발사 성공 모멘텀")
    if contains_any(lowered, ["plunge", "tumble", "falls", "stocks fall", "sinks", "drops", "lower"]):
        signals.append("주가 하락 압력")
    if contains_any(lowered, ["downgrade", "cuts", "analyst", "target"]):
        signals.append("증권사 의견/목표가 이슈")
    if contains_any(lowered, ["earnings", "revenue", "profit", "guidance", "sales"]):
        signals.append("실적/가이던스 이슈")
    if contains_any(lowered, ["beats", "record", "growth", "surges", "jumps", "gains", "rises"]):
        signals.append("성장/상승 모멘텀")
    if contains_any(lowered, ["deal", "contract", "order", "acquisition", "merger"]):
        signals.append("계약/인수 이슈")
    if not signals:
        signals.append("해외 주요 뉴스")
    return f"{subject_text}: {' · '.join(signals[:3])}"


def build_sector_context(results: pd.DataFrame) -> dict[str, dict[str, object]]:
    if results.empty or "sector" not in results.columns:
        return {}

    rows = []
    for _, row in results.iterrows():
        if text(row, "status") and text(row, "status") != "ok":
            continue
        rows.append(
            {
                "market": market_text(row),
                "sector": sector_key(text(row, "sector")),
                "score": number(row.get("score")),
                "ai_score": number(row.get("ai_score")),
                "change": number(row.get("change_pct")),
                "volume": number(row.get("volume_ratio"), 1),
                "trade": number(row.get("trade_value_ratio"), 1),
                "risk": number(row.get("risk")),
                "name": text(row, "name"),
                "ticker": text(row, "ticker"),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return {}

    context: dict[str, dict[str, object]] = {}
    for (market, sector), group in frame.groupby(["market", "sector"]):
        avg_change = float(group["change"].mean())
        avg_volume = float(group["volume"].mean())
        avg_trade = float(group["trade"].mean())
        avg_score = float(group[["score", "ai_score"]].max(axis=1).mean())
        avg_risk = float(group["risk"].mean())
        strength = avg_score * 0.45 + avg_change * 4 + math.log1p(max(avg_volume, 0)) * 18 + math.log1p(max(avg_trade, 0)) * 10 - avg_risk * 0.35
        leaders = (
            group.assign(rank_score=group[["score", "ai_score"]].max(axis=1) + group["volume"] * 4 + group["change"])
            .sort_values("rank_score", ascending=False)
            .head(3)
        )
        context[f"{market}|{sector}"] = {
            "strength": strength,
            "avg_change": avg_change,
            "avg_volume": avg_volume,
            "leaders": [str(name) for name in leaders["name"].tolist() if str(name).strip()],
        }
    return context


def build_market_risk_context(results: pd.DataFrame) -> dict[str, str]:
    context: dict[str, str] = {}
    if results.empty:
        return context

    for market, group in results.groupby(results.apply(market_text, axis=1)):
        changes = group.get("change_pct", pd.Series(dtype=float)).apply(number)
        risks = group.get("risk", pd.Series(dtype=float)).apply(number)
        down_ratio = float((changes < 0).mean()) if len(changes) else 0
        avg_change = float(changes.mean()) if len(changes) else 0
        avg_risk = float(risks.mean()) if len(risks) else 0
        if down_ratio >= 0.62 or avg_change <= -1.2 or avg_risk >= 45:
            mode = "방어장"
            cash = "현금 비중 높게"
        elif down_ratio <= 0.42 and avg_change >= 0.5:
            mode = "공격장"
            cash = "관심 종목 압축"
        else:
            mode = "중립장"
            cash = "분할 접근"
        context[str(market)] = f"{mode} · 평균 {avg_change:+.2f}% · 하락비중 {down_ratio * 100:.0f}% · {cash}"
    return context


def news_lookup(news: pd.DataFrame) -> dict[str, str]:
    if news.empty:
        return {}
    mapping: dict[str, str] = {}
    for _, row in news.iterrows():
        name = text(row, "name")
        if not name:
            continue
        sentiment = text(row, "headline_sentiment") or text(row, "sentiment_summary")
        headline = localize_news_text(text(row, "headline"))
        published = text(row, "published_at")
        summary = " · ".join(part for part in [sentiment, headline, published] if part)
        if summary:
            mapping[name] = summary[:180]
    return mapping


def quiet_lookup(quiet: pd.DataFrame) -> dict[str, str]:
    if quiet.empty:
        return {}
    mapping: dict[str, str] = {}
    for _, row in quiet.iterrows():
        ticker = text(row, "ticker")
        if not ticker:
            continue
        status = text(row, "status")
        reason = text(row, "reasons")
        score = number(row.get("score"))
        mapping[ticker] = f"조용한 자금 후보 · {status or '관찰'} · 점수 {score:.0f} · {reason[:90]}"
    return mapping


def theme_chain(row: pd.Series) -> str:
    value = f"{text(row, 'name')} {text(row, 'sector')} {text(row, 'news_one_line')}".lower()
    chains = [
        (["반도체", "hbm", "nvda", "엔비디아"], "AI/반도체 → 전력 → 냉각 → 데이터센터 → 광통신"),
        (["전력", "변압", "전선", "구리"], "전력 → 전선 → 구리 → 원전/데이터센터"),
        (["원전", "smr", "원자력"], "원전 → 기자재 → 전력기기 → 방사선/검사"),
        (["로봇", "automation"], "로봇 → 감속기 → 자동화 장비 → 센서"),
        (["의료", "바이오", "제약"], "의료/제약 → 임상/승인 → 장비/소모품"),
        (["우주", "space", "항공"], "우주항공 → 위성 → 통신장비 → 소재"),
        (["건설", "시멘트", "철근"], "건설 → 건자재 → 철근/시멘트 → 리츠"),
    ]
    for words, chain in chains:
        if contains_any(value, words):
            return chain
    return "대표 테마 연결 대기"


def today_score(row: pd.Series, sector_context: dict[str, dict[str, object]]) -> int:
    ai_score = max(number(row.get("ai_score")), number(row.get("score")))
    volume = number(row.get("volume_ratio"), 1)
    change = number(row.get("change_pct"))
    risk = number(row.get("risk"))
    news_text = f"{text(row, 'news')} {text(row, 'news_one_line')} {text(row, 'headlines')}"
    sector = sector_context.get(f"{market_text(row)}|{sector_key(text(row, 'sector'))}", {})
    sector_strength = float(sector.get("strength", 0))

    score = ai_score * 0.45
    score += min(max(volume, 0), 6) * 7
    score += min(max(sector_strength, 0), 35) * 0.65
    if contains_any(news_text, ["호재", "계약", "수주", "승인", "흑자", "실적", "공급"]):
        score += 13
    if contains_any(news_text, ["악재", "어닝쇼크", "철근", "누락", "소송", "적자", "급락"]):
        score -= 14
    keyword_level, _ = classify_sector_keyword_impact(text(row, "sector"), news_text)
    if keyword_level == "sector_critical_bad":
        score -= 18
    elif keyword_level == "sector_major_good":
        score += 14
    if 0 <= change <= 3.8:
        score += 8
    if change >= 6:
        score -= 18
    score -= min(risk, 55) * 0.22
    return int(max(0, min(99, round(score))))


def lead_signal(row: pd.Series, score: int, quiet_text: str) -> str:
    change = number(row.get("change_pct"))
    volume = number(row.get("volume_ratio"), 1)
    if quiet_text:
        return quiet_text
    if -2 <= change <= 3 and 1.15 <= volume <= 3.2 and score >= 62:
        return f"선행 탐지 · 아직 덜 올랐고 거래량 {volume:.1f}배가 먼저 붙는 중"
    if change > 5:
        return "추격 주의 · 이미 오른 구간이라 눌림 확인 우선"
    return "선행 신호 대기"


def risk_signal(row: pd.Series, market_risk: str) -> str:
    risk_text = f"{text(row, 'risks')} {text(row, 'news')} {text(row, 'news_one_line')}"
    keyword_level, keyword_message = classify_sector_keyword_impact(text(row, "sector"), risk_text)
    if keyword_level == "sector_critical_bad":
        return keyword_message
    change = number(row.get("change_pct"))
    volume = number(row.get("volume_ratio"), 1)
    if contains_any(risk_text, ["철근", "누락", "부실", "어닝쇼크", "적자", "소송", "전환사채"]):
        return "중대 리스크 · 악재 뉴스 우선 확인"
    if change <= -4 and volume >= 1.4:
        return f"급락 위험 · 거래량 {volume:.1f}배 동반 하락"
    if "방어장" in market_risk:
        return "시장 방어장 · 신규 매수는 작게"
    return "위험 신호 보통"


def breaking_signal(row: pd.Series) -> str:
    volume = number(row.get("volume_ratio"), 1)
    change = number(row.get("change_pct"))
    news_line = text(row, "news_one_line")
    if volume >= 5:
        return f"이상 거래 · 거래량 {volume:.1f}배 급증"
    if abs(change) >= 6:
        return f"급변 감지 · 당일 {change:+.2f}%"
    if news_line and volume >= 1.7:
        return "뉴스+거래량 동시 감지"
    return "급변 신호 없음"


def position_signal(row: pd.Series) -> str:
    price = number(row.get("price"))
    atr = max(3.0, min(12.0, number(row.get("atr_pct"), 5)))
    if price <= 0:
        return "포지션 기준가 대기"
    stop = price * (1 - atr / 100)
    take = price * (1 + max(4.0, atr * 1.25) / 100)
    return f"기준 현재가 {price:,.0f} · 손절 참고 {stop:,.0f} · 1차 익절 참고 {take:,.0f}"


def format_price(value: float, market: str) -> str:
    if market == "국장":
        return f"{value:,.0f}원"
    currency = "CAD" if market == "캐나다" else "USD"
    return f"{value:,.2f} {currency}"


def fixed_trendline_levels(row: pd.Series, state: dict, generated_at: datetime) -> dict[str, object]:
    ticker = text(row, "ticker")
    price = number(row.get("price"))
    if not ticker or price <= 0:
        return {
            "up": 0.0,
            "down": 0.0,
            "anchor": 0.0,
            "date": "",
            "reason": "현재가 확인 대기",
        }

    today_key = generated_at.strftime("%Y-%m-%d")
    saved = state.get(ticker, {})
    saved_date = str(saved.get("date", ""))
    saved_up = number(saved.get("up"))
    saved_down = number(saved.get("down"))
    saved_anchor = number(saved.get("anchor_price"))

    crossed_up = saved_up > 0 and price >= saved_up
    crossed_down = saved_down > 0 and price <= saved_down
    should_reset = (
        saved_date != today_key
        or saved_up <= 0
        or saved_down <= 0
        or crossed_up
        or crossed_down
    )

    if not should_reset:
        return {
            "up": saved_up,
            "down": saved_down,
            "anchor": saved_anchor or price,
            "date": saved_date,
            "reason": "당일 고정",
        }

    atr = number(row.get("atr_pct"), 0)
    change = number(row.get("change_pct"))
    intraday_score = number(row.get("intraday_1m_score"))
    up_basis = atr * 0.45 if atr > 0 else 1.6
    down_basis = atr * 0.40 if atr > 0 else 1.4
    up_percent = max(1.2, min(5.5, up_basis + max(0, change) * 0.08))
    down_percent = max(1.0, min(5.0, down_basis + max(0, -change) * 0.08))
    if intraday_score >= 10:
        up_percent -= 0.25
    if intraday_score <= -8:
        down_percent -= 0.25
    up_percent = max(0.8, up_percent)
    down_percent = max(0.8, down_percent)
    up = price * (1 + up_percent / 100)
    down = price * (1 - down_percent / 100)

    if saved_date != today_key:
        reason = "새 거래일 기준 재설정"
    elif crossed_up:
        reason = "상단 돌파 후 재설정"
    elif crossed_down:
        reason = "하단 이탈 후 재설정"
    else:
        reason = "당일 기준 생성"

    state[ticker] = {
        "date": today_key,
        "anchor_price": round(price, 4),
        "up": round(up, 4),
        "down": round(down, 4),
        "reason": reason,
        "updated_at": generated_at.isoformat(),
    }
    return {
        "up": up,
        "down": down,
        "anchor": price,
        "date": today_key,
        "reason": reason,
    }


def news_impact_key(row: pd.Series, news_text: str) -> str:
    ticker = text(row, "ticker") or text(row, "name")
    headline = text(row, "headlines") or text(row, "news_one_line") or news_text
    primary = headline.split("|", 1)[0].strip()[:220]
    return stable_hash(f"{ticker}|{primary}")


def news_price_forecast(row: pd.Series, state: dict | None = None, generated_at: datetime | None = None) -> str:
    price = number(row.get("price"))
    if price <= 0:
        return "뉴스 영향 예상가: 현재가 확인 대기"

    market = market_text(row)
    news_text = f"{text(row, 'news')} {text(row, 'news_one_line')} {text(row, 'headlines')} {text(row, 'risks')}"
    if contains_any(news_text, ["최신 호재/악재 없음", "과거 뉴스 판단 제외", "과거 뉴스 · 판단 제외"]):
        return "뉴스 영향 예상: 최신 재료 없음 · 과거 뉴스는 판단 제외"

    keyword_level, keyword_message = classify_sector_keyword_impact(text(row, "sector"), news_text)
    atr = max(2.5, min(12.0, number(row.get("atr_pct"), 5.0)))
    volume = max(0.5, min(5.0, number(row.get("volume_ratio"), 1.0)))
    change = number(row.get("change_pct"))
    risk = number(row.get("risk"))

    bad = (
        keyword_level == "sector_critical_bad"
        or contains_any(news_text, ["중대 악재", "악재", "철근", "누락", "부실", "어닝쇼크", "실적 쇼크", "소송", "적자", "launch failure", "launch delay", "rocket explosion", "starship failure", "falcon 9 failure"])
    )
    good = (
        keyword_level == "sector_major_good"
        or contains_any(news_text, ["강한 호재", "호재", "수주", "계약", "승인", "흑자", "실적 서프라이즈", "공급", "launch success", "successful launch", "nasa contract", "government contract", "starlink contract", "starlink deal"])
    )

    if not bad and not good:
        return "뉴스 영향 예상: 방향성 약함 · 가격/거래량 확인 우선"

    state = state if state is not None else {}
    forecast_key = news_impact_key(row, news_text)
    saved = state.get(forecast_key)
    if isinstance(saved, dict) and saved.get("forecast"):
        return saved["forecast"]

    if bad:
        shock_pct = atr * (1.0 + min(risk, 50) / 100) + max(0, volume - 1) * 1.2
        if contains_any(news_text, ["철근", "누락", "붕괴", "부실시공", "영업정지"]):
            shock_pct += 4.0
        if change <= -5:
            shock_pct *= 0.85
        low_pct = max(3.0, min(18.0, shock_pct * 0.55))
        high_pct = max(low_pct + 1.5, min(28.0, shock_pct))
        low_price = price * (1 - high_pct / 100)
        rebound_line = price * (1 + max(2.0, atr * 0.45) / 100)
        forecast = (
            f"악재 영향 예상: -{low_pct:.1f}~-{high_pct:.1f}% "
            f"({format_price(low_price, market)} 부근까지 경계) · 회복 기준 {format_price(rebound_line, market)} 돌파"
            f" · 최초예측 고정 {price:,.0f} 기준"
        )
        state[forecast_key] = {
            "ticker": text(row, "ticker"),
            "name": text(row, "name"),
            "type": "bad",
            "base_price": round(price, 4),
            "low_pct": round(low_pct, 2),
            "high_pct": round(high_pct, 2),
            "forecast": forecast,
            "headline": (text(row, "headlines") or text(row, "news_one_line"))[:240],
            "created_at": (generated_at or datetime.now(VANCOUVER_TZ)).isoformat(),
        }
        return forecast

    if good:
        upside_pct = atr * 0.75 + max(0, volume - 1) * 1.4
        if keyword_level == "sector_major_good" or contains_any(news_text, ["수주", "계약", "승인", "흑자"]):
            upside_pct += 3.0
        if change >= 6:
            upside_pct *= 0.7
        low_pct = max(2.0, min(12.0, upside_pct * 0.55))
        high_pct = max(low_pct + 1.2, min(22.0, upside_pct))
        high_price = price * (1 + high_pct / 100)
        fail_line = price * (1 - max(2.0, atr * 0.45) / 100)
        forecast = (
            f"호재 영향 예상: +{low_pct:.1f}~+{high_pct:.1f}% "
            f"({format_price(high_price, market)} 부근까지 시도) · 이탈 기준 {format_price(fail_line, market)}"
            f" · 최초예측 고정 {price:,.0f} 기준"
        )
        state[forecast_key] = {
            "ticker": text(row, "ticker"),
            "name": text(row, "name"),
            "type": "good",
            "base_price": round(price, 4),
            "low_pct": round(low_pct, 2),
            "high_pct": round(high_pct, 2),
            "forecast": forecast,
            "headline": (text(row, "headlines") or text(row, "news_one_line"))[:240],
            "created_at": (generated_at or datetime.now(VANCOUVER_TZ)).isoformat(),
        }
        return forecast

    return "뉴스 영향 예상: 방향성 약함 · 가격/거래량 확인 우선"


def adaptive_news_impact(row: pd.Series, news_text: str, state: dict, generated_at: datetime) -> dict:
    return analyze_news_impact(
        name=text(row, "name"),
        ticker=text(row, "ticker"),
        market=market_text(row),
        sector=text(row, "sector"),
        news_text=f"{news_text} {text(row, 'news')} {text(row, 'news_one_line')} {text(row, 'headlines')} {text(row, 'risks')}",
        price=number(row.get("price")),
        change_pct=number(row.get("change_pct")),
        volume_ratio=number(row.get("volume_ratio"), 1.0),
        risk=number(row.get("risk")),
        now=generated_at,
        state=state,
    )


def explain_signal(row: pd.Series, score: int, sector_signal: str, news_text: str) -> str:
    parts = []
    volume = number(row.get("volume_ratio"), 1)
    change = number(row.get("change_pct"))
    if score >= 80:
        parts.append("우선 감시")
    elif score >= 65:
        parts.append("관심")
    else:
        parts.append("관망")
    if volume >= 1.2:
        parts.append(f"거래량 {volume:.1f}배")
    if -1 <= change <= 3.5:
        parts.append("추격 부담 낮음")
    elif change > 5:
        parts.append("추격 부담 높음")
    if news_text:
        parts.append(news_text[:70])
    elif sector_signal:
        parts.append(sector_signal[:70])
    failure_adjustment, failure_reason = failure_adjustment_for(
        text(row, "name"),
        text(row, "ticker"),
        market_text(row),
        text(row, "sector"),
    )
    if failure_reason:
        if failure_adjustment < 0:
            parts.append(f"실패 복기 감점: {failure_reason}")
        else:
            parts.append(f"놓친 상승 복기: {failure_reason}")
    return " · ".join(parts)


def sector_keyword_signal(row: pd.Series) -> str:
    sector = text(row, "sector")
    news_text = f"{text(row, 'news')} {text(row, 'news_one_line')} {text(row, 'headlines')} {text(row, 'risks')}"
    _, message = classify_sector_keyword_impact(sector, news_text)
    return message or sector_keyword_text(sector)


def enrich() -> int:
    enforce_runtime_security(BASE_DIR, output_files=[MARKET_RESULTS, IOS_RESULTS])
    results = read_csv(MARKET_RESULTS)
    if results.empty:
        print("[mobile-intel] market_scanner_results.csv 없음")
        return 1
    ok_rows = int((results.get("status", "") == "ok").sum()) if "status" in results.columns else len(results)
    if len(results) < MIN_TOTAL_ROWS_FOR_APP_SYNC:
        print(f"[mobile-intel] 앱 CSV 갱신 차단: 종목 {len(results)}개, 최소 {MIN_TOTAL_ROWS_FOR_APP_SYNC}개 필요")
        return 1
    if ok_rows < MIN_OK_ROWS_FOR_APP_SYNC:
        print(f"[mobile-intel] 앱 CSV 갱신 차단: 정상 분석 {ok_rows}개, 네트워크/데이터 실패 가능")
        return 1

    quiet = read_csv(QUIET_RESULTS)
    news = read_csv(NEWS_RESULTS)
    sectors = build_sector_context(results)
    market_risks = build_market_risk_context(results)
    news_map = news_lookup(news)
    quiet_map = quiet_lookup(quiet)
    generated_dt = datetime.now(VANCOUVER_TZ)
    generated_at = generated_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    trendline_state = load_json(TRENDLINE_STATE_FILE)
    news_impact_state = load_json(NEWS_IMPACT_STATE_FILE)
    adaptive_news_state = load_json(ADAPTIVE_NEWS_STATE_FILE)
    update_news_outcomes(results.to_dict("records"), adaptive_news_state, generated_dt.replace(tzinfo=None))

    enriched_rows = []
    for _, row in results.iterrows():
        row = row.copy()
        market = market_text(row)
        sector = sector_key(text(row, "sector"))
        sector_info = sectors.get(f"{market}|{sector}", {})
        leaders = ", ".join(sector_info.get("leaders", []) or [])
        avg_change = float(sector_info.get("avg_change", 0))
        avg_volume = float(sector_info.get("avg_volume", 0))
        sector_signal = f"{sector} 흐름 · 평균 {avg_change:+.2f}% · 거래량 {avg_volume:.1f}배"
        if leaders:
            sector_signal += f" · 대표 {leaders}"

        market_risk = market_risks.get(market, "시장 위험도 계산 대기")
        quiet_text = quiet_map.get(text(row, "ticker"), "")
        news_text = news_map.get(text(row, "name"), text(row, "news_one_line"))
        news_impact = adaptive_news_impact(row, news_text, adaptive_news_state, generated_dt.replace(tzinfo=None))
        score = today_score(row, sectors)
        trendline = fixed_trendline_levels(row, trendline_state, generated_dt)

        row["mobile_intel_generated_at"] = generated_at
        row["mobile_today_score"] = score
        row["mobile_ai_explain"] = explain_signal(row, score, sector_signal, news_text)
        row["mobile_lead_signal"] = lead_signal(row, score, quiet_text)
        row["mobile_missed_signal"] = "놓칠 가능성 높음" if number(row.get("volume_ratio"), 1) >= 1.8 and number(row.get("change_pct")) < 3 else "놓침 위험 낮음"
        row["mobile_risk_signal"] = risk_signal(row, market_risk)
        row["mobile_breaking_signal"] = breaking_signal(row)
        row["mobile_sector_rotation"] = sector_signal
        row["mobile_market_risk"] = market_risk
        row["mobile_capital_flow"] = text(row, "flow") or text(row, "flow_status") or "수급 확인 대기"
        row["mobile_theme_link"] = theme_chain(row)
        row["mobile_position_ai"] = position_signal(row)
        row["mobile_sector_keywords"] = sector_keyword_signal(row)
        row["mobile_news_price_forecast"] = news_price_forecast(row, news_impact_state, generated_dt)
        row["mobile_news_impact_label"] = news_impact["label"]
        row["mobile_news_impact_score"] = news_impact["impact_score"]
        row["mobile_news_confidence"] = news_impact["confidence"]
        row["mobile_news_basis"] = news_impact["basis"]
        row["mobile_news_similar"] = news_impact["similar"]
        row["mobile_news_expectation"] = news_impact["expectation"]
        row["mobile_news_impact_summary"] = news_impact["summary"]
        row["mobile_news_learned_keywords"] = learned_keyword_summary(adaptive_news_state)
        row["mobile_news_focus"] = " · ".join(part for part in [news_text, row["mobile_sector_keywords"]] if part) or "주요 뉴스 대기"
        row["mobile_news_v2_strength"] = news_impact.get("v2_strength", 0)
        row["mobile_news_v2_duration"] = news_impact.get("v2_duration", "")
        row["mobile_news_v2_market_reaction"] = news_impact.get("v2_market_reaction", "")
        row["mobile_news_v2_positive_factors"] = news_impact.get("v2_positive_factors", "")
        row["mobile_news_v2_negative_factors"] = news_impact.get("v2_negative_factors", "")
        row["mobile_news_v2_short_effect"] = news_impact.get("v2_short_effect", 0)
        row["mobile_news_v2_mid_effect"] = news_impact.get("v2_mid_effect", 0)
        row["mobile_news_v2_long_effect"] = news_impact.get("v2_long_effect", 0)
        row["mobile_news_v2_sector_impact"] = news_impact.get("v2_sector_impact", "")
        row["mobile_news_v2_lead_status"] = news_impact.get("v2_lead_status", "")
        row["mobile_news_v2_core_signal"] = news_impact.get("v2_core_signal", "")
        row["mobile_news_v2_final_signal"] = news_impact.get("v2_final_signal", "")
        row["mobile_news_v2_confidence_grade"] = news_impact.get("v2_confidence_grade", "")
        row["mobile_news_v2_policy_flags"] = news_impact.get("v2_policy_flags", "")
        row["mobile_news_grade"] = news_impact.get("news_grade", "")
        row["mobile_news_type"] = news_impact.get("news_type", "")
        row["mobile_news_good_score"] = news_impact.get("good_score", 0)
        row["mobile_news_bad_score"] = news_impact.get("bad_score", 0)
        row["mobile_news_impact_strength_label"] = news_impact.get("impact_strength_label", "")
        row["mobile_news_leading_detection"] = news_impact.get("leading_detection", "")
        row["mobile_trendline_anchor_date"] = trendline["date"]
        row["mobile_trendline_anchor_price"] = round(float(trendline["anchor"]), 4)
        row["mobile_trendline_up"] = round(float(trendline["up"]), 4)
        row["mobile_trendline_down"] = round(float(trendline["down"]), 4)
        row["mobile_trendline_status"] = trendline["reason"]
        enriched_rows.append(row)

    enriched = pd.DataFrame(enriched_rows)
    enriched.to_csv(MARKET_RESULTS, index=False, encoding="utf-8-sig")
    IOS_RESULTS.parent.mkdir(parents=True, exist_ok=True)
    enriched.to_csv(IOS_RESULTS, index=False, encoding="utf-8-sig")
    save_json(TRENDLINE_STATE_FILE, trendline_state)
    save_json(NEWS_IMPACT_STATE_FILE, news_impact_state)
    save_json(ADAPTIVE_NEWS_STATE_FILE, adaptive_news_state)
    enforce_runtime_security(BASE_DIR, output_files=[MARKET_RESULTS, IOS_RESULTS])
    print(f"[mobile-intel] enriched {len(enriched)} rows -> {MARKET_RESULTS.name}, iOS csv")
    return 0


if __name__ == "__main__":
    raise SystemExit(enrich())
