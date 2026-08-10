#!/usr/bin/env python3
"""Shared Canada market guards for scanner CSV pipelines."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Iterable, Mapping


CANADA_MARKET_LABEL = "캐나다"
CANADA_MARKET_ALIASES = {"캐나다", "CANADA", "CA", "TSX", "TSXV", "TSX-V", "TSX Venture", "Toronto"}
CANADA_SUFFIXES = (".TO", ".V")
MIN_CANADA_ROWS_FOR_APP_SYNC = 20


def is_canada_ticker(ticker: str) -> bool:
    clean = str(ticker or "").strip().upper()
    return clean.endswith(CANADA_SUFFIXES)


def is_canada_market(value: str) -> bool:
    clean = str(value or "").strip()
    upper = clean.upper()
    return clean in CANADA_MARKET_ALIASES or upper in {item.upper() for item in CANADA_MARKET_ALIASES}


def is_canada_row(row: Mapping[str, object]) -> bool:
    return is_canada_market(str(row.get("market", ""))) or is_canada_ticker(str(row.get("ticker", "")))


def normalized_market(row: Mapping[str, object]) -> str:
    if is_canada_row(row):
        return CANADA_MARKET_LABEL
    market = str(row.get("market", "") or "").strip()
    ticker = str(row.get("ticker", "") or "").strip().upper()
    if market:
        return market
    if ticker.endswith((".KS", ".KQ")):
        return "국장"
    return "미장"


def market_counts(rows: Iterable[Mapping[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        market = normalized_market(row)
        if not market:
            continue
        counts[market] = counts.get(market, 0) + 1
    return counts


def canada_count(rows: Iterable[Mapping[str, object]]) -> int:
    return sum(1 for row in rows if is_canada_row(row))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def merge_existing_canada_rows(
    new_rows: list[dict[str, str]],
    existing_rows: Iterable[Mapping[str, object]],
) -> list[dict[str, str]]:
    """Keep new rows but restore previous Canada rows when a run drops Canada to zero/sparse."""
    existing_canada = [dict(row) for row in existing_rows if is_canada_row(row)]
    if not existing_canada:
        return new_rows

    merged_by_key: dict[str, dict[str, str]] = {}
    for row in new_rows:
        key = str(row.get("ticker", "") or row.get("name", "")).strip().upper()
        if key:
            merged_by_key[key] = row
    for row in existing_canada:
        key = str(row.get("ticker", "") or row.get("name", "")).strip().upper()
        if key and key not in merged_by_key:
            merged_by_key[key] = row

    merged = list(new_rows)
    seen = {str(row.get("ticker", "") or row.get("name", "")).strip().upper() for row in merged}
    for row in existing_canada:
        key = str(row.get("ticker", "") or row.get("name", "")).strip().upper()
        if key and key not in seen:
            merged.append(row)
            seen.add(key)
    return merged


def serialize_csv_rows(rows: list[dict[str, str]]) -> bytes:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row.keys():
            if key and key not in seen:
                seen.add(key)
                fieldnames.append(key)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")

