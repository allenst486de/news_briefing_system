"""
Title normalization for duplicate detection
news_aggregator.py(당일 카테고리 내 중복 제거)와 archiver.py(월 단위 압축 중복 제거)가 공유.
"""
import re


def normalize_title(title: str) -> str:
    """공백/구두점 차이로 인한 중복 누락을 줄이기 위한 정규화."""
    normalized = title.strip().lower()
    normalized = re.sub(r"[\s\W_]+", "", normalized)
    return normalized
