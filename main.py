"""
Main Execution Script
뉴스 수집, HTML 생성, 텔레그램 전송을 실행하는 메인 스크립트
"""
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# 프로젝트 루트를 Python 경로에 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.news_aggregator import NewsAggregator
from src.html_generator import HTMLGenerator
from src.telegram_bot import TelegramNotifier
from src.utils.logger import setup_logger


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
        template_dir = os.path.join(os.path.dirname(__file__), 'src', 'templates')
        output_dir = os.path.join(os.path.dirname(__file__), 'docs')
        
        generator = HTMLGenerator(template_dir, output_dir)
        page_urls = generator.generate_all(categorized_news)
        
        # 3. 텔레그램 전송
        logger.info("Step 3: Sending Telegram notification...")
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        base_url = os.getenv('PAGES_BASE_URL')
        
        if not bot_token or not chat_id:
            logger.warning("Telegram credentials not found. Skipping notification.")
        else:
            notifier = TelegramNotifier(bot_token, chat_id, base_url)
            date_str = datetime.now().strftime('%Y-%m-%d')
            notifier.send_briefing_sync(page_urls, date_str)
        
        logger.info("=" * 60)
        logger.info("Daily News Briefing System completed successfully!")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"Error in main execution: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
