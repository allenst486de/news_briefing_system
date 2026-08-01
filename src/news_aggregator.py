"""
News Aggregator
모든 뉴스 소스를 통합하고 카테고리별로 분류
"""
from typing import List, Dict
from .collectors.rss_collector import RSSCollector
from .collectors.sources import SOURCES, CATEGORIES
from .collectors.base_collector import NewsArticle
from .utils.dedup import normalize_title
from .utils.logger import setup_logger
from . import summarizer
from .collectors.sources import CATEGORY_META

CATEGORY_ARTICLE_CAP = 20


class NewsAggregator:
    """뉴스 통합 및 분류 클래스"""

    def __init__(self):
        self.logger = setup_logger()

    def collect_all_news(self) -> Dict[str, List[NewsArticle]]:
        """
        모든 소스에서 뉴스를 수집하고 카테고리별로 분류.
        번역/재구성/250자 요약은 카테고리당 1회 LLM 배치 호출로 처리하며
        (summarizer.summarize_category), 실패 시 규칙기반으로 자동 폴백한다.

        Returns:
            Dict[str, List[NewsArticle]]: 카테고리별 뉴스 딕셔너리
        """
        self.logger.info("Starting news collection...")

        categorized_news = {key: [] for key in CATEGORIES}

        for source in SOURCES:
            collector = RSSCollector(
                source["id"], source["name"], source["feeds"], source.get("language", "ko")
            )
            for category in source["feeds"]:
                try:
                    self.logger.info(f"Collecting {source['id']}/{category}...")
                    articles = collector.collect(category, limit=source.get("limit", 15))
                    for article in articles:
                        article.language = source.get("language", "ko")
                    categorized_news[category].extend(articles)
                except Exception as e:
                    self.logger.warning(f"[{source['id']}] failed category {category}: {e}")
                    continue

        self.logger.info("Processing collected news...")
        for category in categorized_news:
            categorized_news[category] = self._remove_duplicates(categorized_news[category])
            categorized_news[category].sort(key=lambda x: x.published, reverse=True)
            categorized_news[category] = categorized_news[category][:CATEGORY_ARTICLE_CAP]

            self.logger.info(f"Summarizing {category} ({len(categorized_news[category])} articles)...")
            categorized_news[category] = summarizer.summarize_category(
                category, CATEGORY_META[category]['name'], categorized_news[category]
            )

            if category == "it":
                summarizer.extract_ai_items(categorized_news[category])

        self.logger.info(f"News collection completed. Total categories: {len(categorized_news)}")
        for category, articles in categorized_news.items():
            self.logger.info(f"  {category}: {len(articles)} articles")

        return categorized_news

    def _remove_duplicates(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """중복 기사 제거 (정규화된 제목 기준)"""
        seen_titles = set()
        unique_articles = []

        for article in articles:
            normalized = normalize_title(article.title)
            if normalized not in seen_titles:
                seen_titles.add(normalized)
                unique_articles.append(article)

        return unique_articles
