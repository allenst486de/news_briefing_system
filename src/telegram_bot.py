"""
Telegram Bot
텔레그램으로 뉴스 브리핑 요약 전송

8개 카테고리 × top3 요약이 한 메시지(4096자 한도)에 안 들어가서
리드 메시지 1개 + 카테고리별 메시지 8개 = 하루 9개로 분리 전송한다.
"""
import asyncio
from typing import Dict, List
from telegram import Bot
from telegram.error import TelegramError
from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORIES, CATEGORY_META
from .utils.logger import setup_logger

TOP_N_PER_CATEGORY = 3
SUMMARY_TRIM = 180  # HTML 페이지(250자)보다 짧게 — 텔레그램은 티저 역할


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

    def _build_lead_message(self, page_urls: Dict[str, str], date_str: str) -> str:
        parts = [
            f"<b>📰 일일 뉴스 브리핑 ({date_str})</b>",
            "",
            "분야별 브리핑이 곧 이어서 도착합니다.",
            "",
            "📂 <b>분야별 바로가기</b>",
        ]
        for key in CATEGORIES:
            url = page_urls.get(key)
            if not url:
                continue
            meta = CATEGORY_META[key]
            parts.append(f'{meta["icon"]} <a href="{self._full_url(url)}">{meta["name"]}</a>')

        parts.append("")
        parts.append(f'📚 <a href="{self._full_url("archive.html")}">아카이브 보기</a>')
        parts.append("")
        parts.append("<i>매일 오전 6시에 자동으로 업데이트됩니다.</i>")
        return "\n".join(parts)

    def _build_category_message(self, key: str, articles: List[NewsArticle], page_url: str, date_str: str) -> str:
        meta = CATEGORY_META[key]
        parts = [f'<b>{meta["icon"]} {meta["name"]} 뉴스 ({date_str})</b>', ""]

        top_articles = sorted(articles, key=lambda a: a.is_important, reverse=True)[:TOP_N_PER_CATEGORY]
        if not top_articles:
            parts.append("오늘 수집된 뉴스가 없습니다.")
        for article in top_articles:
            summary = (article.summary or "")[:SUMMARY_TRIM]
            parts.append(f"📌 <b>{article.title}</b>")
            if summary:
                parts.append(summary)
            parts.append(f'🔗 <a href="{article.link}">원문 보기</a>')
            parts.append("")

        parts.append(f'📄 <a href="{self._full_url(page_url)}">전체보기</a>')
        return "\n".join(parts)

    async def send_briefing(self, page_urls: Dict[str, str],
                             categorized_news: Dict[str, List[NewsArticle]], date_str: str):
        """리드 메시지 1개 + 카테고리별 메시지(top3 요약)를 순차 전송."""
        self.logger.info("Sending Telegram notification...")

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=self._build_lead_message(page_urls, date_str),
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

            self.logger.info("Telegram notification sent successfully (9 messages)")
        except TelegramError as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            raise

    def send_briefing_sync(self, page_urls: Dict[str, str],
                            categorized_news: Dict[str, List[NewsArticle]], date_str: str):
        """동기 방식으로 브리핑 전송"""
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(self.send_briefing(page_urls, categorized_news, date_str))
        except Exception as e:
            self.logger.error(f"Error in send_briefing_sync: {e}")
            raise
