#!/usr/bin/env python3
"""Korean stock AI screening, backtest, and paper trading utilities.

This module is intentionally paper-trading only. It never connects to a
brokerage order endpoint and never creates real buy/sell orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import pandas as pd
except Exception:  # pragma: no cover - handled at runtime
    pd = None

try:
    import yfinance as yf
except Exception:  # pragma: no cover - handled at runtime
    yf = None


BASE_DIR = Path(__file__).resolve().parent
MARKET_RESULTS_FILE = BASE_DIR / "market_scanner_results.csv"
PROFILE_FILE = BASE_DIR / "ai_screening_profile.json"
SCREENING_RESULTS_FILE = BASE_DIR / "ai_screening_results.csv"
BACKTEST_RESULTS_FILE = BASE_DIR / "ai_screening_backtest_results.csv"
BACKTEST_TRADES_FILE = BASE_DIR / "ai_screening_backtest_trades.csv"
PAPER_ACCOUNT_FILE = BASE_DIR / "paper_trading_account.json"
PAPER_ACCOUNT_DIR = Path(os.getenv("MARKET_PAPER_TRADING_DIR", "/var/data" if os.getenv("RENDER") else str(BASE_DIR)))
RECOMMENDATION_HISTORY_FILE = BASE_DIR / "ai_recommendation_tracking.csv"
WEIGHT_HISTORY_FILE = BASE_DIR / "ai_signal_weight_history.csv"
EVENT_LOG_FILE = BASE_DIR / "ai_screening_event_log.jsonl"

SAFETY_NOTICE = (
    "실제 자동주문 없음 · 실제 매수/매도 버튼 없음 · 모든 거래는 모의투자 · "
    "수익 보장 아님 · 최종 투자 판단은 사용자 책임"
)

DEFAULT_SIGNAL_WEIGHTS = {
    "volume_surge": 12,
    "foreign_buy": 8,
    "institution_buy": 8,
    "pension_buy": 6,
    "rsi": 7,
    "macd": 7,
    "moving_average": 7,
    "new_high_breakout": 7,
    "box_breakout": 5,
    "pullback": 6,
    "ai_news_score": 12,
    "earnings_growth": 6,
    "short_covering": 5,
    "program_buy": 6,
    "etf_flow": 4,
    "market_mood": 6,
}

DEFAULT_PROFILE = {
    "preferred_industries": ["반도체", "전력", "원전", "우주항공", "방산"],
    "themes": ["AI", "전력망", "데이터센터", "원전", "우주항공"],
    "investment_style": "스윙",
    "max_stop_loss_pct": 7.0,
    "target_profit_pct": 15.0,
    "important_signals": list(DEFAULT_SIGNAL_WEIGHTS.keys()),
    "signal_weights": DEFAULT_SIGNAL_WEIGHTS,
    "min_ai_score": 55,
    "max_results": 50,
    "paper_initial_cash": 0.0,
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_event(event: str, **payload: object) -> None:
    row = {"at": utc_now_iso(), "event": event, **payload}
    with EVENT_LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_profile() -> Dict[str, object]:
    if not PROFILE_FILE.exists():
        save_profile(DEFAULT_PROFILE)
        return dict(DEFAULT_PROFILE)
    try:
        loaded = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        loaded = {}
    profile = dict(DEFAULT_PROFILE)
    profile.update({k: v for k, v in loaded.items() if v is not None})
    weights = dict(DEFAULT_SIGNAL_WEIGHTS)
    weights.update(profile.get("signal_weights") or {})
    profile["signal_weights"] = weights
    return profile


def save_profile(profile: Dict[str, object]) -> Dict[str, object]:
    clean = dict(DEFAULT_PROFILE)
    clean.update(profile)
    weights = dict(DEFAULT_SIGNAL_WEIGHTS)
    weights.update(clean.get("signal_weights") or {})
    clean["signal_weights"] = weights
    PROFILE_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    log_event("profile_saved", profile=clean)
    return clean


def as_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        text = str(value).replace(",", "").replace("%", "").strip()
        if not text or text.lower() in {"nan", "none", "null", "-"}:
            return default
        number = float(text)
        if math.isnan(number) or math.isinf(number):
            return default
        return number
    except (TypeError, ValueError):
        return default


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def read_market_rows() -> List[Dict[str, str]]:
    if not MARKET_RESULTS_FILE.exists():
        return []
    with MARKET_RESULTS_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def is_korean_stock(row: Dict[str, str]) -> bool:
    ticker = (row.get("ticker") or "").upper()
    market = row.get("market") or ""
    return "국장" in market or ticker.endswith(".KS") or ticker.endswith(".KQ")


def signal_scores(row: Dict[str, str]) -> Dict[str, Tuple[float, str]]:
    volume_ratio = as_float(row.get("volume_ratio"))
    trade_value_ratio = as_float(row.get("trade_value_ratio"))
    foreign_net = as_float(row.get("foreign_net"))
    institution_net = as_float(row.get("institution_net"))
    rsi = as_float(row.get("rsi"))
    ma20_gap = as_float(row.get("ma20_gap_pct"))
    news_score = as_float(row.get("mobile_news_impact_score"), as_float(row.get("news_score")))
    sector_score = as_float(row.get("sector_score"))
    score = as_float(row.get("score"))
    weekly_rsi = as_float(row.get("weekly_rsi"))
    change_pct = as_float(row.get("change_pct"))
    return_5d = as_float(row.get("return_5d_pct"))
    return_20d = as_float(row.get("return_20d_pct"))
    macd_bullish = str(row.get("macd_bullish", "")).lower() in {"true", "1", "yes"}
    patterns = row.get("patterns", "")
    reasons = row.get("reasons", "")
    flow = row.get("flow", "")
    flow_status = row.get("flow_status", "")
    market_regime = row.get("market_regime", "")
    contrarian = row.get("contrarian_signal", "")
    flow_unavailable = any(word in f"{flow} {flow_status}" for word in ("확인 불가", "수집 실패", "unavailable", "no_code"))

    scores = {
        "volume_surge": (clamp(45 + (volume_ratio - 1.0) * 25 + (trade_value_ratio - 1.0) * 12), f"거래량 {volume_ratio:.1f}배"),
        "foreign_buy": (50 if flow_unavailable else (100 if foreign_net > 0 else 25), "외국인 순매수" if foreign_net > 0 else ("외국인 수급 미수집" if flow_unavailable else "외국인 수급 약함")),
        "institution_buy": (50 if flow_unavailable else (100 if institution_net > 0 else 25), "기관 순매수" if institution_net > 0 else ("기관 수급 미수집" if flow_unavailable else "기관 수급 약함")),
        "pension_buy": (65 if "연기금" in flow and "매수" in flow else 50, "연기금 매수 확인" if "연기금" in flow and "매수" in flow else "연기금 신호 대기"),
        "rsi": (rsi_score(rsi, weekly_rsi), f"RSI {rsi:.1f} / 주봉 {weekly_rsi:.1f}"),
        "macd": (85 if macd_bullish else 25, "MACD 상승" if macd_bullish else "MACD 확인 필요"),
        "moving_average": (clamp(60 + ma20_gap * 2) if -3 <= ma20_gap <= 15 else clamp(40 - abs(ma20_gap)), f"20일선 괴리 {ma20_gap:.1f}%"),
        "new_high_breakout": (90 if "고점 돌파" in reasons or "신고가" in patterns else 45, "고점/신고가 돌파" if "고점 돌파" in reasons or "신고가" in patterns else "돌파 신호 대기"),
        "box_breakout": (80 if "박스" in patterns or "돌파" in reasons else 45, "박스권/저항 돌파" if "박스" in patterns or "돌파" in reasons else "박스 돌파 대기"),
        "pullback": (pullback_score(ma20_gap, change_pct, return_5d), "눌림목 후보" if -4 <= ma20_gap <= 4 and return_5d < 8 else "눌림 확인 필요"),
        "ai_news_score": (clamp(50 + news_score), f"AI 뉴스 영향 {news_score:+.0f}"),
        "earnings_growth": (75 if any(word in reasons + row.get("news", "") for word in ("실적", "흑자", "성장", "서프라이즈")) else 50, "실적/성장 키워드" if any(word in reasons + row.get("news", "") for word in ("실적", "흑자", "성장", "서프라이즈")) else "실적 신호 대기"),
        "short_covering": (65 if "공매도" in reasons and "감소" in reasons else 50, "공매도 감소" if "공매도" in reasons and "감소" in reasons else "공매도 감소 대기"),
        "program_buy": (70 if "프로그램" in flow and "매수" in flow else 50, "프로그램 매수" if "프로그램" in flow and "매수" in flow else "프로그램 매수 대기"),
        "etf_flow": (65 if "ETF" in flow or "etf" in flow.lower() else 50, "ETF 수급 참고" if "ETF" in flow or "etf" in flow.lower() else "ETF 수급 대기"),
        "market_mood": (market_mood_score(market_regime, contrarian, sector_score, score), f"{market_regime or '시장상태 대기'} / 섹터 {sector_score:.0f}"),
    }

    if return_20d > 35 and change_pct > 8:
        scores["market_mood"] = (max(0, scores["market_mood"][0] - 25), "단기 급등 추격위험 감점")
    return scores


def rsi_score(rsi: float, weekly_rsi: float) -> float:
    if weekly_rsi and weekly_rsi <= 20:
        return 100
    if weekly_rsi and weekly_rsi <= 25:
        return 92
    if weekly_rsi and weekly_rsi <= 30:
        return 82
    if 35 <= rsi <= 58:
        return 75
    if 58 < rsi <= 68:
        return 58
    if rsi > 72:
        return 22
    return 45


def pullback_score(ma20_gap: float, change_pct: float, return_5d: float) -> float:
    if -4 <= ma20_gap <= 4 and -3 <= change_pct <= 3:
        return 90
    if -6 <= ma20_gap <= 8 and return_5d < 10:
        return 68
    return 25


def market_mood_score(market_regime: str, contrarian: str, sector_score: float, base_score: float) -> float:
    value = 45 + sector_score * 0.35 + max(0, base_score - 50) * 0.3
    if "공포" in contrarian or "Fear" in contrarian:
        value += 12
    if "방어장" in market_regime:
        value -= 10
    if "공격장" in market_regime:
        value += 10
    return clamp(value)


def profile_match_bonus(row: Dict[str, str], profile: Dict[str, object]) -> Tuple[float, List[str]]:
    sector = row.get("sector", "")
    text = " ".join(str(row.get(key, "")) for key in ("name", "sector", "news", "reasons", "mobile_sector_keywords"))
    bonus = 0.0
    reasons: List[str] = []
    for industry in profile.get("preferred_industries") or []:
        if industry and industry in sector:
            bonus += 5
            reasons.append(f"선호 업종({industry})")
            break
    for theme in profile.get("themes") or []:
        if theme and theme in text:
            bonus += 4
            reasons.append(f"관심 테마({theme})")
            break
    return bonus, reasons


def compute_ai_score(row: Dict[str, str], profile: Dict[str, object]) -> Dict[str, object]:
    weights = profile.get("signal_weights") or DEFAULT_SIGNAL_WEIGHTS
    scores = signal_scores(row)
    total_weight = 0.0
    weighted_sum = 0.0
    active_reasons: List[str] = []
    weak_reasons: List[str] = []

    for key, weight in weights.items():
        weight_value = as_float(weight)
        if weight_value <= 0 or key not in scores:
            continue
        score, reason = scores[key]
        weighted_sum += score * weight_value
        total_weight += weight_value
        if score >= 70:
            active_reasons.append(reason)
        elif score <= 25:
            weak_reasons.append(reason)

    base_score = weighted_sum / total_weight if total_weight else 0
    bonus, profile_reasons = profile_match_bonus(row, profile)
    risk = as_float(row.get("risk"))
    chase_risk = str(row.get("chase_risk", "")).lower() == "true"
    penalty = min(18, risk * 0.15) + (8 if chase_risk else 0)
    final_score = clamp(base_score + bonus - penalty)
    if row.get("additional_upside_label") == "추세 지속 관찰":
        final_score = clamp(final_score + min(8, as_float(row.get("additional_upside_score")) * 0.08))

    recommendation = classify_recommendation(final_score, risk, chase_risk, row)
    reasons = (profile_reasons + active_reasons)[:6]
    if not reasons:
        reasons = [row.get("ai_reason") or row.get("action_reason") or "조건 일부 충족"]
    return {
        "ai_score": round(final_score, 1),
        "base_score": round(base_score, 1),
        "risk": round(risk, 1),
        "recommendation": recommendation,
        "reasons": reasons,
        "weak_points": weak_reasons[:4],
        "safety_notice": SAFETY_NOTICE,
    }


def classify_recommendation(score: float, risk: float, chase_risk: bool, row: Dict[str, str]) -> str:
    if risk >= 70:
        return "위험/제외"
    if chase_risk and as_float(row.get("additional_upside_score")) >= 72:
        return "강한 추세 지속 후보"
    if score >= 85:
        return "최우선 관찰"
    if score >= 75:
        return "관심"
    if score >= 55:
        return "관망"
    return "대기"


def run_screening(profile: Optional[Dict[str, object]] = None, limit: Optional[int] = None) -> Dict[str, object]:
    profile = save_profile(profile or load_profile())
    max_results = int(limit or profile.get("max_results") or 50)
    min_score = as_float(profile.get("min_ai_score"), 60)
    rows = [row for row in read_market_rows() if is_korean_stock(row) and row.get("status", "ok") == "ok"]
    screened = []
    for row in rows:
        result = compute_ai_score(row, profile)
        item = {
            "generated_at": utc_now_iso(),
            "name": row.get("name", ""),
            "ticker": row.get("ticker", ""),
            "sector": row.get("sector", ""),
            "price": row.get("price", ""),
            "change_pct": row.get("change_pct", ""),
            "ai_score": result["ai_score"],
            "base_score": result["base_score"],
            "risk": result["risk"],
            "recommendation": result["recommendation"],
            "reasons": " | ".join(result["reasons"]),
            "weak_points": " | ".join(result["weak_points"]),
            "stop_loss_pct": profile.get("max_stop_loss_pct"),
            "target_profit_pct": profile.get("target_profit_pct"),
            "safety_notice": SAFETY_NOTICE,
        }
        if result["ai_score"] >= min_score or result["recommendation"] == "강한 추세 지속 후보":
            screened.append(item)

    screened.sort(key=lambda item: (as_float(item["ai_score"]), -as_float(item["risk"])), reverse=True)
    screened = screened[:max_results]
    write_csv(SCREENING_RESULTS_FILE, screened)
    append_recommendation_history(screened)
    log_event("screening_run", count=len(screened), min_score=min_score)
    return {
        "ok": True,
        "generated_at": utc_now_iso(),
        "count": len(screened),
        "rows": screened,
        "profile": profile,
        "safety_notice": SAFETY_NOTICE,
    }


def write_csv(path: Path, rows: List[Dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def append_recommendation_history(rows: List[Dict[str, object]]) -> None:
    if not rows:
        return
    exists = RECOMMENDATION_HISTORY_FILE.exists()
    with RECOMMENDATION_HISTORY_FILE.open("a", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def backtest_screening(profile: Optional[Dict[str, object]] = None, period: str = "6mo", max_symbols: int = 30) -> Dict[str, object]:
    profile = profile or load_profile()
    candidates = run_screening(profile=profile, limit=max_symbols)["rows"]
    trades: List[Dict[str, object]] = []
    if yf is None or pd is None:
        return {"ok": False, "error": "yfinance/pandas 사용 불가", "safety_notice": SAFETY_NOTICE}

    for row in candidates[:max_symbols]:
        ticker = str(row["ticker"])
        try:
            hist = yf.download(ticker, period=period, interval="1d", progress=False, auto_adjust=False)
        except Exception as exc:
            log_event("backtest_download_failed", ticker=ticker, error=str(exc))
            continue
        if hist is None or hist.empty or len(hist) < 25:
            continue
        if isinstance(hist.columns, pd.MultiIndex):
            hist.columns = hist.columns.get_level_values(0)
        close = hist["Close"].dropna()
        high = hist["High"].dropna()
        low = hist["Low"].dropna()
        if len(close) < 25:
            continue
        entry_index = max(20, min(len(close) - 6, len(close) // 2))
        entry_price = float(close.iloc[entry_index])
        stop_pct = as_float(profile.get("max_stop_loss_pct"), 7.0) / 100
        target_pct = as_float(profile.get("target_profit_pct"), 15.0) / 100
        exit_price = float(close.iloc[-1])
        exit_reason = "기간 종료"
        for idx in range(entry_index + 1, len(close)):
            if float(low.iloc[idx]) <= entry_price * (1 - stop_pct):
                exit_price = entry_price * (1 - stop_pct)
                exit_reason = "손절 기준"
                break
            if float(high.iloc[idx]) >= entry_price * (1 + target_pct):
                exit_price = entry_price * (1 + target_pct)
                exit_reason = "목표 수익"
                break
        ret = (exit_price / entry_price - 1) * 100
        trades.append({
            "ticker": ticker,
            "name": row["name"],
            "entry_price": round(entry_price, 2),
            "exit_price": round(exit_price, 2),
            "return_pct": round(ret, 2),
            "entry_reason": row["reasons"],
            "exit_reason": exit_reason,
            "ai_score": row["ai_score"],
        })

    summary = summarize_trades(trades)
    write_csv(BACKTEST_TRADES_FILE, trades)
    write_csv(BACKTEST_RESULTS_FILE, [summary] if summary else [])
    log_event("backtest_run", trades=len(trades), period=period)
    return {"ok": True, "summary": summary, "trades": trades, "safety_notice": SAFETY_NOTICE}


def summarize_trades(trades: List[Dict[str, object]]) -> Dict[str, object]:
    if not trades:
        return {
            "total_trades": 0,
            "warning": "백테스트 가능 거래가 없습니다.",
            "safety_notice": SAFETY_NOTICE,
        }
    returns = [as_float(t["return_pct"]) for t in trades]
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    win_streak = lose_streak = max_win_streak = max_lose_streak = 0
    for ret in returns:
        equity *= 1 + ret / 100
        peak = max(peak, equity)
        max_dd = min(max_dd, equity / peak - 1)
        if ret > 0:
            win_streak += 1
            lose_streak = 0
        else:
            lose_streak += 1
            win_streak = 0
        max_win_streak = max(max_win_streak, win_streak)
        max_lose_streak = max(max_lose_streak, lose_streak)
    avg = statistics.mean(returns)
    downside = [r for r in returns if r < 0]
    stdev = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    downside_stdev = statistics.pstdev(downside) if len(downside) > 1 else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    final_return = (equity - 1) * 100
    return {
        "generated_at": utc_now_iso(),
        "total_trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 2),
        "average_profit_pct": round(statistics.mean(wins), 2) if wins else 0,
        "average_loss_pct": round(statistics.mean(losses), 2) if losses else 0,
        "profit_loss_ratio": round((statistics.mean(wins) if wins else 0) / abs(statistics.mean(losses) if losses else -1), 2),
        "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss else 999,
        "mdd_pct": round(max_dd * 100, 2),
        "max_consecutive_losses": max_lose_streak,
        "max_consecutive_wins": max_win_streak,
        "final_return_pct": round(final_return, 2),
        "sharpe_ratio": round(avg / stdev, 2) if stdev else 0,
        "sortino_ratio": round(avg / downside_stdev, 2) if downside_stdev else 0,
        "calmar_ratio": round(final_return / abs(max_dd * 100), 2) if max_dd else 0,
        "safety_notice": SAFETY_NOTICE,
    }


def paper_account_file(account_id: str = "") -> Path:
    clean = "".join(ch for ch in str(account_id or "") if ch.isalnum() or ch in {"-", "_"}).strip("-_")
    if not clean:
        return PAPER_ACCOUNT_DIR / "paper_trading_account.json"
    return PAPER_ACCOUNT_DIR / f"paper_trading_account.{clean[:80]}.json"


def legacy_paper_account_file(account_id: str = "") -> Path:
    clean = "".join(ch for ch in str(account_id or "") if ch.isalnum() or ch in {"-", "_"}).strip("-_")
    if not clean:
        return PAPER_ACCOUNT_FILE
    return BASE_DIR / f"paper_trading_account.{clean[:80]}.json"


def load_paper_account(account_id: str = "") -> Dict[str, object]:
    account_file = paper_account_file(account_id)
    if not account_file.exists():
        legacy_file = legacy_paper_account_file(account_id)
        if legacy_file.exists() and legacy_file != account_file:
            try:
                account = json.loads(legacy_file.read_text(encoding="utf-8"))
                save_paper_account(account, account_id=account_id)
                return account
            except (OSError, json.JSONDecodeError):
                pass
        account = {"cash": 0.0, "positions": {}, "trades": [], "created_at": utc_now_iso(), "safety_notice": SAFETY_NOTICE}
        save_paper_account(account, account_id=account_id)
        return account
    try:
        return json.loads(account_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"cash": 0.0, "positions": {}, "trades": [], "created_at": utc_now_iso(), "safety_notice": SAFETY_NOTICE}


def save_paper_account(account: Dict[str, object], account_id: str = "") -> Dict[str, object]:
    account["updated_at"] = utc_now_iso()
    account["safety_notice"] = SAFETY_NOTICE
    account_file = paper_account_file(account_id)
    payload = json.dumps(account, ensure_ascii=False, indent=2)
    try:
        account_file.parent.mkdir(parents=True, exist_ok=True)
        account_file.write_text(payload, encoding="utf-8")
    except OSError as exc:
        fallback_file = legacy_paper_account_file(account_id)
        print(f"[PAPER] primary write failed path={account_file}: {exc}; fallback={fallback_file}", flush=True)
        fallback_file.write_text(payload, encoding="utf-8")
    return account


def deposit_paper_cash(amount: float, account_id: str = "") -> Dict[str, object]:
    account = load_paper_account(account_id=account_id)
    if amount <= 0:
        raise ValueError("입금액은 0보다 커야 합니다.")
    account["cash"] = as_float(account.get("cash")) + amount
    account.setdefault("trades", []).append({"at": utc_now_iso(), "type": "deposit", "amount": amount})
    log_event("paper_deposit", amount=amount, account_id=account_id or "default")
    return save_paper_account(account, account_id=account_id)


def simulate_paper_trade(ticker: str, quantity: float, price: float, side: str, cash_amount: float = 0.0, account_id: str = "") -> Dict[str, object]:
    if side not in {"buy", "sell"}:
        raise ValueError("side는 buy 또는 sell 이어야 합니다.")
    if quantity <= 0 or price <= 0:
        raise ValueError("수량과 가격은 0보다 커야 합니다.")
    account = load_paper_account(account_id=account_id)
    positions = account.setdefault("positions", {})
    trades = account.setdefault("trades", [])
    cash = as_float(account.get("cash"))
    position = positions.get(ticker, {"quantity": 0.0, "avg_price": 0.0})
    current_qty = as_float(position.get("quantity"))
    avg_price = as_float(position.get("avg_price"))
    trade_value = quantity * price
    cash_value = cash_amount if cash_amount > 0 else trade_value

    if side == "buy":
        cost = cash_value
        if cash < cost:
            raise ValueError("모의 현금이 부족합니다.")
        new_qty = current_qty + quantity
        new_avg = ((current_qty * avg_price) + trade_value) / new_qty
        account["cash"] = cash - cost
        positions[ticker] = {"quantity": new_qty, "avg_price": new_avg}
    else:
        if current_qty < quantity:
            raise ValueError("모의 보유 수량이 부족합니다.")
        proceeds = cash_value
        remain_qty = current_qty - quantity
        account["cash"] = cash + proceeds
        if remain_qty <= 0:
            positions.pop(ticker, None)
        else:
            positions[ticker] = {"quantity": remain_qty, "avg_price": avg_price}

    trades.append({
        "at": utc_now_iso(),
        "type": f"paper_{side}",
        "ticker": ticker,
        "quantity": quantity,
        "price": price,
        "amount": trade_value,
        "cash_amount": cash_value,
    })
    log_event("paper_trade", side=side, ticker=ticker, quantity=quantity, account_id=account_id or "default")
    return save_paper_account(account, account_id=account_id)


def paper_account_summary(account_id: str = "") -> Dict[str, object]:
    account = load_paper_account(account_id=account_id)
    rows = {row.get("ticker"): row for row in read_market_rows()}
    positions = account.get("positions") or {}
    trades = account.get("trades") or []
    details = []
    total_value = as_float(account.get("cash"))
    for ticker, position in positions.items():
        row = rows.get(ticker, {})
        qty = as_float(position.get("quantity"))
        avg = as_float(position.get("avg_price"))
        current = as_float(row.get("price"), avg)
        value = qty * current
        pnl = value - qty * avg
        total_value += value
        details.append({
            "ticker": ticker,
            "name": row.get("name", ticker),
            "quantity": qty,
            "avg_price": round(avg, 2),
            "current_price": round(current, 2),
            "market_value": round(value, 2),
            "profit_loss": round(pnl, 2),
            "profit_loss_pct": round((current / avg - 1) * 100, 2) if avg else 0,
        })
    enriched_trades = []
    for trade in trades[-100:]:
        ticker = str(trade.get("ticker", "") or "")
        row = rows.get(ticker, {})
        quantity = as_float(trade.get("quantity"))
        price = as_float(trade.get("price"))
        amount = as_float(trade.get("amount"), quantity * price)
        enriched_trades.append({
            "at": trade.get("at", ""),
            "type": trade.get("type", ""),
            "ticker": ticker,
            "name": row.get("name", ticker) if ticker else "현금",
            "quantity": quantity,
            "price": price,
            "amount": round(amount, 2),
        })
    return {
        "ok": True,
        "cash": round(as_float(account.get("cash")), 2),
        "total_value": round(total_value, 2),
        "positions": details,
        "trades": enriched_trades,
        "trade_count": len(trades),
        "updated_at": account.get("updated_at"),
        "safety_notice": SAFETY_NOTICE,
    }


def watchdog_status(max_stale_seconds: int = 60) -> Dict[str, object]:
    if not MARKET_RESULTS_FILE.exists():
        return {"ok": False, "state": "missing", "message": "결과 파일 없음", "safety_notice": SAFETY_NOTICE}
    age = time.time() - MARKET_RESULTS_FILE.stat().st_mtime
    state = "ok" if age <= max_stale_seconds else "stale"
    message = "데이터 수신 정상" if state == "ok" else f"데이터 미수신 {int(age)}초 · 재연결/갱신 필요"
    return {
        "ok": state == "ok",
        "state": state,
        "age_seconds": int(age),
        "message": message,
        "file_updated_at": datetime.fromtimestamp(MARKET_RESULTS_FILE.stat().st_mtime, timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="한국 주식 AI 스크리닝 + 모의투자 시스템")
    parser.add_argument("--screen", action="store_true", help="AI 스크리닝 실행")
    parser.add_argument("--backtest", action="store_true", help="백테스트 실행")
    parser.add_argument("--period", default="6mo", help="백테스트 기간: 3mo, 6mo, 1y, 3y, 5y")
    parser.add_argument("--deposit", type=float, default=0.0, help="모의계좌 입금")
    parser.add_argument("--summary", action="store_true", help="모의계좌 요약")
    args = parser.parse_args()

    if args.deposit > 0:
        print(json.dumps(deposit_paper_cash(args.deposit), ensure_ascii=False, indent=2))
    if args.screen:
        print(json.dumps(run_screening(), ensure_ascii=False, indent=2))
    if args.backtest:
        print(json.dumps(backtest_screening(period=args.period), ensure_ascii=False, indent=2))
    if args.summary:
        print(json.dumps(paper_account_summary(), ensure_ascii=False, indent=2))
    if not any([args.deposit > 0, args.screen, args.backtest, args.summary]):
        print(json.dumps({"profile": load_profile(), "watchdog": watchdog_status(), "safety_notice": SAFETY_NOTICE}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
