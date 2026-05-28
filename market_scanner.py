#!/usr/bin/env python3

import html
import ast
import os
import re
import shutil
import stat
import threading
import time as time_module
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from io import StringIO
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import requests
import yfinance as yf

from ops_guard import enforce_runtime_security

try:
    from ai_failure_memory import failure_adjustment_for
except Exception:
    def failure_adjustment_for(name, ticker, market, sector):
        return 0, ""


BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env.market_scanner"
RESULT_FILE = BASE_DIR / "market_scanner_results.csv"
SEOUL_TZ = "Asia/Seoul"
TELEGRAM_MAX_LENGTH = 3900
MARKET_INDEXES = {
    "KOSPI": "^KS11",
    "NASDAQ": "^IXIC",
    "VIX": "^VIX",
    "US10Y": "^TNX",
}
YFINANCE_DOWNLOAD_LOCK = threading.Lock()
ETF_NOW_CACHE_LOCK = threading.Lock()
ETF_NOW_CACHE = None
ETF_HOLDINGS_CACHE_LOCK = threading.Lock()
ETF_HOLDINGS_CACHE = {}
ETF_HOLDINGS_SKIP_TICKERS = {"VFV.TO"}
FULL_SERVICE_ETF_NAMES = {"TIGER 미국우주테크"}
FULL_SERVICE_ETF_PROXY_HOLDINGS = {
    "TIGER 미국우주테크": [
        {"symbol": "RKLB", "name": "Rocket Lab", "weight": 15.0},
        {"symbol": "ASTS", "name": "AST SpaceMobile", "weight": 13.0},
        {"symbol": "PL", "name": "Planet Labs", "weight": 10.0},
        {"symbol": "LUNR", "name": "Intuitive Machines", "weight": 10.0},
        {"symbol": "RDW", "name": "Redwire", "weight": 9.0},
        {"symbol": "AVAV", "name": "AeroVironment", "weight": 8.0},
        {"symbol": "KTOS", "name": "Kratos Defense", "weight": 8.0},
        {"symbol": "JOBY", "name": "Joby Aviation", "weight": 7.0},
        {"symbol": "ACHR", "name": "Archer Aviation", "weight": 7.0},
        {"symbol": "TXT", "name": "Textron", "weight": 5.0},
    ]
}
INTRADAY_CACHE_LOCK = threading.Lock()
INTRADAY_CACHE = {}
INTRADAY_SCAN_COUNT = 0
enforce_runtime_security(BASE_DIR, env_files=[ENV_FILE])

DEFAULT_STOCKS = {
    "삼성전자": "005930.KS",
    "SK하이닉스": "000660.KS",
    "한미반도체": "042700.KS",
    "테스": "095610.KQ",
    "이수페타시스": "007660.KS",
    "리노공업": "058470.KQ",
    "ISC": "095340.KQ",
    "주성엔지니어링": "036930.KQ",
    "동진쎄미켐": "005290.KQ",
    "가온칩스": "399720.KQ",
    "텔레칩스": "054450.KQ",
    "하나마이크론": "067310.KQ",
    "네오셈": "253590.KQ",
    "와이씨": "232140.KQ",
    "이오테크닉스": "039030.KQ",
    "현대차": "005380.KS",
    "기아": "000270.KS",
    "현대로템": "064350.KS",
    "한화에어로스페이스": "012450.KS",
    "한화오션": "042660.KS",
    "한화시스템": "272210.KS",
    "LIG넥스원": "079550.KS",
    "LS ELECTRIC": "010120.KS",
    "HD현대일렉트릭": "267260.KS",
    "효성중공업": "298040.KS",
    "두산에너빌리티": "034020.KS",
    "NAVER": "035420.KS",
    "카카오": "035720.KS",
    "셀트리온": "068270.KS",
    "삼성바이오로직스": "207940.KS",
    "알테오젠": "196170.KQ",
    "HLB": "028300.KQ",
    "삼천당제약": "000250.KQ",
    "에스티팜": "237690.KQ",
    "오스코텍": "039200.KQ",
    "루닛": "328130.KQ",
    "뷰노": "338220.KQ",
    "파마리서치": "214450.KQ",
    "휴젤": "145020.KQ",
    "보로노이": "310210.KQ",
    "POSCO홀딩스": "005490.KS",
    "포스코퓨처엠": "003670.KS",
    "LG에너지솔루션": "373220.KS",
    "에코프로비엠": "247540.KQ",
    "에코프로": "086520.KQ",
    "삼성SDI": "006400.KS",
    "LG화학": "051910.KS",
    "필에너지": "378340.KQ",
    "매커스": "093520.KQ",
    "피엔티": "137400.KQ",
    "윤성에프앤씨": "372170.KQ",
    "탑머티리얼": "360070.KQ",
    "TCC스틸": "002710.KS",
    "HD현대중공업": "329180.KS",
    "HD한국조선해양": "009540.KS",
    "씨에스윈드": "112610.KS",
    "한국전력": "015760.KS",
    "제룡전기": "033100.KQ",
    "일진전기": "103590.KS",
    "세명전기": "017510.KQ",
    "광명전기": "017040.KS",
    "대원전선": "006340.KS",
    "KB금융": "105560.KS",
    "신한지주": "055550.KS",
    "하나금융지주": "086790.KS",
    "삼성화재": "000810.KS",
    "삼성중공업": "010140.KS",
    "STX엔진": "077970.KS",
    "태광": "023160.KQ",
    "성광벤드": "014620.KQ",
    "동성화인텍": "033500.KQ",
    "두산로보틱스": "454910.KS",
    "레인보우로보틱스": "277810.KQ",
    "로보티즈": "108490.KQ",
    "에스피지": "058610.KQ",
    "유진로봇": "056080.KQ",
    "뉴로메카": "348340.KQ",
    "코난테크놀로지": "402030.KQ",
    "솔트룩스": "304100.KQ",
    "폴라리스오피스": "041020.KQ",
    "이스트소프트": "047560.KQ",
    "펄어비스": "263750.KQ",
    "카카오게임즈": "293490.KQ",
    "SOOP": "067160.KQ",
    "디어유": "376300.KQ",
    "와이지엔터테인먼트": "122870.KQ",
    "스튜디오드래곤": "253450.KQ",
}

SECTOR_MAP = {
    "삼성전자": "반도체",
    "SK하이닉스": "반도체",
    "한미반도체": "반도체",
    "테스": "반도체",
    "이수페타시스": "반도체",
    "리노공업": "반도체",
    "ISC": "반도체소부장",
    "주성엔지니어링": "반도체장비",
    "동진쎄미켐": "반도체소재",
    "가온칩스": "반도체설계",
    "텔레칩스": "반도체/자율주행",
    "하나마이크론": "반도체후공정",
    "네오셈": "반도체장비",
    "와이씨": "반도체장비",
    "이오테크닉스": "반도체장비",
    "현대차": "자동차",
    "기아": "자동차",
    "현대로템": "방산/철도",
    "한화에어로스페이스": "방산",
    "한화오션": "조선",
    "한화시스템": "방산",
    "LIG넥스원": "방산",
    "LS ELECTRIC": "전력기기",
    "HD현대일렉트릭": "전력기기",
    "효성중공업": "전력기기",
    "두산에너빌리티": "원전/전력",
    "NAVER": "인터넷",
    "카카오": "인터넷",
    "셀트리온": "바이오",
    "삼성바이오로직스": "바이오",
    "알테오젠": "바이오",
    "HLB": "바이오",
    "삼천당제약": "바이오",
    "에스티팜": "바이오/CDMO",
    "오스코텍": "바이오",
    "루닛": "의료AI",
    "뷰노": "의료AI",
    "파마리서치": "바이오",
    "휴젤": "바이오",
    "보로노이": "바이오",
    "POSCO홀딩스": "2차전지/소재",
    "포스코퓨처엠": "2차전지",
    "LG에너지솔루션": "2차전지",
    "에코프로비엠": "2차전지",
    "에코프로": "2차전지",
    "삼성SDI": "2차전지",
    "LG화학": "2차전지/화학",
    "필에너지": "2차전지장비",
    "매커스": "반도체",
    "피엔티": "2차전지장비",
    "윤성에프앤씨": "2차전지장비",
    "탑머티리얼": "2차전지소재",
    "TCC스틸": "2차전지소재",
    "HD현대중공업": "조선",
    "HD한국조선해양": "조선",
    "씨에스윈드": "풍력",
    "한국전력": "전력",
    "제룡전기": "전력기기",
    "일진전기": "전력기기",
    "세명전기": "전력기기",
    "광명전기": "전력기기",
    "대원전선": "전선",
    "KB금융": "금융",
    "신한지주": "금융",
    "하나금융지주": "금융",
    "삼성화재": "보험",
    "삼성중공업": "조선",
    "STX엔진": "조선/방산",
    "태광": "조선기자재",
    "성광벤드": "조선기자재",
    "동성화인텍": "조선기자재",
    "두산로보틱스": "로봇",
    "레인보우로보틱스": "로봇",
    "로보티즈": "로봇",
    "에스피지": "로봇부품",
    "유진로봇": "로봇",
    "뉴로메카": "로봇",
    "코난테크놀로지": "AI",
    "솔트룩스": "AI",
    "폴라리스오피스": "AI/소프트웨어",
    "이스트소프트": "AI/소프트웨어",
    "펄어비스": "게임",
    "카카오게임즈": "게임",
    "SOOP": "인터넷/콘텐츠",
    "디어유": "엔터/플랫폼",
    "와이지엔터테인먼트": "엔터",
    "스튜디오드래곤": "콘텐츠",
}

EXTRA_DEFAULT_STOCKS = {
    "LG전자": "066570.KS",
    "삼성전기": "009150.KS",
    "LG이노텍": "011070.KS",
    "DB하이텍": "000990.KS",
    "원익IPS": "240810.KQ",
    "HPSP": "403870.KQ",
    "기가비스": "420770.KQ",
    "파크시스템스": "140860.KQ",
    "심텍": "222800.KQ",
    "대덕전자": "353200.KS",
    "해성디에스": "195870.KS",
    "현대모비스": "012330.KS",
    "HL만도": "204320.KS",
    "에스엘": "005850.KS",
    "한국타이어앤테크놀로지": "161390.KS",
    "현대위아": "011210.KS",
    "두산밥캣": "241560.KS",
    "삼성물산": "028260.KS",
    "HD현대": "267250.KS",
    "HD현대미포": "010620.KS",
    "한화엔진": "082740.KS",
    "HMM": "011200.KS",
    "팬오션": "028670.KS",
    "현대글로비스": "086280.KS",
    "대한항공": "003490.KS",
    "아시아나항공": "020560.KS",
    "삼양식품": "003230.KS",
    "CJ제일제당": "097950.KS",
    "농심": "004370.KS",
    "오리온": "271560.KS",
    "빙그레": "005180.KS",
    "한국콜마": "161890.KS",
    "코스맥스": "192820.KS",
    "아모레퍼시픽": "090430.KS",
    "LG생활건강": "051900.KS",
    "크래프톤": "259960.KS",
    "하이브": "352820.KS",
    "JYP Ent.": "035900.KQ",
    "에스엠": "041510.KQ",
    "삼성생명": "032830.KS",
    "삼성증권": "016360.KS",
    "키움증권": "039490.KS",
    "미래에셋증권": "006800.KS",
    "메리츠금융지주": "138040.KS",
    "우리금융지주": "316140.KS",
    "기업은행": "024110.KS",
    "SK텔레콤": "017670.KS",
    "KT": "030200.KS",
    "LG유플러스": "032640.KS",
    "SK스퀘어": "402340.KS",
    "두산퓨얼셀": "336260.KS",
    "SK이노베이션": "096770.KS",
    "S-Oil": "010950.KS",
    "롯데케미칼": "011170.KS",
    "금호석유": "011780.KS",
    "고려아연": "010130.KS",
    "풍산": "103140.KS",
    "현대제철": "004020.KS",
    "세아베스틸지주": "001430.KS",
    "종근당": "185750.KS",
    "한미약품": "128940.KS",
    "유한양행": "000100.KS",
    "SK바이오팜": "326030.KS",
    "SK바이오사이언스": "302440.KS",
    "에이비엘바이오": "298380.KQ",
    "리가켐바이오": "141080.KQ",
    "펩트론": "087010.KQ",
    "에코프로머티": "450080.KS",
    "엘앤에프": "066970.KS",
    "나노신소재": "121600.KQ",
    "솔브레인": "357780.KQ",
    "천보": "278280.KQ",
    "더블유씨피": "393890.KQ",
    "SK아이이테크놀로지": "361610.KS",
    "대주전자재료": "078600.KQ",
    "LS": "006260.KS",
    "LS에코에너지": "229640.KS",
    "대한전선": "001440.KS",
    "산일전기": "062040.KS",
    "서진시스템": "178320.KQ",
    "대한광통신": "010170.KQ",
    "우리기술": "032820.KQ",
    "비에이치아이": "083650.KQ",
    "우진": "105840.KS",
    "한전기술": "052690.KS",
    "한전KPS": "051600.KS",
}

EXTRA_SECTOR_MAP = {
    "LG전자": "전자/가전",
    "삼성전기": "전자부품",
    "LG이노텍": "전자부품",
    "DB하이텍": "반도체",
    "원익IPS": "반도체장비",
    "HPSP": "반도체장비",
    "기가비스": "반도체검사",
    "파크시스템스": "반도체장비",
    "심텍": "반도체기판",
    "대덕전자": "반도체기판",
    "해성디에스": "반도체기판",
    "현대모비스": "자동차부품",
    "HL만도": "자동차부품",
    "에스엘": "자동차부품",
    "한국타이어앤테크놀로지": "자동차부품",
    "현대위아": "자동차부품",
    "두산밥캣": "건설기계",
    "삼성물산": "지주/건설",
    "HD현대": "조선/지주",
    "HD현대미포": "조선",
    "한화엔진": "조선기자재",
    "HMM": "해운",
    "팬오션": "해운",
    "현대글로비스": "물류",
    "대한항공": "항공",
    "아시아나항공": "항공",
    "삼양식품": "음식료",
    "CJ제일제당": "음식료",
    "농심": "음식료",
    "오리온": "음식료",
    "빙그레": "음식료",
    "한국콜마": "화장품",
    "코스맥스": "화장품",
    "아모레퍼시픽": "화장품",
    "LG생활건강": "화장품/생활소비재",
    "크래프톤": "게임",
    "하이브": "엔터",
    "JYP Ent.": "엔터",
    "에스엠": "엔터",
    "삼성생명": "보험",
    "삼성증권": "증권",
    "키움증권": "증권",
    "미래에셋증권": "증권",
    "메리츠금융지주": "금융",
    "우리금융지주": "금융",
    "기업은행": "금융",
    "SK텔레콤": "통신",
    "KT": "통신",
    "LG유플러스": "통신",
    "SK스퀘어": "지주/반도체",
    "두산퓨얼셀": "수소",
    "SK이노베이션": "에너지/2차전지",
    "S-Oil": "정유",
    "롯데케미칼": "화학",
    "금호석유": "화학",
    "고려아연": "비철금속",
    "풍산": "비철금속/방산",
    "현대제철": "철강",
    "세아베스틸지주": "철강",
    "종근당": "제약",
    "한미약품": "제약",
    "유한양행": "제약",
    "SK바이오팜": "바이오",
    "SK바이오사이언스": "바이오",
    "에이비엘바이오": "바이오",
    "리가켐바이오": "바이오",
    "펩트론": "바이오",
    "에코프로머티": "2차전지소재",
    "엘앤에프": "2차전지",
    "나노신소재": "2차전지소재",
    "솔브레인": "반도체/2차전지소재",
    "천보": "2차전지소재",
    "더블유씨피": "2차전지분리막",
    "SK아이이테크놀로지": "2차전지분리막",
    "대주전자재료": "2차전지소재",
    "LS": "전력/전선",
    "LS에코에너지": "전선",
    "대한전선": "전선",
    "산일전기": "전력기기",
    "서진시스템": "전력/ESS",
    "대한광통신": "전력/통신",
    "우리기술": "원전",
    "비에이치아이": "원전/전력",
    "우진": "원전",
    "한전기술": "원전/전력",
    "한전KPS": "원전/전력",
}

DEFAULT_STOCKS.update(EXTRA_DEFAULT_STOCKS)
SECTOR_MAP.update(EXTRA_SECTOR_MAP)

MORE_DEFAULT_STOCKS = {
    "한국항공우주": "047810.KS",
    "한화": "000880.KS",
    "두산": "000150.KS",
    "현대건설": "000720.KS",
    "GS건설": "006360.KS",
    "삼성E&A": "028050.KS",
    "DL이앤씨": "375500.KS",
    "HD현대건설기계": "267270.KS",
    "HD현대마린솔루션": "443060.KS",
    "한국카본": "017960.KS",
    "오리엔탈정공": "014940.KS",
    "카카오뱅크": "323410.KS",
    "카카오페이": "377300.KS",
    "한국금융지주": "071050.KS",
    "NH투자증권": "005940.KS",
    "DB손해보험": "005830.KS",
    "KT&G": "033780.KS",
    "LG": "003550.KS",
    "CJ": "001040.KS",
    "GS": "078930.KS",
    "삼성SDS": "018260.KS",
    "현대오토에버": "307950.KS",
    "카페24": "042000.KQ",
    "클래시스": "214150.KQ",
    "브이티": "018290.KQ",
    "에이피알": "278470.KS",
    "대웅제약": "069620.KS",
    "HLB제약": "047920.KQ",
    "지아이이노베이션": "358570.KQ",
    "안트로젠": "065660.KQ",
    "바이오니아": "064550.KQ",
    "프로텍": "053610.KQ",
    "유진테크": "084370.KQ",
    "네패스": "033640.KQ",
    "원익머트리얼즈": "104830.KQ",
    "케이씨텍": "281820.KS",
    "한양디지텍": "078350.KQ",
    "미코": "059090.KQ",
    "성일하이텍": "365340.KQ",
    "롯데에너지머티리얼즈": "020150.KS",
    "포스코DX": "022100.KS",
}

MORE_SECTOR_MAP = {
    "한국항공우주": "방산/우주",
    "한화": "지주/방산",
    "두산": "지주/로봇",
    "현대건설": "건설",
    "GS건설": "건설",
    "삼성E&A": "건설/플랜트",
    "DL이앤씨": "건설",
    "HD현대건설기계": "건설기계",
    "HD현대마린솔루션": "조선/서비스",
    "한국카본": "조선기자재",
    "오리엔탈정공": "조선기자재",
    "카카오뱅크": "금융/인터넷",
    "카카오페이": "핀테크",
    "한국금융지주": "증권",
    "NH투자증권": "증권",
    "DB손해보험": "보험",
    "KT&G": "소비재",
    "LG": "지주",
    "CJ": "지주/소비",
    "GS": "지주/에너지",
    "삼성SDS": "IT서비스",
    "현대오토에버": "IT서비스/자동차",
    "카페24": "이커머스",
    "클래시스": "의료기기",
    "브이티": "화장품",
    "에이피알": "화장품/뷰티테크",
    "대웅제약": "제약",
    "HLB제약": "제약/바이오",
    "지아이이노베이션": "바이오",
    "안트로젠": "바이오",
    "바이오니아": "바이오",
    "프로텍": "반도체장비",
    "유진테크": "반도체장비",
    "네패스": "반도체후공정",
    "원익머트리얼즈": "반도체소재",
    "케이씨텍": "반도체장비",
    "한양디지텍": "반도체",
    "미코": "반도체소부장",
    "성일하이텍": "2차전지재활용",
    "롯데에너지머티리얼즈": "2차전지소재",
    "포스코DX": "IT/스마트팩토리",
}

HOLDING_GROUP_STOCKS = {
    "LS머트리얼즈": "417200.KQ",
    "LS네트웍스": "000680.KS",
    "LS증권": "078020.KQ",
    "LS전선아시아": "229640.KS",
    "가온전선": "000500.KS",
    "에코프로머티": "450080.KS",
    "에코프로에이치엔": "383310.KQ",
    "롯데지주": "004990.KS",
    "효성": "004800.KS",
    "효성첨단소재": "298050.KS",
}

HOLDING_GROUP_SECTOR_MAP = {
    "LS머트리얼즈": "2차전지소재",
    "LS네트웍스": "지주/유통",
    "LS증권": "금융/증권",
    "LS전선아시아": "전선",
    "가온전선": "전선",
    "에코프로머티": "2차전지소재",
    "에코프로에이치엔": "친환경/소재",
    "롯데지주": "지주",
    "효성": "지주",
    "효성첨단소재": "소재",
}

DEFAULT_STOCKS.update(MORE_DEFAULT_STOCKS)
SECTOR_MAP.update(MORE_SECTOR_MAP)
DEFAULT_STOCKS.update(HOLDING_GROUP_STOCKS)
SECTOR_MAP.update(HOLDING_GROUP_SECTOR_MAP)

SEARCH_EXPANSION_STOCKS = {
    "LG디스플레이": "034220.KS",
    "SKC": "011790.KS",
    "코웨이": "021240.KS",
    "F&F": "383220.KS",
    "영원무역": "111770.KS",
    "한섬": "020000.KS",
    "현대백화점": "069960.KS",
    "신세계": "004170.KS",
    "호텔신라": "008770.KS",
    "이마트": "139480.KS",
    "롯데쇼핑": "023530.KS",
    "BGF리테일": "282330.KS",
    "GS리테일": "007070.KS",
    "오뚜기": "007310.KS",
    "하이트진로": "000080.KS",
    "롯데칠성": "005300.KS",
    "동원산업": "006040.KS",
    "한국가스공사": "036460.KS",
    "지역난방공사": "071320.KS",
    "삼천리": "004690.KS",
    "포스코인터내셔널": "047050.KS",
    "LX인터내셔널": "001120.KS",
    "LX세미콘": "108320.KQ",
    "하나투어": "039130.KS",
    "모두투어": "080160.KQ",
    "파라다이스": "034230.KQ",
    "GKL": "114090.KS",
    "강원랜드": "035250.KS",
    "넷마블": "251270.KS",
    "컴투스": "078340.KQ",
    "위메이드": "112040.KQ",
    "데브시스터즈": "194480.KQ",
    "넥슨게임즈": "225570.KQ",
    "엔씨소프트": "036570.KS",
    "더존비즈온": "012510.KS",
    "안랩": "053800.KQ",
    "알서포트": "131370.KQ",
    "마음AI": "377480.KQ",
    "셀바스AI": "108860.KQ",
    "플리토": "300080.KQ",
    "딥노이드": "315640.KQ",
    "모아데이타": "288980.KQ",
    "티로보틱스": "117730.KQ",
    "로보스타": "090360.KQ",
    "에브리봇": "270660.KQ",
    "휴림로봇": "090710.KQ",
    "에이프릴바이오": "397030.KQ",
    "샤페론": "378800.KQ",
    "메드팩토": "235980.KQ",
    "차바이오텍": "085660.KQ",
    "헬릭스미스": "084990.KQ",
    "지노믹트리": "228760.KQ",
    "바이넥스": "053030.KQ",
    "HK이노엔": "195940.KQ",
    "동국제약": "086450.KQ",
    "보령": "003850.KS",
    "녹십자": "006280.KS",
    "대웅": "003090.KS",
    "JW중외제약": "001060.KS",
    "칩스앤미디어": "094360.KQ",
    "제주반도체": "080220.KQ",
    "어보브반도체": "102120.KQ",
    "넥스트칩": "396270.KQ",
    "퀄리타스반도체": "432720.KQ",
    "오픈엣지테크놀로지": "394280.KQ",
    "자람테크놀로지": "389020.KQ",
    "미래반도체": "254490.KQ",
    "피에스케이홀딩스": "031980.KQ",
    "피에스케이": "319660.KQ",
    "테크윙": "089030.KQ",
    "엑시콘": "092870.KQ",
    "디아이": "003160.KS",
    "엔켐": "348370.KQ",
    "중앙첨단소재": "051980.KQ",
    "금양": "001570.KS",
    "코스모신소재": "005070.KS",
    "코스모화학": "005420.KS",
    "DI동일": "001530.KS",
    "후성": "093370.KS",
    "씨아이에스": "222080.KQ",
    "하나기술": "299030.KQ",
    "SNT다이내믹스": "003570.KS",
    "아이쓰리시스템": "214430.KQ",
    "쎄트렉아이": "099320.KQ",
    "AP위성": "211270.KQ",
    "인텔리안테크": "189300.KQ",
    "세진중공업": "075580.KS",
    "현대힘스": "460930.KQ",
    "일승": "333430.KQ",
    "지투파워": "388050.KQ",
    "그리드위즈": "453450.KS",
    "제일일렉트릭": "199820.KQ",
    "보성파워텍": "006910.KQ",
    "일진파워": "094820.KQ",
}

SEARCH_EXPANSION_SECTOR_MAP = {
    "LG디스플레이": "디스플레이",
    "SKC": "소재/2차전지",
    "코웨이": "렌탈/소비재",
    "F&F": "패션",
    "영원무역": "패션",
    "한섬": "패션",
    "현대백화점": "유통",
    "신세계": "유통",
    "호텔신라": "면세/호텔",
    "이마트": "유통",
    "롯데쇼핑": "유통",
    "BGF리테일": "편의점",
    "GS리테일": "편의점",
    "오뚜기": "음식료",
    "하이트진로": "음식료",
    "롯데칠성": "음식료",
    "동원산업": "음식료",
    "한국가스공사": "에너지",
    "지역난방공사": "에너지",
    "삼천리": "에너지",
    "포스코인터내셔널": "상사/에너지",
    "LX인터내셔널": "상사",
    "LX세미콘": "반도체설계",
    "하나투어": "여행",
    "모두투어": "여행",
    "파라다이스": "카지노/관광",
    "GKL": "카지노/관광",
    "강원랜드": "카지노/관광",
    "넷마블": "게임",
    "컴투스": "게임",
    "위메이드": "게임",
    "데브시스터즈": "게임",
    "넥슨게임즈": "게임",
    "엔씨소프트": "게임",
    "더존비즈온": "소프트웨어",
    "안랩": "보안",
    "알서포트": "소프트웨어",
    "마음AI": "AI",
    "셀바스AI": "AI",
    "플리토": "AI",
    "딥노이드": "의료AI",
    "모아데이타": "AI/데이터",
    "티로보틱스": "로봇",
    "로보스타": "로봇",
    "에브리봇": "로봇",
    "휴림로봇": "로봇",
    "에이프릴바이오": "바이오",
    "샤페론": "바이오",
    "메드팩토": "바이오",
    "차바이오텍": "바이오",
    "헬릭스미스": "바이오",
    "지노믹트리": "바이오",
    "바이넥스": "바이오",
    "HK이노엔": "제약",
    "동국제약": "제약",
    "보령": "제약",
    "녹십자": "제약",
    "대웅": "제약",
    "JW중외제약": "제약",
    "칩스앤미디어": "반도체설계",
    "제주반도체": "반도체",
    "어보브반도체": "반도체",
    "넥스트칩": "반도체/자율주행",
    "퀄리타스반도체": "반도체",
    "오픈엣지테크놀로지": "반도체설계",
    "자람테크놀로지": "반도체",
    "미래반도체": "반도체",
    "피에스케이홀딩스": "반도체장비",
    "피에스케이": "반도체장비",
    "테크윙": "반도체장비",
    "엑시콘": "반도체검사",
    "디아이": "반도체장비",
    "엔켐": "2차전지",
    "중앙첨단소재": "2차전지소재",
    "금양": "2차전지",
    "코스모신소재": "2차전지소재",
    "코스모화학": "2차전지소재",
    "DI동일": "2차전지소재",
    "후성": "2차전지소재",
    "씨아이에스": "2차전지장비",
    "하나기술": "2차전지장비",
    "SNT다이내믹스": "방산",
    "아이쓰리시스템": "방산",
    "쎄트렉아이": "우주/방산",
    "AP위성": "우주",
    "인텔리안테크": "우주/통신",
    "세진중공업": "조선기자재",
    "현대힘스": "조선기자재",
    "일승": "조선기자재",
    "지투파워": "전력기기",
    "그리드위즈": "전력/ESS",
    "제일일렉트릭": "전력기기",
    "보성파워텍": "전력/원전",
    "일진파워": "전력/원전",
}

DEFAULT_STOCKS.update(SEARCH_EXPANSION_STOCKS)
SECTOR_MAP.update(SEARCH_EXPANSION_SECTOR_MAP)

NUCLEAR_THEME_STOCKS = {
    "한신기계": "011700.KS",
    "서전기전": "189860.KQ",
    "오르비텍": "046120.KQ",
    "에너토크": "019990.KQ",
    "수산인더스트리": "126720.KS",
    "우진엔텍": "457550.KQ",
    "대창솔루션": "096350.KQ",
    "삼영엠텍": "054540.KQ",
    "SNT에너지": "100840.KS",
}

NUCLEAR_THEME_SECTOR_MAP = {
    "한신기계": "원전/기계",
    "서전기전": "원전/전력기기",
    "오르비텍": "원전/방사선",
    "에너토크": "원전/밸브",
    "수산인더스트리": "원전/정비",
    "우진엔텍": "원전/정비",
    "대창솔루션": "원전/기자재",
    "삼영엠텍": "원전/기자재",
    "SNT에너지": "원전/에너지설비",
}

DEFAULT_STOCKS.update(NUCLEAR_THEME_STOCKS)
SECTOR_MAP.update(NUCLEAR_THEME_SECTOR_MAP)

KOREA_VALUE_STOCKS = {
    "대우건설": "047040.KS",
    "HDC현대산업개발": "294870.KS",
    "DL": "000210.KS",
    "금호건설": "002990.KS",
    "계룡건설": "013580.KS",
    "동부건설": "005960.KS",
    "코오롱글로벌": "003070.KS",
    "현대해상": "001450.KS",
    "한화생명": "088350.KS",
    "DGB금융지주": "139130.KS",
    "BNK금융지주": "138930.KS",
    "JB금융지주": "175330.KS",
    "제주은행": "006220.KS",
    "롯데손해보험": "000400.KS",
    "대신증권": "003540.KS",
    "유안타증권": "003470.KS",
    "SK증권": "001510.KS",
    "교보증권": "030610.KS",
    "한화투자증권": "003530.KS",
    "현대차우": "005385.KS",
    "기아우": "000275.KS",
    "한국철강": "104700.KS",
    "동국제강": "460860.KS",
    "동국홀딩스": "001230.KS",
    "KG스틸": "016380.KS",
    "대한제강": "084010.KS",
    "동원개발": "013120.KQ",
    "서희건설": "035890.KQ",
}

KOREA_LEADER_STOCKS = {
    "CJ대한통운": "000120.KS",
    "롯데웰푸드": "280360.KS",
    "대상": "001680.KS",
    "현대그린푸드": "453340.KS",
    "CJ프레시웨이": "051500.KQ",
    "현대홈쇼핑": "057050.KS",
    "롯데렌탈": "089860.KS",
    "롯데관광개발": "032350.KS",
    "제주항공": "089590.KS",
    "진에어": "272450.KS",
    "티웨이항공": "091810.KS",
    "대한해운": "005880.KS",
    "CJ ENM": "035760.KQ",
    "제일기획": "030000.KS",
    "이노션": "214320.KS",
    "콘텐트리중앙": "036420.KS",
    "SBS": "034120.KS",
    "네오위즈": "095660.KQ",
    "웹젠": "069080.KQ",
    "NHN": "181710.KS",
    "더블유게임즈": "192080.KS",
    "신세계인터내셔날": "031430.KS",
    "휠라홀딩스": "081660.KS",
    "LF": "093050.KS",
    "한샘": "009240.KS",
    "현대리바트": "079430.KS",
    "HD현대인프라코어": "042670.KS",
    "현대엘리베이터": "017800.KS",
    "HD현대마린엔진": "071970.KS",
    "HJ중공업": "097230.KS",
    "SK오션플랜트": "100090.KS",
    "SNT모티브": "064960.KS",
    "삼성카드": "029780.KS",
    "KG이니시스": "035600.KQ",
    "NHN KCP": "060250.KQ",
    "다날": "064260.KQ",
    "서울반도체": "046890.KQ",
    "덕산네오룩스": "213420.KQ",
    "원익QnC": "074600.KQ",
    "월덱스": "101160.KQ",
    "티씨케이": "064760.KQ",
    "고영": "098460.KQ",
    "비에이치": "090460.KS",
    "이녹스첨단소재": "272290.KQ",
}

KOREA_THEME_STOCKS = {
    "두산로보틱스": "454910.KS",
    "레인보우로보틱스": "277810.KQ",
    "로보티즈": "108490.KQ",
    "유일로보틱스": "388720.KQ",
    "티로보틱스": "117730.KQ",
    "에스피지": "058610.KQ",
    "에스비비테크": "389500.KQ",
    "뉴로메카": "348340.KQ",
    "로보스타": "090360.KQ",
    "휴림로봇": "090710.KQ",
    "삼익THK": "004380.KS",
    "셀트리온": "068270.KS",
    "삼성바이오로직스": "207940.KS",
    "유한양행": "000100.KS",
    "한미약품": "128940.KS",
    "HLB": "028300.KQ",
    "클래시스": "214150.KQ",
    "파마리서치": "214450.KQ",
    "덴티움": "145720.KS",
    "루닛": "328130.KQ",
    "뷰노": "338220.KQ",
    "LS": "006260.KS",
    "LS ELECTRIC": "010120.KS",
    "대한전선": "001440.KS",
    "가온전선": "000500.KS",
    "LS마린솔루션": "060370.KQ",
    "일진전기": "103590.KS",
    "일진홀딩스": "015860.KS",
    "대원전선": "006340.KS",
    "KBI메탈": "024840.KQ",
    "제룡전기": "033100.KQ",
    "조일알미늄": "018470.KS",
    "알루코": "001780.KS",
    "삼아알미늄": "006110.KS",
    "남선알미늄": "008350.KS",
    "DI동일": "001530.KS",
    "피제이메탈": "128660.KQ",
    "HMM": "011200.KS",
    "팬오션": "028670.KS",
    "흥아해운": "003280.KS",
    "KSS해운": "044450.KS",
    "태웅로직스": "124560.KQ",
    "HD현대일렉트릭": "267260.KS",
    "효성중공업": "298040.KS",
    "비츠로테크": "042370.KQ",
    "광명전기": "017040.KS",
    "서전기전": "189860.KQ",
    "풍산": "103140.KS",
    "이구산업": "025820.KS",
    "대창": "012800.KS",
    "국일신동": "060480.KQ",
    "서원": "021050.KS",
    "미래에셋증권": "006800.KS",
    "한국금융지주": "071050.KS",
    "NH투자증권": "005940.KS",
    "삼성증권": "016360.KS",
    "키움증권": "039490.KS",
    "DB금융투자": "016610.KS",
    "케이엠더블유": "032500.KQ",
    "RFHIC": "218410.KQ",
    "쏠리드": "050890.KQ",
    "에이스테크": "088800.KQ",
    "서진시스템": "178320.KQ",
    "오이솔루션": "138080.KQ",
    "대한광통신": "010170.KQ",
    "우리로": "046970.KQ",
    "코위버": "056360.KQ",
    "텔레필드": "091440.KQ",
    "옵티시스": "109080.KQ",
    "머큐리": "100590.KQ",
    "유비쿼스": "264450.KQ",
    "다산네트웍스": "039560.KQ",
    "SK텔레콤": "017670.KS",
    "KT": "030200.KS",
    "LG유플러스": "032640.KS",
    "한국전력": "015760.KS",
    "한전KPS": "051600.KS",
    "한전기술": "052690.KS",
    "지역난방공사": "071320.KS",
    "SGC에너지": "005090.KS",
    "대성에너지": "117580.KS",
    "한국가스공사": "036460.KS",
    "삼천리": "004690.KS",
}

CANADA_DEFAULT_STOCKS = {
    "Shopify": "SHOP.TO",
    "Royal Bank of Canada": "RY.TO",
    "TD Bank": "TD.TO",
    "Bank of Nova Scotia": "BNS.TO",
    "Bank of Montreal": "BMO.TO",
    "CIBC": "CM.TO",
    "Canadian Natural Resources": "CNQ.TO",
    "Suncor Energy": "SU.TO",
    "Enbridge": "ENB.TO",
    "TC Energy": "TRP.TO",
    "Canadian National Railway": "CNR.TO",
    "Canadian Pacific Kansas City": "CP.TO",
    "Brookfield Corp": "BN.TO",
    "Brookfield Asset Management": "BAM.TO",
    "Manulife": "MFC.TO",
    "Sun Life": "SLF.TO",
    "BCE": "BCE.TO",
    "Telus": "T.TO",
    "Thomson Reuters": "TRI.TO",
    "Waste Connections": "WCN.TO",
    "Loblaw": "L.TO",
    "Metro": "MRU.TO",
    "Alimentation Couche-Tard": "ATD.TO",
    "Dollarama": "DOL.TO",
    "Constellation Software": "CSU.TO",
    "CGI": "GIB-A.TO",
    "OpenText": "OTEX.TO",
    "Barrick Gold": "ABX.TO",
    "Agnico Eagle": "AEM.TO",
    "Nutrien": "NTR.TO",
    "Teck Resources": "TECK-B.TO",
    "First Quantum Minerals": "FM.TO",
    "Cameco": "CCO.TO",
    "Magna": "MG.TO",
    "Wheaton Precious Metals": "WPM.TO",
    "Franco-Nevada": "FNV.TO",
    "Power Corp": "POW.TO",
    "Intact Financial": "IFC.TO",
    "Fortis": "FTS.TO",
    "Hydro One": "H.TO",
}

CANADA_EXPANDED_STOCKS = {
    "Vanguard S&P 500 Index ETF": "VFV.TO",
    "National Bank": "NA.TO",
    "Equitable Bank": "EQB.TO",
    "Laurentian Bank": "LB.TO",
    "goeasy": "GSY.TO",
    "Fairfax Financial": "FFH.TO",
    "Great-West Lifeco": "GWO.TO",
    "iA Financial": "IAG.TO",
    "West Fraser Timber": "WFG.TO",
    "Saputo": "SAP.TO",
    "Canadian Tire": "CTC-A.TO",
    "Restaurant Brands": "QSR.TO",
    "Empire": "EMP-A.TO",
    "George Weston": "WN.TO",
    "Premium Brands": "PBH.TO",
    "CCL Industries": "CCL-B.TO",
    "Toromont": "TIH.TO",
    "TFI International": "TFII.TO",
    "CAE": "CAE.TO",
    "Air Canada": "AC.TO",
    "Bombardier": "BBD-B.TO",
    "WSP Global": "WSP.TO",
    "Stantec": "STN.TO",
    "AltaGas": "ALA.TO",
    "Pembina Pipeline": "PPL.TO",
    "Keyera": "KEY.TO",
    "Gibson Energy": "GEI.TO",
    "Tourmaline Oil": "TOU.TO",
    "ARC Resources": "ARX.TO",
    "Whitecap Resources": "WCP.TO",
    "MEG Energy": "MEG.TO",
    "Cenovus Energy": "CVE.TO",
    "Imperial Oil": "IMO.TO",
    "Ovintiv": "OVV.TO",
    "Birchcliff Energy": "BIR.TO",
    "Freehold Royalties": "FRU.TO",
    "Vermilion Energy": "VET.TO",
    "Algonquin Power": "AQN.TO",
    "Emera": "EMA.TO",
    "Canadian Utilities": "CU.TO",
    "Capital Power": "CPX.TO",
    "Northland Power": "NPI.TO",
    "Brookfield Renewable": "BEP-UN.TO",
    "Brookfield Infrastructure": "BIP-UN.TO",
    "Canadian Apartment REIT": "CAR-UN.TO",
    "RioCan REIT": "REI-UN.TO",
    "SmartCentres REIT": "SRU-UN.TO",
    "Granite REIT": "GRT-UN.TO",
    "H&R REIT": "HR-UN.TO",
    "Dream Industrial REIT": "DIR-UN.TO",
    "Colliers": "CIGI.TO",
}

KOREA_VALUE_SECTOR_MAP = {
    "대우건설": "건설/저평가",
    "HDC현대산업개발": "건설/저평가",
    "DL": "지주/화학",
    "금호건설": "건설/저평가",
    "계룡건설": "건설/저평가",
    "동부건설": "건설/저평가",
    "코오롱글로벌": "건설/저평가",
    "현대해상": "보험/저PBR",
    "한화생명": "보험/저PBR",
    "DGB금융지주": "금융/저PBR",
    "BNK금융지주": "금융/저PBR",
    "JB금융지주": "금융/저PBR",
    "제주은행": "금융",
    "롯데손해보험": "보험",
    "대신증권": "증권/저PBR",
    "유안타증권": "증권",
    "SK증권": "증권",
    "교보증권": "증권",
    "한화투자증권": "증권",
    "현대차우": "자동차/우선주",
    "기아우": "자동차/우선주",
    "한국철강": "철강/저평가",
    "동국제강": "철강/저평가",
    "동국홀딩스": "지주/철강",
    "KG스틸": "철강",
    "대한제강": "철강",
    "동원개발": "건설/저평가",
    "서희건설": "건설/저평가",
}

KOREA_LEADER_SECTOR_MAP = {
    "CJ대한통운": "물류",
    "롯데웰푸드": "음식료",
    "대상": "음식료",
    "현대그린푸드": "음식료/급식",
    "CJ프레시웨이": "음식료/급식",
    "현대홈쇼핑": "유통",
    "롯데렌탈": "렌탈",
    "롯데관광개발": "카지노/관광",
    "제주항공": "항공",
    "진에어": "항공",
    "티웨이항공": "항공",
    "대한해운": "해운",
    "CJ ENM": "콘텐츠/미디어",
    "제일기획": "광고",
    "이노션": "광고",
    "콘텐트리중앙": "콘텐츠",
    "SBS": "방송",
    "네오위즈": "게임",
    "웹젠": "게임",
    "NHN": "게임/IT",
    "더블유게임즈": "게임",
    "신세계인터내셔날": "패션/화장품",
    "휠라홀딩스": "패션",
    "LF": "패션",
    "한샘": "가구/인테리어",
    "현대리바트": "가구/인테리어",
    "HD현대인프라코어": "건설기계",
    "현대엘리베이터": "기계",
    "HD현대마린엔진": "조선기자재",
    "HJ중공업": "조선/건설",
    "SK오션플랜트": "해상풍력/조선",
    "SNT모티브": "자동차부품/방산",
    "삼성카드": "카드/금융",
    "KG이니시스": "결제",
    "NHN KCP": "결제",
    "다날": "결제",
    "서울반도체": "LED/부품",
    "덕산네오룩스": "OLED소재",
    "원익QnC": "반도체소재",
    "월덱스": "반도체소재",
    "티씨케이": "반도체소재",
    "고영": "반도체/검사장비",
    "비에이치": "전자부품",
    "이녹스첨단소재": "OLED/소재",
}

KOREA_THEME_SECTOR_MAP = {
    "두산로보틱스": "로봇",
    "레인보우로보틱스": "로봇",
    "로보티즈": "로봇",
    "유일로보틱스": "로봇",
    "티로보틱스": "로봇/자동화",
    "에스피지": "로봇부품",
    "에스비비테크": "로봇부품",
    "뉴로메카": "협동로봇",
    "로보스타": "로봇/자동화",
    "휴림로봇": "로봇",
    "삼익THK": "로봇부품/자동화",
    "셀트리온": "의료/바이오",
    "삼성바이오로직스": "의료/바이오",
    "유한양행": "의료/제약",
    "한미약품": "의료/제약",
    "HLB": "의료/바이오",
    "클래시스": "의료기기",
    "파마리서치": "의료/미용",
    "덴티움": "의료기기",
    "루닛": "의료AI",
    "뷰노": "의료AI",
    "LS": "전선/전력",
    "LS ELECTRIC": "전기설비",
    "대한전선": "전선",
    "가온전선": "전선",
    "LS마린솔루션": "해저케이블/전선",
    "일진전기": "전선/전력기기",
    "일진홀딩스": "전선/전력",
    "대원전선": "전선",
    "KBI메탈": "전선/구리",
    "제룡전기": "전기설비",
    "조일알미늄": "알루미늄",
    "알루코": "알루미늄",
    "삼아알미늄": "알루미늄",
    "남선알미늄": "알루미늄",
    "DI동일": "알루미늄",
    "피제이메탈": "알루미늄",
    "HMM": "해운",
    "팬오션": "해운",
    "흥아해운": "해운",
    "KSS해운": "해운",
    "태웅로직스": "해운/물류",
    "HD현대일렉트릭": "전기설비",
    "효성중공업": "전기설비",
    "비츠로테크": "전력기기",
    "광명전기": "전기설비",
    "서전기전": "전기설비",
    "풍산": "구리/방산",
    "이구산업": "구리",
    "대창": "구리",
    "국일신동": "구리",
    "서원": "구리",
    "미래에셋증권": "증권",
    "한국금융지주": "증권",
    "NH투자증권": "증권",
    "삼성증권": "증권",
    "키움증권": "증권",
    "DB금융투자": "증권",
    "케이엠더블유": "통신장비",
    "RFHIC": "통신장비",
    "쏠리드": "통신장비",
    "에이스테크": "통신장비",
    "서진시스템": "통신장비",
    "오이솔루션": "광통신",
    "대한광통신": "광통신",
    "우리로": "광통신",
    "코위버": "광통신",
    "텔레필드": "광통신",
    "옵티시스": "광통신",
    "머큐리": "통신장비/광통신",
    "유비쿼스": "통신장비",
    "다산네트웍스": "통신장비",
    "SK텔레콤": "통신",
    "KT": "통신",
    "LG유플러스": "통신",
    "한국전력": "전력에너지",
    "한전KPS": "전력에너지",
    "한전기술": "전력에너지",
    "지역난방공사": "전력에너지",
    "SGC에너지": "전력에너지",
    "대성에너지": "전력에너지",
    "한국가스공사": "전력에너지",
    "삼천리": "전력에너지",
}

CANADA_SECTOR_MAP = {
    "Shopify": "캐나다/이커머스",
    "Royal Bank of Canada": "캐나다/은행",
    "TD Bank": "캐나다/은행",
    "Bank of Nova Scotia": "캐나다/은행",
    "Bank of Montreal": "캐나다/은행",
    "CIBC": "캐나다/은행",
    "Canadian Natural Resources": "캐나다/에너지",
    "Suncor Energy": "캐나다/에너지",
    "Enbridge": "캐나다/파이프라인",
    "TC Energy": "캐나다/파이프라인",
    "Canadian National Railway": "캐나다/철도",
    "Canadian Pacific Kansas City": "캐나다/철도",
    "Brookfield Corp": "캐나다/자산운용",
    "Brookfield Asset Management": "캐나다/자산운용",
    "Manulife": "캐나다/보험",
    "Sun Life": "캐나다/보험",
    "BCE": "캐나다/통신",
    "Telus": "캐나다/통신",
    "Thomson Reuters": "캐나다/정보서비스",
    "Waste Connections": "캐나다/환경",
    "Loblaw": "캐나다/소비",
    "Metro": "캐나다/소비",
    "Alimentation Couche-Tard": "캐나다/편의점",
    "Dollarama": "캐나다/소매",
    "Constellation Software": "캐나다/소프트웨어",
    "CGI": "캐나다/IT서비스",
    "OpenText": "캐나다/소프트웨어",
    "Barrick Gold": "캐나다/금광",
    "Agnico Eagle": "캐나다/금광",
    "Nutrien": "캐나다/비료",
    "Teck Resources": "캐나다/광산",
    "First Quantum Minerals": "캐나다/구리",
    "Cameco": "캐나다/우라늄",
    "Magna": "캐나다/자동차부품",
    "Wheaton Precious Metals": "캐나다/귀금속",
    "Franco-Nevada": "캐나다/금광",
    "Power Corp": "캐나다/금융지주",
    "Intact Financial": "캐나다/보험",
    "Fortis": "캐나다/유틸리티",
    "Hydro One": "캐나다/유틸리티",
}

CANADA_EXPANDED_SECTOR_MAP = {
    "Vanguard S&P 500 Index ETF": "캐나다/ETF",
    "National Bank": "캐나다/은행",
    "Equitable Bank": "캐나다/은행",
    "Laurentian Bank": "캐나다/은행",
    "goeasy": "캐나다/금융",
    "Fairfax Financial": "캐나다/보험",
    "Great-West Lifeco": "캐나다/보험",
    "iA Financial": "캐나다/보험",
    "West Fraser Timber": "캐나다/목재",
    "Saputo": "캐나다/식품",
    "Canadian Tire": "캐나다/소매",
    "Restaurant Brands": "캐나다/외식",
    "Empire": "캐나다/소비",
    "George Weston": "캐나다/소비",
    "Premium Brands": "캐나다/식품",
    "CCL Industries": "캐나다/포장",
    "Toromont": "캐나다/산업장비",
    "TFI International": "캐나다/물류",
    "CAE": "캐나다/항공훈련",
    "Air Canada": "캐나다/항공",
    "Bombardier": "캐나다/항공기",
    "WSP Global": "캐나다/엔지니어링",
    "Stantec": "캐나다/엔지니어링",
    "AltaGas": "캐나다/파이프라인",
    "Pembina Pipeline": "캐나다/파이프라인",
    "Keyera": "캐나다/파이프라인",
    "Gibson Energy": "캐나다/에너지인프라",
    "Tourmaline Oil": "캐나다/천연가스",
    "ARC Resources": "캐나다/천연가스",
    "Whitecap Resources": "캐나다/에너지",
    "MEG Energy": "캐나다/오일샌드",
    "Cenovus Energy": "캐나다/에너지",
    "Imperial Oil": "캐나다/에너지",
    "Ovintiv": "캐나다/에너지",
    "Birchcliff Energy": "캐나다/천연가스",
    "Freehold Royalties": "캐나다/에너지로열티",
    "Vermilion Energy": "캐나다/에너지",
    "Algonquin Power": "캐나다/유틸리티",
    "Emera": "캐나다/유틸리티",
    "Canadian Utilities": "캐나다/유틸리티",
    "Capital Power": "캐나다/전력",
    "Northland Power": "캐나다/전력",
    "Brookfield Renewable": "캐나다/재생에너지",
    "Brookfield Infrastructure": "캐나다/인프라",
    "Canadian Apartment REIT": "캐나다/REIT",
    "RioCan REIT": "캐나다/REIT",
    "SmartCentres REIT": "캐나다/REIT",
    "Granite REIT": "캐나다/REIT",
    "H&R REIT": "캐나다/REIT",
    "Dream Industrial REIT": "캐나다/REIT",
    "Colliers": "캐나다/부동산서비스",
}

CANADA_HIGH_DIVIDEND_TICKERS = {
    "RY.TO",
    "TD.TO",
    "BNS.TO",
    "BMO.TO",
    "CM.TO",
    "NA.TO",
    "LB.TO",
    "ENB.TO",
    "TRP.TO",
    "PPL.TO",
    "KEY.TO",
    "GEI.TO",
    "BCE.TO",
    "T.TO",
    "MFC.TO",
    "SLF.TO",
    "GWO.TO",
    "IAG.TO",
    "POW.TO",
    "FTS.TO",
    "H.TO",
    "AQN.TO",
    "EMA.TO",
    "CU.TO",
    "CPX.TO",
    "NPI.TO",
    "BEP-UN.TO",
    "BIP-UN.TO",
    "CAR-UN.TO",
    "REI-UN.TO",
    "SRU-UN.TO",
    "GRT-UN.TO",
    "HR-UN.TO",
    "DIR-UN.TO",
    "FRU.TO",
    "VET.TO",
    "WCP.TO",
}

CANADA_LOW_DIVIDEND_TICKERS = {
    "VFV.TO",
    "SHOP.TO",
    "CSU.TO",
    "DOL.TO",
    "ATD.TO",
    "WCN.TO",
    "CNR.TO",
    "CP.TO",
    "GIB-A.TO",
    "CCO.TO",
    "FFH.TO",
    "GSY.TO",
    "AC.TO",
    "BBD-B.TO",
    "WSP.TO",
    "STN.TO",
    "CIGI.TO",
}

US_TOP100_STOCKS = {
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "NVIDIA": "NVDA",
    "Amazon": "AMZN",
    "Alphabet A": "GOOGL",
    "Meta Platforms": "META",
    "Tesla": "TSLA",
    "Broadcom": "AVGO",
    "Berkshire Hathaway": "BRK-B",
    "JPMorgan Chase": "JPM",
    "Visa": "V",
    "Mastercard": "MA",
    "Eli Lilly": "LLY",
    "UnitedHealth": "UNH",
    "Walmart": "WMT",
    "Costco": "COST",
    "Netflix": "NFLX",
    "Oracle": "ORCL",
    "Adobe": "ADBE",
    "Salesforce": "CRM",
    "AMD": "AMD",
    "Intel": "INTC",
    "Qualcomm": "QCOM",
    "Micron": "MU",
    "Texas Instruments": "TXN",
    "Applied Materials": "AMAT",
    "Lam Research": "LRCX",
    "ASML": "ASML",
    "Taiwan Semi": "TSM",
    "Super Micro Computer": "SMCI",
    "Palantir": "PLTR",
    "Arm": "ARM",
    "CrowdStrike": "CRWD",
    "ServiceNow": "NOW",
    "Snowflake": "SNOW",
    "Shopify US": "SHOP",
    "Uber": "UBER",
    "Airbnb": "ABNB",
    "DoorDash": "DASH",
    "Coinbase": "COIN",
    "Robinhood": "HOOD",
    "Block": "XYZ",
    "PayPal": "PYPL",
    "SoFi": "SOFI",
    "Affirm": "AFRM",
    "Disney": "DIS",
    "Nike": "NKE",
    "Starbucks": "SBUX",
    "McDonald's": "MCD",
    "Coca-Cola": "KO",
    "PepsiCo": "PEP",
    "Procter & Gamble": "PG",
    "Johnson & Johnson": "JNJ",
    "Merck": "MRK",
    "Pfizer": "PFE",
    "AbbVie": "ABBV",
    "Amgen": "AMGN",
    "Gilead": "GILD",
    "Moderna": "MRNA",
    "Intuitive Surgical": "ISRG",
    "GE Vernova": "GEV",
    "GE Aerospace": "GE",
    "Caterpillar": "CAT",
    "Deere": "DE",
    "Boeing": "BA",
    "Lockheed Martin": "LMT",
    "RTX": "RTX",
    "Northrop Grumman": "NOC",
    "Honeywell": "HON",
    "3M": "MMM",
    "Ford": "F",
    "General Motors": "GM",
    "Rivian": "RIVN",
    "Lucid": "LCID",
    "NIO": "NIO",
    "Exxon Mobil": "XOM",
    "Chevron": "CVX",
    "ConocoPhillips": "COP",
    "Occidental": "OXY",
    "Schlumberger": "SLB",
    "Halliburton": "HAL",
    "NextEra Energy": "NEE",
    "Duke Energy": "DUK",
    "Southern": "SO",
    "American Electric Power": "AEP",
    "Freeport-McMoRan": "FCX",
    "Nucor": "NUE",
    "Steel Dynamics": "STLD",
    "Alcoa": "AA",
    "Cleveland-Cliffs": "CLF",
    "Newmont": "NEM",
    "Barrick Gold": "GOLD",
    "Bank of America": "BAC",
    "Wells Fargo": "WFC",
    "Goldman Sachs": "GS",
    "Morgan Stanley": "MS",
    "Charles Schwab": "SCHW",
    "Citigroup": "C",
    "BlackRock": "BLK",
    "Nasdaq": "NDAQ",
}

US_WIRE_STOCKS = {
    "Atkore": "ATKR",
    "Encore Wire": "WIRE",
    "Hubbell": "HUBB",
    "nVent Electric": "NVT",
    "Powell Industries": "POWL",
    "American Superconductor": "AMSC",
}

US_TOP100_SECTOR_MAP = {
    "Apple": "미장/빅테크",
    "Microsoft": "미장/빅테크",
    "NVIDIA": "미장/AI반도체",
    "Amazon": "미장/이커머스",
    "Alphabet A": "미장/인터넷",
    "Meta Platforms": "미장/인터넷",
    "Tesla": "미장/전기차",
    "Broadcom": "미장/반도체",
    "Berkshire Hathaway": "미장/지주",
    "JPMorgan Chase": "미장/금융",
    "Visa": "미장/결제",
    "Mastercard": "미장/결제",
    "Eli Lilly": "미장/제약",
    "UnitedHealth": "미장/헬스케어",
    "Walmart": "미장/소매",
    "Costco": "미장/소매",
    "Netflix": "미장/콘텐츠",
    "Oracle": "미장/소프트웨어",
    "Adobe": "미장/소프트웨어",
    "Salesforce": "미장/소프트웨어",
    "AMD": "미장/반도체",
    "Intel": "미장/반도체",
    "Qualcomm": "미장/반도체",
    "Micron": "미장/메모리",
    "Texas Instruments": "미장/반도체",
    "Applied Materials": "미장/반도체장비",
    "Lam Research": "미장/반도체장비",
    "ASML": "미장/반도체장비",
    "Taiwan Semi": "미장/파운드리",
    "Super Micro Computer": "미장/AI서버",
    "Palantir": "미장/AI소프트웨어",
    "Arm": "미장/반도체설계",
    "CrowdStrike": "미장/보안",
    "ServiceNow": "미장/클라우드",
    "Snowflake": "미장/데이터",
    "Shopify US": "미장/이커머스",
    "Uber": "미장/모빌리티",
    "Airbnb": "미장/여행",
    "DoorDash": "미장/플랫폼",
    "Coinbase": "미장/가상자산",
    "Robinhood": "미장/증권",
    "Block": "미장/핀테크",
    "PayPal": "미장/핀테크",
    "SoFi": "미장/핀테크",
    "Affirm": "미장/핀테크",
    "Disney": "미장/콘텐츠",
    "Nike": "미장/소비재",
    "Starbucks": "미장/외식",
    "McDonald's": "미장/외식",
    "Coca-Cola": "미장/필수소비재",
    "PepsiCo": "미장/필수소비재",
    "Procter & Gamble": "미장/필수소비재",
    "Johnson & Johnson": "미장/헬스케어",
    "Merck": "미장/제약",
    "Pfizer": "미장/제약",
    "AbbVie": "미장/제약",
    "Amgen": "미장/바이오",
    "Gilead": "미장/바이오",
    "Moderna": "미장/바이오",
    "Intuitive Surgical": "미장/의료장비",
    "GE Vernova": "미장/전력에너지",
    "GE Aerospace": "미장/항공",
    "Caterpillar": "미장/산업재",
    "Deere": "미장/기계",
    "Boeing": "미장/항공",
    "Lockheed Martin": "미장/방산",
    "RTX": "미장/방산",
    "Northrop Grumman": "미장/방산",
    "Honeywell": "미장/산업재",
    "3M": "미장/산업재",
    "Ford": "미장/자동차",
    "General Motors": "미장/자동차",
    "Rivian": "미장/전기차",
    "Lucid": "미장/전기차",
    "NIO": "미장/전기차",
    "Exxon Mobil": "미장/에너지",
    "Chevron": "미장/에너지",
    "ConocoPhillips": "미장/에너지",
    "Occidental": "미장/에너지",
    "Schlumberger": "미장/에너지장비",
    "Halliburton": "미장/에너지장비",
    "NextEra Energy": "미장/전력에너지",
    "Duke Energy": "미장/전력",
    "Southern": "미장/전력",
    "American Electric Power": "미장/전력",
    "Freeport-McMoRan": "미장/구리",
    "Nucor": "미장/철강",
    "Steel Dynamics": "미장/철강",
    "Alcoa": "미장/알루미늄",
    "Cleveland-Cliffs": "미장/철강",
    "Newmont": "미장/금",
    "Barrick Gold": "미장/금",
    "Bank of America": "미장/금융",
    "Wells Fargo": "미장/금융",
    "Goldman Sachs": "미장/증권",
    "Morgan Stanley": "미장/증권",
    "Charles Schwab": "미장/증권",
    "Citigroup": "미장/금융",
    "BlackRock": "미장/자산운용",
    "Nasdaq": "미장/거래소",
}

US_WIRE_SECTOR_MAP = {
    "Atkore": "미장/전선",
    "Encore Wire": "미장/전선",
    "Hubbell": "미장/전선",
    "nVent Electric": "미장/전선",
    "Powell Industries": "미장/전선",
    "American Superconductor": "미장/전선",
}

KOREA_SPACE_AEROSPACE_STOCKS = {
    "스피어": "347700.KQ",
    "켄코아에어로스페이스": "274090.KQ",
    "제노코": "361390.KQ",
    "컨텍": "451760.KQ",
    "아스트": "067390.KQ",
    "하이즈항공": "221840.KQ",
    "휴니드": "005870.KS",
}

KOREA_SPACE_AEROSPACE_SECTOR_MAP = {
    "스피어": "우주항공/AI",
    "켄코아에어로스페이스": "우주항공/항공부품",
    "제노코": "우주항공/위성통신",
    "컨텍": "우주항공/위성데이터",
    "아스트": "항공기부품",
    "하이즈항공": "항공기부품",
    "휴니드": "방산/항공전자",
}

US_SPACE_AEROSPACE_STOCKS = {
    "Rocket Lab": "RKLB",
    "AST SpaceMobile": "ASTS",
    "Planet Labs": "PL",
    "Intuitive Machines": "LUNR",
    "Redwire": "RDW",
    "AeroVironment": "AVAV",
    "Kratos Defense": "KTOS",
    "Joby Aviation": "JOBY",
    "Archer Aviation": "ACHR",
    "Textron": "TXT",
}

US_SPACE_AEROSPACE_SECTOR_MAP = {
    "Rocket Lab": "미장/로켓/우주",
    "AST SpaceMobile": "미장/우주통신",
    "Planet Labs": "미장/위성데이터",
    "Intuitive Machines": "미장/달탐사/우주",
    "Redwire": "미장/우주인프라",
    "AeroVironment": "미장/드론/방산",
    "Kratos Defense": "미장/방산/우주",
    "Joby Aviation": "미장/eVTOL항공",
    "Archer Aviation": "미장/eVTOL항공",
    "Textron": "미장/항공/방산",
}

STRATEGIC_SECTOR_FILL_STOCKS = {
    "퍼스텍": "010820.KS",
    "빅텍": "065450.KQ",
    "스페코": "013810.KQ",
    "웨이브일렉트로": "095270.KQ",
    "제룡산업": "147830.KQ",
    "피앤씨테크": "237750.KQ",
    "삼화전기": "009470.KS",
    "삼화콘덴서": "001820.KS",
    "지엔씨에너지": "119850.KQ",
    "에프에스티": "036810.KQ",
    "HPSP": "403870.KQ",
    "와이씨켐": "112290.KQ",
    "원텍": "336570.KQ",
    "아이센스": "099190.KQ",
    "바텍": "043150.KQ",
    "로보로보": "215100.KQ",
    "클로봇": "466100.KQ",
    "에스피시스템스": "317830.KQ",
    "코닉오토메이션": "391710.KQ",
    "브이원텍": "251630.KQ",
    "제이엘케이": "322510.KQ",
    "뷰웍스": "100120.KQ",
    "씨젠": "096530.KQ",
    "한일단조": "024740.KQ",
    "코츠테크놀로지": "448710.KQ",
    "센서뷰": "321370.KQ",
    "모트렉스": "118990.KQ",
    "파두": "440110.KQ",
    "기가비스": "420770.KQ",
}

STRATEGIC_SECTOR_FILL_MAP = {
    "퍼스텍": "방산/항공",
    "빅텍": "방산",
    "스페코": "방산/풍력",
    "웨이브일렉트로": "방산/통신장비",
    "제룡산업": "전력기기",
    "피앤씨테크": "전력기기",
    "삼화전기": "전력/콘덴서",
    "삼화콘덴서": "전력/콘덴서",
    "지엔씨에너지": "전력/데이터센터",
    "에프에스티": "반도체장비",
    "HPSP": "반도체장비",
    "와이씨켐": "반도체소재",
    "원텍": "의료기기",
    "아이센스": "의료기기",
    "바텍": "의료기기",
    "로보로보": "로봇",
    "클로봇": "로봇/AI",
    "에스피시스템스": "로봇/자동화",
    "코닉오토메이션": "로봇/스마트팩토리",
    "브이원텍": "검사장비/로봇",
    "제이엘케이": "의료AI",
    "뷰웍스": "의료기기",
    "씨젠": "진단/바이오",
    "한일단조": "방산/항공부품",
    "코츠테크놀로지": "방산/전자",
    "센서뷰": "통신장비/방산",
    "모트렉스": "자율주행/전장",
    "파두": "반도체/데이터센터",
    "기가비스": "반도체검사",
}

TIGER_ETF_STOCKS = {
    "TIGER 미국우주테크": "0183J0",
    "TIGER 미국S&P500": "360750.KS",
    "TIGER 미국나스닥100": "133690.KS",
    "TIGER 미국테크TOP10 INDXX": "381170.KS",
    "TIGER 미국필라델피아반도체나스닥": "381180.KS",
    "TIGER 미국AI빅테크10": "490090.KS",
    "TIGER 미국배당다우존스": "458730.KS",
    "TIGER 미국테크TOP10타겟커버드콜": "474220.KS",
    "TIGER 2차전지TOP10": "364980.KS",
    "TIGER 반도체TOP10": "396500.KS",
}

TIGER_ETF_SECTOR_MAP = {
    "TIGER 미국우주테크": "국장/TIGER ETF/미국우주",
    "TIGER 미국S&P500": "국장/TIGER ETF/미국지수",
    "TIGER 미국나스닥100": "국장/TIGER ETF/미국지수",
    "TIGER 미국테크TOP10 INDXX": "국장/TIGER ETF/미국빅테크",
    "TIGER 미국필라델피아반도체나스닥": "국장/TIGER ETF/미국반도체",
    "TIGER 미국AI빅테크10": "국장/TIGER ETF/미국AI",
    "TIGER 미국배당다우존스": "국장/TIGER ETF/미국배당",
    "TIGER 미국테크TOP10타겟커버드콜": "국장/TIGER ETF/커버드콜",
    "TIGER 2차전지TOP10": "국장/TIGER ETF/2차전지",
    "TIGER 반도체TOP10": "국장/TIGER ETF/국내반도체",
}

REDUCED_FOR_TIGER_ETF_TICKERS = {
    "263750.KQ",
    "293490.KQ",
    "067160.KQ",
    "376300.KQ",
    "122870.KQ",
    "253450.KQ",
    "041020.KQ",
    "047560.KQ",
    "304100.KQ",
    "402030.KQ",
}

REDUCED_FOR_SPACE_AEROSPACE_TICKERS = {
    "280360.KS",
    "001680.KS",
    "057050.KS",
    "031430.KS",
    "093050.KS",
    "069080.KQ",
    "192080.KS",
    "009240.KS",
    "079430.KS",
    "036420.KS",
}

USER_AVOID_SECTOR_TICKERS = {
    "051900.KS",
    "003230.KS",
    "097950.KS",
    "004370.KS",
    "271560.KS",
    "005180.KS",
    "259960.KS",
    "033780.KS",
    "001040.KS",
    "000680.KS",
    "021240.KS",
    "383220.KS",
    "111770.KS",
    "020000.KS",
    "069960.KS",
    "004170.KS",
    "139480.KS",
    "023530.KS",
    "007310.KS",
    "000080.KS",
    "005300.KS",
    "006040.KS",
    "251270.KS",
    "078340.KQ",
    "112040.KQ",
    "194480.KQ",
    "225570.KQ",
    "036570.KS",
    "095660.KQ",
    "181710.KS",
    "081660.KS",
    "453340.KS",
    "051500.KQ",
    "L.TO",
    "MRU.TO",
    "EMP-A.TO",
    "WN.TO",
    "DOL.TO",
    "CTC-A.TO",
    "QSR.TO",
    "NKE",
    "KO",
    "PEP",
    "PG",
    "WMT",
    "COST",
    "SBUX",
    "MCD",
}

USER_AVOID_SECTOR_KEYWORDS = (
    "패션",
    "소비",
    "게임",
    "음식료",
    "유통",
    "소매",
    "외식",
)

EXCLUDED_TICKERS = {
    "010620.KS",
    "034230.KQ",
    "001570.KS",
    "000275.KS",
    "051810.KQ",
    "MEG.TO",
    "WIRE",
} | REDUCED_FOR_TIGER_ETF_TICKERS | REDUCED_FOR_SPACE_AEROSPACE_TICKERS | USER_AVOID_SECTOR_TICKERS

KOREA_SECTOR_MINIMUM_STOCKS = {
    "인터플렉스": "051370.KQ",
    "파트론": "091700.KQ",
    "KH바텍": "060720.KQ",
    "이수페타시스": "007660.KS",
    "코리아써키트": "007810.KS",
    "세종텔레콤": "036630.KQ",
    "아이즈비전": "031310.KQ",
    "인스코비": "006490.KS",
}

KOREA_SECTOR_MINIMUM_MAP = {
    "한미약품": "의료/제약",
    "유한양행": "의료/제약",
    "종근당": "의료/제약",
    "대웅제약": "의료/제약",
    "보령": "의료/제약",
    "JW중외제약": "의료/제약",
    "HK이노엔": "의료/제약",
    "동국제약": "의료/제약",
    "삼성전기": "전자부품",
    "LG이노텍": "전자부품",
    "비에이치": "전자부품",
    "인터플렉스": "전자부품",
    "파트론": "전자부품",
    "KH바텍": "전자부품",
    "이수페타시스": "전자부품",
    "코리아써키트": "전자부품",
    "SK텔레콤": "통신",
    "KT": "통신",
    "LG유플러스": "통신",
    "세종텔레콤": "통신",
    "아이즈비전": "통신",
    "인스코비": "통신",
}

REQUIRED_KOREA_STOCK_NAMES = {
    "스피어",
    "대우건설",
    "LS",
    "LS에코에너지",
    "LS마린솔루션",
    "대한전선",
    "가온전선",
    "일진전기",
    "일진홀딩스",
    "대원전선",
    "KBI메탈",
    "대한광통신",
    "오이솔루션",
    "우리로",
    "코위버",
    "텔레필드",
    "옵티시스",
    "머큐리",
    "한미약품",
    "유한양행",
    "종근당",
    "대웅제약",
    "보령",
    "JW중외제약",
    "HK이노엔",
    "동국제약",
    "삼성전기",
    "LG이노텍",
    "비에이치",
    "인터플렉스",
    "파트론",
    "KH바텍",
    "이수페타시스",
    "코리아써키트",
    "SK텔레콤",
    "KT",
    "LG유플러스",
    "세종텔레콤",
    "아이즈비전",
    "인스코비",
}

DEFAULT_STOCKS.update(KOREA_VALUE_STOCKS)
SECTOR_MAP.update(KOREA_VALUE_SECTOR_MAP)
DEFAULT_STOCKS.update(KOREA_LEADER_STOCKS)
SECTOR_MAP.update(KOREA_LEADER_SECTOR_MAP)
DEFAULT_STOCKS.update(KOREA_THEME_STOCKS)
SECTOR_MAP.update(KOREA_THEME_SECTOR_MAP)
DEFAULT_STOCKS.update(CANADA_DEFAULT_STOCKS)
SECTOR_MAP.update(CANADA_SECTOR_MAP)
DEFAULT_STOCKS.update(CANADA_EXPANDED_STOCKS)
SECTOR_MAP.update(CANADA_EXPANDED_SECTOR_MAP)
DEFAULT_STOCKS.update(US_TOP100_STOCKS)
SECTOR_MAP.update(US_TOP100_SECTOR_MAP)
DEFAULT_STOCKS.update(US_WIRE_STOCKS)
SECTOR_MAP.update(US_WIRE_SECTOR_MAP)
DEFAULT_STOCKS.update(KOREA_SPACE_AEROSPACE_STOCKS)
SECTOR_MAP.update(KOREA_SPACE_AEROSPACE_SECTOR_MAP)
DEFAULT_STOCKS.update(US_SPACE_AEROSPACE_STOCKS)
SECTOR_MAP.update(US_SPACE_AEROSPACE_SECTOR_MAP)
DEFAULT_STOCKS.update(STRATEGIC_SECTOR_FILL_STOCKS)
SECTOR_MAP.update(STRATEGIC_SECTOR_FILL_MAP)
DEFAULT_STOCKS.update(TIGER_ETF_STOCKS)
SECTOR_MAP.update(TIGER_ETF_SECTOR_MAP)
DEFAULT_STOCKS.update(KOREA_SECTOR_MINIMUM_STOCKS)
SECTOR_MAP.update(KOREA_SECTOR_MINIMUM_MAP)


def dedupe_stocks_by_ticker(stocks, sector_map):
    clean_stocks = {}
    clean_sector_map = {}
    seen_tickers = set()
    for name, ticker in stocks.items():
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        clean_stocks[name] = ticker
        if name in sector_map:
            clean_sector_map[name] = sector_map[name]
    return clean_stocks, clean_sector_map


def remove_excluded_stocks(stocks, sector_map):
    clean_stocks = {
        name: ticker
        for name, ticker in stocks.items()
        if ticker not in EXCLUDED_TICKERS
        and not any(keyword in sector_map.get(name, "") for keyword in USER_AVOID_SECTOR_KEYWORDS)
    }
    clean_sector_map = {name: sector for name, sector in sector_map.items() if name in clean_stocks}
    return clean_stocks, clean_sector_map


DEFAULT_STOCKS, SECTOR_MAP = remove_excluded_stocks(DEFAULT_STOCKS, SECTOR_MAP)
DEFAULT_STOCKS, SECTOR_MAP = dedupe_stocks_by_ticker(DEFAULT_STOCKS, SECTOR_MAP)

POSITIVE_NEWS_KEYWORDS = {
    "수주": 8,
    "계약": 7,
    "공급": 7,
    "시설투자": 7,
    "설비투자": 7,
    "증설": 6,
    "제3자배정": 5,
    "전략적 투자": 6,
    "성장형 유증": 6,
    "실적": 5,
    "흑자": 8,
    "증가": 4,
    "상승": 3,
    "돌파": 4,
    "승인": 6,
    "특허": 4,
    "투자": 5,
    "확대": 4,
}

NEGATIVE_NEWS_KEYWORDS = {
    "적자": 8,
    "급락": 7,
    "하락": 4,
    "소송": 6,
    "조사": 6,
    "유상증자": 6,
    "전환사채": 8,
    "희석": 8,
    "운영자금": 7,
    "채무상환": 8,
    "차입금": 6,
    "주주배정": 7,
    "리콜": 6,
    "매각": 6,
    "처분": 6,
    "감소": 6,
    "지분율": 4,
    "주식등의 수": 6,
    "순매도": 5,
    "거래정지": 8,
    "경고": 6,
    "중단": 6,
    "지연": 4,
    "부진": 5,
    "악재": 6,
    "쇼크": 9,
    "어닝쇼크": 10,
    "어닝 쇼크": 10,
    "어닝콜 쇼크": 10,
    "실적쇼크": 10,
    "실적 쇼크": 10,
    "컨센서스 하회": 9,
    "전망 하향": 8,
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
    "대상자",
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

SECTOR_NEWS_RISK_KEYWORDS = {
    "건설": "철근 누락 부실시공 하자 안전사고 국토부 제재",
    "건설기계": "수요 둔화 리콜 제재 실적 부진",
    "2차전지": "화재 리콜 수요 둔화 적자 공급과잉",
    "반도체": "어닝콜 쇼크 어닝쇼크 어닝 쇼크 실적쇼크 컨센서스 하회 수출통제 재고 부진 규제 실적",
    "전력": "정책 지연 사고 제재 원가",
    "원전": "정책 지연 사고 규제 수주 취소",
    "의료": "임상 실패 허가 지연 부작용 소송",
    "제약": "임상 실패 허가 지연 부작용 소송",
    "조선": "인도 지연 사고 원가 상승",
    "해운": "운임 하락 물동량 감소 제재",
    "증권": "순매도 부동산PF 충당금 손실",
    "은행": "연체 충당금 부실채권 규제",
    "자동차": "리콜 파업 판매 부진 관세",
    "로봇": "수주 지연 실적 부진 경쟁 심화",
    "통신": "과징금 규제 해킹 장애",
    "전선": "구리 가격 원가 상승 공급 지연",
    "알루미늄": "원가 상승 관세 수요 둔화",
}

SECTOR_NEWS_POSITIVE_KEYWORDS = "수주 계약 공급 승인 실적 흑자 투자 확대 정책"
SECTOR_NEWS_CACHE = {}
COMPANY_RISK_NEWS_CACHE = {}
HIGH_RISK_COMPANY_NEWS_NAMES = {
    "한미반도체",
    "현대건설",
    "삼성전자",
    "SK하이닉스",
    "두산에너빌리티",
    "대우건설",
    "GS건설",
    "HDC현대산업개발",
    "삼성바이오로직스",
    "셀트리온",
}
COMPANY_RISK_NEWS_QUERIES = {
    "현대건설": [
        "현대건설 GTX 삼성역 철근 누락",
        "현대건설 철근 2500개 누락",
        "GTX 삼성역 철근 2500개 누락 현대건설",
        "현대건설 국토부 감사 철근 누락",
    ],
    "대우건설": [
        "대우건설 철근 누락 부실시공",
        "대우건설 하자 안전사고 국토부 제재",
    ],
    "GS건설": [
        "GS건설 철근 누락 부실시공",
        "GS건설 하자 안전사고 국토부 제재",
    ],
    "HDC현대산업개발": [
        "HDC현대산업개발 부실시공 붕괴 안전사고",
        "HDC현대산업개발 국토부 제재 하자",
    ],
    "한미반도체": [
        "한미반도체 어닝콜 쇼크",
        "한미반도체 실적 쇼크 컨센서스 하회",
    ],
}
COMPANY_RISK_CONTEXT_TERMS = {
    "현대건설": ["GTX", "삼성역", "철근", "누락", "국토부", "감사", "부실시공"],
    "대우건설": ["철근", "누락", "부실시공", "하자", "국토부", "제재"],
    "GS건설": ["철근", "누락", "부실시공", "하자", "국토부", "제재"],
    "HDC현대산업개발": ["붕괴", "부실시공", "안전사고", "하자", "국토부", "제재"],
    "한미반도체": ["어닝콜", "어닝쇼크", "실적쇼크", "컨센서스", "하회"],
}
NEWS_COMMON_COMPANY_WORDS = {
    "bank",
    "corp",
    "corporation",
    "company",
    "group",
    "holdings",
    "holding",
    "financial",
    "resources",
    "energy",
    "power",
    "reit",
    "inc",
    "ltd",
    "limited",
    "class",
    "the",
    "of",
    "canada",
    "canadian",
    "national",
}
NEWS_REJECT_TITLE_HINTS = (
    "주주 ",
    "지분율",
    "주식등의 수",
    "임원",
    "내부자",
    "부사장",
    "이사 ",
    "최대주주",
)
NEWS_COMPANY_ALIASES = {
    "Apple": ["애플"],
    "Microsoft": ["마이크로소프트"],
    "Nvidia": ["엔비디아", "엔비디아"],
    "Tesla": ["테슬라"],
    "Amazon": ["아마존"],
    "Meta Platforms": ["메타"],
    "Alphabet": ["알파벳", "구글"],
    "Shopify": ["쇼피파이"],
    "Royal Bank of Canada": ["로열뱅크", "캐나다왕립은행", "RBC"],
    "TD Bank": ["TD은행", "토론토도미니언"],
    "Bank of Nova Scotia": ["노바스코샤은행", "스코샤은행"],
    "Bank of Montreal": ["몬트리올은행", "BMO"],
    "CIBC": ["CIBC"],
    "Magna": ["마그나 인터내셔널", "마그나인터내셔널"],
    "National Bank": ["내셔널뱅크", "캐나다 내셔널은행"],
    "Constellation Software": ["컨스텔레이션 소프트웨어", "컨스텔레이션소프트웨어"],
    "Northland Power": ["노스랜드 파워", "노스랜드파워"],
}


def classify_positive_news(keyword_hits, keyword_weights):
    strong = [key for key in keyword_hits if keyword_weights.get(key, 0) >= 7]
    medium = [key for key in keyword_hits if 5 <= keyword_weights.get(key, 0) < 7]
    weak = [key for key in keyword_hits if keyword_weights.get(key, 0) < 5]

    strong_score = sum(keyword_weights[key] for key in strong)
    medium_score = int(sum(keyword_weights[key] for key in medium) * 0.8)
    weak_score = min(sum(keyword_weights[key] for key in weak), 3) if len(weak) >= 2 or strong or medium else 0

    if strong:
        strength = "strong"
    elif medium:
        strength = "medium"
    elif weak:
        strength = "weak"
    else:
        strength = "none"

    return {
        "score": strong_score + medium_score + weak_score,
        "strength": strength,
        "strong_hits": strong,
        "medium_hits": medium,
        "weak_hits": weak,
    }


def classify_capital_raise_news(title):
    text = clean_news_title(title)
    lowered = text.lower()
    if not any(term in text for term in CAPITAL_RAISE_TERMS):
        return "none", []

    good_hits = [
        term
        for term in CAPITAL_RAISE_GOOD_TERMS
        if (term.lower() in lowered if re.search(r"[A-Za-z]", term) else term in text)
    ]
    bad_hits = [
        term
        for term in CAPITAL_RAISE_BAD_TERMS
        if (term.lower() in lowered if re.search(r"[A-Za-z]", term) else term in text)
    ]

    if good_hits and not bad_hits:
        return "good", good_hits[:3]
    if bad_hits and not good_hits:
        return "bad", bad_hits[:3]
    if good_hits and bad_hits:
        return "mixed", (good_hits[:2] + bad_hits[:2])[:4]
    return "mixed", ["자금조달 목적 확인 필요"]


def clean_news_title(title):
    text = html.unescape(str(title or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+-\s+[가-힣A-Za-z][가-힣A-Za-z\s]{1,29}$", "", text).strip()
    return text


def compact_text_for_match(value):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "", clean_news_title(value)).lower()


def ticker_symbol_for_news(name):
    ticker = str(DEFAULT_STOCKS.get(name, "") or "")
    return ticker.split(".")[0].replace("-", ".").upper()


def company_name_tokens_for_news(name):
    raw_tokens = re.findall(r"[A-Za-z0-9]+", str(name or "").lower())
    tokens = []
    for token in raw_tokens:
        if len(token) < 2 or token in NEWS_COMMON_COMPANY_WORDS:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def is_korean_company_name(name):
    return bool(re.search(r"[가-힣]", str(name or "")))


def is_company_relevant_news_title(name, title, ticker=None, allow_context_terms=None):
    title_text = clean_news_title(title)
    if not title_text or is_noise_news_title(title_text):
        return False

    compact_title = compact_text_for_match(title_text)
    compact_name = compact_text_for_match(name)
    ticker_base = (ticker or ticker_symbol_for_news(name)).replace(".", "").replace("-", "").upper()
    upper_title = title_text.upper()

    if compact_name and compact_name in compact_title:
        return True

    for alias in NEWS_COMPANY_ALIASES.get(str(name or ""), []):
        if compact_text_for_match(alias) in compact_title:
            return True

    if ticker_base and len(ticker_base) >= 2:
        if re.search(rf"\b{re.escape(ticker_base)}\b", upper_title):
            return True
        if f"TSX:{ticker_base}" in upper_title or f"NASDAQ:{ticker_base}" in upper_title or f"NYSE:{ticker_base}" in upper_title:
            return True

    tokens = company_name_tokens_for_news(name)
    if tokens:
        token_hits = sum(1 for token in tokens if re.search(rf"\b{re.escape(token)}\b", title_text, re.IGNORECASE))
        if token_hits >= min(2, len(tokens)):
            return True
        if len(tokens) == 1 and tokens[0] in {"shopify", "dollarama", "cameco", "telus", "enbridge", "bombardier"}:
            if re.search(rf"\b{re.escape(tokens[0])}\b", title_text, re.IGNORECASE):
                return True

    if allow_context_terms and any(term in title_text for term in allow_context_terms):
        return True

    return False


def filter_company_news_headlines(name, headlines, ticker=None, allow_context_terms=None):
    filtered = []
    for title in headlines:
        if is_company_relevant_news_title(name, title, ticker=ticker, allow_context_terms=allow_context_terms):
            filtered.append(title)
    return filtered


def is_noise_news_title(title):
    text = clean_news_title(title)
    if not text:
        return True
    if re.search(r"(LCK|e스포츠|야구|축구|농구|배구|선발|라인업|전날 패배|연패|연승)", text, re.IGNORECASE):
        return True
    if re.search(r"(전공\s*학생|대학생|고등학생|중학생|초등학생|입학|졸업|동아리|윷놀이|축제|체험학습)", text, re.IGNORECASE):
        return True
    if re.search(r"(주가전망|투자분석|돌파임박|한방에|급등주|추천주|목표가\s*얼마)", text, re.IGNORECASE):
        return True
    compact = text.replace(" ", "")
    if "|" in text and re.search(r"(가격|price|chg%|change%)", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"[A-Z.\-]{1,8}\|[^|]{1,80}\|가격:[0-9.,]+.*", compact, re.IGNORECASE):
        return True
    if re.search(r"(가격|price)\s*[:：]\s*[0-9.,]+\s*\|?\s*(chg|change)%?", text, re.IGNORECASE):
        return True
    return False


def summarize_news_one_line(news_summary, headlines):
    summary = str(news_summary or "").strip()
    clean_headlines = [
        clean_news_title(title)
        for title in headlines
        if clean_news_title(title) and not is_noise_news_title(title)
    ]
    headline = clean_headlines[0] if clean_headlines else ""
    headline_text = shorten_news_title_preserving_date(headline)
    if headline and not is_fresh_signal_news_title(headline):
        return f"과거 뉴스 · 판단 제외: {headline_text}"
    if "악재" in summary and headline:
        return f"악재 뉴스: {headline_text}"
    if "호재" in summary and headline:
        return f"호재 뉴스: {headline_text}"
    if headline:
        return f"관련 뉴스: {headline_text}"
    if summary and summary not in {"뉴스 중립", "뉴스 비활성", "뉴스 수집 실패"}:
        return summary[:62]
    return "뚜렷한 뉴스는 없어 가격 흐름만 참고하세요."


def shorten_news_title_preserving_date(headline, max_length=96):
    text = clean_news_title(headline)
    if len(text) <= max_length:
        return text
    date_match = re.search(r"\(20\d{2}-\d{2}-\d{2}\)\s*$", text)
    if not date_match:
        return text[: max_length - 1].rstrip() + "…"
    date_text = date_match.group(0)
    body = text[: date_match.start()].rstrip()
    body_limit = max(18, max_length - len(date_text) - 2)
    return f"{body[:body_limit].rstrip()}… {date_text}"


def parse_google_news_pub_date(value):
    try:
        parsed = parsedate_to_datetime(str(value or "").strip())
    except Exception:
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=pd.Timestamp.now(tz="UTC").tzinfo)
    return parsed


def parse_naver_news_pub_date(value):
    text = clean_news_title(value)
    if not text:
        return None
    now = pd.Timestamp.now(tz=SEOUL_TZ).to_pydatetime()
    if any(word in text for word in ["방금", "분 전", "시간 전"]):
        return now
    day_match = re.search(r"(\d+)\s*일 전", text)
    if day_match:
        return now - timedelta(days=int(day_match.group(1)))
    week_match = re.search(r"(\d+)\s*주 전", text)
    if week_match:
        return now - timedelta(days=int(week_match.group(1)) * 7)
    date_match = re.search(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", text)
    if date_match:
        year, month, day = map(int, date_match.groups())
        return datetime(year, month, day, tzinfo=now.tzinfo)
    short_date_match = re.search(r"(?<!\d)(\d{1,2})[.](\d{1,2})[.](?!\d)", text)
    if short_date_match:
        month, day = map(int, short_date_match.groups())
        candidate = datetime(now.year, month, day, tzinfo=now.tzinfo)
        if candidate > now + timedelta(days=2):
            candidate = datetime(now.year - 1, month, day, tzinfo=now.tzinfo)
        return candidate
    return None


def is_recent_news_datetime(value, max_age_days=None):
    if value is None:
        return False
    max_age_days = NEWS_MAX_AGE_DAYS if max_age_days is None else max_age_days
    cutoff = pd.Timestamp.now(tz="UTC").to_pydatetime() - timedelta(days=max_age_days)
    return value.astimezone(pd.Timestamp.now(tz="UTC").tzinfo) >= cutoff


def extract_news_date_from_title(title):
    text = clean_news_title(title)
    match = re.search(r"\((20\d{2})-(\d{2})-(\d{2})\)\s*$", text)
    if not match:
        return None
    year, month, day = map(int, match.groups())
    return datetime(year, month, day, tzinfo=pd.Timestamp.now(tz=SEOUL_TZ).tzinfo)


def is_fresh_signal_news_title(title, max_age_days=None):
    max_age_days = NEWS_SIGNAL_MAX_AGE_DAYS if max_age_days is None else max_age_days
    published_at = extract_news_date_from_title(title)
    if published_at is None:
        return not NEWS_REQUIRE_DATED_SIGNAL
    cutoff = pd.Timestamp.now(tz=SEOUL_TZ).to_pydatetime() - timedelta(days=max_age_days)
    return published_at >= cutoff


def format_news_title_with_date(title, published_at=None):
    clean = clean_news_title(title)
    if not clean:
        return ""
    if published_at is None:
        return clean
    return f"{clean} ({published_at.astimezone(pd.Timestamp.now(tz=SEOUL_TZ).tzinfo):%Y-%m-%d})"


def secure_file_permissions(path):
    if not path.exists():
        return
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        path.chmod(0o600)
        print(f"보안: {path.name} 권한을 600으로 변경했습니다.", flush=True)


def load_env_file(path):
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


secure_file_permissions(ENV_FILE)
load_env_file(ENV_FILE)

SCAN_PERIOD = os.getenv("MARKET_SCANNER_PERIOD", "3mo").strip()
SCAN_INTERVAL = os.getenv("MARKET_SCANNER_INTERVAL", "1d").strip()
TOP_N = int(os.getenv("MARKET_SCANNER_TOP_N", "10"))
MAX_STOCKS = int(os.getenv("MARKET_SCANNER_MAX_STOCKS", "0"))
MIN_TRADE_VALUE = float(os.getenv("MARKET_SCANNER_MIN_TRADE_VALUE", "1000000000"))
ENABLE_NEWS = os.getenv("MARKET_SCANNER_ENABLE_NEWS", "true").lower() == "true"
NEWS_MAX_AGE_DAYS = int(os.getenv("MARKET_SCANNER_NEWS_MAX_AGE_DAYS", "3"))
NEWS_SIGNAL_MAX_AGE_DAYS = int(os.getenv("MARKET_SCANNER_NEWS_SIGNAL_MAX_AGE_DAYS", "2"))
NEWS_REQUIRE_DATED_SIGNAL = os.getenv("MARKET_SCANNER_NEWS_REQUIRE_DATED_SIGNAL", "true").lower() == "true"
NEWS_ALLOW_STALE_FALLBACK = os.getenv("MARKET_SCANNER_NEWS_ALLOW_STALE_FALLBACK", "false").lower() == "true"
NEWS_ALLOW_UNDATED_NAVER = os.getenv("MARKET_SCANNER_NEWS_ALLOW_UNDATED_NAVER", "false").lower() == "true"
ENABLE_FLOW = os.getenv("MARKET_SCANNER_ENABLE_FLOW", "true").lower() == "true"
TELEGRAM_TOKEN = os.getenv("MARKET_SCANNER_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("MARKET_SCANNER_CHAT_ID", "").strip()
MARKET_RISK_DOWNGRADE_THRESHOLD = int(os.getenv("MARKET_SCANNER_RISK_DOWNGRADE_THRESHOLD", "15"))
MARKET_RISK_BLOCK_THRESHOLD = int(os.getenv("MARKET_SCANNER_RISK_BLOCK_THRESHOLD", "25"))
OVERHEAT_RSI = float(os.getenv("MARKET_SCANNER_OVERHEAT_RSI", "82"))
EXTREME_OVERHEAT_RSI = float(os.getenv("MARKET_SCANNER_EXTREME_OVERHEAT_RSI", "88"))
CHASE_RANGE_POS = float(os.getenv("MARKET_SCANNER_CHASE_RANGE_POS", "92"))
MIN_BUY_VOLUME_RATIO = float(os.getenv("MARKET_SCANNER_MIN_BUY_VOLUME_RATIO", "0.8"))
MIN_BUY_TRADE_VALUE_RATIO = float(os.getenv("MARKET_SCANNER_MIN_BUY_TRADE_VALUE_RATIO", "0.8"))
MAX_WORKERS = max(1, int(os.getenv("MARKET_SCANNER_MAX_WORKERS", "10")))
CACHE_RETENTION_DAYS = max(1, int(os.getenv("MARKET_SCANNER_CACHE_RETENTION_DAYS", "2")))
ENABLE_INTRADAY_1M = os.getenv("MARKET_SCANNER_ENABLE_INTRADAY_1M", "true").lower() not in {
    "0",
    "false",
    "no",
}
INTRADAY_1M_MARKET = os.getenv("MARKET_SCANNER_INTRADAY_1M_MARKET", "국장").strip()
USE_FAST_LATEST_PRICE = os.getenv("MARKET_SCANNER_USE_FAST_LATEST_PRICE", "true").lower() not in {
    "0",
    "false",
    "no",
}
CACHE_CLEANUP_TARGETS = [
    "__pycache__",
    ".pycache_check",
    "context_cache.json",
    "signal_state.json",
    "no_data_symbols.csv",
    "excluded_no_data_symbols.csv",
]


def mask_secret(value, visible=4):
    if not value:
        return "없음"
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}...{value[-visible:]}"


def normalize_ohlcv_dataframe(df):
    if df is None or df.empty:
        return df
    normalized = df.copy()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = normalized.columns.get_level_values(0)
    normalized = normalized.loc[:, ~normalized.columns.duplicated()]
    keep_cols = [col for col in ["Open", "High", "Low", "Close", "Volume"] if col in normalized.columns]
    return normalized[keep_cols].dropna()


def korean_stock_code(ticker):
    clean_ticker = str(ticker or "").strip().upper()
    if clean_ticker.endswith((".KS", ".KQ")):
        return clean_ticker.split(".", 1)[0]
    if re.fullmatch(r"[0-9A-Z]{6}", clean_ticker) and any(char.isdigit() for char in clean_ticker):
        return clean_ticker
    return None


def naver_period_start():
    period = SCAN_PERIOD.lower()
    days = 120
    match = re.fullmatch(r"(\d+)([dwmy])", period)
    if match:
        amount = int(match.group(1))
        unit = match.group(2)
        if unit == "d":
            days = amount
        elif unit == "w":
            days = amount * 7
        elif unit == "m":
            days = amount * 31
        elif unit == "y":
            days = amount * 366
    return (datetime.now() - timedelta(days=days + 10)).strftime("%Y%m%d")


def download_naver_price_data(ticker):
    code = korean_stock_code(ticker)
    if not code or SCAN_INTERVAL != "1d":
        return pd.DataFrame()

    response = requests.get(
        "https://api.finance.naver.com/siseJson.naver",
        params={
            "symbol": code,
            "requestType": "1",
            "startTime": naver_period_start(),
            "endTime": datetime.now().strftime("%Y%m%d"),
            "timeframe": "day",
        },
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=8,
    )
    response.raise_for_status()

    rows = ast.literal_eval(response.text.strip())
    data_rows = [row for row in rows[1:] if isinstance(row, list) and len(row) >= 6]
    if not data_rows:
        return pd.DataFrame()

    df = pd.DataFrame(data_rows, columns=["Date", "Open", "High", "Low", "Close", "Volume", "ForeignRatio"])
    df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d", errors="coerce")
    for column in ["Open", "High", "Low", "Close", "Volume"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")
    df = df.dropna(subset=["Date", "Open", "High", "Low", "Close", "Volume"]).set_index("Date")
    return normalize_ohlcv_dataframe(df)


def latest_naver_quote_price(ticker):
    code = korean_stock_code(ticker)
    if not code:
        return None, None
    last_error = None
    try:
        response = requests.get(
            f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Referer": f"https://finance.naver.com/item/main.naver?code={code}",
            },
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        areas = payload.get("result", {}).get("areas", [])
        for area in areas:
            for item in area.get("datas", []):
                if str(item.get("cd", "")).strip().upper().zfill(6) != code:
                    continue
                price = extract_number(item.get("nv"))
                change_pct = extract_number(item.get("cr"))
                if price and price > 0:
                    return price, change_pct
    except Exception as exc:
        last_error = exc

    try:
        response = requests.get(
            f"https://finance.naver.com/item/sise.naver?code={code}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=5,
        )
        response.raise_for_status()
        response.encoding = "EUC-KR"
        match = re.search(r'class="no_today"[\s\S]{0,500}?<span class="blind">([0-9,]+)</span>', response.text)
        if match:
            price = extract_number(match.group(1))
            if price and price > 0:
                return price, None
    except Exception as exc:
        last_error = exc

    if last_error is not None:
        print(f"{ticker} 네이버 현재가 확인 실패: {sanitize_error(last_error)}", flush=True)
    return None, None


def rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))


def macd(series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df, period=14):
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period).mean()


def download_price_data(ticker):
    if korean_stock_code(ticker):
        try:
            naver_df = download_naver_price_data(ticker)
            if not naver_df.empty:
                return naver_df
        except Exception as exc:
            print(f"{ticker} 네이버 가격 확인 실패: {sanitize_error(exc)}", flush=True)

    with YFINANCE_DOWNLOAD_LOCK:
        df = yf.download(
            ticker,
            period=SCAN_PERIOD,
            interval=SCAN_INTERVAL,
            progress=False,
            threads=False,
        )
    return normalize_ohlcv_dataframe(df)


def download_market_data(ticker):
    with YFINANCE_DOWNLOAD_LOCK:
        df = yf.download(
            ticker,
            period="6mo",
            interval="1d",
            progress=False,
            threads=False,
        )
    return normalize_ohlcv_dataframe(df)


def empty_intraday_context(summary="1분봉 데이터 대기"):
    return {
        "preopen_score": 0,
        "preopen_summary": summary,
        "intraday_1m_score": 0,
        "intraday_1m_trend": "대기",
        "intraday_1m_summary": summary,
    }


def should_fetch_intraday_1m(ticker):
    if not ENABLE_INTRADAY_1M:
        return False
    market_label = market_label_for_ticker(ticker)
    if INTRADAY_1M_MARKET in {"all", "전체", "*"}:
        return True
    return market_label == INTRADAY_1M_MARKET


def download_intraday_1m_data(ticker):
    clean_ticker = str(ticker or "").strip().upper()
    if not clean_ticker:
        return pd.DataFrame()

    with INTRADAY_CACHE_LOCK:
        if clean_ticker in INTRADAY_CACHE:
            return INTRADAY_CACHE[clean_ticker]

    try:
        with YFINANCE_DOWNLOAD_LOCK:
            df = yf.download(
                clean_ticker,
                period="1d",
                interval="1m",
                progress=False,
                threads=False,
                prepost=True,
            )
        normalized = normalize_ohlcv_dataframe(df)
    except Exception as exc:
        print(f"{ticker} 1분봉 확인 실패: {sanitize_error(exc)}", flush=True)
        normalized = pd.DataFrame()

    with INTRADAY_CACHE_LOCK:
        INTRADAY_CACHE[clean_ticker] = normalized
    return normalized


def build_intraday_1m_context(ticker, daily_change_pct=0.0):
    global INTRADAY_SCAN_COUNT
    if not should_fetch_intraday_1m(ticker):
        return empty_intraday_context("")

    INTRADAY_SCAN_COUNT += 1
    df = download_intraday_1m_data(ticker)
    if df is None or df.empty or len(df) < 5:
        return empty_intraday_context("1분봉 데이터 부족")

    close = df["Close"].dropna()
    volume = df["Volume"].fillna(0)
    if len(close) < 5:
        return empty_intraday_context("1분봉 데이터 부족")

    first_price = float(close.iloc[0])
    latest_price = float(close.iloc[-1])
    early_slice = close.head(min(60, len(close)))
    recent_slice = close.tail(min(20, len(close)))
    early_volume = volume.head(min(60, len(volume)))
    recent_volume = volume.tail(min(20, len(volume)))

    early_change = ((float(early_slice.iloc[-1]) / first_price) - 1) * 100 if first_price else 0.0
    intraday_change = ((latest_price / first_price) - 1) * 100 if first_price else 0.0
    recent_change = ((float(recent_slice.iloc[-1]) / float(recent_slice.iloc[0])) - 1) * 100 if float(recent_slice.iloc[0]) else 0.0
    early_avg_volume = float(early_volume.mean()) if len(early_volume) else 0.0
    recent_avg_volume = float(recent_volume.mean()) if len(recent_volume) else 0.0
    volume_pressure = recent_avg_volume / early_avg_volume if early_avg_volume else 1.0

    score = 0
    if intraday_change > 0:
        score += 6
    if recent_change > 0:
        score += 6
    if early_change > 0:
        score += 4
    if volume_pressure >= 1.5 and recent_change > 0:
        score += 8
    if daily_change_pct >= 4 and intraday_change < 0:
        score -= 7
    if recent_change < -0.8:
        score -= 8
    if volume_pressure >= 1.8 and recent_change < 0:
        score -= 8

    if score >= 14:
        trend = "강함"
        summary = f"1분봉 강함 · 장중 {intraday_change:+.2f}% · 최근 {recent_change:+.2f}% · 거래 {volume_pressure:.1f}배"
    elif score >= 5:
        trend = "양호"
        summary = f"1분봉 양호 · 장중 {intraday_change:+.2f}% · 최근 {recent_change:+.2f}%"
    elif score <= -8:
        trend = "위험"
        summary = f"1분봉 약함 · 장중 {intraday_change:+.2f}% · 최근 {recent_change:+.2f}% · 거래 {volume_pressure:.1f}배"
    else:
        trend = "중립"
        summary = f"1분봉 중립 · 장중 {intraday_change:+.2f}% · 최근 {recent_change:+.2f}%"

    if early_change >= 1.0 and volume_pressure >= 1.2:
        preopen_score = 10
        preopen_summary = f"본장 전/초반 1시간 강세 · 초반 {early_change:+.2f}% · 오늘 우호적"
    elif early_change <= -1.0:
        preopen_score = -8
        preopen_summary = f"본장 전/초반 1시간 약세 · 초반 {early_change:+.2f}% · 방어 우선"
    else:
        preopen_score = 0
        preopen_summary = f"본장 전/초반 1시간 중립 · 초반 {early_change:+.2f}%"

    return {
        "preopen_score": int(preopen_score),
        "preopen_summary": preopen_summary,
        "intraday_1m_score": int(score),
        "intraday_1m_trend": trend,
        "intraday_1m_summary": summary,
    }


def cleanup_old_caches():
    cutoff = time_module.time() - (CACHE_RETENTION_DAYS * 86400)
    removed = 0
    for name in CACHE_CLEANUP_TARGETS:
        path = BASE_DIR / name
        if not path.exists():
            continue
        try:
            if path.stat().st_mtime >= cutoff:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed += 1
        except OSError as exc:
            print(f"캐시 정리 건너뜀: {name} ({sanitize_error(exc)})", flush=True)

    price_cache_dir = BASE_DIR / ".price_cache"
    if price_cache_dir.exists():
        for cache_file in price_cache_dir.rglob("*"):
            if not cache_file.is_file():
                continue
            try:
                if cache_file.stat().st_mtime < cutoff:
                    cache_file.unlink()
                    removed += 1
            except OSError as exc:
                print(f"가격 캐시 정리 건너뜀: {cache_file.name} ({sanitize_error(exc)})", flush=True)

        for cache_dir in sorted(
            [item for item in price_cache_dir.rglob("*") if item.is_dir()],
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            try:
                cache_dir.rmdir()
            except OSError:
                pass

    if removed:
        print(f"오래된 캐시 {removed}개 자동 삭제", flush=True)


def market_label_for_ticker(ticker):
    if ticker.endswith((".TO", ".V")):
        return "캐나다"
    clean_ticker = str(ticker or "").strip().upper()
    if re.match(r"^\d{6}(\.KS|\.KQ)?$", clean_ticker):
        return "국장"
    if re.fullmatch(r"[0-9A-Z]{6}", clean_ticker) and any(char.isdigit() for char in clean_ticker):
        return "국장"
    if clean_ticker.endswith((".KS", ".KQ")):
        return "국장"
    return "미장"


def dividend_group_for_ticker(ticker):
    if market_label_for_ticker(ticker) != "캐나다":
        return "해당 없음"
    if ticker in CANADA_HIGH_DIVIDEND_TICKERS:
        return "고배당"
    if ticker in CANADA_LOW_DIVIDEND_TICKERS:
        return "저배당"
    return "중간배당"


def latest_quote_price(ticker):
    if not USE_FAST_LATEST_PRICE:
        return None, "daily_close"

    naver_price, _ = latest_naver_quote_price(ticker)
    if naver_price:
        return naver_price, "naver_realtime"

    try:
        with YFINANCE_DOWNLOAD_LOCK:
            fast_info = yf.Ticker(ticker).fast_info
            for key in ("last_price", "regular_market_price", "lastPrice"):
                value = None
                try:
                    value = fast_info.get(key)
                except (AttributeError, KeyError):
                    value = getattr(fast_info, key, None)
                if value is not None and float(value) > 0:
                    return float(value), "fast_quote"
    except Exception as exc:
        print(f"{ticker} 최신가 확인 실패: {sanitize_error(exc)}", flush=True)
    return None, "daily_close"


def read_fast_info_value(fast_info, keys):
    for key in keys:
        value = None
        try:
            value = fast_info.get(key)
        except (AttributeError, KeyError):
            value = getattr(fast_info, key, None)
        if value is not None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number >= 0:
                return number
    return 0.0


def fetch_dividend_context(ticker):
    if market_label_for_ticker(ticker) != "캐나다":
        return {
            "dividend_group": "해당 없음",
            "dividend_amount": 0.0,
            "dividend_annual_amount": 0.0,
            "dividend_yield_pct": 0.0,
            "last_dividend_date": "",
            "next_dividend_estimate": "",
            "dividend_frequency_days": 0,
            "dividend_summary": "해당 없음",
        }

    group = dividend_group_for_ticker(ticker)
    amount = 0.0
    annual_amount = 0.0
    yield_pct = 0.0
    last_dividend_date = ""
    next_dividend_estimate = ""
    frequency_days = 0
    try:
        with YFINANCE_DOWNLOAD_LOCK:
            ticker_obj = yf.Ticker(ticker)
            fast_info = ticker_obj.fast_info
            amount = read_fast_info_value(
                fast_info,
                ("last_dividend_value", "lastDividendValue", "trailingAnnualDividendRate"),
            )
            yield_value = read_fast_info_value(
                fast_info,
                ("dividend_yield", "dividendYield", "trailingAnnualDividendYield"),
            )
            yield_pct = yield_value * 100 if 0 < yield_value < 1 else yield_value
            dividends = ticker_obj.dividends
            if dividends is not None and not dividends.empty:
                amount = float(dividends.iloc[-1])
                cutoff = dividends.index.max() - pd.Timedelta(days=370)
                annual_amount = float(dividends[dividends.index >= cutoff].sum())
                last_date = pd.Timestamp(dividends.index.max()).date()
                last_dividend_date = last_date.isoformat()
                recent_dates = [pd.Timestamp(value).date() for value in dividends.index[-6:]]
                intervals = [
                    (recent_dates[index] - recent_dates[index - 1]).days
                    for index in range(1, len(recent_dates))
                    if (recent_dates[index] - recent_dates[index - 1]).days > 0
                ]
                if intervals:
                    frequency_days = int(round(float(pd.Series(intervals).median())))
                    if 20 <= frequency_days <= 370:
                        next_dividend_estimate = (last_date + timedelta(days=frequency_days)).isoformat()
    except Exception as exc:
        print(f"{ticker} 배당 확인 실패: {sanitize_error(exc)}", flush=True)

    if annual_amount > 0 and yield_pct <= 0:
        latest_price, _ = latest_quote_price(ticker)
        if latest_price:
            yield_pct = (annual_amount / latest_price) * 100

    if amount > 0 and annual_amount > 0 and yield_pct > 0:
        summary = f"{group} · 최근 {amount:.2f} CAD · 연 {annual_amount:.2f} CAD · 배당률 {yield_pct:.2f}%"
    elif amount > 0 and annual_amount > 0:
        summary = f"{group} · 최근 {amount:.2f} CAD · 연 {annual_amount:.2f} CAD"
    elif amount > 0 and yield_pct > 0:
        summary = f"{group} · 최근 {amount:.2f} CAD · 배당률 {yield_pct:.2f}%"
    elif amount > 0:
        summary = f"{group} · 최근 {amount:.2f} CAD"
    elif yield_pct > 0:
        summary = f"{group} · 배당률 {yield_pct:.2f}%"
    else:
        summary = f"{group} · 배당 정보 없음"
    if last_dividend_date:
        summary += f" · 최근 지급일 {last_dividend_date}"
    if next_dividend_estimate:
        summary += f" · 다음 예상 {next_dividend_estimate}"

    return {
        "dividend_group": group,
        "dividend_amount": round(amount, 4),
        "dividend_annual_amount": round(annual_amount, 4),
        "dividend_yield_pct": round(yield_pct, 2),
        "last_dividend_date": last_dividend_date,
        "next_dividend_estimate": next_dividend_estimate,
        "dividend_frequency_days": frequency_days,
        "dividend_summary": summary,
    }


def is_tiger_etf(name, ticker):
    return str(name or "").startswith("TIGER ") or korean_stock_code(ticker) in {
        korean_stock_code(item) for item in TIGER_ETF_STOCKS.values()
    }


def is_full_service_etf(name, ticker):
    full_service_codes = {
        korean_stock_code(TIGER_ETF_STOCKS[item])
        for item in FULL_SERVICE_ETF_NAMES
        if item in TIGER_ETF_STOCKS
    }
    return str(name or "").strip() in FULL_SERVICE_ETF_NAMES or korean_stock_code(ticker) in full_service_codes


def is_etf_like(name, ticker, sector=""):
    sector_text = str(sector or "").upper()
    name_text = str(name or "").upper()
    ticker_text = str(ticker or "").upper()
    return (
        is_tiger_etf(name, ticker)
        or ticker_text in {"VFV.TO"}
        or "ETF" in sector_text.split("/")
        or bool(re.search(r"\bETF\b", name_text))
    )


def is_lightweight_etf(name, ticker, sector=""):
    return is_etf_like(name, ticker, sector) and not is_full_service_etf(name, ticker)


def lightweight_etf_summary(name=None):
    return "ETF 경량 모드 · TIGER 미국우주테크만 풀분석"


def empty_news_context(summary="뉴스 생략"):
    return {
        "score": 0,
        "risk": 0,
        "strength": "none",
        "strong_hits": [],
        "medium_hits": [],
        "weak_hits": [],
        "negative_hits": [],
        "severe_negative_hits": [],
        "summary": summary,
        "headlines": [],
        "one_line": summary,
        "status": "skipped",
        "source": "skipped",
    }


def empty_flow_context(summary="수급 생략"):
    return {
        "score": 0,
        "risk": 0,
        "summary": summary,
        "foreign_net": 0.0,
        "institution_net": 0.0,
        "status": "skipped",
    }


def empty_etf_now_context(summary="ETF NOW 확인 대기"):
    return {
        "etf_now_source_date": "",
        "etf_now_signal": "",
        "etf_now_return_pct": 0.0,
        "etf_now_buy_price": 0.0,
        "etf_now_buy_date": "",
        "etf_now_summary": summary,
    }


def normalize_etf_now_text(text):
    clean = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.IGNORECASE)
    clean = re.sub(r"<style[\s\S]*?</style>", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = html.unescape(clean).replace("\xa0", " ")
    return re.sub(r"\s+", " ", clean).strip()


def fetch_etf_now_cache():
    global ETF_NOW_CACHE
    with ETF_NOW_CACHE_LOCK:
        if ETF_NOW_CACHE is not None:
            return ETF_NOW_CACHE

        cache = {"source_date": "", "items": {}, "status": "unavailable"}
        try:
            response = requests.get(
                "https://etfnow.tudal.co.kr/",
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                },
                timeout=7,
            )
            response.raise_for_status()
            text = normalize_etf_now_text(response.text)
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})\s*기준", text)
            source_date = date_match.group(1) if date_match else ""
            items = {}
            pattern = re.compile(
                r"(?P<name>[A-Z가-힣0-9&()./+ \-]+?)\s+"
                r"(?P<code>[0-9A-Z]{6})\s+평가율\s+"
                r"(?P<return>[+-]?\d+(?:\.\d+)?)%\s+현재가\s+매수가\s+"
                r"(?P<price>[0-9,]+)원\s+(?P<buy_price>[0-9,]+)원\s+"
                r"매수일\s*:\s*(?P<buy_date>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})",
                re.IGNORECASE,
            )
            for match in pattern.finditer(text):
                code = match.group("code").upper()
                return_pct = extract_number(match.group("return")) or 0.0
                buy_price = extract_number(match.group("buy_price")) or 0.0
                name = match.group("name").strip()
                buy_date = match.group("buy_date")
                signal = "매수 유지" if return_pct >= 0 else "손실 구간"
                summary = (
                    f"ETF NOW {signal} · 평가율 {return_pct:+.2f}% · "
                    f"매수가 {buy_price:,.0f}원 · 매수일 {buy_date[:16]}"
                )
                current = items.get(code)
                if current and current.get("buy_date", "") > buy_date:
                    continue
                items[code] = {
                    "name": name,
                    "source_date": source_date,
                    "signal": signal,
                    "return_pct": round(return_pct, 2),
                    "buy_price": round(buy_price, 2),
                    "buy_date": buy_date,
                    "summary": summary,
                }

            cache = {"source_date": source_date, "items": items, "status": "ok"}
        except Exception as exc:
            print(f"ETF NOW 확인 실패: {sanitize_error(exc)}", flush=True)

        ETF_NOW_CACHE = cache
        return ETF_NOW_CACHE


def fetch_etf_now_context(name, ticker):
    if not is_tiger_etf(name, ticker):
        return empty_etf_now_context("")
    if not is_full_service_etf(name, ticker):
        return empty_etf_now_context(lightweight_etf_summary(name))

    code = korean_stock_code(ticker)
    if not code:
        return empty_etf_now_context("ETF NOW 코드 확인 대기")

    cache = fetch_etf_now_cache()
    source_date = cache.get("source_date", "")
    item = cache.get("items", {}).get(code)
    if not item:
        date_text = f" · {source_date} 기준" if source_date else ""
        return empty_etf_now_context(f"ETF NOW 보유/매수 신호 없음{date_text}")

    return {
        "etf_now_source_date": item.get("source_date", source_date),
        "etf_now_signal": item.get("signal", ""),
        "etf_now_return_pct": item.get("return_pct", 0.0),
        "etf_now_buy_price": item.get("buy_price", 0.0),
        "etf_now_buy_date": item.get("buy_date", ""),
        "etf_now_summary": item.get("summary", ""),
    }


def fetch_etf_nav_context(name, ticker, price):
    if not is_tiger_etf(name, ticker):
        return {
            "etf_nav": 0.0,
            "etf_premium_pct": 0.0,
            "etf_summary": "",
        }

    code = korean_stock_code(ticker)
    nav = 0.0
    if code:
        try:
            response = requests.get(
                f"https://polling.finance.naver.com/api/realtime?query=SERVICE_ITEM:{code}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
            for area in payload.get("result", {}).get("areas", []):
                for item in area.get("datas", []):
                    if str(item.get("cd", "")).strip().upper().zfill(6) != code:
                        continue
                    nav_value = extract_number(item.get("nav"))
                    if nav_value and nav_value > 0:
                        nav = nav_value
                        break
                if nav > 0:
                    break
        except Exception as exc:
            print(f"{ticker} 네이버 ETF NAV 확인 실패: {sanitize_error(exc)}", flush=True)

        try:
            if nav <= 0:
                response = requests.get(
                    f"https://www.k-etf.com/etf/{code}",
                    headers={
                        "User-Agent": "Mozilla/5.0",
                        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                    },
                    timeout=6,
                )
                response.raise_for_status()
                text = response.text.replace("\xa0", " ")
                patterns = [
                    r"NAV[^0-9]{0,80}([0-9,]+(?:\.\d+)?)",
                    r"순자산가치[^0-9]{0,80}([0-9,]+(?:\.\d+)?)",
                ]
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        nav_value = extract_number(match.group(1))
                        if nav_value and nav_value > 0:
                            nav = nav_value
                            break
        except Exception as exc:
            print(f"{ticker} ETF NAV 확인 실패: {sanitize_error(exc)}", flush=True)

    if price and nav and not (price * 0.5 <= nav <= price * 1.5):
        nav = 0.0

    premium_pct = ((price / nav) - 1) * 100 if price and nav else 0.0
    if nav > 0:
        status = "고평가" if premium_pct > 0 else "저평가" if premium_pct < 0 else "정상"
        summary = f"NAV {nav:,.0f}원 · 괴리율 {premium_pct:+.2f}% · {status}"
    else:
        summary = "NAV 확인 대기 · 괴리율 계산 대기"

    return {
        "etf_nav": round(nav, 2),
        "etf_premium_pct": round(premium_pct, 2),
        "etf_summary": summary,
    }


def empty_etf_holdings_context(summary="보유비중 확인 대기"):
    return {
        "etf_holdings_source": "",
        "etf_holdings_source_date": "",
        "etf_holdings_count": 0,
        "etf_holdings_top": "",
        "etf_holdings_weighted_move_pct": 0.0,
        "etf_holdings_summary": summary,
    }


def stockanalysis_holdings_url(ticker):
    clean = str(ticker or "").strip().upper()
    if clean.endswith(".KS") or clean.endswith(".KQ") or korean_stock_code(clean):
        code = korean_stock_code(clean) or clean
        return f"https://stockanalysis.com/quote/krx/{code}/holdings/"
    if clean.endswith(".TO"):
        return f"https://stockanalysis.com/quote/tsx/{clean[:-3]}/holdings/"
    return ""


def parse_weight(value):
    number = extract_number(str(value).replace("%", ""))
    return float(number or 0.0)


def normalize_holding_symbol(symbol):
    raw = str(symbol or "").strip().upper()
    if not raw or raw in {"N/A", "NAN", "-"}:
        return ""
    code_match = re.search(r"\b(\d{6})\b", raw)
    if code_match:
        return code_match.group(1)
    return raw.replace(".", "-")


def fetch_stockanalysis_holdings(ticker):
    url = stockanalysis_holdings_url(ticker)
    if not url:
        return [], "", ""

    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        timeout=8,
    )
    response.raise_for_status()
    text = response.text
    date_match = re.search(r"As of\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})", text)
    source_date = date_match.group(1) if date_match else ""

    holdings = []
    row_pattern = re.compile(
        r"<tr[^>]*>.*?"
        r"<td[^>]*>\s*(?P<no>\d+)\s*</td>.*?"
        r"<td[^>]*>\s*(?:<!---->\s*)?(?:<a[^>]*>)?(?P<symbol>[^<]+)(?:</a>)?.*?</td>.*?"
        r"<td[^>]*>\s*(?P<name>[^<]+?)\s*</td>.*?"
        r"<td[^>]*>\s*(?P<weight>[0-9,.]+%)\s*</td>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in row_pattern.finditer(text):
        symbol = html.unescape(match.group("symbol")).strip()
        name_text = html.unescape(match.group("name")).strip()
        weight = parse_weight(match.group("weight"))
        if not name_text or weight <= 0:
            continue
        holdings.append(
            {
                "symbol": symbol,
                "name": name_text,
                "weight": round(weight, 2),
            }
        )
    return holdings[:25], source_date, url


def fetch_holding_daily_moves(holdings):
    changes = {}
    kr_symbols = []
    yf_symbols = []
    symbol_map = {}
    for item in holdings[:10]:
        symbol = str(item.get("symbol", "")).strip().upper()
        if not symbol or symbol in {"N/A", "NAN"}:
            continue
        clean_symbol = normalize_holding_symbol(symbol)
        if re.fullmatch(r"\d{6}", clean_symbol):
            kr_symbols.append(clean_symbol)
            item["quote_symbol"] = clean_symbol
            continue
        yf_symbol = clean_symbol
        if yf_symbol and re.fullmatch(r"[A-Z0-9.\-]{1,12}", yf_symbol):
            yf_symbols.append(yf_symbol)
            symbol_map[yf_symbol] = symbol

    for symbol in kr_symbols:
        try:
            _, change_pct = latest_naver_quote_price(symbol)
            if change_pct is None:
                df = download_naver_price_data(symbol)
                if df is not None and not df.empty and len(df) >= 2:
                    close = df["Close"].dropna()
                    if len(close) >= 2 and close.iloc[-2]:
                        change_pct = ((float(close.iloc[-1]) / float(close.iloc[-2])) - 1) * 100
            if change_pct is not None:
                changes[symbol] = round(float(change_pct), 2)
        except Exception:
            continue

    if yf_symbols:
        try:
            with YFINANCE_DOWNLOAD_LOCK:
                data = yf.download(
                    yf_symbols,
                    period="5d",
                    interval="1d",
                    progress=False,
                    threads=True,
                    auto_adjust=False,
                )
            if len(yf_symbols) == 1:
                closes = data.get("Close", pd.Series(dtype=float)).dropna()
                if len(closes) >= 2 and closes.iloc[-2]:
                    changes[symbol_map[yf_symbols[0]]] = round(((closes.iloc[-1] / closes.iloc[-2]) - 1) * 100, 2)
            else:
                close_frame = data.get("Close")
                if close_frame is not None:
                    for yf_symbol in yf_symbols:
                        if yf_symbol not in close_frame:
                            continue
                        closes = close_frame[yf_symbol].dropna()
                        if len(closes) >= 2 and closes.iloc[-2]:
                            changes[symbol_map[yf_symbol]] = round(((closes.iloc[-1] / closes.iloc[-2]) - 1) * 100, 2)
        except Exception as exc:
            print(f"ETF 구성종목 등락 확인 실패: {sanitize_error(exc)}", flush=True)
    return changes


def fetch_etf_holdings_context(name, ticker, sector=""):
    if not is_etf_like(name, ticker, sector):
        return empty_etf_holdings_context("")
    if not is_full_service_etf(name, ticker):
        return empty_etf_holdings_context(lightweight_etf_summary(name))

    cache_key = str(ticker or name or "").upper()
    if cache_key in ETF_HOLDINGS_SKIP_TICKERS:
        return empty_etf_holdings_context("보유비중 제외 · 가격/배당만 확인")

    with ETF_HOLDINGS_CACHE_LOCK:
        if cache_key in ETF_HOLDINGS_CACHE:
            return ETF_HOLDINGS_CACHE[cache_key]

    try:
        if str(name or "").strip() in FULL_SERVICE_ETF_PROXY_HOLDINGS:
            holdings = FULL_SERVICE_ETF_PROXY_HOLDINGS[str(name or "").strip()]
            source_date = pd.Timestamp.now(tz=SEOUL_TZ).strftime("%Y-%m-%d")
            source_url = "theme_proxy:space_aerospace"
        else:
            holdings, source_date, source_url = fetch_stockanalysis_holdings(ticker)
        if not holdings:
            context = empty_etf_holdings_context("보유비중 확인 대기 · 구성종목 데이터 없음")
        else:
            changes = fetch_holding_daily_moves(holdings)
            lines = []
            weighted_move = 0.0
            for item in holdings[:10]:
                symbol = str(item.get("symbol", "")).strip()
                name_text = str(item.get("name", "")).strip()
                weight = float(item.get("weight", 0.0) or 0.0)
                quote_symbol = item.get("quote_symbol") or symbol.upper()
                change = changes.get(str(quote_symbol).upper()) or changes.get(symbol.upper())
                if change is None:
                    change_text = "당일 등락 확인중"
                    contribution_text = "기여 계산 대기"
                else:
                    contribution = weight * change / 100
                    weighted_move += contribution
                    change_text = f"당일 {change:+.2f}%"
                    contribution_text = f"기여 {contribution:+.2f}%p"
                label = symbol if symbol and symbol.upper() != "N/A" else name_text
                lines.append(f"{label} {weight:.2f}% · {change_text} · {contribution_text}")
            date_text = f" · {source_date} 기준" if source_date else ""
            proxy_text = "대표 우주테크 구성 흐름" if str(source_url).startswith("theme_proxy:") else f"상위 {min(len(lines), 10)}개 보유비중"
            summary = f"{proxy_text}{date_text} · 가중 등락 {weighted_move:+.2f}%p"
            context = {
                "etf_holdings_source": source_url,
                "etf_holdings_source_date": source_date,
                "etf_holdings_count": len(holdings),
                "etf_holdings_top": " | ".join(lines),
                "etf_holdings_weighted_move_pct": float(round(weighted_move, 2)),
                "etf_holdings_summary": summary,
            }
    except Exception as exc:
        print(f"{ticker} ETF 보유비중 확인 실패: {sanitize_error(exc)}", flush=True)
        context = empty_etf_holdings_context("보유비중 확인 실패 · 다음 갱신 때 재시도")

    with ETF_HOLDINGS_CACHE_LOCK:
        ETF_HOLDINGS_CACHE[cache_key] = context
    return context


def apply_latest_price(ticker, price, prev_close, open_price):
    latest_price, source = latest_quote_price(ticker)
    if latest_price is None:
        return price, source, 0.0
    drift_pct = ((latest_price / price) - 1) * 100 if price else 0.0
    return latest_price, source, drift_pct


def latest_change_pct(ticker, price, prev_close, price_source):
    if price_source == "naver_realtime":
        return ((price / prev_close) - 1) * 100 if prev_close else 0.0, "naver_realtime_calculated"
    return ((price / prev_close) - 1) * 100 if prev_close else 0.0, "calculated"


def analyze_market_trend(name, ticker):
    df = download_market_data(ticker)
    if df is None or df.empty or len(df) < 60:
        return {
            "name": name,
            "status": "no_data",
            "trend": "unknown",
            "score_adjust": 0,
            "risk": 0,
            "summary": f"{name} 확인 실패",
            "change_pct": 0.0,
        }

    close = df["Close"].dropna()
    price = float(close.iloc[-1])
    prev = float(close.iloc[-2])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    ma20_prev = float(close.rolling(20).mean().iloc[-2])
    change_pct = ((price / prev) - 1) * 100 if prev else 0

    if name == "VIX":
        if price >= 25:
            return {
                "name": name,
                "status": "ok",
                "trend": "risk_off",
                "score_adjust": -10,
                "risk": 15,
                "summary": f"VIX 고위험({price:.1f})",
                "change_pct": round(change_pct, 2),
            }
        if price >= 20:
            return {
                "name": name,
                "status": "ok",
                "trend": "caution",
                "score_adjust": -5,
                "risk": 8,
                "summary": f"VIX 경계({price:.1f})",
                "change_pct": round(change_pct, 2),
            }
        return {
            "name": name,
            "status": "ok",
            "trend": "normal",
            "score_adjust": 3,
            "risk": 0,
            "summary": f"VIX 안정({price:.1f})",
            "change_pct": round(change_pct, 2),
        }

    if name == "US10Y":
        if price >= 4.8 and ma20 > ma20_prev:
            return {
                "name": name,
                "status": "ok",
                "trend": "risk_off",
                "score_adjust": -8,
                "risk": 12,
                "summary": f"미국 10년물 금리 부담({price:.2f})",
                "change_pct": round(change_pct, 2),
            }
        if price >= 4.4 and ma20 > ma20_prev:
            return {
                "name": name,
                "status": "ok",
                "trend": "caution",
                "score_adjust": -4,
                "risk": 6,
                "summary": f"금리 상승 경계({price:.2f})",
                "change_pct": round(change_pct, 2),
            }
        return {
            "name": name,
            "status": "ok",
            "trend": "normal",
            "score_adjust": 0,
            "risk": 0,
            "summary": f"금리 부담 제한({price:.2f})",
            "change_pct": round(change_pct, 2),
        }

    if price > ma20 > ma60 and ma20 > ma20_prev:
        return {
            "name": name,
            "status": "ok",
            "trend": "bull",
            "score_adjust": 8,
            "risk": 0,
            "summary": f"{name} 상승 추세({change_pct:.2f}%)",
            "change_pct": round(change_pct, 2),
        }
    if price < ma20 and ma20 < ma60:
        return {
            "name": name,
            "status": "ok",
            "trend": "bear",
            "score_adjust": -10,
            "risk": 10,
            "summary": f"{name} 하락 추세({change_pct:.2f}%)",
            "change_pct": round(change_pct, 2),
        }
    if price < ma20:
        return {
            "name": name,
            "status": "ok",
            "trend": "caution",
            "score_adjust": -5,
            "risk": 5,
            "summary": f"{name} 20일선 아래({change_pct:.2f}%)",
            "change_pct": round(change_pct, 2),
        }
    return {
        "name": name,
        "status": "ok",
        "trend": "neutral",
        "score_adjust": 0,
        "risk": 2,
        "summary": f"{name} 중립({change_pct:.2f}%)",
        "change_pct": round(change_pct, 2),
    }


def get_market_context():
    details = [analyze_market_trend(name, ticker) for name, ticker in MARKET_INDEXES.items()]
    risk = sum(item["risk"] for item in details)
    score_adjust = sum(item["score_adjust"] for item in details)
    risk_off_count = sum(1 for item in details if item["trend"] in {"bear", "risk_off"})
    bull_count = sum(1 for item in details if item["trend"] == "bull")

    if risk >= MARKET_RISK_BLOCK_THRESHOLD or risk_off_count >= 2:
        regime = "하락장/Risk-Off"
        mode = "risk_off"
    elif risk >= MARKET_RISK_DOWNGRADE_THRESHOLD:
        regime = "경계장"
        mode = "caution"
    elif bull_count >= 2 and risk < 10:
        regime = "상승장"
        mode = "bull"
    else:
        regime = "중립장"
        mode = "neutral"

    return {
        "mode": mode,
        "regime": regime,
        "risk": int(risk),
        "score_adjust": int(score_adjust),
        "details": details,
        "summary": " / ".join(item["summary"] for item in details),
    }


def get_numeric_code(ticker):
    code = ticker.split(".")[0].strip()
    return code.zfill(6) if code.isdigit() else None


def extract_number(raw_value):
    if raw_value is None:
        return None
    cleaned = str(raw_value).replace(",", "").replace("+", "").replace("\xa0", "").strip()
    if not cleaned or cleaned in {"-", "N/A"}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def flatten_table_columns(table):
    flattened = table.copy()
    if isinstance(flattened.columns, pd.MultiIndex):
        flattened.columns = [
            " ".join(str(part) for part in column if str(part) != "nan").strip()
            for column in flattened.columns
        ]
    else:
        flattened.columns = [str(column).strip() for column in flattened.columns]
    return flattened


def fetch_flow_context(ticker, lookback=5):
    if not ENABLE_FLOW:
        return {"score": 0, "risk": 0, "summary": "수급 비활성", "status": "disabled"}

    numeric_code = get_numeric_code(ticker)
    if not numeric_code:
        return {"score": 0, "risk": 0, "summary": "수급 확인 불가", "status": "no_code"}

    url = f"https://finance.naver.com/item/frgn.naver?code={numeric_code}"
    try:
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        response.raise_for_status()
        tables = [flatten_table_columns(table) for table in pd.read_html(StringIO(response.text))]
    except Exception:
        return {"score": 0, "risk": 0, "summary": "수급 수집 실패", "status": "unavailable"}

    target = None
    for table in tables:
        columns = [str(col) for col in table.columns]
        if any("외국인" in col for col in columns) and any("기관" in col for col in columns):
            target = table.dropna(how="all").copy()
            break

    if target is None:
        return {"score": 0, "risk": 0, "summary": "수급 없음", "status": "unavailable"}

    foreign_col = next((col for col in target.columns if "외국인" in str(col) and "순매매" in str(col)), None)
    institution_col = next((col for col in target.columns if "기관" in str(col) and "순매매" in str(col)), None)
    foreign_col = foreign_col or next((col for col in target.columns if "외국인" in str(col)), None)
    institution_col = institution_col or next((col for col in target.columns if "기관" in str(col)), None)
    if foreign_col is None or institution_col is None:
        return {"score": 0, "risk": 0, "summary": "수급 없음", "status": "unavailable"}

    sample = target.head(lookback).copy()
    foreign_net = sample[foreign_col].map(extract_number).fillna(0).sum()
    institution_net = sample[institution_col].map(extract_number).fillna(0).sum()

    score = 0
    risk = 0
    reasons = []
    if foreign_net > 0:
        score += 15
        reasons.append("외국인 순매수")
    elif foreign_net < 0:
        risk += 8
        reasons.append("외국인 순매도")
    if institution_net > 0:
        score += 12
        reasons.append("기관 순매수")
    elif institution_net < 0:
        risk += 6
        reasons.append("기관 순매도")
    if foreign_net > 0 and institution_net > 0:
        score += 8
        reasons.append("외국인+기관 동반 매수")

    return {
        "score": score,
        "risk": risk,
        "summary": ", ".join(reasons) if reasons else "수급 중립",
        "foreign_net": float(foreign_net),
        "institution_net": float(institution_net),
        "status": "ok",
    }


def score_news_headlines(headlines):
    score = 0
    risk = 0
    positive_hits = []
    negative_hits = []
    severe_negative_hits = []
    capital_raise_notes = []
    for title in headlines[:8]:
        if not is_fresh_signal_news_title(title):
            continue
        capital_raise_type, capital_raise_hits = classify_capital_raise_news(title)
        for keyword, weight in POSITIVE_NEWS_KEYWORDS.items():
            if keyword in title:
                positive_hits.append(keyword)
        for keyword, weight in NEGATIVE_NEWS_KEYWORDS.items():
            if keyword == "유상증자" and capital_raise_type == "good":
                continue
            if keyword in title:
                risk += weight
                negative_hits.append(keyword)
                if weight >= 10:
                    severe_negative_hits.append(keyword)
        if capital_raise_type == "good":
            positive_hits.append("성장형 유증")
            score += 6
            capital_raise_notes.append("성장형 유증: " + ", ".join(capital_raise_hits))
        elif capital_raise_type == "bad":
            risk += 8
            negative_hits.append("부담형 유증")
            capital_raise_notes.append("부담형 유증: " + ", ".join(capital_raise_hits))
        elif capital_raise_type == "mixed":
            risk += 4
            score += 2
            negative_hits.append("유증 확인 필요")
            capital_raise_notes.append("유증 목적 확인 필요: " + ", ".join(capital_raise_hits))

    positive_hits = list(dict.fromkeys(positive_hits))
    negative_hits = list(dict.fromkeys(negative_hits))
    severe_negative_hits = list(dict.fromkeys(severe_negative_hits))
    if severe_negative_hits:
        positive_hits = []
    elif risk >= 8 and risk >= score:
        positive_hits = [hit for hit in positive_hits if POSITIVE_NEWS_KEYWORDS.get(hit, 0) >= 7]
    positive = classify_positive_news(positive_hits, POSITIVE_NEWS_KEYWORDS)

    summary_parts = []
    if positive["strong_hits"]:
        summary_parts.append("강한 호재: " + ", ".join(positive["strong_hits"][:3]))
    if positive["medium_hits"]:
        summary_parts.append("보통 호재: " + ", ".join(positive["medium_hits"][:3]))
    if positive["weak_hits"]:
        summary_parts.append("약한 호재: " + ", ".join(positive["weak_hits"][:3]))
    if severe_negative_hits:
        summary_parts.append("중대 악재: " + ", ".join(severe_negative_hits[:3]))
    elif negative_hits:
        summary_parts.append("악재: " + ", ".join(negative_hits[:3]))
    if capital_raise_notes:
        summary_parts.append(capital_raise_notes[0])

    return {
        "score": min(positive["score"] + score, 20),
        "risk": min(risk, 30),
        "strength": positive["strength"],
        "strong_hits": positive["strong_hits"],
        "medium_hits": positive["medium_hits"],
        "weak_hits": positive["weak_hits"],
        "negative_hits": negative_hits,
        "severe_negative_hits": severe_negative_hits,
        "summary": " / ".join(summary_parts) if summary_parts else "뉴스 중립",
    }


def fetch_google_news_headlines_for_query(query, limit=5):
    recency_query = f"{query} when:{NEWS_MAX_AGE_DAYS}d"
    url = f"https://news.google.com/rss/search?q={quote(recency_query)}&hl=ko&gl=KR&ceid=KR:ko"
    items = []
    response = requests.get(url, timeout=8)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    for item in root.findall("./channel/item")[: max(limit * 3, 10)]:
        title = clean_news_title(item.findtext("title", default="").strip())
        published_at = parse_google_news_pub_date(item.findtext("pubDate", default="").strip())
        if not title:
            continue
        if published_at and is_recent_news_datetime(published_at):
            items.append((published_at, format_news_title_with_date(title, published_at)))
        elif NEWS_ALLOW_STALE_FALLBACK:
            items.append((published_at or datetime.min.replace(tzinfo=pd.Timestamp.now(tz="UTC").tzinfo), title))
    items.sort(key=lambda pair: pair[0], reverse=True)
    headlines = [title for _, title in items[:limit]]
    return headlines


def fetch_google_news_headlines(name, sector=None):
    ticker = ticker_symbol_for_news(name)
    market_hint = "TSX" if str(DEFAULT_STOCKS.get(name, "")).endswith(".TO") else "주식"
    query = f'"{name}" {ticker} {market_hint} stock' if ticker and not is_korean_company_name(name) else f'"{name}" 주식'
    headlines = fetch_google_news_headlines_for_query(query, limit=8)
    return filter_company_news_headlines(name, headlines, ticker=ticker)[:5]


def normalize_sector_for_news(sector):
    sector_text = clean_news_title(sector)
    if not sector_text or sector_text == "기타":
        return ""
    return re.split(r"[/·,\s]", sector_text)[0].strip()


def fetch_sector_news_headlines(name, sector):
    base_sector = normalize_sector_for_news(sector)
    if not base_sector:
        return []

    if base_sector in SECTOR_NEWS_CACHE:
        return SECTOR_NEWS_CACHE[base_sector]

    risk_terms = SECTOR_NEWS_RISK_KEYWORDS.get(base_sector, "악재 리스크 실적 부진 규제")
    queries = [f"{base_sector} 관련주 {SECTOR_NEWS_POSITIVE_KEYWORDS} {risk_terms}"]

    headlines = []
    for query in queries:
        try:
            headlines.extend(fetch_google_news_headlines_for_query(query, limit=3))
        except Exception:
            pass
        try:
            headlines.extend(fetch_naver_news_headlines_for_query(query, limit=3))
        except Exception:
            pass
    SECTOR_NEWS_CACHE[base_sector] = [title for title in dict.fromkeys(headlines) if title][:4]
    return SECTOR_NEWS_CACHE[base_sector]


def fetch_company_risk_news_headlines(name, sector):
    if name not in HIGH_RISK_COMPANY_NEWS_NAMES:
        return []

    base_sector = normalize_sector_for_news(sector)
    risk_terms = SECTOR_NEWS_RISK_KEYWORDS.get(base_sector, "어닝쇼크 실적쇼크 컨센서스 하회 악재 리스크")
    cache_key = f"{name}:{base_sector}:{risk_terms}"
    if cache_key in COMPANY_RISK_NEWS_CACHE:
        return COMPANY_RISK_NEWS_CACHE[cache_key]

    queries = list(COMPANY_RISK_NEWS_QUERIES.get(name, []))
    queries.extend(
        [
            f"{name} {risk_terms}",
            f"{name} 어닝 쇼크 어닝쇼크 실적쇼크 컨센서스 하회 악재",
        ]
    )
    headlines = []
    for query in queries:
        try:
            headlines.extend(fetch_google_news_headlines_for_query(query, limit=4))
        except Exception:
            pass
        try:
            headlines.extend(fetch_naver_news_headlines_for_query(query, limit=4))
        except Exception:
            pass
    context_terms = COMPANY_RISK_CONTEXT_TERMS.get(name, [])
    allow_context_only = name == "현대건설"
    COMPANY_RISK_NEWS_CACHE[cache_key] = filter_company_news_headlines(
        name,
        list(dict.fromkeys(headlines)),
        ticker=ticker_symbol_for_news(name),
        allow_context_terms=context_terms if allow_context_only else None,
    )[:4]
    return COMPANY_RISK_NEWS_CACHE[cache_key]


def fetch_naver_news_headlines_for_query(query, limit=5):
    url = "https://search.naver.com/search.naver"
    response = requests.get(
        url,
        params={"where": "news", "query": query, "sort": "1"},
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=8,
    )
    response.raise_for_status()
    candidates = []
    chunks = re.split(r'(?=<a[^>]+class="[^"]*news_tit)', response.text)
    for chunk in chunks[1:]:
        title_match = re.search(r'class="news_tit"[^>]*title="([^"]+)"', chunk)
        if title_match:
            raw_title = title_match.group(1)
        else:
            link_match = re.search(r'<a[^>]+class="[^"]*news_tit[^"]*"[^>]*>(.*?)</a>', chunk, re.S)
            raw_title = link_match.group(1) if link_match else ""
        title = clean_news_title(raw_title)
        if not title:
            continue
        date_area = clean_news_title(chunk[:1800])
        published_at = parse_naver_news_pub_date(date_area)
        if published_at and is_recent_news_datetime(published_at):
            candidates.append((published_at, format_news_title_with_date(title, published_at)))
        elif NEWS_ALLOW_STALE_FALLBACK or NEWS_ALLOW_UNDATED_NAVER:
            candidates.append((published_at or datetime.min.replace(tzinfo=pd.Timestamp.now(tz="UTC").tzinfo), title))

    if not candidates:
        fallback_titles = re.findall(
            r'<span class="[^"]*sds-comps-text-type-headline1[^"]*"[^>]*>(.*?)</span>',
            response.text,
        )
        if NEWS_ALLOW_UNDATED_NAVER:
            candidates = [
                (datetime.min.replace(tzinfo=pd.Timestamp.now(tz="UTC").tzinfo), clean_news_title(title))
                for title in fallback_titles
                if clean_news_title(title)
            ]

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    return [title for _, title in candidates[:limit] if title]


def fetch_naver_news_headlines(name, sector=None):
    ticker = ticker_symbol_for_news(name)
    if is_korean_company_name(name):
        query = f'"{name}" 주식'
    else:
        market_hint = "TSX" if str(DEFAULT_STOCKS.get(name, "")).endswith(".TO") else "NYSE NASDAQ"
        query = f'"{name}" {ticker} {market_hint}'
    headlines = fetch_naver_news_headlines_for_query(query, limit=8)
    return filter_company_news_headlines(name, headlines, ticker=ticker)[:5]


def fetch_news_context(name, sector=None):
    if not ENABLE_NEWS:
        return {
            "score": 0,
            "risk": 0,
            "summary": "뉴스 비활성",
            "headlines": [],
            "one_line": "뉴스 기능이 꺼져 있습니다.",
            "status": "disabled",
            "source": "disabled",
        }

    company_headlines = []
    sector_headlines = []
    company_sources = []
    sector_sources = []
    errors = []

    for source, fetcher in (
        ("company_risk_news", fetch_company_risk_news_headlines),
        ("google_news", fetch_google_news_headlines),
        ("naver_news", fetch_naver_news_headlines),
    ):
        try:
            source_headlines = fetcher(name, sector)
        except Exception as exc:
            errors.append(f"{source}:{sanitize_error(exc)}")
            continue
        if source_headlines:
            company_sources.append(source)
            company_headlines.extend(source_headlines)

    try:
        sector_headlines = fetch_sector_news_headlines(name, sector)
        if sector_headlines:
            sector_sources.append("sector_news")
    except Exception as exc:
        errors.append(f"sector_news:{sanitize_error(exc)}")

    company_headlines = [title for title in dict.fromkeys(company_headlines) if not is_noise_news_title(title)][:6]
    sector_headlines = [title for title in dict.fromkeys(sector_headlines) if not is_noise_news_title(title)][:3]
    headlines = company_headlines or sector_headlines
    sources = company_sources if company_headlines else sector_sources
    if not headlines:
        return {
            "score": 0,
            "risk": 0,
            "summary": "오늘 기준 관련 뉴스 없음",
            "headlines": [],
            "one_line": "오늘 기준 회사 관련 뉴스 없음 · 엉뚱한 뉴스는 제외",
            "status": "unavailable",
            "source": "none",
            "source_errors": " | ".join(errors[:2]),
        }

    signal_headlines = [title for title in headlines if is_fresh_signal_news_title(title)]
    if not signal_headlines:
        return {
            "score": 0,
            "risk": 0,
            "strength": "none",
            "strong_hits": [],
            "medium_hits": [],
            "weak_hits": [],
            "negative_hits": [],
            "severe_negative_hits": [],
            "summary": "오늘 기준 호재/악재 없음",
            "headlines": [],
            "one_line": "오늘 기준 호재/악재 없음 · 오래된 뉴스는 표시 제외",
            "status": "stale_only",
            "source": "+".join(sources),
        }

    scored = score_news_headlines(signal_headlines)
    if not company_headlines:
        scored["score"] = min(scored["score"], 4)
        scored["risk"] = min(scored["risk"], 8)
        scored["summary"] = "섹터 뉴스 참고: " + scored["summary"]

    return {
        "score": scored["score"],
        "risk": scored["risk"],
        "strength": scored["strength"],
        "strong_hits": scored["strong_hits"],
        "medium_hits": scored["medium_hits"],
        "weak_hits": scored["weak_hits"],
        "negative_hits": scored["negative_hits"],
        "severe_negative_hits": scored.get("severe_negative_hits", []),
        "summary": scored["summary"],
        "headlines": signal_headlines[:2],
        "one_line": summarize_news_one_line(scored["summary"], signal_headlines[:2]),
        "status": "ok",
        "source": "+".join(sources),
    }


def determine_trade_action(
    final_score,
    risk,
    rsi_value,
    range_pos,
    change_pct,
    gap_pct,
    volume_burst,
    supply_concentration,
    market_mode,
    liquidity_confirmed,
):
    overheated = rsi_value >= OVERHEAT_RSI
    extreme_overheated = rsi_value >= EXTREME_OVERHEAT_RSI
    chase_risk = (
        range_pos >= CHASE_RANGE_POS
        or change_pct >= 7
        or gap_pct >= 4
        or (overheated and change_pct >= 4)
    )

    if risk >= MARKET_RISK_BLOCK_THRESHOLD:
        return "🚫 제외", "리스크 과다", chase_risk, overheated
    if market_mode == "risk_off" and final_score < 90:
        return "🛡 방어/관망", "시장 Risk-Off", chase_risk, overheated
    if final_score >= 85 and risk < MARKET_RISK_DOWNGRADE_THRESHOLD and not liquidity_confirmed:
        return "👀 거래량 확인", "점수는 높지만 거래량/거래대금 확인 부족", chase_risk, overheated
    if final_score >= 85 and risk < MARKET_RISK_DOWNGRADE_THRESHOLD and not chase_risk:
        return "✅ 매수 후보", "점수·리스크·타이밍 통과", chase_risk, overheated
    if final_score >= 75 and risk < 20 and supply_concentration and not extreme_overheated:
        return "🟡 분할 관심", "수급 집중 기반 분할 접근", chase_risk, overheated
    if final_score >= 65 and chase_risk:
        return "⏳ 눌림 대기", "이미 오른 구간이라 추격 금지", chase_risk, overheated
    if final_score >= 55 and overheated:
        return "⚡ 단타 관찰", "과열이지만 모멘텀은 유지", chase_risk, overheated
    if final_score >= 45:
        return "👀 관찰", "조건 일부 충족", chase_risk, overheated
    return "대기", "매매 근거 부족", chase_risk, overheated


def build_ai_recommendation(
    final_score,
    risk,
    news,
    volume_ratio,
    dividend,
    market_label,
    change_pct=0,
    rsi_value=50,
    chase_risk=False,
    overheated=False,
    liquidity_confirmed=True,
    action_reason="",
    name="",
    ticker="",
    sector="",
):
    dividend_yield = float(dividend.get("dividend_yield_pct") or 0)
    news_score = int(news.get("score") or 0)
    news_risk = int(news.get("risk") or 0)
    news_status = str(news.get("status") or "")

    ai_score = final_score
    early_setup = -2.5 <= change_pct <= 2.8 and 40 <= rsi_value <= 66 and 0.9 <= volume_ratio <= 2.2
    pullback_setup = ("눌림" in action_reason or "재상승" in action_reason) and change_pct <= 3.5 and rsi_value <= 68
    confirmed_setup = liquidity_confirmed and not chase_risk and not overheated and (early_setup or pullback_setup or volume_ratio >= 1.15)
    chase_penalty = 0

    if news_score > 0 and news_status == "ok":
        ai_score += min(8, news_score)
    if early_setup:
        ai_score += 12
    elif volume_ratio >= 1.2 and change_pct <= 4:
        ai_score += 5
    if pullback_setup:
        ai_score += 8
    if market_label == "캐나다" and dividend_yield >= 3:
        ai_score += 5
    if news_risk > 0:
        ai_score -= min(10, news_risk)
    if news_risk >= 7 and news_score <= 0:
        ai_score = min(ai_score, 84)
    if news_status in {"stale_only", "skipped", "unavailable"}:
        ai_score -= 4
    if risk >= MARKET_RISK_DOWNGRADE_THRESHOLD:
        ai_score -= 8
    if not liquidity_confirmed:
        ai_score -= 14
    if change_pct >= 5:
        chase_penalty += 10
    if change_pct >= 8:
        chase_penalty += 12
    if volume_ratio >= 3 and change_pct >= 4:
        chase_penalty += 8
    if chase_risk:
        chase_penalty += 14
    if overheated or rsi_value >= OVERHEAT_RSI:
        chase_penalty += 10
    if rsi_value >= EXTREME_OVERHEAT_RSI:
        chase_penalty += 12
    ai_score -= chase_penalty

    failure_adjustment, failure_reason = failure_adjustment_for(name, ticker, market_label, sector)
    if failure_adjustment:
        ai_score += failure_adjustment
        if failure_adjustment < 0:
            ai_score = min(ai_score, 69)

    if chase_penalty >= 18:
        ai_score = min(ai_score, 71)
    elif chase_penalty >= 10:
        ai_score = min(ai_score, 83)
    if not confirmed_setup:
        ai_score = min(ai_score, 79)
    if news_risk >= 10:
        ai_score = min(ai_score, 68)

    if ai_score >= 88 and risk < MARKET_RISK_DOWNGRADE_THRESHOLD and confirmed_setup and change_pct <= 3.5:
        label = "AI 추천"
        reason = "추격 구간이 아니고 거래량, 가격 위치, 리스크가 같이 맞습니다."
    elif ai_score >= 72 and risk < MARKET_RISK_BLOCK_THRESHOLD:
        label = "AI 관심"
        reason = "조건은 일부 괜찮지만 바로 매수보다 가격 위치 확인이 필요합니다."
    else:
        label = "AI 관망"
        reason = "지금은 확실한 우위가 부족합니다."

    if chase_penalty >= 18:
        label = "AI 관망"
        reason = "이미 많이 오른 구간이라 신규 매수보다 눌림 확인이 우선입니다."
    elif chase_penalty >= 10 and label == "AI 추천":
        label = "AI 관심"
        reason = "모멘텀은 강하지만 추격 위험이 있어 눌림 확인이 필요합니다."
    if not confirmed_setup and label == "AI 추천":
        label = "AI 관심"
        reason = "점수는 높지만 거래량·가격 위치 확인이 부족해 추천에서 내렸습니다."
    if news_risk >= 10 and label != "AI 관망":
        label = "AI 관망"
        reason = "최근 악재 리스크가 커서 신규 추천에서 제외합니다."

    if market_label == "캐나다" and dividend_yield >= 3 and label != "AI 관망":
        reason = f"{reason} 배당률 {dividend_yield:.2f}%도 참고할 만합니다."
    if failure_reason:
        if failure_adjustment < 0:
            reason = f"{reason} 실패 복기 반영: {failure_reason}."
        elif label != "AI 관망":
            reason = f"{reason} 이전에 놓친 상승 패턴도 일부 반영했습니다."

    return label, max(0, int(ai_score)), reason


def analyze_stock(name, ticker, market_context):
    df = download_price_data(ticker)
    dividend = fetch_dividend_context(ticker)
    if df is None or df.empty or len(df) < 60:
        if is_tiger_etf(name, ticker):
            latest_price, latest_change = latest_naver_quote_price(ticker)
            etf = fetch_etf_nav_context(name, ticker, latest_price or 0)
            etf_now = fetch_etf_now_context(name, ticker)
            etf_holdings = fetch_etf_holdings_context(name, ticker, SECTOR_MAP.get(name, "국장/TIGER ETF"))
            price = latest_price or 0.0
            change_pct = latest_change or 0.0
            lightweight_etf = is_lightweight_etf(name, ticker, SECTOR_MAP.get(name, "국장/TIGER ETF"))
            intraday = empty_intraday_context(lightweight_etf_summary(name)) if lightweight_etf else build_intraday_1m_context(ticker, change_pct)
            news = fetch_news_context(name, SECTOR_MAP.get(name, "국장/TIGER ETF")) if is_full_service_etf(name, ticker) else empty_news_context(lightweight_etf_summary(name))
            data_sources = ["naver_realtime", "naver_etf_nav"]
            if is_full_service_etf(name, ticker):
                data_sources.extend([f"news:{news.get('source', 'unknown')}", "etf_now", "etf_holdings"])
            return {
                "name": name,
                "ticker": ticker,
                "status": "ok" if price > 0 else "no_data",
                "market": market_label_for_ticker(ticker),
                "dividend_group": dividend["dividend_group"],
                "dividend_amount": dividend["dividend_amount"],
                "dividend_annual_amount": dividend["dividend_annual_amount"],
                "dividend_yield_pct": dividend["dividend_yield_pct"],
                "last_dividend_date": dividend["last_dividend_date"],
                "next_dividend_estimate": dividend["next_dividend_estimate"],
                "dividend_frequency_days": dividend["dividend_frequency_days"],
                "dividend_summary": dividend["dividend_summary"],
                "etf_nav": etf["etf_nav"],
                "etf_premium_pct": etf["etf_premium_pct"],
                "etf_summary": etf["etf_summary"],
                "etf_now_source_date": etf_now["etf_now_source_date"],
                "etf_now_signal": etf_now["etf_now_signal"],
                "etf_now_return_pct": etf_now["etf_now_return_pct"],
                "etf_now_buy_price": etf_now["etf_now_buy_price"],
                "etf_now_buy_date": etf_now["etf_now_buy_date"],
                "etf_now_summary": etf_now["etf_now_summary"],
                "etf_holdings_source": etf_holdings["etf_holdings_source"],
                "etf_holdings_source_date": etf_holdings["etf_holdings_source_date"],
                "etf_holdings_count": etf_holdings["etf_holdings_count"],
                "etf_holdings_top": etf_holdings["etf_holdings_top"],
                "etf_holdings_weighted_move_pct": etf_holdings["etf_holdings_weighted_move_pct"],
                "etf_holdings_summary": etf_holdings["etf_holdings_summary"],
                "preopen_score": intraday["preopen_score"],
                "preopen_summary": intraday["preopen_summary"],
                "intraday_1m_score": intraday["intraday_1m_score"],
                "intraday_1m_trend": intraday["intraday_1m_trend"],
                "intraday_1m_summary": intraday["intraday_1m_summary"],
                "ai_label": "ETF 관찰",
                "ai_score": 55 if price > 0 else 0,
                "ai_reason": "신규 ETF라 장기 데이터는 부족합니다. 현재가와 괴리율 중심으로 확인합니다.",
                "sector": SECTOR_MAP.get(name, "국장/TIGER ETF"),
                "label": "👀 관찰" if price > 0 else "보류",
                "action": "👀 괴리율 확인" if price > 0 else "데이터 대기",
                "action_reason": "ETF는 NAV 괴리율과 기초자산 흐름 확인",
                "score": 45 if price > 0 else 0,
                "raw_score": 45 if price > 0 else 0,
                "technical_score": 15 if price > 0 else 0,
                "volume_score": 0,
                "flow_score": 0,
                "news_score": news["score"],
                "market_score": market_context["score_adjust"],
                "risk": (6 + int(news["risk"])) if price > 0 else 0,
                "overheated": False,
                "chase_risk": False,
                "market_regime": market_context["regime"],
                "market_risk": market_context["risk"],
                "price": round(price, 2),
                "daily_close": round(price, 2),
                "price_source": "naver_realtime",
                "change_source": "naver_realtime",
                "price_drift_pct": 0.0,
                "change_pct": round(change_pct, 2),
                "gap_pct": 0.0,
                "volume_ratio": 1.0,
                "trade_value_ratio": 1.0,
                "liquidity_confirmed": price > 0,
                "trade_value": 0,
                "rsi": 50.0,
                "macd_bullish": False,
                "atr_pct": 0.0,
                "patterns": "ETF 괴리율 확인",
                "reasons": " · ".join(
                    item
                    for item in [
                        etf["etf_summary"],
                        etf_now["etf_now_summary"],
                        etf_holdings["etf_holdings_summary"],
                        news.get("one_line", ""),
                    ]
                    if item
                )
                or "ETF 현재가 확인",
                "risks": "신규 ETF는 장기 데이터 부족" if not news["risk"] else f"신규 ETF는 장기 데이터 부족, 뉴스 리스크: {news['summary']}",
                "flow": "ETF 수급 별도 확인",
                "flow_status": "etf",
                "foreign_net": 0.0,
                "institution_net": 0.0,
                "news": news["summary"] if is_full_service_etf(name, ticker) else "ETF 경량 모드",
                "news_source": news.get("source", "etf"),
                "news_one_line": news.get("one_line", "ETF는 현재가와 NAV 괴리율을 같이 확인합니다.") if is_full_service_etf(name, ticker) else lightweight_etf_summary(name),
                "news_strength": news.get("strength", "none"),
                "headlines": " | ".join(news["headlines"]) if news.get("headlines") else "-",
                "data_sources": ", ".join(data_sources),
            }
        return {
            "name": name,
            "ticker": ticker,
            "status": "no_data",
            "market": market_label_for_ticker(ticker),
            "dividend_group": dividend["dividend_group"],
            "dividend_amount": dividend["dividend_amount"],
            "dividend_annual_amount": dividend["dividend_annual_amount"],
            "dividend_yield_pct": dividend["dividend_yield_pct"],
            "last_dividend_date": dividend["last_dividend_date"],
            "next_dividend_estimate": dividend["next_dividend_estimate"],
            "dividend_frequency_days": dividend["dividend_frequency_days"],
            "dividend_summary": dividend["dividend_summary"],
            "etf_nav": 0.0,
            "etf_premium_pct": 0.0,
            "etf_summary": "NAV 확인 대기" if is_tiger_etf(name, ticker) else "",
            "etf_holdings_source": "",
            "etf_holdings_source_date": "",
            "etf_holdings_count": 0,
            "etf_holdings_top": "",
            "etf_holdings_weighted_move_pct": 0.0,
            "etf_holdings_summary": "",
            "ai_label": "AI 관망",
            "ai_score": 0,
            "ai_reason": "가격 데이터를 확인하지 못했습니다.",
            "news_one_line": "뉴스 확인 전입니다.",
            "score": 0,
        }

    close = df["Close"]
    volume = df["Volume"]
    price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2])
    open_price = float(df["Open"].iloc[-1])
    daily_close = price
    price, price_source, price_drift_pct = apply_latest_price(ticker, price, prev_close, open_price)
    change_pct, change_source = latest_change_pct(ticker, price, prev_close, price_source)
    sector = SECTOR_MAP.get(name, "기타")
    lightweight_etf = is_lightweight_etf(name, ticker, sector)
    etf = fetch_etf_nav_context(name, ticker, price)
    etf_now = fetch_etf_now_context(name, ticker)
    etf_holdings = fetch_etf_holdings_context(name, ticker, sector)
    intraday = empty_intraday_context(lightweight_etf_summary(name)) if lightweight_etf else build_intraday_1m_context(ticker, change_pct)
    gap_pct = ((open_price / prev_close) - 1) * 100 if prev_close else 0

    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    ma20_prev = float(close.rolling(20).mean().iloc[-2])
    avg_volume = float(volume.rolling(20).mean().iloc[-1])
    volume_ratio = float(volume.iloc[-1] / avg_volume) if avg_volume else 0
    trade_value = float(price * volume.iloc[-1])
    avg_trade_value = float((close * volume).rolling(20).mean().iloc[-1])
    trade_value_ratio = trade_value / avg_trade_value if avg_trade_value else 0
    rsi_value = float(rsi(close).iloc[-1])
    macd_line, signal_line, macd_hist = macd(close)
    macd_bullish = float(macd_line.iloc[-1]) > float(signal_line.iloc[-1]) and float(macd_hist.iloc[-1]) > 0
    atr_value = float(atr(df).iloc[-1])
    atr_pct = (atr_value / price) * 100 if price else 0
    high_20 = float(close.rolling(20).max().iloc[-2])
    low_20 = float(close.tail(20).min())
    range_pos = ((price - low_20) / (high_20 - low_20)) * 100 if high_20 > low_20 else 0

    flow = empty_flow_context(lightweight_etf_summary(name)) if lightweight_etf else fetch_flow_context(ticker)
    news = empty_news_context(lightweight_etf_summary(name)) if lightweight_etf else fetch_news_context(name, sector)

    technical_score = 0
    volume_score = 0
    flow_score = 0
    news_score = 0
    market_score = 0
    risk = 0
    reasons = []
    risks = []
    patterns = []

    trend_up = ma5 > ma20 > ma60
    pullback_rebound = trend_up and price > ma5 and ma20 > ma20_prev and 35 <= range_pos <= 85
    volume_burst = volume_ratio >= 2.0 or trade_value_ratio >= 2.0
    liquidity_confirmed = volume_ratio >= MIN_BUY_VOLUME_RATIO and trade_value_ratio >= MIN_BUY_TRADE_VALUE_RATIO
    supply_concentration = flow["score"] >= 25

    if trend_up:
        technical_score += 20
        reasons.append("추세 상승")
    if pullback_rebound:
        technical_score += 18
        reasons.append("눌림 후 재상승")
        patterns.append("눌림 후 재상승")
    if volume_burst:
        volume_score += 20
        reasons.append(f"거래량/거래대금 폭발({volume_ratio:.1f}x/{trade_value_ratio:.1f}x)")
        patterns.append("거래량 폭발")
    elif volume_ratio >= 1.3:
        volume_score += 12
        reasons.append(f"거래량 증가({volume_ratio:.1f}x)")
    if price > high_20:
        technical_score += 15
        reasons.append("20일 고점 돌파")
    if 50 <= rsi_value <= 70:
        technical_score += 10
        reasons.append("RSI 건강 구간")
    elif rsi_value > 78:
        risk += 12
        risks.append("RSI 과열")
    if rsi_value >= EXTREME_OVERHEAT_RSI:
        risk += 10
        risks.append("RSI 극단 과열")
    if macd_bullish:
        technical_score += 10
        reasons.append("MACD 상승")
    if 0 < gap_pct < 3:
        technical_score += 6
        reasons.append("건전한 갭 상승")
    elif gap_pct >= 4:
        risk += 12
        risks.append("갭 상승 과열")
    elif gap_pct <= -3:
        risk += 10
        risks.append("갭 하락 경계")
    if atr_pct > 6:
        risk += 15
        risks.append("변동성 과다")
    if change_pct >= 7:
        risk += 10
        risks.append("당일 급등 후 추격 위험")
    if range_pos >= CHASE_RANGE_POS and rsi_value >= 70:
        risk += 8
        risks.append("20일 범위 상단 추격")
    if trade_value < MIN_TRADE_VALUE:
        risk += 15
        risks.append("거래대금 부족")
    flow_score += flow["score"]
    risk += flow["risk"]
    if flow["score"] > 0:
        reasons.append(flow["summary"])
    if flow["risk"] > 0:
        risks.append(flow["summary"])
    if supply_concentration:
        patterns.append("수급 집중")

    news_score += news["score"]
    risk += news["risk"]
    if news["score"] > 0:
        reasons.append(f"뉴스 키워드: {news['summary']}")
    if news.get("strength") == "weak":
        risks.append("뉴스 호재 강도 약함")
    if news["risk"] > 0:
        risks.append(f"뉴스 리스크: {news['summary']}")

    market_mode = market_context["mode"]
    market_score += market_context["score_adjust"]
    risk += market_context["risk"]

    if market_mode == "bull" and volume_burst and trend_up:
        market_score += 12
        reasons.append("상승장+거래량 폭발")
    elif market_mode in {"risk_off", "caution"} and volume_burst:
        risk += 12
        risks.append("약한 시장에서 거래량 폭발은 매물 출회 가능성")
    if market_mode == "risk_off" and not trend_up:
        risk += 10
        risks.append("Risk-Off에서 추세 미확인")
    if market_mode == "bull" and pullback_rebound:
        market_score += 8
        reasons.append("상승장 눌림 재상승")

    if intraday["intraday_1m_score"] > 0:
        technical_score += min(12, intraday["intraday_1m_score"])
        reasons.append(intraday["intraday_1m_summary"])
    elif intraday["intraday_1m_score"] < 0:
        risk += min(12, abs(intraday["intraday_1m_score"]))
        risks.append(intraday["intraday_1m_summary"])
    if intraday["preopen_score"] > 0:
        market_score += intraday["preopen_score"]
        patterns.append("본장 전/초반 강세")
        reasons.append(intraday["preopen_summary"])
    elif intraday["preopen_score"] < 0:
        risk += abs(intraday["preopen_score"])
        risks.append(intraday["preopen_summary"])

    raw_score = technical_score + volume_score + flow_score + news_score + market_score
    if not liquidity_confirmed:
        risks.append(
            f"매수 확인 부족: 거래량 {volume_ratio:.2f}x / 거래대금 {trade_value_ratio:.2f}x"
        )
    final_score = max(0, int(raw_score - risk))
    action, action_reason, chase_risk, overheated = determine_trade_action(
        final_score,
        risk,
        rsi_value,
        range_pos,
        change_pct,
        gap_pct,
        volume_burst,
        supply_concentration,
        market_mode,
        liquidity_confirmed,
    )

    label = "보류"
    if final_score >= 80 and risk < MARKET_RISK_DOWNGRADE_THRESHOLD and not chase_risk and liquidity_confirmed:
        label = "🔥 강력 관심"
    elif final_score >= 60 and risk < MARKET_RISK_DOWNGRADE_THRESHOLD:
        label = "👍 관심"
    elif final_score >= 40:
        label = "👀 관찰"

    if risk >= MARKET_RISK_DOWNGRADE_THRESHOLD and label in {"🔥 강력 관심", "👍 관심"}:
        label = "👀 관찰"
        risks.append(f"리스크 {risk} 이상으로 관심 등급 강등")
    if risk >= MARKET_RISK_BLOCK_THRESHOLD:
        label = "보류"
        risks.append(f"리스크 {risk} 이상으로 신규 관심 제외")
    if market_mode == "risk_off" and label in {"🔥 강력 관심", "👍 관심"}:
        label = "👀 관찰"
        risks.append("시장 Risk-Off로 매수 등급 제한")

    market_label = market_label_for_ticker(ticker)
    ai_label, ai_score, ai_reason = build_ai_recommendation(
        final_score,
        risk,
        news,
        volume_ratio,
        dividend,
        market_label,
        change_pct=change_pct,
        rsi_value=rsi_value,
        chase_risk=chase_risk,
        overheated=overheated,
        liquidity_confirmed=liquidity_confirmed,
        action_reason=", ".join(reasons),
        name=name,
        ticker=ticker,
        sector=sector,
    )

    return {
        "name": name,
        "ticker": ticker,
        "status": "ok",
        "market": market_label,
        "dividend_group": dividend["dividend_group"],
        "dividend_amount": dividend["dividend_amount"],
        "dividend_annual_amount": dividend["dividend_annual_amount"],
        "dividend_yield_pct": dividend["dividend_yield_pct"],
        "last_dividend_date": dividend["last_dividend_date"],
        "next_dividend_estimate": dividend["next_dividend_estimate"],
        "dividend_frequency_days": dividend["dividend_frequency_days"],
        "dividend_summary": dividend["dividend_summary"],
        "etf_nav": etf["etf_nav"],
        "etf_premium_pct": etf["etf_premium_pct"],
        "etf_summary": etf["etf_summary"],
        "etf_now_source_date": etf_now["etf_now_source_date"],
        "etf_now_signal": etf_now["etf_now_signal"],
        "etf_now_return_pct": etf_now["etf_now_return_pct"],
        "etf_now_buy_price": etf_now["etf_now_buy_price"],
        "etf_now_buy_date": etf_now["etf_now_buy_date"],
        "etf_now_summary": etf_now["etf_now_summary"],
        "etf_holdings_source": etf_holdings["etf_holdings_source"],
        "etf_holdings_source_date": etf_holdings["etf_holdings_source_date"],
        "etf_holdings_count": etf_holdings["etf_holdings_count"],
        "etf_holdings_top": etf_holdings["etf_holdings_top"],
        "etf_holdings_weighted_move_pct": etf_holdings["etf_holdings_weighted_move_pct"],
        "etf_holdings_summary": etf_holdings["etf_holdings_summary"],
        "preopen_score": intraday["preopen_score"],
        "preopen_summary": intraday["preopen_summary"],
        "intraday_1m_score": intraday["intraday_1m_score"],
        "intraday_1m_trend": intraday["intraday_1m_trend"],
        "intraday_1m_summary": intraday["intraday_1m_summary"],
        "ai_label": ai_label,
        "ai_score": ai_score,
        "ai_reason": ai_reason,
        "sector": sector,
        "label": label,
        "action": action,
        "action_reason": action_reason,
        "score": final_score,
        "raw_score": int(raw_score),
        "technical_score": int(technical_score),
        "volume_score": int(volume_score),
        "flow_score": int(flow_score),
        "news_score": int(news_score),
        "market_score": int(market_score),
        "risk": int(risk),
        "overheated": overheated,
        "chase_risk": chase_risk,
        "market_regime": market_context["regime"],
        "market_risk": market_context["risk"],
        "price": round(price, 2),
        "daily_close": round(daily_close, 2),
        "price_source": price_source,
        "change_source": change_source,
        "price_drift_pct": round(price_drift_pct, 2),
        "change_pct": round(change_pct, 2),
        "gap_pct": round(gap_pct, 2),
        "volume_ratio": round(volume_ratio, 2),
        "trade_value_ratio": round(trade_value_ratio, 2),
        "liquidity_confirmed": liquidity_confirmed,
        "trade_value": int(trade_value),
        "rsi": round(rsi_value, 1),
        "macd_bullish": macd_bullish,
        "atr_pct": round(atr_pct, 2),
        "patterns": ", ".join(dict.fromkeys(patterns)) if patterns else "일반 모멘텀",
        "reasons": ", ".join(dict.fromkeys(reasons)) if reasons else "-",
        "risks": ", ".join(dict.fromkeys(risks)) if risks else "-",
        "flow": flow["summary"],
        "flow_status": flow["status"],
        "foreign_net": round(flow.get("foreign_net", 0.0), 2),
        "institution_net": round(flow.get("institution_net", 0.0), 2),
        "news": news["summary"],
        "news_source": news.get("source", "unknown"),
        "news_one_line": news.get("one_line", summarize_news_one_line(news["summary"], news["headlines"])),
        "news_strength": news.get("strength", "none"),
        "headlines": " | ".join(news["headlines"]) if news["headlines"] else "-",
        "data_sources": ", ".join(
            dict.fromkeys(
                item
                for item in [
                    "naver_daily" if korean_stock_code(ticker) else "yahoo_daily",
                    price_source,
                    f"news:{news.get('source', 'unknown')}",
                    f"flow:{flow.get('status', 'unknown')}",
                    "intraday_1m" if should_fetch_intraday_1m(ticker) and not lightweight_etf else "",
                    "etf_now" if is_full_service_etf(name, ticker) else "",
                    "etf_holdings" if is_full_service_etf(name, ticker) else "",
                ]
                if item
            )
        ),
    }


def build_sector_context(results):
    ok_results = [item for item in results if item.get("status") == "ok"]
    if not ok_results:
        return {}

    rows = pd.DataFrame(ok_results)
    sector_context = {}
    for sector, group in rows.groupby("sector"):
        if len(group) < 2:
            continue
        avg_score = float(group["score"].mean())
        avg_change = float(group["change_pct"].mean())
        avg_volume = float(group["volume_ratio"].mean())
        strong_count = int((group["score"] >= 60).sum())

        sector_score = 0
        sector_risk = 0
        summary = "중립"
        if avg_score >= 60 and avg_change > 0 and avg_volume >= 1.2 and strong_count >= 2:
            sector_score = 8
            summary = f"{sector} 섹터 동반 강세"
        elif avg_change <= -1.5 and avg_score < 45:
            sector_risk = 6
            summary = f"{sector} 섹터 약세"
        elif avg_volume >= 1.5 and strong_count >= 2:
            sector_score = 5
            summary = f"{sector} 섹터 거래량 집중"

        sector_context[sector] = {
            "score": sector_score,
            "risk": sector_risk,
            "summary": summary,
            "avg_score": round(avg_score, 1),
            "avg_change": round(avg_change, 2),
            "avg_volume": round(avg_volume, 2),
            "strong_count": strong_count,
        }

    return sector_context


def relabel_after_adjustment(item):
    if item["risk"] >= MARKET_RISK_BLOCK_THRESHOLD:
        return "보류"
    if (
        item["score"] >= 80
        and item["risk"] < MARKET_RISK_DOWNGRADE_THRESHOLD
        and not item.get("chase_risk")
        and item.get("liquidity_confirmed")
    ):
        return "🔥 강력 관심"
    if item["score"] >= 60 and item["risk"] < MARKET_RISK_DOWNGRADE_THRESHOLD:
        return "👍 관심"
    if item["score"] >= 40:
        return "👀 관찰"
    return "보류"


def apply_sector_context(results):
    sector_context = build_sector_context(results)
    if not sector_context:
        return results, sector_context

    adjusted = []
    for item in results:
        if item.get("status") != "ok":
            adjusted.append(item)
            continue

        context = sector_context.get(item.get("sector"))
        if not context:
            item["sector_summary"] = "섹터 확인 부족"
            adjusted.append(item)
            continue

        item["sector_score"] = context["score"]
        item["sector_risk"] = context["risk"]
        item["sector_summary"] = context["summary"]
        item["score"] = max(0, int(item["score"] + context["score"] - context["risk"]))
        item["risk"] = int(item["risk"] + context["risk"])
        if context["score"] > 0:
            item["reasons"] = f"{item['reasons']}, {context['summary']}"
        if context["risk"] > 0:
            item["risks"] = f"{item['risks']}, {context['summary']}" if item["risks"] != "-" else context["summary"]
        item["label"] = relabel_after_adjustment(item)
        item["action"], item["action_reason"], item["chase_risk"], item["overheated"] = determine_trade_action(
            item["score"],
            item["risk"],
            item["rsi"],
            100 if item.get("chase_risk") else 50,
            item["change_pct"],
            item["gap_pct"],
            item["volume_ratio"] >= 2 or item["trade_value_ratio"] >= 2,
            item["flow_score"] >= 25,
            "neutral",
            bool(item.get("liquidity_confirmed")),
        )
        news_context = {
            "score": item.get("news_score", 0),
            "risk": 0,
            "strength": item.get("news_strength", "none"),
        }
        dividend_context = {
            "dividend_yield_pct": item.get("dividend_yield_pct", 0),
        }
        item["ai_label"], item["ai_score"], item["ai_reason"] = build_ai_recommendation(
            item["score"],
            item["risk"],
            news_context,
            item.get("volume_ratio", 0),
            dividend_context,
            item.get("market", market_label_for_ticker(item.get("ticker", ""))),
            change_pct=item.get("change_pct", 0),
            rsi_value=item.get("rsi", 50),
            chase_risk=bool(item.get("chase_risk")),
            overheated=bool(item.get("overheated")),
            liquidity_confirmed=bool(item.get("liquidity_confirmed")),
            action_reason=f"{item.get('action_reason', '')} {item.get('reasons', '')}",
            name=item.get("name", ""),
            ticker=item.get("ticker", ""),
            sector=item.get("sector", ""),
        )
        adjusted.append(item)

    return adjusted, sector_context


def build_breadth_context(results, market_context):
    ok_results = [item for item in results if item.get("status") == "ok"]
    if not ok_results:
        return {
            "label": "체감 흐름 확인 불가",
            "summary": "종목 데이터 부족",
            "avg_change": 0.0,
            "up_count": 0,
            "down_count": 0,
            "flat_count": 0,
        }

    up_count = sum(1 for item in ok_results if item.get("change_pct", 0) > 0)
    down_count = sum(1 for item in ok_results if item.get("change_pct", 0) < 0)
    flat_count = len(ok_results) - up_count - down_count
    avg_change = sum(float(item.get("change_pct", 0)) for item in ok_results) / len(ok_results)
    down_ratio = down_count / len(ok_results)
    up_ratio = up_count / len(ok_results)

    label = "체감 중립"
    summary = "상승/하락 종목이 엇갈림"
    if avg_change > 0.4 and up_ratio >= 0.55:
        label = "체감 강세"
        summary = "지수와 종목 흐름이 같이 우호적"
    elif avg_change < -0.4 and down_ratio >= 0.55:
        label = "체감 약세"
        summary = "분석 종목 다수가 당일 하락"
    elif market_context["mode"] == "bull" and (avg_change < 0 or down_ratio >= 0.5):
        label = "상승장 속 단기 눌림"
        summary = "큰 추세는 우호적이지만 오늘 종목 체감은 약함"
    elif market_context["mode"] in {"risk_off", "caution"} and up_ratio >= 0.55:
        label = "약한 시장 속 반등"
        summary = "시장 판정은 조심스럽지만 일부 종목은 반등"

    return {
        "label": label,
        "summary": summary,
        "avg_change": round(avg_change, 2),
        "up_count": up_count,
        "down_count": down_count,
        "flat_count": flat_count,
    }


def build_sector_leaderboard(sector_context):
    leaders = []
    for sector, context in sector_context.items():
        popularity_score = (
            context.get("score", 0) * 10
            + context.get("strong_count", 0) * 4
            + max(0.0, context.get("avg_change", 0.0)) * 2
            + max(0.0, context.get("avg_volume", 0.0) - 1.0) * 3
        )
        leaders.append(
            {
                "sector": sector,
                "summary": context.get("summary", "중립"),
                "avg_change": context.get("avg_change", 0.0),
                "avg_volume": context.get("avg_volume", 0.0),
                "strong_count": context.get("strong_count", 0),
                "popularity_score": round(popularity_score, 1),
            }
        )
    return sorted(
        leaders,
        key=lambda item: (
            item["popularity_score"],
            item["strong_count"],
            item["avg_change"],
            item["avg_volume"],
        ),
        reverse=True,
    )


def build_sector_closing_comment(sector_leaderboard):
    if not sector_leaderboard:
        return "마지막 한줄: 아직 섹터 주도 흐름이 뚜렷하지 않습니다."

    strong_sector = next(
        (item for item in sector_leaderboard if item["summary"] != "중립" and item["avg_change"] > 0),
        sector_leaderboard[0],
    )
    weak_sector = next(
        (item for item in reversed(sector_leaderboard) if item["avg_change"] < 0),
        None,
    )

    comment = (
        f"마지막 한줄: 지금은 {strong_sector['sector']} 쪽이 강합니다"
        f" (평균등락 {strong_sector['avg_change']}%, 거래량 {strong_sector['avg_volume']}x)."
    )
    if weak_sector:
        comment += (
            f" 반대로 {weak_sector['sector']} 쪽은 상대적으로 약합니다"
            f" (평균등락 {weak_sector['avg_change']}%)."
        )
    return comment


def build_report(results, market_context):
    now = datetime.now(pd.Timestamp.now(tz=SEOUL_TZ).tzinfo).strftime("%Y-%m-%d %H:%M")
    candidates = [item for item in results if item.get("status") == "ok" and item["score"] >= 40]
    top = sorted(candidates, key=lambda item: (item["score"], -item["risk"], item["volume_ratio"]), reverse=True)[:TOP_N]
    sector_context = build_sector_context(results)
    breadth_context = build_breadth_context(results, market_context)
    sector_leaderboard = build_sector_leaderboard(sector_context)
    sector_closing_comment = build_sector_closing_comment(sector_leaderboard)
    hot_sectors = [
        (sector, context)
        for sector, context in sector_context.items()
        if context["score"] > 0
    ]
    strongest_stocks = sorted(
        [item for item in candidates if item["change_pct"] > 0],
        key=lambda item: (item["score"], item["change_pct"], item["volume_ratio"]),
        reverse=True,
    )[:5]
    long_term_candidates = sorted(
        [
            item
            for item in candidates
            if item["risk"] <= 18
            and item["score"] >= 55
            and item.get("atr_pct", 99) <= 4.5
            and 45 <= item.get("rsi", 0) <= 70
            and "추세 상승" in item.get("reasons", "")
        ],
        key=lambda item: (item["score"] - item["risk"], -item["atr_pct"], item["volume_ratio"]),
        reverse=True,
    )[:5]

    lines = [
        "📡 마켓 스캐너",
        f"시간: {now}",
        f"기준: {SCAN_INTERVAL} / TOP {TOP_N}",
        f"시장: {market_context['regime']} | 리스크 {market_context['risk']}",
        f"체감: {breadth_context['label']} | 평균등락 {breadth_context['avg_change']}%",
        f"종목 흐름: 상승 {breadth_context['up_count']} / 하락 {breadth_context['down_count']} / 보합 {breadth_context['flat_count']}",
        f"체감 근거: {breadth_context['summary']}",
        f"시장 근거: {market_context['summary']}",
        f"분석 성공: {len([r for r in results if r.get('status') == 'ok'])}개",
        "",
    ]
    if strongest_stocks:
        lines.append("🚀 지금 강한 종목")
        for item in strongest_stocks:
            lines.append(
                f"- {item['name']} ({item['sector']}) | 점수 {item['score']} | 등락 {item['change_pct']}% | 거래량 {item['volume_ratio']}x | {item['action']}"
            )
        lines.append("")

    if long_term_candidates:
        lines.append("🏦 장기 관점 추천")
        for item in long_term_candidates:
            lines.append(
                f"- {item['name']} ({item['sector']}) | 점수 {item['score']} / 위험 {item['risk']} | RSI {item['rsi']} | 변동성 {item['atr_pct']}% | {item['action']}"
            )
        lines.append("")

    if sector_leaderboard:
        lines.append("🏆 인기 섹터 랭킹")
        for rank, item in enumerate(sector_leaderboard[:5], start=1):
            lines.append(
                f"{rank}. {item['sector']} | 강세종목 {item['strong_count']}개 | 평균등락 {item['avg_change']}% | 거래량 {item['avg_volume']}x | {item['summary']}"
            )
        lines.append("")

    if hot_sectors:
        lines.append("🔥 강한 섹터")
        for sector, context in sorted(hot_sectors, key=lambda pair: pair[1]["score"], reverse=True)[:3]:
            lines.append(
                f"- {sector}: {context['summary']} "
                f"(평균등락 {context['avg_change']}%, 거래량 {context['avg_volume']}x)"
            )
        lines.append("")

    if not top:
        lines.append("오늘 에너지가 강하게 쌓인 종목이 아직 없습니다.")
        return "\n".join(lines)

    for rank, item in enumerate(top, start=1):
        lines.append(f"{rank}. {item['name']} | {item['action']} | 점수 {item['score']} / 위험 {item['risk']}")
        lines.append(
            f"   섹터: {item['sector']} | 패턴: {item['patterns']} | 등락 {item['change_pct']}% | 거래량 {item['volume_ratio']}x | RSI {item['rsi']}"
        )
        lines.append(
            f"   점수분해: 기술 {item['technical_score']} / 거래량 {item['volume_score']} / 수급 {item['flow_score']} / 뉴스 {item['news_score']} / 시장 {item['market_score']}"
        )
        lines.append(f"   결정: {item['action_reason']} | 수급: {item['flow']}")
        lines.append(f"   이유: {item['reasons']}")
        if item["risks"] != "-":
            lines.append(f"   주의: {item['risks']}")
        lines.append("")

    lines.append(sector_closing_comment)
    lines.append("")
    lines.append(f"상세 파일: {RESULT_FILE.name}")
    return "\n".join(lines).strip()


def split_message(text):
    if len(text) <= TELEGRAM_MAX_LENGTH:
        return [text]
    chunks = []
    current = []
    current_len = 0
    for line in text.splitlines():
        line_len = len(line) + 1
        if current and current_len + line_len > TELEGRAM_MAX_LENGTH:
            chunks.append("\n".join(current))
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


def sanitize_error(message):
    text = str(message)
    if TELEGRAM_TOKEN:
        text = text.replace(TELEGRAM_TOKEN, mask_secret(TELEGRAM_TOKEN))
    return text


def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("텔레그램 설정 없음: MARKET_SCANNER_BOT_TOKEN / MARKET_SCANNER_CHAT_ID", flush=True)
        return False

    from telegram_message_utils import compact_telegram_message

    text = compact_telegram_message(text)
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    for chunk in split_message(text):
        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(
                    url,
                    data={"chat_id": TELEGRAM_CHAT_ID, "text": chunk, "disable_web_page_preview": True},
                    timeout=12,
                )
                if response.ok:
                    last_error = None
                    break
                last_error = f"HTTP {response.status_code}: {response.text[:250]}"
            except requests.RequestException as exc:
                last_error = sanitize_error(exc)
            if attempt < 2:
                time_module.sleep(1)
        if last_error:
            print(f"텔레그램 전송 실패: {sanitize_error(last_error)}", flush=True)
            return False
    return True


def main():
    print("마켓 스캐너 시작", flush=True)
    cleanup_old_caches()
    print("시장 상태 확인 중", flush=True)
    market_context = get_market_context()
    print(f"시장: {market_context['regime']} / 리스크 {market_context['risk']}", flush=True)

    results = []
    stock_items = list(DEFAULT_STOCKS.items())
    if MAX_STOCKS > 0:
        protected_items = [
            (name, ticker)
            for name, ticker in stock_items
            if name in REQUIRED_KOREA_STOCK_NAMES
            or is_tiger_etf(name, ticker)
            or market_label_for_ticker(ticker) in {"미장", "캐나다"}
        ]
        other_items = [
            (name, ticker)
            for name, ticker in stock_items
            if name not in REQUIRED_KOREA_STOCK_NAMES
            and not is_tiger_etf(name, ticker)
            and market_label_for_ticker(ticker) not in {"미장", "캐나다"}
        ]
        stock_items = (protected_items + other_items)[:MAX_STOCKS]
        print(f"최적화: 상위 {len(stock_items)}개만 스캔(MARKET_SCANNER_MAX_STOCKS)", flush=True)

    workers = min(MAX_WORKERS, len(stock_items))
    print(f"스캔 최적화: 병렬 분석 {workers}개 워커", flush=True)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(analyze_stock, name, ticker, market_context): (name, ticker)
            for name, ticker in stock_items
        }
        for future in as_completed(futures):
            name, ticker = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append(
                    {
                        "name": name,
                        "ticker": ticker,
                        "status": "error",
                        "market": market_label_for_ticker(ticker),
                        "dividend_group": dividend_group_for_ticker(ticker),
                        "dividend_amount": 0.0,
                        "dividend_annual_amount": 0.0,
                        "dividend_yield_pct": 0.0,
                        "last_dividend_date": "",
                        "next_dividend_estimate": "",
                        "dividend_frequency_days": 0,
                        "dividend_summary": "확인 실패",
                        "etf_nav": 0.0,
                        "etf_premium_pct": 0.0,
                        "etf_summary": "NAV 확인 실패" if is_tiger_etf(name, ticker) else "",
                        "etf_holdings_source": "",
                        "etf_holdings_source_date": "",
                        "etf_holdings_count": 0,
                        "etf_holdings_top": "",
                        "etf_holdings_weighted_move_pct": 0.0,
                        "etf_holdings_summary": "보유비중 확인 실패" if is_etf_like(name, ticker) else "",
                        "ai_label": "AI 관망",
                        "ai_score": 0,
                        "ai_reason": "분석 중 오류가 발생했습니다.",
                        "news_one_line": "뉴스 확인 실패",
                        "score": 0,
                        "reason": str(exc),
                    }
                )

    results, sector_context = apply_sector_context(results)
    rows = sorted(results, key=lambda item: item.get("score", 0), reverse=True)
    pd.DataFrame(rows).to_csv(RESULT_FILE, index=False, encoding="utf-8-sig")
    secure_file_permissions(RESULT_FILE)

    report = build_report(rows, market_context)
    print("\n" + report, flush=True)
    if send_telegram(report):
        print("텔레그램 전송 완료", flush=True)


if __name__ == "__main__":
    main()
