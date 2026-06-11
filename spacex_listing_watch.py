#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from xml.etree import ElementTree

import requests


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "spacex_listing_watch_state.json"
YAHOO_SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
YAHOO_QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_SUMMARY_URL = "https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
NASDAQ_IPO_URL = "https://api.nasdaq.com/api/ipo/calendar"
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"
HTTP_TIMEOUT = 8

CORE_SPACE_COMPANIES = [
    {"name": "SpaceX", "aliases": ["Space Exploration Technologies Corp", "SpaceX"], "public": False},
    {"name": "Starlink", "aliases": ["Starlink"], "public": False},
    {"name": "Blue Origin", "aliases": ["Blue Origin"], "public": False},
    {"name": "Rocket Lab", "aliases": ["Rocket Lab", "RKLB"], "public": True, "ticker": "RKLB"},
    {"name": "Intuitive Machines", "aliases": ["Intuitive Machines", "LUNR"], "public": True, "ticker": "LUNR"},
    {"name": "Planet Labs", "aliases": ["Planet Labs", "PL"], "public": True, "ticker": "PL"},
]

LISTING_KEYWORDS = [
    "Space Exploration Technologies Corp",
    "SpaceX",
    "Starlink",
    "SpaceX IPO",
    "Starlink IPO",
    "SpaceX direct listing",
    "Starlink direct listing",
]

EVENT_KEYWORDS = [
    "SpaceX",
    "Starlink",
    "Starship",
    "Falcon 9",
    "Elon Musk",
    "Space Launch",
    "Launch Failure",
    "Launch Success",
    "Government Contract",
    "NASA Contract",
]

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


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "en-US,en;q=0.8,ko;q=0.7",
        }
    )
    return session


def _candidate_tickers() -> List[str]:
    raw = os.getenv("SPACEX_TICKER_CANDIDATES", "").strip()
    candidates: List[str] = []
    if raw:
        candidates.extend(item.strip().upper() for item in raw.split(",") if item.strip())

    # Probe only. Every candidate is validated against name and price data.
    candidates.extend(["SPACEX", "SPACE", "SPCX", "SX", "X"])
    return [ticker for ticker in dict.fromkeys(candidates) if ticker and ticker not in EXCLUDED_TICKERS]


def _looks_like_spacex_quote(quote: Dict[str, object]) -> bool:
    text = " ".join(
        str(quote.get(key, ""))
        for key in ("symbol", "shortname", "longname", "name", "exchDisp")
    ).lower()
    if any(bad in text for bad in ("virgin galactic", "spdr", "space etf", "procure space")):
        return False
    return bool(re.search(r"\bspace\s*x\b|spacex|space exploration technologies|starlink", text))


def _get_recent_quote_meta(session: requests.Session, ticker: str) -> Dict[str, object]:
    try:
        response = session.get(
            YAHOO_QUOTE_URL.format(ticker=ticker),
            params={"range": "5d", "interval": "1d"},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        result = (response.json().get("chart", {}).get("result") or [None])[0]
        if not result:
            return {}
        meta = result.get("meta") or {}
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        if price is None:
            return {}
        return meta
    except Exception:
        return {}


def _get_summary_stats(session: requests.Session, ticker: str) -> Dict[str, object]:
    try:
        response = session.get(
            YAHOO_SUMMARY_URL.format(ticker=ticker),
            params={"modules": "price,summaryDetail,defaultKeyStatistics"},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        result = (response.json().get("quoteSummary", {}).get("result") or [None])[0] or {}
    except Exception:
        return {}

    def raw_value(*path: str):
        cursor = result
        for part in path:
            if not isinstance(cursor, dict):
                return None
            cursor = cursor.get(part)
        if isinstance(cursor, dict) and "raw" in cursor:
            return cursor.get("raw")
        return cursor

    return {
        "market_cap": raw_value("price", "marketCap"),
        "shares_outstanding": raw_value("defaultKeyStatistics", "sharesOutstanding"),
        "float_shares": raw_value("defaultKeyStatistics", "floatShares"),
        "currency": raw_value("price", "currency"),
    }


def _search_yahoo(session: requests.Session, query: str) -> List[Dict[str, object]]:
    try:
        response = session.get(
            YAHOO_SEARCH_URL,
            params={"q": query, "quotesCount": 20, "newsCount": 0},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("quotes") or []
    except Exception:
        return []


def _search_yahoo_for_spacex(session: requests.Session) -> List[str]:
    matches: List[str] = []
    for query in ("SpaceX", "Space Exploration Technologies Corp", "Starlink IPO"):
        for quote in _search_yahoo(session, query):
            ticker = str(quote.get("symbol") or "").upper().strip()
            if not ticker or ticker in EXCLUDED_TICKERS:
                continue
            if quote.get("quoteType") not in {"EQUITY", "ETF"}:
                continue
            if _looks_like_spacex_quote(quote):
                matches.append(ticker)
    return list(dict.fromkeys(matches))


def _nasdaq_ipo_candidates(session: requests.Session) -> List[Dict[str, str]]:
    try:
        response = session.get(NASDAQ_IPO_URL, timeout=HTTP_TIMEOUT)
        response.raise_for_status()
        rows = ((response.json().get("data") or {}).get("upcoming") or {}).get("rows") or []
    except Exception:
        return []

    matches = []
    for row in rows:
        text = json.dumps(row, ensure_ascii=False).lower()
        if not any(term.lower() in text for term in ("spacex", "starlink", "space exploration technologies")):
            continue
        symbol = str(row.get("proposedTickerSymbol") or row.get("symbol") or "").upper().strip()
        company = str(row.get("companyName") or row.get("name") or "SpaceX").strip()
        matches.append({"source": "nasdaq_ipo_calendar", "symbol": symbol, "company": company})
    return matches


def _news_candidates(session: requests.Session) -> List[Dict[str, str]]:
    query = '"SpaceX" OR "Starlink" ("IPO" OR "direct listing" OR "ticker" OR "NASDAQ" OR "NYSE")'
    try:
        response = session.get(
            GOOGLE_NEWS_RSS_URL,
            params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
            timeout=HTTP_TIMEOUT,
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except Exception:
        return []

    candidates = []
    for item in root.findall(".//item")[:12]:
        title = (item.findtext("title") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        lower = title.lower()
        if not any(term in lower for term in ("spacex", "starlink", "space exploration technologies")):
            continue
        if not any(term in lower for term in ("ipo", "direct listing", "ticker", "nasdaq", "nyse")):
            continue
        tickers = re.findall(r"(?:NASDAQ|NYSE)\s*:\s*([A-Z]{1,6})|\(([A-Z]{1,6})\)|ticker\s+([A-Z]{1,6})", title)
        flat = [part for group in tickers for part in group if part]
        published_iso = ""
        if published:
            try:
                published_iso = parsedate_to_datetime(published).astimezone(timezone.utc).isoformat()
            except Exception:
                published_iso = published
        candidates.append(
            {
                "source": "google_news_rss",
                "title": title,
                "published_at": published_iso,
                "symbol": flat[0].upper() if flat else "",
            }
        )
    return candidates


def _confirmed_payload(
    ticker: str,
    meta: Dict[str, object],
    stats: Dict[str, object],
    source: str,
    checked: Iterable[str],
    listing_news: List[Dict[str, str]],
) -> Dict[str, object]:
    price = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0.0)
    market_cap = stats.get("market_cap") or meta.get("marketCap") or 0
    shares = stats.get("shares_outstanding") or (float(market_cap) / price if price and market_cap else 0)
    float_shares = stats.get("float_shares") or 0
    ipo_price = os.getenv("SPACEX_IPO_PRICE", "").strip()
    ipo_return_pct = 0.0
    try:
        ipo_price_value = float(ipo_price)
        if ipo_price_value > 0 and price > 0:
            ipo_return_pct = (price / ipo_price_value - 1) * 100
    except Exception:
        ipo_price_value = 0.0

    return {
        "status": "auto_confirmed",
        "listing_confirmed": True,
        "ticker": ticker,
        "name": "SpaceX",
        "sector": "미장/로켓/우주/IPO",
        "display_status": "상장 감지 완료",
        "source": source,
        "checked_at": _now_iso(),
        "checked_candidates": list(dict.fromkeys(checked)),
        "keywords": EVENT_KEYWORDS,
        "core_space_companies": CORE_SPACE_COMPANIES,
        "listing_news": listing_news[:5],
        "ipo_initial_analysis": {
            "price": price,
            "currency": stats.get("currency") or meta.get("currency") or "USD",
            "market_cap_estimate": market_cap or 0,
            "shares_outstanding_estimate": shares or 0,
            "float_shares_estimate": float_shares or 0,
            "ipo_price": ipo_price_value if "ipo_price_value" in locals() else 0.0,
            "ipo_return_pct": round(ipo_return_pct, 2),
            "volume": meta.get("regularMarketVolume") or 0,
            "institution_flow_status": "상장 초기 수급 추적 대기",
            "news_sentiment_status": "상장 뉴스 감성 분석 대상",
            "ai_risk": "IPO 초기 변동성 높음 · 락업/유통주식수 확인 필요",
        },
        "mobile_sync": {
            "auto_register": True,
            "invalidate_cache": True,
            "show_in_search": True,
            "include_today_score": True,
            "include_ai_recommendation": True,
            "include_sector_flow": True,
            "include_etf_analysis": True,
        },
    }


def _waiting_payload(checked: Iterable[str], news: List[Dict[str, str]], ipo_rows: List[Dict[str, str]]) -> Dict[str, object]:
    return {
        "status": "waiting_for_public_ticker",
        "listing_confirmed": False,
        "ticker": "",
        "name": "SpaceX",
        "sector": "미장/로켓/우주/IPO",
        "display_status": "비상장 기업 · 상장 감시중",
        "checked_at": _now_iso(),
        "checked_candidates": list(dict.fromkeys(checked)),
        "keywords": EVENT_KEYWORDS,
        "listing_keywords": LISTING_KEYWORDS,
        "core_space_companies": CORE_SPACE_COMPANIES,
        "listing_news": news[:5],
        "ipo_calendar_matches": ipo_rows[:5],
        "mobile_sync": {
            "auto_register": False,
            "invalidate_cache": False,
            "show_private_status": True,
            "include_sector_news": True,
            "include_etf_private_exposure": True,
        },
    }


def _save_state(payload: Dict[str, object]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def load_space_industry_watch_state() -> Dict[str, object]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def detect_spacex_public_listing() -> Dict[str, object]:
    manual_ticker = os.getenv("SPACEX_PUBLIC_TICKER", "").strip().upper()
    session = _session()
    yahoo_matches = _search_yahoo_for_spacex(session)
    ipo_rows = _nasdaq_ipo_candidates(session)
    news = _news_candidates(session)

    candidates: List[Tuple[str, str]] = []
    if manual_ticker:
        candidates.append((manual_ticker, "manual_env"))
    candidates.extend((item.get("symbol", ""), item.get("source", "nasdaq_ipo_calendar")) for item in ipo_rows if item.get("symbol"))
    candidates.extend((item.get("symbol", ""), item.get("source", "google_news_rss")) for item in news if item.get("symbol"))
    candidates.extend((ticker, "yahoo_search") for ticker in yahoo_matches)
    candidates.extend((ticker, "ticker_probe") for ticker in _candidate_tickers())

    checked: List[str] = []
    for ticker, source in candidates:
        ticker = str(ticker or "").upper().strip()
        if not ticker or ticker in EXCLUDED_TICKERS:
            continue
        checked.append(ticker)
        meta = _get_recent_quote_meta(session, ticker)
        if not meta:
            continue
        if manual_ticker and ticker == manual_ticker:
            stats = _get_summary_stats(session, ticker)
            payload = _confirmed_payload(ticker, meta, stats, "manual_env", checked, news)
            payload["status"] = "manual_confirmed"
            _save_state(payload)
            return payload
        if ticker not in yahoo_matches:
            continue
        stats = _get_summary_stats(session, ticker)
        payload = _confirmed_payload(ticker, meta, stats, source, checked, news)
        _save_state(payload)
        return payload

    payload = _waiting_payload(checked, news, ipo_rows)
    _save_state(payload)
    return payload


def load_spacex_public_listing() -> Tuple[Dict[str, str], Dict[str, str]]:
    """Return a stock entry only after SpaceX has a validated public quote."""
    payload = detect_spacex_public_listing()
    ticker = str(payload.get("ticker") or "").strip().upper()
    if payload.get("listing_confirmed") and ticker:
        return {"SpaceX": ticker}, {"SpaceX": "미장/로켓/우주/IPO"}
    return {}, {}


if __name__ == "__main__":
    state = detect_spacex_public_listing()
    if state.get("listing_confirmed"):
        print(f"SpaceX public listing detected: {state.get('ticker')}")
    else:
        print("SpaceX public listing not detected yet. Private watch mode active.")
