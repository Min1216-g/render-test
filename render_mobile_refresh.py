#!/usr/bin/env python3

from __future__ import annotations

import subprocess
import sys
import time
import json
import os
import csv
from datetime import datetime, timezone
from pathlib import Path

from runtime_job_guard import InterProcessJobLock
from run_market_scanner_update import RESULT_FILE, upload_results_to_remote


BASE_DIR = Path(__file__).resolve().parent
PERF_REPORT_FILE = BASE_DIR / "mobile_scan_performance_report.json"
HEAVY_JOB_STALE_SECONDS = int(os.getenv("MARKET_HEAVY_JOB_STALE_SECONDS", "7200"))
MOBILE_INTEL_MAX_AGE_HOURS = float(os.getenv("MARKET_MOBILE_INTEL_MAX_AGE_HOURS", "8"))


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
    render_default_workers = "3" if env.get("RENDER") else "4"
    requested_workers = int(env.get("MOBILE_SCAN_FAST_WORKERS", render_default_workers) or render_default_workers)
    existing_workers = int(env.get("MARKET_SCANNER_MAX_WORKERS", requested_workers) or requested_workers)
    max_workers = int(env.get("MARKET_SCANNER_RENDER_WORKER_CAP", render_default_workers) or render_default_workers)
    env["MARKET_SCANNER_MAX_WORKERS"] = str(max(1, min(existing_workers, requested_workers, max_workers)))
    env.setdefault("MARKET_SCANNER_ENABLE_INTRADAY_1M", "false")
    env.setdefault("MARKET_SCANNER_NEWS_SOURCES", "google_news")
    env.setdefault("MARKET_SCANNER_ENABLE_SECTOR_NEWS", "false")
    env.setdefault("MARKET_SCANNER_SKIP_OPTIONAL_YAHOO", "true")
    env.setdefault("CANADA_NEWS_COLLECT_TIMEOUT_SECONDS", "20")
    env.setdefault("MARKET_SCANNER_CACHE_MAX_ITEMS", "96" if env.get("RENDER") else "256")
    env.setdefault("MARKET_DATA_CACHE_MAX_ITEMS", "96" if env.get("RENDER") else "256")
    env.setdefault("MOBILE_INTEL_INCREMENTAL", "true")
    env.setdefault("MOBILE_INTEL_MAX_NEWS_OBSERVATIONS", "250" if env.get("RENDER") else "500")
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


def _parse_mobile_timestamp(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def mobile_intel_is_fresh(path: Path) -> tuple[bool, str]:
    newest: datetime | None = None
    rows = 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                rows += 1
                parsed = _parse_mobile_timestamp(row.get("mobile_intel_generated_at", ""))
                if parsed and (newest is None or parsed > newest):
                    newest = parsed
    except Exception as exc:
        return False, f"mobile intel freshness read failed: {exc}"
    if newest is None:
        return False, f"mobile_intel_generated_at missing rows={rows}"
    age_hours = (datetime.now(timezone.utc) - newest).total_seconds() / 3600
    if age_hours > MOBILE_INTEL_MAX_AGE_HOURS:
        return False, f"mobile intel stale: newest={newest.isoformat()} age_hours={age_hours:.2f}"
    return True, f"mobile intel fresh: newest={newest.isoformat()} age_hours={age_hours:.2f}"


def main() -> int:
    perf = PerfReport()
    py = sys.executable
    env = mobile_fast_env()
    lock = None
    if env.get("MARKET_HEAVY_JOB_LOCK_HELD_BY_PARENT") != "1":
        lock = InterProcessJobLock("render_mobile_refresh", stale_after_seconds=HEAVY_JOB_STALE_SECONDS)
        lock_ok, holder = lock.acquire()
        if not lock_ok:
            perf.save(status="skipped_already_running", lock_holder=holder)
            print(f"skip render_mobile_refresh: heavy job already running {holder}", flush=True)
            return 0
    perf.save(
        status="started",
        api_call_policy="batch where available, reduced mobile news sources",
        cache_policy="incremental mobile intel enabled",
        max_workers=env.get("MARKET_SCANNER_MAX_WORKERS"),
    )
    try:
        scanner_code = run_step("market_scanner_update", [py, str(BASE_DIR / "run_market_scanner_update.py"), "--force"], 3000, perf, env)
        if scanner_code != 0:
            perf.save(status="failed_at_scanner")
            return scanner_code

        intel_script = BASE_DIR / "mobile_intelligence_feed.py"
        if intel_script.exists():
            intel_code = run_step("mobile_intelligence_feed", [py, str(intel_script)], 300, perf, env)
            if intel_code != 0:
                perf.save(status="failed_at_mobile_intelligence")
                print("mobile intelligence failed, not uploading stale scanner CSV", flush=True)
                return intel_code

        fresh, fresh_reason = mobile_intel_is_fresh(RESULT_FILE)
        print(f"mobile intelligence freshness: {fresh_reason}", flush=True)
        if not fresh:
            perf.save(status="failed_stale_mobile_intelligence", freshness=fresh_reason)
            return 1

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
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
