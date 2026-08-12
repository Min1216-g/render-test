#!/usr/bin/env python3
"""Render-ready API server for the Market Scanner app."""

from __future__ import annotations

import csv
import gc
import json
import os
import re
import resource
import shutil
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ops_guard import sanitize_secret, validate_search_text, validate_ticker
from runtime_job_guard import InterProcessJobLock, read_lock_payload
from canada_market_guard import (
    CANADA_MARKET_LABEL,
    MIN_CANADA_ROWS_FOR_APP_SYNC,
    canada_count,
    is_canada_row,
    market_counts,
    merge_existing_canada_rows,
    normalized_market,
    serialize_csv_rows,
)
from stock_universe_guard import validate_no_stock_loss


BASE_DIR = Path(__file__).resolve().parent
RESULT_FILE = Path(os.getenv("MARKET_RESULTS_FILE", BASE_DIR / "market_scanner_results.csv"))
IOS_RESULT_FILE = BASE_DIR / "MarketScannerIOS" / "MarketScannerIOS" / "market_scanner_results.csv"
REFRESH_SCRIPT = BASE_DIR / os.getenv("MARKET_SCANNER_REFRESH_SCRIPT", "render_mobile_refresh.py")
MOBILE_INTEL_SCRIPT = BASE_DIR / "mobile_intelligence_feed.py"
SCANNER_STATUS_FILE = BASE_DIR / "scanner_run_status.json"
BUG_REPORTS_FILE = BASE_DIR / os.getenv("MARKET_BUG_REPORTS_FILE", "bug_reports.json")
API_TOKEN = os.getenv("MARKET_API_TOKEN", "")
ADMIN_TOKEN = os.getenv("MARKET_ADMIN_TOKEN", "")
ALLOW_UNAUTH_HEALTH = os.getenv("MARKET_ALLOW_UNAUTH_HEALTH", "true").lower() == "true"
FORCE_HTTPS = os.getenv("MARKET_FORCE_HTTPS", "true" if os.getenv("RENDER") else "false").lower() == "true"
RATE_LIMIT_PER_MINUTE = int(os.getenv("MARKET_RATE_LIMIT_PER_MINUTE", "90"))
CACHE_TTL_SECONDS = int(os.getenv("MARKET_RESULTS_CACHE_TTL", "20"))
RESULTS_CACHE_MAX_ROWS = int(os.getenv("MARKET_RESULTS_CACHE_MAX_ROWS", "1200"))
SCANNER_RUN_COOLDOWN_SECONDS = int(os.getenv("MARKET_SCANNER_RUN_COOLDOWN_SECONDS", "300"))
ENABLE_FULL_SCANNER = os.getenv("MARKET_ENABLE_FULL_SCANNER", "true").lower() == "true"
SCANNER_DEFAULT_MAX_WORKERS = os.getenv("MARKET_RENDER_SCANNER_MAX_WORKERS", "3" if os.getenv("RENDER") else "4")
SCANNER_DEFAULT_MAX_STOCKS = os.getenv("MARKET_RENDER_SCANNER_MAX_STOCKS", "420" if os.getenv("RENDER") else "550")
SCANNER_ENABLE_INTRADAY_1M = os.getenv("MARKET_RENDER_ENABLE_INTRADAY_1M", "false")
SCANNER_START_MAX_RSS_MB = float(os.getenv("MARKET_SCANNER_START_MAX_RSS_MB", "430" if os.getenv("RENDER") else "2048"))
HEAVY_JOB_STALE_SECONDS = int(os.getenv("MARKET_HEAVY_JOB_STALE_SECONDS", "7200"))
MAX_UPLOAD_BYTES = int(os.getenv("MARKET_RESULTS_UPLOAD_MAX_BYTES", "6000000"))
MAX_JSON_BYTES = int(os.getenv("MARKET_JSON_MAX_BYTES", "200000"))
MIN_UPLOAD_ROWS = int(os.getenv("MARKET_RESULTS_UPLOAD_MIN_ROWS", "500"))
MIN_UPLOAD_OK_ROWS = int(os.getenv("MARKET_RESULTS_UPLOAD_MIN_OK_ROWS", "50"))
RUNTIME_CLEANUP_MAX_AGE_HOURS = int(os.getenv("MARKET_RUNTIME_CLEANUP_MAX_AGE_HOURS", "24"))
RUNTIME_CLEANUP_DIRS = (
    Path(tempfile.gettempdir()) / "market-cache",
    Path(tempfile.gettempdir()) / "market-pycache",
    Path(tempfile.gettempdir()) / "market-mpl",
)

app = FastAPI(title="Market Scanner API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("MARKET_CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-Market-Token", "X-API-Token", "Authorization", "Content-Type"],
)

SAFE_MODE_PATTERN = re.compile(r"^(quick|full)$", re.IGNORECASE)
SAFE_PERIOD_PATTERN = re.compile(r"^(3mo|6mo|1y|3y|5y)$", re.IGNORECASE)


@app.on_event("startup")
def startup_cleanup() -> None:
    _cleanup_runtime_storage()


@app.middleware("http")
async def security_and_no_store_headers(request: Request, call_next):
    started = time.time()
    if FORCE_HTTPS:
        proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",", 1)[0].strip().lower()
        host = (request.url.hostname or "").lower()
        if proto != "https" and host not in {"localhost", "127.0.0.1", "::1"}:
            return JSONResponse(
                status_code=403,
                content={"ok": False, "error": "HTTPS required", "updated_at": _now_iso()},
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max(MAX_UPLOAD_BYTES, MAX_JSON_BYTES):
                return JSONResponse(
                    status_code=413,
                    content={"ok": False, "error": "request too large", "updated_at": _now_iso()},
                    headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
                )
        except ValueError:
            return JSONResponse(
                status_code=400,
                content={"ok": False, "error": "invalid content length", "updated_at": _now_iso()},
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if FORCE_HTTPS:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-Process-RSS-MB"] = str(_memory_rss_mb())
        duration_ms = int((time.time() - started) * 1000)
        if duration_ms >= 1000 or request.url.path in {"/api/scanner/run", "/api/refresh/quick", "/api/results"}:
            print(
                f"[API] {request.method} {request.url.path} status={response.status_code} duration_ms={duration_ms} rss_mb={_memory_rss_mb()}",
                flush=True,
            )
    return response

_request_log: Dict[str, Deque[float]] = defaultdict(deque)
_cache_rows: List[Dict[str, str]] = []
_cache_loaded_at = 0.0
_cache_file_mtime = 0.0
_cache_file_path = ""
_scanner_lock = threading.Lock()
_scanner_running = False
_scanner_last_seen_mtime = 0.0
_bug_reports_lock = threading.Lock()
_memory_events: Deque[Dict[str, object]] = deque(maxlen=120)


def _memory_rss_mb() -> float:
    statm = Path("/proc/self/statm")
    if statm.exists():
        try:
            pages = int(statm.read_text(encoding="utf-8").split()[1])
            return round(pages * os.sysconf("SC_PAGE_SIZE") / 1024 / 1024, 2)
        except Exception:
            pass
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = float(usage.ru_maxrss)
    if sys.platform == "darwin":
        rss = rss / 1024 / 1024
    else:
        rss = rss / 1024
    return round(rss, 2)


def _child_rss_mb(pid: int) -> float:
    if not pid:
        return 0.0
    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            check=False,
            text=True,
            capture_output=True,
            timeout=2,
        )
        rss_kb = float((result.stdout or "0").strip() or 0)
        return round(rss_kb / 1024, 2)
    except Exception:
        return 0.0


def _log_memory(stage: str, **extra: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in extra.items() if value is not None)
    print(f"[MEM] {stage} rss_mb={_memory_rss_mb()} {details}".strip(), flush=True)
    _record_memory_event(stage, **extra)


def _record_memory_event(stage: str, **extra: object) -> None:
    _memory_events.append(
        {
            "stage": stage,
            "rss_mb": _memory_rss_mb(),
            "at": _now_iso(),
            **{key: value for key, value in extra.items() if value is not None},
        }
    )


def _active_heavy_job() -> Optional[Dict[str, object]]:
    lock = InterProcessJobLock("api_probe", stale_after_seconds=HEAVY_JOB_STALE_SECONDS)
    ok, payload = lock.acquire()
    if ok:
        lock.release()
        return None
    return payload


def _scanner_memory_block_payload(mode: str) -> Optional[Dict[str, object]]:
    rss_mb = _memory_rss_mb()
    if rss_mb < SCANNER_START_MAX_RSS_MB:
        return None
    snapshot = _current_result_snapshot()
    status = {
        "running": False,
        "state": "memory_guard",
        "message": f"서버 메모리 {rss_mb}MB · 새 스캔 생략하고 마지막 데이터를 표시",
        "mode": mode,
        "rss_mb": rss_mb,
        "max_start_rss_mb": SCANNER_START_MAX_RSS_MB,
        "progress": 100,
        **snapshot,
    }
    _write_scanner_status(**status)
    _record_memory_event("scanner-start-blocked", mode=mode, max_start_rss_mb=SCANNER_START_MAX_RSS_MB)
    return {
        "ok": True,
        "started": False,
        "running": False,
        "skipped": True,
        "reason": "memory_guard",
        "message": status["message"],
        "status": status,
        "updated_at": _now_iso(),
    }


def _invalidate_results_cache() -> None:
    global _cache_rows, _cache_loaded_at, _cache_file_mtime, _cache_file_path
    _cache_rows = []
    _cache_loaded_at = 0.0
    _cache_file_mtime = 0.0
    _cache_file_path = ""
    gc.collect()


def _iter_public_rows(path: Optional[Path] = None) -> Iterable[Dict[str, str]]:
    path = path or _result_path()
    if not path.exists():
        return
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield _public_row(row)


def _current_result_snapshot() -> Dict[str, object]:
    path = _result_path()
    if not path.exists():
        return {
            "rows": 0,
            "ok_rows": 0,
            "market_counts": {},
            "canada_rows": 0,
            "file_updated_at": "",
            "data_generated_at": "",
        }
    row_count = 0
    ok_rows = 0
    generated_at = ""
    counts: Dict[str, int] = {}
    for row in _iter_public_rows(path):
        row_count += 1
        if row.get("status", "ok") == "ok":
            ok_rows += 1
        market = normalized_market(row)
        if market:
            counts[market] = counts.get(market, 0) + 1
        generated_at = max(generated_at, row.get("mobile_intel_generated_at", ""))
    return {
        "rows": row_count,
        "ok_rows": ok_rows,
        "market_counts": counts,
        "canada_rows": counts.get(CANADA_MARKET_LABEL, 0),
        "file_updated_at": _file_mtime_iso(path),
        "data_generated_at": generated_at,
    }


def _clear_runtime_api_caches() -> None:
    _invalidate_results_cache()
    for pattern in ("context_cache.json.tmp", "news_pulse_state.tmp", "tmp*.csv", ".results-*.csv"):
        for item in BASE_DIR.glob(pattern):
            try:
                item.unlink(missing_ok=True)
            except OSError:
                continue


def _safe_cleanup_path(path: Path, max_age_hours: int = RUNTIME_CLEANUP_MAX_AGE_HOURS) -> int:
    if not path.exists():
        return 0
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for item in path.iterdir():
        try:
            if item.stat().st_mtime > cutoff:
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                item.unlink(missing_ok=True)
            removed += 1
        except OSError:
            continue
    return removed


def _cleanup_runtime_storage() -> None:
    for path in RUNTIME_CLEANUP_DIRS:
        path.mkdir(parents=True, exist_ok=True)
        _safe_cleanup_path(path)
    for pattern in ("*.tmp", ".results-*.csv", "tmp*.csv"):
        for item in BASE_DIR.glob(pattern):
            try:
                if time.time() - item.stat().st_mtime > 3600:
                    item.unlink(missing_ok=True)
            except OSError:
                continue


def _read_text_tail(path: Path, max_chars: int = 4000) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_chars * 4))
            data = handle.read()
        return data.decode("utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_bug_reports_store() -> Dict[str, object]:
    if not BUG_REPORTS_FILE.exists():
        return {"reports": [], "updated_at": None}
    try:
        payload = json.loads(BUG_REPORTS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"reports": [], "updated_at": None}
    if not isinstance(payload, dict):
        return {"reports": [], "updated_at": None}
    reports = payload.get("reports")
    if not isinstance(reports, list):
        reports = []
    return {
        "reports": [report for report in reports if isinstance(report, dict)],
        "updated_at": payload.get("updated_at"),
    }


def _write_bug_reports_store(reports: List[Dict[str, object]]) -> Dict[str, object]:
    payload = {
        "reports": reports,
        "count": len(reports),
        "updated_at": _now_iso(),
    }
    BUG_REPORTS_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _bug_report_sort_value(report: Dict[str, object]) -> float:
    for key in ("updatedAt", "createdAt"):
        value = report.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    return 0.0


def _merge_bug_reports(
    existing: List[Dict[str, object]],
    incoming: List[Dict[str, object]],
) -> tuple[List[Dict[str, object]], int]:
    merged: Dict[str, Dict[str, object]] = {}
    changed = 0
    for report in existing:
        report_id = str(report.get("id") or "").strip()
        if report_id:
            merged[report_id] = report
    for report in incoming:
        report_id = str(report.get("id") or "").strip()
        if not report_id:
            continue
        current = merged.get(report_id)
        if current is None or _bug_report_sort_value(report) >= _bug_report_sort_value(current):
            if current != report:
                changed += 1
            merged[report_id] = report
    reports = sorted(merged.values(), key=_bug_report_sort_value, reverse=True)
    return reports, changed


def _bug_report_prefix(report: Dict[str, object]) -> str:
    report_type = str(report.get("type") or "").strip()
    if report_type == "fix":
        return "FIX"
    if report_type == "improvement":
        return "IMP"
    if report_type == "data":
        return "DATA"
    if report_type == "ui":
        return "UI"
    return "BUG"


def _bug_report_display_id(report: Dict[str, object]) -> str:
    sequence = report.get("sequence")
    try:
        sequence_int = int(sequence)
    except (TypeError, ValueError):
        sequence_int = 0
    return f"{_bug_report_prefix(report)}-{sequence_int:03d}"


BUG_ID_PATTERN = re.compile(r"\b(?:BUG|FIX|IMP|DATA|UI)-\d{1,5}\b", re.IGNORECASE)


def _normalize_supplied_git_commits(commits: object) -> List[Dict[str, str]]:
    if not isinstance(commits, list):
        return []
    normalized: List[Dict[str, str]] = []
    for item in commits:
        if not isinstance(item, dict):
            continue
        commit_hash = str(item.get("hash") or item.get("id") or item.get("sha") or "").strip()
        message = str(item.get("message") or "").strip()
        if not commit_hash or not message:
            continue
        normalized.append(
            {
                "hash": commit_hash,
                "date": str(item.get("date") or item.get("timestamp") or "").strip() or _now_iso(),
                "message": message,
                "source": str(item.get("source") or "").strip(),
                "workflow_run_id": str(item.get("workflow_run_id") or "").strip(),
                "workflow_run_attempt": str(item.get("workflow_run_attempt") or "").strip(),
            }
        )
    return normalized


def _commit_map_for_bug_ids(
    bug_ids: Iterable[str],
    commits: Iterable[Dict[str, str]],
) -> tuple[Dict[str, Dict[str, str]], List[str]]:
    wanted = {bug_id.upper() for bug_id in bug_ids if bug_id}
    matched: Dict[str, Dict[str, str]] = {}
    unmatched: set[str] = set()
    for commit in commits:
        message = commit.get("message", "")
        for raw_bug_id in BUG_ID_PATTERN.findall(message):
            bug_id = raw_bug_id.upper()
            if bug_id in wanted:
                matched.setdefault(bug_id, commit)
            else:
                unmatched.add(bug_id)
    return matched, sorted(unmatched)


def _git_commits_for_bug_ids(
    bug_ids: Iterable[str],
    supplied_commits: Optional[List[Dict[str, str]]] = None,
    limit: int = 400,
) -> tuple[Dict[str, Dict[str, str]], Optional[str], List[str]]:
    wanted = {bug_id.upper() for bug_id in bug_ids if bug_id}
    if not wanted:
        return {}, None, []
    if supplied_commits:
        commits, unmatched = _commit_map_for_bug_ids(wanted, supplied_commits)
        return commits, None, unmatched

    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(BASE_DIR),
                "log",
                f"-n{limit}",
                "--all",
                "--date=iso-strict",
                "--pretty=format:%H%x1f%cI%x1f%s",
            ],
            check=True,
            text=True,
            capture_output=True,
            timeout=8,
        )
    except Exception as exc:
        return {}, f"git commit 확인 실패: {exc}", []

    local_commits: List[Dict[str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) != 3:
            continue
        commit_hash, commit_date, message = parts
        local_commits.append({"hash": commit_hash, "date": commit_date, "message": message, "source": "server_git_log"})
    commits, unmatched = _commit_map_for_bug_ids(wanted, local_commits)
    return commits, None, unmatched


def _extract_version_from_commit(message: str) -> str:
    match = re.search(r"\bv\d+\.\d+\.\d+\b", message or "", re.IGNORECASE)
    if match:
        return match.group(0)
    return os.getenv("MARKET_APP_VERSION", "").strip()


def _append_bug_history(report: Dict[str, object], action: str, detail: str, now: str) -> None:
    history = report.get("history")
    if not isinstance(history, list):
        history = []
    history.insert(
        0,
        {
            "id": str(uuid.uuid4()),
            "at": time.time(),
            "action": action,
            "detail": detail,
        },
    )
    report["history"] = history[:30]


def _git_processing_source_title(source: str) -> str:
    if source == "github_actions":
        return "GitHub Actions 자동 처리"
    if source == "server_git_log":
        return "서버 Git log 확인"
    return "수동 Git 반영 확인"


def _auto_resolution_report(report: Dict[str, object], commit: Dict[str, str], bug_id: str) -> str:
    title = str(report.get("title") or "").strip() or str(report.get("content") or "내용 없음").strip()
    content = str(report.get("content") or "내용 없음").strip()
    feature = str(report.get("relatedFeature") or report.get("screen") or "관련 기능").strip()
    test_result = str(report.get("testResult") or "").strip() or "테스트 결과 확인 필요"
    fix_reason = str(report.get("fixReason") or "").strip() or "원인 확인 필요"
    commit_message = commit.get("message", "")
    source_title = _git_processing_source_title(commit.get("source", ""))
    return (
        "🟢 조치 완료\n\n"
        f"{bug_id} — {title}\n\n"
        "발생 문제\n"
        f"{content}\n\n"
        "발생 원인\n"
        f"{fix_reason}\n\n"
        "조치 내용\n"
        f"Git commit 메시지 기반 자동 연결: {commit_message}\n\n"
        "수정 영역\n"
        f"{feature}\n\n"
        "테스트 결과\n"
        f"{test_result}\n\n"
        "수정 commit\n"
        f"{commit.get('hash', '')[:12]}\n\n"
        "처리 방식\n"
        f"{source_title}\n\n"
        "상태\n"
        "🟢 조치 완료"
    )


def _apply_git_commit_links(
    reports: List[Dict[str, object]],
    supplied_commits: Optional[List[Dict[str, str]]] = None,
) -> tuple[List[Dict[str, object]], int, Optional[str], List[str]]:
    bug_ids = [_bug_report_display_id(report) for report in reports]
    commits, error, unmatched_ids = _git_commits_for_bug_ids(bug_ids, supplied_commits=supplied_commits)
    if error:
        return reports, 0, error, unmatched_ids

    changed = 0
    now = _now_iso()
    for report in reports:
        bug_id = _bug_report_display_id(report)
        commit = commits.get(bug_id)
        if not commit:
            continue
        if str(report.get("gitCommitHash") or "") == commit["hash"]:
            continue

        source = commit.get("source", "server_git_log")
        report["bugID"] = bug_id
        report["gitCommitHash"] = commit["hash"]
        report["gitCommitMessage"] = commit["message"]
        report["gitCommitDate"] = commit["date"]
        report["gitSyncedAt"] = now
        report["gitAutoProcessedAt"] = now
        report["gitAutoProcessingStatus"] = "completed"
        report["gitAutoProcessingSource"] = source
        report["gitAutoProcessingRunID"] = commit.get("workflow_run_id", "")
        report["gitAutoProcessingRunAttempt"] = commit.get("workflow_run_attempt", "")
        report["latestStateChangedAt"] = now
        report["updatedAt"] = time.time()
        report["fixVersion"] = str(report.get("fixVersion") or _extract_version_from_commit(commit["message"]) or "v1.0.22")
        report["status"] = "actionDone"
        report["completedAtText"] = commit["date"][:16].replace("T", " ")
        if not str(report.get("resolutionReport") or "").strip():
            report["resolutionReport"] = _auto_resolution_report(report, commit, bug_id)
        source_title = _git_processing_source_title(source)
        _append_bug_history(report, "Git commit 자동 연결", f"{source_title} · {commit['hash'][:12]} · {commit['message']}", now)
        changed += 1

    if changed:
        reports = sorted(reports, key=_bug_report_sort_value, reverse=True)
    return reports, changed, None, unmatched_ids


def _paper_device_id(request: Request) -> str:
    raw = str(request.headers.get("X-Paper-Device-ID") or request.query_params.get("device_id") or "").strip()
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isalnum() or ch in {"-", "_"})[:80]


def _file_mtime_iso(path: Path) -> str:
    if not path.exists():
        return ""
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")


def _csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except Exception:
        return 0


def _result_path() -> Path:
    if RESULT_FILE.exists() and _csv_row_count(RESULT_FILE) >= MIN_UPLOAD_ROWS:
        return RESULT_FILE
    if IOS_RESULT_FILE.exists() and _csv_row_count(IOS_RESULT_FILE) >= MIN_UPLOAD_ROWS:
        return IOS_RESULT_FILE
    if RESULT_FILE.exists():
        return RESULT_FILE
    return IOS_RESULT_FILE


def _public_row(row: Dict[str, str]) -> Dict[str, str]:
    blocked_prefixes = ("telegram", "token", "chat_id", "api_key", "secret", "password")
    return {
        key: value
        for key, value in row.items()
        if key and not any(key.lower().startswith(prefix) for prefix in blocked_prefixes)
    }


def _safe_query(value: Optional[str], *, max_length: int = 80) -> Optional[str]:
    if value is None:
        return None
    try:
        return validate_search_text(value, max_length=max_length)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _safe_market(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = _safe_query(value, max_length=20)
    allowed = {"", "국장", "미장", "캐나다", "한국", "미국", "전체", "KOREA", "US", "CANADA", "CA", "TSX", "TSXV"}
    if cleaned not in allowed:
        raise HTTPException(status_code=400, detail="허용되지 않는 시장 필터입니다.")
    return cleaned


async def _read_json_payload(request: Request, *, max_bytes: int = MAX_JSON_BYTES) -> Dict[str, object]:
    raw = await request.body()
    if len(raw) > max_bytes:
        raise HTTPException(status_code=413, detail="JSON payload too large")
    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="invalid JSON payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    return payload


def _read_rows() -> List[Dict[str, str]]:
    global _cache_rows, _cache_loaded_at, _cache_file_mtime, _cache_file_path

    path = _result_path()
    if not path.exists():
        return []

    now = time.time()
    file_mtime = path.stat().st_mtime
    file_path = str(path)
    if (
        _cache_rows
        and now - _cache_loaded_at < CACHE_TTL_SECONDS
        and file_mtime == _cache_file_mtime
        and file_path == _cache_file_path
    ):
        return _cache_rows

    rows: List[Dict[str, str]] = []
    for row in _iter_public_rows(path):
        rows.append(row)
        if len(rows) >= RESULTS_CACHE_MAX_ROWS:
            break
    _cache_rows = rows
    _cache_loaded_at = now
    _cache_file_mtime = file_mtime
    _cache_file_path = file_path
    return _cache_rows


def _filter_result_rows_streaming(
    market: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 800,
) -> List[Dict[str, str]]:
    return _filter_rows(_iter_public_rows(), market=market, q=q, limit=limit)


def _parse_csv_bytes(payload: bytes) -> List[Dict[str, str]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"CSV decode failed: {exc}") from exc

    reader = csv.DictReader(text.splitlines())
    rows = [_public_row(row) for row in reader]
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no rows")
    if len(rows) < MIN_UPLOAD_ROWS:
        raise HTTPException(status_code=400, detail=f"CSV row count too low: {len(rows)}")
    ok_rows = sum(1 for row in rows if row.get("status", "ok") == "ok")
    if ok_rows < MIN_UPLOAD_OK_ROWS:
        raise HTTPException(status_code=400, detail=f"CSV ok row count too low: {ok_rows}")
    ca_rows = canada_count(rows)
    if ca_rows < MIN_CANADA_ROWS_FOR_APP_SYNC:
        raise HTTPException(
            status_code=400,
            detail=f"CSV Canada row count too low: {ca_rows}, need at least {MIN_CANADA_ROWS_FOR_APP_SYNC}",
        )
    return rows


def _normalize_uploaded_rows(rows: List[Dict[str, str]]) -> List[Dict[str, str]]:
    normalized: List[Dict[str, str]] = []
    for row in rows:
        item = dict(row)
        if is_canada_row(item):
            item["market"] = CANADA_MARKET_LABEL
        normalized.append(item)
    return normalized


def _prepare_upload_rows(payload: bytes) -> tuple[bytes, List[Dict[str, str]], Dict[str, int]]:
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"CSV decode failed: {exc}") from exc
    rows = [_public_row(row) for row in csv.DictReader(text.splitlines())]
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no rows")

    existing_rows = list(_iter_public_rows(_result_path()))
    rows = _normalize_uploaded_rows(rows)
    if existing_rows:
        ok, reason = validate_no_stock_loss(rows, existing_rows, "api results upload")
        if not ok:
            raise HTTPException(status_code=400, detail=reason)
        print(f"[API] {reason}", flush=True)
    if canada_count(rows) < MIN_CANADA_ROWS_FOR_APP_SYNC and canada_count(existing_rows) >= MIN_CANADA_ROWS_FOR_APP_SYNC:
        before = canada_count(rows)
        rows = _normalize_uploaded_rows(merge_existing_canada_rows(rows, existing_rows))
        print(
            f"[API] Canada guard restored previous Canada rows upload_canada={before} restored_canada={canada_count(rows)}",
            flush=True,
        )
    serialized = serialize_csv_rows(rows)
    validated_rows = _parse_csv_bytes(serialized)
    return serialized, validated_rows, market_counts(validated_rows)


def _replace_result_file(payload: bytes, rows: List[Dict[str, str]]) -> None:
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(RESULT_FILE.parent), prefix=".results-", suffix=".csv") as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(RESULT_FILE)

    if IOS_RESULT_FILE.parent.exists():
        IOS_RESULT_FILE.write_bytes(payload)

    _invalidate_results_cache()
    gc.collect()


def _read_scanner_status() -> Dict[str, object]:
    if not SCANNER_STATUS_FILE.exists():
        path = _result_path()
        if path.exists():
            file_updated_at = _file_mtime_iso(path)
            return {
                "running": False,
                "state": "ready",
                "message": "데이터 준비됨 · 상태 파일은 아직 없음",
                "file_updated_at": file_updated_at,
                "mode": "file",
            }
        return {"running": False, "state": "idle", "message": "스캐너 대기 · 결과 파일 없음"}
    try:
        status = json.loads(SCANNER_STATUS_FILE.read_text(encoding="utf-8"))
        if status.get("running"):
            started_at = float(status.get("started_at") or time.time())
            elapsed = max(0.0, time.time() - started_at)
            scanner_thread_active = _scanner_running
            snapshot = _current_result_snapshot()
            if not scanner_thread_active:
                recovered = {
                    **status,
                    "running": False,
                    "state": "recovered",
                    "message": "스캐너 상태 복구 · 최신 데이터 표시",
                    "progress": 100,
                    "recovered_at": _now_iso(),
                    **snapshot,
                }
                _write_scanner_status(**recovered)
                return recovered
            timeout_seconds = int(os.getenv("MARKET_SCANNER_REFRESH_TIMEOUT", "3600"))
            if elapsed > timeout_seconds + 120:
                recovered = {
                    **status,
                    "running": False,
                    "state": "timeout_recovered",
                    "message": "스캐너 시간 초과 복구 · 최신 저장 데이터 표시",
                    "progress": 100,
                    "recovered_at": _now_iso(),
                    **snapshot,
                }
                _write_scanner_status(**recovered)
                return recovered
            current_progress = int(status.get("progress") or 0)
            if status.get("state") == "queued":
                estimated_progress = min(12, max(current_progress, int(elapsed / 8)))
            elif status.get("state") == "enriching":
                estimated_progress = min(94, max(current_progress, int(82 + elapsed / 120 * 12)))
            elif status.get("state") == "finalizing":
                estimated_progress = min(99, max(current_progress, 95))
            else:
                estimated_progress = min(90, max(current_progress, int(25 + elapsed / 480 * 65)))
            status["progress"] = estimated_progress
            elapsed_minutes = max(1, int(elapsed // 60) + 1)
            if status.get("state") == "running":
                status["message"] = f"AI 분석/뉴스 수집중... {estimated_progress}% · 약 {elapsed_minutes}분째"
            elif status.get("state") == "queued":
                status["message"] = f"스캐너 실행 대기... {estimated_progress}%"
        return status
    except Exception:
        return {"running": False, "state": "unknown", "message": "상태 파일 확인 실패"}


def _write_scanner_status(**payload: object) -> None:
    status = {
        "running": bool(payload.get("running", False)),
        "state": payload.get("state", "idle"),
        "message": payload.get("message", ""),
        "updated_at": _now_iso(),
    }
    status.update(payload)
    SCANNER_STATUS_FILE.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")


def _scanner_completed_age_seconds(status: Optional[Dict[str, object]] = None) -> Optional[float]:
    status = status or _read_scanner_status()
    completed_at = status.get("completed_at") or status.get("finished_at")
    if isinstance(completed_at, (int, float)):
        return max(0.0, time.time() - float(completed_at))
    if isinstance(completed_at, str) and completed_at:
        try:
            normalized = completed_at.replace("Z", "+00:00")
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                return max(0.0, time.time() - parsed.timestamp())
            return max(0.0, time.time() - parsed.timestamp())
        except ValueError:
            pass
    if status.get("state") == "completed":
        updated_at = status.get("updated_at")
        if isinstance(updated_at, str) and updated_at:
            try:
                parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
                return max(0.0, time.time() - parsed.timestamp())
            except ValueError:
                pass
    return None


def _scanner_cooldown_payload(status: Dict[str, object]) -> Optional[Dict[str, object]]:
    age = _scanner_completed_age_seconds(status)
    if age is None or age >= SCANNER_RUN_COOLDOWN_SECONDS:
        return None
    remaining = int(SCANNER_RUN_COOLDOWN_SECONDS - age)
    minutes_ago = max(1, int(age // 60) + 1)
    remaining_minutes = max(1, int(remaining // 60) + 1)
    snapshot = _current_result_snapshot()
    status = {
        **status,
        "running": False,
        "state": "cooldown",
        "message": f"최근 {minutes_ago}분 내 스캔 완료 · 새 실행 생략 · {remaining_minutes}분 후 가능",
        "progress": 100,
        "cooldown_remaining_seconds": remaining,
        **snapshot,
    }
    return {
        "ok": True,
        "started": False,
        "running": False,
        "skipped": True,
        "reason": "cooldown",
        "message": status["message"],
        "status": status,
        "updated_at": _now_iso(),
    }


def _run_scanner_background(mode: str = "quick", job_lock: Optional[InterProcessJobLock] = None) -> None:
    global _scanner_running, _scanner_last_seen_mtime
    scan_mode = "full" if mode == "full" else "quick"
    try:
        if job_lock is None:
            job_lock = InterProcessJobLock(f"api_scanner_{scan_mode}", stale_after_seconds=HEAVY_JOB_STALE_SECONDS)
            ok, holder = job_lock.acquire()
            if not ok:
                snapshot = _current_result_snapshot()
                _write_scanner_status(
                    running=False,
                    state="already_running",
                    message=f"무거운 작업 실행중 · 새 스캔 생략: {holder.get('name', 'unknown')}",
                    progress=100,
                    mode=scan_mode,
                    lock_holder=holder,
                    **snapshot,
                )
                return
        _log_memory("scanner-start")
        _cleanup_runtime_storage()
        _clear_runtime_api_caches()
        started_at = time.time()
        current_path = _result_path()
        _scanner_last_seen_mtime = current_path.stat().st_mtime if current_path.exists() else 0.0
        _write_scanner_status(
            running=True,
            state="running",
            message=f"{'전체' if scan_mode == 'full' else '빠른'} 스캐너 실행 시작 · 캐시 초기화 완료... 8%",
            progress=8,
            started_at=started_at,
            mode=scan_mode,
        )
        if not ENABLE_FULL_SCANNER:
            _write_scanner_status(
                running=False,
                state="disabled",
                message="서버 풀스캐너 비활성 · MARKET_ENABLE_FULL_SCANNER 확인 필요",
                mode="disabled",
                progress=0,
            )
            return

        command = [sys.executable, str(REFRESH_SCRIPT)]
        if REFRESH_SCRIPT.name == "run_market_scanner_update.py":
            command.append("--force")
        scanner_env = os.environ.copy()
        scanner_env.setdefault("MARKET_SCANNER_MAX_WORKERS", SCANNER_DEFAULT_MAX_WORKERS)
        scanner_env.setdefault("MARKET_SCANNER_MAX_STOCKS", SCANNER_DEFAULT_MAX_STOCKS)
        scanner_env.setdefault("MARKET_SCANNER_ENABLE_INTRADAY_1M", SCANNER_ENABLE_INTRADAY_1M)
        scanner_env.setdefault("MARKET_SCANNER_CACHE_RETENTION_DAYS", "1")
        scanner_env.setdefault("MOBILE_INTEL_MAX_NEWS_OBSERVATIONS", "700" if os.getenv("RENDER") else "1200")
        scanner_env.setdefault("MARKET_SCANNER_CACHE_MAX_ITEMS", "128" if os.getenv("RENDER") else "512")
        scanner_env.setdefault("MARKET_DATA_CACHE_MAX_ITEMS", "128" if os.getenv("RENDER") else "512")
        scanner_env.setdefault("MARKET_SCANNER_MEMORY_PROFILE", "true")
        scanner_env["MARKET_HEAVY_JOB_LOCK_HELD_BY_PARENT"] = "1"
        scanner_env["MOBILE_SCAN_FAST_MODE"] = "false" if scan_mode == "full" else "true"
        if scan_mode == "quick":
            scanner_env["MARKET_SCANNER_ENABLE_INTRADAY_1M"] = "false"
            scanner_env["MARKET_SCANNER_NEWS_SOURCES"] = "google_news"
            scanner_env["MARKET_SCANNER_ENABLE_SECTOR_NEWS"] = "false"
            scanner_env["MARKET_SCANNER_SKIP_OPTIONAL_YAHOO"] = "true"
            scanner_env["CANADA_NEWS_COLLECT_TIMEOUT_SECONDS"] = "20"
            scanner_env["MOBILE_INTEL_INCREMENTAL"] = "true"
            scanner_env["MOBILE_INTEL_MAX_NEWS_OBSERVATIONS"] = "300" if os.getenv("RENDER") else "500"
        else:
            scanner_env["MARKET_SCANNER_NEWS_SOURCES"] = "company_risk_news,google_news,naver_news"
            scanner_env["MARKET_SCANNER_ENABLE_SECTOR_NEWS"] = "true"
            scanner_env["MOBILE_INTEL_INCREMENTAL"] = "false"

        _write_scanner_status(
            running=True,
            state="running",
            message=f"{'전체' if scan_mode == 'full' else '빠른'} 스캔 · AI 분석/뉴스 수집 실행중... 25%",
            progress=25,
            started_at=started_at,
            mode=scan_mode,
        )
        stdout = ""
        stderr = ""
        stdout_log = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False, dir=BASE_DIR, prefix=".scanner-stdout-", suffix=".log")
        stderr_log = tempfile.NamedTemporaryFile("w+", encoding="utf-8", delete=False, dir=BASE_DIR, prefix=".scanner-stderr-", suffix=".log")
        stdout_path = Path(stdout_log.name)
        stderr_path = Path(stderr_log.name)
        try:
            update = subprocess.Popen(
                command,
                cwd=BASE_DIR,
                env=scanner_env,
                stdout=stdout_log,
                stderr=stderr_log,
                text=True,
            )
            timeout_seconds = int(os.getenv("MARKET_SCANNER_REFRESH_TIMEOUT", "3600"))
            timeout_at = time.time() + timeout_seconds
            last_heartbeat = 0.0
            while update.poll() is None:
                now = time.time()
                if now > timeout_at:
                    update.kill()
                    update.wait(timeout=10)
                    raise subprocess.TimeoutExpired(command, timeout_seconds)
                path = _result_path()
                current_status = _read_scanner_status()
                if path.exists():
                    mtime = path.stat().st_mtime
                    if mtime > _scanner_last_seen_mtime:
                        _scanner_last_seen_mtime = mtime
                        _invalidate_results_cache()
                        snapshot = _current_result_snapshot()
                        _log_memory(
                            "scanner-partial-data",
                            rows=snapshot.get("rows"),
                            ok_rows=snapshot.get("ok_rows"),
                            canada_rows=snapshot.get("canada_rows"),
                        )
                        _write_scanner_status(
                            running=True,
                            state="partial_data",
                            message=(
                                f"부분 데이터 반영됨 · {snapshot['ok_rows']}/{snapshot['rows']} 정상 · "
                                f"캐나다 {snapshot.get('canada_rows', 0)}개 · 모바일 재조회 가능"
                            ),
                            progress=max(35, int(current_status.get("progress") or 35)),
                            started_at=started_at,
                            mode=scan_mode,
                            **snapshot,
                        )
                        last_heartbeat = now
                if now - last_heartbeat >= 15:
                    snapshot = _current_result_snapshot()
                    child_rss = _child_rss_mb(update.pid)
                    stdout_log.flush()
                    stderr_log.flush()
                    live_output = (_read_text_tail(stdout_path, max_chars=1800) + "\n" + _read_text_tail(stderr_path, max_chars=800))[-2200:]
                    progress = min(80, max(25, int(current_status.get("progress") or 25) + 1))
                    _record_memory_event("scanner-child-running", mode=scan_mode, child_pid=update.pid, child_rss_mb=child_rss)
                    _write_scanner_status(
                        running=True,
                        state="running",
                        message=f"{'전체' if scan_mode == 'full' else '빠른'} 스캔 실행중... {progress}% · child {child_rss}MB",
                        progress=progress,
                        started_at=started_at,
                        mode=scan_mode,
                        server_rss_mb=_memory_rss_mb(),
                        child_rss_mb=child_rss,
                        live_output=live_output,
                        **snapshot,
                    )
                    last_heartbeat = now
                time.sleep(5)

            stdout_log.flush()
            stderr_log.flush()
            stdout = _read_text_tail(stdout_path)
            stderr = _read_text_tail(stderr_path)
        finally:
            stdout_log.close()
            stderr_log.close()
            for log_path in (stdout_path, stderr_path):
                try:
                    log_path.unlink(missing_ok=True)
                except OSError:
                    pass
        if update.returncode != 0:
            _write_scanner_status(
                running=False,
                state="failed",
                message="스캐너 실패",
                return_code=update.returncode,
                output=(stdout + "\n" + stderr)[-4000:],
                progress=0,
            )
            return

        if REFRESH_SCRIPT.name != "render_mobile_refresh.py" and MOBILE_INTEL_SCRIPT.exists():
            _write_scanner_status(
                running=True,
                state="enriching",
                message="모바일 데이터 보강중... 82%",
                progress=82,
                started_at=started_at,
                mode=scan_mode,
            )
            enrich = subprocess.run(
                [sys.executable, str(MOBILE_INTEL_SCRIPT)],
                cwd=BASE_DIR,
                env=scanner_env,
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            if enrich.returncode != 0:
                _write_scanner_status(
                    running=False,
                    state="partial",
                    message="스캐너 완료 · 모바일 보강 실패",
                    return_code=enrich.returncode,
                    output=(stdout + "\n" + stderr + "\n" + enrich.stdout + "\n" + enrich.stderr)[-4000:],
                    progress=90,
                )
                return

        _write_scanner_status(
            running=True,
            state="finalizing",
            message="최신 CSV 반영중... 95%",
            progress=95,
            started_at=started_at,
            mode=scan_mode,
        )
        _invalidate_results_cache()
        snapshot = _current_result_snapshot()
        row_count = int(snapshot.get("rows", 0) or 0)
        ok_rows = int(snapshot.get("ok_rows", 0) or 0)
        duration_seconds = round(time.time() - started_at, 2)
        canada_rows = int(snapshot.get("canada_rows", 0) or 0)
        _log_memory("scanner-completed", rows=row_count, ok_rows=ok_rows, canada_rows=canada_rows)
        _write_scanner_status(
            running=False,
            state="completed",
            message=f"스캐너 완료 · {ok_rows}/{row_count} 정상 · 캐나다 {canada_rows}개 · {duration_seconds}s",
            rows=row_count,
            ok_rows=ok_rows,
            canada_rows=canada_rows,
            market_counts=snapshot.get("market_counts", {}),
            mode=scan_mode,
            duration_seconds=duration_seconds,
            performance_report="mobile_scan_performance_report.json",
            output=(stdout + "\n" + stderr)[-4000:],
            progress=100,
            completed_at=time.time(),
            completed_at_iso=_now_iso(),
        )
        _cleanup_runtime_storage()
        _log_memory("scanner-cleanup")
    except subprocess.TimeoutExpired:
        _write_scanner_status(running=False, state="timeout", message="스캐너 시간 초과", progress=0)
    except Exception as exc:
        _write_scanner_status(running=False, state="failed", message=f"스캐너 오류: {exc}", progress=0)
    finally:
        if job_lock is not None:
            job_lock.release()
        with _scanner_lock:
            _scanner_running = False


def _float_value(row: Dict[str, str], *keys: str) -> float:
    for key in keys:
        raw = row.get(key, "")
        try:
            return float(str(raw).replace(",", "").strip())
        except (TypeError, ValueError):
            continue
    return 0.0


def _filter_rows(
    rows: Iterable[Dict[str, str]],
    market: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 800,
) -> List[Dict[str, str]]:
    query = (q or "").strip().lower()
    market_filter = (market or "").strip()
    if market_filter in {"한국", "KOREA"}:
        market_filter = "국장"
    elif market_filter in {"미국", "US"}:
        market_filter = "미장"
    elif market_filter in {"CANADA", "CA", "TSX", "TSXV"}:
        market_filter = CANADA_MARKET_LABEL
    elif market_filter in {"전체"}:
        market_filter = ""
    filtered = []
    for row in rows:
        if market_filter and normalized_market(row) != market_filter:
            continue
        if query:
            haystack = " ".join(
                [
                    row.get("name", ""),
                    row.get("ticker", ""),
                    row.get("sector", ""),
                    row.get("label", ""),
                    row.get("news", ""),
                    row.get("headlines", ""),
                ]
            ).lower()
            if query not in haystack:
                continue
        filtered.append(row)
        if len(filtered) >= limit:
            break
    if query:
        def rank(row: Dict[str, str]) -> tuple[int, str]:
            name = row.get("name", "").strip().lower()
            ticker = row.get("ticker", "").strip().lower()
            sector = row.get("sector", "").strip().lower()
            if name == query or ticker == query:
                return (0, name)
            if name.startswith(query) or ticker.startswith(query):
                return (1, name)
            if query in name:
                return (2, name)
            if query in ticker:
                return (3, name)
            if query in sector:
                return (4, name)
            return (5, name)

        filtered.sort(key=rank)
    return filtered


def _check_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    now = time.time()
    bucket = _request_log[client]
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_PER_MINUTE:
        raise HTTPException(status_code=429, detail="rate limit exceeded")
    bucket.append(now)


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return ""
    return token.strip()


def _require_token(
    x_market_token: Optional[str],
    x_api_token: Optional[str],
    authorization: Optional[str],
) -> None:
    if not API_TOKEN:
        raise HTTPException(status_code=503, detail="MARKET_API_TOKEN is not configured")
    candidates = [
        x_market_token or "",
        x_api_token or "",
        _extract_bearer_token(authorization),
    ]
    if not any(secrets.compare_digest(token, API_TOKEN) for token in candidates):
        raise HTTPException(status_code=401, detail="unauthorized")


async def guarded(
    request: Request,
) -> None:
    _check_rate_limit(request)
    x_market_token = request.headers.get("X-Market-Token")
    x_api_token = request.headers.get("X-API-Token")
    authorization = request.headers.get("Authorization")
    _require_token(x_market_token, x_api_token, authorization)


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    detail = sanitize_secret(exc.detail, API_TOKEN)
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": detail, "updated_at": _now_iso()},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    print(
        f"[ERROR] {request.method} {request.url.path}: {sanitize_secret(exc, API_TOKEN)}",
        flush=True,
    )
    return JSONResponse(
        status_code=500,
        content={"ok": False, "error": "일시적인 오류가 발생했습니다.", "updated_at": _now_iso()},
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@app.get("/api/health")
def health() -> Dict[str, object]:
    path = _result_path()
    if not ALLOW_UNAUTH_HEALTH and API_TOKEN:
        return {"ok": True, "protected": True}
    return {
        "ok": True,
        "protected": bool(API_TOKEN),
        "result_file_exists": path.exists(),
        "result_file": path.name,
        "updated_at": _now_iso(),
    }


@app.get("/api/status")
async def status(request: Request) -> Dict[str, object]:
    await guarded(request)
    path = _result_path()
    snapshot = _current_result_snapshot()
    markets = sorted({normalized_market(row) for row in _iter_public_rows(path) if normalized_market(row)})
    scanner_status = _read_scanner_status()
    return {
        "ok": True,
        "rows": snapshot["rows"],
        "ok_rows": snapshot["ok_rows"],
        "canada_rows": snapshot.get("canada_rows", 0),
        "market_counts": snapshot.get("market_counts", {}),
        "markets": markets,
        "result_file": path.name,
        "file_updated_at": snapshot["file_updated_at"],
        "data_generated_at": snapshot["data_generated_at"],
        "server_updated_at": _now_iso(),
        "scanner": scanner_status,
    }


@app.get("/api/bug-reports")
async def bug_reports(request: Request) -> Dict[str, object]:
    await guarded(request)
    with _bug_reports_lock:
        store = _read_bug_reports_store()
        reports, git_changed, git_error, unmatched_ids = _apply_git_commit_links(store["reports"])
        if git_changed:
            store = _write_bug_reports_store(reports)
        else:
            store["reports"] = reports
    reports = store["reports"]
    return {
        "ok": True,
        "reports": reports,
        "count": len(reports),
        "git_changed": git_changed,
        "git_sync_error": git_error,
        "git_unmatched_ids": unmatched_ids,
        "updated_at": store.get("updated_at"),
        "server_updated_at": _now_iso(),
    }


@app.post("/api/bug-reports/sync")
async def sync_bug_reports(request: Request) -> Dict[str, object]:
    await guarded(request)
    payload = await _read_json_payload(request)
    incoming = payload.get("reports")
    if not isinstance(incoming, list):
        raise HTTPException(status_code=400, detail="reports must be a list")
    incoming_reports = [report for report in incoming if isinstance(report, dict)]
    with _bug_reports_lock:
        store = _read_bug_reports_store()
        merged, changed = _merge_bug_reports(store["reports"], incoming_reports)
        merged, git_changed, git_error, unmatched_ids = _apply_git_commit_links(merged)
        saved = _write_bug_reports_store(merged)
    return {
        "ok": True,
        "reports": saved["reports"],
        "count": saved["count"],
        "changed": changed + git_changed,
        "git_changed": git_changed,
        "git_sync_error": git_error,
        "git_unmatched_ids": unmatched_ids,
        "updated_at": saved["updated_at"],
    }


@app.post("/api/bug-reports/git-sync")
async def sync_bug_reports_from_git(request: Request) -> Dict[str, object]:
    await guarded(request)
    payload = await _read_json_payload(request)
    supplied_commits = _normalize_supplied_git_commits(payload.get("commits"))
    with _bug_reports_lock:
        store = _read_bug_reports_store()
        reports, changed, git_error, unmatched_ids = _apply_git_commit_links(
            store["reports"],
            supplied_commits=supplied_commits,
        )
        if git_error:
            return {
                "ok": False,
                "reports": store["reports"],
                "count": len(store["reports"]),
                "changed": 0,
                "git_changed": 0,
                "git_sync_error": git_error,
                "git_unmatched_ids": unmatched_ids,
                "received_commits": len(supplied_commits),
                "updated_at": store.get("updated_at"),
                "server_updated_at": _now_iso(),
            }
        saved = _write_bug_reports_store(reports) if changed else {
            "reports": reports,
            "count": len(reports),
            "updated_at": store.get("updated_at"),
        }
    return {
        "ok": True,
        "reports": saved["reports"],
        "count": saved["count"],
        "changed": changed,
        "git_changed": changed,
        "git_sync_error": None,
        "git_unmatched_ids": unmatched_ids,
        "received_commits": len(supplied_commits),
        "updated_at": saved["updated_at"],
        "server_updated_at": _now_iso(),
    }


@app.post("/api/admin/verify")
async def verify_admin_device(request: Request) -> Dict[str, object]:
    await guarded(request)
    payload = await _read_json_payload(request)
    provided = str(payload.get("admin_token") or "").strip()
    expected = (ADMIN_TOKEN or API_TOKEN).strip()
    if not expected:
        raise HTTPException(status_code=503, detail="admin token is not configured")
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="admin unauthorized")
    return {
        "ok": True,
        "admin": True,
        "mode": "temporary_device",
        "updated_at": _now_iso(),
    }


@app.post("/api/refresh/quick")
async def quick_refresh(request: Request) -> Dict[str, object]:
    await guarded(request)
    started = time.time()
    _invalidate_results_cache()
    snapshot = _current_result_snapshot()
    _write_scanner_status(
        running=False,
        state="quick_refreshed",
        message=f"빠른 갱신 완료 · 기존 최신 데이터 즉시 반영 · {snapshot.get('ok_rows', 0)}/{snapshot.get('rows', 0)} 정상",
        progress=100,
        mode="quick",
        **snapshot,
    )
    _log_memory("quick-refresh", rows=snapshot.get("rows"), duration_ms=int((time.time() - started) * 1000))
    return {
        "ok": True,
        "message": "quick refresh completed",
        "count": snapshot.get("rows", 0),
        "status": _read_scanner_status(),
        **snapshot,
        "updated_at": _now_iso(),
    }


@app.post("/api/scanner/run")
async def scanner_run(
    request: Request,
    mode: str = Query(default="quick"),
    force: bool = Query(default=False),
) -> Dict[str, object]:
    global _scanner_running
    await guarded(request)
    if not SAFE_MODE_PATTERN.match(mode.strip()):
        raise HTTPException(status_code=400, detail="invalid scanner mode")
    scan_mode = "full" if mode.lower().strip() == "full" else "quick"
    memory_block = _scanner_memory_block_payload(scan_mode)
    if memory_block:
        return memory_block
    with _scanner_lock:
        if _scanner_running:
            return {
                "ok": True,
                "started": False,
                "running": True,
                "message": "이미 스캐너 실행중",
                "status": _read_scanner_status(),
                "updated_at": _now_iso(),
            }
        job_lock = InterProcessJobLock(f"api_scanner_{scan_mode}", stale_after_seconds=HEAVY_JOB_STALE_SECONDS)
        lock_ok, holder = job_lock.acquire()
        if not lock_ok:
            snapshot = _current_result_snapshot()
            status = {
                "running": True,
                "state": "already_running",
                "message": f"무거운 작업 실행중 · 새 스캔 생략: {holder.get('name', 'unknown')}",
                "progress": 100,
                "mode": scan_mode,
                "lock_holder": holder,
                **snapshot,
            }
            _write_scanner_status(**status)
            return {
                "ok": True,
                "started": False,
                "running": True,
                "skipped": True,
                "reason": "heavy_job_already_running",
                "message": status["message"],
                "status": status,
                "updated_at": _now_iso(),
            }
        current_status = _read_scanner_status()
        cooldown_payload = None if scan_mode == "full" or force else _scanner_cooldown_payload(current_status)
        if cooldown_payload:
            job_lock.release()
            _invalidate_results_cache()
            return cooldown_payload
        _scanner_running = True
        _clear_runtime_api_caches()
        quick_snapshot = _current_result_snapshot()
        _write_scanner_status(
            running=True,
            state="queued",
            message=f"{'전체' if scan_mode == 'full' else '빠른'} 스캔 대기... 5%",
            progress=5,
            started_at=time.time(),
            mode=scan_mode,
            **quick_snapshot,
        )
        thread = threading.Thread(target=_run_scanner_background, args=(scan_mode, job_lock), daemon=True)
        thread.start()
    return {
        "ok": True,
        "started": True,
        "running": True,
        "message": f"{'전체' if scan_mode == 'full' else '빠른'} 스캐너 백그라운드 실행 시작",
        "mode": scan_mode,
        "status": _read_scanner_status(),
        "updated_at": _now_iso(),
    }


@app.post("/run-scanner")
async def scanner_run_alias(request: Request) -> Dict[str, object]:
    return await scanner_run(request)


@app.post("/api/run-scanner")
async def scanner_run_api_alias(request: Request) -> Dict[str, object]:
    return await scanner_run(request)


@app.get("/api/scanner/status")
async def scanner_status(request: Request) -> Dict[str, object]:
    await guarded(request)
    status = _read_scanner_status()
    return {
        "ok": True,
        "status": status,
        "memory": {
            "rss_mb": _memory_rss_mb(),
            "scanner_start_max_rss_mb": SCANNER_START_MAX_RSS_MB,
            "heavy_job_lock": read_lock_payload(),
            "recent_events": list(_memory_events)[-20:],
        },
        "updated_at": _now_iso(),
    }


@app.get("/api/system/memory")
async def system_memory(request: Request) -> Dict[str, object]:
    await guarded(request)
    return {
        "ok": True,
        "rss_mb": _memory_rss_mb(),
        "scanner_running": _scanner_running,
        "scanner_start_max_rss_mb": SCANNER_START_MAX_RSS_MB,
        "heavy_job_lock": read_lock_payload(),
        "recent_events": list(_memory_events),
        "status": _read_scanner_status(),
        "updated_at": _now_iso(),
    }


@app.post("/api/cache/invalidate")
async def invalidate_cache(request: Request) -> Dict[str, object]:
    await guarded(request)
    _clear_runtime_api_caches()
    snapshot = _current_result_snapshot()
    with _scanner_lock:
        scanner_running = _scanner_running
    if not scanner_running:
        _write_scanner_status(
            running=False,
            state="cache_invalidated",
            message="모바일 API 캐시 강제 초기화 완료",
            progress=100,
            **snapshot,
        )
    return {
        "ok": True,
        "message": "cache invalidated",
        "scanner_running": scanner_running,
        "snapshot": snapshot,
        "updated_at": _now_iso(),
    }


@app.post("/api/results/force-refresh")
async def force_refresh_results(request: Request) -> Dict[str, object]:
    await guarded(request)
    _invalidate_results_cache()
    snapshot = _current_result_snapshot()
    return {"ok": True, "message": "results cache refreshed", **snapshot, "updated_at": _now_iso()}


@app.get("/api/results")
async def results(
    request: Request,
    market: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=800, ge=1, le=1200),
) -> Dict[str, object]:
    await guarded(request)
    market = _safe_market(market)
    q = _safe_query(q)
    path = _result_path()
    file_updated_at = _file_mtime_iso(path)
    rows = _filter_result_rows_streaming(market=market, q=q, limit=limit)
    generated_at = max((row.get("mobile_intel_generated_at", "") for row in rows), default="")
    counts = market_counts(rows)
    return {
        "ok": True,
        "count": len(rows),
        "rows": rows,
        "canada_rows": counts.get(CANADA_MARKET_LABEL, 0),
        "market_counts": counts,
        "result_file": path.name,
        "file_updated_at": file_updated_at,
        "data_generated_at": generated_at,
        "updated_at": _now_iso(),
    }


@app.post("/api/results/upload")
async def upload_results(request: Request) -> Dict[str, object]:
    await guarded(request)
    content_type = request.headers.get("Content-Type", "")
    if "text/csv" not in content_type and "application/octet-stream" not in content_type:
        raise HTTPException(status_code=415, detail="upload requires text/csv or application/octet-stream")

    payload = await request.body()
    if not payload:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"upload too large: {len(payload)} bytes")

    payload, rows, counts = _prepare_upload_rows(payload)
    _replace_result_file(payload, rows)
    ok_rows = sum(1 for row in rows if row.get("status", "ok") == "ok")
    _write_scanner_status(
        running=False,
        state="uploaded",
        message=f"CSV 즉시 업로드 완료 · {ok_rows}/{len(rows)} 정상 · 캐나다 {counts.get(CANADA_MARKET_LABEL, 0)}개",
        rows=len(rows),
        ok_rows=ok_rows,
        canada_rows=counts.get(CANADA_MARKET_LABEL, 0),
        market_counts=counts,
        mode="upload",
        progress=100,
    )
    return {
        "ok": True,
        "rows": len(rows),
        "ok_rows": ok_rows,
        "canada_rows": counts.get(CANADA_MARKET_LABEL, 0),
        "market_counts": counts,
        "file_updated_at": _file_mtime_iso(RESULT_FILE),
        "updated_at": _now_iso(),
    }


@app.get("/api/top-movers")
async def top_movers(
    request: Request,
    market: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, object]:
    await guarded(request)
    market = _safe_market(market)
    rows = _filter_result_rows_streaming(market=market, limit=2000)
    change_keys = ("change_pct", "change_percent", "change")
    gainers = sorted(rows, key=lambda row: _float_value(row, *change_keys), reverse=True)[:limit]
    losers = sorted(rows, key=lambda row: _float_value(row, *change_keys))[:limit]
    losers = [row for row in losers if _float_value(row, *change_keys) < 0]
    gainers = [row for row in gainers if _float_value(row, *change_keys) > 0]
    return {
        "ok": True,
        "gainers": gainers,
        "losers": losers,
        "updated_at": _now_iso(),
    }


@app.get("/api/ai-screening/profile")
async def ai_screening_profile(request: Request) -> Dict[str, object]:
    await guarded(request)
    from korean_ai_screening_simulator import SAFETY_NOTICE, load_profile

    return {
        "ok": True,
        "profile": load_profile(),
        "safety_notice": SAFETY_NOTICE,
        "updated_at": _now_iso(),
    }


@app.post("/api/ai-screening/profile")
async def save_ai_screening_profile(request: Request) -> Dict[str, object]:
    await guarded(request)
    from korean_ai_screening_simulator import SAFETY_NOTICE, save_profile

    payload = await _read_json_payload(request)
    profile = save_profile(payload)
    return {
        "ok": True,
        "profile": profile,
        "safety_notice": SAFETY_NOTICE,
        "updated_at": _now_iso(),
    }


@app.post("/api/ai-screening/run")
async def run_ai_screening(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> Dict[str, object]:
    await guarded(request)
    if _memory_rss_mb() >= SCANNER_START_MAX_RSS_MB:
        raise HTTPException(status_code=503, detail="server memory guard active; retry later")
    job_lock = InterProcessJobLock("api_ai_screening", stale_after_seconds=HEAVY_JOB_STALE_SECONDS)
    lock_ok, holder = job_lock.acquire()
    if not lock_ok:
        raise HTTPException(status_code=409, detail=f"heavy job already running: {holder.get('name', 'unknown')}")
    from korean_ai_screening_simulator import run_screening

    try:
        _log_memory("ai-screening-start", limit=limit)
        try:
            payload = await _read_json_payload(request)
        except HTTPException:
            raise
        except Exception:
            payload = {}
        profile = payload if isinstance(payload, dict) and payload else None
        result = run_screening(profile=profile, limit=limit)
        result["updated_at"] = _now_iso()
        _log_memory("ai-screening-finished", limit=limit)
        return result
    finally:
        job_lock.release()
        gc.collect()


@app.post("/api/ai-screening/backtest")
async def run_ai_screening_backtest(
    request: Request,
    period: str = Query(default="6mo"),
    max_symbols: int = Query(default=30, ge=1, le=80),
) -> Dict[str, object]:
    await guarded(request)
    if not SAFE_PERIOD_PATTERN.match(period.strip()):
        raise HTTPException(status_code=400, detail="invalid backtest period")
    if _memory_rss_mb() >= SCANNER_START_MAX_RSS_MB:
        raise HTTPException(status_code=503, detail="server memory guard active; retry later")
    job_lock = InterProcessJobLock("api_ai_backtest", stale_after_seconds=HEAVY_JOB_STALE_SECONDS)
    lock_ok, holder = job_lock.acquire()
    if not lock_ok:
        raise HTTPException(status_code=409, detail=f"heavy job already running: {holder.get('name', 'unknown')}")
    from korean_ai_screening_simulator import backtest_screening

    try:
        _log_memory("ai-backtest-start", period=period, max_symbols=max_symbols)
        try:
            payload = await _read_json_payload(request)
        except HTTPException:
            raise
        except Exception:
            payload = {}
        profile = payload if isinstance(payload, dict) and payload else None
        result = backtest_screening(profile=profile, period=period, max_symbols=max_symbols)
        result["updated_at"] = _now_iso()
        _log_memory("ai-backtest-finished", period=period, max_symbols=max_symbols)
        return result
    finally:
        job_lock.release()
        gc.collect()


@app.get("/api/paper-trading/account")
async def paper_trading_account(request: Request) -> Dict[str, object]:
    await guarded(request)
    from korean_ai_screening_simulator import paper_account_summary

    return paper_account_summary(account_id=_paper_device_id(request))


@app.post("/api/paper-trading/deposit")
async def paper_trading_deposit(request: Request) -> Dict[str, object]:
    await guarded(request)
    from korean_ai_screening_simulator import deposit_paper_cash, paper_account_summary

    payload = await _read_json_payload(request)
    amount = float(payload.get("amount", 0)) if isinstance(payload, dict) else 0.0
    account_id = _paper_device_id(request)
    try:
        deposit_paper_cash(amount, account_id=account_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return paper_account_summary(account_id=account_id)


@app.post("/api/paper-trading/simulate")
async def paper_trading_simulate(request: Request) -> Dict[str, object]:
    await guarded(request)
    from korean_ai_screening_simulator import paper_account_summary, simulate_paper_trade

    payload = await _read_json_payload(request)
    account_id = _paper_device_id(request)
    ticker = str(payload.get("ticker", "")).strip()
    try:
        validate_ticker(ticker)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    side = str(payload.get("side", "")).strip().lower()
    if side not in {"buy", "sell"}:
        raise HTTPException(status_code=400, detail="side must be buy or sell")
    try:
        simulate_paper_trade(
            ticker=ticker,
            quantity=float(payload.get("quantity", 0)),
            price=float(payload.get("price", 0)),
            side=side,
            cash_amount=float(payload.get("cash_amount", 0) or 0),
            account_id=account_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return paper_account_summary(account_id=account_id)


@app.get("/api/watchdog")
async def api_watchdog(request: Request, max_stale_seconds: int = Query(default=60, ge=10, le=86400)) -> Dict[str, object]:
    await guarded(request)
    from korean_ai_screening_simulator import watchdog_status

    return watchdog_status(max_stale_seconds=max_stale_seconds)


@app.get("/")
def root() -> Dict[str, object]:
    return {
        "ok": True,
        "service": "Market Scanner API",
        "endpoints": [
            "/api/health",
            "/api/status",
            "/api/results",
            "/api/results/force-refresh",
            "/api/refresh/quick",
            "/api/top-movers",
            "/api/scanner/run",
            "/api/scanner/status",
            "/api/cache/invalidate",
        ],
        "auth": "Send X-Market-Token, X-API-Token, or Authorization: Bearer <token>",
    }
