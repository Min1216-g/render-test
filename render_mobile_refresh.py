#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from run_market_scanner_update import RESULT_FILE, upload_results_to_remote


BASE_DIR = Path(__file__).resolve().parent


def run_step(name: str, command: list[str], timeout: int) -> int:
    started = time.time()
    print(f"start {name}: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=BASE_DIR, check=False, timeout=timeout)
    duration = round(time.time() - started, 2)
    print(f"done {name}: code={completed.returncode}, {duration}s", flush=True)
    return completed.returncode


def main() -> int:
    py = sys.executable
    scanner_code = run_step("market_scanner_update", [py, str(BASE_DIR / "run_market_scanner_update.py"), "--force"], 3000)
    if scanner_code != 0:
        return scanner_code

    intel_script = BASE_DIR / "mobile_intelligence_feed.py"
    if intel_script.exists():
        intel_code = run_step("mobile_intelligence_feed", [py, str(intel_script)], 300)
        if intel_code != 0:
            print("mobile intelligence failed, keeping scanner CSV", flush=True)

    print("upload final mobile CSV", flush=True)
    upload_results_to_remote(RESULT_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
