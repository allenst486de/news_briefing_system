"""
BBC News RSS Feed Collector
BBC 뉴스 RSS 피드에서 뉴스 수집
"""
import feedparser
from typing import List
from .base_collector import BaseCollector, NewsArticle


class BBCCollector(BaseCollector):
    """BBC 뉴스 수집기"""
    
    # BBC RSS 피드 URL
    RSS_FEEDS = {
        'world': 'http://feeds.bbci.co.uk/news/world/rss.xml',
        'business': 'http://feeds.bbci.co.uk/news/business/rss.xml',
        'politics': 'http://feeds.bbci.co.uk/news/politics/rss.xml',
        'technology': 'http://feeds.bbci.co.uk/news/technology/rss.xml',
        'top': 'http://feeds.bbci.co.uk/news/rss.xml'
    }
    
    def __init__(self):
        super().__init__("BBC News")
        
    def collect(self, category: str = 'world', limit: int = 10) -> List[NewsArticle]:
        """
        BBC 뉴스 수집
        
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
            print(f"Error collecting BBC news: {e}")
            
        return articles
