"""
News Aggregator
모든 뉴스 소스를 통합하고 카테고리별로 분류
"""
from typing import List, Dict
from .collectors.rss_collector import RSSCollector
from .collectors.sources import SOURCES, CATEGORIES
from .collectors.base_collector import NewsArticle
from .utils.importance_analyzer import ImportanceAnalyzer
from .utils.translator import translate_article
from .utils.dedup import normalize_title
from .utils.logger import setup_logger

CATEGORY_ARTICLE_CAP = 20


class NewsAggregator:
    """뉴스 통합 및 분류 클래스"""

    def __init__(self):
        self.logger = setup_logger()
        self.analyzer = ImportanceAnalyzer()

    def collect_all_news(self) -> Dict[str, List[NewsArticle]]:
        """
        모든 소스에서 뉴스를 수집하고 카테고리별로 분류

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

                    if source.get("language") == "en":
                        articles = self._translate_articles(articles)

                    categorized_news[category].extend(articles)
                except Exception as e:
                    self.logger.warning(f"[{source['id']}] failed category {category}: {e}")
                    continue

        self.logger.info("Processing collected news...")
        for category in categorized_news:
            categorized_news[category] = self._process_articles(
                categorized_news[category], category
            )
            categorized_news[category] = self._remove_duplicates(categorized_news[category])
            categorized_news[category].sort(key=lambda x: x.published, reverse=True)
            categorized_news[category] = categorized_news[category][:CATEGORY_ARTICLE_CAP]

        self.logger.info(f"News collection completed. Total categories: {len(categorized_news)}")
        for category, articles in categorized_news.items():
            self.logger.info(f"  {category}: {len(articles)} articles")

        return categorized_news

    def _translate_articles(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """해외 뉴스 기사를 한국어로 번역"""
        translated_articles = []
        for article in articles:
            try:
                translated_articles.append(translate_article(article))
            except Exception as e:
                self.logger.warning(f"Translation failed for article: {article.title[:50]}... Error: {e}")
                translated_articles.append(article)
        return translated_articles

    def _process_articles(self, articles: List[NewsArticle], category: str) -> List[NewsArticle]:
        """기사 리스트를 처리하고 중요도(+IT는 AI 여부) 분석"""
        for article in articles:
            article.is_important = self.analyzer.analyze(article.title, article.summary)
            if category == "it":
                article.is_ai = self.analyzer.is_ai_related(article.title, article.summary)
        return articles

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
