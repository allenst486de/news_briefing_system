import logging
from typing import List
from .base_collector import BaseCollector, NewsArticle
from ..utils.rss_utils import fetch_feed, clean_html, extract_date


class DaumCollector(BaseCollector):

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

        url = self.RSS_FEEDS.get(category, self.RSS_FEEDS["top"])
        feed = fetch_feed(url)

        if not feed or not feed.entries:
            self.logger.warning(f"Daum feed empty: {category}")
            return []

        articles = []

        for entry in feed.entries[:limit]:

            summary = clean_html(entry.get("description"))

            article = NewsArticle(
                title=entry.get("title", "").strip(),
                link=entry.get("link", ""),
                published=extract_date(entry, self._parse_date),
                summary=summary,
                source=self.source_name,
                category=category,
            )

            articles.append(article)

        return articles


