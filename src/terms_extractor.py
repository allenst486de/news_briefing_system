"""
시사용어 추출.

오늘 수집·요약된 기사에서 '설명이 필요한 용어'를 뽑는다. LLM의 사전 지식으로
용어를 지어내지 않고 **반드시 오늘 기사에 실제로 등장한 것만** 고른다 — 그래야
용어마다 출처 기사와 링크를 달 수 있고, 이 시스템의 환각 방지 규칙과도 맞는다.

이미 올해 실린 용어는 프롬프트 단계에서 제외 목록으로 넘겨 중복을 줄이고,
저장 단계(terms_store.append_terms)에서 한 번 더 거른다 — 모델이 제외 목록을
지키지 않는 경우가 있어 두 겹으로 막는다.
"""
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional

from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORY_META
from .summarizer import COMMON_RULES, _one_line, clean_llm_text
from .utils import llm_client
from .utils.llm_client import call_llm_json
from .utils.logger import setup_logger
from .utils.terms_store import normalize_term
from .utils.text_guard import foreign_leak

logger = setup_logger()

# 이미지 1장에 5단어 × 기본 2장. 연관 용어가 많은 날은 4장까지 늘린다.
TERMS_PER_CARD = 5
MIN_CARDS = 2
MAX_CARDS = 4
MIN_TERMS = TERMS_PER_CARD * MIN_CARDS   # 10
MAX_TERMS = TERMS_PER_CARD * MAX_CARDS   # 20

# 후보가 너무 많으면 입력이 커진다. 카테고리별 상위 기사만 후보로 쓴다.
# 8 → 6(2026-10-02): 입력이 길면 클라우드는 순간 장애(502)에 약하고, 로컬은 입력을 읽는 데만
# 2분 가까이 걸려(묶음당 119초) 제한 시간을 넘겼다. 분야당 지역별 6건이면 용어 후보로 충분하다.
CANDIDATES_PER_CATEGORY = 6
SUMMARY_CHARS = 120
TERMS_MAX_TOKENS = 8192

# 단발 호출(재시도·청크 분할 없음)이라 로컬 폴백의 기본 타임아웃(900초)을 그대로 쓰면
# 안 된다 — html_generator가 이 단계에 예약해 준 예산이 600초뿐인데, 로컬 하나가
# 정체되면 그 예산과 무관하게 15분을 혼자 붙든다(2026-10-01: 클라우드 5분 + 로컬 15분
# = 20분 만에 실패, 그날 로컬은 이 호출 하나만 잡고 있었다 — 맥 위 다른 작업과 자원을
# 다투면 더 쉽게 벌어진다). 로컬 청크 실측(277초)보다 약간 여유 있게 잡아 정상 호출은
# 대부분 통과시키면서 정체된 날은 빨리 포기하고 다음 회차로 넘긴다.
# 300 → 420(2026-10-02 실측): 두 분야 묶음 하나가 ComfyUI를 멈춘 상태에서도 156~286초 걸렸다
# (입력 읽기 119초 + 생성). 300초는 정상 호출도 반쯤 잘랐다.
TERMS_LOCAL_TIMEOUT = 420

# 제외 목록을 통째로 넣으면 프롬프트가 무한정 길어진다(연말이면 수백 개).
# 최근 것부터 이만큼만 넘기고, 나머지는 저장 단계의 중복 제거가 막는다.
_EXCLUDE_SAMPLE = 80

# 분야 묶음 — 8개 분야를 한 번에 보내면 입력이 1만2천~1만6천 토큰이다(2026-10-02 실측).
# 새벽 NVIDIA가 불안정한 날 이 한 건만 gemma 504·muse 502·deepseek 502로 통째로 실패했고,
# 같은 시각 같은 모델들이 작게 나눈 본문 요약 80건은 다 받아냈다(같은 요청을 낮에
# 다시 보내면 muse 95초·deepseek 42초에 정상 응답 — 순간 장애였다). 호출이 한 번뿐이라
# 순간 장애 하나가 그날 시사용어 전체를 날렸다. 본문 요약처럼 나눠서 부른다:
# 두 분야씩 4건을 동시에 부르고, 실패한 묶음만 한 번 더 부른다. 한 묶음이 죽어도
# 나머지는 살아남고, 요청이 작아져 로컬 모델도 제한 시간(300초) 안에 끝낼 수 있다.
CATEGORIES_PER_GROUP = 2
TERMS_PER_GROUP = (3, 5)
GROUP_WORKERS = 4
GROUP_MAX_TOKENS = 4096
# 재시도 전에 잠깐 쉰다 — 새벽 NVIDIA 순간 장애(502·504)가 지나갈 틈을 준다.
RETRY_PAUSE_SECONDS = 60


def extract_terms(buckets: Dict[str, Dict[str, List[NewsArticle]]],
                   known_terms: Optional[List[str]] = None,
                   api_key: Optional[str] = None,
                   date_str: str = '') -> List[Dict]:
    """
    {카테고리: {지역: [기사]}} 에서 시사용어를 뽑는다.
    반환: [{term, term_en, definition, category, category_name, date,
            source, link, region, detail_rel, ko_summary}, ...]
    실패하면 빈 목록 — 호출부는 시사용어 없이 그날 브리핑을 계속 진행한다.
    """
    flat = []
    for category, regions in buckets.items():
        for region, articles in regions.items():
            ranked = sorted(articles, key=lambda a: (a.is_important, a.published), reverse=True)
            for article in ranked[:CANDIDATES_PER_CATEGORY]:
                flat.append({"category": category, "region": region, "article": article})
    if not flat:
        return []

    exclude_block = ""
    if known_terms:
        sample = known_terms[:_EXCLUDE_SAMPLE]
        exclude_block = (
            "\n아래 용어는 올해 이미 다뤘으므로 **절대 다시 선정하지 마세요**:\n"
            + ", ".join(sample) + "\n"
        )

    categories = list(dict.fromkeys(e["category"] for e in flat))
    groups = [categories[i:i + CATEGORIES_PER_GROUP]
              for i in range(0, len(categories), CATEGORIES_PER_GROUP)]
    group_entries = [[e for e in flat if e["category"] in group] for group in groups]

    def run(index: int):
        return _extract_group(group_entries[index], groups[index], exclude_block, api_key)

    with ThreadPoolExecutor(max_workers=min(GROUP_WORKERS, len(groups))) as pool:
        results: List[Optional[List]] = list(pool.map(run, range(len(groups))))

    # 실패한 묶음만 한 번 더 — 새벽 NVIDIA 순간 장애(502·504)는 다시 부르면 대개 지나간다
    failed = [i for i, found in enumerate(results) if found is None]
    if failed:
        names = ", ".join("·".join(CATEGORY_META[c]["name"] for c in groups[i]) for i in failed)
        logger.warning(f"시사용어 {len(failed)}개 묶음 실패({names}) — {RETRY_PAUSE_SECONDS}초 뒤 한 번 더 시도")
        time.sleep(RETRY_PAUSE_SECONDS)
        # 1차에서 묶음 4개가 같은 모델로 동시에 실패하면 모델별 차단기가 열려(연속 3회 실패 → 10분)
        # 재시도가 클라우드를 아예 건너뛰고 로컬로만 간다. 시사용어는 이 실행의 마지막 LLM
        # 호출이라 차단기를 초기화해도 다른 단계에 영향이 없다.
        llm_client.reset_model_health()
        with ThreadPoolExecutor(max_workers=min(GROUP_WORKERS, len(failed))) as pool:
            for index, found in zip(failed, pool.map(run, failed)):
                results[index] = found

    if all(found is None for found in results):
        logger.warning("시사용어 추출 실패 — 오늘은 시사용어 없이 진행")
        return []
    still_failed = [i for i, found in enumerate(results) if found is None]
    if still_failed:
        names = ", ".join("·".join(CATEGORY_META[c]["name"] for c in groups[i]) for i in still_failed)
        logger.warning(f"시사용어 일부 묶음은 끝내 실패({names}) — 나머지 분야로 진행")

    # 묶음을 번갈아 섞는다 — 앞에서부터 5개씩 카드가 되므로 한 장이 한 분야로 몰리지 않게
    picked = []
    queues = [list(found or []) for found in results]
    while any(queues):
        for queue in queues:
            if queue:
                picked.append(queue.pop(0))

    known_keys = {normalize_term(t) for t in (known_terms or [])}
    seen = set()
    terms = []
    for entry, item in picked:
        term = clean_llm_text(item.get("term"))
        definition = clean_llm_text(item.get("definition"))
        if not term or not definition:
            continue
        article = entry["article"]
        if foreign_leak(f"{term} {definition}", f"{article.title} {article.summary}"):
            continue            # 대체 모델이 중국어 등을 섞어 쓴 뜻풀이

        key = normalize_term(term)
        # 모델이 제외 목록을 무시하는 경우가 있어 여기서 한 번 더 막는다
        if not key or key in seen or key in known_keys:
            continue
        seen.add(key)

        category = entry["category"]
        terms.append({
            "term": term,
            "definition": definition,
            "category": category,
            "category_name": CATEGORY_META[category]["name"],
            "date": date_str,
            "source": article.source,
            "link": article.link,
            "region": entry["region"],
            # 해외 기사는 원문이 유료라 못 여는 경우가 있어 한국어 상세 요약을 함께 건다
            "detail_rel": getattr(article, "detail_rel", ""),
            "ko_summary": _one_line(article.summary)[:200] if entry["region"] == "overseas" else "",
        })
        if len(terms) >= MAX_TERMS:
            break

    terms = _drop_names(terms)

    # 이미지는 5개 단위로 채운다 — 12개면 2장(10개)만 쓰고 2개는 다음으로 넘기지 않고 버린다.
    # 카드가 반쯤 빈 채로 나가는 것보다 낫다.
    # 기본은 2장(10개)이지만, 걸러내고 5~9개가 남은 날은 1장이라도 보낸다 — 예전에는 10개가
    # 안 되면 그날 시사용어를 통째로 버렸다. 5개도 안 되면 카드가 반쯤 비므로 건너뛴다.
    usable = (len(terms) // TERMS_PER_CARD) * TERMS_PER_CARD
    if usable < TERMS_PER_CARD:
        logger.warning(f"시사용어 {len(terms)}개 — 카드 1장도 못 채워 건너뛴다")
        return []
    if usable < MIN_TERMS:
        logger.warning(f"시사용어 {len(terms)}개 — 기본 {MIN_CARDS}장 대신 {usable // TERMS_PER_CARD}장만")

    logger.info(f"시사용어 {usable}개 추출 (카드 {usable // TERMS_PER_CARD}장)")
    return terms[:usable]


def _extract_group(entries: List[Dict], group: List[str], exclude_block: str,
                   api_key: Optional[str]) -> Optional[List]:
    """
    한 묶음(두 분야)에서 용어를 뽑는다. 반환은 [(후보 entry, 모델 응답 항목)].
    호출이 실패하면 None(재시도 대상), 응답은 왔는데 고를 게 없으면 빈 목록.
    """
    if not entries:
        return []
    names = "·".join(CATEGORY_META[c]["name"] for c in group)
    low, high = TERMS_PER_GROUP
    listing = "\n".join(
        f"{i + 1}. [{e['category']}] {_one_line(e['article'].title)} — "
        f"{_one_line(e['article'].summary)[:SUMMARY_CHARS]}"
        for i, e in enumerate(entries)
    )
    user_prompt = (
        f"입력은 오늘 수집·요약된 {names} 분야 기사 목록입니다. 이 중에서 일반 독자가 뜻을 모르면 "
        "기사를 이해하기 어려운 **시사용어**를 골라 설명하세요.\n\n"
        f"{low}개 이상 {high}개 이하로 선정하되, 다음을 지키세요:\n"
        " - 반드시 **아래 기사 목록에 실제로 등장한 용어만** 고를 것. "
        "기사에 없는 용어를 당신의 지식에서 가져오지 마세요\n"
        " - 목록에 있는 분야에서 고루 고를 것\n"
        " - 너무 당연한 일반 단어(예: 대통령, 회사, 학교)는 제외\n"
        " - 인명·지명 자체는 용어가 아니므로 제외 (제도·현상·기술·정책 개념을 고를 것)\n"
        f"{exclude_block}"
        "\n각 용어에 대해 다음을 생성하세요:\n"
        " - id: 그 용어가 등장한 기사의 아래 번호(정수). 반드시 실제 등장한 기사여야 함\n"
        " - term: 용어 (한국어. 원어가 있으면 괄호로 병기, 예: 이그젬션(Exemption))\n"
        " - 특정 정부·회사가 이번에 만든 사업·시스템·제품 이름(예: 'OO 프로그램', 'OO 데이터베이스')은 "
        "제외. 다른 기사에서도 쓰이는 일반 용어만 고를 것\n"
        " - definition: 80~120자의 간결한 뜻풀이. 먼저 **용어의 일반적인 뜻**을 쓰고, "
        "필요하면 오늘 기사에서 왜 나왔는지를 한 구절만 덧붙일 것. "
        "확인되지 않은 수치·전망을 덧붙이지 말 것\n\n"
        "반드시 아래 JSON 배열 형식으로만 응답하세요:\n"
        '[{"id": 1, "term": "...", "definition": "..."}]\n\n'
        f"기사 목록:\n{listing}"
    )
    result = call_llm_json(COMMON_RULES, user_prompt, max_tokens=GROUP_MAX_TOKENS,
                           api_key=api_key, local_timeout=TERMS_LOCAL_TIMEOUT)
    if not isinstance(result, list):
        return None
    pairs = []
    for item in result:
        if not isinstance(item, dict):
            continue
        try:
            entry = entries[int(item["id"]) - 1]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        pairs.append((entry, item))
    return pairs


def _drop_names(terms: List[Dict]) -> List[Dict]:
    """
    나라·지명·작품·기업 이름을 뺀다 — 프롬프트로 빼라고 해도 '호르무즈 해협' 같은 지명이 섞였다(9/26).
    낱말퍼즐 앱용 용어와 같은 기준(위키데이터 종류)을 쓴다. 위키백과에 물어볼 수 없으면
    그대로 둔다 — 시사용어 때문에 브리핑이 멈추면 안 된다.
    """
    import re
    from .app_terms import wiki
    heads = {t["term"]: re.sub(r"\s*[\(（].*?[\)）]\s*", "", t["term"]).strip() or t["term"] for t in terms}
    try:
        found = wiki.lookup(heads.values())
    except Exception as error:
        logger.warning(f"시사용어 이름 확인 실패({error}) — 거르지 않고 진행")
        return terms
    kept = [t for t in terms if not found.get(heads[t["term"]], {}).get("entity")]
    dropped = [t["term"] for t in terms if t not in kept]
    if dropped:
        logger.info(f"시사용어에서 이름(지명·기관명 등) 제외: {', '.join(dropped)}")
    return kept
