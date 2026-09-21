"""
Main Execution Script
뉴스 수집, HTML 생성, 텔레그램 전송을 실행하는 메인 스크립트
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.news_aggregator import NewsAggregator
from src.html_generator import HTMLGenerator
from src.telegram_bot import TelegramNotifier
from src.utils.logger import setup_logger
from src.utils.cardnews import generate_top10_card, generate_terms_cards
from src.utils import llm_client
from src import archiver

KST = timezone(timedelta(hours=9))


def main():
    """메인 실행 함수"""
    # 환경 변수 로드
    load_dotenv()
    
    # 로거 설정
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("Starting Daily News Briefing System")
    logger.info("=" * 60)
    
    telegram_failed = False
    try:
        # 1. 뉴스 수집
        logger.info("Step 1: Collecting news from all sources...")
        repo_root = os.path.dirname(__file__)
        raw_data_dir = os.path.join(repo_root, 'data', 'raw')
        # 전날 이미 실은 기사를 다시 싣지 않으려면 과거 스냅샷을 봐야 한다
        aggregator = NewsAggregator(raw_data_dir=raw_data_dir)
        categorized_news = aggregator.collect_all_news()

        # 2. HTML 생성
        logger.info("Step 2: Generating HTML pages...")
        template_dir = os.path.join(repo_root, 'src', 'templates')
        output_dir = os.path.join(repo_root, 'docs')
        base_url = os.getenv('PAGES_BASE_URL', '')

        generator = HTMLGenerator(template_dir, output_dir, base_url, raw_data_dir=raw_data_dir)
        (page_urls, top10_by_region, archive_file,
         terms_today, terms_file) = generator.generate_all(categorized_news)
        _record_fallback_rate(categorized_news)

        # 3. 텔레그램 전송
        logger.info("Step 3: Sending Telegram notification...")
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')

        if not bot_token or not chat_id:
            logger.warning("Telegram credentials not found. Skipping notification.")
        else:
            # 러너가 UTC라 naive now()를 쓰면 06시 KST 발행분이 전날로 찍힌다
            date_str = datetime.now(KST).strftime('%Y-%m-%d')
            # 국내/해외 인포그래픽을 따로 만들어 둘 다 보낸다
            images = []
            for region, label in (('domestic', '국내'), ('overseas', '해외')):
                cards = top10_by_region.get(region) or []
                path = generate_top10_card(
                    cards, date_str,
                    os.path.join(tempfile.gettempdir(), f'top10_{region}_{date_str}.png'),
                    region_label=label,
                )
                if path:
                    images.append((path, label))

            # 시사용어 인포그래픽 — 5개씩 끊어 2~4장. 용어가 없는 날은 빈 목록이라
            # 아무것도 보내지 않는다.
            term_images = generate_terms_cards(terms_today, date_str, tempfile.gettempdir())

            notifier = TelegramNotifier(bot_token, chat_id, base_url)
            try:
                notifier.send_briefing_sync(page_urls, top10_by_region, date_str, images,
                                             archive_rel=archive_file,
                                             term_images=term_images,
                                             terms_rel=terms_file if terms_today else '')
                _mark_delivered(date_str)
            except Exception as e:
                # 전송이 실패해도 사이트는 이미 만들어졌다 — 여기서 죽으면 커밋·배포까지
                # 막혀 사이트도 안 올라간다. 배포는 진행하게 두고 종료 코드로 알린다.
                # 실행 스크립트가 전송 완료 표시가 없는 것을 보고 만회 실행 때 다시 보낸다.
                logger.error(f"Telegram 전송 실패 — 사이트 배포는 계속, 만회 실행에서 재전송: {e}")
                telegram_failed = True

        # 4. 3개월 지난 자료 압축 롤오버 (실패해도 전체 실행은 성공으로 취급)
        try:
            logger.info("Step 4: Rolling over archives older than retention window...")
            archive_dir = os.path.join(repo_root, 'archive')
            archiver.rollover_old_archives(raw_data_dir, output_dir, archive_dir)
        except Exception as e:
            logger.warning(f"Archive rollover failed (non-fatal): {e}")

        _report_llm_status(logger)

        if telegram_failed:
            # 3 = 사이트는 만들었지만 전송 실패. 실행 스크립트는 배포까지 하고 만회 실행을 남긴다.
            sys.exit(EXIT_SITE_ONLY)

        logger.info("=" * 60)
        logger.info("Daily News Briefing System completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Error in main execution: {e}", exc_info=True)
        sys.exit(1)


# 사이트는 만들었는데 텔레그램 전송만 실패한 경우의 종료 코드 (scripts/run_daily_briefing.sh와 맞춘다)
EXIT_SITE_ONLY = 3


def _mark_delivered(date_str: str) -> None:
    """
    텔레그램 전송까지 끝났다는 표시. 실행 스크립트가 이 파일을 보고 같은 날 만회 실행
    (재부팅 후·05:45·07:30 재확인)을 건너뛴다 — 두 번 보내지 않기 위한 장치다.
    경로는 실행 스크립트가 BRIEFING_SENT_MARKER로 넘긴다(없으면 아무것도 안 한다).
    """
    marker = os.getenv('BRIEFING_SENT_MARKER')
    if not marker:
        return
    try:
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, 'w', encoding='utf-8') as f:
            f.write(f"{date_str} {datetime.now(KST).isoformat()}\n")
    except OSError as e:
        setup_logger().warning(f"전송 완료 표시를 남기지 못함: {e}")


def _record_fallback_rate(buckets) -> None:
    """
    기사 단위로 몇 건이 규칙기반으로 떨어졌는지 센다.
    호출 성공률만 보면 '✅ 정상'인데 화면에는 영문 기사가 남아 있는 경우가 있다
    (청크 일부만 실패). 지면에 실제로 반영된 비율을 따로 봐야 한다.
    """
    articles = [a for regions in buckets.values() for arts in regions.values() for a in arts]
    failed = sum(1 for a in articles if getattr(a, 'llm_failed', False))
    llm_client.LLM_STATS['articles_total'] = len(articles)
    llm_client.LLM_STATS['articles_fallback'] = failed


def _report_llm_status(logger) -> None:
    """
    LLM은 실패해도 규칙기반으로 조용히 폴백하기 때문에, 번역/요약이 몇 주째 안 되는 걸
    모르고 지나간 적이 있다. 실행 요약($GITHUB_STEP_SUMMARY)과 로그에 집계를 남겨
    Actions 화면에서 바로 보이게 한다.
    """
    summary = llm_client.stats_summary()
    keys = llm_client.key_status_report()
    stats = llm_client.LLM_STATS
    total = stats.get('articles_total') or 0
    failed = stats.get('articles_fallback') or 0
    rate = (failed * 100 // total) if total else 0

    if stats["ok"] == 0 and stats["calls"] > 0:
        headline = "❌ LLM 전부 실패 — 요약/번역이 규칙기반으로 대체됨"
    elif rate >= 10:
        # 호출은 일부 성공했지만 지면에 영문·원문 그대로 남은 기사가 많은 상태
        headline = f"⚠️ LLM 부분 실패 — 기사 {failed}/{total}건({rate}%)이 규칙기반으로 대체됨"
    else:
        headline = f"✅ LLM 정상 동작 (규칙기반 대체 {failed}/{total}건)"
    if stats.get('retry_recovered'):
        headline += f" · 재시도로 {stats['retry_recovered']}건 복구"

    logger.info(f"LLM status: {headline} | {summary}")

    step_summary = os.getenv('GITHUB_STEP_SUMMARY')
    if not step_summary:
        return
    try:
        with open(step_summary, 'a', encoding='utf-8') as f:
            f.write(f"### LLM 요약·번역 상태\n\n{headline}\n\n```\n{summary}\n```\n")
            # 키가 8개라 어느 키가 문제인지 같이 보여야 짚을 수 있다
            f.write(f"\n**API 키 점검**\n\n```\n{keys}\n```\n")
    except OSError as e:
        logger.warning(f"Could not write step summary: {e}")


if __name__ == "__main__":
    main()
