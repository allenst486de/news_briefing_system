"""
Telegram Bot
텔레그램으로 뉴스 브리핑 링크 전송
"""
from typing import Dict
from telegram import Bot
from telegram.error import TelegramError
from .utils.logger import setup_logger


class TelegramNotifier:
    """텔레그램 알림 전송기"""
    
    CATEGORY_EMOJI = {
        'domestic_general': '🇰🇷',
        'domestic_economy': '💰',
        'domestic_politics': '🏛️',
        'world_general': '🌍',
        'world_economy_politics': '🌐'
    }
    
    CATEGORY_NAMES = {
        'domestic_general': '국내 종합 뉴스',
        'domestic_economy': '국내 경제 뉴스',
        'domestic_politics': '국내 정치/시사 뉴스',
        'world_general': '세계 종합 뉴스',
        'world_economy_politics': '세계 경제/정치/시사 뉴스'
    }
    
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

    async def send_briefing(self, page_urls: Dict[str, str], date_str: str):
        """
        브리핑 링크를 텔레그램으로 전송.
        parse_mode='HTML' 사용 → URL 언더바(_) 문제 없음
        """
        self.logger.info("Sending Telegram notification...")
        self.logger.info(f"Base URL: {self.base_url}")
        self.logger.info(f"Page URLs: {page_urls}")

        # HTML 태그로 굵게 처리; URL은 절대 태그 안에 넣지 않음
        parts = [
            f"<b>📰 일일 뉴스 브리핑 ({date_str})</b>",
            "",
            "오늘의 주요 뉴스를 확인하세요!",
            "",
        ]

        for category, url in page_urls.items():
            if category not in self.CATEGORY_NAMES:
                continue
            emoji = self.CATEGORY_EMOJI.get(category, '📌')
            name = self.CATEGORY_NAMES[category]
            clean_url = url.lstrip('/')
            full_url = f"{self.base_url}/{clean_url}"
            self.logger.info(f"URL [{category}]: {full_url}")

            parts.append(f"{emoji} <b>{name}</b>")
            parts.append(f"🔗 {full_url}")
            parts.append("")

        archive_url = f"{self.base_url}/archive.html"
        parts.append(f'📚 <a href="{archive_url}">아카이브 보기</a>')
        parts.append("")
        parts.append("<i>매일 오전 6시에 자동으로 업데이트됩니다.</i>")

        # 실제 줄바꿈 문자(\n)로 합치기
        message = "\n".join(parts)
        # GitHub Actions 로그는 public 저장소에서 누구나 볼 수 있으므로 debug로 낮춤
        self.logger.debug(f"Final message:\n{message}")

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML',           # Markdown 대신 HTML 사용
                disable_web_page_preview=True
            )
            self.logger.info("Telegram notification sent successfully")
        except TelegramError as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            raise

    def send_briefing_sync(self, page_urls: Dict[str, str], date_str: str):
        """동기 방식으로 브리핑 전송"""
        import asyncio
        try:
            try:
                loop = asyncio.get_event_loop()
                if loop.is_closed():
                    raise RuntimeError
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.run_until_complete(self.send_briefing(page_urls, date_str))
        except Exception as e:
            self.logger.error(f"Error in send_briefing_sync: {e}")
            raise
