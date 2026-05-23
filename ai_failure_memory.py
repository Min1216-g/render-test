#!/usr/bin/env python3

from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from ops_guard import enforce_runtime_security, secure_file_permissions


BASE_DIR = Path(__file__).resolve().parent
RESULT_FILE = BASE_DIR / "market_scanner_results.csv"
MEMORY_FILE = BASE_DIR / "ai_failure_memory.json"
REPORT_FILE = BASE_DIR / "ai_failure_memory.csv"
VANCOUVER_TZ = ZoneInfo("America/Vancouver")

FALSE_POSITIVE_DROP_PCT = -4.0
FALSE_NEGATIVE_RISE_PCT = 7.0
CHASE_AFTER_RISE_PCT = 6.0
MIN_AI_SCORE_FOR_REVIEW = 72


def number(value, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        if isinstance(value, str):
            value = value.replace(",", "").replace("%", "").strip()
        return float(value)
    except Exception:
        return default


def clean_text(value) -> str:
    return str(value or "").strip()


def contains_any(text: str, words: list[str]) -> bool:
    lower = text.lower()
    return any(word.lower() in lower for word in words)


def classify_failure(row: pd.Series) -> tuple[str, str, int] | None:
    ai_label = clean_text(row.get("ai_label"))
    ai_score = number(row.get("ai_score"))
    action = clean_text(row.get("action"))
    change_pct = number(row.get("change_pct"))
    risk = number(row.get("risk"))
    volume_ratio = number(row.get("volume_ratio"), 1)
    rsi = number(row.get("rsi"), 50)
    trade_value_ratio = number(row.get("trade_value_ratio"), 1)
    news_blob = " ".join(
        clean_text(row.get(key))
        for key in ["news", "news_one_line", "headlines", "risks", "mobile_news_focus"]
    )

    recommended = "추천" in ai_label or "관심" in ai_label or action in {"🔥 강력 관심", "👍 관심"}
    ignored = "관망" in ai_label or action in {"보류", "대기"}

    if recommended and change_pct <= FALSE_POSITIVE_DROP_PCT:
        reasons = []
        penalty = -8
        if risk >= 25:
            reasons.append("리스크 과다를 과소평가")
            penalty -= 4
        if volume_ratio >= 2.5:
            reasons.append("거래량 급증 후 되돌림")
            penalty -= 4
        if trade_value_ratio < 0.8:
            reasons.append("거래대금 확인 부족")
            penalty -= 3
        if contains_any(news_blob, ["악재", "철근", "누락", "쇼크", "급락", "소송", "적자", "하락"]):
            reasons.append("악재 뉴스 반영 부족")
            penalty -= 5
        if rsi >= 70:
            reasons.append("과열 구간 추격")
            penalty -= 4
        return "false_positive_drop", " · ".join(reasons) or "추천 후 가격이 크게 역방향", max(-24, penalty)

    if recommended and change_pct >= CHASE_AFTER_RISE_PCT and (volume_ratio >= 2.0 or rsi >= 68):
        reasons = ["이미 오른 뒤 추천"]
        penalty = -10
        if volume_ratio >= 3:
            reasons.append("거래량 폭발 후 추격 위험")
            penalty -= 4
        if rsi >= 72:
            reasons.append("RSI 과열")
            penalty -= 4
        return "late_chase", " · ".join(reasons), max(-20, penalty)

    if ignored and ai_score < MIN_AI_SCORE_FOR_REVIEW and change_pct >= FALSE_NEGATIVE_RISE_PCT:
        reasons = []
        penalty = 6
        if 1.2 <= volume_ratio <= 3.0:
            reasons.append("초기 거래량을 낮게 평가")
            penalty += 3
        if contains_any(news_blob, ["수주", "계약", "공급", "승인", "실적", "흑자", "투자"]):
            reasons.append("호재 뉴스 반영 부족")
            penalty += 4
        if 40 <= rsi <= 68:
            reasons.append("초기 추세 구간을 놓침")
            penalty += 3
        return "false_negative_missed_rise", " · ".join(reasons) or "관망 후 크게 상승", min(18, penalty)

    return None


def memory_key(row: pd.Series, failure_type: str) -> str:
    market = clean_text(row.get("market")) or "unknown"
    sector = clean_text(row.get("sector")) or "기타"
    return f"{market}|{sector}|{failure_type}"


def analyze_failures(result_file: Path = RESULT_FILE) -> tuple[list[dict[str, object]], dict[str, object]]:
    if not result_file.exists():
        return [], {"generated_at": datetime.now(VANCOUVER_TZ).isoformat(), "patterns": {}, "stocks": {}}

    df = pd.read_csv(result_file, encoding="utf-8-sig").fillna("")
    rows: list[dict[str, object]] = []
    pattern_counter: Counter[str] = Counter()
    pattern_penalty: defaultdict[str, list[int]] = defaultdict(list)
    stock_counter: Counter[str] = Counter()
    stock_adjustment: defaultdict[str, list[int]] = defaultdict(list)

    for _, row in df.iterrows():
        if clean_text(row.get("status")) and clean_text(row.get("status")) != "ok":
            continue
        classified = classify_failure(row)
        if not classified:
            continue
        failure_type, reason, penalty = classified
        key = memory_key(row, failure_type)
        ticker = clean_text(row.get("ticker"))
        name = clean_text(row.get("name"))
        pattern_counter[key] += 1
        pattern_penalty[key].append(penalty)
        if ticker:
            stock_counter[ticker] += 1
            stock_adjustment[ticker].append(penalty)
        rows.append(
            {
                "generated_at": datetime.now(VANCOUVER_TZ).strftime("%Y-%m-%d %H:%M:%S %Z"),
                "name": name,
                "ticker": ticker,
                "market": clean_text(row.get("market")),
                "sector": clean_text(row.get("sector")),
                "failure_type": failure_type,
                "change_pct": round(number(row.get("change_pct")), 2),
                "ai_label": clean_text(row.get("ai_label")),
                "ai_score": int(number(row.get("ai_score"))),
                "risk": int(number(row.get("risk"))),
                "volume_ratio": round(number(row.get("volume_ratio"), 1), 2),
                "rsi": round(number(row.get("rsi"), 50), 1),
                "reason": reason,
                "next_penalty": penalty,
            }
        )

    patterns = {}
    for key, count in pattern_counter.items():
        penalties = pattern_penalty[key]
        avg_penalty = int(round(sum(penalties) / max(1, len(penalties))))
        patterns[key] = {
            "count": count,
            "avg_penalty": avg_penalty,
            "last_seen": datetime.now(VANCOUVER_TZ).isoformat(),
        }

    memory = {
        "generated_at": datetime.now(VANCOUVER_TZ).isoformat(),
        "patterns": patterns,
        "stocks": {
            ticker: {
                "count": count,
                "avg_adjustment": int(round(sum(stock_adjustment[ticker]) / max(1, len(stock_adjustment[ticker])))),
                "last_seen": datetime.now(VANCOUVER_TZ).isoformat(),
            }
            for ticker, count in stock_counter.items()
        },
    }
    return rows, memory


def save_report(rows: list[dict[str, object]], memory: dict[str, object]) -> None:
    MEMORY_FILE.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")
    secure_file_permissions(MEMORY_FILE)

    fieldnames = [
        "generated_at",
        "name",
        "ticker",
        "market",
        "sector",
        "failure_type",
        "change_pct",
        "ai_label",
        "ai_score",
        "risk",
        "volume_ratio",
        "rsi",
        "reason",
        "next_penalty",
    ]
    with REPORT_FILE.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    secure_file_permissions(REPORT_FILE)


def load_memory() -> dict[str, object]:
    if not MEMORY_FILE.exists():
        return {"patterns": {}, "stocks": {}}
    try:
        return json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"patterns": {}, "stocks": {}}


def failure_adjustment_for(name: str, ticker: str, market: str, sector: str) -> tuple[int, str]:
    memory = load_memory()
    patterns = memory.get("patterns", {}) if isinstance(memory, dict) else {}
    stocks = memory.get("stocks", {}) if isinstance(memory, dict) else {}
    adjustments: list[tuple[int, str]] = []

    for failure_type, label in [
        ("false_positive_drop", "이전 추천 후 급락 패턴"),
        ("late_chase", "이전 추격 추천 패턴"),
        ("false_negative_missed_rise", "이전 놓친 상승 패턴"),
    ]:
        key = f"{market}|{sector}|{failure_type}"
        item = patterns.get(key, {}) if isinstance(patterns, dict) else {}
        count = int(item.get("count", 0) or 0)
        avg_penalty = int(item.get("avg_penalty", 0) or 0)
        if count > 0 and avg_penalty != 0:
            weight = min(1.0, math.log1p(count) / math.log(4))
            adjusted = int(round(avg_penalty * weight))
            adjustments.append((adjusted, f"{label} {count}회"))

    stock_item = stocks.get(ticker, {}) if isinstance(stocks, dict) else {}
    stock_count = int(stock_item.get("count", 0) or 0)
    if stock_count > 0:
        avg_adjustment = int(stock_item.get("avg_adjustment", 0) or 0)
        stock_adjusted = max(-8, min(8, avg_adjustment))
        if stock_adjusted:
            adjustments.append((stock_adjusted, f"{name} 개별 실패 복기 {stock_count}회"))

    if not adjustments:
        return 0, ""

    total = sum(value for value, _ in adjustments)
    total = max(-18, min(10, total))
    reason = " / ".join(reason for _, reason in adjustments[:3])
    return total, reason


def main() -> int:
    enforce_runtime_security(BASE_DIR, output_files=[MEMORY_FILE])
    rows, memory = analyze_failures()
    save_report(rows, memory)
    print(f"AI 실패 복기 완료: {len(rows)}개 패턴 후보")
    if rows:
        worst = sorted(rows, key=lambda item: abs(float(item["change_pct"])), reverse=True)[:5]
        for item in worst:
            print(f"- {item['name']} {item['change_pct']}% | {item['failure_type']} | {item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
