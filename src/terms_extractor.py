"""
시사용어 추출.

오늘 수집·요약된 기사에서 '설명이 필요한 용어'를 뽑는다. LLM의 사전 지식으로
용어를 지어내지 않고 **반드시 오늘 기사에 실제로 등장한 것만** 고른다 — 그래야
용어마다 출처 기사와 링크를 달 수 있고, 이 시스템의 환각 방지 규칙과도 맞는다.

이미 올해 실린 용어는 프롬프트 단계에서 제외 목록으로 넘겨 중복을 줄이고,
저장 단계(terms_store.append_terms)에서 한 번 더 거른다 — 모델이 제외 목록을
지키지 않는 경우가 있어 두 겹으로 막는다.
"""
from typing import Dict, List, Optional

from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORY_META
from .summarizer import COMMON_RULES, _one_line, clean_llm_text
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
CANDIDATES_PER_CATEGORY = 8
TERMS_MAX_TOKENS = 8192

# 제외 목록을 통째로 넣으면 프롬프트가 무한정 길어진다(연말이면 수백 개).
# 최근 것부터 이만큼만 넘기고, 나머지는 저장 단계의 중복 제거가 막는다.
_EXCLUDE_SAMPLE = 120


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

    listing = "\n".join(
        f"{i + 1}. [{e['category']}] {_one_line(e['article'].title)} — "
        f"{_one_line(e['article'].summary)[:160]}"
        for i, e in enumerate(flat)
    )

    exclude_block = ""
    if known_terms:
        sample = known_terms[:_EXCLUDE_SAMPLE]
        exclude_block = (
            "\n아래 용어는 올해 이미 다뤘으므로 **절대 다시 선정하지 마세요**:\n"
            + ", ".join(sample) + "\n"
        )

    user_prompt = (
        "입력은 오늘 수집·요약된 기사 목록입니다. 이 중에서 일반 독자가 뜻을 모르면 "
        "기사를 이해하기 어려운 **시사용어**를 골라 설명하세요.\n\n"
        f"{MIN_TERMS}개 이상 {MAX_TERMS}개 이하로 선정하되, 다음을 지키세요:\n"
        " - 반드시 **아래 기사 목록에 실제로 등장한 용어만** 고를 것. "
        "기사에 없는 용어를 당신의 지식에서 가져오지 마세요\n"
        " - 특정 분야에 몰리지 않게 여러 분야에서 고를 것\n"
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

    result = call_llm_json(COMMON_RULES, user_prompt, max_tokens=TERMS_MAX_TOKENS,
                            api_key=api_key)
    if not isinstance(result, list) or not result:
        logger.warning("시사용어 추출 실패 — 오늘은 시사용어 없이 진행")
        return []

    known_keys = {normalize_term(t) for t in (known_terms or [])}
    seen = set()
    terms = []
    for item in result:
        try:
            entry = flat[int(item["id"]) - 1]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
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
