"""
LLM Summarizer Orchestration
카테고리별 배치 요약(프롬프트 a) + IT 내 AI 소식 추출(프롬프트 b) +
크로스카테고리 top10 선정(프롬프트 c) + 주식 추천 근거 생성(프롬프트 d)을
담당한다. LLM 호출이 실패하면 항상 규칙기반으로 자동 폴백한다 — 이 파일이
파이프라인을 죽이는 일은 없다.
"""
from typing import Dict, List

from .collectors.base_collector import NewsArticle
from .collectors.sources import CATEGORY_META
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
   마세요."""

CATEGORY_MAX_TOKENS = 12288  # 카테고리당 상한 30건 기준 — 20건일 때 8192로 넉넉했던 걸 비례로 올림


def _rule_based_fallback(article: NewsArticle) -> None:
    """LLM 실패 시 Phase1 규칙기반 동작으로 복귀 (번역은 생략, 원문 그대로 유지)."""
    article.summary = clean_html(article.summary)
    article.summary = strip_title_prefix(article.summary, article.title)
    article.is_important = _analyzer.analyze(article.title, article.summary)


def summarize_category(category_key: str, category_name: str, articles: List[NewsArticle]) -> List[NewsArticle]:
    """
    카테고리 기사 전체를 LLM 1회 배치 호출로 번역+재구성+250자 요약.
    실패/부분실패 시 해당 기사만 규칙기반으로 대체 — 전체 카테고리가 통으로
    죽지 않는다. exclude=true로 판정된 기사는 결과 리스트에서 제외한다.
    """
    if not articles:
        return articles

    listing = "\n".join(
        f"{i + 1}. [{a.source}/{getattr(a, 'language', 'ko')}] {a.title} — {a.summary}"
        for i, a in enumerate(articles)
    )
    user_prompt = (
        f"카테고리: {category_name}\n"
        "입력은 이 카테고리의 오늘자 기사 목록입니다. 각 기사에 대해 다음을 생성하세요:\n"
        " - id: 아래 번호와 동일한 정수\n"
        " - paraphrased_title: 기사 제목을 자연스러운 한국어로 재서술 (원문이 한국어여도 그대로 베끼지 말 것)\n"
        " - summary_250: 약 250자 분량의 한국어 요약 (제공된 제목/스니펫 근거로만 작성)\n"
        " - is_important: 이 기사가 오늘 이 카테고리에서 특히 중요한 뉴스인지 (true/false)\n"
        " - exclude: 홍보/유료강의/근거없는 벤치마크 등으로 제외해야 하면 true, 아니면 false\n\n"
        "반드시 아래 JSON 배열 형식으로만 응답하세요:\n"
        '[{"id": 1, "paraphrased_title": "...", "summary_250": "...", "is_important": false, "exclude": false}]\n\n'
        f"기사 목록:\n{listing}"
    )

    result = call_llm_json(COMMON_RULES, user_prompt, max_tokens=CATEGORY_MAX_TOKENS)
    if not isinstance(result, list):
        logger.warning(f"[{category_key}] LLM summarize failed or malformed — falling back to rule-based")
        for article in articles:
            _rule_based_fallback(article)
        return articles

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
        kept.append(article)

    return kept


def extract_ai_items(articles: List[NewsArticle]) -> None:
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

    result = call_llm_json(COMMON_RULES, user_prompt)
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


def select_top10(categorized_news: Dict[str, List[NewsArticle]]) -> List[Dict]:
    """
    8개 카테고리에서 이미 요약된 기사 전체 풀에서 크로스카테고리 top10을
    선정한다 (프롬프트 c). 실패 시 중요도→최신순 정렬로 대체.
    반환: [{rank, category, category_name, link, card_headline, card_blurb}, ...]
    """
    flat = [
        {"category": category, "article": article}
        for category, articles in categorized_news.items()
        for article in articles
    ]
    if not flat:
        return []

    listing = "\n".join(
        f"{i + 1}. [{e['category']}] {e['article'].title} — {e['article'].summary} "
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

    result = call_llm_json(COMMON_RULES, user_prompt, max_tokens=CATEGORY_MAX_TOKENS)
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

    result = call_llm_json(STOCK_REASON_SYSTEM_PROMPT, user_prompt)
    reasons = {}
    if isinstance(result, list):
        for item in result:
            try:
                reasons[int(item["id"])] = (item.get("reason") or "").strip()
            except (KeyError, TypeError, ValueError):
                continue

    for i, (market, horizon, pick) in enumerate(flat_picks):
        pick["reason"] = reasons.get(i + 1) or _fallback_stock_reason(horizon, pick)
