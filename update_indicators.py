"""
Indicator-only refresh
docs/indicators.json만 갱신한다 (뉴스 수집/LLM/텔레그램은 건드리지 않음).
.github/workflows/indicators.yml이 장중 15분마다 실행하고, 페이지의 site.js가
같은 도메인에서 이 파일을 읽어 숫자를 바꿔치기한다.

지표 조회가 통째로 실패하면 기존 파일을 그대로 두고 조용히 종료한다 —
15분 뒤 다시 시도하면 되므로 워크플로를 실패로 만들 이유가 없다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils.indicators import get_market_indicators, write_indicators_json
from src.utils.logger import setup_logger


def main() -> None:
    logger = setup_logger()
    output = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'indicators.json')

    indicators = get_market_indicators()
    if write_indicators_json(indicators, output):
        counts = f"main={len(indicators['main'])} fx={len(indicators['fx'])}"
        logger.info(f"indicators.json updated ({counts}, as_of={indicators['as_of']})")
    else:
        logger.warning("Indicator refresh produced no data — previous file kept")


if __name__ == '__main__':
    main()
