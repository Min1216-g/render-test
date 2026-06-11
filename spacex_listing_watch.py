#!/usr/bin/env python3

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import requests


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "spacex_listing_watch_state.json"
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
HTTP_TIMEOUT = 8

EXCLUDED_TICKERS = {
    "SPCE",  # Virgin Galactic
    "RKLB",
    "ASTS",
    "PL",
    "LUNR",
    "RDW",
    "BA",
    "LMT",
    "NOC",
}


def _now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _session():
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.8,ko;q=0.7",
        }
    )
    return session


def _candidate_tickers():
    raw = os.getenv("SPACEX_TICKER_CANDIDATES", "").strip()
    candidates = []
    if raw:
        candidates.extend(item.strip().upper() for item in raw.split(",") if item.strip())

    # These are only probes. They are validated before use and ignored if they
    # resolve to a different company or have no public quote data.
    candidates.extend(["SPACEX", "SPACE", "SPCX", "SX", "X"])
    return [ticker for ticker in dict.fromkeys(candidates) if ticker not in EXCLUDED_TICKERS]


def _looks_like_spacex_quote(quote):
    text = " ".join(
        str(quote.get(key, ""))
        for key in ("symbol", "shortname", "longname", "name", "exchDisp")
    ).lower()
    if "virgin galactic" in text:
        return False
    return bool(re.search(r"\bspace\s*x\b|spacex", text))


def _has_recent_price(session, ticker):
    try:
        response = session.get(
            YAHOO_QUOTE_URL.format(ticker=ticker),
            params={"range": "5d", "interval": "1d"},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        result = (response.json().get("chart", {}).get("result") or [None])[0]
        if not result:
            return False
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        return price is not None
    except Exception:
        return False


def _search_yahoo_for_spacex(session):
    try:
        response = session.get(
            YAHOO_SEARCH_URL,
            params={"q": "SpaceX", "quotesCount": 12, "newsCount": 0},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        quotes = response.json().get("quotes") or []
    except Exception:
        return []

    matches = []
    for quote in quotes:
        ticker = str(quote.get("symbol") or "").upper().strip()
        if not ticker or ticker in EXCLUDED_TICKERS:
            continue
        if quote.get("quoteType") not in {"EQUITY", "ETF"}:
            continue
        if _looks_like_spacex_quote(quote):
            matches.append(ticker)
    return matches


def _save_state(payload):
    try:
        STATE_FILE.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def load_spacex_public_listing():
    """Return a stock entry only after SpaceX has a validated public quote."""
    manual_ticker = os.getenv("SPACEX_PUBLIC_TICKER", "").strip().upper()
    session = _session()
    candidates = []
    if manual_ticker:
        candidates.append(manual_ticker)
    candidates.extend(_search_yahoo_for_spacex(session))
    candidates.extend(_candidate_tickers())

    checked = []
    for ticker in dict.fromkeys(candidates):
        if not ticker or ticker in EXCLUDED_TICKERS:
            continue
        checked.append(ticker)
        if not _has_recent_price(session, ticker):
            continue
        if manual_ticker and ticker == manual_ticker:
            status = "manual_confirmed"
        else:
            # For non-manual candidates, require Yahoo search to have matched
            # the company name so we do not accidentally add a wrong ticker.
            if ticker not in _search_yahoo_for_spacex(session):
                continue
            status = "auto_confirmed"
        payload = {
            "status": status,
            "ticker": ticker,
            "name": "SpaceX",
            "sector": "미장/로켓/우주/IPO",
            "checked_at": _now_iso(),
            "checked_candidates": checked,
        }
        _save_state(payload)
        return {"SpaceX": ticker}, {"SpaceX": "미장/로켓/우주/IPO"}

    _save_state(
        {
            "status": "waiting_for_public_ticker",
            "ticker": "",
            "name": "SpaceX",
            "sector": "미장/로켓/우주/IPO",
            "checked_at": _now_iso(),
            "checked_candidates": checked,
        }
    )
    return {}, {}


if __name__ == "__main__":
    stocks, sectors = load_spacex_public_listing()
    if stocks:
        print(f"SpaceX public listing detected: {stocks['SpaceX']}")
    else:
        print("SpaceX public listing not detected yet.")
