#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import requests
from concurrent.futures import TimeoutError

from canada_market_guard import is_canada_row, is_canada_ticker


BASE_DIR = Path(__file__).resolve().parent
CANADA_NEWS_CACHE_FILE = BASE_DIR / "canada_news_cache.json"
TORONTO_TZ = ZoneInfo("America/Toronto")
REQUEST_TIMEOUT = 8
COLLECT_TIMEOUT_SECONDS = int(os.getenv("CANADA_NEWS_COLLECT_TIMEOUT_SECONDS", "45"))
PRIMARY_NEWS_HOURS = 24
FALLBACK_NEWS_DAYS = 7
MAX_ITEMS_PER_TICKER = 5


OFFICIAL_NEWS_SOURCES = {
    "SHOP.TO": [
        {
            "source": "Shopify Investor Relations",
            "url": "https://investors.shopify.com/news-and-events/press-releases/default.aspx",
        }
    ],
    "RY.TO": [
        {
            "source": "RBC Newsroom",
            "url": "https://www.rbc.com/newsroom/news/index.html",
        }
    ],
    "TD.TO": [
        {
            "source": "TD Newsroom",
            "url": "https://newsroom.td.com/",
        }
    ],
    "PNG.V": [
        {
            "source": "Kraken Robotics Investor News",
            "url": "https://www.krakenrobotics.com/investors/",
        }
    ],
    "HIVE.TO": [
        {
            "source": "HIVE Digital Technologies News",
            "url": "https://www.hivedigitaltechnologies.com/news/",
        }
    ],
}


POSITIVE_TERMS = {
    "beat",
    "beats",
    "record",
    "growth",
    "raises",
    "raised",
    "approval",
    "approved",
    "contract",
    "order",
    "orders",
    "acquisition",
    "partnership",
    "upgrade",
    "guidance",
    "profit",
    "revenue",
    "dividend increase",
}
NEGATIVE_TERMS = {
    "miss",
    "misses",
    "downgrade",
    "loss",
    "lawsuit",
    "investigation",
    "halt",
    "suspension",
    "cuts",
    "cut",
    "warning",
    "impairment",
    "decline",
    "offering",
    "dilution",
    "delisting",
}
IMPORTANT_TERMS = {
    "earnings",
    "financial results",
    "guidance",
    "contract",
    "acquisition",
    "merger",
    "offering",
    "approval",
    "regulatory",
    "dividend",
    "ceo",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _local_iso(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TORONTO_TZ).strftime("%Y-%m-%d %H:%M %Z")


def _clean_text(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _is_valid_news_title(title: str) -> bool:
    clean = _clean_text(title)
    lower = clean.lower()
    if len(clean) < 20 or len(clean) > 220:
        return False
    blocked = [
        "class=",
        "data-component",
        "component-name",
        "font-component",
        "default.aspx",
        "/investors/",
        "http://",
        "https://",
        "{",
        "}",
        "\\",
    ]
    if any(term in lower for term in blocked):
        return False
    alpha_count = sum(1 for char in clean if char.isalpha())
    return alpha_count >= max(10, len(clean) // 3)


def _ticker_base(ticker: str) -> str:
    return str(ticker or "").upper().replace(".TO", "").replace(".V", "").strip()


def _company_tokens(company: str) -> list[str]:
    clean = re.sub(r"\b(inc|ltd|limited|corp|corporation|company|co|class|common|shares|etf)\b", " ", company.lower())
    tokens = [token for token in re.split(r"[^a-z0-9]+", clean) if len(token) >= 3]
    return tokens[:4]


def _strict_match(title: str, body: str, ticker: str, company: str, source_url: str) -> bool:
    haystack = f"{title} {body} {source_url}".lower()
    base = _ticker_base(ticker).lower()
    if base and re.search(rf"(^|[^a-z0-9]){re.escape(base)}($|[^a-z0-9])", haystack):
        return True
    tokens = _company_tokens(company)
    if not tokens:
        return False
    matched = sum(1 for token in tokens if token in haystack)
    return matched >= min(2, len(tokens))


def _parse_date(raw: str) -> datetime | None:
    raw = _clean_text(raw)
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except Exception:
        pass
    formats = [
        "%B %d, %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
        "%d %B %Y",
        "%m/%d/%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=TORONTO_TZ).astimezone(timezone.utc)
        except Exception:
            continue
    return None


def _sentiment(title: str) -> tuple[str, int]:
    lower = title.lower()
    pos = sum(1 for term in POSITIVE_TERMS if term in lower)
    neg = sum(1 for term in NEGATIVE_TERMS if term in lower)
    if pos > neg:
        return "호재", min(80, 20 + pos * 18)
    if neg > pos:
        return "악재", max(-80, -20 - neg * 18)
    return "중립", 0


def _event_key(title: str) -> str:
    normalized = re.sub(r"[^a-z0-9가-힣 ]+", " ", title.lower())
    normalized = re.sub(r"\b(the|a|an|and|to|of|for|in|on|with|announces|reports)\b", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha1(normalized[:140].encode("utf-8")).hexdigest()[:16]


def _make_item(ticker: str, company: str, title: str, source: str, url: str, published_at: datetime | None) -> dict:
    label, score = _sentiment(title)
    lower = title.lower()
    important = abs(score) >= 35 or any(term in lower for term in IMPORTANT_TERMS)
    collected_at = _now()
    return {
        "ticker": ticker,
        "company": company,
        "title": _clean_text(title),
        "source": source,
        "url": url,
        "published_at": published_at.isoformat() if published_at else "",
        "published_at_local": _local_iso(published_at),
        "collected_at": collected_at.isoformat(),
        "collected_at_local": _local_iso(collected_at),
        "sentiment": label,
        "impact_score": score,
        "important": important,
        "event_key": _event_key(title),
    }


def _extract_press_items(html_text: str, base_url: str, source: str, ticker: str, company: str) -> list[dict]:
    html_text = html_text[:350_000]
    candidates = []
    block_pattern = re.compile(
        r"(?P<title>[A-Z0-9][^<\n]{20,180})\s*(?:</[^>]+>\s*){0,4}"
        r"(?P<date>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
        re.I,
    )
    for match in block_pattern.finditer(html_text):
        title = _clean_text(match.group("title"))
        published = _parse_date(match.group("date"))
        if _is_valid_news_title(title) and _strict_match(title, "", ticker, company, base_url):
            candidates.append(_make_item(ticker, company, title, source, base_url, published))

    for match in re.finditer(r"<a[^>]+href=[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<title>.*?)</a>", html_text, re.S | re.I):
        title = _clean_text(match.group("title"))
        if not _is_valid_news_title(title):
            continue
        url = urljoin(base_url, match.group("href"))
        window = html_text[max(0, match.start() - 500): match.end() + 500]
        date_match = re.search(
            r"((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}|\d{4}-\d{2}-\d{2})",
            window,
            re.I,
        )
        published = _parse_date(date_match.group(1)) if date_match else None
        if _strict_match(title, window, ticker, company, url):
            candidates.append(_make_item(ticker, company, title, source, url, published))
    return candidates


def fetch_tmx_news(ticker: str, company: str) -> tuple[list[dict], str]:
    symbol = _ticker_base(ticker)
    url = f"https://money.tmx.com/en/quote/{symbol}/news"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        response.raise_for_status()
    except Exception as exc:
        return [], f"tmx_error:{exc.__class__.__name__}"
    items = _extract_press_items(response.text, url, "TMX Money", ticker, company)
    return items, "tmx_ok" if items else "tmx_no_items"


def check_sedar_status(ticker: str) -> str:
    try:
        response = requests.get("https://www.sedarplus.ca/", timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        if response.url and "validate.perfdrive.com" in response.url:
            return "sedar_blocked"
        return f"sedar_http_{response.status_code}"
    except Exception as exc:
        return f"sedar_error:{exc.__class__.__name__}"


def check_reuters_status(ticker: str) -> str:
    symbol = _ticker_base(ticker)
    suffix = ".V" if ticker.upper().endswith(".V") else ".TO"
    url = f"https://www.reuters.com/markets/companies/{symbol}{suffix}/"
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code in {401, 403}:
            return f"reuters_blocked:{response.status_code}"
        return f"reuters_http_{response.status_code}"
    except Exception as exc:
        return f"reuters_error:{exc.__class__.__name__}"


def fetch_official_news(ticker: str, company: str) -> tuple[list[dict], list[str]]:
    statuses = []
    items = []
    for source in OFFICIAL_NEWS_SOURCES.get(ticker.upper(), []):
        url = source["url"]
        try:
            response = requests.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
        except Exception as exc:
            statuses.append(f"{source['source']}:error:{exc.__class__.__name__}")
            continue
        extracted = _extract_press_items(response.text, url, source["source"], ticker, company)
        statuses.append(f"{source['source']}:{len(extracted)}")
        items.extend(extracted)
    return items, statuses


def _fresh_filter(items: Iterable[dict]) -> tuple[list[dict], str]:
    now = _now()
    parsed = []
    for item in items:
        raw = item.get("published_at")
        if not raw:
            continue
        try:
            published = datetime.fromisoformat(raw)
        except Exception:
            continue
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        age = now - published.astimezone(timezone.utc)
        if timedelta(0) <= age <= timedelta(days=FALLBACK_NEWS_DAYS):
            parsed.append((age, item))
    primary = [item for age, item in parsed if age <= timedelta(hours=PRIMARY_NEWS_HOURS)]
    if primary:
        return _dedupe(primary), "fresh_24h"
    return _dedupe([item for _, item in parsed]), "fresh_7d"


def _dedupe(items: Iterable[dict]) -> list[dict]:
    by_key = {}
    for item in items:
        key = item.get("event_key") or _event_key(item.get("title", ""))
        existing = by_key.get(key)
        if not existing:
            by_key[key] = item
            continue
        if item.get("source", "").startswith(("TMX", "SEDAR")) and not existing.get("source", "").startswith(("TMX", "SEDAR")):
            by_key[key] = item
    values = list(by_key.values())
    values.sort(key=lambda item: item.get("published_at", ""), reverse=True)
    return values[:MAX_ITEMS_PER_TICKER]


def load_canada_news_cache() -> dict:
    try:
        return json.loads(CANADA_NEWS_CACHE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_canada_news_cache(cache: dict) -> None:
    tmp_path = CANADA_NEWS_CACHE_FILE.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(CANADA_NEWS_CACHE_FILE)


def fetch_canada_news_for_symbol(ticker: str, company: str, cache: dict | None = None) -> dict:
    ticker = str(ticker or "").upper()
    cache = cache if cache is not None else load_canada_news_cache()
    all_items, statuses = fetch_official_news(ticker, company)
    tmx_items, tmx_status = fetch_tmx_news(ticker, company)
    all_items.extend(tmx_items)
    statuses.append(tmx_status)
    statuses.append(check_sedar_status(ticker))
    statuses.append(check_reuters_status(ticker))
    items, freshness = _fresh_filter(all_items)
    status = "ok" if items else "unavailable"
    if not items:
        cached = cache.get(ticker, {}).get("items", [])
        items, freshness = _fresh_filter(cached)
        if items:
            status = "cache"
    result = {
        "status": status,
        "freshness": freshness,
        "items": items,
        "source_status": " | ".join(statuses[:5]),
        "collected_at": _now().isoformat(),
        "collected_at_local": _local_iso(_now()),
    }
    if status == "ok":
        cache[ticker] = result
    return result


def apply_canada_news_to_rows(rows: list[dict], max_symbols: int | None = None) -> tuple[list[dict], dict]:
    cache = load_canada_news_cache()
    updated = []
    stats = {"canada_rows": 0, "news_ok": 0, "news_cache": 0, "news_unavailable": 0}
    targets = []
    for index, row in enumerate(rows):
        ticker = str(row.get("ticker", "") or "")
        if is_canada_row(row) or is_canada_ticker(ticker):
            stats["canada_rows"] += 1
            if max_symbols is None or len(targets) < max_symbols:
                targets.append((index, ticker, str(row.get("name", "") or "")))

    news_by_index = {}
    if targets:
        workers = min(8, max(1, len(targets)))
        executor = ThreadPoolExecutor(max_workers=workers)
        try:
            futures = {
                executor.submit(fetch_canada_news_for_symbol, ticker, company, cache): (index, ticker)
                for index, ticker, company in targets
            }
            pending = set(futures)
            try:
                completed_iter = as_completed(futures, timeout=COLLECT_TIMEOUT_SECONDS)
                for future in completed_iter:
                    pending.discard(future)
                    index, ticker = futures[future]
                    try:
                        news_by_index[index] = future.result(timeout=1)
                    except Exception as exc:
                        news_by_index[index] = {
                            "status": "unavailable",
                            "freshness": "",
                            "items": [],
                            "source_status": f"canada_news_error:{exc.__class__.__name__}",
                            "collected_at_local": _local_iso(_now()),
                        }
            except TimeoutError:
                pass
            for future in pending:
                future.cancel()
                index, ticker = futures[future]
                cached = cache.get(ticker, {}).get("items", [])
                items, freshness = _fresh_filter(cached)
                news_by_index[index] = {
                    "status": "cache" if items else "timeout",
                    "freshness": freshness,
                    "items": items,
                    "source_status": f"canada_news_timeout:{COLLECT_TIMEOUT_SECONDS}s",
                    "collected_at_local": _local_iso(_now()),
                }
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    for index, row in enumerate(rows):
        item = dict(row)
        ticker = str(item.get("ticker", "") or "")
        if is_canada_row(item) or is_canada_ticker(ticker):
            news = news_by_index.get(
                index,
                {"status": "skipped", "freshness": "", "items": [], "source_status": "symbol_limit", "collected_at_local": ""},
            )
            items = news.get("items", [])
            status = news.get("status", "unavailable")
            stats[f"news_{status}"] = stats.get(f"news_{status}", 0) + 1
            item["canada_news_status"] = status
            item["canada_news_freshness"] = news.get("freshness", "")
            item["canada_news_count"] = len(items)
            item["canada_news_json"] = json.dumps(items, ensure_ascii=False)
            item["canada_news_collected_at"] = news.get("collected_at_local", "")
            item["canada_news_sources"] = news.get("source_status", "")
            if items:
                titles = [f"{entry.get('title')} ({entry.get('source')}, {entry.get('published_at_local')})" for entry in items[:3]]
                item["headlines"] = " | ".join(titles)
                item["news_one_line"] = f"캐나다 공식/신뢰 뉴스 {len(items)}건 · {items[0].get('sentiment', '중립')} · {items[0].get('published_at_local', '')}"
                item["news"] = items[0].get("title", item.get("news", ""))
                item["news_source"] = items[0].get("source", item.get("news_source", "canada_news"))
            elif status == "cache":
                item["news_one_line"] = "캐나다 뉴스 최신 수집 실패 · 캐시 확인"
            else:
                item["news_one_line"] = "최근 7일 내 공식/신뢰 캐나다 뉴스 없음"
        updated.append(item)
    save_canada_news_cache(cache)
    return updated, stats
