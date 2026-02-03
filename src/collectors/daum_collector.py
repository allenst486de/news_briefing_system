"""
Daum News RSS Feed Collector
다음 뉴스 RSS 피드에서 뉴스 수집
"""
import feedparser
from typing import List
from .base_collector import BaseCollector, NewsArticle


class DaumCollector(BaseCollector):
    """다음 뉴스 수집기"""
    
    # 다음 뉴스 RSS 피드 URL
    RSS_FEEDS = {
        'politics': 'https://news.daum.net/rss/politics',      # 정치
        'economic': 'https://news.daum.net/rss/economic',      # 경제
        'society': 'https://news.daum.net/rss/society',        # 사회
        'foreign': 'https://news.daum.net/rss/foreign',        # 국제
        'culture': 'https://news.daum.net/rss/culture',        # 문화
        'digital': 'https://news.daum.net/rss/digital',        # IT
        'top': 'https://news.daum.net/rss/newsview'            # 종합
    }
    
    def __init__(self):
        super().__init__("다음 뉴스")
        
    def collect(self, category: str = 'top', limit: int = 15) -> List[NewsArticle]:
        """
        다음 뉴스 수집
        
        Args:
            category: 'politics', 'economic', 'society', 'foreign', 'culture', 'digital', 'top'
            limit: 수집할 뉴스 개수
            
        Returns:
            List[NewsArticle]: 수집된 뉴스 리스트
        """
        articles = []
        
        # 카테고리 확인
        if category not in self.RSS_FEEDS:
            category = 'top'
            
        try:
            # RSS 피드 파싱
            feed = feedparser.parse(self.RSS_FEEDS[category])
            
            for entry in feed.entries[:limit]:
                # 다음 뉴스도 description에 HTML이 포함될 수 있음
                summary = entry.get('description', '')
                # HTML 태그 제거
                import re
                summary = re.sub('<[^<]+?>', '', summary)
                
                article = NewsArticle(
                    title=entry.get('title', ''),
                    link=entry.get('link', ''),
                    published=self._parse_date(entry.get('published', '')),
                    summary=summary,
                    source=self.source_name,
                    category=category
                )
                articles.append(article)
                
        except Exception as e:
            print(f"Error collecting Daum news: {e}")
            
        return articles
