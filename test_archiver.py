"""
Self-check: archiver.py의 롤오버/압축/멱등성 검증
임시 디렉토리에 가짜 원본 스냅샷을 만들어 실제 rollover_old_archives()를
돌려본다. 실제 파일시스템 조작만 하고 네트워크/LLM 호출은 없다.

python test_archiver.py 로 실행. 실패 시 AssertionError로 즉시 중단.
"""
import json
import os
import shutil
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src import archiver


def _write_snapshot(raw_data_dir, d: date, titles):
    snapshot_dir = os.path.join(raw_data_dir, f"{d.year:04d}", f"{d.month:02d}")
    os.makedirs(snapshot_dir, exist_ok=True)
    snapshot = {
        "date": d.isoformat(),
        "categories": {
            "economy": [
                {"title": t, "summary": f"{t} 요약", "source": "테스트", "link": f"https://example.com/{t}"}
                for t in titles
            ]
        },
        "stock_picks": {
            "domestic": {"daily": [{"symbol": "005930", "name": "삼성전자", "price": 70000, "reason": "테스트", "daily_change_pct": 1.0}],
                         "weekly": [], "monthly": []},
            "overseas": {"daily": [], "weekly": [], "monthly": []},
        },
    }
    with open(os.path.join(snapshot_dir, f"{d.day:02d}.json"), "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False)


def _write_docs_day(docs_dir, d: date):
    day_dir = os.path.join(docs_dir, f"{d.year:04d}", f"{d.month:02d}", f"{d.day:02d}")
    os.makedirs(day_dir, exist_ok=True)
    with open(os.path.join(day_dir, "economy.html"), "w") as f:
        f.write("<html></html>")

    archive_data_file = os.path.join(docs_dir, "archive_data.json")
    items = []
    if os.path.exists(archive_data_file):
        with open(archive_data_file, "r", encoding="utf-8") as f:
            items = json.load(f)
    items.append({"date": d.isoformat(), "categories": []})
    with open(archive_data_file, "w", encoding="utf-8") as f:
        json.dump(items, f)


def test_rollover_compacts_dedupes_and_is_idempotent():
    tmp = tempfile.mkdtemp(prefix="test_archiver_")
    try:
        raw_dir = os.path.join(tmp, "data", "raw")
        docs_dir = os.path.join(tmp, "docs")
        archive_dir = os.path.join(tmp, "archive")

        today = date(2026, 8, 1)  # cutoff = 90일 전 = 2026-05-03
        old_date1 = date(2026, 4, 5)    # 롤오버 대상
        old_date2 = date(2026, 4, 20)   # 롤오버 대상, old_date1과 같은 달
        recent_date = today - timedelta(days=10)  # 보관 유지 대상

        # old_date1/old_date2는 제목이 하나 겹침("중복기사") — 월 단위 중복 제거 검증용
        _write_snapshot(raw_dir, old_date1, ["기사A", "중복기사"])
        _write_snapshot(raw_dir, old_date2, ["기사B", "중복기사"])
        _write_snapshot(raw_dir, recent_date, ["최근기사"])
        for d in (old_date1, old_date2, recent_date):
            _write_docs_day(docs_dir, d)

        archiver.rollover_old_archives(raw_dir, docs_dir, archive_dir, retention_days=90, today=today)

        # 오래된 두 날짜는 raw/docs에서 사라지고, 최근 날짜는 그대로 남아야 함
        year_month = old_date1.strftime('%Y-%m')
        assert old_date1.strftime('%Y-%m') == old_date2.strftime('%Y-%m'), "테스트 전제: 두 날짜가 같은 달이어야 함"

        old_raw1 = os.path.join(raw_dir, f"{old_date1.year:04d}", f"{old_date1.month:02d}", f"{old_date1.day:02d}.json")
        old_raw2 = os.path.join(raw_dir, f"{old_date2.year:04d}", f"{old_date2.month:02d}", f"{old_date2.day:02d}.json")
        assert not os.path.exists(old_raw1) and not os.path.exists(old_raw2), "원본 스냅샷이 삭제되지 않음"

        old_day_dir = os.path.join(docs_dir, f"{old_date1.year:04d}", f"{old_date1.month:02d}", f"{old_date1.day:02d}")
        assert not os.path.exists(old_day_dir), "오래된 날짜의 docs 폴더가 삭제되지 않음"

        recent_day_dir = os.path.join(docs_dir, f"{recent_date.year:04d}", f"{recent_date.month:02d}", f"{recent_date.day:02d}")
        assert os.path.exists(recent_day_dir), "최근 날짜(90일 이내)가 잘못 삭제됨"

        summary = archiver.load_month_summary(archive_dir, year_month)
        assert summary is not None, "월 요약 파일이 생성되지 않음"
        assert set(summary["included_dates"]) == {old_date1.isoformat(), old_date2.isoformat()}

        headlines = summary["categories"]["economy"]["headlines"]
        titles = [h["title"] for h in headlines]
        assert titles.count("중복기사") == 1, f"월 단위 중복 제거 실패: {titles}"
        assert "기사A" in titles and "기사B" in titles

        stock_picks = summary["categories"]["economy"]["stock_picks"]
        assert len(stock_picks) == 2, "두 날짜의 주식 추천이 모두 병합되어야 함"

        archive_data_file = os.path.join(docs_dir, "archive_data.json")
        with open(archive_data_file, "r", encoding="utf-8") as f:
            remaining = json.load(f)
        remaining_dates = {item["date"] for item in remaining}
        assert old_date1.isoformat() not in remaining_dates
        assert old_date2.isoformat() not in remaining_dates
        assert recent_date.isoformat() in remaining_dates

        # 멱등성: 같은 날짜로 다시 실행해도 summary가 그대로여야 함 (원본은 이미 삭제됐으니 no-op)
        archiver.rollover_old_archives(raw_dir, docs_dir, archive_dir, retention_days=90, today=today)
        summary_again = archiver.load_month_summary(archive_dir, year_month)
        assert summary_again == summary, "재실행 시 요약이 바뀌면 안 됨 (idempotent 아님)"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_rollover_compacts_dedupes_and_is_idempotent()
    print("OK: archiver self-check passed")
