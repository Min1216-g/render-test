from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .models import ResearchResult

MARKET_ORDER = (
    ("KOREA", "🇰🇷 국내장", {"국장", "한국", "KOREA"}),
    ("US", "🇺🇸 미국장", {"미장", "US", "USA", "미국"}),
    ("CANADA", "🇨🇦 캐나다장", {"캐나다", "CANADA", "TSX", "TSXV"}),
)


def _as_record_dict(record: object) -> dict:
    if isinstance(record, dict):
        return record
    if is_dataclass(record):
        return asdict(record)
    to_dict = getattr(record, "to_dict", None)
    if callable(to_dict):
        data = to_dict()
        if isinstance(data, dict):
            return data
    return {}


def _normalize_records(records: list[dict] | list[object]) -> list[dict]:
    return [_as_record_dict(record) for record in records]


def _money(value: float | None) -> str:
    if value is None:
        return "DATA_UNAVAILABLE"
    return f"{value:,.2f}"


def _market_flag(market: str | None) -> str:
    text = str(market or "")
    if text in {"국장", "한국", "KOREA"}:
        return "🇰🇷"
    if text in {"미장", "US", "USA", "미국"}:
        return "🇺🇸"
    if text in {"캐나다", "CANADA", "TSX", "TSXV"}:
        return "🇨🇦"
    return "🌎"


def _market_key(market: str | None) -> str:
    text = str(market or "")
    if text in {"국장", "한국", "KOREA"}:
        return "KOREA"
    if text in {"미장", "US", "USA", "미국"}:
        return "US"
    if text in {"캐나다", "CANADA", "TSX", "TSXV"}:
        return "CANADA"
    return text or "MARKET"


def _format_price(value: object, market: str | None) -> str:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "DATA_UNAVAILABLE"
    if _market_key(market) == "KOREA":
        return f"₩{price:,.0f}"
    if _market_key(market) == "CANADA":
        return f"C${price:,.2f}"
    return f"${price:,.2f}"


def _parse_time(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    timezone_suffixes = {
        "PDT": "-07:00",
        "PST": "-08:00",
        "EDT": "-04:00",
        "EST": "-05:00",
        "KST": "+09:00",
    }
    parts = text.rsplit(" ", 1)
    if len(parts) == 2 and parts[1] in timezone_suffixes:
        text = f"{parts[0]}{timezone_suffixes[parts[1]]}"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        return parsed
    except ValueError:
        return None


def _format_time(value: object, market: str | None) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "데이터 없음"
    try:
        if _market_key(market) == "KOREA":
            return parsed.astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M KST")
        if _market_key(market) in {"US", "CANADA"}:
            return parsed.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M ET")
    except ValueError:
        pass
    return parsed.isoformat(timespec="minutes")


def _decision_pair(record: dict) -> tuple[str, str]:
    return str(record.get("existing_ai_decision") or "N/A").upper(), str(record.get("research_decision") or "N/A").upper()


def _kr_decision(value: object) -> str:
    mapping = {"BUY CANDIDATE": "매수 후보", "WATCH": "관찰", "WAIT": "대기", "AVOID": "회피", "N/A": "정보 없음"}
    return mapping.get(str(value or "N/A").upper(), str(value or "정보 없음"))


def _kr_risk(value: object) -> str:
    mapping = {"LOW": "낮음", "MEDIUM": "보통", "HIGH": "높음"}
    return mapping.get(str(value or "").upper(), str(value or "정보 없음"))


def _kr_data_status(record: dict) -> str:
    quality = record.get("data_quality")
    if isinstance(quality, dict):
        status = str(quality.get("status") or "")
        issues = quality.get("issues") or []
        if status == "VALID":
            return "정상"
        if issues:
            return f"확인 필요 ({', '.join(map(str, issues[:2]))})"
        return status or "확인 필요"
    if record.get("reference_price") is not None and record.get("reference_timestamp"):
        return "정상"
    return "DATA_UNAVAILABLE"


def _kr_news_status(record: dict) -> str:
    quality = record.get("news_quality")
    if isinstance(quality, dict):
        status = str(quality.get("status") or "")
    else:
        sentiment = record.get("sentiment_analysis") if isinstance(record.get("sentiment_analysis"), dict) else {}
        reason = str(sentiment.get("reason") or "")
        status = str(sentiment.get("status") or reason or "")
        if status == "NEWS_UNAVAILABLE" and reason in {"NEWS_MISSING", "NEWS_STALE"}:
            status = reason
    mapping = {
        "NEWS_AVAILABLE": "최신 뉴스 확인",
        "NEWS_MISSING": "최근 뉴스 없음",
        "NEWS_STALE": "오래된 뉴스 제외",
        "NEWS_UNAVAILABLE": "뉴스 없음",
    }
    return mapping.get(status, status or "뉴스 상태 확인 필요")


def _market_records(records: list[dict] | list[object], aliases: set[str]) -> list[dict]:
    return [record for record in _normalize_records(records) if str(record.get("market") or "") in aliases]


def _record_has_current_data(record: dict, market_key: str, now: datetime | None = None) -> bool:
    quality = record.get("data_quality")
    if isinstance(quality, dict):
        if quality.get("status") != "VALID":
            return False
        timestamp = quality.get("reference_timestamp") or record.get("reference_data_timestamp") or record.get("reference_timestamp")
    else:
        if record.get("reference_price") is None or not record.get("reference_timestamp"):
            return False
        timestamp = record.get("reference_data_timestamp") or record.get("reference_timestamp")
    parsed = _parse_time(timestamp)
    if parsed is None:
        return False
    current = (now or datetime.now(ZoneInfo("UTC"))).astimezone(ZoneInfo("UTC"))
    age_minutes = (current - parsed.astimezone(ZoneInfo("UTC"))).total_seconds() / 60
    return 0 <= age_minutes <= 180


def _display_name(record: dict | None) -> str:
    if not record:
        return "현재 유효한 강세 후보 없음"
    name = str(record.get("name") or "").strip()
    ticker = str(record.get("ticker") or "").strip()
    if name and ticker and name.upper() != ticker.upper():
        return f"{name} ({ticker})"
    return name or ticker or "현재 유효한 강세 후보 없음"


def _ticker_key(record: dict) -> str:
    return str(record.get("ticker") or "").strip().upper()


def _scanner_picks(records: list[dict], market_key: str, now: datetime | None = None, limit: int = 5) -> list[dict]:
    bullish = {"BUY CANDIDATE", "WATCH"}
    candidates = [
        record
        for record in records
        if _record_has_current_data(record, market_key, now)
        and str(record.get("existing_ai_decision") or "").upper() in bullish
    ]
    return sorted(
        candidates,
        key=lambda record: (
            float(record.get("existing_ai_score") or 0),
            float(record.get("reference_change_pct") or record.get("change_pct") or 0),
            str(record.get("ticker") or ""),
        ),
        reverse=True,
    )[:limit]


def _research_picks(records: list[dict], market_key: str, now: datetime | None = None, limit: int = 5) -> list[dict]:
    bullish = {"BUY CANDIDATE", "WATCH"}
    valid_records = [
        record
        for record in records
        if _record_has_current_data(record, market_key, now)
    ]
    candidates = [
        record
        for record in valid_records
        if str(record.get("research_decision") or "").upper() in bullish
    ]
    if not candidates:
        candidates = [
            record
            for record in valid_records
            if float(record.get("research_score") or 0) >= 45
        ]
    return sorted(
        candidates,
        key=lambda record: (
            float(record.get("research_score") or 0),
            float(record.get("reference_change_pct") or record.get("change_pct") or 0),
            str(record.get("ticker") or ""),
        ),
        reverse=True,
    )[:limit]


def _rank_map(records: list[dict]) -> dict[str, int]:
    return {_ticker_key(record): index for index, record in enumerate(records, start=1) if _ticker_key(record)}


def _record_map(records: list[dict]) -> dict[str, dict]:
    return {_ticker_key(record): record for record in records if _ticker_key(record)}


def _candidate_lines(records: list[dict]) -> list[str]:
    if not records:
        return ["현재 유효한 강세 후보 없음"]
    return [f"{index}. {_display_name(record)}" for index, record in enumerate(records, start=1)]


def _comparison_lines(scanner: list[dict], research: list[dict]) -> list[str]:
    scanner_ranks = _rank_map(scanner)
    research_ranks = _rank_map(research)
    scanner_by_ticker = _record_map(scanner)
    research_by_ticker = _record_map(research)
    scanner_tickers = set(scanner_ranks)
    research_tickers = set(research_ranks)

    both = sorted(
        scanner_tickers & research_tickers,
        key=lambda ticker: ((scanner_ranks[ticker] + research_ranks[ticker]) / 2, scanner_ranks[ticker], research_ranks[ticker]),
    )
    scanner_only = sorted(scanner_tickers - research_tickers, key=lambda ticker: scanner_ranks[ticker])
    research_only = sorted(research_tickers - scanner_tickers, key=lambda ticker: research_ranks[ticker])

    lines = ["[비교 결과]", "🏆 BOTH"]
    if both:
        for index, ticker in enumerate(both, start=1):
            record = scanner_by_ticker.get(ticker) or research_by_ticker[ticker]
            avg_rank = (scanner_ranks[ticker] + research_ranks[ticker]) / 2
            lines.append(
                f"{index}. {_display_name(record)} "
                f"(scanner {scanner_ranks[ticker]}위 / research {research_ranks[ticker]}위 / 평균 {avg_rank:g}위)"
            )
    else:
        lines.append("현재 유효한 공통 후보 없음")

    lines.extend(["", "🔵 SCANNER ONLY"])
    if scanner_only:
        for index, ticker in enumerate(scanner_only, start=1):
            lines.append(f"{index}. {_display_name(scanner_by_ticker[ticker])} (scanner {scanner_ranks[ticker]}위)")
    else:
        lines.append("현재 유효한 단독 후보 없음")

    lines.extend(["", "🟣 RESEARCH ONLY"])
    if research_only:
        for index, ticker in enumerate(research_only, start=1):
            lines.append(f"{index}. {_display_name(research_by_ticker[ticker])} (research {research_ranks[ticker]}위)")
    else:
        lines.append("현재 유효한 단독 후보 없음")
    return lines


def _market_comparison_block(label: str, records: list[dict], *, now: datetime | None = None, limit: int = 5) -> list[str]:
    market_key = next((key for key, market_label, _ in MARKET_ORDER if market_label == label), "")
    scanner = _scanner_picks(records, market_key, now, limit)
    research = _research_picks(records, market_key, now, limit)
    lines = [
        "━━━━━━━━━━━━━━━━━━",
        label,
        "━━━━━━━━━━━━━━━━━━",
        "",
        "[scanner.py]",
        *_candidate_lines(scanner),
        "",
        "[Research AI]",
        *_candidate_lines(research),
        "",
        *_comparison_lines(scanner, research),
    ]
    return lines


def _market_block(label: str, records: list[dict], picker, *, now: datetime | None = None, limit: int = 5) -> list[str]:
    market_key = next((key for key, market_label, _ in MARKET_ORDER if market_label == label), "")
    lines = [label, ""]
    if not any(_record_has_current_data(record, market_key, now) for record in records):
        return lines + ["현재 유효한 강세 후보 없음"]
    picked = picker(records, market_key, now, limit)
    if not picked:
        return lines + ["현재 유효한 강세 후보 없음"]
    return lines + [f"{index}. {_display_name(record)}" for index, record in enumerate(picked, start=1)]


def scanner_prediction_message(records: list[dict] | list[object], *, now: datetime | None = None) -> str:
    records = _normalize_records(records)
    lines = [
        "[scanner.py]",
        "현재 기준 강세로 예측되는 종목",
        "",
    ]
    grouped = [(key, label, _market_records(records, aliases)) for key, label, aliases in MARKET_ORDER]
    for _, label, market_records in grouped:
        lines.extend(_market_block(label, market_records, _scanner_picks, now=now))
        lines.append("")
    if lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def research_prediction_message(records: list[dict] | list[object], *, now: datetime | None = None) -> str:
    records = _normalize_records(records)
    lines = [
        "[research]",
        "현재 기준 강세로 예측되는 종목",
        "",
    ]
    grouped = [(key, label, _market_records(records, aliases)) for key, label, aliases in MARKET_ORDER]
    for _, label, market_records in grouped:
        lines.extend(_market_block(label, market_records, _research_picks, now=now))
        lines.append("")
    if lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def prediction_summary_message(records: list[dict] | list[object], *, now: datetime | None = None) -> str:
    records = _normalize_records(records)
    lines = [
        "📡 Research Lab AI 비교 분석",
        "기준: 최신 market_scanner_results.csv",
        "※ Full Scan 미실행",
        "",
    ]
    for _, label, aliases in MARKET_ORDER:
        lines.extend(_market_comparison_block(label, _market_records(records, aliases), now=now))
        lines.append("")
    if lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines)


def compact_ai_comparison_message(record: dict) -> str:
    market = str(record.get("market") or "")
    existing, research = _decision_pair(record)
    different = existing != research
    title = "⚔️ AI 의견 충돌" if different else "📊 AI 비교"
    return "\n".join(
        [
            title,
            "",
            f"{_market_flag(market)} {record.get('ticker')}",
            str(record.get("name") or ""),
            "",
            f"현재가: {_format_price(record.get('reference_price'), market)}",
            f"기준 시각: {_format_time(record.get('reference_timestamp'), market)}",
            f"데이터 상태: {_kr_data_status(record)}",
            f"뉴스 상태: {_kr_news_status(record)}",
            "",
            "기존 AI",
            f"점수: {record.get('existing_ai_score')}",
            f"판단: {_kr_decision(existing)}",
            f"위험도: {_kr_risk(record.get('existing_risk'))}",
            "",
            "Research AI",
            f"점수: {record.get('research_score')}",
            f"판단: {_kr_decision(research)}",
            f"위험도: {_kr_risk(record.get('research_risk'))}",
            "",
            f"의견: {'다름' if different else '같음'}",
            "결과: 대기 중",
        ]
    )


def compact_result(result: ResearchResult) -> str:
    comparison = result.reasoning.get("comparison", {})
    diff = comparison.get("difference")
    diff_text = "N/A" if diff is None else f"{diff:+d}"
    alignment = comparison.get("alignment", "UNKNOWN")
    return "\n".join(
        [
            f"{result.ticker} RESEARCH",
            "",
            f"Score: {result.research_score}",
            f"Decision: {result.research_decision}",
            "",
            f"Technical: {result.technical_score if result.technical_score is not None else 'DATA_UNAVAILABLE'}",
            f"Fundamental: {result.fundamental_score if result.fundamental_score is not None else 'DATA_UNAVAILABLE'}",
            f"News: {result.sentiment_score if result.sentiment_score is not None else 'NO_RECENT_NEWS'}",
            "",
            f"Bull: {result.bull_score}",
            f"Bear: {result.bear_score}",
            f"Risk: {result.risk_level}",
            f"Continuation Potential: {result.continuation_potential}",
            "",
            f"Existing AI: {result.existing_ai_score if result.existing_ai_score is not None else 'DATA_UNAVAILABLE'}",
            f"Difference: {diff_text}",
            f"AI + Research {alignment}",
        ]
    )


def detail_result(result: ResearchResult) -> str:
    lines = [
        f"{result.ticker} RESEARCH DETAIL",
        f"Name: {result.name}",
        f"Market: {result.market}",
        f"Current Price: {_money(result.current_price)}",
        f"Data Timestamp: {result.data_timestamp or 'DATA_UNAVAILABLE'}",
        "",
        compact_result(result),
        "",
        f"Already Risen: {'YES' if result.already_risen else 'NO'}",
        f"Momentum: {result.momentum}",
        f"Overheat Risk: {result.overheat_risk}",
        "",
        "Bull Case:",
    ]
    for reason in result.reasoning.get("bull_case", {}).get("reasons", []):
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("Bear Case:")
    for reason in result.reasoning.get("bear_case", {}).get("reasons", []):
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("Analyst Notes:")
    for key in ("technical", "fundamental", "sentiment"):
        note = result.reasoning.get(key, {})
        lines.append(f"- {key}: {note.get('direction')} · {note.get('reason')}")
    return "\n".join(lines)


def compare_result(result: ResearchResult) -> str:
    comparison = result.reasoning.get("comparison", {})
    diff = comparison.get("difference")
    return "\n".join(
        [
            f"{result.ticker} RESEARCH COMPARISON",
            "",
            f"Current Price: {_money(result.current_price)}",
            "",
            "Existing AI",
            f"Score: {result.existing_ai_score if result.existing_ai_score is not None else 'DATA_UNAVAILABLE'}",
            f"Decision: {result.existing_ai_decision}",
            "",
            "Research Engine",
            f"Score: {result.research_score}",
            f"Decision: {result.research_decision}",
            "",
            f"Technical: {result.reasoning.get('technical', {}).get('direction')}",
            f"Fundamental: {result.reasoning.get('fundamental', {}).get('direction')}",
            f"News: {result.reasoning.get('sentiment', {}).get('direction')}",
            "",
            f"Bull Case: {result.bull_score}",
            f"Bear Case: {result.bear_score}",
            f"Risk: {result.risk_level}",
            f"Difference: {'N/A' if diff is None else f'{diff:+d}'}",
            "",
            comparison.get("alignment", "UNKNOWN"),
        ]
    )


def hot_results(results: list[ResearchResult]) -> str:
    lines = ["HOT RESEARCH", ""]
    for idx, result in enumerate(results, start=1):
        lines.append(
            f"{idx}. {result.ticker} · {result.research_decision} · Research {result.research_score} · Existing {result.existing_ai_score if result.existing_ai_score is not None else 'N/A'} · Risk {result.risk_level}"
        )
    return "\n".join(lines)


def history_message(records: list[dict]) -> str:
    if not records:
        return "RESEARCH HISTORY\n\nDATA_UNAVAILABLE"
    lines = ["RESEARCH HISTORY", ""]
    for record in reversed(records):
        returns = record.get("future_returns") or {}
        lines.append(
            f"{record.get('ticker')} · {record.get('research_decision')} · score {record.get('research_score')} · price {record.get('entry_reference')} · 5D {returns.get('5D') if returns.get('5D') is not None else 'pending'}"
        )
        lines.append(f"time: {record.get('timestamp')}")
    return "\n".join(lines)


def stats_message(stats: dict) -> str:
    if stats.get("status") != "OK":
        return "\n".join(
            [
                "RESEARCH PERFORMANCE",
                "",
                "DATA_UNAVAILABLE",
                f"Total Signals: {stats.get('total_signals', 0)}",
                f"Completed 5D: {stats.get('completed_5d', 0)}",
            ]
        )
    return "\n".join(
        [
            "RESEARCH PERFORMANCE",
            "",
            f"Total Signals: {stats.get('total_signals')}",
            f"Completed 5D: {stats.get('completed_5d')}",
            f"BUY CANDIDATE Win Rate: {stats.get('buy_candidate_win_rate')}%",
            f"Average 5D Return: {stats.get('average_5d_return')}%",
        ]
    )


def existing_scanner_message(record: dict) -> str:
    return scanner_prediction_message([record])


def research_lab_message(record: dict) -> str:
    return research_prediction_message([record])


def comparison_started_message(records: list[dict]) -> str:
    if not records:
        return prediction_summary_message([])
    return prediction_summary_message(records)


def comparison_report_message(report: dict) -> str:
    if report.get("status") != "OK":
        return "\n".join(
            [
                "일일 AI 비교",
                "",
                "DATA_UNAVAILABLE",
                f"전체 표본: {report.get('total_samples', 0)}",
                f"5일 평가 완료: {report.get('completed_5d', 0)}",
                str(report.get("message", "")),
            ]
        )
    metrics = report.get("metrics") or {}
    lines = [
        "일일 AI 비교",
        "",
        f"테스트: {report.get('total_samples')}",
        f"평가 완료: {report.get('evaluated_samples')}",
        f"5일 평가 완료: {report.get('completed_5d')}",
        "",
    ]
    for window in ("1H", "CLOSE", "1D", "3D", "5D"):
        item = metrics.get(window)
        if not item:
            continue
        lines.extend(
            [
                f"{window} 결과",
                f"기존 AI 정확도: {item.get('existing_accuracy')}%",
                f"Research AI 정확도: {item.get('research_accuracy')}%",
                f"평균 수익률: {item.get('average_return')}%",
                "",
            ]
        )
    lines.append("차이가 큰 종목:")
    for item in (report.get("top_differences") or [])[:5]:
        lines.append(
            f"- {item.get('ticker')}: 기존 {item.get('existing_score')} vs Research AI {item.get('research_score')}"
        )
    return "\n".join(lines)
