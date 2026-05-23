import os
import re


NOISY_PATTERNS = (
    "상세 파일",
    "CSV SAVE",
    "LOG SAVE",
    "PRICE SNAPSHOT CACHE",
    "COMPLETED CANDLE",
    "WORKERS",
    "COOLDOWN",
    "DEDUPE",
    "EXCLUDED NO DATA",
    "TARGETS:",
    "INTERVAL:",
    "MODE:",
    "SESSION:",
    "NETWORK:",
    "AVG SCORE/RISK:",
    "AVG POSITION:",
    "ANALYZED:",
    "SKIPPED:",
    "NO DATA:",
    "SUCCESS RATE:",
)

IMPORTANT_KEYWORDS = (
    "TOP",
    "추천",
    "강추",
    "매수",
    "관심",
    "관망",
    "손절",
    "익절",
    "위험",
    "리스크",
    "악재",
    "호재",
    "뉴스",
    "거래량",
    "수급",
    "섹터",
    "자금",
    "급등",
    "급락",
    "돌파",
    "하락",
    "상승",
    "현재가",
    "배당",
    "오류",
    "실패",
    "완료",
    "시장",
    "WATCH",
    "SCORE",
    "ACTIONABLE",
    "DEFENSIVE",
)


def _clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line).strip()
    replacements = {
        "📊 ANALYSIS COMPLETE": "분석 완료",
        "📌 TOP ACTIONABLE": "오늘 볼 종목",
        "🛡 TOP DEFENSIVE": "방어/주의 종목",
        "STRONG BUY": "강한 매수",
        "ACTIONABLE": "실행 후보",
        "DEFENSIVE": "방어 후보",
        "MARKET": "시장",
        "SESSION": "세션",
        "ALERT SENT": "알림",
        "PORTFOLIO PICKS": "포트폴리오 후보",
    }
    for src, dst in replacements.items():
        line = line.replace(src, dst)
    return line


def compact_telegram_message(text: str, *, max_lines: int = 14, max_chars: int = 1200) -> str:
    """Make stock alerts short enough to read quickly on Telegram."""
    if os.getenv("TELEGRAM_VERBOSE", "").lower() in {"1", "true", "yes"}:
        return text

    raw_lines = [_clean_line(line) for line in str(text).splitlines()]
    lines = [line for line in raw_lines if line]
    if not lines:
        return str(text).strip()

    filtered = [
        line
        for line in lines
        if not any(pattern in line for pattern in NOISY_PATTERNS)
    ]
    if not filtered:
        filtered = lines

    already_short = len("\n".join(filtered)) <= max_chars and len(filtered) <= max_lines
    if already_short:
        return "\n".join(filtered)

    title = filtered[0]
    picked: list[str] = [title]
    seen = {title}

    def add(line: str) -> None:
        if line not in seen and len(picked) < max_lines:
            picked.append(line)
            seen.add(line)

    for line in filtered[1:]:
        if any(keyword in line for keyword in IMPORTANT_KEYWORDS):
            add(line)

    item_pattern = re.compile(r"^(\d+[\).]|[-•]|#|[A-Z0-9]{1,8}\s)")
    for line in filtered[1:]:
        if item_pattern.search(line):
            add(line)

    for line in filtered[1:]:
        add(line)

    compacted = "\n".join(picked)
    if len(compacted) > max_chars:
        compacted = compacted[: max_chars - 24].rstrip() + "\n자세한 내용은 앱 확인"
    elif len(filtered) > len(picked):
        compacted += "\n자세한 내용은 앱/CSV 확인"
    return compacted
