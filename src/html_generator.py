"""
HTML Generator
뉴스 데이터를 HTML 페이지로 생성
"""
import os
import json
import shutil
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse
from jinja2 import Environment, FileSystemLoader, select_autoescape
from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORIES, CATEGORY_META, REGIONS, REGION_META
from .utils.logger import setup_logger
from .utils.indicators import get_market_indicators, write_indicators_json
from .utils.pagekey import load_or_create_salt, obfuscate
from .utils import stock_data
from . import summarizer

PREVIEW_COUNT = 5
AI_PREVIEW_COUNT = 3
FEED_ITEMS_PER_CATEGORY = 3
KST = timezone(timedelta(hours=9))
_WEEKDAYS_KO = ['월', '화', '수', '목', '금', '토', '일']


def date_with_weekday(dt) -> str:
    """'2026-08-12 (수)' — 화면 표시용. 폴더 경로에는 쓰지 않는다."""
    return f"{dt.strftime('%Y-%m-%d')} ({_WEEKDAYS_KO[dt.weekday()]})"


class HTMLGenerator:
    """HTML 페이지 생성기"""

    CATEGORY_NAMES = {key: f"{meta['icon']} {meta['name']}" for key, meta in CATEGORY_META.items()}
    CATEGORY_FILES = {key: f"{key}.html" for key in CATEGORIES}

    def __init__(self, template_dir: str, output_dir: str, base_url: str = '', raw_data_dir: Optional[str] = None):
        """
        Args:
            template_dir: 템플릿 디렉토리 경로
            output_dir: 출력 디렉토리 경로 (docs/)
            base_url: GitHub Pages 기본 URL (예: https://user.github.io/news_briefing_system)
                      서브경로 포함. 빈 문자열이면 루트 경로 사용.
            raw_data_dir: 일일 원본 스냅샷 저장 경로 (docs/ 밖, 3개월 롤오버용).
                          지정 안 하면 스냅샷을 저장하지 않는다.
        """
        self.logger = setup_logger()
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.raw_data_dir = raw_data_dir
        self.base_url = base_url.rstrip('/')

        if base_url:
            parsed = urlparse(base_url.rstrip('/'))
            self.base_path = parsed.path.rstrip('/')
        else:
            self.base_path = ''

        # 페이지 URL 난수화용 salt — docs/ 밖에 두어 공개되지 않게 한다
        self.salt = load_or_create_salt(raw_data_dir or os.path.dirname(output_dir))

        self.logger.info(f"HTMLGenerator initialized with base_path: '{self.base_path}'")

        # Jinja2 환경 설정 (외부 RSS 콘텐츠를 렌더링하므로 autoescape 필수)
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=select_autoescape(['html', 'xml']),
        )

    def generate_all(self, buckets: Dict[str, Dict[str, List[NewsArticle]]]):
        """
        모든 카테고리의 HTML 페이지 + 포털 홈 + 부가 파일 생성.
        buckets는 {카테고리: {"domestic": [...], "overseas": [...]}}.

        Returns:
            (page_urls, top10_by_region) — 텔레그램이 HTML과 동일한 top10을
            재사용하도록 함께 반환한다(다시 계산하면 LLM 호출이 두 배가 된다).
        """
        self.logger.info("Starting HTML generation...")

        # 러너는 UTC라 naive now()를 쓰면 06시 KST 발행분이 전날로 찍힌다
        now = datetime.now(KST)
        date_str = now.strftime('%Y-%m-%d')
        date_full = date_with_weekday(now)   # 화면에는 요일까지 표시
        date_path = now.strftime('%Y/%m/%d')

        output_path = os.path.join(self.output_dir, date_path)
        os.makedirs(output_path, exist_ok=True)

        self._copy_css()
        self._copy_static()

        salt = self.salt
        category_files = {
            key: obfuscate(f'{key}.html', salt, date_str) for key in CATEGORIES
        }
        nav_categories = [
            {
                'key': key,
                'name': CATEGORY_META[key]['name'],
                'icon': CATEGORY_META[key]['icon'],
                'url': self._make_path(f'/{date_path}/{category_files[key]}'),
            }
            for key in CATEGORIES
        ]

        self.logger.info("Fetching economy dashboard data (indicators + stock picks)...")
        indicators = get_market_indicators()
        # 장중 갱신 워크플로가 15분마다 덮어쓰는 파일 — 첫 배포 시점에도 있어야
        # site.js의 fetch가 404로 실패하지 않는다
        write_indicators_json(indicators, os.path.join(self.output_dir, 'indicators.json'))
        stock_picks = {"domestic": stock_data.get_domestic_picks(), "overseas": stock_data.get_overseas_picks()}
        summarizer.generate_stock_reasons(stock_picks)

        # 해외 기사 상세 요약 페이지를 먼저 만들어야 목록에서 링크를 걸 수 있다
        self._generate_detail_pages(buckets, output_path, date_path, date_str, salt,
                                     nav_categories)

        self.logger.info("Selecting top10 (domestic / overseas)...")
        top10_by_region = {
            region: summarizer.select_top10(
                {key: buckets[key].get(region, []) for key in CATEGORIES},
                api_key=summarizer.category_api_key('politics'),
            )
            for region in REGIONS
        }

        page_urls = {}
        for category in CATEGORIES:
            html_file = category_files[category]
            file_path = os.path.join(output_path, html_file)

            self._generate_briefing_page(
                category=category, regions=buckets.get(category, {}), output_file=file_path,
                date_str=date_str, date_full=date_full, date_path=date_path,
                nav_categories=nav_categories,
                indicators=indicators, stock_picks=stock_picks,
                page_rel=f'/{date_path}/{html_file}',
            )
            page_urls[category] = f"{date_path}/{html_file}"
            self.logger.info(f"Generated {category}: {file_path}")

        # 아카이브는 홈 푸터에서 링크한다. 파일명 자체는 계속 난수화되어 있어
        # 주소를 추측해서 들어올 수는 없다(저장소가 public이면 파일 목록이 보이므로
        # 어차피 접근 제어가 아니다 — 주소 추측 차단이 목적).
        archive_file = obfuscate('archive.html', salt, 'archive')
        self._update_archive(date_str, date_path, archive_file, nav_categories)
        self._generate_index_page(buckets, date_str, date_full, date_path, nav_categories,
                                   top10_by_region, indicators, archive_file=archive_file)
        self._generate_feed_xml(buckets, date_str)
        self._generate_robots_txt()
        self._save_raw_snapshot(buckets, stock_picks, date_str)

        self.logger.info("HTML generation completed")
        # archive_file은 난수 파일명이라 호출부가 스스로 만들어낼 수 없다 —
        # 텔레그램 메시지에서 링크하려면 여기서 돌려줘야 한다.
        return page_urls, top10_by_region, archive_file

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

    def _generate_detail_pages(self, buckets, output_path, date_path, date_str, salt,
                                nav_categories=None) -> int:
        """
        해외 기사마다 한국어 상세 요약 페이지를 만든다.
        원문 전체 번역이 아니라 상세 '요약'이다 — 타사 기사 전문을 번역해 재배포하면
        저작권 문제가 되고, NYT·WSJ 같은 유료 매체는 본문 자체를 못 가져온다(403).
        상세 요약이 없으면(LLM 실패 등) 페이지를 만들지 않고 링크도 걸지 않는다.
        """
        template = self.env.get_template('article.html')
        made = 0
        for category in CATEGORIES:
            for article in buckets.get(category, {}).get('overseas', []):
                detail = (getattr(article, 'detail_summary', '') or '').strip()
                if not detail:
                    continue
                filename = obfuscate('a.html', salt, date_str, article.link)
                with open(os.path.join(output_path, filename), 'w', encoding='utf-8') as f:
                    f.write(template.render(
                        title=article.title,
                        original_title=getattr(article, 'original_title', ''),
                        source=article.source,
                        published=article.published.astimezone(KST).strftime('%Y-%m-%d %H:%M'),
                        detail=detail,
                        summary=article.summary,
                        link=article.link,
                        category_name=CATEGORY_META[category]['name'],
                        category_key=category,
                        nav_categories=nav_categories or [],
                        css_path=self._make_path('/style.css'),
                        site_js_path=self._make_path('/site.js'),
                        index_path=self._make_path('/index.html'),
                        **self._og_context(article.title, article.summary[:120],
                                            f'/{date_path}/{filename}'),
                    ))
                # detail_path: 페이지 <a href>용 (base_path 포함)
                # detail_rel : 텔레그램용 상대경로 (_full_url이 base_url을 붙이므로
                #              base_path가 들어가면 경로가 두 번 겹친다)
                article.detail_path = self._make_path(f'/{date_path}/{filename}')
                article.detail_rel = f'{date_path}/{filename}'
                made += 1
        self.logger.info(f"Generated {made} overseas detail pages")
        return made

    @staticmethod
    def _article_to_dict(article: NewsArticle) -> Dict:
        d = {
            'title': article.title,
            'link': article.link,
            'published': article.published.astimezone(KST).strftime('%Y-%m-%d %H:%M'),
            'summary': article.summary,
            'source': article.source,
            'is_important': article.is_important,
            'detail_path': getattr(article, 'detail_path', ''),
        }
        if hasattr(article, 'original_title'):
            d['original_title'] = article.original_title
        if hasattr(article, 'original_summary'):
            d['original_summary'] = article.original_summary
        if hasattr(article, 'ai_subtype_label'):
            d['ai_subtype_label'] = article.ai_subtype_label
        return d

    def _generate_briefing_page(self, category: str, regions: Dict[str, List[NewsArticle]],
                                 output_file: str, date_str: str, date_path: str,
                                 nav_categories: List[Dict], indicators: Optional[Dict] = None,
                                 stock_picks: Optional[Dict] = None, page_rel: str = '',
                                 date_full: str = ''):
        """개별 브리핑 페이지 생성 — 국내/해외 탭으로 나눠 렌더링"""
        template = self.env.get_template('briefing.html')
        category_name = self.CATEGORY_NAMES[category]

        region_blocks = []
        ai_items = []
        for region in REGIONS:
            articles = regions.get(region, [])
            if category == 'it':
                ai_items.extend(self._article_to_dict(a) for a in articles if getattr(a, 'is_ai', False))
                articles = [a for a in articles if not getattr(a, 'is_ai', False)]
            region_blocks.append({
                'key': region,
                'name': REGION_META[region]['name'],
                'icon': REGION_META[region]['icon'],
                'articles': [self._article_to_dict(a) for a in articles],
            })

        html_content = template.render(
            category_key=category,
            category_name=category_name,
            date=date_str,
            date_full=date_full or date_str,
            region_blocks=region_blocks,
            ai_items=ai_items,
            indicators=indicators if category == 'economy' else None,
            stock_picks=stock_picks if category == 'economy' else None,
            indicators_url=self._make_path('/indicators.json'),
            css_path=self._make_path('/style.css'),
            site_js_path=self._make_path('/site.js'),
            index_path=self._make_path('/index.html'),
            date_path=date_path,
            base_path=self.base_path,
            nav_categories=nav_categories,
            **self._og_context(f"{category_name} — {date_str}",
                                f"{category_name} 일일 뉴스 브리핑 ({date_str})", page_rel),
        )

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)

    def _update_archive(self, date_str: str, date_path: str, archive_file_name: str,
                         nav_categories=None):
        """
        아카이브 페이지 업데이트.
        파일명 자체가 난수화돼 있고 홈에서 링크하지 않으므로, 링크를 직접 아는
        사람만 과거 기록을 볼 수 있다(요청사항). 날짜별 카테고리 경로는
        archive_data.json에 누적되므로 예전 날짜의 난수 경로도 그대로 유지된다.
        """
        archive_file = os.path.join(self.output_dir, archive_file_name)
        archive_data_file = os.path.join(self.output_dir, 'archive_data.json')

        archive_items = []
        if os.path.exists(archive_data_file):
            with open(archive_data_file, 'r', encoding='utf-8') as f:
                archive_items = json.load(f)

        existing_date_strs = {item['date'] for item in archive_items if 'date' in item}

        if date_str not in existing_date_strs:
            categories_list = [
                {'name': self.CATEGORY_NAMES[key],
                 'path': self._make_path(f'/{date_path}/{obfuscate(f"{key}.html", self.salt, date_str)}')}
                for key in CATEGORIES
            ]
            archive_items.append({'date': date_str, 'categories': categories_list})

        archive_items.sort(key=lambda x: x['date'], reverse=True)

        with open(archive_data_file, 'w', encoding='utf-8') as f:
            json.dump(archive_items, f, ensure_ascii=False, indent=2)

        # 이전 실행이 남긴 예전 이름의 아카이브 파일은 지운다 (링크 노출 방지)
        legacy = os.path.join(self.output_dir, 'archive.html')
        if os.path.exists(legacy) and os.path.abspath(legacy) != os.path.abspath(archive_file):
            os.remove(legacy)

        template = self.env.get_template('archive.html')
        html_content = template.render(
            archive_items=archive_items,
            nav_categories=nav_categories or [],
            css_path=self._make_path('/style.css'),
            site_js_path=self._make_path('/site.js'),
            index_path=self._make_path('/index.html'),
            **self._og_context('뉴스 브리핑 아카이브', '날짜별 과거 브리핑 모음',
                                f'/{archive_file_name}'),
        )

        with open(archive_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        self.logger.info(f"Archive written to {archive_file_name} (linked from home footer)")

    def _generate_index_page(self, buckets: Dict[str, Dict[str, List[NewsArticle]]],
                              date_str: str, date_full: str, date_path: str,
                              nav_categories: List[Dict],
                              top10_by_region: Dict[str, List[Dict]],
                              indicators: Optional[Dict] = None,
                              archive_file: Optional[str] = None):
        """포털형 홈페이지 생성 — Top10 카드 + 카테고리 미리보기 + AI 소식 미리보기 + 헤더"""
        index_file = os.path.join(self.output_dir, 'index.html')
        template = self.env.get_template('index.html')

        category_previews = []
        all_ai_items = []
        for cat in nav_categories:
            key = cat['key']
            regions = buckets.get(key, {})
            # 홈 미리보기는 국내/해외를 합쳐 중요도순 상위만 보여준다
            articles = [a for region in REGIONS for a in regions.get(region, [])]
            articles.sort(key=lambda a: (a.is_important, a.published), reverse=True)
            if key == 'it':
                all_ai_items.extend(a for a in articles if getattr(a, 'is_ai', False))
                articles = [a for a in articles if not getattr(a, 'is_ai', False)]
            category_previews.append({
                **cat,
                'top5': [self._article_to_dict(a) for a in articles[:PREVIEW_COUNT]],
            })

        ai_preview = [self._article_to_dict(a) for a in all_ai_items[:AI_PREVIEW_COUNT]]

        top10_blocks = [
            {'key': region, 'name': REGION_META[region]['name'],
             'icon': REGION_META[region]['icon'], 'cards': top10_by_region.get(region, [])}
            for region in REGIONS
        ]

        html_content = template.render(
            date=date_str,
            date_full=date_full,
            indicators=indicators,
            top10_blocks=top10_blocks,
            category_previews=category_previews,
            ai_items=ai_preview,
            nav_categories=nav_categories,
            indicators_url=self._make_path('/indicators.json'),
            css_path=self._make_path('/style.css'),
            site_js_path=self._make_path('/site.js'),
            feed_path=self._make_path('/feed.xml'),
            # 없으면 템플릿이 링크를 통째로 감춘다 — 깨진 링크를 내보내지 않도록
            archive_path=self._make_path(f'/{archive_file}') if archive_file else None,
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
            regions = categorized_news.get(key, {})
            merged = [a for region in REGIONS for a in regions.get(region, [])]
            merged.sort(key=lambda a: (a.is_important, a.published), reverse=True)
            for article in merged[:FEED_ITEMS_PER_CATEGORY]:
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

    def _save_raw_snapshot(self, categorized_news: Dict[str, List[NewsArticle]],
                            stock_picks: Dict, date_str: str):
        """
        docs/ 밖에 그날의 원본 데이터를 저장 (archiver.py의 3개월 롤오버 압축용).
        raw_data_dir이 지정 안 됐으면 스냅샷을 만들지 않는다(예: 테스트 환경).
        """
        if not self.raw_data_dir:
            return

        year, month, day = date_str.split('-')
        snapshot_dir = os.path.join(self.raw_data_dir, year, month)
        os.makedirs(snapshot_dir, exist_ok=True)

        snapshot = {
            'date': date_str,
            'categories': {
                key: {region: [a.to_dict() for a in articles]
                      for region, articles in regions.items()}
                for key, regions in categorized_news.items()
            },
            'stock_picks': stock_picks,
        }

        with open(os.path.join(snapshot_dir, f'{day}.json'), 'w', encoding='utf-8') as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
