"""
Stock Data & Deterministic Pick Screening
- 국내: Naver Finance 개별 종목 시세 페이지(로그인 불필요)를 스크래핑한다.
  원래는 pykrx를 쓸 계획이었으나, 구현 시점(2026-08) 확인 결과 pykrx는
  KRX_ID/KRX_PW 환경변수(KRX 계정 로그인)가 있어야 동작해 "무료·키 불필요"
  전제가 깨졌다. Naver Finance는 로그인 없이 동일한 데이터를 제공한다.
- 해외: yfinance 배치 다운로드(무료, 키 불필요).

종목 선정(스크리닝)은 전부 결정론적 파이썬 로직이다 — LLM은 여기서 만든
숫자를 근거로 '이유' 문장만 작성한다(summarizer.generate_stock_reasons).
전체 시장을 스캔하지 않고 유동성 큰 대형주 관찰목록으로 한정했다 —
필요하면 아래 WATCHLIST에 종목을 추가하면 된다.
"""
from io import StringIO
from typing import Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf

from .logger import setup_logger

logger = setup_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0"}

DOMESTIC_WATCHLIST = [
    ("005930", "삼성전자"), ("000660", "SK하이닉스"), ("035420", "NAVER"),
    ("035720", "카카오"), ("373220", "LG에너지솔루션"), ("005380", "현대차"),
    ("000270", "기아"), ("005490", "POSCO홀딩스"), ("207940", "삼성바이오로직스"),
    ("068270", "셀트리온"), ("105560", "KB금융"), ("055550", "신한지주"),
    ("006400", "삼성SDI"), ("051910", "LG화학"), ("096770", "SK이노베이션"),
    ("028260", "삼성물산"), ("066570", "LG전자"), ("323410", "카카오뱅크"),
    ("086790", "하나금융지주"), ("030200", "KT"),
]

OVERSEAS_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet", "AMZN": "Amazon",
    "NVDA": "NVIDIA", "META": "Meta Platforms", "TSLA": "Tesla", "AVGO": "Broadcom",
    "JPM": "JPMorgan Chase", "V": "Visa", "JNJ": "Johnson & Johnson", "WMT": "Walmart",
    "PG": "Procter & Gamble", "UNH": "UnitedHealth", "HD": "Home Depot", "MA": "Mastercard",
    "XOM": "ExxonMobil", "CVX": "Chevron", "KO": "Coca-Cola", "PEP": "PepsiCo",
}

HORIZONS = ["daily", "weekly", "monthly"]
_HORIZON_OFFSET = {"daily": 1, "weekly": 5, "monthly": 20}
PICKS_PER_HORIZON = 2


def _pct_change(closes_newest_first: List[float], offset: int) -> Optional[float]:
    if offset >= len(closes_newest_first):
        return None
    latest, past = closes_newest_first[0], closes_newest_first[offset]
    if not past:
        return None
    return round((latest - past) / past * 100, 2)


def _build_entry(market: str, symbol: str, name: str,
                  closes_newest_first: List[float], volumes_newest_first: List[float]) -> Optional[Dict]:
    if len(closes_newest_first) < 6:
        return None
    entry = {"market": market, "symbol": symbol, "name": name, "price": round(closes_newest_first[0], 2)}
    for horizon, offset in _HORIZON_OFFSET.items():
        entry[f"{horizon}_change_pct"] = _pct_change(closes_newest_first, min(offset, len(closes_newest_first) - 1))
    recent = volumes_newest_first[1:6]
    avg_recent_volume = sum(recent) / len(recent) if recent else 0
    entry["volume_ratio"] = round(volumes_newest_first[0] / avg_recent_volume, 2) if avg_recent_volume else None
    return entry


def _fetch_domestic_history(code: str, pages: int = 3) -> Optional[pd.DataFrame]:
    """최근 거래일 순 시세(index 0이 최신) DataFrame[date, close, volume]. 실패 시 None."""
    frames = []
    try:
        for page in range(1, pages + 1):
            url = f"https://finance.naver.com/item/sise_day.naver?code={code}&page={page}"
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.encoding = "euc-kr"
            tables = pd.read_html(StringIO(resp.text))
            df = tables[0].dropna()
            if df.empty:
                break
            frames.append(df)
        if not frames:
            return None
        combined = pd.concat(frames, ignore_index=True)
        combined = combined.rename(columns={"날짜": "date", "종가": "close", "거래량": "volume"})
        return combined[["date", "close", "volume"]]
    except Exception as e:
        logger.warning(f"Domestic history fetch failed for {code}: {e}")
        return None


def _screen(candidates: List[Dict], horizon: str) -> List[Dict]:
    ranked = [c for c in candidates if c.get(f"{horizon}_change_pct") is not None]
    ranked.sort(key=lambda c: c[f"{horizon}_change_pct"], reverse=True)
    return ranked[:PICKS_PER_HORIZON]


def get_domestic_picks() -> Dict[str, List[Dict]]:
    """{"daily": [...], "weekly": [...], "monthly": [...]} — 실패 종목은 후보에서 제외, 실패 시 빈 dict."""
    candidates = []
    for code, name in DOMESTIC_WATCHLIST:
        hist = _fetch_domestic_history(code)
        if hist is None:
            continue
        entry = _build_entry("domestic", code, name, hist["close"].tolist(), hist["volume"].tolist())
        if entry:
            candidates.append(entry)

    if not candidates:
        logger.warning("No domestic stock candidates collected — omitting domestic picks")
    return {h: _screen(candidates, h) for h in HORIZONS}


def get_overseas_picks() -> Dict[str, List[Dict]]:
    tickers = list(OVERSEAS_NAMES.keys())
    try:
        data = yf.download(tickers=tickers, period="35d", group_by="ticker", threads=True, progress=False)
    except Exception as e:
        logger.warning(f"yfinance batch download failed — omitting overseas picks: {e}")
        return {h: [] for h in HORIZONS}

    candidates = []
    for symbol in tickers:
        try:
            df = data[symbol][["Close", "Volume"]].dropna()
        except (KeyError, TypeError):
            continue
        if df.empty:
            continue
        closes = df["Close"].tolist()[::-1]
        volumes = df["Volume"].tolist()[::-1]
        entry = _build_entry("overseas", symbol, OVERSEAS_NAMES[symbol], closes, volumes)
        if entry:
            candidates.append(entry)

    if not candidates:
        logger.warning("No overseas stock candidates collected — omitting overseas picks")
    return {h: _screen(candidates, h) for h in HORIZONS}
