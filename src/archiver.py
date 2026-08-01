"""
Archive Rollover & Compaction
3개월(retention_days) 지난 원본 데이터를 삭제하고, 연-월 단위 요약 JSON으로
압축해 archive/에 보관한다. archive/는 docs/ 밖에 있어 GitHub Pages에는
배포되지 않는다(publish_dir이 ./docs뿐이므로).

멱등성: summary.json의 included_dates에 이미 포함된 날짜는 재삽입하지 않는다.
원본 삭제 전에 실패해도(예: 중간에 크래시) 다음 실행에서 안전하게 재시도된다.
"""
import json
import os
import shutil
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from .utils.dedup import normalize_title
from .utils.logger import setup_logger

logger = setup_logger()


def load_month_summary(archive_dir: str, year_month: str) -> Optional[Dict]:
    path = os.path.join(archive_dir, year_month, 'summary.json')
    if not os.path.exists(path):
        return None
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def compact_month(archive_dir: str, year_month: str, day_snapshots: List[Dict]) -> Dict:
    """
    day_snapshots: 이번에 롤오버되는, 이 달에 속한 날짜들의 원본 스냅샷 리스트
    (html_generator._save_raw_snapshot이 만든 형식). 기존 summary.json이 있으면
    이어붙이고, 없으면 새로 만든다. 이미 포함된 날짜는 건너뛴다(idempotent).
    """
    summary = load_month_summary(archive_dir, year_month) or {
        'year_month': year_month, 'included_dates': [], 'categories': {}
    }
    included = set(summary['included_dates'])

    for snapshot in day_snapshots:
        date_str = snapshot.get('date')
        if not date_str or date_str in included:
            continue
        included.add(date_str)

        for category, articles in snapshot.get('categories', {}).items():
            cat_entry = summary['categories'].setdefault(category, {'article_count': 0, 'headlines': []})
            for article in articles:
                cat_entry['headlines'].append({
                    'date': date_str,
                    'title': article.get('title', ''),
                    'gist': (article.get('summary') or '')[:80],
                    'source': article.get('source', ''),
                    'link': article.get('link', ''),
                })

        stock_picks = snapshot.get('stock_picks') or {}
        if stock_picks:
            econ_entry = summary['categories'].setdefault('economy', {'article_count': 0, 'headlines': []})
            picks_list = econ_entry.setdefault('stock_picks', [])
            for market, horizons in stock_picks.items():
                for horizon, picks in horizons.items():
                    for pick in picks:
                        picks_list.append({
                            'date': date_str, 'market': market, 'horizon': horizon,
                            'symbol': pick.get('symbol'), 'name': pick.get('name'),
                            'reason': pick.get('reason'), 'price_at_pick': pick.get('price'),
                        })

    # 월 전체 기준 중복 제거 (정규화 제목 기준, 최초 등장 유지)
    for cat_entry in summary['categories'].values():
        seen = set()
        deduped = []
        for h in cat_entry['headlines']:
            key = normalize_title(h['title'])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(h)
        cat_entry['headlines'] = deduped
        cat_entry['article_count'] = len(deduped)

    summary['included_dates'] = sorted(included)
    summary['compacted_at'] = datetime.now().isoformat()

    month_dir = os.path.join(archive_dir, year_month)
    os.makedirs(month_dir, exist_ok=True)
    with open(os.path.join(month_dir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary


def query_stock_history(archive_dir: str, symbol: str, market: str, since: date) -> List[Dict]:
    """압축 아카이브에서 특정 종목의 과거 추천 이력을 조회 (Phase3 종목 추천 근거 생성 시 선택적으로 활용 가능)."""
    results = []
    if not os.path.isdir(archive_dir):
        return results

    for year_month in sorted(os.listdir(archive_dir)):
        try:
            ym = datetime.strptime(year_month, '%Y-%m').date()
        except ValueError:
            continue
        if ym.replace(day=1) < since.replace(day=1):
            continue

        summary = load_month_summary(archive_dir, year_month)
        if not summary:
            continue
        for pick in summary.get('categories', {}).get('economy', {}).get('stock_picks', []):
            if pick.get('symbol') != symbol or pick.get('market') != market:
                continue
            try:
                pick_date = datetime.strptime(pick['date'], '%Y-%m-%d').date()
            except (KeyError, ValueError):
                continue
            if pick_date >= since:
                results.append(pick)

    return results


def _remove_from_archive_data(docs_dir: str, date_str: str) -> None:
    archive_data_file = os.path.join(docs_dir, 'archive_data.json')
    if not os.path.exists(archive_data_file):
        return
    with open(archive_data_file, 'r', encoding='utf-8') as f:
        items = json.load(f)
    items = [item for item in items if item.get('date') != date_str]
    with open(archive_data_file, 'w', encoding='utf-8') as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def rollover_old_archives(raw_data_dir: str, docs_dir: str, archive_dir: str,
                           retention_days: int = 90, today: Optional[date] = None) -> None:
    """
    raw_data_dir(data/raw/YYYY/MM/DD.json)를 훑어 retention_days보다 오래된
    날짜를 archive/YYYY-MM/summary.json으로 압축한 뒤 docs/의 원본 페이지와
    archive_data.json 항목, data/raw의 원본 JSON을 삭제한다.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=retention_days)

    if not os.path.isdir(raw_data_dir):
        return

    old_dates = []
    for year_dir in os.listdir(raw_data_dir):
        year_path = os.path.join(raw_data_dir, year_dir)
        if not os.path.isdir(year_path) or not year_dir.isdigit():
            continue
        for month_dir in os.listdir(year_path):
            month_path = os.path.join(year_path, month_dir)
            if not os.path.isdir(month_path):
                continue
            for day_file in os.listdir(month_path):
                if not day_file.endswith('.json'):
                    continue
                day_str = day_file[:-5]
                try:
                    file_date = date(int(year_dir), int(month_dir), int(day_str))
                except ValueError:
                    continue
                if file_date < cutoff:
                    old_dates.append((file_date, os.path.join(month_path, day_file)))

    if not old_dates:
        logger.info("Archive rollover: nothing older than retention window")
        return

    by_month: Dict[str, List[Dict]] = {}
    loaded = []
    for file_date, raw_path in old_dates:
        try:
            with open(raw_path, 'r', encoding='utf-8') as f:
                snapshot = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {raw_path} for rollover: {e}")
            continue
        by_month.setdefault(file_date.strftime('%Y-%m'), []).append(snapshot)
        loaded.append((file_date, raw_path))

    for year_month, snapshots in by_month.items():
        compact_month(archive_dir, year_month, snapshots)
        logger.info(f"Compacted {len(snapshots)} day(s) into archive/{year_month}/summary.json")

    for file_date, raw_path in loaded:
        date_str = file_date.isoformat()
        try:
            os.remove(raw_path)
        except OSError:
            pass
        shutil.rmtree(os.path.join(docs_dir, file_date.strftime('%Y/%m/%d')), ignore_errors=True)
        _remove_from_archive_data(docs_dir, date_str)

    logger.info(f"Archive rollover complete: {len(loaded)} day(s) archived and removed from docs/")
