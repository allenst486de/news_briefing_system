"""
Base News Collector Class
모든 뉴스 수집기의 공통 인터페이스 정의
"""
from abc import ABC, abstractmethod
from typing import List, Dict
from datetime import datetime, timezone


class NewsArticle:
    """뉴스 기사 데이터 클래스"""
    def __init__(self, title: str, link: str, published: datetime,
                 summary: str = "", source: str = "", category: str = ""):
        self.title = title
        # javascript:/data: 등 위험한 스킴 차단 (모든 수집기가 이 생성자를 거침)
        self.link = link if link.startswith(('http://', 'https://')) else ''
        self.published = published
        self.summary = summary
        self.source = source
        self.category = category
        self.is_important = False  # 중요도 플래그
        self.body = ""  # 원문 본문 (article_body.enrich가 채움, 요약 입력으로만 사용)
        self.date_is_approximate = False  # 피드에 날짜가 없어 목록 순서로 추정한 경우
        self.region = "domestic"  # sources.py의 region — 국내/해외 탭 분리 기준
        self.language = "ko"
        self.detail_path = ""  # 해외 기사 상세 요약 페이지 href (base_path 포함)
        self.detail_rel = ""   # 같은 페이지의 상대경로 (텔레그램 링크 조립용)
        self.llm_failed = False  # 요약이 규칙기반으로 떨어졌는지 (재시도 스윕 대상)
        
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
        """
        날짜 문자열을 datetime 객체로 변환.
        언론사마다 RFC822 오프셋 유무가 달라 aware/naive가 섞이면
        나중에 카테고리 통합 정렬(sort)에서 TypeError가 난다 — 항상 UTC aware로 정규화.
        """
        from email.utils import parsedate_to_datetime
        try:
            dt = parsedate_to_datetime(date_str)
        except Exception:
            dt = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
