"""
Telegram Bot
텔레그램으로 뉴스 브리핑 링크 전송
"""
import os
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
        """
        self.logger = setup_logger()
        self.bot = Bot(token=bot_token)
        self.chat_id = chat_id
        # base_url에서 trailing slash 제거
        self.base_url = base_url.rstrip('/')
        self.logger.info(f"Telegram bot initialized with base URL: {self.base_url}")
        
    async def send_briefing(self, page_urls: Dict[str, str], date_str: str):
        """
        브리핑 링크를 텔레그램으로 전송
        
        Args:
            page_urls: 카테고리별 페이지 URL 딕셔너리 (예: {"domestic_general": "2026/02/11/domestic_general.html"})
            date_str: 날짜 문자열
        """
        self.logger.info("Sending Telegram notification...")
        self.logger.info(f"Page URLs received: {page_urls}")
        
        # 메시지 구성
        message = f"📰 *일일 뉴스 브리핑* ({date_str})\\n\\n"
        message += "오늘의 주요 뉴스를 확인하세요!\\n\\n"
        
        for category, url in page_urls.items():
            if category in self.CATEGORY_NAMES:
                emoji = self.CATEGORY_EMOJI.get(category, '📌')
                name = self.CATEGORY_NAMES[category]
                
                # URL이 이미 /로 시작하면 그대로 사용, 아니면 /를 추가
                if url.startswith('/'):
                    full_url = f"{self.base_url}{url}"
                else:
                    full_url = f"{self.base_url}/{url}"
                
                self.logger.info(f"Generated URL for {category}: {full_url}")
                
                message += f"{emoji} *{name}*\\n"
                message += f"🔗 {full_url}\\n\\n"
        
        # 아카이브 링크
        archive_url = f"{self.base_url}/archive.html"
        message += f"📚 [아카이브 보기]({archive_url})\\n\\n"
        message += "_매일 오전 6시에 자동으로 업데이트됩니다._"
        
        self.logger.info(f"Final message:\n{message}")
        
        try:
            # 메시지 전송
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            self.logger.info("Telegram notification sent successfully")
            
        except TelegramError as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            raise
    
    def send_briefing_sync(self, page_urls: Dict[str, str], date_str: str):
        """
        동기 방식으로 브리핑 전송 (비동기 래퍼)
        
        Args:
            page_urls: 카테고리별 페이지 URL 딕셔너리
            date_str: 날짜 문자열
        """
        import asyncio
        
        try:
            # 이벤트 루프 가져오기 또는 생성
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            # 비동기 함수 실행
            loop.run_until_complete(self.send_briefing(page_urls, date_str))
            
        except Exception as e:
            self.logger.error(f"Error in send_briefing_sync: {e}")
            raise
