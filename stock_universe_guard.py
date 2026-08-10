#!/usr/bin/env python3

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from canada_market_guard import market_counts


def read_csv_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return [dict(row) for row in csv.DictReader(handle)]
    except Exception:
        return []


def ticker_set(rows: Iterable[dict]) -> set[str]:
    tickers = set()
    for row in rows:
        ticker = str(row.get("ticker", "") or "").strip().upper()
        if ticker:
            tickers.add(ticker)
    return tickers


def validate_no_stock_loss(new_rows: Iterable[dict], previous_rows: Iterable[dict], context: str) -> tuple[bool, str]:
    new_rows = list(new_rows)
    previous_rows = list(previous_rows)
    previous_tickers = ticker_set(previous_rows)
    new_tickers = ticker_set(new_rows)
    if not previous_tickers:
        return True, f"{context}: 기준 종목 없음 · 새 종목 {len(new_tickers)}개"

    missing = sorted(previous_tickers - new_tickers)
    previous_counts = market_counts(previous_rows)
    new_counts = market_counts(new_rows)
    if missing:
        preview = ", ".join(missing[:12])
        suffix = "" if len(missing) <= 12 else f" 외 {len(missing) - 12}개"
        return (
            False,
            f"{context}: 종목 삭제 감지 · 이전 {len(previous_tickers)}개 -> 새 {len(new_tickers)}개 · "
            f"누락 {len(missing)}개 [{preview}{suffix}] · 이전시장={previous_counts} 새시장={new_counts}",
        )

    if len(new_tickers) < len(previous_tickers):
        return (
            False,
            f"{context}: 종목 수 감소 감지 · 이전 {len(previous_tickers)}개 -> 새 {len(new_tickers)}개 · "
            f"이전시장={previous_counts} 새시장={new_counts}",
        )

    return (
        True,
        f"{context}: 종목 보존 확인 · 이전 {len(previous_tickers)}개 -> 새 {len(new_tickers)}개 · "
        f"이전시장={previous_counts} 새시장={new_counts}",
    )
