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
from src.utils.cardnews import generate_top10_card
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
    
    try:
        # 1. 뉴스 수집
        logger.info("Step 1: Collecting news from all sources...")
        aggregator = NewsAggregator()
        categorized_news = aggregator.collect_all_news()
        
        # 2. HTML 생성
        logger.info("Step 2: Generating HTML pages...")
        repo_root = os.path.dirname(__file__)
        template_dir = os.path.join(repo_root, 'src', 'templates')
        output_dir = os.path.join(repo_root, 'docs')
        raw_data_dir = os.path.join(repo_root, 'data', 'raw')
        base_url = os.getenv('PAGES_BASE_URL', '')

        generator = HTMLGenerator(template_dir, output_dir, base_url, raw_data_dir=raw_data_dir)
        page_urls, top10_by_region = generator.generate_all(categorized_news)

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

            notifier = TelegramNotifier(bot_token, chat_id, base_url)
            notifier.send_briefing_sync(page_urls, top10_by_region, date_str, images)

        # 4. 3개월 지난 자료 압축 롤오버 (실패해도 전체 실행은 성공으로 취급)
        try:
            logger.info("Step 4: Rolling over archives older than retention window...")
            archive_dir = os.path.join(repo_root, 'archive')
            archiver.rollover_old_archives(raw_data_dir, output_dir, archive_dir)
        except Exception as e:
            logger.warning(f"Archive rollover failed (non-fatal): {e}")

        _report_llm_status(logger)

        logger.info("=" * 60)
        logger.info("Daily News Briefing System completed successfully!")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Error in main execution: {e}", exc_info=True)
        sys.exit(1)


def _report_llm_status(logger) -> None:
    """
    LLM은 실패해도 규칙기반으로 조용히 폴백하기 때문에, 번역/요약이 몇 주째 안 되는 걸
    모르고 지나간 적이 있다. 실행 요약($GITHUB_STEP_SUMMARY)과 로그에 집계를 남겨
    Actions 화면에서 바로 보이게 한다.
    """
    summary = llm_client.stats_summary()
    stats = llm_client.LLM_STATS
    degraded = stats["ok"] == 0 and stats["calls"] > 0
    headline = "❌ LLM 전부 실패 — 요약/번역이 규칙기반으로 대체됨" if degraded else "✅ LLM 정상 동작"

    logger.info(f"LLM status: {headline} | {summary}")

    step_summary = os.getenv('GITHUB_STEP_SUMMARY')
    if not step_summary:
        return
    try:
        with open(step_summary, 'a', encoding='utf-8') as f:
            f.write(f"### LLM 요약·번역 상태\n\n{headline}\n\n```\n{summary}\n```\n")
    except OSError as e:
        logger.warning(f"Could not write step summary: {e}")


if __name__ == "__main__":
    main()
