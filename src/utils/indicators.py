"""
Market Indicators
홈 화면/경제 대시보드에 쓰는 국내+해외 주요 지수.
국내(KOSPI/KOSDAQ/USD-KRW)는 Naver Finance 폴링 엔드포인트,
해외(다우/나스닥/S&P500/니케이225)는 yfinance 배치 다운로드 — 둘 다 무료·키 불필요.
"""
from typing import Dict, List, Optional
import requests
import yfinance as yf
from .logger import setup_logger

logger = setup_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com"}
_INDEX_URL = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ"
_FX_URL = "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW"
_REQUEST_TIMEOUT = 6

_OVERSEAS_TICKERS = {
    "^DJI": "다우존스", "^IXIC": "나스닥", "^GSPC": "S&P500", "^N225": "니케이225",
}


def _direction(text: str) -> str:
    return "up" if text == "상승" else ("down" if text == "하락" else "flat")


def _dir_from_pct(pct: float) -> str:
    if pct > 0:
        return "up"
    if pct < 0:
        return "down"
    return "flat"


def _get_domestic() -> List[Dict]:
    index_resp = requests.get(_INDEX_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
    index_resp.raise_for_status()
    index_data = {d["itemCode"]: d for d in index_resp.json()["datas"]}
    kospi, kosdaq = index_data["KOSPI"], index_data["KOSDAQ"]

    fx_resp = requests.get(_FX_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
    fx_resp.raise_for_status()
    fx = fx_resp.json()["result"][0]

    return [
        {"name": "KOSPI", "value": kospi["closePrice"], "pct": f"{kospi['fluctuationsRatio']}%",
         "dir": _direction(kospi["compareToPreviousPrice"]["text"])},
        {"name": "KOSDAQ", "value": kosdaq["closePrice"], "pct": f"{kosdaq['fluctuationsRatio']}%",
         "dir": _direction(kosdaq["compareToPreviousPrice"]["text"])},
        {"name": "USD/KRW", "value": fx["closePrice"], "pct": f"{fx['fluctuationsRatio']}%",
         "dir": _direction(fx["fluctuationsType"]["text"])},
    ]


def _get_overseas() -> List[Dict]:
    tickers = list(_OVERSEAS_TICKERS.keys())
    data = yf.download(tickers=tickers, period="5d", group_by="ticker", threads=True,
                        progress=False, timeout=_REQUEST_TIMEOUT)
    results = []
    for ticker, name in _OVERSEAS_TICKERS.items():
        try:
            closes = data[ticker]["Close"].dropna().tolist()
        except (KeyError, TypeError):
            continue
        if len(closes) < 2:
            continue
        latest, prev = closes[-1], closes[-2]
        pct = round((latest - prev) / prev * 100, 2) if prev else 0.0
        results.append({
            "name": name,
            "value": f"{latest:,.2f}",
            "pct": f"{pct:+.2f}%",
            "dir": _dir_from_pct(pct),
        })
    return results


def get_market_indicators() -> Optional[Dict[str, List[Dict]]]:
    """국내/해외 각각 독립적으로 실패 처리 — 한쪽이 죽어도 나머지는 표시."""
    domestic, overseas = [], []
    try:
        domestic = _get_domestic()
    except Exception as e:
        logger.warning(f"Domestic indicators fetch failed: {e}")

    try:
        overseas = _get_overseas()
    except Exception as e:
        logger.warning(f"Overseas indicators fetch failed: {e}")

    if not domestic and not overseas:
        return None
    return {"domestic": domestic, "overseas": overseas}
