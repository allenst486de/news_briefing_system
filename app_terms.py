"""
앱용 시사 용어 채우기 — 낱말퍼즐 매거진 앱에 싣는 용어만 따로 채운다.

GitHub Actions(.github/workflows/app_terms.yml)가 하루 네 번(모두 오전 8시 전) 부른다.
맥의 일일 브리핑과 따로 돌아서, 맥이 멈춘 날에도 용어가 쌓인다. 설계는 src/app_terms/.

    python app_terms.py                          # 오늘(KST) 채우기
    python app_terms.py --date 2026-09-14        # 특정 날짜 (07:40 마감 없이)
    python app_terms.py --out /tmp/app_terms     # 저장소 대신 다른 폴더에 (시험용)
    python app_terms.py --no-rss                 # 기사 목록이 없어도 RSS 를 모으지 않음

용어를 못 채워도 실패로 끝내지 않는다(종료 코드 0) — 다음 회차가 이어서 채운다.
결과 요약은 로그와 Actions 실행 요약 화면에 남는다.
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from dotenv import load_dotenv  # noqa: E402

from src.app_terms import pipeline  # noqa: E402

KST = timezone(timedelta(hours=9))


def _date(text: str):
    return datetime.strptime(text, "%Y-%m-%d").date()


def main(argv=None) -> int:
    load_dotenv(os.path.join(ROOT, ".env"))

    parser = argparse.ArgumentParser(description="앱용 시사 용어를 그날 파일에 채운다")
    parser.add_argument("--date", type=_date,
                        help="KST 날짜 YYYY-MM-DD — 적으면 07:40 마감 없이 그 날짜를 채운다 (기본: 오늘)")
    parser.add_argument("--out", help="저장 폴더 (기본: data/app_terms)")
    parser.add_argument("--target", type=int, default=pipeline.TARGET, help="하루 목표 개수")
    parser.add_argument("--budget", type=int, default=pipeline.JOB_BUDGET_SECONDS,
                        help="작업 전체 시간 상한(초)")
    parser.add_argument("--no-rss", action="store_true", help="기사 목록이 없어도 RSS 를 모으지 않음")
    args = parser.parse_args(argv)

    now = datetime.now(KST)
    day = args.date or now.date()
    budget, rss_ok, skip = pipeline.plan_run(day, now, args.budget, explicit_date=args.date is not None)
    if skip:
        text = f"앱용 시사 용어 {day.isoformat()}: {skip}"
    else:
        result = pipeline.fill_day(day, repo_root=ROOT, out_root=args.out, target=args.target,
                                   budget=budget, allow_rss=rss_ok and not args.no_rss)
        text = pipeline.format_summary(result)
        if not rss_ok and not args.no_rss:
            text += f"\n(RSS 대체 수집은 {pipeline.RSS_NOT_BEFORE:%H:%M} 이후 회차에서)"
    print(text)

    step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if step_summary:
        with open(step_summary, "a", encoding="utf-8") as f:
            f.write("### 앱용 시사 용어\n\n```\n" + text + "\n```\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
