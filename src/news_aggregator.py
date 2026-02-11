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
from .utils.translator import translate_article
from .utils.logger import setup_logger

# === Category Mapping Layer ===

STANDARD_CATEGORIES = {
    "domestic_general": ["top"],
    "domestic_economy": ["economy"],
    "domestic_politics": ["politics", "society"],
    "world_general": ["world"],
    "world_economy_politics": ["business", "politics_world"]
}

SOURCE_CATEGORY_MAP = {
    "naver": {
        "top": "top",
        "economy": "economy",
        "politics": "politics",
        "society": "society",
        "world": "world"
    },
    "daum": {
        "top": "top",
        "economic": "economy",
        "politics": "politics",
        "society": "society",
        "world": "world"
    },
    "bbc": {
        "world": "world",
        "business": "business",
        "politics": "politics_world"
    },
    "nyt": {
        "world": "world",
        "business": "business",
        "politics": "politics_world"
    }
}

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
        
        categorized_news = {key: [] for key in STANDARD_CATEGORIES}

        collectors = {
            "naver": self.naver,
            "daum": self.daum,
            "bbc": self.bbc,
            "nyt": self.nyt
        }
        
        limits = {
            "naver": 15,
            "daum": 15,
            "bbc": 10,
            "nyt": 10
        }
        
        # 각 소스별로 뉴스 수집
        for source, collector in collectors.items():
            self.logger.info(f"Collecting from {source}...")
        
            for source_category, std_category in SOURCE_CATEGORY_MAP[source].items():
                try:
                    self.logger.info(f"  - Collecting {source}/{source_category} -> {std_category}")
                    articles = collector.collect(
                        source_category,
                        limit=limits[source]
                    )
                    
                    # 해외 뉴스는 번역
                    if source in ['bbc', 'nyt']:
                        self.logger.info(f"  - Translating {len(articles)} articles from {source}")
                        articles = self._translate_articles(articles)
                    
                    # 표준 카테고리에 매핑
                    for target_category, mapped_categories in STANDARD_CATEGORIES.items():
                        if std_category in mapped_categories:
                            categorized_news[target_category].extend(articles)
                            self.logger.info(f"  - Added {len(articles)} articles to {target_category}")
                            break
                    
                except Exception as e:
                    self.logger.warning(
                        f"[{source}] failed category {source_category}: {e}"
                    )
                    continue
        
        # 중요도 분석 및 후처리
        self.logger.info("Processing collected news...")
        for category in categorized_news:
            categorized_news[category] = self._process_articles(
                categorized_news[category]
            )
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
    
    def _translate_articles(self, articles: List[NewsArticle]) -> List[NewsArticle]:
        """
        해외 뉴스 기사를 한국어로 번역
        
        Args:
            articles: 기사 리스트
            
        Returns:
            List[NewsArticle]: 번역된 기사 리스트
        """
        translated_articles = []
        for article in articles:
            try:
                translated = translate_article(article)
                translated_articles.append(translated)
            except Exception as e:
                self.logger.warning(f"Translation failed for article: {article.title[:50]}... Error: {e}")
                # 번역 실패 시 원본 사용
                translated_articles.append(article)
        return translated_articles
    
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
