"""
Self-check: sources.py에 등록된 모든 RSS 피드가 살아있는지 확인
(daily_briefing.yml 워크플로에는 포함하지 않음 — 언론사 목록을 바꿀 때 수동 실행)

python test_feeds.py 로 실행. 죽은 피드가 있어도 중단하지 않고 끝까지 확인 후 요약 출력.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.collectors.sources import SOURCES
from src.utils.rss_utils import fetch_feed


def check_all_feeds():
    failures = []
    total = 0

    for source in SOURCES:
        for category, url in source["feeds"].items():
            total += 1
            feed = fetch_feed(url)
            ok = bool(feed and feed.entries)
            status = "OK  " if ok else "FAIL"
            print(f"[{status}] {source['id']}/{category}: {url}")
            if not ok:
                failures.append((source["id"], category, url))

    print(f"\n{total - len(failures)}/{total} feeds alive.")
    if failures:
        print("Dead feeds:")
        for source_id, category, url in failures:
            print(f"  - {source_id}/{category}: {url}")
    return failures


if __name__ == "__main__":
    dead = check_all_feeds()
    if dead:
        sys.exit(1)
    print("OK: all feeds alive")
