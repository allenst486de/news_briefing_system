"""
LLM Summarizer Orchestration
카테고리별 배치 요약(프롬프트 a) + IT 내 AI 소식 추출(프롬프트 b) +
크로스카테고리 top10 선정(프롬프트 c) + 주식 추천 근거 생성(프롬프트 d)을
담당한다. LLM 호출이 실패하면 항상 규칙기반으로 자동 폴백한다 — 이 파일이
파이프라인을 죽이는 일은 없다.
"""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORY_META
from .utils import llm_client
from .utils.llm_client import call_llm_json
from .utils.importance_analyzer import ImportanceAnalyzer, AI_SUBTYPE_LABELS
from .utils.rss_utils import clean_html, strip_title_prefix
from .utils.logger import setup_logger

logger = setup_logger()
_analyzer = ImportanceAnalyzer()

COMMON_RULES = """당신은 뉴스 요약 보조자입니다. 아래 규칙을 반드시 지키세요.

1. 절대 확인되지 않은 수치·실적·가격·출시일·미래 예측을 지어내지 마세요.
   숫자는 아래 제공된 원문(기사 제목/요약)에 실제로 등장하는 것만 사용하고,
   없으면 언급하지 마세요.
2. 당신의 사전 학습 지식(기억)에 의존해 "최근 OO가 출시되었다"와 같은 주장을
   하지 마세요. 오직 오늘 수집된 아래 제공 데이터로만 판단하세요.
3. 원문 문장을 절대 그대로 베끼지 마세요 (한국어 기사든, 번역이 필요한 외국어
   기사든 동일). 반드시 당신 자신의 표현으로 다시 서술(paraphrase)하세요.
   직역도 금지입니다 — 자연스러운 한국어로 재구성하세요. 원문이 외국어라면
   한국어로 번역하면서 재구성하세요.
4. 번역 시 의미가 모호해질 수 있는 표현은 한국어 표현 뒤에 괄호로 원어 표현을
   병기하세요. 예: "관세 유예(tariff pause)"
5. 홍보성 문구, 근거 없는 벤치마크 주장, 유료 강의/제휴링크성 내용은
   요약에서 완전히 제외하세요.
6. 반드시 지정된 JSON 형식으로만 응답하세요. 그 외 설명 문구를 절대 추가하지
   마세요.
7. 글자 수를 채우려고 내용을 늘리지 마세요. 요약 길이 기준은 '최대'이며,
   제공된 원문에 담긴 내용이 부족하면 짧게 끝내는 것이 정답입니다.
   분량을 맞추려 배경 설명·추측·일반론을 덧붙이는 것은 1번 규칙 위반입니다."""

# 카테고리 30건을 한 번에 요청하면 한국어 출력이 1.3~1.9토큰/자라 응답이
# max_tokens에 걸려 배열이 닫히기 전에 잘리고, 그러면 JSON 파싱이 실패해
# 카테고리 전체가 규칙기반으로 폴백된다(실제로 매일 8개 카테고리 전부 이랬다).
# 한 번에 8건씩 끊어 요청해 응답이 상한에 닿지 않게 한다.
CHUNK_SIZE = 8
CHUNK_MAX_TOKENS = 6144
TOP10_MAX_TOKENS = 6144

# 해외 기사는 250자 요약에 600~800자 상세 요약까지 한 호출에서 받으므로
# 기사당 출력이 3배 이상이다 — 청크를 작게 잡아야 응답이 안 잘린다.
DETAIL_CHUNK_SIZE = 3
DETAIL_MAX_TOKENS = 8192

# 카테고리마다 전용 API 키를 쓰므로 카테고리 8개를 동시에 돌린다.
# 카테고리 안쪽 청크 동시 실행은 키 하나에 몰리므로 낮게 유지한다.
CATEGORY_WORKERS = 8
CHUNK_WORKERS = 3


def _rule_based_fallback(article: NewsArticle) -> None:
    """LLM 실패 시 Phase1 규칙기반 동작으로 복귀 (번역은 생략, 원문 그대로 유지)."""
    article.summary = clean_html(article.summary)
    article.summary = strip_title_prefix(article.summary, article.title)
    article.is_important = _analyzer.analyze(article.title, article.summary)


def _summarize_chunk(category_name: str, articles: List[NewsArticle],
                      api_key: Optional[str] = None, want_detail: bool = False) -> List[NewsArticle]:
    """
    한 덩어리를 LLM 1회 호출로 처리. 반환은 남길 기사 목록.
    want_detail=True(해외 기사)면 상세 요약 페이지용 detail_summary도 같이 받는다 —
    별도 호출로 나누면 호출 수가 두 배가 되어 30분 제한에 걸린다.
    """
    listing = "\n".join(
        f"{i + 1}. [{a.source}/{getattr(a, 'language', 'ko')}] {a.title} — "
        f"{getattr(a, 'body', '') or a.summary}"
        for i, a in enumerate(articles)
    )
    detail_field = (
        " - detail_600: 600~800자의 한국어 상세 요약. 원문 전체를 번역해 옮기지 말고,\n"
        "   핵심 사실·배경·전개를 당신의 표현으로 정리할 것. 원문에 없는 내용은 쓰지 말고,\n"
        "   근거가 부족하면 짧게 끝낼 것\n"
        if want_detail else ""
    )
    detail_json = ', "detail_600": "..."' if want_detail else ""
    user_prompt = (
        f"카테고리: {category_name}\n"
        "입력은 이 카테고리의 오늘자 기사 목록입니다. 각 기사에 대해 다음을 생성하세요:\n"
        " - id: 아래 번호와 동일한 정수\n"
        " - paraphrased_title: 기사 제목을 자연스러운 한국어로 재서술 (원문이 한국어여도 그대로 베끼지 말 것)\n"
        " - summary_250: 최대 250자의 한국어 요약. 제공된 원문에 있는 내용만으로 쓰고,\n"
        "   내용이 부족하면 짧게 끝낼 것 (분량을 채우려고 지어내지 말 것)\n"
        f"{detail_field}"
        " - is_important: 이 기사가 오늘 이 카테고리에서 특히 중요한 뉴스인지 (true/false)\n"
        " - exclude: 홍보/유료강의/근거없는 벤치마크 등으로 제외해야 하면 true, 아니면 false\n\n"
        "반드시 아래 JSON 배열 형식으로만 응답하세요:\n"
        '[{"id": 1, "paraphrased_title": "...", "summary_250": "..."'
        f'{detail_json}, "is_important": false, "exclude": false}}]\n\n'
        f"기사 목록:\n{listing}"
    )

    max_tokens = DETAIL_MAX_TOKENS if want_detail else CHUNK_MAX_TOKENS
    result = call_llm_json(COMMON_RULES, user_prompt, max_tokens=max_tokens, api_key=api_key)
    if not isinstance(result, list):
        for article in articles:
            _rule_based_fallback(article)
        return list(articles)

    by_id = {}
    for item in result:
        try:
            by_id[int(item["id"])] = item
        except (KeyError, TypeError, ValueError):
            continue

    kept = []
    for i, article in enumerate(articles):
        item = by_id.get(i + 1)
        if item is None:
            _rule_based_fallback(article)
            kept.append(article)
            continue

        if item.get("exclude"):
            continue

        new_title = (item.get("paraphrased_title") or "").strip()
        new_summary = (item.get("summary_250") or "").strip()
        new_summary = strip_title_prefix(new_summary, new_title)
        if not new_title or not new_summary:
            _rule_based_fallback(article)
            kept.append(article)
            continue

        if getattr(article, "language", "ko") == "en":
            article.original_title = article.title
            article.original_summary = clean_html(article.summary)

        article.title = new_title
        article.summary = new_summary
        article.is_important = bool(item.get("is_important"))
        if want_detail:
            article.detail_summary = (item.get("detail_600") or "").strip()
        kept.append(article)

    return kept


def category_api_key(category_key: str) -> Optional[str]:
    """
    카테고리 전용 키(NVIDIA_API_KEY_POLITICS 등)가 있으면 그걸 쓰고, 없으면 공용 키.
    카테고리마다 키가 다르면 rate limit이 나뉘어 8개를 동시에 돌릴 수 있다.
    """
    return os.getenv(f"NVIDIA_API_KEY_{category_key.upper()}") or os.getenv("NVIDIA_API_KEY")


def summarize_region(category_key: str, category_name: str, articles: List[NewsArticle],
                      region: str, api_key: Optional[str]) -> List[NewsArticle]:
    """
    한 카테고리·한 지역의 기사를 청크로 끊어 요약한다.
    해외 기사는 상세 요약(detail_600)까지 같은 호출에서 받아 온다 — 페이월 기사는
    원문을 못 가져오니 RSS 요약문 기준으로만 작성된다.
    한 덩어리가 실패해도 그 덩어리만 규칙기반으로 대체되고 나머지는 살아남는다.
    """
    if not articles:
        return articles

    want_detail = region == "overseas"
    size = DETAIL_CHUNK_SIZE if want_detail else CHUNK_SIZE
    chunks = [articles[i:i + size] for i in range(0, len(articles), size)]

    # 청크끼리는 서로 의존이 없으므로 병렬로 부른다. 카테고리들도 동시에 도는
    # 상황이라 카테고리 안쪽 동시 실행 수는 낮게 잡는다(키 하나당 rate limit).
    results = [None] * len(chunks)
    with ThreadPoolExecutor(max_workers=CHUNK_WORKERS) as pool:
        futures = {
            pool.submit(_summarize_chunk, category_name, c, api_key, want_detail): i
            for i, c in enumerate(chunks)
        }
        for future in as_completed(futures):
            i = futures[future]
            try:
                results[i] = future.result()
            except Exception as e:
                logger.warning(f"[{category_key}/{region}] chunk {i} failed ({e}) — rule-based fallback")
                for article in chunks[i]:
                    _rule_based_fallback(article)
                results[i] = list(chunks[i])

    # 원래 순서(중요도 정렬 전 최신순)를 유지해서 이어 붙인다
    return [article for chunk_result in results for article in chunk_result]


def resolve_keys(category_keys: List[str]) -> Dict[str, Optional[str]]:
    """
    카테고리별 키를 실제로 한 번 찔러 보고, 죽은 키는 살아있는 키로 대체한다.
    키가 8개로 늘면서 그중 하나만 잘못돼도 화면에는 '전부 실패'로만 보여
    어느 키가 문제인지 알 수 없었다. 여기서 키별 상태를 남기고,
    쓸 수 없는 키는 공용 키(또는 살아있는 아무 키)로 라우팅한다.
    """
    distinct = {}
    for key in category_keys:
        value = category_api_key(key)
        distinct.setdefault(value, []).append(key)

    common = os.getenv("NVIDIA_API_KEY")

    def probe(item):
        value, owners = item
        label = ",".join(sorted(owners))
        if value and value == common:
            label += " (공용)"
        return value, llm_client.probe_key(value, label)

    # 순차로 찌르면 NIM 콜드스타트 지연(모델 예열)이 앞선 항목에 몰려 실제로
    # 멀쩡한 키까지 느리게 응답한 것처럼 보인다 — 병렬로 찔러 한 번에 예열시킨다
    with ThreadPoolExecutor(max_workers=len(distinct) or 1) as pool:
        usable = dict(pool.map(probe, distinct.items()))

    fallback = next((v for v, ok in usable.items() if ok), None)
    resolved = {}
    for key in category_keys:
        value = category_api_key(key)
        resolved[key] = value if usable.get(value) else fallback
        if not usable.get(value) and fallback:
            logger.warning(f"[{key}] 전용 키를 쓸 수 없어 다른 키로 대체함")

    logger.info("LLM 키 점검:\n" + llm_client.key_status_report())
    # 살아있는 키가 하나뿐이면 동시 호출을 줄여야 429가 안 터진다
    llm_client.set_concurrency(sum(1 for ok in usable.values() if ok))
    return resolved


def summarize_all(buckets: Dict[str, Dict[str, List[NewsArticle]]]) -> None:
    """
    {카테고리: {지역: [기사]}} 전체를 in-place로 요약한다.
    카테고리마다 전용 API 키를 쓰므로 8개 카테고리를 동시에 돌린다 — 순차로 하면
    호출 수가 늘어난 만큼 그대로 벽시계 시간이 되어 30분 제한을 넘긴다.
    """
    keys = list(buckets.keys())
    resolved = resolve_keys(keys)

    def run(category_key):
        api_key = resolved.get(category_key) or category_api_key(category_key)
        category_name = CATEGORY_META[category_key]["name"]
        for region in ("domestic", "overseas"):
            articles = buckets[category_key].get(region) or []
            buckets[category_key][region] = summarize_region(
                category_key, category_name, articles, region, api_key
            )
        if category_key == "it":
            for region in ("domestic", "overseas"):
                extract_ai_items(buckets[category_key][region], api_key)

    keys = list(buckets.keys())
    with ThreadPoolExecutor(max_workers=min(len(keys), CATEGORY_WORKERS)) as pool:
        list(pool.map(run, keys))


def extract_ai_items(articles: List[NewsArticle], api_key: Optional[str] = None) -> None:
    """
    IT 카테고리의 이미 요약된 기사 중 AI 관련 항목에 is_ai/ai_subtype/
    ai_subtype_label을 부여한다 (in-place). LLM 실패 시 키워드 매칭으로 폴백.
    """
    if not articles:
        return

    listing = "\n".join(f"{i + 1}. {a.title} — {a.summary}" for i, a in enumerate(articles))
    user_prompt = (
        "입력은 'IT' 카테고리에서 이미 요약된 기사 목록입니다. 이 중 다음에 해당하는 "
        "기사만 골라내세요:\n"
        " - 새로운 AI 모델 출시/업데이트\n"
        " - AI 서비스 가격 정책/이용약관 변경\n"
        " - 산업 판도를 바꿀 만한 AI 관련 발표\n"
        "일반 IT 뉴스(AI와 무관한 것)는 포함하지 마세요.\n"
        "각 항목에 ai_subtype(release|pricing|policy|industry_shift)을 부여하세요.\n"
        "반드시 아래 JSON 배열 형식으로만 응답하세요. 해당 기사가 없으면 빈 배열([])을 반환하세요:\n"
        '[{"id": 1, "ai_subtype": "release"}]\n\n'
        f"기사 목록:\n{listing}"
    )

    result = call_llm_json(COMMON_RULES, user_prompt, api_key=api_key)
    if not isinstance(result, list):
        logger.warning("AI subsection extraction failed — falling back to keyword matching")
        for article in articles:
            article.is_ai = _analyzer.is_ai_related(article.title, article.summary)
        return

    ai_subtypes = {}
    for item in result:
        try:
            ai_subtypes[int(item["id"])] = item.get("ai_subtype", "release")
        except (KeyError, TypeError, ValueError):
            continue

    for i, article in enumerate(articles):
        subtype = ai_subtypes.get(i + 1)
        article.is_ai = subtype is not None
        if subtype:
            article.ai_subtype = subtype
            article.ai_subtype_label = AI_SUBTYPE_LABELS.get(subtype, subtype)


TOP10_COUNT = 10
TOP10_CANDIDATES_PER_CATEGORY = 6  # 8개 카테고리 × 6 = 48건 후보 (10건 고르기엔 충분)


def select_top10(categorized_news: Dict[str, List[NewsArticle]],
                  api_key: Optional[str] = None) -> List[Dict]:
    """
    8개 카테고리에서 이미 요약된 기사 전체 풀에서 크로스카테고리 top10을
    선정한다 (프롬프트 c). 실패 시 중요도→최신순 정렬로 대체.
    국내/해외를 따로 뽑으려면 지역별로 나눈 dict를 각각 넘긴다.
    반환: [{rank, category, category_name, link, card_headline, card_blurb}, ...]
    """
    # 8개 카테고리 × 30건 전체를 요약문까지 붙여 보내면 입력만 7만 자를 넘는다.
    # top10을 고르는 데는 카테고리별 상위 후보만으로 충분하고, 요약도 앞부분만 있으면 된다.
    flat = [
        {"category": category, "article": article}
        for category, articles in categorized_news.items()
        for article in sorted(
            articles, key=lambda a: (a.is_important, a.published), reverse=True
        )[:TOP10_CANDIDATES_PER_CATEGORY]
    ]
    if not flat:
        return []

    listing = "\n".join(
        f"{i + 1}. [{e['category']}] {e['article'].title} — {e['article'].summary[:120]} "
        f"(is_important={e['article'].is_important})"
        for i, e in enumerate(flat)
    )
    user_prompt = (
        "입력은 오늘 8개 카테고리에서 요약된 전체 기사 목록입니다. 이 중 오늘 가장 "
        "중요하고 관심도가 높을 것으로 판단되는 10건을 선정하세요 (특정 카테고리에 "
        "몰리지 않도록 다양성을 고려하되, 중요도가 최우선 기준입니다).\n"
        "각 항목에 대해:\n"
        " - id: 아래 번호와 동일한 정수\n"
        " - rank: 1~10\n"
        " - card_headline: 카드에 표시할 30자 내외의 헤드라인 (한 줄에 다 안 들어가면 2줄로 표시되니 "
        "억지로 줄이지 말고 자연스러운 문장으로 작성)\n"
        " - card_blurb: 카드에 표시할 80~100자 내외의 짧은 설명 (요약을 그대로 복사하지 말고 카드용으로 더 짧게 재구성)\n\n"
        "반드시 아래 JSON 배열 형식으로만 응답하세요:\n"
        '[{"id": 1, "rank": 1, "card_headline": "...", "card_blurb": "..."}]\n\n'
        f"전체 기사 목록:\n{listing}"
    )

    result = call_llm_json(COMMON_RULES, user_prompt, max_tokens=TOP10_MAX_TOKENS,
                            api_key=api_key)
    if isinstance(result, list) and result:
        cards = []
        for item in result:
            try:
                entry = flat[int(item["id"]) - 1]
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            article = entry["article"]
            cards.append({
                "rank": item.get("rank", len(cards) + 1),
                "category": entry["category"],
                "category_name": CATEGORY_META[entry["category"]]["name"],
                "link": article.link,
                "source": article.source,
                "card_headline": (item.get("card_headline") or article.title[:32]).strip(),
                "card_blurb": (item.get("card_blurb") or article.summary[:90]).strip(),
            })
        if cards:
            cards.sort(key=lambda c: c["rank"])
            return cards[:TOP10_COUNT]

    logger.warning("Top10 selection failed — falling back to importance+recency sort")
    flat.sort(key=lambda e: (e["article"].is_important, e["article"].published), reverse=True)
    cards = []
    for rank, entry in enumerate(flat[:TOP10_COUNT], start=1):
        article = entry["article"]
        cards.append({
            "rank": rank,
            "category": entry["category"],
            "category_name": CATEGORY_META[entry["category"]]["name"],
            "link": article.link,
            "source": article.source,
            "card_headline": article.title[:32],
            "card_blurb": article.summary[:90],
        })
    return cards


STOCK_REASON_SYSTEM_PROMPT = """당신은 투자 정보 뉴스레터의 보조 작성자입니다. 아래는 예외 규칙입니다:
이 항목에 한해서는 향후 전망/추세에 대한 서술적 예측(forward-looking reasoning)이 허용됩니다.
단, 다음은 여전히 지켜야 합니다:
- 제공된 실제 수치(가격, 등락률, 거래량 등) 외의 수치를 지어내지 마세요.
- 종목 선정 근거는 오직 제공된 데이터(가격/거래량 지표)에 기반해 서술하세요. 데이터에 없는 이유를 지어내지 마세요.
- 확정적 단정("반드시 오를 것") 대신 조건부/완곡 표현을 사용하세요.
- 이 결과는 투자 자문이 아니라는 점을 이해하고 조언조가 아닌 정보 제공조로 작성하세요.
반드시 지정된 JSON 형식으로만 응답하세요."""


def _fallback_stock_reason(horizon: str, pick: Dict) -> str:
    change = pick.get(f"{horizon}_change_pct")
    vol = pick.get("volume_ratio")
    parts = []
    if change is not None:
        parts.append(f"최근 등락률 {change:+.1f}%")
    if vol is not None:
        parts.append(f"거래량 평균 대비 {vol}배")
    return (", ".join(parts) + " 흐름을 보이고 있습니다.") if parts else "관련 데이터를 확인해 주세요."


def generate_stock_reasons(picks_by_market: Dict[str, Dict[str, List[Dict]]]) -> None:
    """
    picks_by_market: {"domestic": {"daily":[...], "weekly":[...], "monthly":[...]}, "overseas": {...}}
    각 pick dict에 'reason'을 채워 넣는다 (in-place). 종목 선정은 이미
    stock_data.py가 결정론적으로 끝냈고, 여기서는 문장만 생성한다 —
    이 프롬프트에 한해 전망성 서술이 허용된다(요구사항 명시 예외).
    """
    flat_picks = [
        (market, horizon, pick)
        for market, horizons in picks_by_market.items()
        for horizon, picks in horizons.items()
        for pick in picks
    ]
    if not flat_picks:
        return

    listing = "\n".join(
        f"{i + 1}. market={market}, horizon={horizon}, symbol={p['symbol']}, name={p['name']}, "
        f"price={p['price']}, change_pct={p.get(f'{horizon}_change_pct')}, volume_ratio={p.get('volume_ratio')}"
        for i, (market, horizon, p) in enumerate(flat_picks)
    )
    user_prompt = (
        "각 종목에 대해 reason(120자 내외, 한국어)을 생성하세요.\n"
        "반드시 아래 JSON 배열 형식으로만 응답하세요:\n"
        '[{"id": 1, "reason": "..."}]\n\n'
        f"종목 목록:\n{listing}"
    )

    result = call_llm_json(STOCK_REASON_SYSTEM_PROMPT, user_prompt,
                            api_key=category_api_key("economy"))
    reasons = {}
    if isinstance(result, list):
        for item in result:
            try:
                reasons[int(item["id"])] = (item.get("reason") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue

    for i, (market, horizon, pick) in enumerate(flat_picks):
        pick["reason"] = reasons.get(i + 1) or _fallback_stock_reason(horizon, pick)
