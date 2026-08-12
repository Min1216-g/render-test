#!/usr/bin/env python3
"""Market data provider router.

Project code should ask this module for quotes/history instead of calling a
single vendor directly.  FMP is used first when configured, while Yahoo remains
as a fallback so existing behavior keeps working when paid/free API limits hit.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple

import pandas as pd
import requests
import yfinance as yf


FMP_API_KEY = os.getenv("FMP_API_KEY") or os.getenv("FINANCIAL_MODELING_PREP_API_KEY") or ""
FMP_BASE_URL = os.getenv("FMP_BASE_URL", "https://financialmodelingprep.com/api/v3").rstrip("/")
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
PROVIDER_ORDER = [
    item.strip().lower()
    for item in os.getenv("MARKET_DATA_PROVIDER_ORDER", "fmp,yahoo").split(",")
    if item.strip()
]
QUOTE_TTL_SECONDS = int(os.getenv("MARKET_DATA_QUOTE_TTL_SECONDS", "15"))
HISTORY_TTL_SECONDS = int(os.getenv("MARKET_DATA_HISTORY_TTL_SECONDS", "1800"))
REQUEST_TIMEOUT_SECONDS = int(os.getenv("MARKET_DATA_TIMEOUT_SECONDS", "8"))
MAX_CACHE_ITEMS = max(32, int(os.getenv("MARKET_DATA_CACHE_MAX_ITEMS", "512")))

_session = requests.Session()
_session.headers.update({"User-Agent": "MarketScanner/1.0"})
_cache_lock = threading.Lock()
_quote_cache: Dict[str, Tuple[float, "MarketQuote"]] = {}
_history_cache: Dict[Tuple[str, str, str], Tuple[float, pd.DataFrame]] = {}


@dataclass
class MarketQuote:
    symbol: str
    price: float = 0.0
    change_pct: Optional[float] = None
    previous_close: Optional[float] = None
    volume: Optional[float] = None
    market_cap: Optional[float] = None
    currency: str = ""
    source: str = ""
    provider: str = ""
    updated_at: str = ""
    status: str = "unavailable"
    error: str = ""

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _bounded_set(cache: Dict, key, value) -> None:
    cache[key] = value
    while len(cache) > MAX_CACHE_ITEMS:
        try:
            cache.pop(next(iter(cache)))
        except StopIteration:
            break


def _safe_float(value, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        number = float(value)
        if number != number:
            return default
        return number
    except (TypeError, ValueError):
        return default


def _fmp_symbol(symbol: str) -> str:
    clean = str(symbol or "").strip().upper()
    if clean.endswith(".TO"):
        return f"TSX:{clean[:-3]}"
    if clean.endswith(".V"):
        return f"TSXV:{clean[:-2]}"
    return clean


def _period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    period = str(period or "6mo").lower()
    if period.endswith("mo"):
        return now - timedelta(days=max(1, int(period[:-2] or "6")) * 31)
    if period.endswith("y"):
        return now - timedelta(days=max(1, int(period[:-1] or "1")) * 366)
    if period.endswith("d"):
        return now - timedelta(days=max(1, int(period[:-1] or "30")))
    return now - timedelta(days=180)


def _normalize_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame()
    df = frame.copy()
    rename_map = {
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "adjClose": "Adj Close",
        "volume": "Volume",
    }
    df = df.rename(columns={key: value for key, value in rename_map.items() if key in df.columns})
    keep = [column for column in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if column in df.columns]
    df = df[keep]
    for column in keep:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df.dropna(subset=["Close"]) if "Close" in df.columns else df


def _quote_from_fmp(symbol: str) -> MarketQuote:
    if not FMP_API_KEY:
        raise RuntimeError("FMP API key not configured")
    response = _session.get(
        f"{FMP_BASE_URL}/quote/{_fmp_symbol(symbol)}",
        params={"apikey": FMP_API_KEY},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    items = response.json()
    if not isinstance(items, list) or not items:
        raise RuntimeError("FMP quote empty")
    item = items[0]
    price = _safe_float(item.get("price"), 0.0) or 0.0
    previous_close = _safe_float(item.get("previousClose"))
    change_pct = _safe_float(item.get("changesPercentage"))
    if price <= 0:
        raise RuntimeError("FMP quote has no price")
    return MarketQuote(
        symbol=str(item.get("symbol") or symbol).upper(),
        price=price,
        change_pct=change_pct,
        previous_close=previous_close,
        volume=_safe_float(item.get("volume")),
        market_cap=_safe_float(item.get("marketCap")),
        currency=str(item.get("currency") or ""),
        source="fmp_quote",
        provider="fmp",
        updated_at=_now_iso(),
        status="ok",
    )


def _quote_from_yahoo(symbol: str) -> MarketQuote:
    try:
        response = _session.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": "5d", "interval": "1m", "includePrePost": "true"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = (((response.json().get("chart") or {}).get("result") or [None])[0]) or {}
        meta = result.get("meta") or {}
        candidates = [
            ("yahoo_chart_post", meta.get("postMarketPrice")),
            ("yahoo_chart_pre", meta.get("preMarketPrice")),
            ("yahoo_chart_regular", meta.get("regularMarketPrice")),
            ("yahoo_chart_previous", meta.get("previousClose")),
        ]
        previous_close = _safe_float(meta.get("previousClose"))
        for source, raw_price in candidates:
            price = _safe_float(raw_price)
            if price and price > 0:
                change_pct = ((price / previous_close) - 1) * 100 if previous_close else None
                return MarketQuote(
                    symbol=symbol.upper(),
                    price=price,
                    change_pct=change_pct,
                    previous_close=previous_close,
                    volume=_safe_float(meta.get("regularMarketVolume")),
                    market_cap=_safe_float(meta.get("marketCap")),
                    currency=str(meta.get("currency") or ""),
                    source=source,
                    provider="yahoo",
                    updated_at=_now_iso(),
                    status="ok",
                )
    except Exception:
        pass

    fast_info = yf.Ticker(symbol).fast_info
    getter = fast_info.get if hasattr(fast_info, "get") else lambda key, default=None: getattr(fast_info, key, default)
    price = None
    for key in ("last_price", "lastPrice", "regular_market_price", "regularMarketPrice"):
        price = _safe_float(getter(key))
        if price and price > 0:
            break
    previous_close = None
    for key in ("previous_close", "previousClose", "regular_market_previous_close", "regularMarketPreviousClose"):
        previous_close = _safe_float(getter(key))
        if previous_close and previous_close > 0:
            break
    if not price or price <= 0:
        raise RuntimeError("Yahoo quote has no price")
    change_pct = ((price / previous_close) - 1) * 100 if previous_close else None
    return MarketQuote(
        symbol=symbol.upper(),
        price=price,
        change_pct=change_pct,
        previous_close=previous_close,
        volume=_safe_float(getter("last_volume") or getter("lastVolume")),
        market_cap=_safe_float(getter("market_cap") or getter("marketCap")),
        currency=str(getter("currency") or ""),
        source="yahoo_fast_info",
        provider="yahoo",
        updated_at=_now_iso(),
        status="ok",
    )


def get_quote(symbol: str, *, use_cache: bool = True) -> MarketQuote:
    clean = str(symbol or "").strip().upper()
    if not clean:
        return MarketQuote(symbol=clean, status="unavailable", error="empty symbol", updated_at=_now_iso())
    now = time.time()
    with _cache_lock:
        cached = _quote_cache.get(clean)
        if use_cache and cached and now - cached[0] < QUOTE_TTL_SECONDS:
            return cached[1]
    errors = []
    for provider in PROVIDER_ORDER:
        try:
            quote = _quote_from_fmp(clean) if provider == "fmp" else _quote_from_yahoo(clean)
            with _cache_lock:
                _bounded_set(_quote_cache, clean, (now, quote))
            return quote
        except Exception as exc:
            errors.append(f"{provider}:{str(exc)[:80]}")
            continue
    quote = MarketQuote(symbol=clean, status="error", error="; ".join(errors), updated_at=_now_iso())
    with _cache_lock:
        _bounded_set(_quote_cache, clean, (now, quote))
    return quote


def _history_from_fmp(symbol: str, period: str, interval: str) -> pd.DataFrame:
    if not FMP_API_KEY:
        raise RuntimeError("FMP API key not configured")
    if str(interval or "1d").lower() != "1d":
        raise RuntimeError("FMP fallback supports daily interval only")
    start = _period_start(period).date().isoformat()
    response = _session.get(
        f"{FMP_BASE_URL}/historical-price-full/{_fmp_symbol(symbol)}",
        params={"from": start, "apikey": FMP_API_KEY},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    historical = response.json().get("historical") or []
    if not historical:
        raise RuntimeError("FMP history empty")
    frame = pd.DataFrame(historical)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).sort_values("date").set_index("date")
    return _normalize_ohlcv(frame)


def _history_from_yahoo(symbol: str, period: str, interval: str) -> pd.DataFrame:
    try:
        response = _session.get(
            YAHOO_CHART_URL.format(symbol=symbol),
            params={"range": period, "interval": interval, "includePrePost": "true", "events": "div,splits"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = (((response.json().get("chart") or {}).get("result") or [None])[0]) or {}
        timestamps = result.get("timestamp") or []
        quote_items = (((result.get("indicators") or {}).get("quote") or [{}])[0]) or {}
        if timestamps and quote_items:
            data = {
                "Open": quote_items.get("open") or [],
                "High": quote_items.get("high") or [],
                "Low": quote_items.get("low") or [],
                "Close": quote_items.get("close") or [],
                "Volume": quote_items.get("volume") or [],
            }
            size = min([len(timestamps)] + [len(values) for values in data.values() if isinstance(values, list)])
            if size > 0:
                frame = pd.DataFrame({key: values[:size] for key, values in data.items()})
                frame.index = pd.to_datetime(timestamps[:size], unit="s", utc=True)
                return _normalize_ohlcv(frame)
    except Exception:
        pass
    frame = yf.download(symbol, period=period, interval=interval, progress=False, threads=False, auto_adjust=False)
    return _normalize_ohlcv(frame)


def get_historical_ohlcv(symbol: str, period: str = "6mo", interval: str = "1d", *, use_cache: bool = True) -> pd.DataFrame:
    clean = str(symbol or "").strip().upper()
    if not clean:
        return pd.DataFrame()
    key = (clean, str(period), str(interval))
    now = time.time()
    with _cache_lock:
        cached = _history_cache.get(key)
        if use_cache and cached and now - cached[0] < HISTORY_TTL_SECONDS:
            return cached[1].copy()
    for provider in PROVIDER_ORDER:
        try:
            frame = _history_from_fmp(clean, period, interval) if provider == "fmp" else _history_from_yahoo(clean, period, interval)
            if frame is not None and not frame.empty:
                with _cache_lock:
                    _bounded_set(_history_cache, key, (now, frame))
                return frame.copy()
        except Exception:
            continue
    return pd.DataFrame()


def clear_provider_caches() -> None:
    with _cache_lock:
        _quote_cache.clear()
        _history_cache.clear()
