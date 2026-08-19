from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from .models import ResearchResult


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
    return "🌎"


def _market_key(market: str | None) -> str:
    text = str(market or "")
    if text in {"국장", "한국", "KOREA"}:
        return "KOREA"
    if text in {"미장", "US", "USA", "미국"}:
        return "US"
    return text or "MARKET"


def _format_price(value: object, market: str | None) -> str:
    try:
        price = float(value)
    except (TypeError, ValueError):
        return "DATA_UNAVAILABLE"
    if _market_key(market) == "KOREA":
        return f"₩{price:,.0f}"
    return f"${price:,.2f}"


def _format_time(value: object, market: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "DATA_UNAVAILABLE"
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("UTC"))
        if _market_key(market) == "KOREA":
            return parsed.astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M KST")
        if _market_key(market) == "US":
            return parsed.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M ET")
    except ValueError:
        pass
    return text


def _decision_pair(record: dict) -> tuple[str, str]:
    return str(record.get("existing_ai_decision") or "N/A").upper(), str(record.get("research_decision") or "N/A").upper()


def compact_ai_comparison_message(record: dict) -> str:
    market = str(record.get("market") or "")
    existing, research = _decision_pair(record)
    different = existing != research
    title = "⚔️ AI CONFLICT" if different else "📊 AI COMPARISON"
    return "\n".join(
        [
            title,
            "",
            f"{_market_flag(market)} {record.get('ticker')}",
            str(record.get("name") or ""),
            "",
            "Reference:",
            _format_price(record.get("reference_price"), market),
            _format_time(record.get("reference_timestamp"), market),
            "",
            "EXISTING",
            f"{existing} · {record.get('existing_ai_score')}",
            f"Risk: {record.get('existing_risk')}",
            "",
            "RESEARCH",
            f"{research} · {record.get('research_score')}",
            f"Risk: {record.get('research_risk')}",
            "",
            "Decision:",
            "DIFFERENT" if different else "SAME",
            "",
            "Result:",
            "PENDING",
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
    return compact_ai_comparison_message(record)


def research_lab_message(record: dict) -> str:
    return compact_ai_comparison_message(record)


def comparison_started_message(records: list[dict]) -> str:
    if not records:
        return "DAILY AI COMPARISON\n\nDATA_UNAVAILABLE"
    conflicts = [record for record in records if _decision_pair(record)[0] != _decision_pair(record)[1]]
    same_count = len(records) - len(conflicts)
    market = _market_key(records[0].get("market"))
    lines = [
        "📊 PRIMARY TEST SUMMARY",
        "",
        f"{_market_flag(records[0].get('market'))} {market}",
        _format_time(records[0].get("reference_timestamp"), records[0].get("market")),
        "",
        "Tested:",
        str(len(records)),
        "",
        "Same Decision:",
        str(same_count),
        "",
        "Conflict:",
        str(len(conflicts)),
        "",
        "Status:",
        "RUNNING",
    ]
    if conflicts:
        lines.extend(["", "━━━━━━━━━━━━━━", "", "⚔️ CONFLICT CASES", ""])
        for record in conflicts[:12]:
            existing, research = _decision_pair(record)
            lines.append(
                f"{record.get('ticker')} · Existing: {existing} · {record.get('existing_ai_score')} / "
                f"Research: {research} · {record.get('research_score')}"
            )
        if len(conflicts) > 12:
            lines.append(f"... +{len(conflicts) - 12} more")
    return "\n".join(lines)


def comparison_report_message(report: dict) -> str:
    if report.get("status") != "OK":
        return "\n".join(
            [
                "DAILY AI COMPARISON",
                "",
                "DATA_UNAVAILABLE",
                f"Total samples: {report.get('total_samples', 0)}",
                f"Completed 5D: {report.get('completed_5d', 0)}",
                str(report.get("message", "")),
            ]
        )
    metrics = report.get("metrics") or {}
    lines = [
        "DAILY AI COMPARISON",
        "",
        f"Tested: {report.get('total_samples')}",
        f"Evaluated: {report.get('evaluated_samples')}",
        f"Completed 5D: {report.get('completed_5d')}",
        "",
    ]
    for window in ("1H", "CLOSE", "1D", "3D", "5D"):
        item = metrics.get(window)
        if not item:
            continue
        lines.extend(
            [
                f"{window} Result",
                f"Existing Accuracy: {item.get('existing_accuracy')}%",
                f"Research Accuracy: {item.get('research_accuracy')}%",
                f"Average Return: {item.get('average_return')}%",
                "",
            ]
        )
    lines.append("Top Differences:")
    for item in (report.get("top_differences") or [])[:5]:
        lines.append(
            f"- {item.get('ticker')}: Existing {item.get('existing_score')} vs Research {item.get('research_score')}"
        )
    return "\n".join(lines)
