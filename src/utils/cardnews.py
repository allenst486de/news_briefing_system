"""
Top10 카드뉴스 이미지 생성 (Pillow)
텔레그램에 텍스트 목록 대신 이미지 한 장으로 보내기 위함.
실패해도 예외를 던지지 않고 None을 반환한다 — 호출부(main.py)가
텍스트 리스트로 폴백하도록.

한글 렌더링을 위해 나눔고딕(SIL OFL 1.1, 재배포 자유)을
src/templates/static/fonts/에 번들했다 — CI 환경에 한글 폰트가
없어도 항상 동작하도록.
"""
import os
from typing import Dict, List, Optional

from PIL import Image, ImageDraw, ImageFont

from .logger import setup_logger

logger = setup_logger()

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'static', 'fonts')
_FONT_REGULAR = os.path.join(_FONT_DIR, 'NanumGothic-Regular.ttf')
_FONT_BOLD = os.path.join(_FONT_DIR, 'NanumGothic-Bold.ttf')

_WIDTH, _HEIGHT = 1080, 1620
_BG = (15, 17, 23)
_CARD_BG = (30, 34, 53)
_ACCENT = (91, 141, 238)
_TEXT_PRIMARY = (232, 234, 240)
_TEXT_SECONDARY = (155, 163, 188)
_WHITE = (255, 255, 255)

_CATEGORY_COLORS = {
    'politics': (249, 115, 22), 'economy': (34, 197, 94), 'society': (234, 179, 8),
    'life': (236, 72, 153), 'culture': (168, 85, 247), 'it': (6, 182, 212),
    'science': (20, 184, 166), 'world': (139, 92, 246),
}


def _truncate_to_width(draw, text: str, font, max_width: float) -> str:
    """폭에 맞을 때까지 한 글자씩 줄이고 맞지 않으면 말줄임표를 붙인다."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    truncated = text
    while truncated and draw.textlength(truncated + '…', font=font) > max_width:
        truncated = truncated[:-1]
    return truncated + '…' if truncated else text[:1]


def generate_top10_card(top10: List[Dict], date_str: str, output_path: str) -> Optional[str]:
    """성공 시 저장된 파일 경로, 실패 시 None."""
    if not top10:
        return None

    try:
        font_title = ImageFont.truetype(_FONT_BOLD, 48)
        font_date = ImageFont.truetype(_FONT_REGULAR, 30)
        font_rank = ImageFont.truetype(_FONT_BOLD, 28)
        font_headline = ImageFont.truetype(_FONT_BOLD, 32)
        font_tag = ImageFont.truetype(_FONT_REGULAR, 22)
        font_footer = ImageFont.truetype(_FONT_REGULAR, 24)

        img = Image.new('RGB', (_WIDTH, _HEIGHT), _BG)
        draw = ImageDraw.Draw(img)

        draw.text((60, 56), "📰 오늘의 뉴스 Top 10", font=font_title, fill=_TEXT_PRIMARY)
        draw.text((60, 120), date_str, font=font_date, fill=_TEXT_SECONDARY)

        top_y = 200
        pad_x = 60
        row_gap = 12
        row_h = (_HEIGHT - top_y - 90 - row_gap * 9) // 10
        row_w = _WIDTH - pad_x * 2

        for i, item in enumerate(top10[:10]):
            y = top_y + i * (row_h + row_gap)
            draw.rounded_rectangle([pad_x, y, pad_x + row_w, y + row_h], radius=16, fill=_CARD_BG)

            cy = y + row_h // 2
            badge_r = 26
            cx = pad_x + 40
            draw.ellipse([cx - badge_r, cy - badge_r, cx + badge_r, cy + badge_r], fill=_ACCENT)
            rank_text = str(item.get('rank', i + 1))
            rw = draw.textlength(rank_text, font=font_rank)
            draw.text((cx - rw / 2, cy - 16), rank_text, font=font_rank, fill=_WHITE)

            tag_color = _CATEGORY_COLORS.get(item.get('category'), _ACCENT)
            tag_text = item.get('category_name', '')
            tag_x = cx + badge_r + 20
            tw = draw.textlength(tag_text, font=font_tag)
            draw.rounded_rectangle([tag_x, cy - 16, tag_x + tw + 20, cy + 16], radius=14, fill=tag_color)
            draw.text((tag_x + 10, cy - 13), tag_text, font=font_tag, fill=_WHITE)

            text_x = tag_x + tw + 40
            max_w = pad_x + row_w - text_x - 20
            headline = _truncate_to_width(draw, item.get('card_headline', ''), font_headline, max_w)
            draw.text((text_x, cy - 26), headline, font=font_headline, fill=_TEXT_PRIMARY)
            source = _truncate_to_width(draw, item.get('source', ''), font_tag, max_w)
            draw.text((text_x, cy + 12), source, font=font_tag, fill=_TEXT_SECONDARY)

        draw.text((60, _HEIGHT - 56), "일일 뉴스 브리핑", font=font_footer, fill=_TEXT_SECONDARY)

        img.save(output_path, 'PNG')
        return output_path
    except Exception as e:
        logger.warning(f"Top10 card image generation failed: {e}")
        return None
