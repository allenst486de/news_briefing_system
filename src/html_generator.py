"""
HTML Generator
뉴스 데이터를 HTML 페이지로 생성
"""
import os
import json
from datetime import datetime
from typing import Dict, List
from jinja2 import Environment, FileSystemLoader
from .collectors.base_collector import NewsArticle
from .utils.logger import setup_logger


class HTMLGenerator:
    """HTML 페이지 생성기"""
    
    CATEGORY_NAMES = {
        'domestic_general': '🇰🇷 국내 종합 뉴스',
        'domestic_economy': '💰 국내 경제 뉴스',
        'domestic_politics': '🏛️ 국내 정치/시사 뉴스',
        'world_general': '🌍 세계 종합 뉴스',
        'world_economy_politics': '🌐 세계 경제/정치/시사 뉴스'
    }
    
    CATEGORY_FILES = {
        'domestic_general': 'domestic_general.html',
        'domestic_economy': 'domestic_economy.html',
        'domestic_politics': 'domestic_politics.html',
        'world_general': 'world_general.html',
        'world_economy_politics': 'world_economy_politics.html'
    }
    
    def __init__(self, template_dir: str, output_dir: str, base_url: str = ''):
        """
        Args:
            template_dir: 템플릿 디렉토리 경로
            output_dir: 출력 디렉토리 경로 (docs/)
            base_url: GitHub Pages 기본 URL (예: https://user.github.io/news_briefing_system)
                      서브경로 포함. 빈 문자열이면 루트 경로 사용.
        """
        self.logger = setup_logger()
        self.template_dir = template_dir
        self.output_dir = output_dir
        
        # base_url에서 서브경로 추출 (예: /news_briefing_system)
        # GitHub Pages에서 저장소명이 서브경로로 사용될 때 필요
        if base_url:
            from urllib.parse import urlparse
            parsed = urlparse(base_url.rstrip('/'))
            # 경로 부분만 추출 (예: /news_briefing_system)
            self.base_path = parsed.path.rstrip('/')
        else:
            self.base_path = ''
        
        self.logger.info(f"HTMLGenerator initialized with base_path: '{self.base_path}'")
        
        # Jinja2 환경 설정
        self.env = Environment(loader=FileSystemLoader(template_dir))
        
    def generate_all(self, categorized_news: Dict[str, List[NewsArticle]]) -> Dict[str, str]:
        """
        모든 카테고리의 HTML 페이지 생성
        
        Returns:
            Dict[str, str]: 카테고리별 생성된 페이지 상대경로 (예: "2026/02/19/domestic_general.html")
        """
        self.logger.info("Starting HTML generation...")
        
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        date_path = now.strftime('%Y/%m/%d')
        
        output_path = os.path.join(self.output_dir, date_path)
        os.makedirs(output_path, exist_ok=True)
        
        # CSS 파일 복사
        self._copy_css()
        
        page_urls = {}
        
        for category, articles in categorized_news.items():
            if category in self.CATEGORY_NAMES:
                html_file = self.CATEGORY_FILES[category]
                file_path = os.path.join(output_path, html_file)
                
                self._generate_briefing_page(
                    category=category,
                    articles=articles,
                    output_file=file_path,
                    date_str=date_str,
                    date_path=date_path
                )
                
                # 텔레그램 봇이 사용할 상대경로
                page_urls[category] = f"{date_path}/{html_file}"
                
                self.logger.info(f"Generated {category}: {file_path}")
        
        self._update_archive(date_str, date_path)
        self._generate_index_page(date_path)
        
        self.logger.info("HTML generation completed")
        return page_urls
    
    def _make_path(self, relative: str) -> str:
        """
        base_path + relative 경로 생성
        예) base_path='/news_briefing_system', relative='/style.css'
            => '/news_briefing_system/style.css'
        """
        clean = relative.lstrip('/')
        if self.base_path:
            return f"{self.base_path}/{clean}"
        return f"/{clean}"
    
    def _generate_briefing_page(self, category: str, articles: List[NewsArticle],
                                output_file: str, date_str: str, date_path: str):
        """개별 브리핑 페이지 생성"""
        template = self.env.get_template('briefing.html')
        
        articles_data = []
        for article in articles:
            article_dict = {
                'title': article.title,
                'link': article.link,
                'published': article.published.strftime('%Y-%m-%d %H:%M'),
                'summary': article.summary,
                'source': article.source,
                'is_important': article.is_important
            }
            
            if hasattr(article, 'original_title'):
                article_dict['original_title'] = article.original_title
            if hasattr(article, 'original_summary'):
                article_dict['original_summary'] = article.original_summary
            
            articles_data.append(article_dict)
        
        html_content = template.render(
            category_name=self.CATEGORY_NAMES[category],
            date=date_str,
            articles=articles_data,
            css_path=self._make_path('/style.css'),
            archive_path=self._make_path('/archive.html'),
            index_path=self._make_path('/index.html'),
            date_path=date_path,
            base_path=self.base_path,
            nav_domestic_general=self._make_path(f'/{date_path}/domestic_general.html'),
            nav_domestic_economy=self._make_path(f'/{date_path}/domestic_economy.html'),
            nav_domestic_politics=self._make_path(f'/{date_path}/domestic_politics.html'),
            nav_world_general=self._make_path(f'/{date_path}/world_general.html'),
            nav_world_economy_politics=self._make_path(f'/{date_path}/world_economy_politics.html'),
        )
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _update_archive(self, date_str: str, date_path: str):
        """아카이브 페이지 업데이트"""
        archive_file = os.path.join(self.output_dir, 'archive.html')
        archive_data_file = os.path.join(self.output_dir, 'archive_data.json')
        
        archive_items = []
        if os.path.exists(archive_data_file):
            with open(archive_data_file, 'r', encoding='utf-8') as f:
                archive_items = json.load(f)
        
        # 날짜별로 그룹화된 구조로 저장
        existing_dates = {item['date'] for item in archive_items if 'categories' in item}
        # 구형 데이터와 신형 데이터 모두 처리
        existing_date_strs = set()
        for item in archive_items:
            if 'date' in item:
                existing_date_strs.add(item['date'])
        
        if date_str not in existing_date_strs:
            categories_list = []
            for category, filename in self.CATEGORY_FILES.items():
                categories_list.append({
                    'name': self.CATEGORY_NAMES[category],
                    'path': self._make_path(f'/{date_path}/{filename}')
                })
            
            archive_items.append({
                'date': date_str,
                'categories': categories_list
            })
        
        # 날짜 역순 정렬
        archive_items.sort(key=lambda x: x['date'], reverse=True)
        
        with open(archive_data_file, 'w', encoding='utf-8') as f:
            json.dump(archive_items, f, ensure_ascii=False, indent=2)
        
        template = self.env.get_template('archive.html')
        html_content = template.render(
            archive_items=archive_items,
            css_path=self._make_path('/style.css'),
            index_path=self._make_path('/index.html')
        )
        
        with open(archive_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _generate_index_page(self, latest_date_path: str):
        """메인 인덱스 페이지 생성 (최신 브리핑으로 리다이렉트)"""
        index_file = os.path.join(self.output_dir, 'index.html')
        template = self.env.get_template('index.html')
        
        latest_url = self._make_path(f'/{latest_date_path}/domestic_general.html')
        archive_url = self._make_path('/archive.html')
        
        html_content = template.render(
            latest_briefing_url=latest_url,
            archive_url=archive_url,
            css_path=self._make_path('/style.css')
        )
        
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _copy_css(self):
        """CSS 파일을 output 디렉토리로 복사"""
        import shutil
        
        css_source = os.path.join(self.template_dir, 'style.css')
        css_dest = os.path.join(self.output_dir, 'style.css')
        
        shutil.copy2(css_source, css_dest)
