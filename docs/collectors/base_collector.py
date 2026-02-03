"""
Base News Collector Class
모든 뉴스 수집기의 공통 인터페이스 정의
"""
from abc import ABC, abstractmethod
from typing import List, Dict
from datetime import datetime


class NewsArticle:
    """뉴스 기사 데이터 클래스"""
    def __init__(self, title: str, link: str, published: datetime, 
                 summary: str = "", source: str = "", category: str = ""):
        self.title = title
        self.link = link
        self.published = published
        self.summary = summary
        self.source = source
        self.category = category
        self.is_important = False  # 중요도 플래그
        
    def to_dict(self) -> Dict:
        """딕셔너리로 변환"""
        return {
            'title': self.title,
            'link': self.link,
            'published': self.published.isoformat(),
            'summary': self.summary,
            'source': self.source,
            'category': self.category,
            'is_important': self.is_important
        }


class BaseCollector(ABC):
    """뉴스 수집기 기본 클래스"""
    
    def __init__(self, source_name: str):
        self.source_name = source_name
        
    @abstractmethod
    def collect(self, category: str = None, limit: int = 10) -> List[NewsArticle]:
        """
        뉴스 수집 메서드
        
        Args:
            category: 뉴스 카테고리 (optional)
            limit: 수집할 뉴스 개수
            
        Returns:
            List[NewsArticle]: 수집된 뉴스 리스트
        """
        pass
    
    def _parse_date(self, date_str: str) -> datetime:
        """날짜 문자열을 datetime 객체로 변환"""
        from email.utils import parsedate_to_datetime
        try:
            return parsedate_to_datetime(date_str)
        except:
            return datetime.now()
