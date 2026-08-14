"""
Title normalization for duplicate detection
news_aggregator.py(당일 카테고리 내 중복 제거)와 archiver.py(월 단위 압축 중복 제거)가 공유.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone

_KST = timezone(timedelta(hours=9))


def _canonical_link(link: str) -> str:
    """추적 파라미터(utm_* 등)를 떼어낸 비교용 URL."""
    return (link or "").split("?")[0].split("#")[0].rstrip("/")


def load_recent_links(raw_data_dir: str, days: int = 7, today=None) -> set:
    """
    최근 N일 일일 스냅샷에 실린 기사 URL 집합.
    같은 기사가 며칠씩 피드에 남아 있어 어제 실린 기사가 오늘 또 올라온다
    (실측: 287건 중 61건, 21%). 제목은 LLM이 매일 다르게 재서술해서 못 잡고
    URL이 유일하게 안정적인 키다.
    """
    if not raw_data_dir or not os.path.isdir(raw_data_dir):
        return set()

    base = (today or datetime.now(_KST)).date()
    links = set()
    for back in range(1, days + 1):
        day = base - timedelta(days=back)
        path = os.path.join(raw_data_dir, f"{day.year:04d}", f"{day.month:02d}", f"{day.day:02d}.json")
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                snapshot = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        for entry in (snapshot.get("categories") or {}).values():
            groups = entry.values() if isinstance(entry, dict) else [entry]
            for articles in groups:
                for article in articles:
                    canonical = _canonical_link(article.get("link", ""))
                    if canonical:
                        links.add(canonical)
    return links


def normalize_title(title: str) -> str:
    """공백/구두점 차이로 인한 중복 누락을 줄이기 위한 정규화."""
    normalized = title.strip().lower()
    normalized = re.sub(r"[\s\W_]+", "", normalized)
    return normalized
