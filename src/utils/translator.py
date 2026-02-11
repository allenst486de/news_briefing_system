"""
Translator Utility
해외 뉴스를 한국어로 번역하는 유틸리티
"""
import os
import time
from typing import Optional
from deep_translator import GoogleTranslator
from ..collectors.base_collector import NewsArticle
from .logger import setup_logger

logger = setup_logger()

def translate_text(text: str, max_retries: int = 3) -> str:
    """
    텍스트를 영어에서 한국어로 번역
    
    Args:
        text: 번역할 텍스트
        max_retries: 최대 재시도 횟수
        
    Returns:
        str: 번역된 텍스트
    """
    if not text or not text.strip():
        return text
    
    # 텍스트가 너무 길면 분할
    max_length = 4500  # Google Translate API 제한
    
    if len(text) <= max_length:
        return _translate_chunk(text, max_retries)
    
    # 긴 텍스트는 문장 단위로 분할하여 번역
    sentences = text.split('. ')
    translated_sentences = []
    current_chunk = ""
    
    for sentence in sentences:
        if len(current_chunk) + len(sentence) + 2 <= max_length:
            current_chunk += sentence + ". "
        else:
            if current_chunk:
                translated_sentences.append(_translate_chunk(current_chunk.strip(), max_retries))
            current_chunk = sentence + ". "
    
    if current_chunk:
        translated_sentences.append(_translate_chunk(current_chunk.strip(), max_retries))
    
    return " ".join(translated_sentences)


def _translate_chunk(text: str, max_retries: int = 3) -> str:
    """
    텍스트 청크를 번역 (재시도 로직 포함)
    
    Args:
        text: 번역할 텍스트
        max_retries: 최대 재시도 횟수
        
    Returns:
        str: 번역된 텍스트
    """
    translator = GoogleTranslator(source='auto', target='ko')
    
    for attempt in range(max_retries):
        try:
            translated = translator.translate(text)
            return translated
        except Exception as e:
            logger.warning(f"Translation attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(1)  # 재시도 전 대기
            else:
                logger.error(f"Translation failed after {max_retries} attempts")
                return text  # 번역 실패 시 원문 반환


def translate_article(article: NewsArticle) -> NewsArticle:
    """
    뉴스 기사를 번역
    
    Args:
        article: 원본 기사
        
    Returns:
        NewsArticle: 번역된 기사
    """
    try:
        # 제목 번역
        translated_title = translate_text(article.title)
        
        # 요약 번역
        translated_summary = translate_text(article.summary) if article.summary else ""
        
        # 새로운 기사 객체 생성 (번역된 내용 + 원본 출처 유지)
        translated_article = NewsArticle(
            title=translated_title,
            link=article.link,
            published=article.published,
            summary=translated_summary,
            source=f"{article.source} (번역)",
            category=article.category
        )
        translated_article.is_important = article.is_important
        
        # 원본 제목과 요약을 속성으로 저장
        translated_article.original_title = article.title
        translated_article.original_summary = article.summary
        
        logger.info(f"Translated: {article.title[:50]}... -> {translated_title[:50]}...")
        
        return translated_article
        
    except Exception as e:
        logger.error(f"Error translating article: {e}")
        return article  # 번역 실패 시 원본 반환
