"""
News Source Registry
언론사 RSS 피드 설정 — 신규 언론사 추가는 클래스 작성 없이 이 목록에 항목만 추가하면 됨.

각 소스의 feeds 딕셔너리 키가 곧 최종 카테고리 키(CATEGORIES)이고,
region은 "domestic"(국내) / "overseas"(해외) — 카테고리 페이지의 국내/해외 탭과
매체별 수집 상한이 이 값을 기준으로 나뉜다.

URL은 등재 전에 실제로 받아 항목 수와 날짜 파싱 여부까지 확인한 것만 넣는다.
2026-08 재검증에서 죽어 있던 후보는 제외했다: 헤럴드경제(4개 주소 모두 항목 0),
매일경제(403), 서울경제/한국일보/파이낸셜뉴스(404), 중앙일보/KBS/MBC(항목 0),
Reuters(404), AP(403), 블로터(403), 이데일리(연결 실패).
새로 추가하려면 test_feeds.py로 먼저 검증할 것.
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

REGIONS = ["domestic", "overseas"]
REGION_META = {
    "domestic": {"name": "국내", "icon": "🇰🇷"},
    "overseas": {"name": "해외", "icon": "🌐"},
}

SOURCES = [
    {
        "id": "yonhap", "name": "연합뉴스TV", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {
            "politics": "https://www.yonhapnewstv.co.kr/category/news/politics/feed/",
            "economy":  "https://www.yonhapnewstv.co.kr/category/news/economy/feed/",
            "society":  "https://www.yonhapnewstv.co.kr/category/news/society/feed/",
            "world":    "https://www.yonhapnewstv.co.kr/category/news/international/feed/",
        },
    },
    {
        "id": "googlenews", "name": "구글 뉴스", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {
            "politics": "https://news.google.com/rss/topics/CAAqIQgKIhtDQkFTRGdvSUwyMHZNRFZ4ZERBU0FtdHZLQUFQAQ?hl=ko&gl=KR&ceid=KR:ko",
            "economy":  "https://news.google.com/rss/topics/CAAqIggKIhxDQkFTRHdvSkwyMHZNR2RtY0hNekVnSnJieWdBUAE?hl=ko&gl=KR&ceid=KR:ko",
            # society 토픽 ID는 test_feeds.py 확인 결과 죽어있어 제외 (yonhap/guardian/hani가 society 커버)
            "world":    "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGx1YlY4U0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
            "it":       "https://news.google.com/rss/topics/CAAqJggKIiBDQkFTRWdvSUwyMHZNRGRqTVhZU0FtdHZHZ0pMVWlnQVAB?hl=ko&gl=KR&ceid=KR:ko",
        },
    },
    {
        "id": "bbc", "name": "BBC News", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {
            "world":    "http://feeds.bbci.co.uk/news/world/rss.xml",
            "economy":  "http://feeds.bbci.co.uk/news/business/rss.xml",
            "politics": "http://feeds.bbci.co.uk/news/politics/rss.xml",
            "it":       "http://feeds.bbci.co.uk/news/technology/rss.xml",
            "science":  "http://feeds.bbci.co.uk/news/science_and_environment/rss.xml",
        },
    },
    {
        "id": "nyt", "name": "New York Times", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {
            "world":    "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "economy":  "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
            "politics": "https://rss.nytimes.com/services/xml/rss/nyt/Politics.xml",
            "it":       "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
            "science":  "https://rss.nytimes.com/services/xml/rss/nyt/Science.xml",
        },
    },
    {
        "id": "guardian", "name": "The Guardian", "language": "en", "region": "overseas", "limit": 10,
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
        "id": "aljazeera", "name": "Al Jazeera", "language": "en", "region": "overseas", "limit": 15,
        "feeds": {
            # 통합 피드 하나뿐이라 world에만 매핑
            "world": "https://www.aljazeera.com/xml/rss/all.xml",
        },
    },
    {
        "id": "hani", "name": "한겨레", "language": "ko", "region": "domestic", "limit": 15,
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
        "id": "hankyung", "name": "한국경제", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {
            "politics": "https://www.hankyung.com/feed/politics",
            "economy":  "https://www.hankyung.com/feed/economy",
            "it":       "https://www.hankyung.com/feed/it",
        },
    },
    {
        "id": "wsj", "name": "WSJ Markets", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {
            # 해외 증시/경제 전문 — NYT와 동일하게 원문은 페이월이지만 제목/요약은 RSS로 무료 제공
            "economy": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
        },
    },
    {
        "id": "yna", "name": "연합뉴스", "language": "ko", "region": "domestic", "limit": 15,
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
        "id": "khan", "name": "경향신문", "language": "ko", "region": "domestic", "limit": 15,
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
        "id": "donga", "name": "동아일보", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {
            "politics": "https://rss.donga.com/politics.xml",
            "economy":  "https://rss.donga.com/economy.xml",
            "society":  "https://rss.donga.com/national.xml",
            "world":    "https://rss.donga.com/international.xml",
            "culture":  "https://rss.donga.com/culture.xml",
            # science.xml은 IT가 아니라 과학/의학 피드다 — it으로 매핑돼 있어서
            # IT 페이지에 폐암·전립선·장건강 기사가 올라왔다(27건 중 6건). science로 옮김.
            "science":  "https://rss.donga.com/science.xml",
            "life":     "https://rss.donga.com/lifeinfo.xml",
        },
    },
    {
        # 한 소스의 feeds는 카테고리당 URL 하나뿐이라, 동아 건강 피드는 별도 항목으로
        # 분리한다(표시명은 동일하므로 화면·중복제거상으로는 같은 매체로 취급된다).
        "id": "donga_health", "name": "동아일보", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"life": "https://rss.donga.com/health.xml"},
    },
    {
        "id": "asiae", "name": "아시아경제", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"economy": "https://www.asiae.co.kr/rss/stock.htm"},
    },
    {
        "id": "einfomax", "name": "연합인포맥스", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"economy": "https://news.einfomax.co.kr/rss/allArticle.xml"},
    },
    {
        "id": "etnews", "name": "전자신문", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"it": "https://rss.etnews.com/Section901.xml"},
    },
    {
        "id": "zdnetkr", "name": "ZDNet Korea", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"it": "https://feeds.feedburner.com/zdkorea"},
    },
    {
        "id": "nocut", "name": "노컷뉴스", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"society": "https://rss.nocutnews.co.kr/nocutnews.xml"},
    },
    {
        "id": "sbs", "name": "SBS 뉴스", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"society": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=03"},
    },
    {
        "id": "ohmynews", "name": "오마이뉴스", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"society": "http://rss.ohmynews.com/rss/ohmynews.xml"},
    },
    {
        "id": "pressian", "name": "프레시안", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"society": "https://www.pressian.com/api/v3/site/rss/news"},
    },
    {
        "id": "cnn", "name": "CNN", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"world": "http://rss.cnn.com/rss/edition_world.rss"},
    },
    {
        "id": "ft", "name": "Financial Times", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"economy": "https://www.ft.com/rss/home"},
    },
    {
        "id": "nature", "name": "Nature", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"science": "https://www.nature.com/nature.rss"},
    },
    {
        "id": "sciencedaily", "name": "ScienceDaily", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"science": "https://www.sciencedaily.com/rss/all.xml"},
    },
    {
        "id": "wired", "name": "WIRED", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"it": "https://www.wired.com/feed/rss"},
    },
    {
        "id": "techcrunch", "name": "TechCrunch", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"it": "https://techcrunch.com/feed/"},
    },
    {
        "id": "arstechnica", "name": "Ars Technica", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"it": "https://feeds.arstechnica.com/arstechnica/index"},
    },
]
