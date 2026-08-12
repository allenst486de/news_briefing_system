import calendar
import html
import requests
import feedparser
import re
from datetime import datetime, timedelta, timezone


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


def extract_date(entry, parse_func, feed_anchor=None, index=0):
    """
    발행일 추출. 우선순위:
      1) feedparser가 이미 파싱해 둔 published_parsed/updated_parsed
         — RFC822뿐 아니라 ISO 8601(<dc:date>)도 처리한다. 경향신문이
           ISO를 쓰는데 예전엔 RFC822 파서만 돌려 전부 실패했다.
      2) 원문 문자열을 parse_func으로 재시도
      3) 피드에 날짜가 아예 없으면(한겨레) feed_anchor 기준으로 목록 순서를
         이용해 근사치를 만든다 — RSS는 최신순이라 index가 클수록 오래된 글이다.
         날짜를 now()로 찍어버리면 그 매체가 항상 '최신'이 되어 정렬 상위를
         독식하고 다른 매체가 밀려난다(실제로 그랬다).
    반환: (published, is_approximate)
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        try:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc), False
        except (ValueError, OverflowError, TypeError):
            pass

    raw = entry.get("published") or entry.get("updated") or ""
    if raw:
        try:
            return parse_func(raw), False
        except Exception:
            pass

    anchor = feed_anchor or datetime.now(timezone.utc)
    return anchor - timedelta(minutes=index), True


def feed_anchor_time(feed):
    """피드 자체의 갱신 시각 — 항목에 날짜가 없는 피드의 기준점."""
    parsed = getattr(feed, "feed", {}).get("updated_parsed") if feed else None
    if parsed:
        try:
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
        except (ValueError, OverflowError, TypeError):
            pass
    return datetime.now(timezone.utc)


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
