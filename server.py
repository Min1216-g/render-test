#!/usr/bin/env python3
"""Render-ready API server for the Market Scanner app."""

from __future__ import annotations

import csv
import os
import secrets
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
API_TOKEN = os.getenv("MARKET_API_TOKEN", "")
ALLOW_UNAUTH_HEALTH = os.getenv("MARKET_ALLOW_UNAUTH_HEALTH", "true").lower() == "true"
RATE_LIMIT_PER_MINUTE = int(os.getenv("MARKET_RATE_LIMIT_PER_MINUTE", "90"))
CACHE_TTL_SECONDS = int(os.getenv("MARKET_RESULTS_CACHE_TTL", "20"))

app = FastAPI(title="Market Scanner API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("MARKET_CORS_ORIGINS", "*").split(",")],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["X-Market-Token", "X-API-Token", "Authorization", "Content-Type"],
)

_request_log: Dict[str, Deque[float]] = defaultdict(deque)
_cache_rows: List[Dict[str, str]] = []
_cache_loaded_at = 0.0
_cache_file_mtime = 0.0


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
    return {
        "ok": True,
        "rows": len(rows),
        "ok_rows": ok_rows,
        "markets": sorted({row.get("market", "") for row in rows if row.get("market")}),
        "file_updated_at": mtime,
        "server_updated_at": _now_iso(),
    }


@app.get("/api/results")
async def results(
    request: Request,
    market: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(default=800, ge=1, le=1200),
) -> Dict[str, object]:
    await guarded(request)
    rows = _filter_rows(_read_rows(), market=market, q=q, limit=limit)
    return {
        "ok": True,
        "count": len(rows),
        "rows": rows,
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
        "endpoints": ["/api/health", "/api/status", "/api/results", "/api/top-movers"],
        "auth": "Send X-Market-Token, X-API-Token, or Authorization: Bearer <token>",
    }
