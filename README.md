# 📰 일일 뉴스 브리핑 시스템

매일 오전 6시(KST)에 국내외 12개 언론사에서 8개 분야 뉴스를 수집해 LLM으로 번역·재구성·요약하고, 포털 스타일 웹사이트와 텔레그램으로 전달하는 완전 자동화 시스템입니다.

## 📋 주요 기능

- **8개 분야 자동 수집**: 🏛️ 정치 · 💰 경제 · 👥 사회 · 🌱 생활 · 🎭 문화 · 💻 IT · 🔬 과학 · 🌍 국제
- **12개 언론사, 57개 RSS 피드**: 연합뉴스, 경향신문, 한겨레, 동아일보, 한국경제, 연합뉴스TV, 구글 뉴스(국내) + BBC, NYT, The Guardian, Al Jazeera, WSJ(해외) — 전체 목록은 `src/collectors/sources.py` 참고
- **LLM 기반 번역·재구성·요약**: NVIDIA NIM(무료 티어)으로 기사 8건씩 끊어 배치 호출 — 원문을 그대로 베끼지 않고 자기 표현으로 재구성, 해외 기사는 번역과 동시에 자연스럽게 다듬음, 확인되지 않은 수치·전망은 지어내지 않음. **API 키가 없거나 호출이 실패해도 규칙기반 요약으로 자동 폴백**해 서비스가 멈추지 않음
- **원문 본문 기반 요약**: RSS 요약문이 짧거나 `…`로 잘린 기사는 원문 링크에서 본문을 가져와 요약 근거로 쓴다(실측 12개 매체 중 8곳 성공, 나머지는 봇 차단·JS 리다이렉트라 RSS 요약문으로 폴백). 요약 길이 250자는 **상한**이며, 근거가 부족하면 늘려 쓰지 않고 짧게 끝낸다 — 분량을 맞추려 지어내는 것이 환각 금지 규칙과 충돌하기 때문
- **IT 내 AI 소식 서브섹션**: 신규 모델 출시·가격 정책 변경·산업 동향을 일반 IT 뉴스와 분리 표시
- **크로스카테고리 Top10**: 8개 분야를 통틀어 가장 중요한 10건을 선정해 홈 화면 카드뉴스로 표시하고, 텔레그램에는 2열×5행 포스터형 인포그래픽 PNG 한 장과 텍스트 목록을 **함께** 전송(이미지 생성이 실패해도 텍스트는 항상 나감)
- **경제 대시보드**: **주요 지표**(코스피·코스닥·나스닥·다우존스·S&P500·니케이225)와 **환율**(달러·유로·엔·위안) 2개 탭 — 10개 항목 모두 최근 7거래일 추이를 인라인 SVG 스파크라인으로 표시(차트 라이브러리 없이 서버에서 직접 그림). 일간/주간/월간 주식 추천도 같은 방식의 탭 박스(추천 종목 선정은 100% 결정론적 로직, LLM은 근거 문장만 작성 — 투자자문 아님 고지 포함)
- **장중 15분 지표 갱신**: 지표만 갱신하는 별도 워크플로가 평일 장중 15분마다 `docs/indicators.json`을 덮어쓰고, 페이지의 JS가 같은 도메인에서 그 파일을 읽어 숫자·등락률을 바꿔치기한다. 박스 하단에 기준 시각을 표시한다
- **중요도순 정렬**: 모든 페이지·텔레그램 메시지가 (중요도, 최신순)으로 정렬
- **포털형 홈 화면**: 실시간 시계, 방문자 위치 기반 날씨, 8개 분야 미리보기, 라이트/다크 테마 전환
- **텔레그램 알림**: 하루에 **2건만** 전송 — Top10 인포그래픽 이미지 1장 + "일일 뉴스 브리핑" 메시지 1개. 분야별 상세는 메시지로 보내지 않고 브리핑 메시지의 분야별 링크를 눌러 웹에서 본다(기사별 250자 요약은 그 페이지에 있음). 모든 링크는 `원문 보기` 같은 마스킹 텍스트로 표시하고 출처 언론사명을 따로 적음(URL 노출 없음 — 텔레그램이 링크 확인 팝업을 띄우는 건 마스킹 링크의 알려진 트레이드오프)
- **3개월 자동 아카이브 압축**: 원본 페이지는 최근 90일만 보관하고, 그 이전은 월 단위 요약 JSON(`archive/`)으로 압축 후 원본 삭제 — 저장소 용량이 무한정 커지지 않음
- **비공개 노출 정책**: `robots.txt`로 검색엔진 색인을 차단(링크를 아는 사람만 접근 가능한 조용한 사이트)
- **GitHub Pages 호스팅**: 무료로 웹 페이지 호스팅

## 🚀 설치 및 설정

### 1. 저장소 클론

```bash
git clone https://github.com/allenst486de/news_briefing_system.git
cd news_briefing_system
```

### 2. Python 패키지 설치

```bash
pip install -r requirements.txt
```

### 3. 환경 변수 설정

`.env` 파일을 생성하고 다음 내용을 입력하세요:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
PAGES_BASE_URL=https://yourusername.github.io/news_briefing_system
NVIDIA_API_KEY=your_nvidia_api_key_here
```

**텔레그램 봇 토큰 받기:**
1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 검색
2. `/newbot` 명령어로 새 봇 생성
3. 받은 토큰을 `TELEGRAM_BOT_TOKEN`에 입력

**채팅 ID 확인:**
1. 봇에게 메시지 전송
2. `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` 접속
3. `chat.id` 값을 `TELEGRAM_CHAT_ID`에 입력

**NVIDIA API 키 받기 (선택, 없어도 동작함):**
1. [build.nvidia.com](https://build.nvidia.com)에서 무료 계정 생성 후 API 키 발급
2. `NVIDIA_API_KEY`에 입력
3. 비워두면 번역/250자 재구성 요약/Top10 선정이 규칙기반(원문 그대로, 최신순 정렬)으로 대체되어 동작합니다 — 서비스가 멈추지 않습니다

### 4. GitHub Secrets 설정

GitHub 저장소 Settings > Secrets and variables > Actions에서 다음 Secrets 추가:

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 텔레그램 채팅 ID
- `PAGES_BASE_URL`: GitHub Pages URL (예: `https://yourusername.github.io/news_briefing_system`)
- `NVIDIA_API_KEY`: NVIDIA NIM API 키 (선택)
  - ⚠️ 주의: `GITHUB_`로 시작하는 이름은 사용할 수 없습니다

### 5. GitHub Pages 활성화

1. GitHub 저장소 Settings > Pages
2. Source: Deploy from a branch
3. Branch: `gh-pages` / `/ (root)`
4. Save

## 💻 사용 방법

### 로컬에서 실행

```bash
python main.py
```

실행 후 `docs/`에 8개 분야 HTML + 포털 홈(`index.html`)이, `data/raw/`에 압축용 원본 스냅샷이 생성됩니다.

### 자동 실행 (GitHub Actions)

- 매일 오전 6시(KST)에 자동으로 실행됩니다.
- 수동 실행: GitHub Actions 탭 > Daily News Briefing > Run workflow
- 워크플로는 실행이 끝나면 생성물(`docs/`·`data/`·`archive/`)을 `main`에 직접 커밋합니다. 브리핑 생성에 수 분~수십 분이 걸려 그 사이 다른 push가 들어오면 커밋 단계가 non-fast-forward로 거절되므로, push 실패 시 `git pull --rebase` 후 최대 3회 재시도합니다.

### 자체 점검 스크립트

프레임워크 없이 `assert` 기반으로 작성된 수동 점검 스크립트들입니다. 코드를 크게 건드릴 때 실행하세요.

```bash
python test_escaping.py    # XSS 이스케이프 회귀 검증
python test_feeds.py       # sources.py의 모든 RSS 피드 생존 확인
python test_llm_client.py  # LLM JSON 파싱/복구/폴백 로직 검증 (실제 API 호출 없음)
python test_archiver.py    # 3개월 롤오버/압축/멱등성 검증
python test_salvage.py     # 잘린 JSON 복구 + 청크 분할 + 본문 추출 판별 검증
```

### LLM이 실제로 동작했는지 확인하는 법

LLM은 실패해도 규칙기반으로 조용히 폴백하기 때문에 "번역이 안 된다"를 며칠씩 모르고 지나가기 쉽다. 실행할 때마다 GitHub Actions 실행 요약 화면 맨 아래에 아래처럼 집계가 찍힌다.

```
### LLM 요약·번역 상태
✅ LLM 정상 동작
호출 35건 · 성공 35 · 부분복구 0 · JSON실패 0 · HTTP오류 0 · 네트워크오류 0 · 키없음 0
```

`❌ LLM 전부 실패`가 뜨면 같은 줄의 분류로 원인을 바로 알 수 있다 — `키없음`이면 Secret 미설정, `HTTP오류`면 키 만료나 모델명 변경(첫 오류 메시지에 응답 본문이 같이 찍힌다), `JSON실패`면 응답 형식 문제다.

## 📁 프로젝트 구조

```
news_briefing_system/
├── .github/workflows/
│   ├── daily_briefing.yml        # 매일 06시 KST 실행 + docs/data/archive 커밋(rebase 재시도) + Pages 배포
│   └── indicators.yml            # 평일 장중 15분마다 docs/indicators.json만 갱신
├── src/
│   ├── collectors/
│   │   ├── base_collector.py     # NewsArticle, 수집기 공통 인터페이스 (위험 링크 스킴 차단)
│   │   ├── rss_collector.py      # 설정 기반 범용 RSS 수집기 (모든 언론사 공용)
│   │   └── sources.py            # 언론사·카테고리·피드 URL 목록 (신규 언론사 = 여기 항목 추가)
│   ├── templates/
│   │   ├── briefing.html         # 분야별 페이지
│   │   ├── index.html            # 포털형 홈
│   │   ├── archive.html          # 아카이브 목록
│   │   ├── _home_header.html     # 홈 헤더(시계/날씨/지표)
│   │   ├── _indicator_box.html   # 국내/해외 지수 탭 박스 (홈+경제 페이지 공용)
│   │   ├── _economy_dashboard.html  # 경제 지표 + 주식 추천 탭 박스
│   │   ├── _top10_cards.html     # Top10 카드뉴스
│   │   ├── _ai_subsection.html   # IT 내 AI 소식
│   │   ├── style.css
│   │   └── static/
│   │       ├── site.js           # 시계/날씨/테마토글/탭전환
│   │       └── fonts/            # 카드뉴스 이미지용 나눔고딕(SIL OFL)
│   ├── utils/
│   │   ├── logger.py
│   │   ├── importance_analyzer.py  # 중요도 키워드 폴백 + AI 관련 키워드 폴백
│   │   ├── rss_utils.py          # RSS 공통 유틸(HTML 정리, 구글뉴스 래퍼/제목접미사 제거)
│   │   ├── dedup.py              # 제목 정규화(당일 중복 제거 + 월간 압축 중복 제거 공용)
│   │   ├── llm_client.py         # NVIDIA NIM REST 클라이언트 (재시도+잘린 JSON 복구+실패 집계)
│   │   ├── article_body.py       # 원문 본문 추출 (요약 근거 보강, 실패 시 RSS 요약문 폴백)
│   │   ├── indicators.py         # 주요 지표/환율 + 7일 추이 스파크라인 SVG
│   │   ├── stock_data.py         # 주식 추천 결정론적 스크리닝 (Naver Finance + yfinance)
│   │   └── cardnews.py           # Top10 포스터형 카드뉴스 PNG 생성 (Pillow)
│   ├── news_aggregator.py        # 수집 → 중복/공지성 기사 제거 → 요약 → 정렬
│   ├── summarizer.py             # LLM 배치 요약/AI추출/Top10선정/주식근거 생성 + 폴백
│   ├── html_generator.py         # HTML·RSS피드·robots.txt·원본 스냅샷 생성
│   ├── archiver.py               # 90일 지난 자료 월단위 압축 + 원본 삭제
│   └── telegram_bot.py           # 텔레그램 전송 (이미지 1 + 브리핑 메시지 1)
├── docs/                         # 생성된 HTML (GitHub Pages, 최근 90일)
├── update_indicators.py          # 지표만 갱신 (indicators.yml 워크플로가 실행)
├── data/raw/                     # 일일 원본 JSON 스냅샷 (docs 밖, 비공개)
├── archive/                      # 90일 지난 자료의 월별 압축 요약 (docs 밖, 비공개)
├── test_*.py                     # 자체 점검 스크립트
├── main.py
├── requirements.txt
├── .env.example
└── README.md
```

## 🎨 기능 상세

### 뉴스 수집 → 요약 파이프라인

1. `sources.py`에 등록된 12개 언론사에서 8개 분야 RSS를 병렬로 수집
2. 정기 행정 공지(예: "N월N일 인사/부고/동정/알림")와 카테고리 내 중복 기사 제거
3. RSS 요약문이 짧거나 잘린 기사는 원문 본문을 병렬로 가져옴(시간 예산 240초, 실패 시 RSS 요약문 유지)
4. 카테고리당 최대 30건을 **8건씩 끊어** LLM 호출로 번역+재구성+요약 (덩어리 단위로 실패 격리 — 한 덩어리가 죽어도 나머지는 살아남음)
5. IT 카테고리에서 AI 관련 기사만 따로 추출
6. (중요도, 최신순)으로 정렬 후 HTML/텔레그램에 전달

> 8건씩 끊는 이유: 30건을 한 번에 요청하면 한국어 출력이 `max_tokens`를 넘겨 JSON 배열이 닫히기 전에 잘리고, 그러면 카테고리 전체가 규칙기반으로 폴백된다. 그래도 잘리는 경우에 대비해 `llm_client._salvage_array()`가 완성된 객체만 건져낸다.

### LLM 환각 방지 규칙

모든 요약 프롬프트에 공통으로 적용되는 규칙(`summarizer.py`):
- 제공된 원문에 없는 수치·실적·가격·출시일·미래 예측 금지
- 사전 학습 지식이 아닌 오늘 수집된 데이터로만 판단
- 원문을 그대로 베끼지 않고 자기 표현으로 재구성 (직역 금지)
- 번역이 모호한 표현은 원어를 괄호로 병기
- 홍보성 문구·근거 없는 벤치마크·유료 강의성 내용 제외
- 요약 길이(250자)는 상한이며, 근거가 부족하면 분량을 채우지 말고 짧게 끝낼 것
- (예외) 주식 추천 근거 문장만 전망성 서술 허용 — 단 실제 가격/거래량 데이터에 근거해야 하며 투자자문 아님을 명시

### 웹 페이지 디자인

- 다크/라이트 테마 전환 (버튼 클릭, localStorage 저장)
- 주요 지표/환율, 일/주/월 주식 추천을 탭으로 전환하는 공용 박스 UI
- 반응형 디자인 (모바일, 태블릿, 데스크톱)
- 기사마다 출처 언론사 표기, 원문 링크 연결
- OG 메타태그(공유 시 미리보기), 자체 RSS 피드(`feed.xml`, 비공개)

## 🔧 커스터마이징

### 뉴스 소스 추가/변경

`src/collectors/sources.py`의 `SOURCES` 목록에 언론사 항목을 추가하면 됩니다 — 새 클래스를 작성할 필요 없이 RSS URL만 등록하면 `RSSCollector`가 공통으로 처리합니다. 추가 후에는 `python test_feeds.py`로 살아있는 피드인지 확인하세요.

### 카테고리 수정

`src/collectors/sources.py`의 `CATEGORIES`/`CATEGORY_META`를 수정하세요 (아이콘·표시명 포함).

### 아카이브 보관 기간 변경

`main.py`에서 `archiver.rollover_old_archives(...)` 호출 시 `retention_days` 인자를 조정하세요 (기본 90일).

### 스케줄 변경

`.github/workflows/daily_briefing.yml`(일일 브리핑)과 `.github/workflows/indicators.yml`(장중 지표 갱신)의 cron 표현식을 수정하세요.

### 지표 항목 추가/변경

`src/utils/indicators.py`의 `_DOMESTIC_INDEX_CODES` / `_OVERSEAS_TICKERS` / `_FX_CODES`에 항목을 추가하면 됩니다. 각 항목의 `key`는 `site.js`가 장중 갱신 때 DOM을 찾는 데 쓰이므로, 이미 있는 항목의 key는 바꾸지 마세요.

## 📝 라이선스

MIT License

번들된 나눔고딕 폰트(`src/templates/static/fonts/`)는 SIL Open Font License 1.1을 따릅니다.

## 🤝 기여

이슈 및 풀 리퀘스트를 환영합니다!

## 📧 문의

문제가 발생하면 GitHub Issues를 통해 문의해주세요.
