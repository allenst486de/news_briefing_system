"""
시사용어 만회 — 새벽 브리핑에서 시사용어가 빠진 날 뒤늦게 채운다.

새벽(03:50 무렵) NVIDIA가 불안정하면 시사용어 호출만 실패하는 날이 있었다(2026-10-01·10-02).
그날 기사·요약은 이미 data/raw에 저장돼 있으므로, 05:45·07:30 재확인 실행이 그 스냅샷으로
시사용어를 다시 뽑는다. 성공하면
  1) 연 단위 저장소(data/terms)에 쌓고
  2) 시사용어 페이지를 다시 만들고
  3) 텔레그램으로 시사용어 카드와 링크를 보낸다.
홈·분야 페이지와 Top10은 이미 발행됐으므로 건드리지 않는다.

오늘치 용어가 이미 있으면 아무것도 하지 않는다(LLM도 부르지 않는다).
종료 코드: 0 = 할 일 없음 또는 성공, 2 = 이번에도 실패(다음 재확인 때 다시).
"""
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

KST = timezone(timedelta(hours=9))


def _load_buckets(raw_file: str, generator, date_str: str):
    from src.collectors.base_collector import NewsArticle
    with open(raw_file, encoding="utf-8") as f:
        categories = json.load(f)["categories"]
    buckets = {}
    for category, regions in categories.items():
        buckets[category] = {}
        for region, items in regions.items():
            articles = []
            for item in items:
                article = NewsArticle(item["title"], item["link"],
                                      datetime.fromisoformat(item["published"]),
                                      item.get("summary", ""), item.get("source", ""), category)
                article.is_important = item.get("is_important", False)
                if region == "overseas":
                    article.detail_rel = generator.detail_rel_for(article.link, date_str)
                articles.append(article)
            buckets[category][region] = articles
    return buckets


def main() -> int:
    load_dotenv(os.path.join(ROOT, ".env"))
    from src.html_generator import HTMLGenerator
    from src import summarizer, terms_extractor
    from src.utils import llm_client, terms_store
    from src.utils.cardnews import generate_terms_cards
    from src.utils.logger import setup_logger

    logger = setup_logger()
    now = datetime.now(KST)
    date_str = now.strftime("%Y-%m-%d")
    raw_dir = os.path.join(ROOT, "data", "raw")
    generator = HTMLGenerator(os.path.join(ROOT, "src", "templates"), os.path.join(ROOT, "docs"),
                              os.getenv("PAGES_BASE_URL", ""), raw_data_dir=raw_dir)
    terms_dir = generator._terms_dir()
    year_terms = terms_store.load_year(terms_dir, now.year)
    if any(t.get("date") == date_str for t in year_terms):
        print(f"시사용어 만회: 오늘({date_str}) 용어가 이미 있음 — 할 일 없음")
        return 0

    raw_file = os.path.join(raw_dir, now.strftime("%Y"), now.strftime("%m"), f"{now.strftime('%d')}.json")
    if not os.path.exists(raw_file):
        print(f"시사용어 만회: 오늘 기사 스냅샷이 없음({raw_file}) — 브리핑이 먼저 돌아야 함")
        return 0

    logger.info("시사용어 만회: 새벽 실행에서 빠진 오늘 시사용어를 다시 뽑는다")
    buckets = _load_buckets(raw_file, generator, date_str)
    llm_client.reserve_budget(1200)
    extracted = terms_extractor.extract_terms(
        buckets, known_terms=[t.get("term", "") for t in year_terms],
        api_key=summarizer.category_api_key("society"), date_str=date_str,
    )
    if not extracted:
        print("시사용어 만회: 이번에도 실패 — 다음 재확인 실행에서 다시")
        print(llm_client.stats_summary())
        return 2

    terms_store.append_terms(terms_dir, extracted)
    terms_file = generator.regenerate_terms_page(date_str)
    print(f"시사용어 만회: {len(extracted)}건 저장, 시사용어 페이지 갱신")

    bot_token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        from src.telegram_bot import TelegramNotifier
        images = generate_terms_cards(extracted, date_str, tempfile.gettempdir())
        notifier = TelegramNotifier(bot_token, chat_id, os.getenv("PAGES_BASE_URL", ""))
        try:
            notifier.send_terms_sync(images, date_str, terms_file)
            print(f"시사용어 만회: 텔레그램 전송 완료(카드 {len(images)}장)")
        except Exception as error:
            # 저장·페이지는 이미 됐다 — 다음 재확인은 '오늘 용어 있음'으로 건너뛰므로 다시 보내지 않는다
            print(f"시사용어 만회: 텔레그램 전송 실패({error}) — 페이지에는 반영됨")
    return 0


if __name__ == "__main__":
    sys.exit(main())
