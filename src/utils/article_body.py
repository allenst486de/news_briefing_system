"""
Article Body Extraction
RSS description만으로는 요약 근거가 부족한 문제를 보완한다 — 실측 결과 국제
카테고리 17건 중 83자짜리 요약문이 있었고, 83자를 250자로 "요약"하는 건 불가능하다
(늘려 쓰면 환각 금지 규칙 위반). 그래서 원문 링크에서 본문 텍스트를 가져와
요약 입력으로 쓴다.

가져오지 못하면 조용히 None을 반환하고 호출부가 기존 RSS 요약문을 그대로 쓴다 —
언론사가 봇을 차단하거나 레이아웃이 달라도 파이프라인이 멈추지 않는다.
전체 시간 예산(_BUDGET_SECONDS)을 두어 느린 사이트가 실행 시간을 잡아먹지 않게 한다.
"""
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import requests
from lxml import html as lxml_html

from .logger import setup_logger

logger = setup_logger()

_HEADERS = {"User-Agent": "Mozilla/5.0 (NewsAggregator Bot)"}
_TIMEOUT = 5
_WORKERS = 8
# 실행 '전체'에 걸친 예산이다. 카테고리마다 새로 잡으면 8배가 되어 워크플로
# 30분 제한을 혼자서 넘긴다(실제로 넘겨서 run이 취소됐다).
_TOTAL_BUDGET_SECONDS = 300
_deadline = None

# RSS 요약문이 이보다 짧으면(또는 …로 잘려 있으면) 본문을 시도한다
_SHORT_SUMMARY_CHARS = 300
_MIN_BODY_CHARS = 400
_MAX_BODY_CHARS = 1500

_DROP_XPATH = (
    '//script | //style | //noscript | //nav | //header | //footer | //aside '
    '| //form | //iframe | //figure | //figcaption'
)
_CONTAINER_XPATH = (
    '//article'
    ' | //div[contains(@id, "article") or contains(@class, "article")]'
    ' | //div[contains(@id, "content") or contains(@class, "content")]'
    ' | //div[contains(@class, "news_body") or contains(@class, "articleBody")]'
)


# 문장 종결 밀도로 '본문'과 '관련기사 헤드라인 목록'을 가른다. 실측(12개 매체):
# 헤드라인 목록/내비게이션은 0.08~0.61, 실제 기사 본문은 0.87~4.25로 뚜렷이 갈렸다.
_SENTENCE_END = re.compile(r"[.!?]|다\s|음\s|죠\s")
_MIN_PROSE_SCORE = 0.75


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _prose_score(text: str) -> float:
    """100자당 문장 종결 개수."""
    return len(_SENTENCE_END.findall(text)) / max(len(text) / 100, 1)


def _paragraph_text(node) -> str:
    return _clean(" ".join(p.text_content() for p in node.xpath(".//p")))


def _node_text(node) -> str:
    """
    <p>로 문단을 나눈 사이트(BBC/Guardian 등)는 <p>만 모으는 게 깔끔하지만,
    연합뉴스TV처럼 본문을 <p> 없이 div에 그대로 넣는 곳도 있다(실측). 문단
    텍스트가 빈약하면 컨테이너 전체 텍스트를 쓴다.
    """
    para = _paragraph_text(node)
    if len(para) >= _MIN_BODY_CHARS:
        return para
    return _clean(node.text_content())


def fetch_body(url: str) -> Optional[str]:
    """기사 본문 텍스트. 못 가져오면 None."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
        if not resp.ok or not resp.content:
            return None

        tree = lxml_html.fromstring(resp.content)
        for el in tree.xpath(_DROP_XPATH):
            parent = el.getparent()
            if parent is not None:
                parent.remove(el)

        # 충분히 길고(_MIN_BODY_CHARS) 산문다운(_MIN_PROSE_SCORE) 후보 중
        # 가장 작은 것을 고른다 — 바깥 래퍼일수록 메뉴/공유버튼이 섞이므로 작을수록 좋고,
        # 산문 점수는 '관련기사 헤드라인 목록'을 본문으로 착각하는 걸 막는다.
        candidates = [
            text for text in (_node_text(n) for n in tree.xpath(_CONTAINER_XPATH))
            if len(text) >= _MIN_BODY_CHARS and _prose_score(text) >= _MIN_PROSE_SCORE
        ]
        if candidates:
            return min(candidates, key=len)[:_MAX_BODY_CHARS]

        # 컨테이너를 못 찾는 레이아웃 — 문서 전체 <p>로 폴백
        fallback = _paragraph_text(tree)
        return fallback[:_MAX_BODY_CHARS] if len(fallback) >= _MIN_BODY_CHARS else None
    except Exception:
        return None


def needs_body(article) -> bool:
    summary = (article.summary or "").strip()
    return len(summary) < _SHORT_SUMMARY_CHARS or summary.endswith(("...", "…"))


def enrich(articles: List) -> int:
    """
    요약 근거가 부족한 기사에 article.body를 채운다 (in-place).
    반환값은 실제로 본문을 확보한 건수.
    """
    global _deadline
    if _deadline is None:
        _deadline = time.monotonic() + _TOTAL_BUDGET_SECONDS

    targets = [a for a in articles if a.link and needs_body(a)]
    if not targets:
        return 0
    if time.monotonic() > _deadline:
        logger.warning("Article body budget already spent — using RSS summaries")
        return 0

    filled = 0
    with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
        futures = {pool.submit(fetch_body, a.link): a for a in targets}
        for future in as_completed(futures):
            if time.monotonic() > _deadline:
                # 남은 건은 포기 — RSS 요약문으로 진행한다
                for f in futures:
                    f.cancel()
                logger.warning("Article body fetch budget exhausted — using RSS summaries for the rest")
                break
            article = futures[future]
            try:
                body = future.result()
            except Exception:
                body = None
            if body:
                article.body = body
                filled += 1

    logger.info(f"Article bodies fetched: {filled}/{len(targets)} attempted")
    return filled
