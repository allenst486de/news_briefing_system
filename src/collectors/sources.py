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
2026-08 3차: 피드가 살아 있어도 '갱신을 멈춘' 경우가 있다 — CNN world(기사 중앙값
1225일), WSJ(564일), 경향 과학(513일, 8건)이 그랬다. 등재 전에 항목 수만 보지 말고
발행일까지 확인할 것. 셋은 요청에 따라 목록에 유지하되, 오래된 기사는
news_aggregator의 MAX_ARTICLE_AGE_DAYS 필터가 일괄로 막는다.
새로 추가하려면 test_feeds.py로 먼저 검증할 것.

2026-09 전문지 보강: 과학·생활의 국내 소스가 종합일간지뿐이라 전문지를 찾아 28개
후보를 검증했고 4곳(헬로디디·AI타임스·청년의사·바이라인네트워크)만 통과했다.
다시 시도하지 않도록 탈락 사유를 남긴다.
  - RSS 자체가 없음(모든 경로 404 또는 HTML 반환): 동아사이언스(과학동아 발행처),
    사이언스타임즈, 씨네21, 조선비즈, 이코노미스트, 디지털데일리, 메디칼타임즈,
    헬스조선, 텐아시아, 비즈워치. 한국 매체는 RSS를 걷어낸 곳이 많다.
  - 갱신 중단: IT조선 S1N1(기사 중앙값 1058일 — 2023년 국감 기사가 최신),
    시사IN(821일).
  - 피드 내용이 분야와 불일치: IT조선(allArticle·S1N2 모두 '농심 3세 결혼' 같은
    재계 가십이 섞인 종합 피드), 한국경제 life 피드(내용이 연예·문화).
    전자신문 Section901 사고와 같은 유형이라 등재하지 않는다.
  - 발행일 파싱 불가: 한겨레21(항목 30건, 날짜 0건).
  - 전문성 기준 미달: 코메디닷컴(연성 건강 기사·클릭베이트성 제목),
    법률신문(부고가 피드에 섞이고 날짜 중앙값이 -1일로 미래 날짜).

2026-09 2차(구글 뉴스 경유): RSS 미제공 매체를 google_site_feed()로 다시 검토해
5곳(동아사이언스·씨네21·농민신문·디지털데일리·비즈워치)을 추가했다. 탈락 사유:
  - 피드에 기사가 아닌 페이지가 섞임: 사이언스타임즈('통합검색'), 하이닥('건강Q&A',
    '의사·병원찾기'), 아트인사이트('테스트1'), 한국문화예술위(공연소개·공지사항).
  - 제목이 비거나 깨짐: 메디칼타임즈(전부 '- Medicaltimes'),
    헬스조선(제목이 영어로 나옴 — 구글이 번역본을 물어온다).
  - 분야 불일치: 조선비즈(연예 가십 혼입), 여성신문(내용이 정치·사회).
  - 전문성 기준 미달: 텐아시아·맥스무비(연예 가십·인터뷰 위주).
  - 검색 결과 0건: 월간미술, 월간객석.
"""

import urllib.parse


def google_site_feed(domain: str, days: int = 3) -> str:
    """
    RSS를 제공하지 않는 매체를 구글 뉴스 검색 RSS로 우회 수집한다.

    한국 매체는 RSS를 걷어낸 곳이 많아(동아사이언스·씨네21·조선비즈 등) 자체 피드로는
    등재할 수 없다. 구글 뉴스의 `site:` 검색 결과를 RSS로 받으면 그 매체 기사만
    골라 올 수 있다.

    ⚠️ 대가가 있다. 링크가 구글 리다이렉트(news.google.com/rss/articles/...)라
    article_body가 본문을 못 가져온다 — 서버 리다이렉트가 아니라 JS로 넘기는
    페이지여서 그렇고, URL 디코딩도 막혀 있다(2026-09 확인). 그래서 이 소스들의
    요약은 RSS 요약문만 근거로 쓰며, 근거가 얇으면 요약이 짧아진다(환각 방지 규칙이
    분량을 채우지 못하게 막는다). 자체 RSS가 있는 매체는 반드시 그쪽을 쓸 것.

    when:Nd로 기간을 제한해 오래된 기사가 딸려오지 않게 한다.
    """
    query = urllib.parse.quote_plus(f"site:{domain} when:{days}d")
    return f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"


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
        "via": "googlenews",
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
        # 아래 셋은 한때 오래된 기사만 내보내 제거했다가 요청에 따라 되살렸다.
        # 3일 초과 기사는 news_aggregator가 일괄로 걸러내므로, 피드가 다시 멈춰도
        # 옛날 기사가 지면에 오르지는 않는다(그동안 0건으로 보일 뿐이다).
        "id": "wsj", "name": "WSJ Markets", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"economy": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    },
    {
        "id": "cnn", "name": "CNN", "language": "en", "region": "overseas", "limit": 10,
        "feeds": {"world": "http://rss.cnn.com/rss/edition_world.rss"},
    },
    {
        "id": "khan_sci", "name": "경향신문", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"science": "https://www.khan.co.kr/rss/rssdata/kh_science.xml"},
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
        # Section901은 이름과 달리 "오늘의뉴스"(종합)라 IT 페이지에 사형 집행·환전소
        # 기사까지 올라왔다. 실제 섹션 피드로 교체 — 04=AI·SW, 20=과학.
        "id": "etnews", "name": "전자신문", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"it": "https://rss.etnews.com/04.xml"},
    },
    {
        "id": "etnews_sci", "name": "전자신문", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"science": "https://rss.etnews.com/20.xml"},
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

    # ── 분야별 전문지 (2026-09 추가) ─────────────────────────────────────
    # 종합일간지보다 소식이 빠르고 깊다. 특히 과학·생활은 그전까지 국내 소스가
    # 종합일간지뿐이었다. 아래는 전부 등재 전에 항목 수·발행일 중앙값·제목 표본까지
    # 확인했다(검증 기준은 이 파일 상단 참고).
    {
        # 대덕연구단지 기반 과학기술 전문지. 표본: KAIST-롯데 R&D센터, 대만 양자산업,
        # 생체 뇌영상 기술 — 종합지가 다루지 않는 연구 현장 소식이 주력이다.
        "id": "hellodd", "name": "헬로디디", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"science": "https://www.hellodd.com/rss/allArticle.xml"},
    },
    {
        # AI 전문지. 표본 50건이 전부 AI/모델/인프라 소식으로 IT 분야 적중률이 높다.
        # IT 페이지의 AI 서브섹션(importance_analyzer가 분류)과 특히 잘 맞는다.
        "id": "aitimes", "name": "AI타임스", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"it": "https://www.aitimes.com/rss/allArticle.xml"},
    },
    {
        # 의료계 전문지. 표본: 폐암 국제학회(WCLC), 중소병원 외과, 전자약 개발 —
        # 건강 정보성 기사가 아니라 의료 현장·연구 소식이라 전문성이 확보된다.
        "id": "docdocdoc", "name": "청년의사", "language": "ko", "region": "domestic", "limit": 15,
        "feeds": {"life": "https://www.docdocdoc.co.kr/rss/allArticle.xml"},
    },
    {
        # 테크 전문 매체. 다만 기사 발행일 중앙값이 3일로 MAX_ARTICLE_AGE_DAYS 경계에
        # 걸쳐 있어 실제로 지면에 오르는 건 절반 남짓이고, 유통·커머스 기사도 일부
        # 섞인다(분야 무관 건은 요약 단계의 off_topic 필터가 걸러낸다).
        # 수확량이 적은 대신 다른 매체가 안 다루는 각도를 가져오는 자리다.
        "id": "byline", "name": "바이라인네트워크", "language": "ko", "region": "domestic", "limit": 10,
        "feeds": {"it": "https://byline.network/feed/"},
    },

    # ── 구글 뉴스 경유 전문지 (2026-09 추가) ─────────────────────────────
    # RSS를 제공하지 않아 자체 피드로는 못 넣는 매체들. google_site_feed()의
    # 주의사항(본문 추출 불가 → 요약이 RSS 요약문에만 의존)을 반드시 읽을 것.
    # 자체 RSS가 생기면 그쪽으로 갈아타는 편이 낫다.
    {
        # 과학동아·수학동아 발행처. 자체 RSS가 없어졌다(홈페이지에 링크조차 없음).
        # 표본: 접착제 없이 붙는 플라스틱, 우주항공청 캔위성, 휴머노이드 — 연구 소식이 주력.
        "id": "dongascience", "name": "동아사이언스", "language": "ko", "region": "domestic",
        "limit": 12, "via": "googlenews",
        "feeds": {"science": google_site_feed("dongascience.com")},
    },
    {
        # 영화 전문지. 문화 분야는 그전까지 국내 전문지가 하나도 없었다.
        # 표본: 베니스영화제 중간 점검, 편집장 오프닝, OTT리뷰.
        "id": "cine21", "name": "씨네21", "language": "ko", "region": "domestic",
        "limit": 12, "via": "googlenews",
        "feeds": {"culture": google_site_feed("cine21.com")},
    },
    {
        # 농업 전문지. 생활 분야를 종합일간지 바깥에서 채운다.
        # 표본: 농지 전수조사, 직불금 교육 감액, 수입콩 GMO 표시.
        "id": "nongmin", "name": "농민신문", "language": "ko", "region": "domestic",
        "limit": 12, "via": "googlenews",
        "feeds": {"life": google_site_feed("nongmin.com")},
    },
    {
        # IT 전문지. 표본: ISDS 소송, 현대차 자율주행 전략, LCK — 일부 e스포츠가 섞인다.
        "id": "ddaily", "name": "디지털데일리", "language": "ko", "region": "domestic",
        "limit": 12, "via": "googlenews",
        "feeds": {"it": google_site_feed("ddaily.co.kr")},
    },
    {
        # 경제·금융 전문지. 표본: 금양 물적분할, 빗썸 FIU 재판, OTT 해킹 보상.
        "id": "bizwatch", "name": "비즈워치", "language": "ko", "region": "domestic",
        "limit": 12, "via": "googlenews",
        "feeds": {"economy": google_site_feed("bizwatch.co.kr")},
    },
]
