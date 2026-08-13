#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_DIR = Path(__file__).resolve().parent
VANCOUVER_TZ = ZoneInfo("America/Vancouver")
SKIP_WEEKDAYS = {5, 6}  # Saturday, Sunday in Vancouver. Python: Monday=0.


def run_command(command: list[str]) -> int:
    print("running:", " ".join(command), flush=True)
    completed = subprocess.run(command, cwd=BASE_DIR, check=False)
    print("exit code:", completed.returncode, flush=True)
    return completed.returncode


def require_upload_token() -> bool:
    if os.getenv("MARKET_API_TOKEN", "").strip():
        print("upload token: configured", flush=True)
        return True
    print("upload token: missing MARKET_API_TOKEN, mobile app will not receive cron results", flush=True)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Render cron entrypoint with Vancouver-time guard.")
    parser.add_argument("--slot", type=int, choices=(5, 16, 17), help="Vancouver hour to run.")
    parser.add_argument("--mode", choices=("auto", "scanner", "full"), default="auto", help="Program set to run.")
    parser.add_argument("--force", action="store_true", help="Run even if the current Vancouver hour does not match.")
    args = parser.parse_args()

    now = datetime.now(VANCOUVER_TZ)
    print(f"render cron check: Vancouver {now:%Y-%m-%d %H:%M:%S %Z}", flush=True)

    if now.weekday() in SKIP_WEEKDAYS and not args.force:
        print(f"skip: Vancouver {now:%A}", flush=True)
        return 0

    mode = args.mode
    if mode == "auto":
        if now.hour == 16:
            mode = "scanner"
        elif now.hour == 17:
            mode = "full"
        elif now.hour == 5:
            mode = "scanner"
        elif args.force:
            mode = "scanner"
        else:
            print(f"skip: current hour {now.hour}:00 is not 05:00, 16:00 or 17:00 Vancouver", flush=True)
            return 0
    elif args.slot is not None and now.hour != args.slot and not args.force:
        print(f"skip: slot {args.slot}:00, current hour {now.hour}:00", flush=True)
        return 0

    if mode == "scanner":
        if not require_upload_token():
            return 2
        return run_command([sys.executable, str(BASE_DIR / "render_mobile_refresh.py")])

    if not require_upload_token():
        return 2
    return run_command([sys.executable, str(BASE_DIR / "render_mobile_refresh.py")])


if __name__ == "__main__":
    raise SystemExit(main())
