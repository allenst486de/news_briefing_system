"""
Naver News RSS Feed Collector
네이버 뉴스 RSS 피드에서 뉴스 수집
"""
import feedparser
from typing import List
from .base_collector import BaseCollector, NewsArticle


class NaverCollector(BaseCollector):
    """네이버 뉴스 수집기"""
    
    # 네이버 뉴스 RSS 피드 URL
    RSS_FEEDS = {
        'politics': 'https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=100',  # 정치
        'economy': 'https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=101',  # 경제
        'society': 'https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=102',  # 사회
        'world': 'https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=104',    # 세계
        'it': 'https://news.naver.com/officelist/rss.nhn?type=ranking&office=001&section=105',       # IT/과학
        'top': 'https://news.naver.com/officelist/rss.nhn?type=ranking&office=001'                   # 종합
    }
    
    def __init__(self):
        super().__init__("네이버 뉴스")
        
    def collect(self, category: str = 'top', limit: int = 15) -> List[NewsArticle]:
        """
        네이버 뉴스 수집
        
        Args:
            category: 'politics', 'economy', 'society', 'world', 'it', 'top'
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
                # 네이버 뉴스는 description에 HTML이 포함되어 있을 수 있음
                summary = entry.get('description', '')
                # HTML 태그 제거 (간단한 방법)
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
            print(f"Error collecting Naver news: {e}")
            
        return articles
