"""
시사용어 누적 저장소.

하루치를 만들고 버리는 게 아니라 **연 단위로 쌓는다** — 오늘의 용어 / 이달의 용어 /
올해의 용어를 같은 데이터에서 뽑아 쓰기 위해서다.

저장 위치: data/terms/YYYY.json  (docs/ 밖 — 발행 대상이 아니다)

중복 판정은 '올해 쌓인 전체'를 상대로 한다. 같은 용어가 며칠 뒤 다른 기사에서
다시 뽑히는 일이 흔한데, 그걸 매번 새 용어로 실으면 목록이 같은 단어로 채워진다.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from .logger import setup_logger

logger = setup_logger()

KST = timezone(timedelta(hours=9))

# 중복 판정용 정규화: 괄호 안 원어, 공백, 가운뎃점, 조사성 접미사를 걷어낸다.
# "이그젬션(Exemption)" 과 "이그젬션" 을 같은 용어로 본다.
_PAREN = re.compile(r'\([^)]*\)|\[[^\]]*\]')
_NON_WORD = re.compile(r'[^0-9A-Za-z가-힣]+')


def normalize_term(term: str) -> str:
    """중복 판정 키. 표시는 원문 그대로 하고 비교만 이 값으로 한다."""
    base = _PAREN.sub(' ', str(term or ''))
    return _NON_WORD.sub('', base).lower()


def _year_path(terms_dir: str, year: int) -> str:
    return os.path.join(terms_dir, f'{year}.json')


def load_year(terms_dir: str, year: int) -> List[Dict]:
    path = _year_path(terms_dir, year)
    if not os.path.exists(path):
        return []
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        # 깨진 파일 때문에 그날 브리핑 전체가 멈추면 안 된다
        logger.warning(f"Terms store unreadable ({path}): {e}")
        return []


def load_known_keys(terms_dir: str, year: int) -> set:
    """올해 이미 실린 용어의 정규화 키. 신규 추출 시 중복 제외에 쓴다."""
    return {normalize_term(t.get('term')) for t in load_year(terms_dir, year)}


def append_terms(terms_dir: str, entries: List[Dict], year: Optional[int] = None) -> int:
    """
    새 용어를 올해 파일에 덧붙인다. 이미 있는 용어는 건너뛴다.
    반환: 실제로 추가된 건수.
    """
    if not entries:
        return 0
    year = year or datetime.now(KST).year
    os.makedirs(terms_dir, exist_ok=True)

    existing = load_year(terms_dir, year)
    known = {normalize_term(t.get('term')) for t in existing}

    added = []
    for entry in entries:
        key = normalize_term(entry.get('term'))
        if not key or key in known:
            continue
        known.add(key)
        added.append(entry)

    if not added:
        return 0

    merged = existing + added
    path = _year_path(terms_dir, year)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # 중간에 죽어도 반쪽 파일이 남지 않게

    logger.info(f"Terms store: +{len(added)} new (total {len(merged)} in {year})")
    return len(added)


def collect_buckets(terms_dir: str, today: Optional[datetime] = None) -> Dict[str, List[Dict]]:
    """
    오늘의 / 이달의 / 올해의 용어를 한 번에 뽑는다.
    각 목록은 최신순(같은 날짜면 나중에 추가된 것이 앞).
    """
    now = today or datetime.now(KST)
    year_terms = load_year(terms_dir, now.year)

    today_str = now.strftime('%Y-%m-%d')
    month_prefix = now.strftime('%Y-%m')

    def newest_first(items):
        return sorted(items, key=lambda t: t.get('date', ''), reverse=True)

    return {
        'today': newest_first([t for t in year_terms if t.get('date') == today_str]),
        'month': newest_first([t for t in year_terms if str(t.get('date', '')).startswith(month_prefix)]),
        'year': newest_first(year_terms),
    }
