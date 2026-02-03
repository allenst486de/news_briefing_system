"""
News Aggregator
모든 뉴스 소스를 통합하고 카테고리별로 분류
"""
from typing import List, Dict
from datetime import datetime
from .collectors.bbc_collector import BBCCollector
from .collectors.nyt_collector import NYTCollector
from .collectors.naver_collector import NaverCollector
from .collectors.daum_collector import DaumCollector
from .collectors.base_collector import NewsArticle
from .utils.importance_analyzer import ImportanceAnalyzer
from .utils.logger import setup_logger


class NewsAggregator:
    """뉴스 통합 및 분류 클래스"""
    
    def __init__(self):
        self.logger = setup_logger()
        self.bbc = BBCCollector()
        self.nyt = NYTCollector()
        self.naver = NaverCollector()
        self.daum = DaumCollector()
        self.analyzer = ImportanceAnalyzer()
        
    def collect_all_news(self) -> Dict[str, List[NewsArticle]]:
        """
        모든 소스에서 뉴스를 수집하고 카테고리별로 분류
        
        Returns:
            Dict[str, List[NewsArticle]]: 카테고리별 뉴스 딕셔너리
        """
        self.logger.info("Starting news collection...")
        
        categorized_news = {
            'domestic_general': [],      # 국내 일반 뉴스
            'domestic_economy': [],       # 국내 경제 뉴스
            'domestic_politics': [],      # 국내 정치/시사 뉴스
            'world_general': [],          # 세계 일반 뉴스
            'world_economy_politics': []  # 세계 경제/정치/시사 뉴스
        }
        
        # 1. 국내 뉴스 수집 (네이버, 다음)
        self.logger.info("Collecting domestic news...")
        
        # 네이버 - 종합
        naver_top = self.naver.collect('top', limit=15)
        # 네이버 - 경제
        naver_economy = self.naver.collect('economy', limit=15)
        # 네이버 - 정치
        naver_politics = self.naver.collect('politics', limit=15)
        
        # 다음 - 종합
        daum_top = self.daum.collect('top', limit=15)
        # 다음 - 경제
        daum_economy = self.daum.collect('economic', limit=15)
        # 다음 - 정치
        daum_politics = self.daum.collect('politics', limit=15)
        
        # 2. 해외 뉴스 수집 (BBC, NYT)
        self.logger.info("Collecting international news...")
        
        # BBC - 세계
        bbc_world = self.bbc.collect('world', limit=10)
        # BBC - 비즈니스
        bbc_business = self.bbc.collect('business', limit=10)
        # BBC - 정치
        bbc_politics = self.bbc.collect('politics', limit=10)
        
        # NYT - 세계
        nyt_world = self.nyt.collect('world', limit=10)
        # NYT - 비즈니스
        nyt_business = self.nyt.collect('business', limit=10)
        # NYT - 정치
        nyt_politics = self.nyt.collect('politics', limit=10)
        
        # 3. 카테고리별 분류 및 중요도 분석
        self.logger.info("Categorizing and analyzing news...")
        
        # 국내 일반 뉴스
        categorized_news['domestic_general'] = self._process_articles(
            naver_top + daum_top
        )
        
        # 국내 경제 뉴스
        categorized_news['domestic_economy'] = self._process_articles(
            naver_economy + daum_economy
        )
        
        # 국내 정치/시사 뉴스
        categorized_news['domestic_politics'] = self._process_articles(
            naver_politics + daum_politics
        )
        
        # 세계 일반 뉴스
        categorized_news['world_general'] = self._process_articles(
            bbc_world + nyt_world
        )
        
        # 세계 경제/정치/시사 뉴스
        categorized_news['world_economy_politics'] = self._process_articles(
            bbc_business + bbc_politics + nyt_business + nyt_politics
        )
        
        # 4. 중복 제거 및 정렬
        for category in categorized_news:
            categorized_news[category] = self._remove_duplicates(
                categorized_news[category]
            )
            # 최신순 정렬
            categorized_news[category].sort(
                key=lambda x: x.published, reverse=True
            )
            # 상위 20개만 유지
            categorized_news[category] = categorized_news[category][:20]
            
        self.logger.info(f"News collection completed. Total categories: {len(categorized_news)}")
        for category, articles in categorized_news.items():
            self.logger.info(f"  {category}: {len(articles)} articles")
            
        return categorized_news
    
    def _process_articles(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """
        기사 리스트를 처리하고 중요도 분석
        
        Args:
            articles: 기사 리스트
            
        Returns:
            List[NewsArticle]: 처리된 기사 리스트
        """
        for article in articles:
            # 중요도 분석
            article.is_important = self.analyzer.analyze(
                article.title, article.summary
            )
        return articles
    
    def _remove_duplicates(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """
        중복 기사 제거 (제목 기준)
        
        Args:
            articles: 기사 리스트
            
        Returns:
            List[NewsArticle]: 중복 제거된 기사 리스트
        """
        seen_titles = set()
        unique_articles = []
        
        for article in articles:
            # 제목을 정규화 (공백, 특수문자 제거)
            normalized_title = article.title.strip().lower()
            
            if normalized_title not in seen_titles:
                seen_titles.add(normalized_title)
                unique_articles.append(article)
                
        return unique_articles
