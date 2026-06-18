#!/usr/bin/env python3

import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import security_check
from ops_guard import enforce_runtime_security
from news_impact_engine import analyze_news_impact


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env.news_pulse"
ANALYSIS_FILE = BASE_DIR / "analysis_results.csv"
MARKET_SCANNER_FILE = BASE_DIR / "market_scanner_results.csv"
RESULTS_FILE = BASE_DIR / "news_pulse_results.csv"
STATE_FILE = BASE_DIR / "news_pulse_state.json"
LOG_FILE = BASE_DIR / "news_pulse_log.csv"
SEOUL_TZ = ZoneInfo("Asia/Seoul")
HTTP = requests.Session()
enforce_runtime_security(BASE_DIR, env_files=[ENV_FILE])


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file(ENV_FILE)

BOT_TOKEN = os.getenv("NEWS_PULSE_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("NEWS_PULSE_CHAT_ID", "").strip()
NEWS_PRIMARY_WINDOW_HOURS = int(os.getenv("NEWS_PULSE_PRIMARY_WINDOW_HOURS", str(7 * 24)))
NEWS_WINDOW_HOURS = int(os.getenv("NEWS_PULSE_WINDOW_HOURS", str(30 * 24)))
NEWS_FETCH_LIMIT = int(os.getenv("NEWS_PULSE_FETCH_LIMIT", "8"))
NEWS_QUERY_LIMIT = int(os.getenv("NEWS_PULSE_QUERY_LIMIT", "25"))
NEWS_ALERT_TOP_N = int(os.getenv("NEWS_PULSE_ALERT_TOP_N", "7"))
NEWS_LOOP_MINUTES = int(os.getenv("NEWS_PULSE_LOOP_MINUTES", "20"))
NEWS_RUN_ONCE = os.getenv("NEWS_PULSE_RUN_ONCE", "false").lower() == "true"
NEWS_SEND_TELEGRAM = os.getenv("NEWS_PULSE_SEND_TELEGRAM", "true").lower() == "true"
NEWS_REQUIRED_MENTIONS = int(os.getenv("NEWS_PULSE_REQUIRED_MENTIONS", "1"))
NEWS_SECURITY_CHECK = os.getenv("NEWS_PULSE_SECURITY_CHECK", "true").lower() == "true"
NEWS_SECURITY_AUTO_FIX = os.getenv("NEWS_PULSE_SECURITY_AUTO_FIX", "true").lower() == "true"
NEWS_KEYWORDS = [
    token.strip()
    for token in os.getenv(
        "NEWS_PULSE_KEYWORDS",
        "투자,계약,수주,협력,공급,승인,인수,합병,출시,실적,증가,유상증자,증자,시설투자,설비투자,제3자배정,전환사채,악재,급락,폭발,발사 실패,발사 지연,블루오리진,Blue Origin,rocket explosion,launch failure,tumble,plunge",
    ).split(",")
    if token.strip()
]
POSITIVE_NEWS_KEYWORDS = [
    token.strip()
    for token in os.getenv(
        "NEWS_PULSE_POSITIVE_KEYWORDS",
        "수주,계약,협력,공급,승인,인수,합병,출시,실적,흑자,증가,성장,확대,돌파,호실적,상승,시설투자,설비투자,증설,제3자배정,전략적 투자",
    ).split(",")
    if token.strip()
]
NEGATIVE_NEWS_KEYWORDS = [
    token.strip()
    for token in os.getenv(
        "NEWS_PULSE_NEGATIVE_KEYWORDS",
        "하락,급락,유상증자,전환사채,희석,운영자금,채무상환,차입금,주주배정,적자,소송,매각,처분,감소,지분율,주식등의 수,순매도,거래정지,중단,부진,악재,리스크,경고,정지,쇼크,어닝쇼크,어닝 쇼크,어닝콜 쇼크,실적쇼크,실적 쇼크,컨센서스 하회,전망 하향,목표가 하향,하향,낮아,가능성 낮아,급감,못 미치,시장전망,철근,누락,부실시공,붕괴,하자,안전사고,영업정지,제재,벌점,국토부,폭발,실패,발사 실패,로켓 폭발,발사 지연,궤도 실패,launch failure,rocket explosion,explosion,launch delay,wrong orbit,downgrade,tumble,plunge,crash,falls,fall,stocks fall,blows up,sinks,sank,lower",
    ).split(",")
    if token.strip()
]

SECTOR_NEWS_QUERIES = {
    "건설": "건설 관련주 철근 누락 부실시공 하자 안전사고 국토부 제재",
    "2차전지": "2차전지 관련주 화재 리콜 수요 둔화 적자 공급과잉",
    "반도체": "반도체 관련주 어닝콜 쇼크 어닝쇼크 어닝 쇼크 실적쇼크 컨센서스 하회 수출통제 재고 부진 규제 실적",
    "전력": "전력 관련주 정책 지연 사고 제재 원가 수주",
    "원전": "원전 관련주 정책 지연 사고 규제 수주 취소",
    "의료/제약": "의료 제약 관련주 임상 실패 허가 지연 부작용 소송",
    "조선/해운": "조선 해운 관련주 인도 지연 운임 하락 사고 원가",
    "증권/금융": "증권 금융 관련주 순매도 부동산PF 충당금 손실",
    "우주항공": "AST SpaceMobile Rocket Lab Blue Origin rocket explosion space stocks",
}

ALWAYS_WATCH_NEWS_QUERIES = {
    "TIGER 미국우주테크": "AST SpaceMobile Rocket Lab Blue Origin rocket explosion space stocks",
    "우주항공 리스크": "Blue Origin SpaceX Rocket Lab AST SpaceMobile launch failure delay explosion space stocks",
    "건설 중대악재": "현대건설 대우건설 GS건설 철근 누락 부실시공 국토부 제재",
    "반도체 실적쇼크": "한미반도체 삼성전자 SK하이닉스 어닝쇼크 실적쇼크 컨센서스 하회",
    "전력 원전 리스크": "전력 원전 관련주 정책 지연 사고 제재 수주 취소",
}

POSITIVE_NEWS_WEIGHTS = {
    "수주": 8,
    "계약": 7,
    "공급": 7,
    "승인": 7,
    "흑자": 8,
    "호실적": 7,
    "실적": 5,
    "투자": 5,
    "시설투자": 8,
    "설비투자": 8,
    "증설": 6,
    "제3자배정": 5,
    "전략적 투자": 6,
    "협력": 5,
    "확대": 4,
    "출시": 4,
    "돌파": 3,
    "상승": 2,
}

NEGATIVE_NEWS_WEIGHTS = {
    "유상증자": 6,
    "전환사채": 9,
    "희석": 9,
    "운영자금": 7,
    "채무상환": 8,
    "차입금": 6,
    "주주배정": 7,
    "적자": 8,
    "급락": 7,
    "소송": 7,
    "조사": 7,
    "거래정지": 8,
    "정지": 7,
    "경고": 6,
    "처분": 6,
    "매각": 6,
    "감소": 6,
    "주식등의 수": 6,
    "하락": 5,
    "부진": 5,
    "중단": 6,
    "지연": 5,
    "리스크": 5,
    "순매도": 4,
    "지분율": 4,
    "쇼크": 9,
    "어닝쇼크": 10,
    "어닝 쇼크": 10,
    "어닝콜 쇼크": 10,
    "실적쇼크": 10,
    "실적 쇼크": 10,
    "컨센서스 하회": 9,
    "전망 하향": 8,
    "폭발": 10,
    "실패": 8,
    "발사 실패": 10,
    "로켓 폭발": 10,
    "발사 지연": 8,
    "궤도 실패": 10,
    "launch failure": 10,
    "rocket explosion": 10,
    "explosion": 10,
    "launch delay": 8,
    "wrong orbit": 9,
    "downgrade": 8,
    "tumble": 8,
    "plunge": 8,
    "crash": 8,
    "falls": 5,
    "fall": 5,
    "stocks fall": 7,
    "blows up": 10,
    "sinks": 8,
    "sank": 8,
    "lower": 5,
    "목표가 하향": 7,
    "하향": 6,
    "낮아": 6,
    "가능성 낮아": 8,
    "급감": 8,
    "못 미치": 7,
    "시장전망": 5,
    "철근": 10,
    "누락": 10,
    "부실시공": 12,
    "붕괴": 12,
    "하자": 8,
    "안전사고": 10,
    "영업정지": 10,
    "제재": 8,
    "벌점": 8,
    "국토부": 5,
}

NEWS_NOISE_KEYWORDS = (
    "lck",
    "e스포츠",
    "야구",
    "축구",
    "농구",
    "배구",
    "선발",
    "라인업",
    "전날 패배",
    "연패",
    "연승",
    "시구",
)
CAPITAL_RAISE_TERMS = ("유상증자", "증자")
CAPITAL_RAISE_GOOD_TERMS = (
    "시설투자",
    "설비투자",
    "공장",
    "증설",
    "생산능력",
    "인수자금",
    "m&a",
    "전략적 투자",
    "전략투자",
    "제3자배정",
)
CAPITAL_RAISE_BAD_TERMS = (
    "운영자금",
    "채무상환",
    "차입금",
    "재무구조",
    "주주배정",
    "실권",
    "할인율",
    "희석",
    "적자",
)

DOMESTIC_SUFFIXES = (".KS", ".KQ")


def now_kst() -> datetime:
    return datetime.now(SEOUL_TZ)


def safe_text(value, default="-"):
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def fmt_int(value):
    try:
        return f"{int(round(float(value))):,}"
    except Exception:
        return "-"


def fmt_pct(value, digits=2):
    try:
        return f"{float(value):+,.{digits}f}%"
    except Exception:
        return "-"


def split_telegram_message(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > limit:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def send_telegram(text: str) -> bool:
    if not BOT_TOKEN or not CHAT_ID:
        print("텔레그램 설정 없음: BOT_TOKEN / CHAT_ID 확인 필요", flush=True)
        return False
    from telegram_message_utils import compact_telegram_message

    text = compact_telegram_message(text)
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for chunk in split_telegram_message(text):
        response = HTTP.post(
            url,
            data={"chat_id": CHAT_ID, "text": chunk, "disable_web_page_preview": True},
            timeout=20,
        )
        response.raise_for_status()
    return True


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def run_security_guard() -> dict:
    result = security_check.run_security_check(fix_mode=NEWS_SECURITY_AUTO_FIX)
    issues = result.get("issues", [])
    high_count = sum(1 for issue in issues if issue.get("level") == "HIGH")
    medium_count = sum(1 for issue in issues if issue.get("level") == "MEDIUM")

    status = "ok"
    action = "정상 진행"
    if high_count:
        status = "block"
        action = "보안 이슈 확인 전 자동 뉴스 추적 중단"
    elif medium_count:
        status = "warn"
        action = "주의 상태로 진행"

    result["status"] = status
    result["action"] = action
    return result


def is_domestic_stock(code: str) -> bool:
    code_text = safe_text(code, "")
    return any(code_text.endswith(suffix) for suffix in DOMESTIC_SUFFIXES) or bool(
        re.fullmatch(r"[0-9A-Z]{6}", code_text.upper())
    )


def normalize_sector_for_news_pulse(sector: str) -> str:
    text = safe_text(sector, "")
    lowered = text.lower()
    if any(keyword in text for keyword in ("우주", "항공", "로켓", "위성")) or any(
        keyword in lowered for keyword in ("space", "aerospace", "rocket", "satellite")
    ):
        return "우주항공"
    return text.split("/")[0].strip()


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"sent_links": {}, "last_run_at": ""}
    try:
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"sent_links": {}, "last_run_at": ""}
    state.setdefault("sent_links", {})
    state.setdefault("last_run_at", "")
    return state


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def prune_state(state: dict, current_time: datetime) -> dict:
    cutoff = current_time - timedelta(days=3)
    sent_links = {}
    for link, sent_at in state.get("sent_links", {}).items():
        try:
            if datetime.fromisoformat(sent_at) >= cutoff:
                sent_links[link] = sent_at
        except Exception:
            continue
    state["sent_links"] = sent_links
    return state


def collect_query_targets() -> list[dict]:
    queries = []
    seen = set()

    for name, query in ALWAYS_WATCH_NEWS_QUERIES.items():
        seen.add(name)
        queries.append(
            {
                "name": name,
                "code": f"WATCH:{name}",
                "source": "always_watch",
                "query": query,
            }
        )

    analysis_df = read_csv(ANALYSIS_FILE)
    if not analysis_df.empty:
        analysis_df = analysis_df.copy()
        if "score" in analysis_df.columns:
            analysis_df["score"] = pd.to_numeric(analysis_df["score"], errors="coerce").fillna(0)
        if "risk" in analysis_df.columns:
            analysis_df["risk"] = pd.to_numeric(analysis_df["risk"], errors="coerce").fillna(99)
        if "signal" in analysis_df.columns:
            analysis_df = analysis_df[analysis_df["signal"].fillna("").astype(str).isin(["🔥 STRONG BUY", "👍 BUY", "👀 WATCH"])]
        analysis_df = analysis_df.sort_values(["score", "risk"], ascending=[False, True])
        for _, row in analysis_df.head(NEWS_QUERY_LIMIT).iterrows():
            name = safe_text(row.get("name"), "")
            code = safe_text(row.get("code"), "")
            if name and code and is_domestic_stock(code) and name not in seen:
                seen.add(name)
                queries.append({"name": name, "code": code, "source": "bot"})

    market_df = read_csv(MARKET_SCANNER_FILE)
    if not market_df.empty:
        market_df = market_df.copy()
        if "score" in market_df.columns:
            market_df["score"] = pd.to_numeric(market_df["score"], errors="coerce").fillna(0)
        market_df = market_df.sort_values("score", ascending=False)
        for _, row in market_df.head(max(10, NEWS_QUERY_LIMIT // 2)).iterrows():
            name = safe_text(row.get("name"), "")
            code = safe_text(row.get("ticker"), "")
            if name and code and is_domestic_stock(code) and name not in seen:
                seen.add(name)
                queries.append({"name": name, "code": code, "source": "market"})

        if "sector" in market_df.columns:
            for sector in market_df["sector"].dropna().astype(str):
                sector_head = normalize_sector_for_news_pulse(sector)
                if not sector_head:
                    continue
                for label, query in SECTOR_NEWS_QUERIES.items():
                    if sector_head in label or label.split("/")[0] in sector_head:
                        sector_name = f"{label} 섹터"
                        if sector_name not in seen:
                            seen.add(sector_name)
                            queries.append(
                                {
                                    "name": sector_name,
                                    "code": f"SECTOR:{label}",
                                    "source": "sector",
                                    "query": query,
                                }
                            )
                        break

    watch_count = len(ALWAYS_WATCH_NEWS_QUERIES)
    return queries[: NEWS_QUERY_LIMIT + len(SECTOR_NEWS_QUERIES) + watch_count]


def parse_pub_date(raw_value: str) -> Optional[datetime]:
    if not raw_value:
        return None
    try:
        dt = parsedate_to_datetime(raw_value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=SEOUL_TZ)
        return dt.astimezone(SEOUL_TZ)
    except Exception:
        return None


def fetch_google_news(query: str, limit: int) -> tuple[list[dict], Optional[str]]:
    items = []
    errors = []
    searches = [(query, "ko", "KR", "KR:ko")]
    if re.search(r"[A-Za-z]", query):
        searches.append((query, "en-US", "US", "US:en"))

    for search_query, hl, gl, ceid in searches:
        rss_url = (
            "https://news.google.com/rss/search?"
            f"q={quote(search_query)}&hl={hl}&gl={gl}&ceid={ceid}"
        )
        try:
            response = HTTP.get(rss_url, timeout=12)
            response.raise_for_status()
            root = ET.fromstring(response.text)
        except (requests.RequestException, ET.ParseError) as exc:
            errors.append(str(exc))
            continue

        for item in root.findall("./channel/item"):
            title = item.findtext("title", default="").strip()
            link = item.findtext("link", default="").strip()
            pub_date = parse_pub_date(item.findtext("pubDate", default="").strip())
            source = ""
            source_node = item.find("source")
            if source_node is not None and source_node.text:
                source = source_node.text.strip()
            if title and link and link not in {existing["link"] for existing in items}:
                items.append(
                    {
                        "title": title,
                        "link": link,
                        "published_at": pub_date,
                        "source": source,
                    }
                )
            if len(items) >= limit:
                break
        if len(items) >= limit:
            break

    items.sort(
        key=lambda item: item.get("published_at") if isinstance(item.get("published_at"), datetime) else datetime.min.replace(tzinfo=SEOUL_TZ),
        reverse=True,
    )
    return items[:limit], None if items else " | ".join(errors[:2]) if errors else None


def is_recent_news(item: dict, current_time: datetime) -> bool:
    published_at = item.get("published_at")
    if not isinstance(published_at, datetime):
        return False
    return published_at >= current_time - timedelta(hours=NEWS_WINDOW_HOURS)


def is_primary_recent_news(item: dict, current_time: datetime) -> bool:
    published_at = item.get("published_at")
    if not isinstance(published_at, datetime):
        return False
    return published_at >= current_time - timedelta(hours=NEWS_PRIMARY_WINDOW_HOURS)


def extract_keyword_hits(text: str) -> list[str]:
    lowered = safe_text(text, "").lower()
    hits = []
    for keyword in NEWS_KEYWORDS:
        if keyword.lower() in lowered and keyword not in hits:
            hits.append(keyword)
    return hits


def is_noise_news_title(text: str) -> bool:
    lowered = safe_text(text, "").lower()
    return any(keyword in lowered for keyword in NEWS_NOISE_KEYWORDS)


def looks_mostly_english(text: str) -> bool:
    letters = [char for char in safe_text(text, "") if char.isalpha()]
    if not letters:
        return False
    latin_count = sum(1 for char in letters if "A" <= char.upper() <= "Z")
    return latin_count / max(len(letters), 1) >= 0.55


def contains_any(text: str, keywords: list[str]) -> bool:
    lowered = safe_text(text, "").lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def localize_news_title(title: str) -> str:
    value = safe_text(title, "")
    if not looks_mostly_english(value):
        return value

    lower = value.lower()
    subjects = []
    for label, keys in [
        ("AST SpaceMobile", ["ast spacemobile", "asts"]),
        ("Rocket Lab", ["rocket lab", "rklb"]),
        ("Blue Origin", ["blue origin"]),
        ("SpaceX", ["spacex"]),
        ("Oracle", ["oracle", "orcl"]),
        ("Broadcom", ["broadcom", "avgo"]),
        ("Microsoft", ["microsoft", "msft"]),
        ("Nvidia", ["nvidia", "nvda"]),
    ]:
        if any(key in lower for key in keys):
            subjects.append(label)
    subject_text = "/".join(subjects[:3]) if subjects else "해외 종목"

    signals = []
    if contains_any(lower, ["rocket explosion", "blows up", "explosion"]):
        signals.append("로켓 폭발 여파")
    if contains_any(lower, ["launch delay", "launch failure", "setback", "wrong orbit"]):
        signals.append("발사 지연/실패 우려")
    if contains_any(lower, ["plunge", "tumble", "falls", "stocks fall", "sinks", "drops", "lower"]):
        signals.append("주가 하락 압력")
    if contains_any(lower, ["downgrade", "cuts", "cut target", "analyst"]):
        signals.append("증권사 하향/목표가 이슈")
    if contains_any(lower, ["earnings", "revenue", "profit", "guidance", "sales"]):
        signals.append("실적/가이던스 이슈")
    if contains_any(lower, ["beats", "record", "growth", "surges", "jumps", "gains", "rises"]):
        signals.append("성장/상승 모멘텀")
    if contains_any(lower, ["deal", "contract", "order", "acquisition", "merger"]):
        signals.append("계약/인수 이슈")
    if not signals:
        signals.append("해외 주요 뉴스")
    return f"{subject_text}: {' · '.join(signals[:3])}"


def classify_capital_raise_news(text: str) -> tuple[str, list[str]]:
    value = safe_text(text, "")
    lowered = value.lower()
    if not any(term in value for term in CAPITAL_RAISE_TERMS):
        return "none", []

    good_hits = [
        term
        for term in CAPITAL_RAISE_GOOD_TERMS
        if (term.lower() in lowered if any(ch.isascii() and ch.isalpha() for ch in term) else term in value)
    ]
    bad_hits = [
        term
        for term in CAPITAL_RAISE_BAD_TERMS
        if (term.lower() in lowered if any(ch.isascii() and ch.isalpha() for ch in term) else term in value)
    ]

    if good_hits and not bad_hits:
        return "good", good_hits[:3]
    if bad_hits and not good_hits:
        return "bad", bad_hits[:3]
    if good_hits and bad_hits:
        return "mixed", (good_hits[:2] + bad_hits[:2])[:4]
    return "mixed", ["자금조달 목적 확인 필요"]


def classify_news_sentiment(text: str) -> tuple[str, list[str], dict]:
    lowered = safe_text(text, "").lower()
    positive_hits = []
    negative_hits = []
    capital_raise_type, capital_raise_hits = classify_capital_raise_news(text)

    for keyword in POSITIVE_NEWS_KEYWORDS:
        if keyword.lower() in lowered and keyword not in positive_hits:
            positive_hits.append(keyword)

    for keyword in NEGATIVE_NEWS_KEYWORDS:
        if keyword == "유상증자" and capital_raise_type == "good":
            continue
        if keyword.lower() in lowered and keyword not in negative_hits:
            negative_hits.append(keyword)

    if capital_raise_type == "good":
        positive_hits.append("성장형 유증")
        positive_score_extra = 6
        negative_score_extra = 0
        capital_reason = ["성장형 유증"] + capital_raise_hits[:2]
    elif capital_raise_type == "bad":
        positive_score_extra = 0
        negative_score_extra = 8
        capital_reason = ["부담형 유증"] + capital_raise_hits[:2]
        negative_hits.append("부담형 유증")
    elif capital_raise_type == "mixed":
        positive_score_extra = 2
        negative_score_extra = 4
        capital_reason = ["유증 목적 확인 필요"] + capital_raise_hits[:2]
        negative_hits.append("유증 확인 필요")
    else:
        positive_score_extra = 0
        negative_score_extra = 0
        capital_reason = []

    positive_score = sum(POSITIVE_NEWS_WEIGHTS.get(keyword, 3) for keyword in positive_hits) + positive_score_extra
    negative_score = sum(NEGATIVE_NEWS_WEIGHTS.get(keyword, 4) for keyword in negative_hits) + negative_score_extra

    adaptive = analyze_news_impact(
        name="뉴스",
        ticker="",
        market="",
        sector="",
        news_text=text,
        price=0,
        change_pct=0,
        volume_ratio=1,
        risk=0,
        now=datetime.now(SEOUL_TZ).replace(tzinfo=None),
        state={},
    )

    if abs(int(adaptive.get("impact_score", 0))) >= 10:
        label = str(adaptive.get("label", "중립"))
        if "호재" in label:
            return "호재", list(dict.fromkeys((capital_reason or []) + positive_hits + adaptive.get("patterns", []))), adaptive
        if "악재" in label:
            return "악재", list(dict.fromkeys((capital_reason or []) + negative_hits + adaptive.get("patterns", []))), adaptive

    if negative_score >= max(positive_score, 4):
        return "악재", (capital_reason or []) + negative_hits, adaptive
    if positive_score >= 5 and positive_score > negative_score:
        return "호재", (capital_reason or []) + positive_hits, adaptive
    if positive_hits and negative_hits:
        return "혼재", (capital_reason or []) + positive_hits[:1] + negative_hits[:1], adaptive
    return "중립", [], adaptive


def analyze_news_target(target: dict, current_time: datetime) -> Optional[dict]:
    items, error = fetch_google_news(target.get("query") or target["name"], NEWS_FETCH_LIMIT)
    if error:
        return None

    recent_items = [
        item
        for item in items
        if is_recent_news(item, current_time) and not is_noise_news_title(item.get("title"))
    ]
    primary_recent_items = [item for item in recent_items if is_primary_recent_news(item, current_time)]
    if primary_recent_items:
        recent_items = primary_recent_items
    if len(recent_items) < NEWS_REQUIRED_MENTIONS:
        return None

    keyword_hits = []
    latest_published_at = None
    sentiment_counts = {"호재": 0, "악재": 0, "혼재": 0, "중립": 0}
    sentiment_reasons = {"호재": [], "악재": []}
    for item in recent_items:
        hits = extract_keyword_hits(item["title"])
        for hit in hits:
            if hit not in keyword_hits:
                keyword_hits.append(hit)
        sentiment, reasons, impact = classify_news_sentiment(item["title"])
        item["sentiment"] = sentiment
        item["sentiment_reasons"] = reasons
        item["impact_score"] = impact.get("impact_score", 0)
        item["confidence"] = impact.get("confidence", 0)
        item["impact_basis"] = impact.get("basis", "")
        sentiment_counts[sentiment] = sentiment_counts.get(sentiment, 0) + 1
        if sentiment in {"호재", "악재"}:
            for reason in reasons:
                if reason not in sentiment_reasons[sentiment]:
                    sentiment_reasons[sentiment].append(reason)
        published_at = item.get("published_at")
        if isinstance(published_at, datetime):
            if latest_published_at is None or published_at > latest_published_at:
                latest_published_at = published_at

    net_sentiment = sentiment_counts["호재"] - sentiment_counts["악재"]
    if target.get("source") != "sector" and not keyword_hits and not sentiment_counts["호재"] and not sentiment_counts["악재"]:
        return None

    impact_scores = [int(item.get("impact_score", 0) or 0) for item in recent_items]
    avg_impact = round(sum(impact_scores) / max(len(impact_scores), 1))
    avg_confidence = round(sum(int(item.get("confidence", 0) or 0) for item in recent_items) / max(len(recent_items), 1))
    score = len(recent_items) * 10 + len(keyword_hits) * 4 + net_sentiment * 3 + int(abs(avg_impact) * 0.25)
    if sentiment_counts["호재"] > sentiment_counts["악재"]:
        sentiment_summary = "호재 우세"
    elif sentiment_counts["악재"] > sentiment_counts["호재"]:
        sentiment_summary = "악재 우세"
    elif sentiment_counts["호재"] or sentiment_counts["악재"]:
        sentiment_summary = "호악재 혼재"
    else:
        sentiment_summary = "중립"

    return {
        "name": target["name"],
        "code": target["code"],
        "source": target["source"],
        "mentions_24h": len(recent_items),
        "keyword_hits": ", ".join(keyword_hits) if keyword_hits else "-",
        "latest_published_at": latest_published_at.isoformat() if latest_published_at else "",
        "headlines": recent_items,
        "score": score,
        "sentiment_summary": sentiment_summary,
        "positive_count": sentiment_counts["호재"],
        "negative_count": sentiment_counts["악재"],
        "mixed_count": sentiment_counts["혼재"],
        "neutral_count": sentiment_counts["중립"],
        "positive_reasons": ", ".join(sentiment_reasons["호재"][:4]) if sentiment_reasons["호재"] else "-",
        "negative_reasons": ", ".join(sentiment_reasons["악재"][:4]) if sentiment_reasons["악재"] else "-",
        "impact_score": avg_impact,
        "confidence": avg_confidence,
        "impact_basis": ", ".join(
            list(dict.fromkeys(str(item.get("impact_basis", "")).strip() for item in recent_items if item.get("impact_basis")))[:4]
        ) or "-",
    }


def format_news_time(raw_value) -> str:
    if isinstance(raw_value, datetime):
        dt = raw_value
    else:
        try:
            dt = datetime.fromisoformat(str(raw_value))
        except Exception:
            return "-"
    return dt.astimezone(SEOUL_TZ).strftime("%m/%d %H:%M")


def build_report(rows: list[dict], current_time: datetime, state: dict) -> tuple[str, list[str]]:
    lines = []
    fresh_links = []

    lines.append("📰 국내주식 뉴스 펄스 추적")
    lines.append(f"기준 시각: {current_time.strftime('%Y-%m-%d %H:%M KST')}")
    lines.append(f"기준 범위: 최근 {NEWS_WINDOW_HOURS}시간")
    lines.append("")

    if not rows:
        lines.append("최근 24시간 안에서 조건에 맞는 뉴스 급증 종목이 없습니다.")
        return "\n".join(lines), fresh_links

    for idx, row in enumerate(rows[:NEWS_ALERT_TOP_N], start=1):
        lines.append(
            f"{idx}. {row['name']} ({safe_text(row['code'])}) | 뉴스 {row['mentions_24h']}건 | 점수 {row['score']} | {row['sentiment_summary']}"
        )
        lines.append(f"   영향도 {int(row.get('impact_score', 0)):+d} · 신뢰도 {int(row.get('confidence', 0))}% · 근거 {row.get('impact_basis', '-')}")
        lines.append(
            f"   키워드 {row['keyword_hits']} | 호재 {row['positive_count']} / 악재 {row['negative_count']} / 혼재 {row['mixed_count']}"
        )
        if row.get("positive_reasons") and row["positive_reasons"] != "-":
            lines.append(f"   호재 포인트: {row['positive_reasons']}")
        if row.get("negative_reasons") and row["negative_reasons"] != "-":
            lines.append(f"   악재 포인트: {row['negative_reasons']}")
        for headline in row["headlines"][:3]:
            link = safe_text(headline.get("link"), "")
            published_at = headline.get("published_at")
            if link and link not in state.get("sent_links", {}):
                fresh_links.append(link)
            lines.append(
                f"   - [{format_news_time(published_at)}] {headline.get('sentiment', '중립')} | {localize_news_title(headline.get('title'))}"
            )
        lines.append("")

    return "\n".join(lines).strip(), fresh_links


def append_log(row: dict) -> None:
    frame = pd.DataFrame([row])
    if LOG_FILE.exists():
        frame.to_csv(LOG_FILE, mode="a", header=False, index=False, encoding="utf-8-sig")
    else:
        frame.to_csv(LOG_FILE, index=False, encoding="utf-8-sig")


def save_results(rows: list[dict]) -> None:
    export_rows = []
    for row in rows:
        for headline in row.get("headlines", []):
            export_rows.append(
                {
                    "name": row["name"],
                    "code": row["code"],
                    "source": row["source"],
                    "mentions_24h": row["mentions_24h"],
                    "keyword_hits": row["keyword_hits"],
                    "score": row["score"],
                    "sentiment_summary": row["sentiment_summary"],
                    "positive_count": row["positive_count"],
                    "negative_count": row["negative_count"],
                    "mixed_count": row["mixed_count"],
                    "neutral_count": row["neutral_count"],
                    "positive_reasons": row["positive_reasons"],
                    "negative_reasons": row["negative_reasons"],
                    "impact_score": row.get("impact_score", 0),
                    "confidence": row.get("confidence", 0),
                    "impact_basis": row.get("impact_basis", "-"),
                    "headline": localize_news_title(headline.get("title")),
                    "headline_sentiment": headline.get("sentiment", "중립"),
                    "headline_sentiment_reasons": ", ".join(headline.get("sentiment_reasons", [])) if headline.get("sentiment_reasons") else "-",
                    "headline_impact_score": headline.get("impact_score", 0),
                    "headline_confidence": headline.get("confidence", 0),
                    "headline_impact_basis": headline.get("impact_basis", "-"),
                    "published_at": headline.get("published_at").isoformat() if isinstance(headline.get("published_at"), datetime) else "",
                    "link": headline.get("link"),
                    "publisher": headline.get("source"),
                }
            )
    pd.DataFrame(export_rows).to_csv(RESULTS_FILE, index=False, encoding="utf-8-sig")


def run_once() -> int:
    current_time = now_kst()
    state = prune_state(load_state(), current_time)
    security_result = {"status": "ok", "summary": "이슈 없음", "action": "정상 진행", "fixed": 0, "issues": []}

    if NEWS_SECURITY_CHECK:
        security_result = run_security_guard()
        if security_result.get("fixed"):
            print(f"보안 자동 수정 완료: {security_result['fixed']}개", flush=True)
        if security_result.get("status") == "block":
            warning_text = (
                "⚠️ 뉴스 펄스 보안 경고\n"
                f"상태: {security_result.get('summary', '이슈 있음')}\n"
                f"조치: {security_result.get('action', '중단')}"
            )
            send_telegram(warning_text)
            append_log(
                {
                    "run_at": current_time.isoformat(),
                    "status": "blocked",
                    "tracked_targets": 0,
                    "detected_rows": 0,
                    "security_summary": security_result.get("summary", ""),
                }
            )
            return 1

    targets = collect_query_targets()
    rows = []
    for target in targets:
        result = analyze_news_target(target, current_time)
        if result:
            rows.append(result)

    rows.sort(key=lambda item: (item["score"], item["mentions_24h"]), reverse=True)
    save_results(rows)
    report, fresh_links = build_report(rows, current_time, state)
    if security_result.get("status") == "warn":
        report += (
            "\n\n보안 상태: 주의"
            f"\n- {security_result.get('summary', '점검 필요')}"
            f"\n- {security_result.get('action', '주의 진행')}"
        )
    if NEWS_SEND_TELEGRAM:
        send_telegram(report)

    for link in fresh_links:
        state.setdefault("sent_links", {})[link] = current_time.isoformat()
    state["last_run_at"] = current_time.isoformat()
    save_state(state)
    append_log(
        {
            "run_at": current_time.isoformat(),
            "status": "ok",
            "tracked_targets": len(targets),
            "detected_rows": len(rows),
            "security_summary": security_result.get("summary", ""),
        }
    )
    print(f"뉴스 펄스 전송 완료: {len(rows)}개 종목", flush=True)
    return 0


def main() -> int:
    if NEWS_SEND_TELEGRAM and (not BOT_TOKEN or not CHAT_ID):
        print(".env.news_pulse의 NEWS_PULSE_BOT_TOKEN / NEWS_PULSE_CHAT_ID가 필요합니다.", flush=True)
        return 1

    if "--once" in os.sys.argv or NEWS_RUN_ONCE:
        return run_once()

    print(f"뉴스 펄스 추적 시작: {NEWS_LOOP_MINUTES}분 주기 / 최근 {NEWS_WINDOW_HOURS}시간", flush=True)
    while True:
        try:
            run_once()
        except Exception as exc:
            error_text = f"뉴스 펄스 오류: {exc}"
            print(error_text, flush=True)
            try:
                send_telegram(f"⚠️ {error_text}")
            except Exception:
                pass
        time.sleep(max(60, NEWS_LOOP_MINUTES * 60))


if __name__ == "__main__":
    raise SystemExit(main())
