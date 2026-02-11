# 📰 일일 뉴스 브리핑 시스템

매일 오전 6시에 자동으로 국내외 주요 뉴스를 수집하여 카테고리별로 정리한 웹 페이지를 생성하고, 텔레그램으로 링크를 전송하는 자동화 시스템입니다.

## 📋 주요 기능

- **자동 뉴스 수집**: BBC, New York Times, 네이버 뉴스, 다음 뉴스에서 RSS 피드를 통해 뉴스 수집
- **자동 번역**: 해외 뉴스(BBC, NYT)를 한국어로 자동 번역하여 제공 (원문 보기 기능 포함)
- **카테고리별 분류**: 
  - 🇰🇷 국내 종합 뉴스
  - 💰 국내 경제 뉴스
  - 🏛️ 국내 정치/시사 뉴스
  - 🌍 세계 종합 뉴스
  - 🌐 세계 경제/정치/시사 뉴스
- **중요 뉴스 강조**: 키워드 기반으로 중요한 뉴스를 자동 감지하여 강조 표시
- **웹 페이지 생성**: 깔끔하고 읽기 쉬운 HTML 페이지 (다크모드 지원, 인쇄 최적화)
- **아카이브 기능**: 과거 브리핑을 블로그 형식으로 보관 및 열람
- **텔레그램 알림**: 매일 오전 6시에 브리핑 링크를 텔레그램으로 전송
- **GitHub Pages 호스팅**: 무료로 웹 페이지 호스팅

## 🚀 설치 및 설정

### 1. 저장소 클론

```bash
git clone https://github.com/yourusername/news_briefing_system.git
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
```

**텔레그램 봇 토큰 받기:**
1. 텔레그램에서 [@BotFather](https://t.me/BotFather) 검색
2. `/newbot` 명령어로 새 봇 생성
3. 받은 토큰을 `TELEGRAM_BOT_TOKEN`에 입력

**채팅 ID 확인:**
1. 봇에게 메시지 전송
2. `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` 접속
3. `chat.id` 값을 `TELEGRAM_CHAT_ID`에 입력

### 4. GitHub Secrets 설정

GitHub 저장소 Settings > Secrets and variables > Actions에서 다음 Secrets 추가:

- `TELEGRAM_BOT_TOKEN`: 텔레그램 봇 토큰
- `TELEGRAM_CHAT_ID`: 텔레그램 채팅 ID
- `PAGES_BASE_URL`: GitHub Pages URL (예: `https://yourusername.github.io/news_briefing_system`)
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

실행 후 `docs/` 디렉토리에 HTML 파일이 생성됩니다.

### 자동 실행 (GitHub Actions)

- 매일 오전 6시 (KST)에 자동으로 실행됩니다.
- 수동 실행: GitHub Actions 탭 > Daily News Briefing > Run workflow

## 📁 프로젝트 구조

```
news_briefing_system/
├── .github/
│   └── workflows/
│       └── daily_briefing.yml    # GitHub Actions 워크플로우
├── src/
│   ├── collectors/               # 뉴스 수집기
│   │   ├── base_collector.py
│   │   ├── bbc_collector.py
│   │   ├── nyt_collector.py
│   │   ├── naver_collector.py
│   │   └── daum_collector.py
│   ├── templates/                # HTML 템플릿
│   │   ├── briefing.html
│   │   ├── archive.html
│   │   ├── index.html
│   │   └── style.css
│   ├── utils/                    # 유틸리티
│   │   ├── logger.py
│   │   ├── importance_analyzer.py
│   │   ├── translator.py         # 번역 유틸리티
│   │   └── rss_utils.py          # RSS 피드 유틸리티
│   ├── news_aggregator.py        # 뉴스 통합 및 분류
│   ├── html_generator.py         # HTML 생성
│   └── telegram_bot.py           # 텔레그램 봇
├── docs/                         # 생성된 HTML 파일 (GitHub Pages)
├── main.py                       # 메인 실행 스크립트
├── requirements.txt              # Python 패키지
├── .env.example                  # 환경 변수 예시
├── .gitignore
└── README.md
```

## 🎨 기능 상세

### 뉴스 수집 및 번역

- **BBC News**: 세계 뉴스, 비즈니스, 정치 등 (자동 번역)
- **New York Times**: 세계 뉴스, 비즈니스, 정치 등 (자동 번역)
- **네이버 뉴스**: 정치, 경제, 사회, 세계, IT 등
- **다음 뉴스**: 정치, 경제, 사회, 국제, 문화, IT 등

해외 뉴스는 Google Translate API를 통해 자동으로 한국어로 번역되며, 각 기사에서 "원문 보기"를 클릭하면 영문 원문을 확인할 수 있습니다.

### 중요도 분석

다음 키워드를 포함한 뉴스를 자동으로 중요 뉴스로 표시:
- 전쟁, 재난, 위기, 긴급, 경보
- 금리, 환율, 주가, 폭락, 급등
- 대통령, 국회, 법안, 선거, 탄핵
- 기타 중요 키워드

### 웹 페이지 디자인

- 반응형 디자인 (모바일, 태블릿, 데스크톱)
- 다크모드 자동 지원
- A4 인쇄 최적화
- 출처 링크 표기

## 🔧 커스터마이징

### 뉴스 소스 추가

`src/collectors/` 디렉토리에 새로운 수집기 클래스를 추가하고, `src/news_aggregator.py`에서 통합하세요.

### 카테고리 수정

`src/news_aggregator.py`와 `src/html_generator.py`에서 카테고리 정의를 수정하세요.

### 스케줄 변경

`.github/workflows/daily_briefing.yml`의 cron 표현식을 수정하세요.

## 📝 라이선스

MIT License

## 🤝 기여

이슈 및 풀 리퀘스트를 환영합니다!

## 📧 문의

문제가 발생하면 GitHub Issues를 통해 문의해주세요.
