"""
News Aggregator
모든 뉴스 소스를 통합하고 카테고리 × 지역(국내/해외)으로 분류
"""
import os
import re
from datetime import datetime, timedelta, timezone
from collections import OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List

from .collectors.rss_collector import RSSCollector
from .collectors.sources import SOURCES, CATEGORIES, CATEGORY_META, REGIONS
from .collectors.base_collector import NewsArticle
from .utils import article_body
from .utils.dedup import normalize_title, load_recent_links, _canonical_link
from .utils.logger import setup_logger
from . import summarizer

# 발행일이 이보다 오래된 기사는 버린다. 피드가 살아 있어도 갱신을 멈춘 곳이 있어
# 3년 전 기사가 그대로 올라왔다(실측: CNN 1217일, WSJ 562일, 경향 과학 513일).
# 죽은 피드를 목록에서 빼는 것과 별개로, 일간 브리핑에는 오래된 기사가 들어오면 안 된다.
MAX_ARTICLE_AGE_DAYS = 3

# 전날 이미 실은 기사를 다시 싣지 않기 위해 되돌아볼 일수
CROSS_DAY_LOOKBACK_DAYS = 7

# 지역별 상한. 예전엔 카테고리당 통합 30건이었는데, 그러면 국내 기사에 밀려
# 해외 기사가 거의 안 보였다.
REGION_ARTICLE_CAP = 20

# 언론사가 정기적으로 내보내는 행정성 공지("N월N일 인사/부고/동정/알림") —
# 한겨레 society 피드에서 실제 확인됨. 뉴스 가치가 없어 통째로 제외한다.
_WIRE_BULLETIN_PATTERN = re.compile(r'^\d{1,2}월\s*\d{1,2}일\s*(궂긴\s*소식|인사|동정|부고|알림|일정)\s*$')

# 같은 매체가 같은 사안을 제목만 조금 바꿔 두 번 내보내는 경우가 있어
# (예: "…발사체 포착" / "…발사체 감지") 제목 토큰 자카드 유사도로 잡는다.
_NEAR_DUP_THRESHOLD = 0.5
_TOKEN_PATTERN = re.compile(r'[가-힣A-Za-z0-9]{2,}')


def _is_wire_bulletin(title: str) -> bool:
    return bool(_WIRE_BULLETIN_PATTERN.match((title or '').strip()))


def _title_tokens(title: str) -> set:
    return set(_TOKEN_PATTERN.findall(title or ''))


class NewsAggregator:
    """뉴스 통합 및 분류 클래스"""

    def __init__(self, raw_data_dir: str = ''):
        self.logger = setup_logger()
        self.raw_data_dir = raw_data_dir

    def collect_all_news(self) -> Dict[str, Dict[str, List[NewsArticle]]]:
        """
        Returns: {카테고리: {"domestic": [...], "overseas": [...]}}

        요약은 카테고리별로 서로 다른 API 키를 써서 8개 카테고리를 동시에 처리한다
        (summarizer.summarize_all) — 키가 카테고리마다 다르면 rate limit이 나뉘어
        전체 실행 시간이 카테고리 수만큼 짧아진다.
        """
        self.logger.info("Starting news collection...")
        buckets = self._collect_raw()

        # 본문 수집은 카테고리 경계와 무관하게 한 번에 — 전역 시간 예산을 쓰므로
        # 카테고리별로 나눠 부르면 예산 관리가 어려워진다
        selected = [a for regions in buckets.values() for arts in regions.values() for a in arts]
        self.logger.info(f"Selected {len(selected)} articles; fetching article bodies...")
        if os.getenv('NVIDIA_API_KEY') or os.getenv('NVIDIA_API_KEY_POLITICS'):
            article_body.enrich(selected)

        summarizer.summarize_all(buckets)

        for category, regions in buckets.items():
            for region in REGIONS:
                # is_important는 요약 단계에서 확정되므로 여기서 최종 정렬
                regions[region].sort(key=lambda x: (x.is_important, x.published), reverse=True)
            self.logger.info(
                f"  {category}: 국내 {len(regions['domestic'])} / 해외 {len(regions['overseas'])}"
            )

        return buckets

    def _collect_raw(self) -> Dict[str, Dict[str, List[NewsArticle]]]:
        """수집 → 오래된/전날 기사 제거 → 공지성 제거 → 중복 제거 → 매체 균형 선별."""
        raw = {key: {region: [] for region in REGIONS} for key in CATEGORIES}
        seen_before = load_recent_links(self.raw_data_dir, CROSS_DAY_LOOKBACK_DAYS)
        cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_ARTICLE_AGE_DAYS)
        dropped = {'old': 0, 'seen': 0}

        def fetch(job):
            source, category = job
            collector = RSSCollector(
                source["id"], source["name"], source["feeds"], source.get("language", "ko")
            )
            try:
                articles = collector.collect(category, limit=source.get("limit", 15))
            except Exception as e:
                self.logger.warning(f"[{source['id']}] failed category {category}: {e}")
                return source, category, []
            kept = []
            for article in articles:
                article.language = source.get("language", "ko")
                article.region = source.get("region", "domestic")
                if _is_wire_bulletin(article.title):
                    continue
                # 발행일이 추정치인 건(피드에 날짜가 없는 매체) 나이로 거르지 않는다 —
                # 나중에 기사 메타로 교정되므로 여기서 버리면 멀쩡한 기사를 잃는다
                if not article.date_is_approximate and article.published < cutoff:
                    dropped['old'] += 1
                    continue
                if _canonical_link(article.link) in seen_before:
                    dropped['seen'] += 1
                    continue
                kept.append(article)
            return source, category, kept

        jobs = [(s, c) for s in SOURCES for c in s["feeds"]]
        # 피드 수가 늘어 순차 수집이면 그것만 몇 분 걸린다 — 네트워크 대기라 병렬이 안전
        with ThreadPoolExecutor(max_workers=12) as pool:
            for source, category, articles in pool.map(fetch, jobs):
                raw[category][source.get("region", "domestic")].extend(articles)

        self.logger.info(
            f"Filtered out {dropped['old']} stale (>{MAX_ARTICLE_AGE_DAYS}d) "
            f"and {dropped['seen']} already-published articles "
            f"({len(seen_before)} links seen in last {CROSS_DAY_LOOKBACK_DAYS} days)"
        )

        for category in CATEGORIES:
            for region in REGIONS:
                articles = self._remove_duplicates(raw[category][region])
                raw[category][region] = self._select_balanced(articles, REGION_ARTICLE_CAP)
        return raw

    def _remove_duplicates(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """
        정규화 제목 완전일치 + 같은 매체 내 근사 중복 제거.
        근사 중복은 요약이 더 긴(= 내용이 더 상세한) 쪽을 남긴다.
        """
        unique = OrderedDict()
        for article in articles:
            key = normalize_title(article.title)
            existing = unique.get(key)
            if existing is None or len(article.summary or '') > len(existing.summary or ''):
                unique[key] = article

        kept: List[NewsArticle] = []
        tokens_by_source = defaultdict(list)
        for article in unique.values():
            tokens = _title_tokens(article.title)
            duplicate_of = None
            for index, seen_tokens in tokens_by_source[article.source]:
                union = tokens | seen_tokens
                if union and len(tokens & seen_tokens) / len(union) >= _NEAR_DUP_THRESHOLD:
                    duplicate_of = index
                    break

            if duplicate_of is None:
                tokens_by_source[article.source].append((len(kept), tokens))
                kept.append(article)
            elif len(article.summary or '') > len(kept[duplicate_of].summary or ''):
                kept[duplicate_of] = article  # 더 상세한 쪽으로 교체

        return kept

    def _select_balanced(self, articles: List[NewsArticle], cap: int) -> List[NewsArticle]:
        """
        매체별로 최신순 정렬한 뒤 라운드로빈으로 뽑는다.
        단순 최신순 상위 N을 자르면 발행이 잦은 매체 한두 곳이 전부 차지한다
        (실측: 경제·문화 카테고리가 매체 2곳으로만 채워졌다).
        """
        by_source = defaultdict(list)
        for article in articles:
            by_source[article.source].append(article)
        for group in by_source.values():
            group.sort(key=lambda a: a.published, reverse=True)

        # 최신 기사를 가진 매체부터 돌아 같은 순번끼리는 최신순이 되게 한다
        order = sorted(by_source.values(), key=lambda g: g[0].published, reverse=True)
        selected = []
        for rank in range(max((len(g) for g in order), default=0)):
            for group in order:
                if rank < len(group):
                    selected.append(group[rank])
                    if len(selected) >= cap:
                        return selected
        return selected
