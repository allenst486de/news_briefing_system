import logging
from typing import List
from .base_collector import BaseCollector, NewsArticle
from ..utils.rss_utils import fetch_feed, clean_html, extract_date


class NaverCollector(BaseCollector):
    """네이버 뉴스 수집기"""
    
    # 네이버 뉴스 RSS 피드 (주요 언론사별)
    RSS_FEEDS = {
        "top": "https://news.naver.com/main/list.naver?mode=LSD&mid=sec&sid1=001",  # 종합
        "politics": "https://news.naver.com/main/list.naver?mode=LSD&mid=sec&sid1=100",  # 정치
        "economy": "https://news.naver.com/main/list.naver?mode=LSD&mid=sec&sid1=101",  # 경제
        "society": "https://news.naver.com/main/list.naver?mode=LSD&mid=sec&sid1=102",  # 사회
        "world": "https://news.naver.com/main/list.naver?mode=LSD&mid=sec&sid1=104",  # 세계
        "it": "https://news.naver.com/main/list.naver?mode=LSD&mid=sec&sid1=105",  # IT
    }
    
    # 실제 작동하는 RSS 피드 (연합뉴스)
    WORKING_RSS_FEEDS = {
        "top": "https://www.yonhapnewstv.co.kr/category/news/headline/feed/",
        "politics": "https://www.yonhapnewstv.co.kr/category/news/politics/feed/",
        "economy": "https://www.yonhapnewstv.co.kr/category/news/economy/feed/",
        "society": "https://www.yonhapnewstv.co.kr/category/news/society/feed/",
        "world": "https://www.yonhapnewstv.co.kr/category/news/international/feed/",
        "it": "https://www.yonhapnewstv.co.kr/category/news/science/feed/",
    }

    def __init__(self):
        super().__init__("연합뉴스")
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
        url = self.WORKING_RSS_FEEDS.get(category, self.WORKING_RSS_FEEDS["top"])
        self.logger.info(f"Fetching Naver news from: {url}")
        
        feed = fetch_feed(url)

        if not feed or not feed.entries:
            self.logger.warning(f"Naver feed empty: {category} from {url}")
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
