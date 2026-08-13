#!/usr/bin/env python3

import csv
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
LOCK_FILE = BASE_DIR / ".mobile_market_daily_update.lock"
LOG_PREFIX = "mobile-market-daily"
VANCOUVER_TZ = ZoneInfo("America/Vancouver")
IOS_RESULT_FILE = BASE_DIR / "MarketScannerIOS" / "MarketScannerIOS" / "market_scanner_results.csv"
MARKET_RESULT_FILE = BASE_DIR / "market_scanner_results.csv"
BACKTEST_ENV_FILE = BASE_DIR / ".env.backtest"
MARKET_ENV_FILE = BASE_DIR / ".env.market_scanner"
MOBILE_UPDATE_ENV_FILE = BASE_DIR / ".env.mobile_update"
TELEGRAM_MAX_LENGTH = 3900
MIN_TOTAL_ROWS_FOR_APP_SYNC = 500
MIN_OK_ROWS_FOR_APP_SYNC = 50


def python_bin() -> str:
    venv_python = BASE_DIR / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python)
    return sys.executable


def run_step(name: str, args: List[str], env_update: Optional[Dict[str, str]] = None) -> int:
    env = os.environ.copy()
    if env_update:
        env.update(env_update)

    started_at = datetime.now(VANCOUVER_TZ)
    print(f"[{LOG_PREFIX}] start {name}: {started_at:%Y-%m-%d %H:%M:%S %Z}", flush=True)
    completed = subprocess.run(args, cwd=BASE_DIR, env=env, check=False)
    finished_at = datetime.now(VANCOUVER_TZ)
    print(
        f"[{LOG_PREFIX}] done {name}: code={completed.returncode} at {finished_at:%Y-%m-%d %H:%M:%S %Z}",
        flush=True,
    )
    return completed.returncode


def load_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    values: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def send_status_report(lines: List[str]) -> None:
    env = load_env_file(MOBILE_UPDATE_ENV_FILE) or load_env_file(BACKTEST_ENV_FILE) or load_env_file(MARKET_ENV_FILE)
    token = env.get("MOBILE_UPDATE_BOT_TOKEN") or env.get("BACKTEST_BOT_TOKEN") or env.get("MARKET_SCANNER_BOT_TOKEN")
    chat_id = env.get("MOBILE_UPDATE_CHAT_ID") or env.get("BACKTEST_CHAT_ID") or env.get("MARKET_SCANNER_CHAT_ID")
    if not token or not chat_id:
        print(f"[{LOG_PREFIX}] telegram status skipped: missing token/chat", flush=True)
        return

    try:
        import requests

        text = "\n".join(lines)
        from telegram_message_utils import compact_telegram_message

        text = compact_telegram_message(text)
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        chunks = [text[i : i + TELEGRAM_MAX_LENGTH] for i in range(0, len(text), TELEGRAM_MAX_LENGTH)]
        for chunk in chunks:
            response = requests.post(
                url,
                data={"chat_id": chat_id, "text": chunk, "disable_web_page_preview": True},
                timeout=12,
            )
            if not response.ok:
                print(f"[{LOG_PREFIX}] telegram status failed: HTTP {response.status_code}", flush=True)
                return
        print(f"[{LOG_PREFIX}] telegram status sent", flush=True)
    except Exception as exc:
        print(f"[{LOG_PREFIX}] telegram status failed: {exc}", flush=True)


def sync_ios_csv() -> int:
    if not MARKET_RESULT_FILE.exists():
        print(f"[{LOG_PREFIX}] missing {MARKET_RESULT_FILE.name}", flush=True)
        return 1

    with MARKET_RESULT_FILE.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    ok_rows = sum(1 for row in rows if row.get("status", "ok") == "ok")
    if len(rows) < MIN_TOTAL_ROWS_FOR_APP_SYNC:
        print(
            f"[{LOG_PREFIX}] app csv sync blocked: only {len(rows)} rows, need {MIN_TOTAL_ROWS_FOR_APP_SYNC}",
            flush=True,
        )
        return 1
    if ok_rows < MIN_OK_ROWS_FOR_APP_SYNC:
        print(
            f"[{LOG_PREFIX}] app csv sync blocked: only {ok_rows} ok rows, likely data failure",
            flush=True,
        )
        return 1

    IOS_RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MARKET_RESULT_FILE, IOS_RESULT_FILE)
    print(f"[{LOG_PREFIX}] synced {MARKET_RESULT_FILE.name} -> {IOS_RESULT_FILE}", flush=True)
    return 0


def main() -> int:
    now = datetime.now(VANCOUVER_TZ)
    print(f"[{LOG_PREFIX}] daily update requested: {now:%Y-%m-%d %H:%M:%S %Z}", flush=True)

    if now.weekday() in {5, 6}:
        print(f"[{LOG_PREFIX}] skipped on Vancouver {now:%A}", flush=True)
        return 0

    if LOCK_FILE.exists():
        print(f"[{LOG_PREFIX}] already running: {LOCK_FILE}", flush=True)
        return 0

    py = python_bin()
    LOCK_FILE.write_text(now.isoformat(), encoding="utf-8")
    try:
        steps = [
            (
                "market_scanner",
                [py, str(BASE_DIR / "run_market_scanner_update.py"), "--force"],
                {
                    "MARKET_SCANNER_ENABLE_FLOW": os.getenv("MARKET_SCANNER_ENABLE_FLOW", "true"),
                },
            ),
            (
                "quiet_money",
                [py, str(BASE_DIR / "quiet_money_scanner.py")],
                {
                    "QUIET_SEND_EMPTY_REPORT": "false",
                    "QUIET_MAX_WORKERS": os.getenv("QUIET_MAX_WORKERS", "4"),
                },
            ),
            (
                "ai_failure_memory",
                [py, str(BASE_DIR / "ai_failure_memory.py")],
                {},
            ),
            (
                "news_pulse",
                [py, str(BASE_DIR / "news_pulse_tracker.py"), "--once"],
                {"NEWS_PULSE_SEND_TELEGRAM": "false"},
            ),
            (
                "today_hot_predictor",
                [py, str(BASE_DIR / "today_hot_predictor.py")],
                {"TODAY_PICK_AUTO_REFRESH": "false"},
            ),
            (
                "mobile_intelligence_feed",
                [py, str(BASE_DIR / "mobile_intelligence_feed.py")],
                {},
            ),
            (
                "investment_horizon_recommender",
                [py, str(BASE_DIR / "investment_horizon_recommender.py")],
                {"TODAY_PICK_AUTO_REFRESH": "false"},
            ),
            (
                "market_briefing",
                [py, str(BASE_DIR / "market_briefing_bot.py"), "--once"],
                {},
            ),
        ]

        status_lines = [
            "📌 모바일 마켓 일일 업데이트",
            f"시간: {datetime.now(VANCOUVER_TZ):%Y-%m-%d %H:%M %Z}",
        ]
        failed_steps: List[str] = []

        for name, args, env_update in steps:
            code = run_step(name, args, env_update)
            status_lines.append(f"- {name}: {'완료' if code == 0 else f'실패({code})'}")
            if code != 0:
                failed_steps.append(name)
                print(f"[{LOG_PREFIX}] continuing after {name} failure", flush=True)

        sync_code = sync_ios_csv()
        status_lines.append(f"- app_csv_sync: {'완료' if sync_code == 0 else f'실패({sync_code})'}")
        if failed_steps or sync_code != 0:
            status_lines.append("일부 실패가 있어 로그 확인 필요.")
        else:
            status_lines.append("전체 순차 업데이트 완료.")
        send_status_report(status_lines)
        return sync_code if sync_code != 0 else (1 if failed_steps else 0)
    finally:
        LOCK_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
