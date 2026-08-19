from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .comparison import ComparisonLab
from .config import DATA_DIR, DEFAULT_MARKET_RESULTS, ResearchLabConfig
from .daily_comparison import DailyComparisonLab
from .engine import ResearchEngine, _num, validate_market_row, validate_news_row
from .storage import JsonlStore


BASE_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = DATA_DIR / "automation_state.json"
LOG_FILE = DATA_DIR / "automation_log.jsonl"
LOCK_FILE = DATA_DIR / ".automation.lock"
MONITORING_FILE = DATA_DIR / "monitoring_history.jsonl"

TELEGRAM_MAX_LENGTH = 3900
DEFAULT_PRIMARY_LIMIT = 40
DEFAULT_MONITORING_LIMIT = 40
DEFAULT_SNAPSHOT_MAX_AGE_MINUTES = 180
JOB_STATUS_PENDING = "PENDING"
JOB_STATUS_RUNNING = "RUNNING"
JOB_STATUS_COMPLETED = "COMPLETED"
JOB_STATUS_SKIPPED_NO_FRESH_SNAPSHOT = "SKIPPED_NO_FRESH_SNAPSHOT"


@dataclass(frozen=True)
class ResearchSlot:
    key: str
    phase: str
    snapshot_type: str
    local_time: time
    window_minutes: int
    official_evaluation: bool


@dataclass(frozen=True)
class MarketSchedule:
    key: str
    labels: set[str]
    timezone: str
    open_time: time
    close_time: time
    open_delay_minutes: int
    close_delay_minutes: int
    open_window_minutes: int
    close_window_minutes: int
    holiday_env: str
    default_holidays: set[str]


MARKETS = {
    "KOREA": MarketSchedule(
        key="KOREA",
        labels={"국장", "한국", "KOREA"},
        timezone="Asia/Seoul",
        open_time=time(9, 0),
        close_time=time(15, 30),
        open_delay_minutes=5,
        close_delay_minutes=20,
        open_window_minutes=45,
        close_window_minutes=90,
        holiday_env="RESEARCH_KOREA_HOLIDAYS",
        default_holidays={
            "2026-01-01",
            "2026-02-16",
            "2026-02-17",
            "2026-02-18",
            "2026-03-02",
            "2026-05-05",
            "2026-05-25",
            "2026-08-17",
            "2026-09-24",
            "2026-09-25",
            "2026-10-05",
            "2026-10-09",
            "2026-12-25",
            "2026-12-31",
        },
    ),
    "US": MarketSchedule(
        key="US",
        labels={"미장", "US", "USA", "미국"},
        timezone="America/New_York",
        open_time=time(9, 30),
        close_time=time(16, 0),
        open_delay_minutes=5,
        close_delay_minutes=20,
        open_window_minutes=45,
        close_window_minutes=90,
        holiday_env="RESEARCH_US_HOLIDAYS",
        default_holidays={
            "2026-01-01",
            "2026-01-19",
            "2026-02-16",
            "2026-04-03",
            "2026-05-25",
            "2026-06-19",
            "2026-07-03",
            "2026-09-07",
            "2026-11-26",
            "2026-12-25",
        },
    ),
}


SCHEDULE_SLOTS = {
    "KOREA": (
        ResearchSlot("PREMARKET", "PRE_MARKET", "PRE_MARKET", time(8, 45), 10, False),
        ResearchSlot("PRIMARY", "PRIMARY_TEST", "PRIMARY_TEST", time(9, 5), 24, True),
        ResearchSlot("MONITOR_0930", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(9, 30), 10, False),
        ResearchSlot("MONITOR_1000", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(10, 0), 10, False),
        ResearchSlot("MONITOR_1200", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(12, 0), 10, False),
        ResearchSlot("MONITOR_1430", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(14, 30), 10, False),
        ResearchSlot("CLOSE", "CLOSE_EVALUATION", "CLOSE_EVALUATION", time(15, 30), 90, True),
    ),
    "US": (
        ResearchSlot("PREMARKET", "PRE_MARKET", "PRE_MARKET", time(9, 15), 10, False),
        ResearchSlot("PRIMARY", "PRIMARY_TEST", "PRIMARY_TEST", time(9, 35), 24, True),
        ResearchSlot("MONITOR_1000", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(10, 0), 10, False),
        ResearchSlot("MONITOR_1030", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(10, 30), 10, False),
        ResearchSlot("MONITOR_1230", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(12, 30), 10, False),
        ResearchSlot("MONITOR_1530", "INTRADAY_MONITORING", "INTRADAY_MONITORING", time(15, 30), 10, False),
        ResearchSlot("CLOSE", "CLOSE_EVALUATION", "CLOSE_EVALUATION", time(16, 0), 90, True),
    ),
}


def load_env_files() -> dict[str, str]:
    values = dict(os.environ)
    for filename in [".env", ".env.market_scanner", ".env.backtest", ".env.news_pulse"]:
        path = BASE_DIR / filename
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_config(env: dict[str, str]) -> ResearchLabConfig:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return ResearchLabConfig(
        telegram_bot_token=env.get("TELEGRAM_BOT_TOKEN", "").strip(),
        allowed_chat_id=env.get("RESEARCH_ALLOWED_CHAT_ID", "8749935590").strip() or "8749935590",
        market_results_file=Path(env.get("RESEARCH_MARKET_RESULTS_FILE", str(DEFAULT_MARKET_RESULTS))).expanduser(),
        history_file=Path(env.get("RESEARCH_HISTORY_FILE", str(DATA_DIR / "research_history.jsonl"))).expanduser(),
        poll_timeout=int(env.get("RESEARCH_TELEGRAM_POLL_TIMEOUT", "30")),
        request_timeout=int(env.get("RESEARCH_REQUEST_TIMEOUT", "20")),
        hot_limit=max(1, min(20, int(env.get("RESEARCH_HOT_LIMIT", "12")))),
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"completed_jobs": {}, "daily_jobs": {}}


def write_state(state: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(STATE_FILE)


def append_log(event: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    event.setdefault("logged_at", utc_now_iso())
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def acquire_lock() -> bool:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(utc_now_iso())
        return True
    except FileExistsError:
        try:
            modified_at = datetime.fromtimestamp(LOCK_FILE.stat().st_mtime, timezone.utc)
            if datetime.now(timezone.utc) - modified_at > timedelta(hours=2):
                LOCK_FILE.unlink(missing_ok=True)
                return acquire_lock()
        except OSError:
            pass
        return False


def release_lock() -> None:
    LOCK_FILE.unlink(missing_ok=True)


def env_holidays(schedule: MarketSchedule, env: dict[str, str]) -> set[str]:
    configured = {
        item.strip()
        for item in env.get(schedule.holiday_env, "").split(",")
        if item.strip()
    }
    return schedule.default_holidays | configured


def is_trading_day(schedule: MarketSchedule, local_date: date, env: dict[str, str]) -> tuple[bool, str]:
    if local_date.weekday() >= 5:
        return False, "weekend"
    if local_date.isoformat() in env_holidays(schedule, env):
        return False, "market_holiday"
    return True, "trading_day"


def in_window(local_now: datetime, target: time, delay_minutes: int, window_minutes: int) -> bool:
    start = datetime.combine(local_now.date(), target, tzinfo=local_now.tzinfo) + timedelta(minutes=delay_minutes)
    end = start + timedelta(minutes=window_minutes)
    return start <= local_now <= end


def slot_due(local_now: datetime, slot: ResearchSlot) -> bool:
    start = datetime.combine(local_now.date(), slot.local_time, tzinfo=local_now.tzinfo)
    end = start + timedelta(minutes=slot.window_minutes)
    return start <= local_now <= end


def slot_window_end(local_now: datetime, slot: ResearchSlot) -> datetime:
    start = datetime.combine(local_now.date(), slot.local_time, tzinfo=local_now.tzinfo)
    return start + timedelta(minutes=slot.window_minutes)


def primary_retry_deadline(local_now: datetime, slot: ResearchSlot) -> datetime:
    start = datetime.combine(local_now.date(), slot.local_time, tzinfo=local_now.tzinfo)
    return start + timedelta(minutes=20)


def retry_times(slot: ResearchSlot) -> list[str]:
    attempts = []
    cursor = datetime.combine(date(2000, 1, 1), slot.local_time)
    end = cursor + timedelta(minutes=20 if slot.key == "PRIMARY" else slot.window_minutes)
    while cursor <= end:
        attempts.append(cursor.strftime("%H:%M"))
        cursor += timedelta(minutes=5)
    return attempts


def due_slots(now: datetime, env: dict[str, str]) -> list[tuple[str, MarketSchedule, ResearchSlot, datetime]]:
    due = []
    for market_key, schedule in MARKETS.items():
        tz = ZoneInfo(schedule.timezone)
        local_now = now.astimezone(tz)
        trading, _ = is_trading_day(schedule, local_now.date(), env)
        if not trading:
            continue
        for slot in SCHEDULE_SLOTS[market_key]:
            if slot_due(local_now, slot):
                due.append((market_key, schedule, slot, local_now))
    return due


def snapshot_job_id(market_key: str, slot: ResearchSlot, trading_date: str) -> str:
    return f"{market_key}_{slot.key}_{trading_date}"


def terminal_snapshot_status(status_value: str | None) -> bool:
    return status_value in {JOB_STATUS_COMPLETED, JOB_STATUS_SKIPPED_NO_FRESH_SNAPSHOT}


def job_status(job: dict[str, Any] | None) -> str | None:
    if not job:
        return None
    return str(job.get("status") or JOB_STATUS_COMPLETED)


def stale_running_job(job: dict[str, Any] | None, now: datetime, minutes: int = 30) -> bool:
    if job_status(job) != JOB_STATUS_RUNNING:
        return False
    try:
        updated_at = datetime.fromisoformat(str(job.get("updated_at", "")).replace("Z", "+00:00"))
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return now - updated_at.astimezone(timezone.utc) > timedelta(minutes=minutes)


def update_snapshot_job(
    state: dict[str, Any],
    job_id: str,
    *,
    market_key: str,
    slot: ResearchSlot,
    trading_date: str,
    status_value: str,
    reason: str | None = None,
    reference_timestamp: str | None = None,
    records: int | None = None,
    local_now: datetime | None = None,
) -> dict[str, Any]:
    completed_jobs = state.setdefault("completed_jobs", {})
    job = completed_jobs.setdefault(
        job_id,
        {
            "market": market_key,
            "slot": slot.key,
            "phase": slot.phase,
            "snapshot_type": slot.snapshot_type,
            "trading_date": trading_date,
            "official_evaluation": slot.official_evaluation,
            "created_at": utc_now_iso(),
        },
    )
    attempts = job.setdefault("attempts", [])
    attempt_time = (local_now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    if not attempts or attempts[-1].get("attempted_at") != attempt_time or attempts[-1].get("reason") != reason:
        attempts.append({"attempted_at": attempt_time, "reason": reason or status_value})
    job["status"] = status_value
    job["updated_at"] = utc_now_iso()
    if reason:
        job["reason"] = reason
    if reference_timestamp:
        job["reference_timestamp"] = reference_timestamp
    if records is not None:
        job["records"] = records
    return job


def due_open_markets(now: datetime, env: dict[str, str]) -> list[tuple[str, MarketSchedule, datetime]]:
    due = []
    for market_key, schedule in MARKETS.items():
        tz = ZoneInfo(schedule.timezone)
        local_now = now.astimezone(tz)
        trading, _ = is_trading_day(schedule, local_now.date(), env)
        if trading and in_window(local_now, schedule.open_time, schedule.open_delay_minutes, schedule.open_window_minutes):
            due.append((market_key, schedule, local_now))
    return due


def due_close_markets(now: datetime, env: dict[str, str]) -> list[tuple[str, MarketSchedule, datetime]]:
    due = []
    for market_key, schedule in MARKETS.items():
        tz = ZoneInfo(schedule.timezone)
        local_now = now.astimezone(tz)
        trading, _ = is_trading_day(schedule, local_now.date(), env)
        if trading and in_window(local_now, schedule.close_time, schedule.close_delay_minutes, schedule.close_window_minutes):
            due.append((market_key, schedule, local_now))
    return due


def parse_snapshot_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for suffix, tz_name in [
        (" KST", "Asia/Seoul"),
        (" EDT", "America/New_York"),
        (" EST", "America/New_York"),
        (" PDT", "America/Vancouver"),
        (" PST", "America/Vancouver"),
    ]:
        if text.endswith(suffix):
            clean = text[: -len(suffix)]
            try:
                return datetime.strptime(clean, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(tz_name)).astimezone(timezone.utc)
            except ValueError:
                return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def snapshot_timestamp(row: pd.Series, fallback_mtime: datetime) -> str:
    for key in ("mobile_intel_generated_at", "data_generated_at", "file_updated_at"):
        value = str(row.get(key, "") or "").strip()
        if value:
            return value
    return fallback_mtime.astimezone(ZoneInfo("America/Vancouver")).strftime("%Y-%m-%d %H:%M:%S %Z")


def validate_snapshot(
    config: ResearchLabConfig,
    schedule: MarketSchedule,
    now: datetime,
    env: dict[str, str],
) -> tuple[pd.DataFrame | None, str, str | None]:
    path = config.market_results_file
    if not path.exists():
        return None, f"SNAPSHOT_MISSING: {path}", None
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        return None, f"SNAPSHOT_READ_FAILED: {type(exc).__name__}", None
    if df.empty:
        return None, "SNAPSHOT_EMPTY", None
    required = {"ticker", "market", "price"}
    missing = sorted(required - set(df.columns))
    if missing:
        return None, f"SNAPSHOT_COLUMNS_MISSING: {','.join(missing)}", None
    market_df = df[df["market"].astype(str).isin(schedule.labels)].copy()
    if market_df.empty:
        return None, f"SNAPSHOT_MARKET_EMPTY: {schedule.key}", None
    prices = market_df["price"].apply(lambda value: _num(value))
    if prices.dropna().empty:
        return None, "SNAPSHOT_PRICE_MISSING", None

    fallback_mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    timed_rows = []
    for index, row in market_df.iterrows():
        parsed_time = parse_snapshot_time(snapshot_timestamp(row, fallback_mtime))
        if parsed_time is not None:
            timed_rows.append((index, parsed_time))
    if not timed_rows:
        return None, "SNAPSHOT_TIMESTAMP_MISSING", None
    usable_rows = [(index, item) for index, item in timed_rows if (item - now).total_seconds() <= 300]
    usable_times = [item for _, item in usable_rows]
    if not usable_times:
        newest_future = min(item for _, item in timed_rows)
        age_minutes = (now - newest_future).total_seconds() / 60
        return None, f"SNAPSHOT_FROM_FUTURE: {age_minutes:.1f}m", newest_future.isoformat(timespec="seconds")
    newest = max(usable_times)
    max_age = int(env.get("RESEARCH_SNAPSHOT_MAX_AGE_MINUTES", str(DEFAULT_SNAPSHOT_MAX_AGE_MINUTES)))
    age_minutes = (now - newest).total_seconds() / 60
    if age_minutes > max_age:
        return None, f"SNAPSHOT_STALE: {age_minutes:.1f}m > {max_age}m", newest.isoformat(timespec="seconds")
    usable_index = [index for index, item in usable_rows if now - item <= timedelta(minutes=max_age)]
    return market_df.loc[usable_index].copy(), "OK", newest.isoformat(timespec="seconds")


def select_market_sample(df: pd.DataFrame, limit: int) -> list[tuple[str, pd.Series]]:
    valid_df = df[df.apply(lambda row: validate_market_row(row).get("status") == "VALID", axis=1)].copy()
    if valid_df.empty:
        return []
    df = valid_df
    change = df.get("change_pct", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
    volume = df.get("volume_ratio", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
    news_ok = df.apply(lambda row: validate_news_row(row).get("status") == "NEWS_AVAILABLE", axis=1)
    rsi = df.get("rsi", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
    trade_value = df.get("trade_value", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
    ticker_sorted = df.assign(_ticker=df["ticker"].astype(str).str.upper()).sort_values("_ticker")
    buckets = [
        ("gainer", df.assign(_rank=change).sort_values(["_rank", "ticker"], ascending=[False, True])),
        ("decliner", df.assign(_rank=change).sort_values(["_rank", "ticker"], ascending=[True, True])),
        ("volume_spike", df.assign(_rank=volume).sort_values(["_rank", "ticker"], ascending=[False, True])),
        ("news", df[news_ok].assign(_ticker=df[news_ok]["ticker"].astype(str).str.upper()).sort_values("_ticker")),
        ("already_risen", df[(change >= 5) | (rsi >= 70)].assign(_rank=change).sort_values(["_rank", "ticker"], ascending=[False, True])),
        ("large_liquid", df.assign(_rank=trade_value).sort_values(["_rank", "ticker"], ascending=[False, True])),
        ("mid_small", df.assign(_rank=trade_value).sort_values(["_rank", "ticker"], ascending=[True, True])),
        ("general", ticker_sorted),
    ]
    seen: set[str] = set()
    selected: list[tuple[str, pd.Series]] = []
    per_bucket = max(2, min(6, (limit + len(buckets) - 1) // len(buckets)))
    for category, bucket in buckets:
        added = 0
        for _, row in bucket.head(max(per_bucket * 3, per_bucket)).iterrows():
            ticker = str(row.get("ticker", "")).upper()
            if ticker and ticker not in seen:
                seen.add(ticker)
                selected.append((category, row.drop(labels=["_rank", "_ticker"], errors="ignore")))
                added += 1
                if added >= per_bucket:
                    break
            if len(selected) >= limit:
                return selected[:limit]
    for _, row in ticker_sorted.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            selected.append(("fill", row.drop(labels=["_rank", "_ticker"], errors="ignore")))
            if len(selected) >= limit:
                break
    return selected[:limit]


def _short(value: Any, limit: int = 170) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def market_flag(market_key: str) -> str:
    return "🇰🇷" if market_key == "KOREA" else "🇺🇸" if market_key == "US" else "🌎"


def format_reference_price(value: Any, market_key: str) -> str:
    price = _num(value)
    if price is None:
        return "DATA_UNAVAILABLE"
    if market_key == "KOREA":
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"


def format_reference_time(value: Any, market_key: str) -> str:
    parsed = parse_snapshot_time(value)
    if parsed is None:
        return str(value or "DATA_UNAVAILABLE")
    tz_name = MARKETS.get(market_key, MARKETS["US"]).timezone
    suffix = "KST" if market_key == "KOREA" else "ET" if market_key == "US" else parsed.astimezone().tzname()
    return f"{parsed.astimezone(ZoneInfo(tz_name)).strftime('%H:%M')} {suffix}"


def compact_decision_pair(record: dict[str, Any]) -> tuple[str, str]:
    existing = str(record.get("existing_ai_decision") or "N/A").upper()
    research = str(record.get("research_decision") or "N/A").upper()
    return existing, research


def kr_decision(value: Any) -> str:
    mapping = {"BUY CANDIDATE": "매수 후보", "WATCH": "관찰", "WAIT": "대기", "AVOID": "회피", "N/A": "정보 없음"}
    return mapping.get(str(value or "N/A").upper(), str(value or "정보 없음"))


def kr_risk(value: Any) -> str:
    mapping = {"LOW": "낮음", "MEDIUM": "보통", "HIGH": "높음"}
    return mapping.get(str(value or "").upper(), str(value or "정보 없음"))


def is_conflict(record: dict[str, Any]) -> bool:
    existing, research = compact_decision_pair(record)
    return existing != research


def compact_comparison_line(record: dict[str, Any]) -> str:
    existing, research = compact_decision_pair(record)
    return (
        f"{record.get('ticker')} · 기존: {kr_decision(existing)} · {record.get('existing_ai_score')} / "
        f"Research AI: {kr_decision(research)} · {record.get('research_score')}"
    )


def existing_message(record: dict[str, Any], market_key: str) -> str:
    existing, research = compact_decision_pair(record)
    return "\n".join(
        [
            "⚔️ AI 의견 충돌" if existing != research else "📊 AI 비교",
            "",
            f"{market_flag(market_key)} {record.get('ticker')}",
            str(record.get("name") or ""),
            "",
            "기준 가격:",
            format_reference_price(record.get("reference_price"), market_key),
            "",
            "기준 시각:",
            format_reference_time(record.get("reference_timestamp"), market_key),
            "",
            "기존 AI",
            f"점수: {record.get('existing_ai_score')}",
            f"판단: {kr_decision(existing)}",
            f"위험도: {kr_risk(record.get('existing_risk'))}",
            "",
            "Research AI",
            f"점수: {record.get('research_score')}",
            f"판단: {kr_decision(research)}",
            f"위험도: {kr_risk(record.get('research_risk'))}",
            "",
            "의견:",
            "다름" if existing != research else "같음",
            "",
            "결과:",
            "대기 중",
        ]
    )


def research_message(record: dict[str, Any], market_key: str) -> str:
    return existing_message(record, market_key)


def existing_summary_message(records: list[dict[str, Any]], market_key: str, slot: ResearchSlot) -> str:
    if slot.phase == "INTRADAY_MONITORING":
        return intraday_update_message(records, market_key, slot)
    conflicts = [record for record in records if is_conflict(record)]
    same_count = len(records) - len(conflicts)
    ref_time = format_reference_time(records[0].get("reference_timestamp"), market_key) if records else "DATA_UNAVAILABLE"
    lines = [
        "📊 PRIMARY 테스트" if slot.snapshot_type == "PRIMARY_TEST" else "📊 AI 스냅샷",
        "",
        f"{market_flag(market_key)} {market_key}",
        ref_time,
        "",
        "테스트:",
        str(len(records)),
        "",
        "같은 의견:",
        str(same_count),
        "",
        "다른 의견:",
        str(len(conflicts)),
        "",
        "상태:",
        "완료" if slot.official_evaluation else "대기 중",
    ]
    if conflicts:
        lines.extend(["", "━━━━━━━━━━━━━━", "", "⚔️ 의견 다른 종목", ""])
        for record in conflicts[:12]:
            lines.append(compact_comparison_line(record))
        if len(conflicts) > 12:
            lines.append(f"... 외 {len(conflicts) - 12}개")
    return "\n".join(lines)


def research_summary_message(records: list[dict[str, Any]], market_key: str, slot: ResearchSlot) -> str:
    return existing_summary_message(records, market_key, slot)


def intraday_update_message(records: list[dict[str, Any]], market_key: str, slot: ResearchSlot) -> str:
    conflicts = [record for record in records if is_conflict(record)]
    major_moves = []
    for record in records:
        change_pct = _num(record.get("close_return")) or _num(record.get("change_pct")) or _num(record.get("reference_change_pct"))
        if change_pct is not None and abs(change_pct) >= 2:
            major_moves.append((record, change_pct))
    if not conflicts and not major_moves:
        return ""
    ref_time = format_reference_time(records[0].get("reference_timestamp"), market_key) if records else slot.local_time.strftime("%H:%M")
    lines = [
        "📈 장중 업데이트",
        "",
        f"{market_flag(market_key)} {market_key}",
        ref_time,
        "",
        "추적 종목:",
        str(len(records)),
        "",
        "신호 변화:",
        str(len(conflicts)),
        "",
        "주요 변동:",
    ]
    if major_moves:
        for record, change_pct in major_moves[:8]:
            lines.append(f"{record.get('ticker')} {change_pct:+.1f}%")
    else:
        lines.append("없음")
    lines.extend(["", "Research 변화:", str(len(conflicts)), "", "기존 AI 변화:", str(len(conflicts))])
    return "\n".join(lines)


def primary_skip_message(market_key: str, slot: ResearchSlot, reason: str, attempts: list[str]) -> str:
    flag = "🇰🇷" if market_key == "KOREA" else "🇺🇸"
    return "\n".join(
        [
            "[Research Lab]",
            "",
            f"{flag} {market_key} PRIMARY 테스트",
            "",
            "상태:",
            JOB_STATUS_SKIPPED_NO_FRESH_SNAPSHOT,
            "",
            "사유:",
            "최신 Existing Scanner 스냅샷을 찾지 못했습니다.",
            "",
            "마지막 확인:",
            reason,
            "",
            "재확인:",
            "\n".join(attempts),
        ]
    )


def send_telegram(token: str, chat_id: str, text: str, timeout: int) -> tuple[bool, str]:
    if not token:
        return False, "TOKEN_MISSING"
    if not chat_id:
        return False, "CHAT_ID_MISSING"
    try:
        chunks = [text[i : i + TELEGRAM_MAX_LENGTH] for i in range(0, len(text), TELEGRAM_MAX_LENGTH)] or [""]
        for chunk in chunks:
            response = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=timeout,
            )
            if not response.ok:
                try:
                    detail = response.json().get("description", "")
                except Exception:
                    detail = response.text[:120]
                return False, f"HTTP_{response.status_code}:{detail}"
        return True, "SEND_SUCCESS"
    except requests.Timeout:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, f"{type(exc).__name__}:{str(exc)[:120]}"


def run_market_open(market_key: str, *, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    return run_snapshot_slot(market_key, "PRIMARY", dry_run=dry_run, now=now)


def run_snapshot_slot(
    market_key: str,
    slot_key: str,
    *,
    dry_run: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    env = load_env_files()
    config = load_config(env)
    schedule = MARKETS[market_key]
    slot = next((item for item in SCHEDULE_SLOTS[market_key] if item.key == slot_key), None)
    if slot is None:
        return {"status": "SKIPPED", "market": market_key, "reason": f"UNKNOWN_SLOT:{slot_key}"}
    if slot.phase == "CLOSE_EVALUATION":
        return run_daily_close(market_key, dry_run=dry_run, now=now)

    local_now = now.astimezone(ZoneInfo(schedule.timezone))
    trading, trading_reason = is_trading_day(schedule, local_now.date(), env)
    if not trading:
        return {"status": "SKIPPED", "market": market_key, "slot": slot.key, "reason": trading_reason}
    trading_date = local_now.date().isoformat()
    job_id = snapshot_job_id(market_key, slot, trading_date)
    state = read_state()
    completed_jobs = state.setdefault("completed_jobs", {})
    existing_job = completed_jobs.get(job_id)
    existing_status = job_status(existing_job)
    if terminal_snapshot_status(existing_status):
        return {
            "status": "SKIPPED",
            "market": market_key,
            "slot": slot.key,
            "reason": "DUPLICATE",
            "job_id": job_id,
            "job_status": existing_status,
        }
    if existing_status == JOB_STATUS_RUNNING:
        if stale_running_job(existing_job, now):
            existing_job["status"] = JOB_STATUS_PENDING
            existing_job["reason"] = "STALE_RUNNING_RECOVERED"
            existing_job["updated_at"] = utc_now_iso()
            write_state(state)
        else:
            return {
                "status": "SKIPPED",
                "market": market_key,
                "slot": slot.key,
                "reason": "ALREADY_RUNNING",
                "job_id": job_id,
            }

    market_df, validation, snapshot_time = validate_snapshot(config, schedule, now, env)
    if market_df is None:
        is_primary = slot.key == "PRIMARY"
        final_retry = is_primary and local_now >= primary_retry_deadline(local_now, slot)
        status_value = JOB_STATUS_SKIPPED_NO_FRESH_SNAPSHOT if final_retry else JOB_STATUS_PENDING
        append_log(
            {
                "event": "slot_snapshot_unavailable",
                "market": market_key,
                "slot": slot.key,
                "reason": validation,
                "status": status_value,
                "dry_run": dry_run,
            }
        )
        if not dry_run:
            update_snapshot_job(
                state,
                job_id,
                market_key=market_key,
                slot=slot,
                trading_date=trading_date,
                status_value=status_value,
                reason=validation,
                local_now=local_now,
            )
            write_state(state)
            if final_retry:
                token = config.telegram_bot_token or env.get("BACKTEST_BOT_TOKEN", "").strip()
                chat_id = config.allowed_chat_id or env.get("BACKTEST_CHAT_ID", "8749935590").strip()
                send_telegram(token, chat_id, primary_skip_message(market_key, slot, validation, retry_times(slot)), config.request_timeout)
            elif not is_primary:
                notify_failure(env, config, market_key, slot.phase, f"MONITORING_SKIPPED_STALE_DATA: {validation}")
        if is_primary:
            return {
                "status": status_value,
                "market": market_key,
                "slot": slot.key,
                "reason": validation,
                "job_id": job_id,
                "retry_until": primary_retry_deadline(local_now, slot).isoformat(timespec="minutes"),
            }
        return {
            "status": "MONITORING_SKIPPED_STALE_DATA" if slot.phase == "INTRADAY_MONITORING" else "SKIPPED",
            "market": market_key,
            "slot": slot.key,
            "reason": validation,
            "job_id": job_id,
        }

    reference_timestamp = snapshot_time or utc_now_iso()
    if not dry_run:
        update_snapshot_job(
            state,
            job_id,
            market_key=market_key,
            slot=slot,
            trading_date=trading_date,
            status_value=JOB_STATUS_RUNNING,
            reason="FRESH_SNAPSHOT_FOUND",
            reference_timestamp=reference_timestamp,
            local_now=local_now,
        )
        write_state(state)

    engine = ResearchEngine(config)
    lab = ComparisonLab(config)
    limit_key = "RESEARCH_AUTO_PRIMARY_LIMIT" if slot.official_evaluation else "RESEARCH_AUTO_MONITORING_LIMIT"
    default_limit = DEFAULT_PRIMARY_LIMIT if slot.official_evaluation else DEFAULT_MONITORING_LIMIT
    records = []
    for category, row in select_market_sample(market_df, int(env.get(limit_key, default_limit))):
        research = engine._build_result(row)
        record = lab._build_record(job_id, category, row, research, reference_timestamp).to_dict()
        record.update(
            {
                "job_id": job_id,
                "trading_date": trading_date,
                "schedule_slot": slot.key,
                "snapshot_type": slot.snapshot_type,
                "official_evaluation": slot.official_evaluation,
                "lookahead_guard": "fixed_snapshot_no_recalculation",
            }
        )
        records.append(record)
    if not records:
        append_log({"event": "slot_skipped", "market": market_key, "slot": slot.key, "reason": "NO_SAMPLE"})
        return {"status": "SKIPPED", "market": market_key, "slot": slot.key, "reason": "NO_SAMPLE"}

    if not dry_run:
        target_store = lab.store if slot.official_evaluation else JsonlStore(MONITORING_FILE)
        for record in records:
            target_store.append(record)
        market_token = env.get("MARKET_SCANNER_BOT_TOKEN", "").strip()
        market_chat = env.get("MARKET_SCANNER_CHAT_ID", "8749935590").strip() or "8749935590"
        research_token = config.telegram_bot_token
        research_chat = config.allowed_chat_id
        existing_text = existing_summary_message(records, market_key, slot)
        research_text = research_summary_message(records, market_key, slot)
        if existing_text:
            existing_ok, existing_status = send_telegram(market_token, market_chat, existing_text, config.request_timeout)
        else:
            existing_ok, existing_status = False, "NO_MEANINGFUL_INTRADAY_CHANGE"
        if research_text:
            research_ok, research_status = send_telegram(research_token, research_chat, research_text, config.request_timeout)
        else:
            research_ok, research_status = False, "NO_MEANINGFUL_INTRADAY_CHANGE"
        job = update_snapshot_job(
            state,
            job_id,
            market_key=market_key,
            slot=slot,
            trading_date=trading_date,
            status_value=JOB_STATUS_COMPLETED,
            reason="COMPLETED",
            reference_timestamp=reference_timestamp,
            records=len(records),
            local_now=local_now,
        )
        job.update(
            {
                "existing_telegram_status": existing_status,
                "research_telegram_status": research_status,
                "existing_telegram_sent": int(existing_ok),
                "research_telegram_sent": int(research_ok),
                "completed_at": utc_now_iso(),
            }
        )
        write_state(state)
    append_log(
        {
            "event": "slot_processed",
            "market": market_key,
            "slot": slot.key,
            "job_id": job_id,
            "records": len(records),
            "snapshot_type": slot.snapshot_type,
            "dry_run": dry_run,
        }
    )
    return {
        "status": "OK",
        "market": market_key,
        "slot": slot.key,
        "snapshot_type": slot.snapshot_type,
        "job_id": job_id,
        "records": len(records),
        "dry_run": dry_run,
    }


def run_monitoring_slot(market_key: str, slot_key: str, *, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    return run_snapshot_slot(market_key, slot_key, dry_run=dry_run, now=now)


def run_daily_close(market_key: str, *, dry_run: bool = False, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    env = load_env_files()
    config = load_config(env)
    schedule = MARKETS[market_key]
    local_now = now.astimezone(ZoneInfo(schedule.timezone))
    trading, trading_reason = is_trading_day(schedule, local_now.date(), env)
    if not trading:
        return {"status": "SKIPPED", "market": market_key, "reason": trading_reason}
    state = read_state()
    result_id = f"{market_key}_DAILY_RESULT_{local_now.date().isoformat()}"
    if result_id in state.setdefault("daily_jobs", {}):
        return {"status": "SKIPPED", "market": market_key, "reason": "DUPLICATE", "result_id": result_id}
    if dry_run:
        return {"status": "OK", "market": market_key, "result_id": result_id, "dry_run": True}

    lab = DailyComparisonLab(config)
    result = lab.calculate(market_key, local_now.date()) or lab._load_result(result_id)
    if not result:
        append_log({"event": "daily_skipped", "market": market_key, "reason": "NO_EVALUATABLE_RECORDS", "result_id": result_id})
        return {"status": "SKIPPED", "market": market_key, "reason": "NO_EVALUATABLE_RECORDS", "result_id": result_id}
    lab._send_once(result)
    state["daily_jobs"][result_id] = {"market": market_key, "sent_at": utc_now_iso()}
    write_state(state)
    append_log({"event": "daily_processed", "market": market_key, "result_id": result_id})
    return {"status": "OK", "market": market_key, "result_id": result_id, "dry_run": False}


def notify_failure(env: dict[str, str], config: ResearchLabConfig, market_key: str, phase: str, reason: str) -> None:
    token = config.telegram_bot_token or env.get("BACKTEST_BOT_TOKEN", "").strip()
    chat_id = config.allowed_chat_id or env.get("BACKTEST_CHAT_ID", "8749935590").strip()
    text = "\n".join(["[Research Lab 자동화 경고]", "", f"시장: {market_key}", f"단계: {phase}", f"사유: {reason}"])
    send_telegram(token, chat_id, text, config.request_timeout)


def run_due(*, dry_run: bool = False, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    env = load_env_files()
    results: list[dict[str, Any]] = []
    for market_key, _, slot, _ in due_slots(now, env):
        if slot.phase == "CLOSE_EVALUATION":
            results.append(run_daily_close(market_key, dry_run=dry_run, now=now))
        else:
            results.append(run_snapshot_slot(market_key, slot.key, dry_run=dry_run, now=now))
    if not results:
        append_log({"event": "no_due_jobs", "dry_run": dry_run})
    return results


def status(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    env = load_env_files()
    state = read_state()
    completed_jobs = state.get("completed_jobs", {})
    snapshot_status_counts: dict[str, int] = {}
    for job in completed_jobs.values():
        value = job_status(job) or "UNKNOWN"
        snapshot_status_counts[value] = snapshot_status_counts.get(value, 0) + 1
    markets = {}
    for market_key, schedule in MARKETS.items():
        local_now = now.astimezone(ZoneInfo(schedule.timezone))
        trading, reason = is_trading_day(schedule, local_now.date(), env)
        markets[market_key] = {
            "local_time": local_now.isoformat(timespec="seconds"),
            "trading_day": trading,
            "trading_reason": reason,
            "open_due": trading and in_window(local_now, schedule.open_time, schedule.open_delay_minutes, schedule.open_window_minutes),
            "close_due": trading and in_window(local_now, schedule.close_time, schedule.close_delay_minutes, schedule.close_window_minutes),
            "open_time": schedule.open_time.strftime("%H:%M"),
            "close_time": schedule.close_time.strftime("%H:%M"),
            "due_slots": [
                {
                    "slot": slot.key,
                    "phase": slot.phase,
                    "snapshot_type": slot.snapshot_type,
                    "local_time": slot.local_time.strftime("%H:%M"),
                }
                for slot in SCHEDULE_SLOTS[market_key]
                if trading and slot_due(local_now, slot)
            ],
            "schedule_slots": [
                {
                    "slot": slot.key,
                    "phase": slot.phase,
                    "snapshot_type": slot.snapshot_type,
                    "local_time": slot.local_time.strftime("%H:%M"),
                    "official_evaluation": slot.official_evaluation,
                }
                for slot in SCHEDULE_SLOTS[market_key]
            ],
            "timezone": schedule.timezone,
        }
    return {
        "now_utc": now.isoformat(timespec="seconds"),
        "state_file": str(STATE_FILE),
        "completed_jobs": len(completed_jobs),
        "snapshot_status_counts": snapshot_status_counts,
        "daily_jobs": len(state.get("daily_jobs", {})),
        "markets": markets,
    }


def parse_now(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser(description="Research Lab market-open and daily comparison automation.")
    parser.add_argument("action", choices=["run-due", "slot", "open", "monitor", "daily", "status"])
    parser.add_argument("--market", choices=sorted(MARKETS), default=None)
    parser.add_argument("--slot", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--now", default=None, help="ISO timestamp for scheduler validation tests.")
    args = parser.parse_args()

    now = parse_now(args.now)
    if args.action == "status":
        print(json.dumps(status(now), ensure_ascii=False, indent=2, sort_keys=True))
        return

    if not acquire_lock():
        payload = {"status": "SKIPPED", "reason": "LOCKED"}
        append_log({"event": "locked"})
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    try:
        if args.action == "run-due":
            payload = run_due(dry_run=args.dry_run, now=now)
        elif args.action == "slot":
            if not args.market or not args.slot:
                raise SystemExit("--market and --slot are required for slot")
            payload = run_snapshot_slot(args.market, args.slot, dry_run=args.dry_run, now=now)
        elif args.action == "open":
            if not args.market:
                raise SystemExit("--market is required for open")
            payload = run_market_open(args.market, dry_run=args.dry_run, now=now)
        elif args.action == "monitor":
            if not args.market or not args.slot:
                raise SystemExit("--market and --slot are required for monitor")
            payload = run_monitoring_slot(args.market, args.slot, dry_run=args.dry_run, now=now)
        elif args.action == "daily":
            if not args.market:
                raise SystemExit("--market is required for daily")
            payload = run_daily_close(args.market, dry_run=args.dry_run, now=now)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        release_lock()


if __name__ == "__main__":
    main()
