"""
Market Indicators
홈 화면 상단 티커에 쓰는 KOSPI/KOSDAQ/USD-KRW 현재가.
Phase1에서는 종목 추천(pykrx/yfinance, Phase3)과 분리된 가벼운 조회이므로
새 의존성 없이 requests만으로 Naver Finance 공개 폴링 엔드포인트를 사용한다.
"""
from typing import Dict, Optional
import requests
from .logger import setup_logger

logger = setup_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com"}
_INDEX_URL = "https://polling.finance.naver.com/api/realtime/domestic/index/KOSPI,KOSDAQ"
_FX_URL = "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW"


def _direction(text: str) -> str:
    return "up" if text == "상승" else ("down" if text == "하락" else "flat")


def get_market_indicators() -> Optional[Dict[str, str]]:
    """실패 시 None — 호출부(html_generator)가 티커 블록을 통째로 생략하도록."""
    try:
        index_resp = requests.get(_INDEX_URL, headers=_HEADERS, timeout=10)
        index_resp.raise_for_status()
        index_data = {d["itemCode"]: d for d in index_resp.json()["datas"]}
        kospi, kosdaq = index_data["KOSPI"], index_data["KOSDAQ"]

        fx_resp = requests.get(_FX_URL, headers=_HEADERS, timeout=10)
        fx_resp.raise_for_status()
        fx = fx_resp.json()["result"][0]

        return {
            "kospi": kospi["closePrice"],
            "kospi_pct": f"{kospi['fluctuationsRatio']}%",
            "kospi_dir": _direction(kospi["compareToPreviousPrice"]["text"]),
            "kosdaq": kosdaq["closePrice"],
            "kosdaq_pct": f"{kosdaq['fluctuationsRatio']}%",
            "kosdaq_dir": _direction(kosdaq["compareToPreviousPrice"]["text"]),
            "usdkrw": fx["closePrice"],
            "usdkrw_pct": f"{fx['fluctuationsRatio']}%",
            "usdkrw_dir": _direction(fx["fluctuationsType"]["text"]),
        }
    except Exception as e:
        logger.warning(f"Market indicators fetch failed, omitting ticker: {e}")
        return None
