"""
앱용 시사 용어 비축 — data/app_terms/stock/YYYY.json.

하루치 후보가 모자란 날(NVIDIA 장애·기사 부족·위키백과 문서 없음)에 끌어 쓸 용어를 미리 쌓아 둔다.
  build   지난 브리핑(2/3~)의 기사 제목·요약에서 용어를 뽑아 위키백과·뜻풀이까지 마친 뒤 쌓는다.
  take    fill_day 가 그날 몫이 모자랄 때 하나씩 꺼내 그날 파일에 옮긴다(꺼낸 건 비축에서 빠진다).

비축 항목은 그날 파일 항목과 같은 모양이고 date 만 없다(꺼낼 때 붙인다). 중복 판단·글 규칙은 pipeline 과 같다.

    python -m src.app_terms.stock build --target 400 --stop-before 02:45
"""
import argparse
import glob
import html
import json
import os
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

from ..utils.logger import setup_logger
from . import nim, pipeline, store, web, wiki

logger = setup_logger()
KST = timezone(timedelta(hours=9))

FIRST_BRIEFING = Date(2026, 2, 3)          # 브리핑을 시작한 날 — 1월 자료는 없다
WINDOW_DAYS = 3                            # 한 호출에 며칠치 기사를 보여 줄지
WINDOW_ARTICLES = 30                       # 호출당 기사 수 (중요 기사 먼저)
SUMMARY_CHARS = 120
TERMS_PER_CALL = 6
CALL_WORKERS = 4
ROUND_WINDOWS = 3                          # 한 회차에 창을 몇 개 함께 부를지 — 응답 대기를 겹쳐 쓴다
STRIDE = 37                                # 창을 건너뛰며 고른다 — 일찍 멈춰도 해 전체에서 고르게 모이도록

# 옛 사이트(2~7월)는 분야가 5쪽뿐이다 — 쪽 이름으로 8개 분야에 맞춘다
_PAGE_CATEGORY = {
    "politics": "politics", "economy": "economy", "society": "society", "life": "life",
    "culture": "culture", "it": "it", "science": "science", "world": "world",
    "domestic_politics": "politics", "domestic_economy": "economy", "domestic_general": "society",
    "world_economy_politics": "world", "world_general": "world",
}
_ITEM = re.compile(r'<div class="news-item[^"]*">(.*?)(?=<div class="news-item|</section>|$)', re.S)
_TITLE = re.compile(r'class="news-title">\s*<a [^>]*>(.*?)</a>', re.S)
_SUMMARY = re.compile(r'<p class="news-summary">(.*?)</p>', re.S)


def stock_path(root: str, year: int) -> str:
    return os.path.join(root, "stock", f"{year}.json")


def load(root: str, year: int) -> Dict:
    try:
        with open(stock_path(root, year), "r", encoding="utf-8") as f:
            doc = json.load(f)
        if isinstance(doc, dict) and isinstance(doc.get("terms"), list):
            doc.setdefault("done", [])
            return doc
    except (OSError, ValueError):
        pass
    return {"terms": [], "done": []}


def save(root: str, year: int, doc: Dict) -> None:
    path = stock_path(root, year)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def keys_of(doc: Dict) -> Set[str]:
    keys: Set[str] = set()
    for entry in doc["terms"]:
        keys |= store.term_keys(entry)
    return keys


# ── 꺼내 쓰기 ─────────────────────────────────────────────────────────────

def take(root: str, day: Date, doc: Dict, count: int) -> List[Dict]:
    """비축에서 count개를 그날 doc 에 옮긴다(저장은 부르는 쪽이). 올해 이미 실린 것과 겹치면 버린다."""
    if count <= 0:
        return []
    stock = load(root, day.year)
    known: Set[str] = set()
    for entry in store.load_year_terms(root, day.year):
        known |= store.term_keys(entry)
    for entry in doc["terms"]:
        known |= store.term_keys(entry)

    taken, kept = [], []
    for entry in pipeline.interleave(list(stock["terms"])):
        keys = store.term_keys(entry)
        if keys & known:
            continue                    # 그사이 다른 경로로 실렸다 — 비축에서도 지운다
        if not store.is_wiki(entry) and not pipeline.NON_WIKI_IN_DAY:
            kept.append(entry)          # 앱이 받을 준비가 되기 전까지 비축에 둔다
            continue
        if len(taken) < count:
            known |= keys
            taken.append({**{k: v for k, v in entry.items() if k != "foundOn"},
                          "date": day.isoformat(), "via": "stock"})
        else:
            kept.append(entry)
    if taken or len(kept) != len(stock["terms"]):
        stock["terms"] = kept
        save(root, day.year, stock)
    doc["terms"].extend(taken)
    return taken


# ── 지난 기사 읽기 ────────────────────────────────────────────────────────

def _articles_from_pages(repo_root: str, day: Date) -> Dict[str, List[Dict]]:
    folder = os.path.join(repo_root, "docs", f"{day:%Y}", f"{day:%m}", f"{day:%d}")
    result: Dict[str, List[Dict]] = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.html"))):
        name = os.path.basename(path)[:-5]
        category = _PAGE_CATEGORY.get(name if name in _PAGE_CATEGORY else name.split("-")[0])
        if not category:
            continue                    # a-xxxx 상세 쪽 등
        try:
            text = open(path, "r", encoding="utf-8").read()
        except OSError:
            continue
        for block in _ITEM.findall(text):
            title = _TITLE.search(block)
            summary = _SUMMARY.search(block)
            if not title:
                continue
            result.setdefault(category, []).append({
                "title": html.unescape(re.sub(r"<[^>]+>", "", title.group(1))).strip(),
                "summary": html.unescape(re.sub(r"<[^>]+>", "", summary.group(1))).strip() if summary else "",
                "important": "important-badge" in block,
            })
    for items in result.values():
        items.sort(key=lambda a: a["important"], reverse=True)
    return result


def day_articles(repo_root: str, day: Date) -> Dict[str, List[Dict]]:
    """그날 기사 — 맥이 남긴 원본이 있으면 그것, 없으면 사이트 쪽에서 읽는다."""
    path = pipeline.raw_path(repo_root, day)
    if os.path.exists(path):
        try:
            data = pipeline.articles_from_raw(path)
            if any(data.values()):
                return data
        except (OSError, ValueError, AttributeError, TypeError):
            pass            # 8/4~8/12 원본은 분야 아래가 목록이다(지역 구분 없음) — 사이트 쪽에서 읽는다
    return _articles_from_pages(repo_root, day)


def _days(repo_root: str, last: Date) -> List[Date]:
    days, day = [], FIRST_BRIEFING
    while day <= last:
        if any(day_articles(repo_root, day).values()):     # 기사 없이 비어 있던 날(초기 시험 기간)은 뺀다
            days.append(day)
        day += timedelta(days=1)
    return days


def _windows(days: List[Date]) -> List[List[Date]]:
    chunks = [days[i:i + WINDOW_DAYS] for i in range(0, len(days), WINDOW_DAYS)]
    n = len(chunks)
    order, seen, i = [], set(), 0
    while len(order) < n:
        k = (i * STRIDE) % n
        while k in seen:
            k = (k + 1) % n
        seen.add(k)
        order.append(chunks[k])
        i += 1
    return order


# ── 공개되는 말인지(낱말퍼즐 쪽 금칙어·12개월 중복) ──────────────────────

def _publish_check(clone: Optional[str]):
    """낱말퍼즐 쪽 게시 스크립트가 거르는 말(금칙어·앱에 이미 들어 있는 말)을 미리 거른다."""
    path = os.path.join(clone or "", ".github", "affairs", "publish.py")
    if not os.path.exists(path):
        return lambda entry: True
    import importlib.util
    spec = importlib.util.spec_from_file_location("affairs_publish", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    day = Date(2026, 12, 31)
    return lambda entry: bool(module.pick([entry], day)[0])


# ── 쌓기 ──────────────────────────────────────────────────────────────────

def _prompt(category: str, articles: List[Dict], exclude: List[str]) -> str:
    listing = "\n".join(f"{i}. {pipeline.one_line(a['title'])} — "
                        f"{pipeline.one_line(a['summary'])[:SUMMARY_CHARS]}"
                        for i, a in enumerate(articles, 1))
    block = ("이미 실은 용어이니 고르지 마세요: " + ", ".join(exclude) + "\n") if exclude else ""
    return (f"분야: {pipeline._category_name(category)}\n"
            f"아래 기사 목록에서 독자가 뜻을 알면 기사를 더 잘 이해할 수 있는 시사 용어를 "
            f"최대 {TERMS_PER_CALL}개 고르세요. 위키백과에 문서가 있을 만한 일반 용어를 우선합니다.\n"
            "영어 등 원어가 기사에 함께 쓰였으면 '한국어(원어)' 형태로 적으세요.\n"
            f"{block}"
            '형식: [{"id": 기사번호, "term": "용어"}]\n\n'
            f"기사 목록:\n{listing}")


def build(repo_root: str, *, out_root: Optional[str] = None, target: int = 400,
          stop_before: Optional[str] = None, max_rounds: int = 10_000, pool=None, chat=None,
          wiki_lookup=None, publish_clone: Optional[str] = None, today: Optional[Date] = None) -> Dict:
    out_root = out_root or os.path.join(repo_root, "data", "app_terms")
    chat = chat or nim.chat_with_model
    wiki_lookup = wiki_lookup or wiki.lookup
    pool = pool if pool is not None else nim.KeyPool.from_env()
    if not len(pool):
        return {"stopped": "NVIDIA 키 없음", "added": 0, "total": 0}
    publishable = _publish_check(publish_clone)

    today = today or datetime.now(KST).date()
    year = today.year
    doc = load(out_root, year)
    done = set(doc["done"])
    windows = [w for w in _windows(_days(repo_root, today - timedelta(days=1)))
               if f"{w[0]:%Y-%m-%d}" not in done]
    quiet_rounds = 0
    stats = Counter()
    result = {"stopped": "", "added": 0, "rejected": stats}
    nim.reset_stats()

    def past_stop() -> bool:
        if not stop_before:
            return False
        hour, minute = (int(x) for x in stop_before.split(":"))
        now = datetime.now(KST)
        return hour * 60 + minute <= now.hour * 60 + now.minute < 8 * 60   # stop_before~08:00 사이만 쉰다

    for round_no, start in enumerate(range(0, len(windows[:max_rounds * ROUND_WINDOWS]), ROUND_WINDOWS), 1):
        group = windows[start:start + ROUND_WINDOWS]
        if len(doc["terms"]) >= target:
            result["stopped"] = f"목표 {target}개 달성"
            break
        if past_stop():
            result["stopped"] = f"{stop_before} 도달 — 새벽 브리핑에 자리를 비운다"
            break
        # 새벽 회차가 비축에서 꺼냈을 수 있으니 매번 디스크 기준으로 다시 잡는다
        doc["terms"] = load(out_root, year)["terms"]
        known = store.known_keys(out_root, year) | keys_of(doc)
        deadline = time.monotonic() + 1500
        exclude = [e.get("reading") or e.get("term") for e in reversed(doc["terms"])][:60]
        jobs = []
        for window in group:
            buckets: Dict[str, List[Dict]] = {}
            for day in window:
                for category, items in day_articles(repo_root, day).items():
                    buckets.setdefault(category, []).extend(items[:10])
            for category, items in buckets.items():
                items = items[:WINDOW_ARTICLES]
                if items:
                    jobs.append((category, items, _prompt(category, items, exclude), f"{window[0]:%Y-%m-%d}"))
        window = group[0]

        def ask(job):
            return pipeline._reply(chat(pool, pipeline.DISCOVERY_SYSTEM, job[2], max_tokens=700,
                                        temperature=0.3, deadline=deadline))[0]

        with ThreadPoolExecutor(max_workers=min(len(jobs), CALL_WORKERS) or 1) as workers:
            replies = list(workers.map(ask, jobs)) if jobs else []

        fresh, tried = [], set()
        for (category, items, _, found_on), raw in zip(jobs, replies):
            for item in pipeline._json_list(raw)[:TERMS_PER_CALL]:
                try:
                    index = int(item.get("id"))
                except (TypeError, ValueError):
                    continue
                term = pipeline.clean_text(item.get("term"))
                if not term or not 1 <= index <= len(items):
                    continue
                article = items[index - 1]
                if not pipeline.appears_in(term, f"{article['title']} {article['summary']}"):
                    stats["not_in_article"] += 1
                    continue
                original, reading = pipeline.split_term(term)
                head = pipeline.tidy_headword(original)
                keys = {pipeline.normalize_term(head), pipeline.normalize_term(reading)} - {""}
                if not keys or keys & (known | tried):
                    stats["duplicate"] += 1
                    continue
                tried |= keys
                fresh.append({"term": term, "category": category, "head": head,
                              "reading": reading, "lookup": original, "foundOn": found_on})

        approved, webbed = [], []
        if fresh:
            found = wiki_lookup([t for c in fresh for t in (c["reading"], c["lookup"]) if t])
            for candidate in pipeline.interleave(fresh):
                info = (found.get(candidate["reading"]) if candidate["reading"] else None) \
                    or found.get(candidate["lookup"])
                reason = None
                if not info:
                    webbed.append(candidate)
                    continue
                elif info.get("disambiguation"):
                    reason = "disambiguation"
                elif info.get("person"):
                    reason = "person"
                elif info.get("entity"):
                    reason = "entity"
                elif "wiki:" + info["title"] in known:
                    reason = "duplicate"
                if reason:
                    stats[reason] += 1
                    continue
                known.add("wiki:" + info["title"])
                approved.append({**candidate, "wiki": info})

        proofs = web.evidence(webbed)       # 위키 문서가 없는 말은 검색 근거로(비축분에만 쌓인다)
        for candidate in webbed:
            if candidate["head"] in proofs:
                approved.append({**candidate, "evidence": proofs[candidate["head"]]})
            else:
                stats["no_evidence"] += 1

        batches = [approved[i:i + pipeline.MEANING_BATCH]
                   for i in range(0, len(approved), pipeline.MEANING_BATCH)]
        if batches:
            with ThreadPoolExecutor(max_workers=min(len(batches), pipeline.MEANING_WORKERS)) as workers:
                results = list(workers.map(
                    lambda b: pipeline.write_meanings(b, pool=pool, chat=chat, deadline=deadline), batches))
            for batch, meanings in zip(batches, results):
                for number, candidate in enumerate(batch, 1):
                    meaning, concept, model = meanings.get(number, (None, None, None))
                    if not meaning:
                        stats["no_meaning"] += 1
                        continue
                    entry = {**pipeline.build_entry(candidate, meaning, concept, model),
                             "via": "stock", "foundOn": candidate["foundOn"]}
                    if not publishable(entry):
                        stats["blocked_by_app"] += 1
                        continue
                    doc["terms"].append(entry)
                    known |= store.term_keys(entry)
                    result["added"] += 1
        # 응답을 한 번도 못 받은 창(429·장애)은 읽은 것으로 치지 않는다 — 다음 실행이 다시 읽는다
        answered = {job[3] for job, reply in zip(jobs, replies) if reply}
        silent = [w for w in group if f"{w[0]:%Y-%m-%d}" not in answered and any(j[3] == f"{w[0]:%Y-%m-%d}" for j in jobs)]
        doc["done"].extend(f"{w[0]:%Y-%m-%d}" for w in group if w not in silent)
        save(out_root, year, doc)
        if jobs and not answered:
            quiet_rounds += 1
            if quiet_rounds >= 3:
                result["stopped"] = "NVIDIA가 연달아 응답하지 않아 멈춤(호출제한일 수 있음) — 나중에 이어서"
                break
            time.sleep(180)             # 호출제한이 풀릴 때까지 쉰다
        else:
            quiet_rounds = 0
        logger.info(f"비축 {round_no}회차(창 {len(group)}개, {group[0][0]}~): 비축 {len(doc['terms'])}개 "
                    f"(+{result['added']}) · {nim.stats_line()}")
    else:
        result["stopped"] = result["stopped"] or "읽을 창을 다 읽음"
    result["total"] = len(doc["terms"])
    result["rejected"] = dict(stats)
    return result


def main(argv=None) -> int:
    from dotenv import load_dotenv
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    load_dotenv(os.path.join(root, ".env"))
    parser = argparse.ArgumentParser(description="앱용 시사 용어 비축 쌓기")
    parser.add_argument("command", choices=["build", "status"])
    parser.add_argument("--target", type=int, default=400)
    parser.add_argument("--stop-before", help="이 시각(KST HH:MM)이 되면 멈춘다 — 새벽 브리핑과 겹치지 않게")
    parser.add_argument("--max-rounds", type=int, default=10_000)
    parser.add_argument("--clone", default=os.path.expanduser(
        "~/Library/Application Support/news-briefing/natmalpuzzle"))
    args = parser.parse_args(argv)
    out_root = os.path.join(root, "data", "app_terms")
    if args.command == "status":
        doc = load(out_root, datetime.now(KST).year)
        by_cat = Counter(e.get("categoryName") for e in doc["terms"])
        print(f"비축 {len(doc['terms'])}개 · 읽은 창 {len(doc['done'])}개 · {dict(by_cat)}")
        return 0
    result = build(root, target=args.target, stop_before=args.stop_before, max_rounds=args.max_rounds,
                   publish_clone=args.clone)
    print(f"비축 +{result['added']} → {result['total']}개 · {result['stopped']} · 걸러짐 {result['rejected']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
