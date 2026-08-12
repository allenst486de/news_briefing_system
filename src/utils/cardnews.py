"""
Top10 카드뉴스 이미지 생성 (Pillow)
텔레그램에 텍스트 목록과 별도로 함께 보내는 인포그래픽 한 장.
실패해도 예외를 던지지 않고 None을 반환한다 — 호출부(main.py)가 텍스트 목록만으로도
계속 동작하도록.

디자인: 어두운 캔버스 위에 순위 10개를 2열×5행 카드 그리드로 배치하고, 각 카드는
분야별 강조색을 파스텔로 우려낸 배경 + 진한 헤드라인 텍스트로 구성한다 — 실제
일러스트 없이도 "카드뉴스" 느낌(칸마다 다른 색, 굵은 타이포)을 내기 위한 절충이다.
매일 자동 생성되는 동적 콘텐츠라 AI 이미지 생성/수동 디자인 도구 대신 순수 코드로
그린다 — 매일 다른 헤드라인 10개를 텍스트 오버레이 걱정 없이 안정적으로 넣을 수
있는 유일한 방법.

한글 렌더링을 위해 나눔고딕(SIL OFL 1.1, 재배포 자유)을
src/templates/static/fonts/에 번들했다 — CI 환경에 한글 폰트가
없어도 항상 동작하도록.
"""
import os
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .logger import setup_logger

logger = setup_logger()

_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'templates', 'static', 'fonts')
_FONT_REGULAR = os.path.join(_FONT_DIR, 'NanumGothic-Regular.ttf')
_FONT_BOLD = os.path.join(_FONT_DIR, 'NanumGothic-Bold.ttf')

_BG = (15, 17, 23)
_TEXT_PRIMARY = (232, 234, 240)
_TEXT_SECONDARY = (155, 163, 188)
_INK = (26, 29, 41)  # 카드 안 헤드라인 색 — 파스텔 배경 위에서 항상 잘 읽히는 짙은 남색
_WHITE = (255, 255, 255)

_CATEGORY_COLORS = {
    'politics': (249, 115, 22), 'economy': (34, 197, 94), 'society': (234, 179, 8),
    'life': (236, 72, 153), 'culture': (168, 85, 247), 'it': (6, 182, 212),
    'science': (20, 184, 166), 'world': (139, 92, 246),
}

_COLS, _ROWS = 2, 5
_CELL_W, _CELL_H, _GAP = 490, 320, 20
_MARGIN = 40
_HEADER_H = 150
_FOOTER_H = 60

_WIDTH = _MARGIN * 2 + _CELL_W * _COLS + _GAP * (_COLS - 1)
_GRID_TOP = _MARGIN + _HEADER_H
_HEIGHT = _GRID_TOP + _CELL_H * _ROWS + _GAP * (_ROWS - 1) + _FOOTER_H + _MARGIN


def _pastel(rgb: Tuple[int, int, int], white_ratio: float = 0.78) -> Tuple[int, int, int]:
    return tuple(int(c + (255 - c) * white_ratio) for c in rgb)


def _wrap_lines(draw, text: str, font, max_width: float, max_lines: int = 3) -> List[str]:
    """글자 단위로 폭에 맞춰 줄바꿈 (한국어는 어절 간격이 일정하지 않아 글자 단위가 더 안전)."""
    lines, current = [], ""
    for ch in text:
        trial = current + ch
        if draw.textlength(trial, font=font) > max_width and current:
            lines.append(current)
            current = ch
            if len(lines) == max_lines:
                break
        else:
            current = trial
    if len(lines) < max_lines and current:
        lines.append(current)

    if len(lines) == max_lines and draw.textlength(text, font=font) > sum(
        draw.textlength(l, font=font) for l in lines
    ):
        last = lines[-1]
        while last and draw.textlength(last + '…', font=font) > max_width:
            last = last[:-1]
        lines[-1] = last + '…'
    return lines


def generate_top10_card(top10: List[Dict], date_str: str, output_path: str,
                         region_label: str = "") -> Optional[str]:
    """성공 시 저장된 파일 경로, 실패 시 None. region_label은 제목에 붙는 국내/해외 구분."""
    if not top10:
        return None

    try:
        font_title = ImageFont.truetype(_FONT_BOLD, 44)
        font_date = ImageFont.truetype(_FONT_REGULAR, 26)
        font_rank = ImageFont.truetype(_FONT_BOLD, 24)
        font_tag = ImageFont.truetype(_FONT_BOLD, 20)
        font_headline = ImageFont.truetype(_FONT_BOLD, 30)
        font_source = ImageFont.truetype(_FONT_REGULAR, 20)
        font_footer = ImageFont.truetype(_FONT_REGULAR, 22)

        img = Image.new('RGB', (_WIDTH, _HEIGHT), _BG)
        draw = ImageDraw.Draw(img)

        heading = f"🔥 오늘의 {region_label} 뉴스 Top 10" if region_label else "🔥 오늘의 뉴스 Top 10"
        draw.text((_MARGIN, 48), heading, font=font_title, fill=_TEXT_PRIMARY)
        draw.text((_MARGIN, 106), date_str, font=font_date, fill=_TEXT_SECONDARY)

        pad = 24
        for i, item in enumerate(top10[:_COLS * _ROWS]):
            col, row = i % _COLS, i // _COLS
            x = _MARGIN + col * (_CELL_W + _GAP)
            y = _GRID_TOP + row * (_CELL_H + _GAP)
            accent = _CATEGORY_COLORS.get(item.get('category'), (91, 141, 238))

            draw.rounded_rectangle([x, y, x + _CELL_W, y + _CELL_H], radius=20, fill=_pastel(accent))

            # 순위 배지
            badge_r = 22
            bx, by = x + pad + badge_r, y + pad + badge_r
            draw.ellipse([bx - badge_r, by - badge_r, bx + badge_r, by + badge_r], fill=accent)
            rank_text = str(item.get('rank', i + 1))
            rw = draw.textlength(rank_text, font=font_rank)
            draw.text((bx - rw / 2, by - 15), rank_text, font=font_rank, fill=_WHITE)

            # 분야 태그
            tag_text = item.get('category_name', '')
            tag_x = bx + badge_r + 14
            tw = draw.textlength(tag_text, font=font_tag)
            tag_y = by - 15
            draw.rounded_rectangle([tag_x, tag_y, tag_x + tw + 22, tag_y + 30], radius=15, fill=accent)
            draw.text((tag_x + 11, tag_y + 4), tag_text, font=font_tag, fill=_WHITE)

            # 헤드라인 (최대 3줄)
            headline_y = y + pad + badge_r * 2 + 22
            max_text_w = _CELL_W - pad * 2
            lines = _wrap_lines(draw, item.get('card_headline', ''), font_headline, max_text_w, max_lines=3)
            for li, line in enumerate(lines):
                draw.text((x + pad, headline_y + li * 40), line, font=font_headline, fill=_INK)

            # 출처
            source_text = item.get('source', '')
            if source_text:
                draw.text((x + pad, y + _CELL_H - pad - 22), source_text, font=font_source,
                          fill=tuple(int(c * 0.55) for c in _INK))

        draw.text((_MARGIN, _HEIGHT - _FOOTER_H + 4), "일일 뉴스 브리핑", font=font_footer, fill=_TEXT_SECONDARY)

        img.save(output_path, 'PNG')
        return output_path
    except Exception as e:
        logger.warning(f"Top10 card image generation failed: {e}")
        return None
