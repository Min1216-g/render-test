2#!/usr/bin/env python3

import os
import stat
import subprocess
import time as time_module
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf

from ops_guard import enforce_runtime_security


BASE_DIR = Path(__file__).resolve().parent
BACKTEST_ENV_FILE = BASE_DIR / ".env.backtest"
RESULT_FILE = BASE_DIR / "today_hot_predictor_results.csv"
BOT_RESULTS_FILE = BASE_DIR / "analysis_results.csv"
MARKET_RESULTS_FILE = BASE_DIR / "market_scanner_results.csv"
QUIET_RESULTS_FILE = BASE_DIR / "quiet_money_results.csv"
NEWS_RESULTS_FILE = BASE_DIR / "news_pulse_results.csv"
US_LEADER_RESULTS_FILE = BASE_DIR / "us_leader_watch_results.csv"
US_UNDER20_RESULTS_FILE = BASE_DIR / "us_under20_scanner_results.csv"
BACKTEST_QUALITY_FILE = BASE_DIR / "backtest_quality_report.csv"
SEOUL_TZ = ZoneInfo("Asia/Seoul")
TELEGRAM_MAX_LENGTH = 3900
TELEGRAM_RETRIES = 3
enforce_runtime_security(BASE_DIR, env_files=[BACKTEST_ENV_FILE])


def secure_file_permissions(path):
    if not path.exists():
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        path.chmod(0o600)
        print(f"보안: {path.name} 권한을 600으로 변경했습니다.", flush=True)


def load_env_file(path):
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


secure_file_permissions(BACKTEST_ENV_FILE)
load_env_file(BACKTEST_ENV_FILE)

BOT_TOKEN = os.getenv("BACKTEST_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("BACKTEST_CHAT_ID", "").strip()
TOP_N = int(os.getenv("TODAY_PICK_TOP_N", "8"))
MIN_SCORE = float(os.getenv("TODAY_PICK_MIN_SCORE", "55"))
AUTO_REFRESH = os.getenv("TODAY_PICK_AUTO_REFRESH", "true").lower() == "true"
MAX_SOURCE_AGE_MINUTES = int(os.getenv("TODAY_PICK_MAX_SOURCE_AGE_MINUTES", "30"))
REFRESH_TIMEOUT_SECONDS = int(os.getenv("TODAY_PICK_REFRESH_TIMEOUT_SECONDS", "900"))
QUOTE_REFRESH_LIMIT = int(os.getenv("TODAY_PICK_QUOTE_REFRESH_LIMIT", "15"))

SOURCE_FILES = {
    "bot": BOT_RESULTS_FILE,
    "market_scanner": MARKET_RESULTS_FILE,
    "quiet_money": QUIET_RESULTS_FILE,
    "news_pulse": NEWS_RESULTS_FILE,
    "us_leader": US_LEADER_RESULTS_FILE,
    "us_under20": US_UNDER20_RESULTS_FILE,
}
REFRESH_COMMANDS = [
    (
        "market_scanner",
        ["python3", "market_scanner.py"],
        {
            "MARKET_SCANNER_BOT_TOKEN": "",
            "MARKET_SCANNER_CHAT_ID": "",
            "MARKET_SCANNER_ENABLE_FLOW": "false",
            "MARKET_SCANNER_MAX_STOCKS": os.getenv("TODAY_PICK_MARKET_MAX_STOCKS", "0"),
        },
    ),
    (
        "quiet_money",
        ["python3", "quiet_money_scanner.py"],
        {
            "BOT_TOKEN": "",
            "CHAT_ID": "",
            "QUIET_SEND_EMPTY_REPORT": "false",
            "QUIET_MAX_WORKERS": os.getenv("TODAY_PICK_QUIET_MAX_WORKERS", "4"),
            "QUIET_MAX_STOCKS": os.getenv("TODAY_PICK_QUIET_MAX_STOCKS", "80"),
        },
    ),
    (
        "us_leader",
        ["python3", "us_leader_watch.py"],
        {
            "MARKET_SCANNER_BOT_TOKEN": "",
            "MARKET_SCANNER_CHAT_ID": "",
            "US_LEADER_BOT_TOKEN": "",
            "US_LEADER_CHAT_ID": "",
            "US_LEADER_MAX_STOCKS": os.getenv("TODAY_PICK_US_LEADER_MAX_STOCKS", "120"),
        },
    ),
    (
        "us_under20",
        ["python3", "us_under20_scanner.py"],
        {
            "MARKET_SCANNER_BOT_TOKEN": "",
            "MARKET_SCANNER_CHAT_ID": "",
            "US_UNDER20_BOT_TOKEN": "",
            "US_UNDER20_CHAT_ID": "",
            "US_UNDER20_MAX_STOCKS": os.getenv("TODAY_PICK_US_UNDER20_MAX_STOCKS", "45"),
        },
    ),
    ("news_pulse", ["python3", "news_pulse_tracker.py", "--once"], {"NEWS_PULSE_SEND_TELEGRAM": "false"}),
]
SOURCE_STATUS = {}
QUOTE_CACHE = {}


def mask_secret(value, visible=4):
    if not value:
        return "없음"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def read_csv(path):
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        print(f"{path.name} 읽기 실패: {exc}", flush=True)
        return pd.DataFrame()


def source_age_minutes(path):
    path = Path(path)
    if not path.exists():
        return None
    modified_at = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    return (datetime.now(timezone.utc) - modified_at).total_seconds() / 60


def source_is_fresh(source_name):
    path = SOURCE_FILES[source_name]
    age = source_age_minutes(path)
    if age is None:
        SOURCE_STATUS[source_name] = {"fresh": False, "age_minutes": None, "note": "파일 없음"}
        return False
    fresh = age <= MAX_SOURCE_AGE_MINUTES
    SOURCE_STATUS[source_name] = {
        "fresh": fresh,
        "age_minutes": round(age, 1),
        "note": "최신" if fresh else "오래됨",
    }
    return fresh


def refresh_source_data():
    if not AUTO_REFRESH:
        for name in SOURCE_FILES:
            source_is_fresh(name)
        return

    for name, command, env_updates in REFRESH_COMMANDS:
        if source_is_fresh(name):
            print(f"최신화 건너뜀: {name} / 이미 최신", flush=True)
            continue
        before_age = source_age_minutes(SOURCE_FILES[name])
        print(f"최신화: {name} 실행 중", flush=True)
        env = os.environ.copy()
        env.update(env_updates)
        try:
            result = subprocess.run(
                command,
                cwd=BASE_DIR,
                env=env,
                text=True,
                capture_output=True,
                timeout=REFRESH_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            SOURCE_STATUS[name] = {
                "fresh": False,
                "age_minutes": round(before_age, 1) if before_age is not None else None,
                "note": f"갱신 실패: {exc}",
            }
            print(f"최신화 실패: {name} / {exc}", flush=True)
            continue
        after_age = source_age_minutes(SOURCE_FILES[name])
        fresh = after_age is not None and after_age <= MAX_SOURCE_AGE_MINUTES
        note = "갱신 완료" if result.returncode == 0 and fresh else f"갱신 확인 필요(code {result.returncode})"
        SOURCE_STATUS[name] = {
            "fresh": fresh,
            "age_minutes": round(after_age, 1) if after_age is not None else None,
            "note": note,
        }
        print(f"최신화 결과: {name} / {note}", flush=True)

    source_is_fresh("bot")


def freshness_summary():
    parts = []
    for name in SOURCE_FILES:
        status = SOURCE_STATUS.get(name)
        if not status:
            source_is_fresh(name)
            status = SOURCE_STATUS[name]
        age = status["age_minutes"]
        age_text = "없음" if age is None else f"{age:.1f}분"
        marker = "OK" if status["fresh"] else "OLD"
        parts.append(f"{name}:{marker}({age_text})")
    return " / ".join(parts)


def to_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(number):
        return default
    return number


def clean_text(value, default="-"):
    text = str(value or "").strip()
    if not text or text.lower() == "nan":
        return default
    return text


def compact(text, limit=92):
    value = clean_text(text)
    return value if len(value) <= limit else value[: limit - 3] + "..."


def fmt_number(value, digits=0, suffix=""):
    number = to_float(value, None)
    if number is None:
        return "-"
    if digits == 0:
        return f"{number:,.0f}{suffix}"
    return f"{number:,.{digits}f}{suffix}"


def normalize_ohlcv_dataframe(df):
    if df is None or df.empty:
        return pd.DataFrame()
    normalized = df.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = normalized.columns.get_level_values(0)
    keep_cols = [col for col in ["Open", "High", "Low", "Close", "Volume"] if col in normalized.columns]
    return normalized[keep_cols].dropna() if keep_cols else pd.DataFrame()


def latest_quote(ticker):
    ticker = clean_text(ticker, "")
    if not ticker:
        return None
    if ticker in QUOTE_CACHE:
        return QUOTE_CACHE[ticker]

    for period, interval in [("1d", "1m"), ("5d", "5m"), ("10d", "1d")]:
        try:
            df = yf.download(
                ticker,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=False,
                threads=False,
            )
        except Exception:
            continue

        df = normalize_ohlcv_dataframe(df)
        if df.empty or "Close" not in df.columns:
            continue

        close = df["Close"].dropna().astype(float)
        if close.empty:
            continue
        price = float(close.iloc[-1])

        previous = None
        if interval in {"1m", "5m"}:
            daily = normalize_ohlcv_dataframe(
                yf.download(
                    ticker,
                    period="5d",
                    interval="1d",
                    progress=False,
                    auto_adjust=False,
                    threads=False,
                )
            )
            daily_close = daily["Close"].dropna().astype(float) if not daily.empty and "Close" in daily.columns else pd.Series(dtype=float)
            if len(daily_close) >= 2:
                previous = float(daily_close.iloc[-2])
            elif len(close) >= 2:
                previous = float(close.iloc[0])
        elif len(close) >= 2:
            previous = float(close.iloc[-2])

        change_pct = ((price / previous) - 1) * 100 if previous else None
        quote = {
            "price": round(price, 2),
            "change_pct": round(change_pct, 2) if change_pct is not None else None,
            "quote_interval": interval,
            "quote_status": "검증완료",
        }
        QUOTE_CACHE[ticker] = quote
        return quote

    QUOTE_CACHE[ticker] = None
    return None


def refresh_latest_quotes(rows):
    if not rows or QUOTE_REFRESH_LIMIT <= 0:
        return rows

    refreshed = []
    for index, row in enumerate(rows):
        item = dict(row)
        if index < QUOTE_REFRESH_LIMIT:
            quote = latest_quote(item.get("ticker"))
            if quote:
                old_price = to_float(item.get("price"), None)
                item["price"] = quote["price"]
                if quote["change_pct"] is not None:
                    item["change_pct"] = quote["change_pct"]
                item["quote_interval"] = quote["quote_interval"]
                item["quote_status"] = quote["quote_status"]
                item["price_checked_at"] = datetime.now(SEOUL_TZ).isoformat()
                if old_price and old_price > 0:
                    item["price_delta_from_source_pct"] = round(((quote["price"] / old_price) - 1) * 100, 2)
            else:
                item["quote_interval"] = "-"
                item["quote_status"] = "현재가 검증 실패"
                item["price_checked_at"] = datetime.now(SEOUL_TZ).isoformat()
        refreshed.append(item)
    return refreshed


def quality_boost_for_signal(signal):
    quality = read_csv(BACKTEST_QUALITY_FILE)
    if quality.empty or "signal" not in quality.columns:
        return 0.0, "백테스트 보정 없음"

    rows = quality[quality["signal"].astype(str) == str(signal)].copy()
    if rows.empty:
        return 0.0, "백테스트 표본 없음"

    preferred_windows = {"return_4h_pct", "return_1d_pct", "return_3d_pct"}
    if "window" in rows.columns:
        selected = rows[rows["window"].isin(preferred_windows)].copy()
        rows = selected if not selected.empty else rows

    rows["samples_num"] = pd.to_numeric(rows.get("samples", 0), errors="coerce").fillna(0)
    rows["avg_return_num"] = pd.to_numeric(rows.get("avg_return_pct", 0), errors="coerce").fillna(0)
    rows["win_rate_num"] = pd.to_numeric(rows.get("win_rate_pct", 0), errors="coerce").fillna(0)
    reliable = rows[rows["samples_num"] >= 20]
    if reliable.empty:
        return 0.0, "백테스트 표본 부족"

    avg_return = float(reliable["avg_return_num"].mean())
    win_rate = float(reliable["win_rate_num"].mean())
    boost = max(-10.0, min(10.0, avg_return * 2 + (win_rate - 50) * 0.15))
    return boost, f"백테스트 {avg_return:.2f}% / 승률 {win_rate:.0f}%"


def add_candidate(candidates, key, item):
    current = candidates.get(key)
    if current is None or item["predict_score"] > current["predict_score"]:
        candidates[key] = item


def news_strength_penalty(strength):
    strength = clean_text(strength, "none").lower()
    if strength == "weak":
        return 6.0
    return 0.0


def merge_news_note(primary, strength):
    primary = compact(primary, 70)
    strength = clean_text(strength, "none").lower()
    if strength == "weak":
        return "약한 호재: 단독 매수 근거 부족" if primary == "-" else f"{primary} / 약한 호재"
    if strength == "strong":
        return "강한 호재" if primary == "-" else f"{primary} / 강한 호재"
    if strength == "medium":
        return "보통 호재" if primary == "-" else f"{primary} / 보통 호재"
    return primary


def news_boost_map():
    if not source_is_fresh("news_pulse"):
        return {}
    news = read_csv(NEWS_RESULTS_FILE)
    if news.empty:
        return {}

    boosts = {}
    for _, row in news.iterrows():
        key = clean_text(row.get("code"), "")
        if not key:
            key = clean_text(row.get("name"), "")
        if not key:
            continue
        score = min(18.0, max(-12.0, to_float(row.get("score")) / 8))
        positive = to_float(row.get("positive_count"))
        negative = to_float(row.get("negative_count"))
        score += min(7.0, positive * 1.2) - min(8.0, negative * 2.0)
        reason = compact(row.get("positive_reasons") or row.get("keyword_hits") or row.get("headline"), 70)
        previous = boosts.get(key)
        if previous is None or score > previous["boost"]:
            boosts[key] = {"boost": score, "reason": reason}
    return boosts


def build_bot_candidates(candidates, news_boosts):
    if not source_is_fresh("bot"):
        return
    df = read_csv(BOT_RESULTS_FILE)
    if df.empty:
        return
    for _, row in df.iterrows():
        if clean_text(row.get("status")) != "ok":
            continue
        signal = clean_text(row.get("signal"))
        base = to_float(row.get("score")) - to_float(row.get("risk")) * 3.2
        if signal == "🔥 STRONG BUY":
            base += 18
        elif signal == "👍 BUY":
            base += 12
        elif signal == "👀 WATCH":
            base += 6
        elif signal in {"🔻 SELL", "📉 WEAK"}:
            base -= 16

        volume_ratio = to_float(row.get("volume_ratio"))
        trade_value_ratio = to_float(row.get("trade_value_ratio"))
        base += min(12.0, max(0.0, volume_ratio - 1) * 10)
        base += min(8.0, max(0.0, trade_value_ratio - 1) * 7)
        if str(row.get("chasing_risk")).lower() == "true":
            base -= 8
        timing = clean_text(row.get("entry_timing"), "")
        if "눌림" in timing or "초입" in timing:
            base += 5
        elif "고점" in timing:
            base -= 8

        quality_boost, quality_reason = quality_boost_for_signal(signal)
        code = clean_text(row.get("code"))
        news = news_boosts.get(code, {"boost": 0.0, "reason": "-"})
        source_news_strength = clean_text(row.get("news_strength"), "none")
        predict_score = base + quality_boost + news["boost"] - news_strength_penalty(source_news_strength)
        add_candidate(
            candidates,
            code,
            {
                "name": clean_text(row.get("name")),
                "ticker": code,
                "market": clean_text(row.get("market"), "KR"),
                "source": "bot",
                "signal": signal,
                "predict_score": round(predict_score, 1),
                "price": row.get("price"),
                "change_pct": row.get("change"),
                "rsi": row.get("rsi"),
                "volume_ratio": volume_ratio,
                "risk": row.get("risk"),
                "reason": compact(row.get("reasons")),
                "risk_note": compact(row.get("risks")),
                "news_note": merge_news_note(news["reason"], source_news_strength),
                "quality_note": quality_reason,
            },
        )


def build_market_candidates(candidates, news_boosts):
    if not source_is_fresh("market_scanner"):
        return
    df = read_csv(MARKET_RESULTS_FILE)
    if df.empty:
        return
    for _, row in df.iterrows():
        if clean_text(row.get("status")) != "ok":
            continue
        base = to_float(row.get("score")) - to_float(row.get("risk")) * 2.7
        action = clean_text(row.get("action"))
        label = clean_text(row.get("label"))
        if "매수" in action:
            base += 12
        if "강력" in label:
            base += 8
        if str(row.get("chase_risk")).lower() == "true" or str(row.get("overheated")).lower() == "true":
            base -= 18
        volume_ratio = to_float(row.get("volume_ratio"))
        change_pct = to_float(row.get("change_pct"))
        rsi_value = to_float(row.get("rsi"))
        early_setup = -2.5 <= change_pct <= 3.5 and 40 <= rsi_value <= 68 and 0.8 <= volume_ratio <= 2.4
        if early_setup:
            base += 14
        elif change_pct <= 4:
            base += min(7.0, max(0.0, volume_ratio - 1) * 5)
        if change_pct >= 5:
            base -= 12
        if change_pct >= 8:
            base -= 14
        if volume_ratio >= 3 and change_pct >= 4:
            base -= 8
        if rsi_value >= 78:
            base -= 10
        contrarian_score = to_float(row.get("contrarian_score"))
        if contrarian_score > 0:
            base += min(22.0, contrarian_score * 0.45)
        elif contrarian_score < 0:
            base += max(-12.0, contrarian_score * 0.6)

        ticker = clean_text(row.get("ticker"))
        news = news_boosts.get(ticker, {"boost": 0.0, "reason": "-"})
        source_news_strength = clean_text(row.get("news_strength"), "none")
        contrarian_note = compact(row.get("contrarian_signal"))
        add_candidate(
            candidates,
            ticker,
            {
                "name": clean_text(row.get("name")),
                "ticker": ticker,
                "market": clean_text(row.get("market"), "KR"),
                "source": "market_scanner",
                "signal": action,
                "predict_score": round(base + news["boost"] - news_strength_penalty(source_news_strength), 1),
                "price": row.get("price"),
                "change_pct": change_pct,
                "rsi": row.get("rsi"),
                "volume_ratio": volume_ratio,
                "risk": row.get("risk"),
                "reason": compact(" · ".join(part for part in [row.get("reasons"), contrarian_note] if part)),
                "risk_note": compact(row.get("risks")),
                "news_note": merge_news_note(news["reason"], source_news_strength),
                "quality_note": "마켓 스캐너 점수 기반",
            },
        )


def build_quiet_candidates(candidates, news_boosts):
    if not source_is_fresh("quiet_money"):
        return
    df = read_csv(QUIET_RESULTS_FILE)
    if df.empty:
        return
    for _, row in df.iterrows():
        if clean_text(row.get("status")) != "ok":
            continue
        base = to_float(row.get("score")) - 8
        if str(row.get("alert_ready")).lower() in {"true", "1"}:
            base += 18
        volume_ratio = to_float(row.get("volume_ratio"))
        base += min(12.0, max(0.0, volume_ratio - 1.2) * 8)
        ticker = clean_text(row.get("ticker"))
        news = news_boosts.get(ticker, {"boost": 0.0, "reason": "-"})
        source_news_strength = clean_text(row.get("news_strength"), "none")
        add_candidate(
            candidates,
            ticker,
            {
                "name": clean_text(row.get("name")),
                "ticker": ticker,
                "market": "KR",
                "source": "quiet_money",
                "signal": "진입알림" if str(row.get("alert_ready")).lower() in {"true", "1"} else "관찰",
                "predict_score": round(base + news["boost"] - news_strength_penalty(source_news_strength), 1),
                "price": row.get("price"),
                "change_pct": row.get("change_pct"),
                "rsi": row.get("rsi"),
                "volume_ratio": volume_ratio,
                "risk": row.get("risk", 0),
                "reason": compact(row.get("reasons") or row.get("news_keywords")),
                "risk_note": compact(row.get("risks")),
                "news_note": merge_news_note(news["reason"], source_news_strength),
                "quality_note": "조용한 수급 포착",
            },
        )


def build_us_candidates(candidates):
    for path, source, score_penalty in [
        (US_LEADER_RESULTS_FILE, "us_leader", 0.0),
        (US_UNDER20_RESULTS_FILE, "us_under20", 6.0),
    ]:
        if not source_is_fresh(source):
            continue
        df = read_csv(path)
        if df.empty:
            continue
        for _, row in df.iterrows():
            if clean_text(row.get("status")) != "ok":
                continue
            ticker = clean_text(row.get("ticker"))
            if not ticker or ticker.startswith("^") or "=" in ticker:
                continue
            base = to_float(row.get("score")) - to_float(row.get("risk")) * 2.5 - score_penalty
            change_pct = to_float(row.get("change_pct"))
            volume_ratio = to_float(row.get("volume_ratio"))
            rsi_value = to_float(row.get("rsi"))
            early_setup = -3 <= change_pct <= 4 and 38 <= rsi_value <= 68 and 0.8 <= volume_ratio <= 2.6
            if early_setup:
                base += 12
            elif change_pct <= 4:
                base += min(7.0, max(0.0, volume_ratio - 1) * 5)
            if change_pct >= 5:
                base -= 14
            if change_pct >= 10:
                base -= 18
            if change_pct >= 20:
                base -= 30
            if volume_ratio >= 3 and change_pct >= 4:
                base -= 10
            if rsi_value >= 78:
                base -= 10
            if source == "us_under20" and "초기 매수" in clean_text(row.get("action")):
                base += 10
            source_news_strength = clean_text(row.get("news_strength"), "none")
            base -= news_strength_penalty(source_news_strength)
            add_candidate(
                candidates,
                ticker,
                {
                    "name": clean_text(row.get("name")),
                    "ticker": ticker,
                    "market": "US",
                    "source": source,
                    "signal": clean_text(row.get("trend") or row.get("action")),
                    "predict_score": round(base, 1),
                    "price": row.get("price"),
                    "change_pct": row.get("change_pct"),
                    "rsi": row.get("rsi"),
                    "volume_ratio": volume_ratio,
                    "risk": row.get("risk", 0),
                    "reason": compact(row.get("reasons")),
                    "risk_note": compact(row.get("risks")),
                    "news_note": merge_news_note(row.get("news_summary", "-"), source_news_strength),
                    "quality_note": "미국 스캐너 점수 기반",
                },
            )


def build_predictions():
    refresh_source_data()
    candidates = {}
    news_boosts = news_boost_map()
    build_bot_candidates(candidates, news_boosts)
    build_market_candidates(candidates, news_boosts)
    build_quiet_candidates(candidates, news_boosts)
    build_us_candidates(candidates)

    rows = list(candidates.values())
    generated_at = datetime.now(SEOUL_TZ).isoformat()
    for row in rows:
        status = SOURCE_STATUS.get(row["source"], {})
        row["generated_at"] = generated_at
        row["source_age_minutes"] = status.get("age_minutes")
        row["source_freshness"] = status.get("note", "-")
    rows = [row for row in rows if row["predict_score"] >= MIN_SCORE]
    rows.sort(key=lambda item: item["predict_score"], reverse=True)
    rows = refresh_latest_quotes(rows)
    return rows


def format_candidate(index, item):
    currency = "$" if item["market"] == "US" else ""
    price_suffix = "" if item["market"] == "US" else "원"
    lines = [
        f"{index}. {item['name']} ({item['ticker']}) | {item['market']} | 예측점수 {item['predict_score']}",
        f"   신호: {item['signal']} / 출처: {item['source']}",
        f"   가격: {currency}{fmt_number(item['price'], 2 if item['market'] == 'US' else 0)}{price_suffix} / 등락 {fmt_number(item['change_pct'], 2, '%')} / 거래량 {fmt_number(item['volume_ratio'], 2, 'x')} / RSI {fmt_number(item['rsi'], 1)}",
        f"   근거: {item['reason']}",
    ]
    if item.get("quote_status"):
        quote_note = item["quote_status"]
        if item.get("price_delta_from_source_pct") not in (None, ""):
            quote_note += f" / 원본대비 {fmt_number(item.get('price_delta_from_source_pct'), 2, '%')}"
        lines.append(f"   현재가: {quote_note}")
    if item["news_note"] != "-":
        lines.append(f"   뉴스: {item['news_note']}")
    if item["quality_note"] != "-":
        lines.append(f"   보정: {item['quality_note']}")
    if item["risk_note"] != "-":
        lines.append(f"   주의: {item['risk_note']}")
    return "\n".join(lines)


def build_report(predictions):
    now = datetime.now(SEOUL_TZ)
    top = predictions[:TOP_N]
    kr_count = sum(1 for item in predictions if item["market"] == "KR")
    us_count = sum(1 for item in predictions if item["market"] == "US")
    lines = [
        "🔮 [오늘 뜰 가능성 높은 종목 예측]",
        f"시간: {now:%Y-%m-%d %H:%M}",
        f"데이터 신선도: {freshness_summary()}",
        f"후보: 국내 {kr_count}개 / 미국 {us_count}개 / 기준점수 {MIN_SCORE}",
        "",
    ]
    if not top:
        lines.append("지금 기준으로 점수 기준을 넘는 후보가 없습니다. 무리한 진입보다 관망 우선입니다.")
        return "\n".join(lines)

    lines.append("🔥 TOP 후보")
    for index, item in enumerate(top, start=1):
        lines.append(format_candidate(index, item))
        lines.append("")
    lines.append("원칙: 시초가 급등 추격보다 눌림/거래량 재확인 후 분할 접근. 손절가는 종목별 변동성에 맞춰 짧게.")
    lines.append(f"상세 파일: {RESULT_FILE.name}")
    return "\n".join(lines).strip()


def split_telegram_message(text):
    if len(text) <= TELEGRAM_MAX_LENGTH:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > TELEGRAM_MAX_LENGTH:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def sanitize_error(message):
    text = str(message)
    if BOT_TOKEN:
        text = text.replace(BOT_TOKEN, mask_secret(BOT_TOKEN))
    return text


def send_telegram(text):
    if not BOT_TOKEN or not CHAT_ID:
        print("텔레그램 설정 없음: .env.backtest의 BACKTEST_BOT_TOKEN / BACKTEST_CHAT_ID를 확인하세요.", flush=True)
        return False

    from telegram_message_utils import compact_telegram_message

    text = compact_telegram_message(text)
    print(f"전송 대상: backtest token {mask_secret(BOT_TOKEN)} / chat {mask_secret(CHAT_ID, 2)}", flush=True)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for chunk in split_telegram_message(text):
        last_error = None
        for attempt in range(1, TELEGRAM_RETRIES + 1):
            try:
                response = requests.post(
                    url,
                    data={"chat_id": CHAT_ID, "text": chunk, "disable_web_page_preview": True},
                    timeout=12,
                )
                if response.ok:
                    last_error = None
                    break
                last_error = f"HTTP {response.status_code}: {response.text[:250]}"
            except requests.RequestException as exc:
                last_error = sanitize_error(exc)
            if attempt < TELEGRAM_RETRIES:
                time_module.sleep(1)
        if last_error:
            print(f"텔레그램 전송 실패: {sanitize_error(last_error)}", flush=True)
            return False
    return True


def main():
    predictions = build_predictions()
    pd.DataFrame(predictions).to_csv(RESULT_FILE, index=False, encoding="utf-8-sig")
    report = build_report(predictions)
    print(report, flush=True)
    if send_telegram(report):
        print("텔레그램 전송 완료", flush=True)


if __name__ == "__main__":
    main()
