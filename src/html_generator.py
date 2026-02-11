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
    
    def __init__(self, template_dir: str, output_dir: str):
        """
        Args:
            template_dir: 템플릿 디렉토리 경로
            output_dir: 출력 디렉토리 경로 (docs/)
        """
        self.logger = setup_logger()
        self.template_dir = template_dir
        self.output_dir = output_dir
        
        # Jinja2 환경 설정
        self.env = Environment(loader=FileSystemLoader(template_dir))
        
    def generate_all(self, categorized_news: Dict[str, List[NewsArticle]]) -> Dict[str, str]:
        """
        모든 카테고리의 HTML 페이지 생성
        
        Args:
            categorized_news: 카테고리별 뉴스 딕셔너리
            
        Returns:
            Dict[str, str]: 카테고리별 생성된 페이지 URL
        """
        self.logger.info("Starting HTML generation...")
        
        # 현재 날짜로 디렉토리 생성
        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        date_path = now.strftime('%Y/%m/%d')
        
        output_path = os.path.join(self.output_dir, date_path)
        os.makedirs(output_path, exist_ok=True)
        
        # CSS 파일 복사
        self._copy_css()
        
        # 각 카테고리별 페이지 생성
        page_urls = {}
        
        for category, articles in categorized_news.items():
            if category in self.CATEGORY_NAMES:
                html_file = self.CATEGORY_FILES[category]
                file_path = os.path.join(output_path, html_file)
                
                # HTML 생성
                self._generate_briefing_page(
                    category=category,
                    articles=articles,
                    output_file=file_path,
                    date_str=date_str
                )
                
                # URL 저장 (상대 경로)
                page_urls[category] = f"{date_path}/{html_file}"
                
                self.logger.info(f"Generated {category}: {file_path}")
        
        # 아카이브 페이지 업데이트
        self._update_archive(date_str, date_path)
        
        # 인덱스 페이지 생성
        self._generate_index_page(date_path)
        
        self.logger.info("HTML generation completed")
        
        return page_urls
    
    def _generate_briefing_page(self, category: str, articles: List[NewsArticle],
                                output_file: str, date_str: str):
        """개별 브리핑 페이지 생성"""
        template = self.env.get_template('briefing.html')
        
        # 기사 데이터 변환
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
            
            # 번역된 기사인 경우 원문 정보 추가
            if hasattr(article, 'original_title'):
                article_dict['original_title'] = article.original_title
            if hasattr(article, 'original_summary'):
                article_dict['original_summary'] = article.original_summary
            
            articles_data.append(article_dict)
        
        # HTML 렌더링
        html_content = template.render(
            category_name=self.CATEGORY_NAMES[category],
            date=date_str,
            articles=articles_data,
            css_path='../../../style.css'
        )
        
        # 파일 저장
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _update_archive(self, date_str: str, date_path: str):
        """아카이브 페이지 업데이트"""
        archive_file = os.path.join(self.output_dir, 'archive.html')
        archive_data_file = os.path.join(self.output_dir, 'archive_data.json')
        
        # 기존 아카이브 데이터 로드
        archive_items = []
        if os.path.exists(archive_data_file):
            with open(archive_data_file, 'r', encoding='utf-8') as f:
                archive_items = json.load(f)
        
        # 새 항목 추가 (중복 체크)
        existing_dates = [item['date'] for item in archive_items]
        if date_str not in existing_dates:
            for category, filename in self.CATEGORY_FILES.items():
                archive_items.append({
                    'title': f"{date_str} - {self.CATEGORY_NAMES[category]}",
                    'date': date_str,
                    'path': f"{date_path}/{filename}"
                })
        
        # 날짜 역순 정렬
        archive_items.sort(key=lambda x: x['date'], reverse=True)
        
        # 아카이브 데이터 저장
        with open(archive_data_file, 'w', encoding='utf-8') as f:
            json.dump(archive_items, f, ensure_ascii=False, indent=2)
        
        # 아카이브 HTML 생성
        template = self.env.get_template('archive.html')
        html_content = template.render(archive_items=archive_items)
        
        with open(archive_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _generate_index_page(self, latest_date_path: str):
        """메인 인덱스 페이지 생성 (최신 브리핑으로 리다이렉트)"""
        index_file = os.path.join(self.output_dir, 'index.html')
        template = self.env.get_template('index.html')
        
        # 최신 브리핑 URL (국내 종합으로 기본 설정)
        latest_url = f"{latest_date_path}/domestic_general.html"
        
        html_content = template.render(latest_briefing_url=latest_url)
        
        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
    
    def _copy_css(self):
        """CSS 파일을 output 디렉토리로 복사"""
        import shutil
        
        css_source = os.path.join(self.template_dir, 'style.css')
        css_dest = os.path.join(self.output_dir, 'style.css')
        
        shutil.copy2(css_source, css_dest)
