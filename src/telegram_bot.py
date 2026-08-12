"""
Telegram Bot
텔레그램으로 뉴스 브리핑 요약 전송

하루에 보내는 건 2개뿐이다: Top10 인포그래픽 이미지 1장 + "일일 뉴스 브리핑"
메시지 1개. 분야별 상세 내용은 메시지로 보내지 않고, 브리핑 메시지의 분야별
링크를 눌러 웹 페이지에서 보게 한다(각 기사 250자 요약은 그 페이지에 있다).
Top10은 이미지와 텍스트 목록을 함께 보낸다 — 웹 홈 화면의 Top10과 동일한
데이터(summarizer.select_top10)를 그대로 재사용하므로 내용은 항상 같다.

모든 링크(뉴스 원문 링크 포함, 분야별 바로가기/아카이브/홈 등 내비게이션 링크
포함)는 텍스트로 감싼 링크(<a href="URL">텍스트</a>)를 쓴다 — URL을 그대로
노출하지 않는다는 요청에 따른 것. 단, 표시 텍스트와 실제 URL이 다르면 텔레그램
클라이언트가 피싱 방지용 "이 링크를 여시겠습니까?" 확인 팝업을 띄운다 — 가독성을
팝업 없음보다 우선한 트레이드오프다.
"""
import asyncio
from typing import Dict, List, Optional, Tuple
from telegram import Bot
from telegram.error import TelegramError
from .collectors.sources import CATEGORIES, CATEGORY_META
from .utils.logger import setup_logger


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

    def _build_lead_message(self, page_urls: Dict[str, str],
                             top10_by_region: Dict[str, List[Dict]], date_str: str) -> str:
        parts = [f"<b>📰 일일 뉴스 브리핑 ({date_str})</b>", ""]

        for region, label in (("domestic", "국내"), ("overseas", "해외")):
            cards = top10_by_region.get(region) or []
            if not cards:
                continue
            parts.append(f"🔥 <b>오늘의 {label} Top 10</b>")
            for item in cards:
                parts.append(f'{item["rank"]}. <b>{item["card_headline"]}</b>')
                parts.append(f'{item.get("category_name", "")} · {item.get("source", "")} · '
                              f'<a href="{item["link"]}">원문 보기</a>')
            parts.append("")

        parts.append("📂 <b>분야별 바로가기</b>")
        nav_links = []
        for key in CATEGORIES:
            url = page_urls.get(key)
            if not url:
                continue
            meta = CATEGORY_META[key]
            nav_links.append(f'<a href="{self._full_url(url)}">{meta["icon"]} {meta["name"]}</a>')
        parts.append(" · ".join(nav_links))

        parts.append("")
        # 아카이브는 링크하지 않는다 — 과거 기록은 직접 링크를 아는 사람만 보도록(요청사항)
        parts.append(f'🏠 <a href="{self._full_url("index.html")}">홈(최신 브리핑)</a>')
        parts.append("")
        parts.append("<i>분야별 링크를 누르면 국내·해외 탭과 기사별 요약이 있는 전체 목록으로 이동합니다.</i>")
        parts.append("<i>매일 오전 6시에 자동으로 업데이트됩니다.</i>")
        parts.append("⚠️ 경제 분야의 종목 추천은 정보 제공 목적이며 투자 자문이 아닙니다.")
        return "\n".join(parts)

    async def send_briefing(self, page_urls: Dict[str, str],
                             top10_by_region: Dict[str, List[Dict]], date_str: str,
                             images: Optional[List[Tuple[str, str]]] = None):
        """국내/해외 Top10 인포그래픽(있으면) + 일일 뉴스 브리핑 메시지 1개 전송."""
        self.logger.info("Sending Telegram notification...")

        try:
            for path, label in (images or []):
                try:
                    with open(path, 'rb') as photo:
                        await self.bot.send_photo(chat_id=self.chat_id, photo=photo,
                                                   caption=f"🔥 오늘의 {label} Top 10 ({date_str})")
                except (TelegramError, OSError) as e:
                    # 이미지가 실패해도 아래 텍스트 목록은 그대로 나간다
                    self.logger.warning(f"Top10 {label} image send failed: {e}")

            await self.bot.send_message(
                chat_id=self.chat_id,
                text=self._build_lead_message(page_urls, top10_by_region, date_str),
                parse_mode='HTML',
                disable_web_page_preview=True,
            )

            self.logger.info("Telegram notification sent successfully")
        except TelegramError as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            raise

    def send_briefing_sync(self, page_urls: Dict[str, str],
                            top10_by_region: Dict[str, List[Dict]], date_str: str,
                            images: Optional[List[Tuple[str, str]]] = None):
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
                self.send_briefing(page_urls, top10_by_region, date_str, images)
            )
        except Exception as e:
            self.logger.error(f"Error in send_briefing_sync: {e}")
            raise
