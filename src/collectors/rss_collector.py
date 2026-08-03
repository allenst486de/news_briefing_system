"""
Generic RSS Collector
sources.py의 설정 하나당 이 클래스 인스턴스 하나 — 언론사 추가는 클래스 작성이 아니라
sources.py에 항목을 추가하는 것으로 끝난다.
"""
import logging
from typing import Dict, List
from .base_collector import BaseCollector, NewsArticle
from ..utils.rss_utils import (
    fetch_feed, clean_html, extract_date, strip_title_prefix, strip_google_news_title_suffix,
)


class RSSCollector(BaseCollector):
    """설정 기반 범용 RSS 수집기"""

    def __init__(self, source_id: str, display_name: str, feeds: Dict[str, str], language: str = "ko"):
        super().__init__(display_name)
        self.source_id = source_id
        self.feeds = feeds
        self.language = language
        self.logger = logging.getLogger(__name__)

    def collect(self, category: str = None, limit: int = 15) -> List[NewsArticle]:
        url = self.feeds.get(category)
        if not url:
            return []

        self.logger.info(f"Fetching {self.source_name}/{category} from: {url}")
        feed = fetch_feed(url)

        if not feed or not feed.entries:
            self.logger.warning(f"Feed empty: {self.source_id}/{category} from {url}")
            return []

        articles = []
        for entry in feed.entries[:limit]:
            try:
                # 요약은 clean_html로 엔티티가 풀리는데 제목은 그냥 두면 "&amp;"가
                # 그대로 남고, 템플릿이 한 번 더 이스케이프해 화면에 "&amp;"로 보인다.
                title = clean_html(entry.get("title", "")).strip()
                if self.source_id == "googlenews":
                    title = strip_google_news_title_suffix(title)
                summary = clean_html(entry.get("description", "") or entry.get("summary", ""))
                summary = strip_title_prefix(summary, title)
                summary = summary or title[:200]

                article = NewsArticle(
                    title=title,
                    link=entry.get("link", ""),
                    published=extract_date(entry, self._parse_date),
                    summary=summary,
                    source=self.source_name,
                    category=category,
                )
                articles.append(article)
            except Exception as e:
                self.logger.error(f"Error parsing entry from {self.source_id}: {e}")
                continue

        self.logger.info(f"Collected {len(articles)} articles from {self.source_id}/{category}")
        return articles
