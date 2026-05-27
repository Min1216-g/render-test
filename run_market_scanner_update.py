#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
SCANNER = BASE_DIR / "market_scanner.py"
AI_FAILURE_MEMORY = BASE_DIR / "ai_failure_memory.py"
RESULT_FILE = BASE_DIR / "market_scanner_results.csv"
IOS_RESULT_FILE = BASE_DIR / "MarketScannerIOS" / "MarketScannerIOS" / "market_scanner_results.csv"
LOCK_FILE = BASE_DIR / ".market_scanner_update.lock"
STATE_FILE = BASE_DIR / ".market_scanner_update_state"
VANCOUVER_TZ = ZoneInfo("America/Vancouver")
VANCOUVER_RUN_TIMES = {(15, 0), (15, 30), (16, 0)}
VANCOUVER_SKIP_WEEKDAYS = {4, 5}
MIN_TOTAL_ROWS_FOR_APP_SYNC = 500
MIN_OK_ROWS_FOR_APP_SYNC = 50
REMOTE_UPLOAD_URL = os.getenv("MARKET_SCANNER_REMOTE_UPLOAD_URL", "https://market-scanner-api-fo2m.onrender.com/api/results/upload").strip()
REMOTE_API_TOKEN = os.getenv("MARKET_API_TOKEN", "").strip()


def should_run_now(force: bool) -> tuple[bool, str]:
    now = datetime.now(VANCOUVER_TZ)
    if force:
        return True, f"force run at Vancouver {now:%Y-%m-%d %H:%M %Z}"

    if now.weekday() in VANCOUVER_SKIP_WEEKDAYS:
        return False, f"skip on Vancouver {now:%A} {now:%Y-%m-%d %H:%M %Z}"

    run_key = f"{now:%Y-%m-%d-%H-%M}"
    last_run_key = STATE_FILE.read_text(encoding="utf-8").strip() if STATE_FILE.exists() else ""
    if (now.hour, now.minute) in VANCOUVER_RUN_TIMES and last_run_key != run_key:
        return True, f"scheduled run at Vancouver {now:%Y-%m-%d %H:%M %Z}"
    return False, f"skip at Vancouver {now:%Y-%m-%d %H:%M %Z}"


def result_file_is_safe_for_app(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, f"missing result file: {path}"
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        return False, f"result file unreadable: {exc}"

    total_rows = len(df)
    ok_rows = int((df.get("status", "") == "ok").sum()) if "status" in df.columns else total_rows
    if total_rows < MIN_TOTAL_ROWS_FOR_APP_SYNC:
        return False, f"app sync blocked: only {total_rows} rows, need at least {MIN_TOTAL_ROWS_FOR_APP_SYNC}"
    if ok_rows < MIN_OK_ROWS_FOR_APP_SYNC:
        return False, f"app sync blocked: only {ok_rows} ok rows, likely network/data failure"
    return True, f"result safe: {total_rows} rows, {ok_rows} ok rows"


def upload_results_to_remote(path: Path) -> None:
    if not REMOTE_UPLOAD_URL or not REMOTE_API_TOKEN:
        print("remote upload skipped: MARKET_API_TOKEN not set", flush=True)
        return
    try:
        response = requests.post(
            REMOTE_UPLOAD_URL,
            data=path.read_bytes(),
            headers={
                "X-Market-Token": REMOTE_API_TOKEN,
                "Content-Type": "text/csv; charset=utf-8",
            },
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        print(
            f"remote upload ok: {payload.get('ok_rows', '?')}/{payload.get('rows', '?')} rows",
            flush=True,
        )
    except Exception as exc:
        print(f"remote upload failed: {exc}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run market scanner on KST schedule and sync app CSV.")
    parser.add_argument("--force", action="store_true", help="Run regardless of KST schedule.")
    args = parser.parse_args()

    run, reason = should_run_now(args.force)
    print(reason, flush=True)
    if not run:
        return 0

    if LOCK_FILE.exists():
        print(f"already running: {LOCK_FILE}", flush=True)
        return 0

    LOCK_FILE.write_text(str(datetime.now()), encoding="utf-8")
    try:
        completed = subprocess.run(
            [sys.executable, str(SCANNER)],
            cwd=BASE_DIR,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode

        failure_completed = subprocess.run(
            [sys.executable, str(AI_FAILURE_MEMORY)],
            cwd=BASE_DIR,
            check=False,
        )
        if failure_completed.returncode != 0:
            print(f"ai failure memory skipped: code {failure_completed.returncode}", flush=True)

        safe, safe_reason = result_file_is_safe_for_app(RESULT_FILE)
        print(safe_reason, flush=True)
        if not safe:
            return 1

        IOS_RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RESULT_FILE, IOS_RESULT_FILE)
        print(f"synced {RESULT_FILE.name} -> {IOS_RESULT_FILE}", flush=True)
        upload_results_to_remote(RESULT_FILE)
        STATE_FILE.write_text(datetime.now(VANCOUVER_TZ).strftime("%Y-%m-%d-%H-%M"), encoding="utf-8")
    finally:
        LOCK_FILE.unlink(missing_ok=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
