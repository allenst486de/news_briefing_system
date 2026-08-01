"""
Importance Analyzer
뉴스 중요도 분석 유틸리티
"""
from typing import List
import re


class ImportanceAnalyzer:
    """뉴스 중요도 분석기"""
    
    # 중요 키워드 (한국어 + 영어)
    CRITICAL_KEYWORDS = {
        'korean': [
            '전쟁', '사망', '사고', '재난', '붕괴', '폭발', '화재', '지진', '태풍',
            '위기', '비상', '긴급', '경보', '파산', '부도', '폐쇄', '중단',
            '금리', '인상', '인하', '정책', '법안', '통과', '탄핵', '사퇴',
            '북한', '미사일', '핵', '테러', '감염', '확진', '팬데믹'
        ],
        'english': [
            'war', 'death', 'accident', 'disaster', 'collapse', 'explosion', 'fire', 'earthquake',
            'crisis', 'emergency', 'urgent', 'alert', 'bankruptcy', 'shutdown', 'suspended',
            'interest rate', 'policy', 'bill', 'impeachment', 'resignation',
            'missile', 'nuclear', 'terror', 'pandemic', 'outbreak', 'conflict'
        ]
    }
    
    # 경제 관련 중요 키워드
    ECONOMIC_KEYWORDS = {
        'korean': [
            '금리', '환율', '주가', '폭락', '급등', 'GDP', '실업률', '인플레이션',
            '경기침체', '부동산', '가격', '상승', '하락', '무역', '적자', '흑자'
        ],
        'english': [
            'interest rate', 'exchange rate', 'stock', 'crash', 'surge', 'GDP', 'unemployment',
            'inflation', 'recession', 'real estate', 'price', 'trade', 'deficit', 'surplus'
        ]
    }
    
    # 정치 관련 중요 키워드
    POLITICAL_KEYWORDS = {
        'korean': [
            '대통령', '국회', '법안', '선거', '투표', '정책', '개혁', '논란',
            '탄핵', '사퇴', '임명', '해임', '여당', '야당', '정부'
        ],
        'english': [
            'president', 'congress', 'parliament', 'bill', 'election', 'vote', 'policy',
            'reform', 'controversy', 'impeachment', 'resignation', 'appointment', 'government'
        ]
    }
    
    @staticmethod
    def analyze(title: str, summary: str = "") -> bool:
        """
        뉴스의 중요도 분석
        
        Args:
            title: 뉴스 제목
            summary: 뉴스 요약
            
        Returns:
            bool: 중요한 뉴스인 경우 True
        """
        text = (title + " " + summary).lower()
        
        # 모든 키워드 카테고리 확인
        all_keywords = (
            ImportanceAnalyzer.CRITICAL_KEYWORDS['korean'] +
            ImportanceAnalyzer.CRITICAL_KEYWORDS['english'] +
            ImportanceAnalyzer.ECONOMIC_KEYWORDS['korean'] +
            ImportanceAnalyzer.ECONOMIC_KEYWORDS['english'] +
            ImportanceAnalyzer.POLITICAL_KEYWORDS['korean'] +
            ImportanceAnalyzer.POLITICAL_KEYWORDS['english']
        )
        
        # 키워드 매칭
        for keyword in all_keywords:
            if keyword.lower() in text:
                return True
                
        return False
    
    # AI 관련 키워드 — IT 카테고리 내 AI 소식 서브섹션 분류용
    # Phase1 임시 규칙기반 구현. Phase2에서 LLM 프롬프트(b)로 교체되며,
    # 이 키워드 매칭은 LLM 호출 실패 시 폴백으로 재사용된다.
    AI_KEYWORDS = {
        'korean': [
            '인공지능', 'AI', '생성형', '챗봇', '거대언어모델', '딥러닝', '머신러닝',
            'LLM', 'GPT', '오픈AI', '앤스로픽', '제미나이', '클로드', '코파일럿'
        ],
        'english': [
            'artificial intelligence', ' ai ', 'chatbot', 'large language model', 'deep learning',
            'machine learning', 'llm', 'gpt', 'openai', 'anthropic', 'gemini', 'claude', 'copilot'
        ]
    }

    @staticmethod
    def is_ai_related(title: str, summary: str = "") -> bool:
        """IT 카테고리 기사 중 AI 관련 여부 판단 (키워드 매칭)."""
        text = f" {title} {summary} ".lower()
        keywords = ImportanceAnalyzer.AI_KEYWORDS['korean'] + ImportanceAnalyzer.AI_KEYWORDS['english']
        return any(keyword.lower() in text for keyword in keywords)

    @staticmethod
    def get_importance_badge(is_important: bool) -> str:
        """
        중요도에 따른 배지 HTML 반환
        
        Args:
            is_important: 중요 뉴스 여부
            
        Returns:
            str: HTML 배지 태그
        """
        if is_important:
            return '<span class="badge badge-important">⚠️ 중요</span>'
        return ''
