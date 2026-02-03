"""
New York Times RSS Feed Collector
NYT 뉴스 RSS 피드에서 뉴스 수집
"""
import feedparser
from typing import List
from .base_collector import BaseCollector, NewsArticle


class NYTCollector(BaseCollector):
    """New York Times 뉴스 수집기"""
    
    # NYT RSS 피드 URL
    RSS_FEEDS = {
        'world': 'https://rss.nytimes.com/services/xml/rss/nyt/World.xml',
        'business': 'https://rss.nytimes.com/services/xml/rss/nyt/Business.xml',
        'politics': 'https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml',
        'technology': 'https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml',
        'top': 'https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml'
    }
    
    def __init__(self):
        super().__init__("New York Times")
        
    def collect(self, category: str = 'world', limit: int = 10) -> List[NewsArticle]:
        """
        NYT 뉴스 수집
        
        Args:
            category: 'world', 'business', 'politics', 'technology', 'top'
            limit: 수집할 뉴스 개수
            
        Returns:
            List[NewsArticle]: 수집된 뉴스 리스트
        """
        articles = []
        
        # 카테고리 확인
        if category not in self.RSS_FEEDS:
            category = 'world'
            
        try:
            # RSS 피드 파싱
            feed = feedparser.parse(self.RSS_FEEDS[category])
            
            for entry in feed.entries[:limit]:
                article = NewsArticle(
                    title=entry.get('title', ''),
                    link=entry.get('link', ''),
                    published=self._parse_date(entry.get('published', '')),
                    summary=entry.get('summary', ''),
                    source=self.source_name,
                    category=category
                )
                articles.append(article)
                
        except Exception as e:
            print(f"Error collecting NYT news: {e}")
            
        return articles
