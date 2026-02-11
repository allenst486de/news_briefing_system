import logging
from typing import List
from .base_collector import BaseCollector, NewsArticle
from ..utils.rss_utils import fetch_feed, clean_html, extract_date


class DaumCollector(BaseCollector):
    """구글 뉴스 수집기 (다음 뉴스 대체)"""
    
    # 구글 뉴스 RSS 피드 (헤드라인)
    RSS_FEEDS = {
        "top": "https://news.google.com/rss?hl=ko&gl=KR&ceid=KR:ko",  # 주요뉴스
        "politics": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtdHZLQUFQAQ?hl=ko&gl=KR&ceid=KR:ko",  # 정치
        "economic": "https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSnJieWdBUAE?hl=ko&gl=KR&ceid=KR:ko",  # 경제
        "society": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRGs0ZDNJU0FtdHZLQUFQAQ?hl=ko&gl=KR&ceid=KR:ko",  # 사회
        "world": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",  # 국제
        "it": "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",  # 과학/기술
    }

    def __init__(self):
        super().__init__("구글 뉴스")
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
        self.logger.info(f"Fetching Google News from: {url}")
        
        feed = fetch_feed(url)

        if not feed or not feed.entries:
            self.logger.warning(f"Google News feed empty: {category} from {url}")
            return []

        articles = []
        self.logger.info(f"Found {len(feed.entries)} entries in feed")

        for entry in feed.entries[:limit]:
            try:
                # 구글 뉴스는 description이 없을 수 있음
                summary = clean_html(entry.get("description", "")) or entry.get("title", "")[:200]
                
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
