"""
Market Indicators
"주요 지표"(국내+해외 지수를 한데 모음) + "환율"(달러/유로/엔/위안) 2개 그룹으로
제공한다. 국내 지수는 Naver Finance 일별 시세, 환율은 Naver 모바일 marketIndex
API(통화별 10일치 히스토리 제공), 해외 지수는 yfinance 배치 다운로드 —
전부 무료·키 불필요.

스파크라인은 차트 라이브러리 없이 서버에서 직접 그린 작은 인라인 SVG 폴리라인이다
(값 몇 개로 그리는 추이선이라 별도 JS 차트 라이브러리를 붙일 필요가 없다).

값은 build 시점 스냅샷이다. 장중 갱신은 update_indicators.py를 15분마다 돌리는
별도 워크플로가 docs/indicators.json을 덮어쓰고 site.js가 그걸 읽어 숫자만
바꿔치기하는 방식으로 처리한다 — GitHub Pages가 정적 호스팅이고 Naver API가
CORS를 허용하지 않아(실측 확인) 브라우저에서 직접 호출할 수 없기 때문.
"""
import json
import os
from datetime import datetime, timedelta, timezone
from io import StringIO
from typing import Dict, List, Optional

import pandas as pd
import requests
import yfinance as yf

from .logger import setup_logger

logger = setup_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.naver.com"}
_REQUEST_TIMEOUT = 6
_HISTORY_DAYS = 7
_KST = timezone(timedelta(hours=9))

_DOMESTIC_INDEX_CODES = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}
_OVERSEAS_TICKERS = {
    "^IXIC": "나스닥", "^DJI": "다우존스", "^GSPC": "S&P500", "^N225": "니케이225",
}
_FX_CODES = {
    "FX_USDKRW": "달러 / USD",
    "FX_EURKRW": "유로 / EUR",
    "FX_JPYKRW": "엔 / JPY (100엔)",
    "FX_CNYKRW": "위안 / CNY",
}
_FX_URL = ("https://m.stock.naver.com/front-api/marketIndex/prices"
           "?category=exchange&reutersCode={code}&page=1&pageSize=10")

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


def _item(key: str, name: str, value: str, pct: float, history: List[float]) -> Dict:
    """key는 site.js가 장중 갱신 때 DOM 노드를 찾는 데 쓴다 — 이름 바꾸면 JS도 같이."""
    return {
        "key": key,
        "name": name,
        "value": value,
        "pct": f"{pct:+.2f}%",
        "dir": _dir_from_pct(pct),
        "sparkline_svg": _sparkline_svg(history),
    }


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


def _get_domestic_indices() -> List[Dict]:
    results = []
    for code, name in _DOMESTIC_INDEX_CODES.items():
        try:
            history = _fetch_domestic_index_history(code)
        except Exception as e:
            logger.warning(f"Domestic index history fetch failed for {code}: {e}")
            continue
        if len(history) < 2:
            continue
        latest, prev = history[-1], history[-2]
        pct = round((latest - prev) / prev * 100, 2) if prev else 0.0
        results.append(_item(code, name, f"{latest:,.2f}", pct, history))
    return results


def _get_overseas_indices() -> List[Dict]:
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
        results.append(_item(ticker.lstrip("^"), name, f"{latest:,.2f}", pct, history))
    return results


def _to_float(price) -> float:
    return float(str(price).replace(",", ""))


def _get_fx() -> List[Dict]:
    """통화별로 독립 실패 처리 — 한 통화가 죽어도 나머지는 표시."""
    results = []
    for code, name in _FX_CODES.items():
        try:
            resp = requests.get(_FX_URL.format(code=code), headers=_HEADERS,
                                 timeout=_REQUEST_TIMEOUT)
            resp.raise_for_status()
            rows = resp.json()["result"]
            if not rows:
                continue
            # 응답은 최신순 — 스파크라인용으로 뒤집어 오래된→최신으로 만든다
            history = [_to_float(r["closePrice"]) for r in rows[:_HISTORY_DAYS]][::-1]
            latest = rows[0]
            results.append(_item(
                code.replace("FX_", ""), name, latest["closePrice"],
                float(latest["fluctuationsRatio"]), history,
            ))
        except Exception as e:
            logger.warning(f"FX fetch failed for {code}: {e}")
    return results


def get_market_indicators() -> Optional[Dict]:
    """
    {"main": [...], "fx": [...], "as_of": "2026-08-03 06:05"} 형태.
    각 그룹은 독립적으로 실패 처리 — 한쪽이 죽어도 나머지는 표시한다.
    """
    main, fx = [], []
    try:
        main.extend(_get_domestic_indices())
    except Exception as e:
        logger.warning(f"Domestic indices fetch failed: {e}")

    try:
        main.extend(_get_overseas_indices())
    except Exception as e:
        logger.warning(f"Overseas indices fetch failed: {e}")

    try:
        fx = _get_fx()
    except Exception as e:
        logger.warning(f"FX fetch failed: {e}")

    if not main and not fx:
        return None
    return {
        "main": main,
        "fx": fx,
        "as_of": datetime.now(_KST).strftime("%Y-%m-%d %H:%M"),
    }


def write_indicators_json(indicators: Optional[Dict], path: str) -> bool:
    """
    site.js가 장중에 읽어가는 파일을 쓴다. 조회가 통째로 실패해 indicators가 None이면
    기존 파일을 지우지 않고 그대로 둔다 — 마지막으로 성공한 값이 남는 게
    빈 화면보다 낫다.
    """
    if not indicators:
        logger.warning("No indicator data — leaving existing indicators.json untouched")
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(indicators, f, ensure_ascii=False, separators=(",", ":"))
    return True
