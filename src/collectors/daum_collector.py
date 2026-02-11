import logging
from typing import List
from .base_collector import BaseCollector, NewsArticle
from ..utils.rss_utils import fetch_feed, clean_html, extract_date


class DaumCollector(BaseCollector):
    """다음 뉴스 수집기"""
    
    RSS_FEEDS = {
        "top": "https://news.daum.net/rss/popular",
        "politics": "https://news.daum.net/rss/politics",
        "economic": "https://news.daum.net/rss/economic",
        "society": "https://news.daum.net/rss/society",
        "world": "https://news.daum.net/rss/foreign",
        "it": "https://news.daum.net/rss/digital",
    }

    def __init__(self):
        super().__init__("다음 뉴스")
        self.logger = logging.getLogger(__name__)

    def collect(self, category="top", limit=15) -> List[NewsArticle]:
        """
        뉴스 수집
        
        Args:
            category: 카테고리
            limit: 수집할 뉴스 개수
            
        Returns:
            List[NewsArticle]: 수집된 뉴스 리스트
        """
        url = self.RSS_FEEDS.get(category, self.RSS_FEEDS["top"])
        self.logger.info(f"Fetching Daum news from: {url}")
        
        feed = fetch_feed(url)

        if not feed or not feed.entries:
            self.logger.warning(f"Daum feed empty: {category} from {url}")
            return []

        articles = []
        self.logger.info(f"Found {len(feed.entries)} entries in feed")

        for entry in feed.entries[:limit]:
            try:
                summary = clean_html(entry.get("description", ""))
                
                article = NewsArticle(
                    title=entry.get("title", "").strip(),
                    link=entry.get("link", ""),
                    published=extract_date(entry, self._parse_date),
                    summary=summary,
                    source=self.source_name,
                    category=category,
                )

                articles.append(article)
                self.logger.debug(f"Collected: {article.title[:50]}...")
                
            except Exception as e:
                self.logger.error(f"Error parsing entry: {e}")
                continue

        self.logger.info(f"Successfully collected {len(articles)} articles from {category}")
        return articles
