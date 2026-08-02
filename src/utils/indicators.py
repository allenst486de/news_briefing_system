"""
Market Indicators
홈 화면/경제 대시보드에 쓰는 국내+해외 주요 지수 + 최근 추이 스파크라인.
국내(KOSPI/KOSDAQ)는 Naver Finance 일별 시세 페이지, USD/KRW는 폴링 엔드포인트,
해외(다우/나스닥/S&P500/니케이225)는 yfinance 배치 다운로드 — 전부 무료·키 불필요.

스파크라인은 차트 라이브러리 없이 서버에서 직접 그린 작은 인라인 SVG 폴리라인이다
(값 몇 개로 그리는 추이선이라 별도 JS 차트 라이브러리를 붙일 필요가 없다).
"""
from io import StringIO
from typing import Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf

from .logger import setup_logger

logger = setup_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com"}
_FX_URL = "https://m.stock.naver.com/front-api/marketIndex/prices?category=exchange&reutersCode=FX_USDKRW"
_REQUEST_TIMEOUT = 6
_HISTORY_DAYS = 7

_DOMESTIC_INDEX_CODES = ["KOSPI", "KOSDAQ"]
_OVERSEAS_TICKERS = {
    "^DJI": "다우존스", "^IXIC": "나스닥", "^GSPC": "S&P500", "^N225": "니케이225",
}

_UP_COLOR = "#ef4444"
_DOWN_COLOR = "#3b82f6"
_FLAT_COLOR = "#8890a3"


def _dir_from_pct(pct: float) -> str:
    if pct > 0:
        return "up"
    if pct < 0:
        return "down"
    return "flat"


def _sparkline_svg(values: List[float], width: int = 84, height: int = 28) -> str:
    """오래된→최신 순 값 목록으로 작은 추이선 SVG를 그린다. 2개 미만이면 빈 문자열."""
    if len(values) < 2:
        return ""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / (len(values) - 1)
    pad = 3
    points = " ".join(
        f"{i * step:.1f},{height - pad - ((v - lo) / span) * (height - pad * 2):.1f}"
        for i, v in enumerate(values)
    )
    color = _UP_COLOR if values[-1] > values[0] else (_DOWN_COLOR if values[-1] < values[0] else _FLAT_COLOR)
    return (
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" class="sparkline" '
        f'aria-hidden="true"><polyline points="{points}" fill="none" stroke="{color}" '
        f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>'
    )


def _fetch_domestic_index_history(code: str, days: int = _HISTORY_DAYS) -> List[float]:
    """최근 거래일 종가 목록, 오래된→최신 순. 실패 시 빈 리스트."""
    resp = requests.get(
        f"https://finance.naver.com/sise/sise_index_day.naver?code={code}&page=1",
        headers=_HEADERS, timeout=_REQUEST_TIMEOUT,
    )
    resp.encoding = "euc-kr"
    tables = pd.read_html(StringIO(resp.text))
    df = tables[0].dropna()
    closes = df["체결가"].tolist()[:days]
    return list(reversed(closes))


def _get_domestic() -> List[Dict]:
    results = []
    for code in _DOMESTIC_INDEX_CODES:
        try:
            history = _fetch_domestic_index_history(code)
        except Exception as e:
            logger.warning(f"Domestic index history fetch failed for {code}: {e}")
            history = []
        if len(history) < 2:
            continue
        latest, prev = history[-1], history[-2]
        pct = round((latest - prev) / prev * 100, 2) if prev else 0.0
        results.append({
            "name": code,
            "value": f"{latest:,.2f}",
            "pct": f"{pct:+.2f}%",
            "dir": _dir_from_pct(pct),
            "sparkline_svg": _sparkline_svg(history),
        })

    try:
        fx_resp = requests.get(_FX_URL, headers=_HEADERS, timeout=_REQUEST_TIMEOUT)
        fx_resp.raise_for_status()
        fx = fx_resp.json()["result"][0]
        results.append({
            "name": "USD/KRW",
            "value": fx["closePrice"],
            "pct": f"{fx['fluctuationsRatio']}%",
            "dir": "up" if fx["fluctuationsType"]["text"] == "상승" else (
                "down" if fx["fluctuationsType"]["text"] == "하락" else "flat"),
            "sparkline_svg": "",  # 환율은 히스토리 엔드포인트가 따로 없어 그래프 생략
        })
    except Exception as e:
        logger.warning(f"USD/KRW fetch failed: {e}")

    return results


def _get_overseas() -> List[Dict]:
    tickers = list(_OVERSEAS_TICKERS.keys())
    data = yf.download(tickers=tickers, period="10d", group_by="ticker", threads=True,
                        progress=False, timeout=_REQUEST_TIMEOUT)
    results = []
    for ticker, name in _OVERSEAS_TICKERS.items():
        try:
            closes = data[ticker]["Close"].dropna().tolist()
        except (KeyError, TypeError):
            continue
        if len(closes) < 2:
            continue
        history = closes[-_HISTORY_DAYS:]
        latest, prev = history[-1], history[-2]
        pct = round((latest - prev) / prev * 100, 2) if prev else 0.0
        results.append({
            "name": name,
            "value": f"{latest:,.2f}",
            "pct": f"{pct:+.2f}%",
            "dir": _dir_from_pct(pct),
            "sparkline_svg": _sparkline_svg(history),
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
