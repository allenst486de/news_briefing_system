import html
import requests
import feedparser
import re
from datetime import datetime


USER_AGENT = {
    "User-Agent": "Mozilla/5.0 (NewsAggregator Bot)"
}


def fetch_feed(url: str):
    try:
        response = requests.get(url, headers=USER_AGENT, timeout=10)
        response.raise_for_status()

        feed = feedparser.parse(response.content)

        if feed.bozo:
            return None

        return feed

    except Exception:
        return None


_GOOGLE_NEWS_WRAPPER = re.compile(
    r'^\s*<a[^>]*>.*?</a>\s*(?:&nbsp;)+\s*<font[^>]*>.*?</font>\s*$',
    re.IGNORECASE | re.DOTALL,
)


def clean_html(text: str) -> str:
    """
    태그 제거 + HTML 엔티티 복원(&nbsp; 등이 리터럴 텍스트로 노출되는 것 방지).
    구글 뉴스 description은 항상 "<a>제목</a>&nbsp;&nbsp;<font>출처도메인</font>"
    형태뿐이라 실질 요약이 없다 — 그대로 두면 "v.daum.net" 같은 도메인명이 요약
    본문에 그대로 섞여 나온다(실제 피드에서 확인). 이 패턴이면 빈 문자열을 반환해
    호출부가 제목 기반 폴백을 쓰게 한다.
    """
    raw = text or ""
    if _GOOGLE_NEWS_WRAPPER.match(raw):
        return ""
    stripped = re.sub("<[^<]+?>", "", raw)
    return html.unescape(stripped)


def extract_date(entry, parse_func):
    date_str = entry.get("published") or entry.get("updated") or ""
    return parse_func(date_str)


_GOOGLE_NEWS_TITLE_SUFFIX = re.compile(r'\s+-\s+[^-]{1,30}$')


def strip_google_news_title_suffix(title: str) -> str:
    """구글 뉴스는 제목 끝에 항상 ' - 출처명'(예: ' - v.daum.net')을 붙인다 — 제거."""
    return _GOOGLE_NEWS_TITLE_SUFFIX.sub('', title or '').strip()


def strip_title_prefix(summary: str, title: str) -> str:
    """
    요약이 제목과 완전히 같은 문자열로 시작하면 그 부분을 제거.
    Google News 등 여러 언론사 헤드라인을 이어붙인 description에서
    제목이 요약 맨 앞에 그대로 다시 나오는 경우가 흔해 화면/텔레그램에
    제목이 두 번 보이는 원인이 된다.
    """
    if not summary or not title:
        return summary
    t = title.strip()
    s = summary.strip()
    if t and s.startswith(t):
        return s[len(t):].lstrip('  -–—:·').strip()
    return summary
