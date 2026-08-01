"""
Telegram Bot
텔레그램으로 뉴스 브리핑 요약 전송

8개 카테고리 × top3 요약이 한 메시지(4096자 한도)에 안 들어가서
리드 메시지 1개(+ Top10 카드뉴스 이미지, 있으면) + 카테고리별 메시지 8개 = 하루
9~10개로 분리 전송한다. Top10은 이미지와 텍스트 목록을 함께 보낸다 — 웹 홈 화면의
Top10과 동일한 데이터(summarizer.select_top10)를 그대로 재사용하므로 내용은 항상 같다.

뉴스 원문 링크는 "원문 보기"처럼 텍스트로 감싼 링크(<a href="URL">텍스트</a>)를
쓴다 — 표시 텍스트와 실제 URL이 다르면 텔레그램 클라이언트가 피싱 방지용
"이 링크를 여시겠습니까?" 확인 팝업을 띄우지만, 가독성을 우선한 사용자 선택이다.
(팝업 없이 바로 연결하고 싶다면 평문 URL을 그대로 노출해야 한다 — 트레이드오프.)
분야별 바로가기/아카이브/홈 같은 자체 사이트 내비게이션 링크는 계속 평문 URL을 쓴다.
"""
import asyncio
from typing import Dict, List, Optional
from telegram import Bot
from telegram.error import TelegramError
from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORIES, CATEGORY_META
from .utils.logger import setup_logger

TOP_N_PER_CATEGORY = 3
SUMMARY_TRIM = 250


class TelegramNotifier:
    """텔레그램 알림 전송기"""

    def __init__(self, bot_token: str, chat_id: str, base_url: str):
        """
        Args:
            bot_token: 텔레그램 봇 토큰
            chat_id: 텔레그램 채팅 ID
            base_url: GitHub Pages 기본 URL
                      (예: https://user.github.io/news_briefing_system)
        """
        self.logger = setup_logger()
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        self.base_url = base_url.rstrip('/')
        self.logger.info(f"Telegram bot initialized with base URL: {self.base_url}")

    def _full_url(self, relative: str) -> str:
        return f"{self.base_url}/{relative.lstrip('/')}"

    def _build_lead_message(self, page_urls: Dict[str, str], top10: List[Dict], date_str: str) -> str:
        parts = [f"<b>📰 일일 뉴스 브리핑 ({date_str})</b>", ""]

        if top10:
            parts.append("🔥 <b>오늘의 Top 10</b>")
            for item in top10:
                parts.append(f'{item["rank"]}. <b>{item["card_headline"]}</b>')
                parts.append(f'{item.get("category_name", "")} · {item.get("source", "")} · '
                              f'<a href="{item["link"]}">원문 보기</a>')
            parts.append("")

        parts.append("📂 <b>분야별 바로가기</b>")
        for key in CATEGORIES:
            url = page_urls.get(key)
            if not url:
                continue
            meta = CATEGORY_META[key]
            parts.append(f'{meta["icon"]} {meta["name"]}: {self._full_url(url)}')

        parts.append("")
        parts.append(f'📚 아카이브: {self._full_url("archive.html")}')
        parts.append(f'🏠 홈(최신 브리핑): {self._full_url("index.html")}')
        parts.append("")
        parts.append("<i>매일 오전 6시에 자동으로 업데이트됩니다.</i>")
        return "\n".join(parts)

    def _build_category_message(self, key: str, articles: List[NewsArticle], page_url: str, date_str: str) -> str:
        meta = CATEGORY_META[key]
        parts = [f'<b>{meta["icon"]} {meta["name"]} 뉴스 ({date_str})</b>', ""]

        # news_aggregator에서 이미 (중요도, 최신순)으로 정렬해서 넘어옴
        top_articles = articles[:TOP_N_PER_CATEGORY]
        if not top_articles:
            parts.append("오늘 수집된 뉴스가 없습니다.")
        for article in top_articles:
            summary = (article.summary or "")[:SUMMARY_TRIM]
            parts.append(f"📌 <b>{article.title}</b>")
            parts.append(f"({article.source})")
            if summary:
                parts.append(summary)
            parts.append(f'<a href="{article.link}">원문 보기</a>')
            parts.append("")

        parts.append(f'📄 전체보기: {self._full_url(page_url)}')
        if key == 'economy':
            parts.append("⚠️ 주식 추천은 정보 제공 목적이며 투자 자문이 아닙니다.")
        return "\n".join(parts)

    async def send_briefing(self, page_urls: Dict[str, str],
                             categorized_news: Dict[str, List[NewsArticle]],
                             top10: List[Dict], date_str: str,
                             top10_image_path: Optional[str] = None):
        """Top10 인포그래픽 이미지(있으면) + 리드 메시지(Top10 텍스트 포함) + 카테고리별 메시지를 순차 전송."""
        self.logger.info("Sending Telegram notification...")

        try:
            if top10_image_path:
                try:
                    with open(top10_image_path, 'rb') as photo:
                        await self.bot.send_photo(chat_id=self.chat_id, photo=photo,
                                                   caption=f"🔥 오늘의 Top 10 ({date_str})")
                except TelegramError as e:
                    self.logger.warning(f"Top10 image send failed (text list still sent): {e}")

            await self.bot.send_message(
                chat_id=self.chat_id,
                text=self._build_lead_message(page_urls, top10, date_str),
                parse_mode='HTML',
                disable_web_page_preview=True,
            )

            for key in CATEGORIES:
                page_url = page_urls.get(key)
                if not page_url:
                    continue
                message = self._build_category_message(key, categorized_news.get(key, []), page_url, date_str)
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=message,
                    parse_mode='HTML',
                    disable_web_page_preview=True,
                )

            self.logger.info("Telegram notification sent successfully")
        except TelegramError as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            raise

    def send_briefing_sync(self, page_urls: Dict[str, str],
                            categorized_news: Dict[str, List[NewsArticle]],
                            top10: List[Dict], date_str: str,
                            top10_image_path: Optional[str] = None):
        """동기 방식으로 브리핑 전송"""
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(
                self.send_briefing(page_urls, categorized_news, top10, date_str, top10_image_path)
            )
        except Exception as e:
            self.logger.error(f"Error in send_briefing_sync: {e}")
            raise
