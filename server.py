#!/usr/bin/env python3
"""Render-ready API server for the Market Scanner app."""

from __future__ import annotations

import csv
import json
import os
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
ENABLE_FULL_SCANNER = os.getenv("MARKET_ENABLE_FULL_SCANNER", "true").lower() == "true"
MAX_UPLOAD_BYTES = int(os.getenv("MARKET_RESULTS_UPLOAD_MAX_BYTES", "6000000"))
MIN_UPLOAD_ROWS = int(os.getenv("MARKET_RESULTS_UPLOAD_MIN_ROWS", "500"))
MIN_UPLOAD_OK_ROWS = int(os.getenv("MARKET_RESULTS_UPLOAD_MIN_OK_ROWS", "50"))

app = FastAPI(title="Market Scanner API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("MARKET_CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["X-Market-Token", "X-API-Token", "Authorization", "Content-Type"],
)


@app.middleware("http")
async def no_store_api_cache(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

_request_log: Dict[str, Deque[float]] = defaultdict(deque)
_cache_rows: List[Dict[str, str]] = []
_cache_loaded_at = 0.0
_cache_file_mtime = 0.0
_scanner_lock = threading.Lock()
_scanner_running = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _result_path() -> Path:
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
    global _cache_rows, _cache_loaded_at, _cache_file_mtime

    path = _result_path()
    if not path.exists():
        return []

    now = time.time()
    file_mtime = path.stat().st_mtime
    if _cache_rows and now - _cache_loaded_at < CACHE_TTL_SECONDS and file_mtime == _cache_file_mtime:
        return _cache_rows

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _cache_rows = [_public_row(row) for row in reader]
    _cache_loaded_at = now
    _cache_file_mtime = file_mtime
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
    global _cache_rows, _cache_loaded_at, _cache_file_mtime

    RESULT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("wb", delete=False, dir=str(RESULT_FILE.parent), prefix=".results-", suffix=".csv") as tmp:
        tmp.write(payload)
        tmp_path = Path(tmp.name)
    tmp_path.replace(RESULT_FILE)

    if IOS_RESULT_FILE.parent.exists():
        IOS_RESULT_FILE.write_bytes(payload)

    _cache_rows = rows
    _cache_loaded_at = time.time()
    _cache_file_mtime = RESULT_FILE.stat().st_mtime


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
            current_progress = int(status.get("progress") or 0)
            estimated_progress = min(90, max(current_progress, int(8 + elapsed / 1800 * 82)))
            status["progress"] = estimated_progress
            if estimated_progress >= 20 and status.get("state") == "running":
                status["message"] = f"스캐너 실행중... {estimated_progress}%"
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


def _run_scanner_background() -> None:
    global _scanner_running, _cache_loaded_at
    try:
        started_at = time.time()
        _write_scanner_status(
            running=True,
            state="running",
            message="스캐너 실행중... 8%",
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

        _write_scanner_status(
            running=True,
            state="running",
            message="AI 분석/뉴스 수집 실행중... 15%",
            progress=15,
            started_at=started_at,
        )
        update = subprocess.run(
            command,
            cwd=BASE_DIR,
            check=False,
            capture_output=True,
            text=True,
            timeout=int(os.getenv("MARKET_SCANNER_REFRESH_TIMEOUT", "1800")),
        )
        if update.returncode != 0:
            _write_scanner_status(
                running=False,
                state="failed",
                message="스캐너 실패",
                return_code=update.returncode,
                output=(update.stdout + "\n" + update.stderr)[-4000:],
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
                    output=(update.stdout + "\n" + enrich.stdout + "\n" + enrich.stderr)[-4000:],
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
        _cache_loaded_at = 0
        rows = _read_rows()
        ok_rows = sum(1 for row in rows if row.get("status", "ok") == "ok")
        _write_scanner_status(
            running=False,
            state="completed",
            message=f"스캐너 완료 · {ok_rows}/{len(rows)} 정상",
            rows=len(rows),
            ok_rows=ok_rows,
            mode="full",
            output=(update.stdout + "\n" + update.stderr)[-4000:],
            progress=100,
        )
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
    scanner_status = _read_scanner_status()
    return {
        "ok": True,
        "rows": len(rows),
        "ok_rows": ok_rows,
        "markets": sorted({row.get("market", "") for row in rows if row.get("market")}),
        "file_updated_at": mtime,
        "server_updated_at": _now_iso(),
        "scanner": scanner_status,
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
        _scanner_running = True
        _write_scanner_status(
            running=True,
            state="queued",
            message="스캐너 실행 요청됨... 0%",
            progress=0,
            started_at=time.time(),
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
    return {
        "ok": True,
        "count": len(rows),
        "rows": rows,
        "file_updated_at": file_updated_at,
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
        "endpoints": ["/api/health", "/api/status", "/api/results", "/api/top-movers", "/api/scanner/run", "/api/scanner/status"],
        "auth": "Send X-Market-Token, X-API-Token, or Authorization: Bearer <token>",
    }
