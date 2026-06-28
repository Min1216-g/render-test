#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from ops_guard import enforce_runtime_security
from run_market_scanner_update import RESULT_FILE, upload_results_to_remote


BASE_DIR = Path(__file__).resolve().parent
VANCOUVER_TZ = ZoneInfo("America/Vancouver")
REPORT_FILE = BASE_DIR / "run_all_market_programs_report.json"
LOG_FILE = BASE_DIR / "run_all_market_programs.log"
SECRET_PATTERNS = (
    re.compile(r"\b\d{8,12}:[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"(?i)(bot|token|api[_-]?key|secret|password)([=: /]+)([^\s\"']{8,})"),
)


@dataclass(frozen=True)
class ProgramStep:
    name: str
    command: list[str]
    env: dict[str, str] | None = None
    timeout_seconds: int = 900
    optional: bool = False


def python_bin() -> str:
    venv_python = BASE_DIR / ".venv" / "bin" / "python"
    return str(venv_python) if venv_python.exists() else sys.executable


def write_log(line: str) -> None:
    timestamp = datetime.now(VANCOUVER_TZ).strftime("%Y-%m-%d %H:%M:%S %Z")
    message = f"[{timestamp}] {line}"
    print(message, flush=True)
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def sanitize_log_text(text: str) -> str:
    safe = str(text or "")
    safe = SECRET_PATTERNS[0].sub("[telegram-token-hidden]", safe)
    safe = SECRET_PATTERNS[1].sub(lambda match: f"{match.group(1)}{match.group(2)}[hidden]", safe)
    return safe


def step_plan(py: str, quick: bool = False) -> list[ProgramStep]:
    scanner_env = {
        "MARKET_SCANNER_ENABLE_FLOW": os.getenv("MARKET_SCANNER_ENABLE_FLOW", "true"),
    }
    if quick:
        scanner_env["MARKET_SCANNER_MAX_STOCKS"] = os.getenv("MARKET_SCANNER_MAX_STOCKS", "0")

    return [
        ProgramStep("security_check", [py, str(BASE_DIR / "security_check.py")], timeout_seconds=120),
        ProgramStep("market_scanner", [py, str(BASE_DIR / "run_market_scanner_update.py"), "--force"], scanner_env, timeout_seconds=2400),
        ProgramStep("ai_failure_memory", [py, str(BASE_DIR / "ai_failure_memory.py")], timeout_seconds=180),
        ProgramStep("quiet_money", [py, str(BASE_DIR / "quiet_money_scanner.py")], {"QUIET_SEND_EMPTY_REPORT": "false"}, timeout_seconds=1200),
        ProgramStep("news_pulse", [py, str(BASE_DIR / "news_pulse_tracker.py"), "--once"], {"NEWS_PULSE_SEND_TELEGRAM": "false"}, timeout_seconds=900),
        ProgramStep("korean_ai_screening", [py, str(BASE_DIR / "korean_ai_screening_simulator.py"), "--screen"], timeout_seconds=180),
        ProgramStep("us_leader_watch", [py, str(BASE_DIR / "us_leader_watch.py")], timeout_seconds=900, optional=True),
        ProgramStep("us_under20", [py, str(BASE_DIR / "us_under20_scanner.py")], timeout_seconds=900, optional=True),
        ProgramStep("canada_leader_watch", [py, str(BASE_DIR / "canada_leader_watch.py")], timeout_seconds=900, optional=True),
        ProgramStep("today_hot_predictor", [py, str(BASE_DIR / "today_hot_predictor.py")], {"TODAY_PICK_AUTO_REFRESH": "false"}, timeout_seconds=600),
        ProgramStep("mobile_intelligence_feed", [py, str(BASE_DIR / "mobile_intelligence_feed.py")], timeout_seconds=180),
        ProgramStep("investment_horizon", [py, str(BASE_DIR / "investment_horizon_recommender.py")], timeout_seconds=600, optional=True),
        ProgramStep("market_briefing", [py, str(BASE_DIR / "market_briefing_bot.py"), "--once"], timeout_seconds=300, optional=True),
    ]


def run_step(step: ProgramStep) -> dict[str, object]:
    env = os.environ.copy()
    if step.env:
        env.update(step.env)

    started = time.time()
    write_log(f"start {step.name}")
    try:
        completed = subprocess.run(
            step.command,
            cwd=BASE_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=step.timeout_seconds,
            check=False,
        )
        duration = round(time.time() - started, 2)
        ok = completed.returncode == 0
        write_log(f"done {step.name}: code={completed.returncode}, {duration}s")
        return {
            "name": step.name,
            "ok": ok,
            "optional": step.optional,
            "returncode": completed.returncode,
            "duration_seconds": duration,
            "stdout_tail": sanitize_log_text(completed.stdout[-2500:]),
            "stderr_tail": sanitize_log_text(completed.stderr[-2500:]),
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.time() - started, 2)
        write_log(f"timeout {step.name}: {duration}s")
        return {
            "name": step.name,
            "ok": False,
            "optional": step.optional,
            "returncode": 124,
            "duration_seconds": duration,
            "stdout_tail": sanitize_log_text((exc.stdout or "")[-2500:]) if isinstance(exc.stdout, str) else "",
            "stderr_tail": "timeout",
        }


def save_report(items: list[dict[str, object]]) -> None:
    payload = {
        "generated_at": datetime.now(VANCOUVER_TZ).isoformat(),
        "ok": all(item["ok"] or item["optional"] for item in items),
        "steps": items,
    }
    REPORT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def upload_final_mobile_result() -> dict[str, object]:
    started = time.time()
    write_log("start final_mobile_upload")
    try:
        upload_results_to_remote(RESULT_FILE)
        duration = round(time.time() - started, 2)
        write_log(f"done final_mobile_upload: {duration}s")
        return {
            "name": "final_mobile_upload",
            "ok": True,
            "optional": False,
            "returncode": 0,
            "duration_seconds": duration,
            "stdout_tail": "final CSV upload requested",
            "stderr_tail": "",
        }
    except Exception as exc:
        duration = round(time.time() - started, 2)
        write_log(f"failed final_mobile_upload: {exc}")
        return {
            "name": "final_mobile_upload",
            "ok": False,
            "optional": False,
            "returncode": 1,
            "duration_seconds": duration,
            "stdout_tail": "",
            "stderr_tail": sanitize_log_text(str(exc)),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="원클릭 전체 마켓 프로그램 실행기")
    parser.add_argument("--quick", action="store_true", help="market scanner 종목 수를 줄여 빠르게 점검")
    parser.add_argument("--continue-on-error", action="store_true", default=True, help="실패해도 다음 프로그램 계속 실행")
    args = parser.parse_args()

    enforce_runtime_security(BASE_DIR, output_files=[REPORT_FILE, LOG_FILE])
    py = python_bin()
    results: list[dict[str, object]] = []

    for step in step_plan(py, quick=args.quick):
        item = run_step(step)
        results.append(item)
        save_report(results)
        if not item["ok"] and not args.continue_on_error and not step.optional:
            break

    if all(item["ok"] or item["optional"] for item in results):
        results.append(upload_final_mobile_result())

    save_report(results)
    failed_required = [item["name"] for item in results if not item["ok"] and not item["optional"]]
    if failed_required:
        write_log(f"required failures: {', '.join(failed_required)}")
        write_log("run: python3 program_error_doctor.py")
        return 1

    write_log("all required programs finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
