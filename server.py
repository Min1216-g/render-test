#!/usr/bin/env python3
"""Render-ready API server for the Market Scanner app."""

from __future__ import annotations

import csv
import gc
import json
import os
import resource
import shutil
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse


BASE_DIR = Path(__file__).resolve().parent
RESULT_FILE = Path(os.getenv("MARKET_RESULTS_FILE", BASE_DIR / "market_scanner_results.csv"))
IOS_RESULT_FILE = BASE_DIR / "MarketScannerIOS" / "MarketScannerIOS" / "market_scanner_results.csv"
REFRESH_SCRIPT = BASE_DIR / os.getenv("MARKET_SCANNER_REFRESH_SCRIPT", "render_mobile_refresh.py")
MOBILE_INTEL_SCRIPT = BASE_DIR / "mobile_intelligence_feed.py"
SCANNER_STATUS_FILE = BASE_DIR / "scanner_run_status.json"
API_TOKEN = os.getenv("MARKET_API_TOKEN", "")
ALLOW_UNAUTH_HEALTH = os.getenv("MARKET_ALLOW_UNAUTH_HEALTH", "true").lower() == "true"
RATE_LIMIT_PER_MINUTE = int(os.getenv("MARKET_RATE_LIMIT_PER_MINUTE", "90"))
CACHE_TTL_SECONDS = int(os.getenv("MARKET_RESULTS_CACHE_TTL", "20"))
SCANNER_RUN_COOLDOWN_SECONDS = int(os.getenv("MARKET_SCANNER_RUN_COOLDOWN_SECONDS", "3600"))
ENABLE_FULL_SCANNER = os.getenv("MARKET_ENABLE_FULL_SCANNER", "true").lower() == "true"
SCANNER_DEFAULT_MAX_WORKERS = os.getenv("MARKET_RENDER_SCANNER_MAX_WORKERS", "4")
SCANNER_DEFAULT_MAX_STOCKS = os.getenv("MARKET_RENDER_SCANNER_MAX_STOCKS", "550")
SCANNER_ENABLE_INTRADAY_1M = os.getenv("MARKET_RENDER_ENABLE_INTRADAY_1M", "false")
MAX_UPLOAD_BYTES = int(os.getenv("MARKET_RESULTS_UPLOAD_MAX_BYTES", "6000000"))
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


@app.on_event("startup")
def startup_cleanup() -> None:
    _cleanup_runtime_storage()


@app.middleware("http")
async def no_store_api_cache(request: Request, call_next):
    started = time.time()
    response = await call_next(request)
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


def _memory_rss_mb() -> float:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = float(usage.ru_maxrss)
    if sys.platform == "darwin":
        rss = rss / 1024 / 1024
    else:
        rss = rss / 1024
    return round(rss, 2)


def _log_memory(stage: str, **extra: object) -> None:
    details = " ".join(f"{key}={value}" for key, value in extra.items() if value is not None)
    print(f"[MEM] {stage} rss_mb={_memory_rss_mb()} {details}".strip(), flush=True)


def _invalidate_results_cache() -> None:
    global _cache_rows, _cache_loaded_at, _cache_file_mtime, _cache_file_path
    _cache_rows = []
    _cache_loaded_at = 0.0
    _cache_file_mtime = 0.0
    _cache_file_path = ""
    gc.collect()


def _current_result_snapshot() -> Dict[str, object]:
    path = _result_path()
    if not path.exists():
        return {"rows": 0, "ok_rows": 0, "file_updated_at": "", "data_generated_at": ""}
    rows = _read_rows()
    return {
        "rows": len(rows),
        "ok_rows": sum(1 for row in rows if row.get("status", "ok") == "ok"),
        "file_updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "data_generated_at": max((row.get("mobile_intel_generated_at", "") for row in rows), default=""),
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _cache_rows = [_public_row(row) for row in reader]
    _cache_loaded_at = now
    _cache_file_mtime = file_mtime
    _cache_file_path = file_path
    return _cache_rows


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
    return rows


def _replace_result_file(payload: bytes, rows: List[Dict[str, str]]) -> None:
    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(RESULT_FILE.parent), prefix=".results-", suffix=".csv") as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(RESULT_FILE)

    if IOS_RESULT_FILE.parent.exists():
        IOS_RESULT_FILE.write_bytes(payload)

    _invalidate_results_cache()
    _read_rows()


def _read_scanner_status() -> Dict[str, object]:
    if not SCANNER_STATUS_FILE.exists():
        path = _result_path()
        if path.exists():
            file_updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")
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


def _run_scanner_background() -> None:
    global _scanner_running, _scanner_last_seen_mtime
    try:
        _log_memory("scanner-start")
        _cleanup_runtime_storage()
        _clear_runtime_api_caches()
        started_at = time.time()
        current_path = _result_path()
        _scanner_last_seen_mtime = current_path.stat().st_mtime if current_path.exists() else 0.0
        _write_scanner_status(
            running=True,
            state="running",
            message="스캐너 실행 시작 · 캐시 초기화 완료... 8%",
            progress=8,
            started_at=started_at,
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
        scanner_env.setdefault("MOBILE_INTEL_MAX_NEWS_OBSERVATIONS", "1200")

        _write_scanner_status(
            running=True,
            state="running",
            message="AI 분석/뉴스 수집 실행중... 25%",
            progress=25,
            started_at=started_at,
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
                        _log_memory("scanner-partial-data", rows=snapshot.get("rows"), ok_rows=snapshot.get("ok_rows"))
                        _write_scanner_status(
                            running=True,
                            state="partial_data",
                            message=f"부분 데이터 반영됨 · {snapshot['ok_rows']}/{snapshot['rows']} 정상 · 모바일 재조회 가능",
                            progress=max(35, int(current_status.get("progress") or 35)),
                            started_at=started_at,
                            **snapshot,
                        )
                        last_heartbeat = now
                if now - last_heartbeat >= 15:
                    snapshot = _current_result_snapshot()
                    progress = min(80, max(25, int(current_status.get("progress") or 25) + 1))
                    _write_scanner_status(
                        running=True,
                        state="running",
                        message=f"AI 분석/뉴스 수집 실행중... {progress}%",
                        progress=progress,
                        started_at=started_at,
                        **snapshot,
                    )
                    last_heartbeat = now
                time.sleep(5)

            stdout_log.flush()
            stderr_log.flush()
            stdout_log.seek(0)
            stderr_log.seek(0)
            stdout = stdout_log.read()
            stderr = stderr_log.read()
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
        )
        _invalidate_results_cache()
        rows = _read_rows()
        ok_rows = sum(1 for row in rows if row.get("status", "ok") == "ok")
        _log_memory("scanner-completed", rows=len(rows), ok_rows=ok_rows)
        _write_scanner_status(
            running=False,
            state="completed",
            message=f"스캐너 완료 · {ok_rows}/{len(rows)} 정상",
            rows=len(rows),
            ok_rows=ok_rows,
            mode="full",
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
    filtered = []
    for row in rows:
        if market_filter and row.get("market", "") != market_filter:
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
    return JSONResponse(
        status_code=exc.status_code,
        content={"ok": False, "error": exc.detail, "updated_at": _now_iso()},
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
    rows = _read_rows()
    path = _result_path()
    mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.exists() else ""
    ok_rows = sum(1 for row in rows if row.get("status", "ok") == "ok")
    generated_at = max((row.get("mobile_intel_generated_at", "") for row in rows), default="")
    scanner_status = _read_scanner_status()
    return {
        "ok": True,
        "rows": len(rows),
        "ok_rows": ok_rows,
        "markets": sorted({row.get("market", "") for row in rows if row.get("market")}),
        "result_file": path.name,
        "file_updated_at": mtime,
        "data_generated_at": generated_at,
        "server_updated_at": _now_iso(),
        "scanner": scanner_status,
    }


@app.post("/api/refresh/quick")
async def quick_refresh(request: Request) -> Dict[str, object]:
    await guarded(request)
    started = time.time()
    _invalidate_results_cache()
    rows = _read_rows()
    snapshot = _current_result_snapshot()
    _write_scanner_status(
        running=False,
        state="quick_refreshed",
        message=f"빠른 갱신 완료 · 기존 최신 데이터 즉시 반영 · {snapshot.get('ok_rows', 0)}/{snapshot.get('rows', 0)} 정상",
        progress=100,
        mode="quick",
        **snapshot,
    )
    _log_memory("quick-refresh", rows=len(rows), duration_ms=int((time.time() - started) * 1000))
    return {
        "ok": True,
        "message": "quick refresh completed",
        "count": len(rows),
        "status": _read_scanner_status(),
        **snapshot,
        "updated_at": _now_iso(),
    }


@app.post("/api/scanner/run")
async def scanner_run(request: Request) -> Dict[str, object]:
    global _scanner_running
    await guarded(request)
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
        current_status = _read_scanner_status()
        cooldown_payload = _scanner_cooldown_payload(current_status)
        if cooldown_payload:
            _invalidate_results_cache()
            return cooldown_payload
        _scanner_running = True
        _clear_runtime_api_caches()
        quick_snapshot = _current_result_snapshot()
        _write_scanner_status(
            running=True,
            state="queued",
            message="빠른 데이터 반영 완료 · 백그라운드 스캐너 대기... 5%",
            progress=5,
            started_at=time.time(),
            **quick_snapshot,
        )
        thread = threading.Thread(target=_run_scanner_background, daemon=True)
        thread.start()
    return {
        "ok": True,
        "started": True,
        "running": True,
        "message": "스캐너 백그라운드 실행 시작",
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
    path = _result_path()
    file_updated_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds") if path.exists() else ""
    rows = _filter_rows(_read_rows(), market=market, q=q, limit=limit)
    generated_at = max((row.get("mobile_intel_generated_at", "") for row in rows), default="")
    return {
        "ok": True,
        "count": len(rows),
        "rows": rows,
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

    rows = _parse_csv_bytes(payload)
    _replace_result_file(payload, rows)
    ok_rows = sum(1 for row in rows if row.get("status", "ok") == "ok")
    _write_scanner_status(
        running=False,
        state="uploaded",
        message=f"CSV 즉시 업로드 완료 · {ok_rows}/{len(rows)} 정상",
        rows=len(rows),
        ok_rows=ok_rows,
        mode="upload",
        progress=100,
    )
    return {
        "ok": True,
        "rows": len(rows),
        "ok_rows": ok_rows,
        "file_updated_at": datetime.fromtimestamp(RESULT_FILE.stat().st_mtime).isoformat(timespec="seconds"),
        "updated_at": _now_iso(),
    }


@app.get("/api/top-movers")
async def top_movers(
    request: Request,
    market: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, object]:
    await guarded(request)
    rows = _filter_rows(_read_rows(), market=market, limit=2000)
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
