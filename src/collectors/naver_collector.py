import logging
from typing import List
from .base_collector import BaseCollector, NewsArticle
from ..utils.rss_utils import fetch_feed, clean_html, extract_date


class NaverCollector(BaseCollector):

    RSS_FEEDS = {
    "top": "https://news.naver.com/officelist/rss.nhn?type=ranking&office=001",

    "politics": "https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=100",
    "economy": "https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=101",
    "society": "https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=102",
    "world": "https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=104",
    "it": "https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=105",
}


    def __init__(self):
        super().__init__("네이버 뉴스")
        self.logger = logging.getLogger(__name__)

    def collect(self, category="top", limit=15) -> List[NewsArticle]:

        url = self.RSS_FEEDS.get(category, self.RSS_FEEDS["top"])
        feed = fetch_feed(url)

        if not feed or not feed.entries:
            self.logger.warning(f"Naver feed empty: {category}")
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


