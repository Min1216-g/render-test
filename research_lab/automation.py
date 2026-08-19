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
from .engine import ResearchEngine, _num


BASE_DIR = Path(__file__).resolve().parents[1]
STATE_FILE = DATA_DIR / "automation_state.json"
LOG_FILE = DATA_DIR / "automation_log.jsonl"
LOCK_FILE = DATA_DIR / ".automation.lock"

TELEGRAM_MAX_LENGTH = 3900
DEFAULT_SAMPLE_LIMIT = 6
DEFAULT_SNAPSHOT_MAX_AGE_MINUTES = 180


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
    for suffix, tz_name in [(" PDT", "America/Vancouver"), (" PST", "America/Vancouver")]:
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
    timestamps = [parse_snapshot_time(snapshot_timestamp(row, fallback_mtime)) for _, row in market_df.iterrows()]
    valid_times = [item for item in timestamps if item is not None]
    if not valid_times:
        return None, "SNAPSHOT_TIMESTAMP_MISSING", None
    newest = max(valid_times)
    max_age = int(env.get("RESEARCH_SNAPSHOT_MAX_AGE_MINUTES", str(DEFAULT_SNAPSHOT_MAX_AGE_MINUTES)))
    age_minutes = (now - newest).total_seconds() / 60
    if age_minutes < -5:
        return None, f"SNAPSHOT_FROM_FUTURE: {age_minutes:.1f}m", newest.isoformat(timespec="seconds")
    if age_minutes > max_age:
        return None, f"SNAPSHOT_STALE: {age_minutes:.1f}m > {max_age}m", newest.isoformat(timespec="seconds")
    return market_df, "OK", newest.isoformat(timespec="seconds")


def select_market_sample(df: pd.DataFrame, limit: int) -> list[tuple[str, pd.Series]]:
    change = df.get("change_pct", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
    volume = df.get("volume_ratio", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
    news = df.get("news_one_line", pd.Series([""] * len(df))).astype(str)
    rsi = df.get("rsi", pd.Series([0] * len(df))).apply(lambda value: _num(value, 0) or 0)
    buckets = [
        ("gainer", df.assign(_rank=change).sort_values("_rank", ascending=False)),
        ("decliner", df.assign(_rank=change).sort_values("_rank", ascending=True)),
        ("volume_spike", df.assign(_rank=volume).sort_values("_rank", ascending=False)),
        ("news", df[news.ne("") & ~news.str.contains("뉴스 없음|NO_RECENT_NEWS", na=False)]),
        ("already_risen", df[(change >= 5) | (rsi >= 70)]),
        ("general", df.sort_values("ticker")),
    ]
    seen: set[str] = set()
    selected: list[tuple[str, pd.Series]] = []
    for category, bucket in buckets:
        for _, row in bucket.iterrows():
            ticker = str(row.get("ticker", "")).upper()
            if ticker and ticker not in seen:
                seen.add(ticker)
                selected.append((category, row.drop(labels=["_rank"], errors="ignore")))
                break
            if len(selected) >= limit:
                return selected
    for _, row in df.iterrows():
        ticker = str(row.get("ticker", "")).upper()
        if ticker and ticker not in seen:
            seen.add(ticker)
            selected.append(("fill", row))
            if len(selected) >= limit:
                break
    return selected[:limit]


def _short(value: Any, limit: int = 170) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def existing_message(record: dict[str, Any], market_key: str) -> str:
    return "\n".join(
        [
            "[EXISTING SCANNER AUTO]",
            "",
            f"Market: {market_key}",
            f"Ticker: {record.get('ticker')}",
            f"Name: {record.get('name')}",
            f"Price: {record.get('reference_price')}",
            f"Existing AI Score: {record.get('existing_ai_score')}",
            f"Decision: {record.get('existing_ai_decision')}",
            f"Risk: {record.get('existing_risk')}",
            f"Reference Timestamp: {record.get('reference_timestamp')}",
            f"Reference Data: {record.get('reference_data_timestamp')}",
            f"Reason: {_short(record.get('existing_reason'))}",
        ]
    )


def research_message(record: dict[str, Any], market_key: str) -> str:
    bull = record.get("bull_case") or {}
    bear = record.get("bear_case") or {}
    return "\n".join(
        [
            "[RESEARCH LAB AUTO]",
            "",
            f"Market: {market_key}",
            f"Ticker: {record.get('ticker')}",
            f"Name: {record.get('name')}",
            f"Reference Price: {record.get('reference_price')}",
            f"Reference Timestamp: {record.get('reference_timestamp')}",
            f"Research Score: {record.get('research_score')}",
            f"Decision: {record.get('research_decision')}",
            f"Risk: {record.get('research_risk')}",
            f"Continuation Potential: {record.get('continuation_potential')}",
            f"Bull Case: {_short((bull.get('reasons') or ['DATA_UNAVAILABLE'])[0])}",
            f"Bear Case: {_short((bear.get('reasons') or ['DATA_UNAVAILABLE'])[0])}",
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
    now = now or datetime.now(timezone.utc)
    env = load_env_files()
    config = load_config(env)
    schedule = MARKETS[market_key]
    local_now = now.astimezone(ZoneInfo(schedule.timezone))
    trading, trading_reason = is_trading_day(schedule, local_now.date(), env)
    if not trading:
        return {"status": "SKIPPED", "market": market_key, "reason": trading_reason}

    market_df, validation, snapshot_time = validate_snapshot(config, schedule, now, env)
    if market_df is None:
        append_log({"event": "open_skipped", "market": market_key, "reason": validation})
        if not dry_run:
            notify_failure(env, config, market_key, "OPEN", validation)
        return {"status": "SKIPPED", "market": market_key, "reason": validation}

    reference_timestamp = snapshot_time or utc_now_iso()
    trading_date = local_now.date().isoformat()
    job_id = f"{market_key}_{trading_date}_{reference_timestamp}"
    state = read_state()
    completed_jobs = state.setdefault("completed_jobs", {})
    if job_id in completed_jobs:
        return {"status": "SKIPPED", "market": market_key, "reason": "DUPLICATE", "job_id": job_id}

    engine = ResearchEngine(config)
    lab = ComparisonLab(config)
    records = []
    for category, row in select_market_sample(market_df, int(env.get("RESEARCH_AUTO_SAMPLE_LIMIT", DEFAULT_SAMPLE_LIMIT))):
        research = engine._build_result(row)
        records.append(lab._build_record(job_id, category, row, research, reference_timestamp).to_dict())
    if not records:
        append_log({"event": "open_skipped", "market": market_key, "reason": "NO_SAMPLE"})
        return {"status": "SKIPPED", "market": market_key, "reason": "NO_SAMPLE"}

    if not dry_run:
        for record in records:
            lab.store.append(record)
        market_token = env.get("MARKET_SCANNER_BOT_TOKEN", "").strip()
        market_chat = env.get("MARKET_SCANNER_CHAT_ID", "8749935590").strip() or "8749935590"
        research_token = config.telegram_bot_token
        research_chat = config.allowed_chat_id
        existing_ok = 0
        research_ok = 0
        for record in records:
            ok, _ = send_telegram(market_token, market_chat, existing_message(record, market_key), config.request_timeout)
            existing_ok += int(ok)
            ok, _ = send_telegram(research_token, research_chat, research_message(record, market_key), config.request_timeout)
            research_ok += int(ok)
        completed_jobs[job_id] = {
            "market": market_key,
            "trading_date": trading_date,
            "reference_timestamp": reference_timestamp,
            "records": len(records),
            "existing_telegram_sent": existing_ok,
            "research_telegram_sent": research_ok,
            "completed_at": utc_now_iso(),
        }
        write_state(state)
    append_log({"event": "open_processed", "market": market_key, "job_id": job_id, "records": len(records), "dry_run": dry_run})
    return {"status": "OK", "market": market_key, "job_id": job_id, "records": len(records), "dry_run": dry_run}


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
    text = "\n".join(["[RESEARCH LAB AUTO WARNING]", "", f"Market: {market_key}", f"Phase: {phase}", f"Reason: {reason}"])
    send_telegram(token, chat_id, text, config.request_timeout)


def run_due(*, dry_run: bool = False, now: datetime | None = None) -> list[dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    env = load_env_files()
    results: list[dict[str, Any]] = []
    for market_key, _, _ in due_open_markets(now, env):
        results.append(run_market_open(market_key, dry_run=dry_run, now=now))
    for market_key, _, _ in due_close_markets(now, env):
        results.append(run_daily_close(market_key, dry_run=dry_run, now=now))
    if not results:
        append_log({"event": "no_due_jobs", "dry_run": dry_run})
    return results


def status(now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    env = load_env_files()
    state = read_state()
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
            "timezone": schedule.timezone,
        }
    return {
        "now_utc": now.isoformat(timespec="seconds"),
        "state_file": str(STATE_FILE),
        "completed_jobs": len(state.get("completed_jobs", {})),
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
    parser.add_argument("action", choices=["run-due", "open", "daily", "status"])
    parser.add_argument("--market", choices=sorted(MARKETS), default=None)
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
        elif args.action == "open":
            if not args.market:
                raise SystemExit("--market is required for open")
            payload = run_market_open(args.market, dry_run=args.dry_run, now=now)
        elif args.action == "daily":
            if not args.market:
                raise SystemExit("--market is required for daily")
            payload = run_daily_close(args.market, dry_run=args.dry_run, now=now)
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    finally:
        release_lock()


if __name__ == "__main__":
    main()
