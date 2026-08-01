"""
HTML Generator
뉴스 데이터를 HTML 페이지로 생성
"""
import os
import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, List
from urllib.parse import urlparse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORIES, CATEGORY_META
from .utils.logger import setup_logger
from .utils.indicators import get_market_indicators

PREVIEW_COUNT = 5
AI_PREVIEW_COUNT = 3
FEED_ITEMS_PER_CATEGORY = 3


class HTMLGenerator:
    """HTML 페이지 생성기"""

    CATEGORY_NAMES = {key: f"{meta['icon']} {meta['name']}" for key, meta in CATEGORY_META.items()}
    CATEGORY_FILES = {key: f"{key}.html" for key in CATEGORIES}

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
        self.base_url = base_url.rstrip('/')

        if base_url:
            parsed = urlparse(base_url.rstrip('/'))
            self.base_path = parsed.path.rstrip('/')
        else:
            self.base_path = ''

        self.logger.info(f"HTMLGenerator initialized with base_path: '{self.base_path}'")

        # Jinja2 환경 설정 (외부 RSS 콘텐츠를 렌더링하므로 autoescape 필수)
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(['html', 'xml']),
        )

    def generate_all(self, categorized_news: Dict[str, List[NewsArticle]]) -> Dict[str, str]:
        """
        모든 카테고리의 HTML 페이지 + 포털 홈 + 부가 파일 생성

        Returns:
            Dict[str, str]: 카테고리별 생성된 페이지 상대경로
        """
        self.logger.info("Starting HTML generation...")

        now = datetime.now()
        date_str = now.strftime('%Y-%m-%d')
        date_path = now.strftime('%Y/%m/%d')

        output_path = os.path.join(self.output_dir, date_path)
        os.makedirs(output_path, exist_ok=True)

        self._copy_css()
        self._copy_static()

        nav_categories = [
            {
                'key': key,
                'name': CATEGORY_META[key]['name'],
                'icon': CATEGORY_META[key]['icon'],
                'url': self._make_path(f'/{date_path}/{self.CATEGORY_FILES[key]}'),
            }
            for key in CATEGORIES
        ]

        page_urls = {}
        for category in CATEGORIES:
            articles = categorized_news.get(category, [])
            html_file = self.CATEGORY_FILES[category]
            file_path = os.path.join(output_path, html_file)

            self._generate_briefing_page(
                category=category, articles=articles, output_file=file_path,
                date_str=date_str, date_path=date_path, nav_categories=nav_categories,
            )
            page_urls[category] = f"{date_path}/{html_file}"
            self.logger.info(f"Generated {category}: {file_path}")

        self._update_archive(date_str, date_path)
        self._generate_index_page(categorized_news, date_str, date_path, nav_categories)
        self._generate_feed_xml(categorized_news, date_str)
        self._generate_robots_txt()

        self.logger.info("HTML generation completed")
        return page_urls

    def _make_path(self, relative: str) -> str:
        clean = relative.lstrip('/')
        if self.base_path:
            return f"{self.base_path}/{clean}"
        return f"/{clean}"

    def _og_context(self, title: str, description: str, path: str) -> Dict[str, str]:
        return {
            'og_title': title,
            'og_description': description,
            'og_url': f"{self.base_url}{self._make_path(path)}" if self.base_url else self._make_path(path),
        }

    @staticmethod
    def _article_to_dict(article: NewsArticle) -> Dict:
        d = {
            'title': article.title,
            'link': article.link,
            'published': article.published.strftime('%Y-%m-%d %H:%M'),
            'summary': article.summary,
            'source': article.source,
            'is_important': article.is_important,
        }
        if hasattr(article, 'original_title'):
            d['original_title'] = article.original_title
        if hasattr(article, 'original_summary'):
            d['original_summary'] = article.original_summary
        return d

    def _generate_briefing_page(self, category: str, articles: List[NewsArticle],
                                 output_file: str, date_str: str, date_path: str,
                                 nav_categories: List[Dict]):
        """개별 브리핑 페이지 생성"""
        template = self.env.get_template('briefing.html')
        category_name = self.CATEGORY_NAMES[category]

        articles_data = [self._article_to_dict(a) for a in articles]

        ai_items = []
        if category == 'it':
            ai_items = [self._article_to_dict(a) for a in articles if getattr(a, 'is_ai', False)]
            articles_data = [self._article_to_dict(a) for a in articles if not getattr(a, 'is_ai', False)]

        html_content = template.render(
            category_key=category,
            category_name=category_name,
            date=date_str,
            articles=articles_data,
            ai_items=ai_items,
            css_path=self._make_path('/style.css'),
            site_js_path=self._make_path('/site.js'),
            archive_path=self._make_path('/archive.html'),
            index_path=self._make_path('/index.html'),
            date_path=date_path,
            base_path=self.base_path,
            nav_categories=nav_categories,
            **self._og_context(f"{category_name} — {date_str}", f"{category_name} 일일 뉴스 브리핑 ({date_str})", f'/{date_path}/{self.CATEGORY_FILES[category]}'),
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

        existing_date_strs = {item['date'] for item in archive_items if 'date' in item}

        if date_str not in existing_date_strs:
            categories_list = [
                {'name': self.CATEGORY_NAMES[key], 'path': self._make_path(f'/{date_path}/{self.CATEGORY_FILES[key]}')}
                for key in CATEGORIES
            ]
            archive_items.append({'date': date_str, 'categories': categories_list})

        archive_items.sort(key=lambda x: x['date'], reverse=True)

        with open(archive_data_file, 'w', encoding='utf-8') as f:
            json.dump(archive_items, f, ensure_ascii=False, indent=2)

        template = self.env.get_template('archive.html')
        html_content = template.render(
            archive_items=archive_items,
            css_path=self._make_path('/style.css'),
            site_js_path=self._make_path('/site.js'),
            index_path=self._make_path('/index.html'),
            **self._og_context('뉴스 브리핑 아카이브', '날짜별 과거 브리핑 모음', '/archive.html'),
        )

        with open(archive_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def _generate_index_page(self, categorized_news: Dict[str, List[NewsArticle]],
                              date_str: str, date_path: str, nav_categories: List[Dict]):
        """포털형 홈페이지 생성 — 카테고리 미리보기 + AI 소식 미리보기 + 헤더"""
        index_file = os.path.join(self.output_dir, 'index.html')
        template = self.env.get_template('index.html')

        category_previews = []
        all_ai_items = []
        for cat in nav_categories:
            key = cat['key']
            articles = categorized_news.get(key, [])
            if key == 'it':
                ai_articles = [a for a in articles if getattr(a, 'is_ai', False)]
                all_ai_items.extend(ai_articles)
                articles = [a for a in articles if not getattr(a, 'is_ai', False)]
            category_previews.append({
                **cat,
                'top5': [self._article_to_dict(a) for a in articles[:PREVIEW_COUNT]],
            })

        ai_preview = [self._article_to_dict(a) for a in all_ai_items[:AI_PREVIEW_COUNT]]
        indicators = get_market_indicators()

        html_content = template.render(
            date=date_str,
            indicators=indicators,
            category_previews=category_previews,
            ai_items=ai_preview,
            nav_categories=nav_categories,
            css_path=self._make_path('/style.css'),
            site_js_path=self._make_path('/site.js'),
            archive_path=self._make_path('/archive.html'),
            feed_path=self._make_path('/feed.xml'),
            **self._og_context('일일 뉴스 브리핑', f'{date_str} 오늘의 뉴스를 한눈에', '/index.html'),
        )

        with open(index_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def _generate_feed_xml(self, categorized_news: Dict[str, List[NewsArticle]], date_str: str):
        """자체 RSS 2.0 피드 — 검색엔진 자동탐지 태그는 템플릿에 넣지 않음(비공개 노출 방침)"""
        rss = ET.Element('rss', version='2.0')
        channel = ET.SubElement(rss, 'channel')
        ET.SubElement(channel, 'title').text = '일일 뉴스 브리핑'
        ET.SubElement(channel, 'link').text = self.base_url or '/'
        ET.SubElement(channel, 'description').text = f'{date_str} 뉴스 브리핑'

        items = []
        for key in CATEGORIES:
            for article in categorized_news.get(key, [])[:FEED_ITEMS_PER_CATEGORY]:
                items.append((article.published, key, article))
        items.sort(key=lambda t: t[0], reverse=True)

        for published, key, article in items:
            item = ET.SubElement(channel, 'item')
            ET.SubElement(item, 'title').text = f"[{CATEGORY_META[key]['name']}] {article.title}"
            ET.SubElement(item, 'link').text = article.link
            ET.SubElement(item, 'description').text = article.summary
            ET.SubElement(item, 'pubDate').text = published.strftime('%a, %d %b %Y %H:%M:%S %z') or published.isoformat()

        feed_file = os.path.join(self.output_dir, 'feed.xml')
        ET.ElementTree(rss).write(feed_file, encoding='utf-8', xml_declaration=True)

    def _generate_robots_txt(self):
        """검색엔진 색인 차단 — 링크를 아는 사람은 여전히 접근 가능하지만 크롤링은 막음"""
        robots_file = os.path.join(self.output_dir, 'robots.txt')
        with open(robots_file, 'w', encoding='utf-8') as f:
            f.write("User-agent: *\nDisallow: /\n")

    def _copy_css(self):
        css_source = os.path.join(self.template_dir, 'style.css')
        css_dest = os.path.join(self.output_dir, 'style.css')
        shutil.copy2(css_source, css_dest)

    def _copy_static(self):
        js_source = os.path.join(self.template_dir, 'static', 'site.js')
        js_dest = os.path.join(self.output_dir, 'site.js')
        shutil.copy2(js_source, js_dest)
