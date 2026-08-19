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


def _format_time(value: object, market: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "DATA_UNAVAILABLE"
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
        if _market_key(market) == "KOREA":
            return parsed.astimezone(ZoneInfo("Asia/Seoul")).strftime("%H:%M KST")
        if _market_key(market) in {"US", "CANADA"}:
            return parsed.astimezone(ZoneInfo("America/New_York")).strftime("%H:%M ET")
    except ValueError:
        pass
    return text


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
    return compact_ai_comparison_message(record)


def research_lab_message(record: dict) -> str:
    return compact_ai_comparison_message(record)


def comparison_started_message(records: list[dict]) -> str:
    if not records:
        return "일일 AI 비교\n\nDATA_UNAVAILABLE"
    conflicts = [record for record in records if _decision_pair(record)[0] != _decision_pair(record)[1]]
    same_count = len(records) - len(conflicts)
    market = _market_key(records[0].get("market"))
    lines = [
        "📊 PRIMARY 테스트 요약",
        "",
        f"{_market_flag(records[0].get('market'))} {market}",
        _format_time(records[0].get("reference_timestamp"), records[0].get("market")),
        "",
        "테스트:",
        str(len(records)),
        "",
        "같은 의견:",
        str(same_count),
        "",
        "다른 의견:",
        str(len(conflicts)),
        "",
        "상태:",
        "진행 중",
    ]
    if conflicts:
        lines.extend(["", "━━━━━━━━━━━━━━", "", "⚔️ 의견 다른 종목", ""])
        for record in conflicts[:12]:
            existing, research = _decision_pair(record)
            lines.append(
                f"{record.get('ticker')} · 기존: {_kr_decision(existing)} · {record.get('existing_ai_score')} / "
                f"Research AI: {_kr_decision(research)} · {record.get('research_score')}"
            )
        if len(conflicts) > 12:
            lines.append(f"... 외 {len(conflicts) - 12}개")
    return "\n".join(lines)


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
