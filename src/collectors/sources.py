"""
News Source Registry
언론사 RSS 피드 설정 — 신규 언론사 추가는 클래스 작성 없이 이 목록에 항목만 추가하면 됨.

각 소스의 feeds 딕셔너리 키가 곧 최종 카테고리 키(CATEGORIES)이다.
URL은 구현 시점(2026-08)에 curl로 상태코드+content-type을 직접 확인한 것만 등재했다.
확인 결과 죽어있던 후보(매일경제, 조선일보, KBS, YTN, Reuters/AP/CNN, 코리아헤럴드,
전자신문-카테고리 미분리)는 제외했다 — 새로 추가하려면 test_feeds.py로 먼저 검증할 것.
"""

CATEGORIES = ["politics", "economy", "society", "life", "culture", "it", "science", "world"]

CATEGORY_META = {
    "politics": {"name": "정치", "icon": "🏛️"},
    "economy":  {"name": "경제", "icon": "💰"},
    "society":  {"name": "사회", "icon": "👥"},
    "life":     {"name": "생활", "icon": "🌱"},
    "culture":  {"name": "문화", "icon": "🎭"},
    "it":       {"name": "IT", "icon": "💻"},
    "science":  {"name": "과학", "icon": "🔬"},
    "world":    {"name": "국제", "icon": "🌍"},
}

SOURCES = [
    {
        "id": "yonhap", "name": "연합뉴스TV", "language": "ko", "limit": 15,
        "feeds": {
            "politics": "https://www.yonhapnewstv.co.kr/category/news/politics/feed/",
            "economy":  "https://www.yonhapnewstv.co.kr/category/news/economy/feed/",
            "society":  "https://www.yonhapnewstv.co.kr/category/news/society/feed/",
            "world":    "https://www.yonhapnewstv.co.kr/category/news/international/feed/",
        },
    },
    {
        "id": "googlenews", "name": "구글 뉴스", "language": "ko", "limit": 15,
        "feeds": {
            "politics": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtdHZLQUFQAQ?hl=ko&gl=KR&ceid=KR:ko",
            "economy":  "https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSnJieWdBUAE?hl=ko&gl=KR&ceid=KR:ko",
            # society 토픽 ID는 test_feeds.py 확인 결과 죽어있어 제외 (yonhap/guardian/hani가 society 커버)
            "world":    "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
            "it":       "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
        },
    },
    {
        "id": "bbc", "name": "BBC News", "language": "en", "limit": 10,
        "feeds": {
            "world":    "http://feeds.bbci.co.uk/news/world/rss.xml",
            "economy":  "http://feeds.bbci.co.uk/news/business/rss.xml",
            "politics": "http://feeds.bbci.co.uk/news/politics/rss.xml",
            "it":       "http://feeds.bbci.co.uk/news/technology/rss.xml",
            "science":  "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        },
    },
    {
        "id": "nyt", "name": "New York Times", "language": "en", "limit": 10,
        "feeds": {
            "world":    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "economy":  "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
            "politics": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
            "it":       "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
            "science":  "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        },
    },
    {
        "id": "guardian", "name": "The Guardian", "language": "en", "limit": 10,
        "feeds": {
            "world":    "https://www.theguardian.com/world/rss",
            "economy":  "https://www.theguardian.com/uk/business/rss",
            "politics": "https://www.theguardian.com/politics/rss",
            "it":       "https://www.theguardian.com/uk/technology/rss",
            "science":  "https://www.theguardian.com/science/rss",
            "culture":  "https://www.theguardian.com/uk/culture/rss",
            "society":  "https://www.theguardian.com/society/rss",
            "life":     "https://www.theguardian.com/uk/lifeandstyle/rss",
        },
    },
    {
        "id": "aljazeera", "name": "Al Jazeera", "language": "en", "limit": 15,
        "feeds": {
            # 통합 피드 하나뿐이라 world에만 매핑
            "world": "https://www.aljazeera.com/xml/rss/all.xml",
        },
    },
    {
        "id": "hani", "name": "한겨레", "language": "ko", "limit": 15,
        "feeds": {
            "politics": "https://www.hani.co.kr/rss/politics",
            "economy":  "https://www.hani.co.kr/rss/economy",
            "society":  "https://www.hani.co.kr/rss/society",
            "world":    "https://www.hani.co.kr/rss/international",
            "culture":  "https://www.hani.co.kr/rss/culture",
            "science":  "https://www.hani.co.kr/rss/science",
        },
    },
    {
        "id": "hankyung", "name": "한국경제", "language": "ko", "limit": 15,
        "feeds": {
            "politics": "https://www.hankyung.com/feed/politics",
            "economy":  "https://www.hankyung.com/feed/economy",
            "it":       "https://www.hankyung.com/feed/it",
        },
    },
    {
        "id": "wsj", "name": "WSJ Markets", "language": "en", "limit": 10,
        "feeds": {
            # 해외 증시/경제 전문 — NYT와 동일하게 원문은 페이월이지만 제목/요약은 RSS로 무료 제공
            "economy": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        },
    },
    {
        "id": "yna", "name": "연합뉴스", "language": "ko", "limit": 15,
        "feeds": {
            "politics": "https://www.yna.co.kr/rss/politics.xml",
            "economy":  "https://www.yna.co.kr/rss/economy.xml",
            "society":  "https://www.yna.co.kr/rss/society.xml",
            "world":    "https://www.yna.co.kr/rss/international.xml",
            "culture":  "https://www.yna.co.kr/rss/culture.xml",
            "life":     "https://www.yna.co.kr/rss/health.xml",
        },
    },
    {
        "id": "khan", "name": "경향신문", "language": "ko", "limit": 15,
        "feeds": {
            "politics": "https://www.khan.co.kr/rss/rssdata/politic_news.xml",
            "economy":  "https://www.khan.co.kr/rss/rssdata/economy_news.xml",
            "society":  "https://www.khan.co.kr/rss/rssdata/society_news.xml",
            "culture":  "https://www.khan.co.kr/rss/rssdata/culture_news.xml",
            "it":       "https://www.khan.co.kr/rss/rssdata/it_news.xml",
            "science":  "https://www.khan.co.kr/rss/rssdata/kh_science.xml",
            "life":     "https://www.khan.co.kr/rss/rssdata/life_news.xml",
        },
    },
    {
        "id": "donga", "name": "동아일보", "language": "ko", "limit": 15,
        "feeds": {
            "politics": "https://rss.donga.com/politics.xml",
            "economy":  "https://rss.donga.com/economy.xml",
            "society":  "https://rss.donga.com/national.xml",
            "world":    "https://rss.donga.com/international.xml",
            "culture":  "https://rss.donga.com/culture.xml",
            "it":       "https://rss.donga.com/science.xml",  # 실제로는 "IT/의학" 혼합 피드
            "life":     "https://rss.donga.com/lifeinfo.xml",
        },
    },
]
