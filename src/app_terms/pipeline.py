"""
앱용 시사 용어 채우기 — 한 회차의 흐름.

  1. 오늘 파일에 목표 개수(TARGET)가 이미 있으면 아무것도 부르지 않고 끝낸다.
  2. 후보를 모은다. 싼 것부터 쓴다.
       a. 맥 브리핑이 오늘 뽑은 용어(data/terms/YYYY.json) — 용어 이름만 가져온다. 호출 0번.
       b. 맥이 올린 오늘 기사 목록(data/raw/YYYY/MM/DD.json) — 분야별 작은 호출로 용어만 고른다.
       c. b 가 없으면(맥이 멈춘 날) RSS 제목을 직접 모아 b 처럼 고른다.
     고른 용어가 그 기사 제목·요약에 실제로 있는지 코드로 확인한다(모델이 지어낸 말 차단).
  3. 올해 이미 실은 용어를 뺀다.
  4. 위키백과로 확인한다 — 문서 있음 · 동음이의 아님 · 사람 아님.
  5. 뜻풀이를 쓴다. 기사는 보여 주지 않고 용어 이름·분야·위키백과 문서 제목만 준다.
     그래서 뜻풀이에 기사 내용이 섞이지 않는다(언론사 RSS 는 상업 이용 금지, 앱은 상업용).
  6. 다섯 개 묶음마다 바로 저장한다. 중간에 끊겨도 된 만큼은 남고, 다음 회차가 나머지를 채운다.

목표는 하루 10개다. 앱은 하루 5개를 싣고, 남는 것은 NVIDIA 가 하루 종일 실패한 날
대신 꺼내 쓰는 비축분이 된다.
"""
import json
import os
import re
import time
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import date as Date
from datetime import datetime, timedelta, timezone
from datetime import time as dtime
from typing import Callable, Dict, List, Optional, Tuple

from ..collectors.sources import CATEGORIES, CATEGORY_META
from ..utils.llm_client import _salvage_array, _try_parse
from ..utils.logger import setup_logger
from ..utils.terms_store import normalize_term
from . import nim, store, wiki

logger = setup_logger()

KST = timezone(timedelta(hours=9))

TARGET = 10
MEANING_BATCH = 10           # 한 호출에 열 개 — NVIDIA 대기열에서 기다리는 횟수를 줄인다
JOB_BUDGET_SECONDS = 1500    # 대기열(최대 300초)과 대체 모델까지 기다릴 여유
DISCOVERY_WORKERS = 4        # 분야별 고르기 호출을 동시에 몇 개까지
MEANING_WORKERS = 2

DISCOVERY_ARTICLES = 12      # 분야당 보여 줄 기사 수 — 입력을 작게 해야 응답이 빨리 온다
DISCOVERY_TERMS = 3          # 분야당 고를 용어 수
EXCLUDE_SAMPLE = 80          # 프롬프트에 넣는 '올해 이미 실은 용어' 수 (나머지는 코드가 막는다)

MEANING_MIN, MEANING_MAX = 30, 140

RSS_MAX_AGE_DAYS = 2
RSS_TIME_LIMIT = 150

# 앱은 매일 오전 8시(KST)에 그날 용어를 연다. 예약 실행은 그 전에 오늘 몫을 끝내야 한다.
#   TODAY_CUTOFF    이 시각이 지나면 오늘 몫의 새 호출을 시작하지 않는다. 호출 하나가 늘어져도
#                   (최대 330초) 커밋까지 8시 전에 끝나게 20분 여유를 둔다.
#   RSS_NOT_BEFORE  이 시각 전에는 RSS 로 대신 모으지 않고 맥이 올릴 기사 목록을 기다린다
#                   (맥 브리핑은 늦어도 05:40 에 끝난다).
APP_OPENS_AT = dtime(8, 0)
TODAY_CUTOFF = dtime(7, 40)
RSS_NOT_BEFORE = dtime(6, 40)

VIA_LABELS = {"news_terms": "브리핑 용어", "raw": "기사 목록", "rss": "RSS 제목"}
REJECT_LABELS = {
    "duplicate": "올해 중복", "not_in_article": "기사에 없는 말", "no_wiki": "위키백과 문서 없음",
    "disambiguation": "동음이의 문서", "person": "사람 문서", "entity": "나라·지명·단체·작품 문서",
    "no_meaning": "뜻풀이 실패",
}

DISCOVERY_SYSTEM = """당신은 시사 용어 사전의 편집자입니다. 기사 목록에서 독자가 뜻을 알아야 할 용어를 고릅니다.
- 반드시 목록에 실제로 쓰인 표기 그대로 고릅니다. 목록에 없는 말을 만들지 않습니다.
- 제도·정책·경제 현상·기술·과학 개념을 고릅니다.
- 사람 이름, 지명, 나라 이름, 회사·브랜드·단체 이름, 작품 제목은 고르지 않습니다.
- 대통령·회사·학교처럼 누구나 아는 일반 단어는 고르지 않습니다.
- 긴 용어의 일부만 떼어 내지 않습니다. 기사에 '비례대표'라고 쓰였으면 '비례'가 아니라 '비례대표'입니다.
- 반드시 JSON 배열만 출력합니다. 설명 문구를 붙이지 않습니다."""

MEANING_SYSTEM = """당신은 한국어 사전 편찬자입니다. 용어의 일반적인 뜻을 풀이하고 분야를 정합니다.
1. 누구에게나 늘 참인 일반적인 뜻만 씁니다. 특정 사건·기사·인물·회사·날짜·수치는 쓰지 않습니다.
2. '최근', '올해', '이번' 같은 시점 표현을 쓰지 않습니다.
3. 한두 문장, 50~100자로 씁니다. 문장은 반드시 '~을 말한다', '~을 뜻한다', '~이다'처럼 한다체로 끝냅니다.
   '~입니다', '~합니다' 같은 존댓말로 끝내지 않습니다.
4. 영어에서 온 말이면 무엇의 줄임말이나 합성어인지 짧게 밝혀도 좋습니다.
5. 함께 적힌 '기사 분야'에서 그 용어가 쓰이는 뜻으로 풀이합니다. 같은 말이 분야마다 뜻이 다르면
   기사 분야의 뜻을 따릅니다. 예: 기사 분야가 IT인 'Distillation'은 화학의 증류가 아니라
   인공지능 모델의 지식 증류입니다.
   위키백과 문서가 그 분야의 뜻과 다른 개념을 가리키면(예: 위 Distillation에 문서가 '증류') 또는
   뜻을 확실히 모르면 meaning 을 빈 문자열로 둡니다. 문서 링크와 풀이가 어긋나면 안 되기 때문입니다.
   추측하지 않습니다.
6. category 는 용어 자체가 속한 분야를 politics·economy·society·life·culture·it·science·world 중
   하나로 고르고, 어디에도 맞지 않으면 other 로 둡니다. 기사 분야는 뜻을 고르는 데 쓰고,
   category 는 용어 자체로 정합니다(선거 기사에 나온 인플레이션은 economy, 벤처캐피털은 economy).
   예: 장치·소프트웨어·인터넷 기술은 it.
7. 반드시 JSON 배열만 출력합니다. 설명 문구를 붙이지 않습니다.
예시 출력: [{"n": 1, "meaning": "물가가 전반적으로 오르고 돈의 가치가 떨어지는 현상을 말한다.", "category": "economy"}]"""

_PAREN = re.compile(r"^\s*(.+?)\s*[\(（]\s*([^)）]+?)\s*[\)）]\s*$")
_LATIN = re.compile(r"[A-Za-z]")
_SQUASH = re.compile(r"[^0-9A-Za-z가-힣]+")
_TIME_WORDS = re.compile(
    r"최근|요즘|올해|지난해|작년|이번|오늘(?!날)|어제|내일|지난달|이달|\d{4}년|\d{1,2}월\s*\d{1,2}일")
_POLITE = re.compile(r"(니다|세요|어요|아요|해요)[.!]?$")


# ── 글자 다루기 ───────────────────────────────────────────────────────────

def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def clean_text(value) -> str:
    return one_line(value).strip("\"'“”‘’")


def split_term(raw: str) -> Tuple[str, str]:
    """표제를 (표제, 한글 읽기) 로 나눈다. 앱은 영어에서 온 말의 원어를 표제로 쓴다.

    "인플레이션(Inflation)" → ("Inflation", "인플레이션")
    "사자성어(四字成語)"     → ("사자성어", "")
    """
    raw = one_line(raw)
    match = _PAREN.match(raw)
    if not match:
        return raw, ""
    outside, inside = match.group(1).strip(), match.group(2).strip()
    if _LATIN.search(inside) and not _LATIN.search(outside):
        return inside, outside
    return outside, ""


def tidy_headword(head: str) -> str:
    """소문자로만 온 영어 표제는 단어 첫 글자를 대문자로 — 기본 목록(Supply Chain 등)과 맞춘다.
    IPO·Connectome 처럼 대문자가 섞여 있으면 그대로 둔다."""
    if _LATIN.search(head) and head == head.lower():
        return " ".join(word[:1].upper() + word[1:] for word in head.split(" "))
    return head


def _squash(text: str) -> str:
    return _SQUASH.sub("", text or "").lower()


def appears_in(raw_term: str, text: str) -> bool:
    """용어(괄호 안팎 중 하나)가 기사 글에 실제로 있는가. 띄어쓰기·문장부호는 무시한다."""
    match = _PAREN.match(raw_term or "")
    parts = [match.group(1), match.group(2)] if match else [raw_term]
    haystack = _squash(text)
    return any(len(_squash(part)) >= 2 and _squash(part) in haystack for part in parts)


def valid_meaning(value) -> Optional[str]:
    """앱에 실을 만한 뜻풀이면 다듬어 돌려주고, 아니면 None.

    시점 표현이 들어 있으면 기사 맥락이 섞였다는 신호라 버린다.
    """
    text = clean_text(value)
    if not MEANING_MIN <= len(text) <= MEANING_MAX:
        return None
    if _TIME_WORDS.search(text) or "http" in text.lower():
        return None
    if _POLITE.search(text):        # 앱의 다른 해설과 문체를 맞춘다(한다체)
        return None
    return text


def _json_list(raw: Optional[str]) -> List[Dict]:
    parsed = _try_parse(raw)
    if isinstance(parsed, dict):        # {"terms": [...]} 처럼 감싸 오는 경우
        parsed = next((v for v in parsed.values() if isinstance(v, list)), None)
    if not isinstance(parsed, list):
        parsed = _salvage_array(raw or "") or []   # max_tokens 에 잘린 응답에서 완성된 것만
    return [item for item in parsed if isinstance(item, dict)]


def _reply(value) -> Tuple[Optional[str], Optional[str]]:
    """chat 이 (본문, 모델) 을 주든 본문만 주든 같게 다룬다."""
    if isinstance(value, tuple):
        return value[0], value[1]
    return value, None


# 8개 분야 어디에도 들지 않는 용어 — 앱은 "기타" 칩으로 보여 준다
OTHER_CATEGORY = "other"


def _category_name(category: str) -> str:
    if category == OTHER_CATEGORY:
        return "기타"
    return CATEGORY_META.get(category, {}).get("name", "")


def interleave(candidates: List[Dict]) -> List[Dict]:
    """분야별로 번갈아 세운다 — 앞에서부터 저장되므로 한 분야로 몰리지 않게."""
    groups: "OrderedDict[str, List[Dict]]" = OrderedDict()
    for candidate in candidates:
        groups.setdefault(candidate.get("category", ""), []).append(candidate)
    result = []
    while any(groups.values()):
        for items in groups.values():
            if items:
                result.append(items.pop(0))
    return result


# ── 후보 모으기 ───────────────────────────────────────────────────────────

def news_term_candidates(repo_root: str, day: Date) -> List[Dict]:
    """맥 브리핑이 오늘 뽑은 용어. 뜻풀이·기사 링크는 버리고 이름과 분야만 쓴다."""
    path = os.path.join(repo_root, "data", "terms", f"{day.year}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except (OSError, ValueError):
        return []
    return [{"term": e["term"], "category": e.get("category", "")}
            for e in entries if isinstance(entries, list)
            if isinstance(e, dict) and e.get("term") and e.get("date") == day.isoformat()]


def raw_path(repo_root: str, day: Date) -> str:
    return os.path.join(repo_root, "data", "raw", f"{day:%Y}", f"{day:%m}", f"{day:%d}.json")


def articles_from_raw(path: str) -> Dict[str, List[Dict]]:
    """맥이 올린 기사 목록을 분야별 {title, summary} 로. 중요 기사를 앞에 둔다."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    result = {}
    for category, regions in (data.get("categories") or {}).items():
        items = []
        for articles in (regions or {}).values():
            for article in articles or []:
                if article.get("title"):
                    items.append({
                        "title": article["title"],
                        "summary": article.get("summary", ""),
                        "important": str(article.get("is_important")).lower() == "true",
                    })
        items.sort(key=lambda a: a["important"], reverse=True)
        result[category] = items[:DISCOVERY_ARTICLES]
    return result


def articles_from_rss(time_limit: int = RSS_TIME_LIMIT) -> Dict[str, List[Dict]]:
    """맥이 멈춘 날의 대안 — RSS 제목·설명만 모은다. 본문·요약·LLM 없이."""
    from ..collectors.rss_collector import RSSCollector
    from ..collectors.sources import SOURCES

    cutoff = datetime.now(timezone.utc) - timedelta(days=RSS_MAX_AGE_DAYS)
    jobs = [(source, category) for source in SOURCES for category in source.get("feeds", {})]
    collected: Dict[str, List] = {category: [] for category in CATEGORIES}

    def fetch(job):
        source, category = job
        collector = RSSCollector(source["id"], source["name"], source["feeds"],
                                 source.get("language", "ko"), source.get("via", ""))
        try:
            return category, collector.collect(category, limit=8)
        except Exception as error:
            logger.warning(f"[{source['id']}] RSS 실패 {category}: {error}")
            return category, []

    pool = ThreadPoolExecutor(max_workers=8)
    try:
        futures = [pool.submit(fetch, job) for job in jobs]
        for future in as_completed(futures, timeout=time_limit):
            category, articles = future.result()
            for article in articles:
                if not article.date_is_approximate and article.published < cutoff:
                    continue
                collected.setdefault(category, []).append(article)
    except FuturesTimeout:
        logger.warning(f"RSS 수집 {time_limit}초 초과 — 모은 만큼만 쓴다")
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    result = {}
    for category, articles in collected.items():
        articles.sort(key=lambda a: a.published, reverse=True)
        seen, items = set(), []
        for article in articles:
            key = _squash(article.title)
            if key and key not in seen:
                seen.add(key)
                items.append({"title": article.title, "summary": article.summary or "",
                              "important": False})
        result[category] = items[:DISCOVERY_ARTICLES]
    return result


def discover(articles_by_category: Dict[str, List[Dict]], *, pool, chat, deadline: float,
             exclude_names: List[str], rejected: Counter,
             clock: Callable[[], float] = time.monotonic) -> List[Dict]:
    """분야마다 작은 호출 한 번으로 용어만 고른다. 분야끼리는 동시에 부른다
    — NVIDIA 대기열이 길면 차례대로 부를 경우 분야 수만큼 기다린다."""
    exclude_block = ""
    if exclude_names:
        exclude_block = "이미 실은 용어이니 고르지 마세요: " + ", ".join(exclude_names) + "\n"

    jobs = []
    for category in CATEGORIES:
        articles = articles_by_category.get(category) or []
        if not articles:
            continue
        listing = "\n".join(f"{i}. {one_line(a['title'])} — {one_line(a['summary'])[:160]}"
                            for i, a in enumerate(articles, 1))
        user_prompt = (
            f"분야: {_category_name(category)}\n"
            f"아래 기사 목록에서 독자가 뜻을 알면 기사를 더 잘 이해할 수 있는 시사 용어를 "
            f"최대 {DISCOVERY_TERMS}개 고르세요.\n"
            "영어 등 원어가 기사에 함께 쓰였으면 '한국어(원어)' 형태로 적으세요.\n"
            f"{exclude_block}"
            '형식: [{"id": 기사번호, "term": "용어"}]\n\n'
            f"기사 목록:\n{listing}"
        )
        jobs.append((category, articles, user_prompt))
    if not jobs or clock() >= deadline:
        return []

    def ask(job):
        return _reply(chat(pool, DISCOVERY_SYSTEM, job[2], max_tokens=400, temperature=0.2,
                           deadline=deadline))[0]

    with ThreadPoolExecutor(max_workers=min(len(jobs), DISCOVERY_WORKERS)) as workers:
        replies = list(workers.map(ask, jobs))

    found: List[Dict] = []
    for (category, articles, _), raw in zip(jobs, replies):
        for item in _json_list(raw)[:DISCOVERY_TERMS]:
            try:
                index = int(item.get("id"))
            except (TypeError, ValueError):
                continue
            term = clean_text(item.get("term"))
            if not term or not 1 <= index <= len(articles):
                continue
            article = articles[index - 1]
            if not appears_in(term, f"{article['title']} {article['summary']}"):
                rejected["not_in_article"] += 1
                continue
            found.append({"term": term, "category": category})
    return found


# ── 뜻풀이 ────────────────────────────────────────────────────────────────

def write_meanings(batch: List[Dict], *, pool, chat,
                   deadline: float) -> Dict[int, Tuple[str, Optional[str], Optional[str]]]:
    """{묶음 안 번호: (뜻풀이, 용어 분야, 쓴 모델)}. 기사 글은 넘기지 않는다."""
    lines = []
    for number, candidate in enumerate(batch, 1):
        label = candidate["head"] + (f" ({candidate['reading']})" if candidate["reading"] else "")
        category = _category_name(candidate.get("category", "")) or "모름"
        lines.append(f"{number}. {label} · 기사 분야: {category} · 위키백과 문서: {candidate['wiki']['title']}")
    user_prompt = ("아래 용어의 뜻을 풀이하세요.\n\n" + "\n".join(lines)
                   + '\n\n형식: [{"n": 1, "meaning": "...", "category": "economy"}]')
    raw, model = _reply(chat(pool, MEANING_SYSTEM, user_prompt, max_tokens=1500, temperature=0.2,
                             deadline=deadline))
    meanings = {}
    for item in _json_list(raw):
        try:
            number = int(item.get("n"))
        except (TypeError, ValueError):
            continue
        text = valid_meaning(item.get("meaning"))
        concept = str(item.get("category") or "").strip().lower()
        if text and 1 <= number <= len(batch):
            known = concept in CATEGORIES or concept == OTHER_CATEGORY
            meanings[number] = (text, concept if known else None, model)
    return meanings


# ── 한 회차 ───────────────────────────────────────────────────────────────

def plan_run(day: Date, now: datetime, budget: int,
             explicit_date: bool = False) -> Tuple[int, bool, str]:
    """(이번 회차에 쓸 초, RSS 허용 여부, 건너뛸 이유).

    예약 실행(날짜를 적지 않음)은 오늘 몫을 TODAY_CUTOFF 전에 끝낸다.
    날짜를 직접 적은 실행은 밀린 날을 손으로 채우는 것이라 마감이 없다.
    """
    if explicit_date or day != now.date():
        return budget, True, ""
    cutoff = datetime.combine(day, TODAY_CUTOFF, tzinfo=now.tzinfo)
    remaining = int((cutoff - now).total_seconds())
    if remaining <= 0:
        return 0, False, (f"오늘 몫 마감({TODAY_CUTOFF:%H:%M}) 지남 — 앱은 {APP_OPENS_AT:%H:%M}에 "
                          "비축분을 연다. 그래도 채우려면 날짜를 적어 실행")
    return min(budget, remaining), now.time() >= RSS_NOT_BEFORE, ""



def fill_day(day: Date, *, repo_root: str, out_root: Optional[str] = None,
             target: int = TARGET, budget: int = JOB_BUDGET_SECONDS, allow_rss: bool = True,
             pool=None, chat=None, wiki_lookup=None, rss_loader=None,
             clock: Callable[[], float] = time.monotonic) -> Dict:
    out_root = out_root or os.path.join(repo_root, "data", "app_terms")
    chat = chat or nim.chat_with_model
    wiki_lookup = wiki_lookup or wiki.lookup
    # RSS 수집도 마감을 넘지 않게 남은 시간의 절반까지만 쓴다
    rss_loader = rss_loader or (lambda: articles_from_rss(
        time_limit=max(10, min(RSS_TIME_LIMIT, int(deadline - clock()) // 2))))
    nim.reset_stats()
    deadline = clock() + budget

    doc = store.load_day(out_root, day)
    result = {"date": day.isoformat(), "before": len(doc["terms"]), "after": len(doc["terms"]),
              "added": 0, "via": [], "rejected": Counter(), "stopped": "",
              "path": store.day_path(out_root, day)}

    if len(doc["terms"]) >= target:
        result["stopped"] = f"이미 {len(doc['terms'])}개 — 할 일 없음"
        return _finish(result)

    pool = pool if pool is not None else nim.KeyPool.from_env()
    if not len(pool):
        result["stopped"] = "NVIDIA 키 없음"
        return _finish(result)

    year_terms = store.load_year_terms(out_root, day.year)
    known = set()
    for entry in year_terms:
        known |= store.term_keys(entry)
    run = {"at": datetime.now(KST).isoformat(timespec="seconds"), "added": 0, "via": []}

    def remaining() -> int:
        return target - len(doc["terms"])

    def exclude_names() -> List[str]:
        # 이번 회차에 방금 실은 것까지 넣는다 — 고르기 호출이 그걸 다시 고르지 않게
        names = [e.get("reading") or e.get("term") for e in reversed(doc["terms"])]
        names += [e.get("reading") or e.get("term") for e in reversed(year_terms)]
        return [name for name in dict.fromkeys(names) if name][:EXCLUDE_SAMPLE]

    def from_articles(load_articles):
        def load():
            return discover(load_articles(), pool=pool, chat=chat, deadline=deadline,
                            exclude_names=exclude_names(), rejected=result["rejected"],
                            clock=clock)
        return load

    sources = [("news_terms", lambda: news_term_candidates(repo_root, day))]
    today_raw = raw_path(repo_root, day)
    if os.path.exists(today_raw):
        sources.append(("raw", from_articles(lambda: articles_from_raw(today_raw))))
    elif allow_rss:
        sources.append(("rss", from_articles(rss_loader)))

    tried = set()
    for via, load in sources:
        if remaining() <= 0 or clock() >= deadline:
            break
        fresh = []
        for candidate in load():
            original, reading = split_term(candidate["term"])
            head = tidy_headword(original)
            keys = {normalize_term(head), normalize_term(reading)} - {""}
            if not keys:
                continue
            if keys & (known | tried):
                result["rejected"]["duplicate"] += 1
                continue
            tried |= keys
            # 위키백과는 원래 표기로 찾는다 — 제목은 첫 글자 뒤로 대소문자를 가린다
            fresh.append({**candidate, "head": head, "reading": reading, "lookup": original})
        if not fresh:
            continue
        result["via"].append(via)
        _admit(fresh, via=via, day=day, doc=doc, out_root=out_root, known=known, target=target,
               pool=pool, chat=chat, wiki_lookup=wiki_lookup, deadline=deadline, clock=clock,
               rejected=result["rejected"], run=run)

    result["after"] = len(doc["terms"])
    result["added"] = result["after"] - result["before"]
    if result["after"] >= target:
        result["stopped"] = "목표 달성"
    elif clock() >= deadline:
        result["stopped"] = "작업 마감 — 다음 회차에 이어서"
    else:
        result["stopped"] = "후보 소진 — 다음 회차에 다시"
    return _finish(result)


def _admit(fresh: List[Dict], *, via: str, day: Date, doc: Dict, out_root: str, known: set,
           target: int, pool, chat, wiki_lookup, deadline: float, clock, rejected: Counter,
           run: Dict) -> None:
    """위키백과 확인 → 뜻풀이 → 묶음마다 저장."""
    found = wiki_lookup([title for c in fresh for title in (c["reading"], c["lookup"]) if title])
    approved = []
    for candidate in interleave(fresh):
        info = (found.get(candidate["reading"]) if candidate["reading"] else None) \
            or found.get(candidate["lookup"])
        if not info:
            rejected["no_wiki"] += 1
            continue
        if info.get("disambiguation"):
            rejected["disambiguation"] += 1
            continue
        if info.get("person"):
            rejected["person"] += 1
            continue
        if info.get("entity"):
            rejected["entity"] += 1
            continue
        wiki_key = "wiki:" + info["title"]
        if wiki_key in known:           # 다른 이름으로 같은 문서를 가리키는 경우
            rejected["duplicate"] += 1
            continue
        known.add(wiki_key)
        approved.append({**candidate, "wiki": info})

    needed = target - len(doc["terms"])
    approved = approved[:needed + MEANING_BATCH // 2]      # 뜻풀이에 실패하는 몫만큼 여유
    batches = [approved[i:i + MEANING_BATCH] for i in range(0, len(approved), MEANING_BATCH)]
    if not batches or clock() >= deadline:
        return
    # 묶음끼리는 서로 기다릴 필요가 없다 — NVIDIA 대기열에서 동시에 차례를 기다린다
    with ThreadPoolExecutor(max_workers=min(len(batches), MEANING_WORKERS)) as workers:
        results = list(workers.map(
            lambda batch: write_meanings(batch, pool=pool, chat=chat, deadline=deadline), batches))

    for batch, meanings in zip(batches, results):
        added = 0
        for number, candidate in enumerate(batch, 1):
            if len(doc["terms"]) >= target:
                break
            meaning, concept, model = meanings.get(number, (None, None, None))
            if not meaning:
                rejected["no_meaning"] += 1
                continue
            # 색 구분은 기사 분야가 아니라 용어 자체의 분야로 — 선거 기사에 나온 '인플레이션'은 경제
            category = concept or candidate.get("category", "")
            entry = {
                "term": candidate["head"],
                "reading": candidate["reading"],
                "meaning": meaning,
                "category": category,
                "categoryName": _category_name(category),
                "wikiTitle": candidate["wiki"]["title"],
                "url": candidate["wiki"]["url"],
                "date": day.isoformat(),
                "via": via,
            }
            if model:       # 대체 모델이 쓴 뜻풀이는 나중에 골라 검토할 수 있게
                entry["model"] = model
            doc["terms"].append(entry)
            known |= store.term_keys(entry)
            added += 1
        if added:
            run["added"] += added
            if via not in run["via"]:
                run["via"].append(via)
            if not doc["runs"] or doc["runs"][-1] is not run:
                doc["runs"].append(run)
            store.save_day(out_root, day, doc)
            logger.info(f"앱 용어 +{added} ({VIA_LABELS.get(via, via)}) — 오늘 {len(doc['terms'])}개")


def _finish(result: Dict) -> Dict:
    result["rejected"] = dict(result["rejected"])
    result["llm"] = nim.stats_line()
    return result


def format_summary(result: Dict) -> str:
    lines = [f"앱용 시사 용어 {result['date']}: {result['before']}개 → {result['after']}개 "
             f"(+{result['added']})"]
    if result["via"]:
        lines.append("후보 출처: " + " → ".join(VIA_LABELS.get(v, v) for v in result["via"]))
    if result["rejected"]:
        lines.append("걸러짐: " + " · ".join(f"{REJECT_LABELS.get(k, k)} {v}"
                                           for k, v in sorted(result["rejected"].items())))
    lines.append("NVIDIA: " + result["llm"])
    lines.append("종료: " + result["stopped"])
    return "\n".join(lines)
