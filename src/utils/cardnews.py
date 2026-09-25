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
import re
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


# 나눔고딕에는 한자가 없어 '이란 美에 휴전안'이 '이란    에'로 빈칸이 되었다(2026-09-26).
# 번들 폰트에 없는 글자만 한자가 있는 폰트로 그린다. 맥 기본 폰트(애플 SD 산돌고딕 Neo)는
# 한국 신문이 쓰는 한자(美·中·北·韓·日)를 갖고 있다. 어느 폰트에도 없는 글자는 그대로 둔다.
_FALLBACK_FONTS = [
    '/System/Library/Fonts/AppleSDGothicNeo.ttc',
    '/System/Library/Fonts/Supplemental/AppleGothic.ttf',
    '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
]
_fallback_cache: Dict[Tuple[int, int], object] = {}
_glyph_cache: Dict[Tuple[int, str], bool] = {}


def _fallback_for(font):
    """같은 크기·같은 굵기의 대체 폰트 (없으면 None)"""
    key = (id(font), font.size)
    if key not in _fallback_cache:
        _fallback_cache[key] = None
        bold = 'Bold' in (font.getname()[1] or '')
        for path in _FALLBACK_FONTS:
            if not os.path.exists(path):
                continue
            # 애플 SD 산돌고딕 Neo 묶음에서 6번이 Bold, 0번이 Regular
            index = 6 if bold and path.endswith('AppleSDGothicNeo.ttc') else 0
            try:
                _fallback_cache[key] = ImageFont.truetype(path, font.size, index=index)
                break
            except OSError:
                continue
    return _fallback_cache[key]


def _has_glyph(font, char: str) -> bool:
    """글리프가 있는가 — 없는 글자는 빈 그림(나눔고딕)이나 '없음' 네모(애플 폰트)가 나온다"""
    key = (id(font), char)
    if key not in _glyph_cache:
        mask = font.getmask(char)
        blank = mask.getbbox() is None
        notdef = bytes(font.getmask('\uE000')) == bytes(mask)
        _glyph_cache[key] = not blank and not notdef
    return _glyph_cache[key]


def _runs(text: str, font) -> List[Tuple[str, object]]:
    """[(글자 묶음, 그릴 폰트)] — 번들 폰트에 없는 글자만 대체 폰트로"""
    fallback = _fallback_for(font)
    runs: List[Tuple[str, object]] = []
    for char in str(text):
        use = font
        if fallback is not None and not char.isspace() and not _has_glyph(font, char) \
                and _has_glyph(fallback, char):
            use = fallback
        if runs and runs[-1][1] is use:
            runs[-1] = (runs[-1][0] + char, use)
        else:
            runs.append((char, use))
    return runs


def _len(draw, text: str, font) -> float:
    return sum(draw.textlength(part, font=use) for part, use in _runs(text, font))


def _text(draw, xy, text: str, font, fill) -> None:
    x, y = xy
    for part, use in _runs(text, font):
        draw.text((x, y), part, font=use, fill=fill)
        x += draw.textlength(part, font=use)


def _pastel(rgb: Tuple[int, int, int], white_ratio: float = 0.78) -> Tuple[int, int, int]:
    return tuple(int(c + (255 - c) * white_ratio) for c in rgb)


def _one_line(text: str) -> str:
    """
    개행·연속 공백을 한 칸으로 눌러 준다.

    Pillow의 _len(draw, )는 개행이 든 문자열에 "can't measure length of
    multiline text" 예외를 던진다. 헤드라인은 LLM이 만들어 개행이 섞여 들어올 수
    있고, 그러면 카드 이미지 생성이 통째로 실패해 텔레그램에 인포그래픽이 한 장만
    간다(실제 발생 — 국내/해외 2장 중 1장만 도착했다).
    """
    return re.sub(r'\s+', ' ', str(text or '')).strip()


def _wrap_lines(draw, text: str, font, max_width: float, max_lines: int = 3) -> List[str]:
    """글자 단위로 폭에 맞춰 줄바꿈 (한국어는 어절 간격이 일정하지 않아 글자 단위가 더 안전)."""
    text = _one_line(text)
    lines, current = [], ""
    for ch in text:
        trial = current + ch
        if _len(draw, trial, font=font) > max_width and current:
            lines.append(current)
            current = ch
            if len(lines) == max_lines:
                break
        else:
            current = trial
    if len(lines) < max_lines and current:
        lines.append(current)

    if len(lines) == max_lines and _len(draw, text, font=font) > sum(
        _len(draw, l, font=font) for l in lines
    ):
        last = lines[-1]
        while last and _len(draw, last + '…', font=font) > max_width:
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

        # 이모지는 그릴 폰트가 없어 빈칸만 남는다(제목 앞이 비어 보였다) — 시사용어 카드처럼 뺀다
        heading = f"오늘의 {region_label} 뉴스 Top 10" if region_label else "오늘의 뉴스 Top 10"
        _text(draw, (_MARGIN, 48), heading, font=font_title, fill=_TEXT_PRIMARY)
        _text(draw, (_MARGIN, 106), date_str, font=font_date, fill=_TEXT_SECONDARY)

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
            rank_text = _one_line(item.get('rank', i + 1))
            rw = _len(draw, rank_text, font=font_rank)
            _text(draw, (bx - rw / 2, by - 15), rank_text, font=font_rank, fill=_WHITE)

            # 분야 태그
            tag_text = _one_line(item.get('category_name', ''))
            tag_x = bx + badge_r + 14
            tw = _len(draw, tag_text, font=font_tag)
            tag_y = by - 15
            draw.rounded_rectangle([tag_x, tag_y, tag_x + tw + 22, tag_y + 30], radius=15, fill=accent)
            _text(draw, (tag_x + 11, tag_y + 4), tag_text, font=font_tag, fill=_WHITE)

            # 헤드라인 (최대 3줄)
            headline_y = y + pad + badge_r * 2 + 22
            max_text_w = _CELL_W - pad * 2
            lines = _wrap_lines(draw, item.get('card_headline', ''), font_headline, max_text_w, max_lines=3)
            for li, line in enumerate(lines):
                _text(draw, (x + pad, headline_y + li * 40), line, font=font_headline, fill=_INK)

            # 출처
            source_text = _one_line(item.get('source', ''))
            if source_text:
                _text(draw, (x + pad, y + _CELL_H - pad - 22), source_text, font=font_source,
                          fill=tuple(int(c * 0.55) for c in _INK))

        _text(draw, (_MARGIN, _HEIGHT - _FOOTER_H + 4), "일일 뉴스 브리핑", font=font_footer, fill=_TEXT_SECONDARY)

        img.save(output_path, 'PNG')
        return output_path
    except Exception as e:
        logger.warning(f"Top10 card image generation failed: {e}")
        return None


# ── 시사용어 카드 ────────────────────────────────────────────────────────
# Top10 카드가 2열×5행 포스터라면 이쪽은 1열×5행 목록형이다. 용어는 제목이 짧고
# 뜻풀이가 길어서, 가로로 넓은 칸에 용어와 설명을 위아래로 놓는 편이 읽기 좋다.
_TERM_CARD_W = 1000
_TERM_ROW_H = 190
_TERM_ROWS = 5
_TERM_HEADER_H = 150
_TERM_HEIGHT = _MARGIN + _TERM_HEADER_H + _TERM_ROW_H * _TERM_ROWS \
    + _GAP * (_TERM_ROWS - 1) + _FOOTER_H + _MARGIN
_TERM_WIDTH = _MARGIN * 2 + _TERM_CARD_W


def generate_terms_card(terms: List[Dict], date_str: str, output_path: str,
                        page: int = 1, total_pages: int = 1) -> Optional[str]:
    """
    시사용어 5개를 한 장에 담는다. 성공 시 경로, 실패 시 None.
    page/total_pages는 제목 옆의 '1/2' 표시에만 쓴다.
    """
    if not terms:
        return None

    try:
        img = Image.new('RGB', (_TERM_WIDTH, _TERM_HEIGHT), _BG)
        draw = ImageDraw.Draw(img)

        font_title = ImageFont.truetype(_FONT_BOLD, 44)
        font_date = ImageFont.truetype(_FONT_REGULAR, 26)
        font_tag = ImageFont.truetype(_FONT_BOLD, 20)
        font_term = ImageFont.truetype(_FONT_BOLD, 34)
        font_def = ImageFont.truetype(_FONT_REGULAR, 24)
        font_source = ImageFont.truetype(_FONT_REGULAR, 20)
        font_footer = ImageFont.truetype(_FONT_REGULAR, 22)

        # 번들 폰트(나눔고딕)에 이모지 글리프가 없어 제목에 이모지를 쓰면 빈칸만 남는다
        title = "오늘의 시사용어"
        if total_pages > 1:
            title += f"  {page}/{total_pages}"
        _text(draw, (_MARGIN, _MARGIN + 10), title, font=font_title, fill=_TEXT_PRIMARY)
        _text(draw, (_MARGIN, _MARGIN + 74), date_str, font=font_date, fill=_TEXT_SECONDARY)

        pad = 26
        for i, item in enumerate(terms[:_TERM_ROWS]):
            y = _MARGIN + _TERM_HEADER_H + i * (_TERM_ROW_H + _GAP)
            accent = _CATEGORY_COLORS.get(item.get('category'), (91, 141, 238))

            draw.rounded_rectangle([_MARGIN, y, _MARGIN + _TERM_CARD_W, y + _TERM_ROW_H],
                                   radius=18, fill=_pastel(accent))
            # 왼쪽 색 띠 — 분야를 한눈에 구분하는 장치(웹 카드의 태그 색과 같은 팔레트)
            draw.rounded_rectangle([_MARGIN, y, _MARGIN + 10, y + _TERM_ROW_H],
                                   radius=5, fill=accent)

            tag_text = _one_line(item.get('category_name', ''))
            tw = _len(draw, tag_text, font=font_tag)
            tag_x = _MARGIN + pad
            draw.rounded_rectangle([tag_x, y + pad - 2, tag_x + tw + 22, y + pad + 28],
                                   radius=15, fill=accent)
            _text(draw, (tag_x + 11, y + pad + 2), tag_text, font=font_tag, fill=_WHITE)

            term_lines = _wrap_lines(draw, item.get('term', ''), font_term,
                                     _TERM_CARD_W - pad * 2 - tw - 40, max_lines=1)
            if term_lines:
                _text(draw, (tag_x + tw + 40, y + pad - 1), term_lines[0], font=font_term, fill=_INK)

            def_lines = _wrap_lines(draw, item.get('definition', ''), font_def,
                                    _TERM_CARD_W - pad * 2, max_lines=3)
            for li, line in enumerate(def_lines):
                _text(draw, (tag_x, y + pad + 48 + li * 33), line, font=font_def,
                          fill=tuple(int(c * 0.82) for c in _INK))

            source_text = _one_line(item.get('source', ''))
            if source_text:
                _text(draw, (tag_x, y + _TERM_ROW_H - pad - 20), f"출처 · {source_text}",
                          font=font_source, fill=tuple(int(c * 0.55) for c in _INK))

        _text(draw, (_MARGIN, _TERM_HEIGHT - _FOOTER_H + 4), "일일 뉴스 브리핑 · 시사용어",
                  font=font_footer, fill=_TEXT_SECONDARY)

        img.save(output_path, 'PNG')
        return output_path
    except Exception as e:
        logger.warning(f"Terms card image generation failed: {e}")
        return None


def generate_terms_cards(terms: List[Dict], date_str: str, output_dir: str) -> List[str]:
    """용어 목록을 5개씩 끊어 여러 장 생성. 생성된 파일 경로 목록을 순서대로 반환."""
    paths = []
    pages = [terms[i:i + _TERM_ROWS] for i in range(0, len(terms), _TERM_ROWS)]
    pages = [p for p in pages if len(p) == _TERM_ROWS]  # 반쯤 빈 장은 만들지 않는다
    for idx, chunk in enumerate(pages, start=1):
        path = os.path.join(output_dir, f'terms_{date_str}_{idx}.png')
        made = generate_terms_card(chunk, date_str, path, page=idx, total_pages=len(pages))
        if made:
            paths.append(made)
    return paths
