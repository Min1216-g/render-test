#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import time
import json
import os
from pathlib import Path

from run_market_scanner_update import RESULT_FILE, upload_results_to_remote


BASE_DIR = Path(__file__).resolve().parent
PERF_REPORT_FILE = BASE_DIR / "mobile_scan_performance_report.json"


class PerfReport:
    def __init__(self) -> None:
        self.started = time.perf_counter()
        self.steps: list[dict[str, object]] = []

    def add(self, name: str, started: float, ok: bool = True, **extra: object) -> None:
        duration_ms = int((time.perf_counter() - started) * 1000)
        self.steps.append({"name": name, "duration_ms": duration_ms, "ok": ok, **extra})
        print(f"[perf] {name}: {duration_ms}ms ok={ok}", flush=True)

    def save(self, **summary: object) -> None:
        total_ms = int((time.perf_counter() - self.started) * 1000)
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "total_duration_ms": total_ms,
            "baseline_duration_ms": int(os.getenv("MOBILE_SCAN_BASELINE_MS", str(13 * 60 * 1000))),
            "target_first_ms": 3 * 60 * 1000,
            "target_final_ms": 60 * 1000,
            "steps": self.steps,
            "optimization_summary": summary,
            "skipped_stages": {
                "camera": "not_used",
                "image_processing": "not_used",
                "ocr": "not_used",
                "db_bulk_insert": "csv_pipeline",
            },
        }
        baseline = max(1, int(payload["baseline_duration_ms"]))
        payload["estimated_time_reduction_pct"] = round((1 - total_ms / baseline) * 100, 2)
        PERF_REPORT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[perf] report saved: {PERF_REPORT_FILE.name} total={total_ms}ms", flush=True)


def mobile_fast_env() -> dict[str, str]:
    env = os.environ.copy()
    if env.get("MOBILE_SCAN_FAST_MODE", "true").lower() in {"0", "false", "no"}:
        return env
    existing_workers = int(env.get("MARKET_SCANNER_MAX_WORKERS", "0") or 0)
    env["MARKET_SCANNER_MAX_WORKERS"] = str(max(existing_workers, int(env.get("MOBILE_SCAN_FAST_WORKERS", "8"))))
    env.setdefault("MARKET_SCANNER_ENABLE_INTRADAY_1M", "false")
    env.setdefault("MARKET_SCANNER_NEWS_SOURCES", "google_news")
    env.setdefault("MARKET_SCANNER_ENABLE_SECTOR_NEWS", "false")
    env.setdefault("MOBILE_INTEL_INCREMENTAL", "true")
    env.setdefault("MOBILE_INTEL_MAX_NEWS_OBSERVATIONS", "500")
    env.setdefault("MOBILE_INTEL_MAX_NEWS_PATTERNS", "50")
    return env


def run_step(name: str, command: list[str], timeout: int, perf: PerfReport, env: dict[str, str]) -> int:
    started = time.time()
    perf_started = time.perf_counter()
    print(f"start {name}: {' '.join(command)}", flush=True)
    completed = subprocess.run(command, cwd=BASE_DIR, env=env, check=False, timeout=timeout)
    duration = round(time.time() - started, 2)
    print(f"done {name}: code={completed.returncode}, {duration}s", flush=True)
    perf.add(name, perf_started, ok=completed.returncode == 0, return_code=completed.returncode)
    return completed.returncode


def main() -> int:
    perf = PerfReport()
    py = sys.executable
    env = mobile_fast_env()
    perf.save(
        status="started",
        api_call_policy="batch where available, reduced mobile news sources",
        cache_policy="incremental mobile intel enabled",
    )
    scanner_code = run_step("market_scanner_update", [py, str(BASE_DIR / "run_market_scanner_update.py"), "--force"], 3000, perf, env)
    if scanner_code != 0:
        perf.save(status="failed_at_scanner")
        return scanner_code

    intel_script = BASE_DIR / "mobile_intelligence_feed.py"
    if intel_script.exists():
        intel_code = run_step("mobile_intelligence_feed", [py, str(intel_script)], 300, perf, env)
        if intel_code != 0:
            print("mobile intelligence failed, keeping scanner CSV", flush=True)

    print("upload final mobile CSV", flush=True)
    upload_started = time.perf_counter()
    upload_results_to_remote(RESULT_FILE)
    perf.add("remote_upload", upload_started, ok=True)
    perf.save(
        status="completed",
        api_call_policy="mobile fast mode uses reduced news sources and disabled 1m intraday",
        cache_policy="unchanged mobile intelligence rows reused",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
