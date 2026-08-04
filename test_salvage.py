"""
잘린 JSON 복구 + 요약 청킹 self-check (프레임워크 없음, assert 기반).
실제 LLM API는 호출하지 않는다 — call_llm을 가짜 함수로 바꿔치기해서 검증한다.

배경: 카테고리 30건을 한 번에 요청하면 응답이 max_tokens에 걸려 배열이 닫히기 전에
잘리고, 그러면 카테고리 전체가 규칙기반으로 폴백됐다(실제로 매일 그랬다).
여기서 검증하는 건 (1) 잘린 응답에서 완성된 객체만 건져내는지 (2) 청크 단위로
끊어 호출하는지 (3) 한 청크가 죽어도 나머지는 살아남는지.
"""
import os
from datetime import datetime, timezone

from src.collectors.base_collector import NewsArticle
from src.utils import article_body, llm_client
from src import summarizer


def _article(n):
    return NewsArticle(
        title=f"제목{n}", link=f"https://example.com/{n}",
        published=datetime.now(timezone.utc), summary=f"요약{n}", source="테스트",
    )


def test_salvage_truncated_array():
    truncated = (
        '[{"id": 1, "paraphrased_title": "가", "summary_250": "내용1"},'
        '{"id": 2, "paraphrased_title": "나", "summary_250": "내용2"},'
        '{"id": 3, "paraphrased_title": "다", "summary_2'  # 여기서 잘림
    )
    items = llm_client._salvage_array(truncated)
    assert items is not None, "잘린 배열에서 아무것도 못 건졌다"
    assert len(items) == 2, f"완성된 객체 2개를 기대했는데 {len(items)}개"
    assert items[1]["summary_250"] == "내용2"


def test_salvage_ignores_braces_inside_strings():
    """요약문 안에 중괄호가 들어가도 객체 경계를 잘못 잡으면 안 된다."""
    raw = '[{"id": 1, "summary_250": "괄호 { 포함 \\" 따옴표도"}, {"id": 2, "summary_250": "끝"}]'
    items = llm_client._salvage_array(raw)
    assert len(items) == 2, f"문자열 안 중괄호에 속았다: {items}"
    assert items[0]["id"] == 1


def test_salvage_returns_none_without_array():
    assert llm_client._salvage_array("설명만 있고 JSON이 없음") is None


def test_call_llm_json_salvages_truncated(monkeypatched):
    """call_llm_json이 잘린 응답을 폐기하지 않고 건져 쓰는지."""
    result = llm_client.call_llm_json("sys", "user")
    assert isinstance(result, list) and len(result) == 2, f"복구 실패: {result}"


def test_chunking_splits_calls():
    """30건이면 CHUNK_SIZE(8) 기준으로 4번 나눠 호출해야 한다."""
    articles = [_article(i) for i in range(30)]
    calls = []

    def fake_call(system, user, **kwargs):
        # 이 청크에 몇 건이 들어왔는지 세어 그대로 응답을 만들어 준다
        count = user.count("[테스트/ko]")
        calls.append(count)
        items = ", ".join(
            f'{{"id": {i + 1}, "paraphrased_title": "재서술{i}", '
            f'"summary_250": "요약된내용{i}", "is_important": false, "exclude": false}}'
            for i in range(count)
        )
        return f"[{items}]"

    original = llm_client.call_llm
    llm_client.call_llm = fake_call
    try:
        kept = summarizer.summarize_category("world", "국제", articles)
    finally:
        llm_client.call_llm = original

    assert len(calls) == 4, f"청크 4회 호출을 기대했는데 {len(calls)}회: {calls}"
    # 청크는 병렬로 돌아 완료 순서가 매번 다르다 — 크기 구성만 확인한다
    assert sorted(calls) == [6, 8, 8, 8], f"청크 크기 분배가 이상하다: {calls}"
    assert len(kept) == 30, f"기사 30건이 유지돼야 하는데 {len(kept)}건"
    assert kept[0].title == "재서술0", "LLM 결과가 반영되지 않았다"


def test_one_bad_chunk_does_not_kill_the_rest():
    """청크 하나가 실패해도 나머지 청크는 LLM 결과를 유지해야 한다."""
    articles = [_article(i) for i in range(16)]

    def flaky_call(system, user, **kwargs):
        # 첫 청크(제목0이 들어간 덩어리)는 재프롬프트를 해도 계속 실패시킨다
        if "제목0 —" in user:
            return "완전히 망가진 응답"
        count = user.count("[테스트/ko]")
        items = ", ".join(
            f'{{"id": {i + 1}, "paraphrased_title": "재서술", '
            f'"summary_250": "요약", "is_important": false, "exclude": false}}'
            for i in range(count)
        )
        return f"[{items}]"

    original = llm_client.call_llm
    llm_client.call_llm = flaky_call
    try:
        kept = summarizer.summarize_category("world", "국제", articles)
    finally:
        llm_client.call_llm = original

    assert len(kept) == 16, f"16건이 유지돼야 하는데 {len(kept)}건"
    assert kept[0].title == "제목0", "실패한 청크는 원래 제목이 남아야 한다"
    assert kept[8].title == "재서술", "성공한 청크까지 폴백되면 안 된다"


def test_parallel_chunks_preserve_article_order():
    """
    청크를 병렬로 부르므로 완료 순서가 뒤섞인다. 결과를 완료 순서대로 이어붙이면
    기사 순서가 망가지므로, 원래 순서가 유지되는지 확인한다.
    (뒤 청크를 일부러 먼저 끝내도 순서가 지켜져야 한다.)
    """
    import time as _time
    articles = [_article(i) for i in range(24)]

    def staggered(system, user, **kwargs):
        count = user.count("[테스트/ko]")
        # 첫 청크(제목0 포함)를 일부러 가장 늦게 끝내 완료 순서를 뒤집는다
        if "제목0 —" in user:
            _time.sleep(0.25)
        items = ", ".join(
            f'{{"id": {i + 1}, "paraphrased_title": "T{i}", '
            f'"summary_250": "S{i}", "is_important": false, "exclude": false}}'
            for i in range(count)
        )
        return f"[{items}]"

    original = llm_client.call_llm
    llm_client.call_llm = staggered
    try:
        kept = summarizer.summarize_category("world", "국제", articles)
    finally:
        llm_client.call_llm = original

    assert len(kept) == 24, f"24건이 유지돼야 하는데 {len(kept)}건"
    # 각 청크 안에서 id가 1부터 다시 시작하므로 제목은 T0..T7 이 3번 반복된다
    expected = [f"T{i % summarizer.CHUNK_SIZE}" for i in range(24)]
    assert [a.title for a in kept] == expected, \
        f"병렬 실행 후 기사 순서가 뒤바뀌었다: {[a.title for a in kept][:10]}"


def test_llm_time_budget_stops_calls():
    """시간 예산을 넘기면 즉시 None을 반환해 실행이 무한정 길어지지 않아야 한다."""
    original_deadline = llm_client._deadline
    original_budget = llm_client.LLM_TIME_BUDGET_SECONDS
    called = []

    def should_not_run(*a, **k):
        called.append(1)
        return "{}"

    try:
        llm_client._deadline = None
        llm_client.LLM_TIME_BUDGET_SECONDS = -1  # 첫 호출 이후 즉시 소진
        llm_client._budget_exhausted()           # 데드라인 설정
        before = llm_client.LLM_STATS["budget"]
        assert llm_client.call_llm("sys", "user") is None, "예산 초과인데 호출이 진행됐다"
        assert llm_client.LLM_STATS["budget"] == before + 1, "예산 초과가 집계되지 않았다"
    finally:
        llm_client._deadline = original_deadline
        llm_client.LLM_TIME_BUDGET_SECONDS = original_budget


def test_body_budget_is_global_not_per_category():
    """
    본문 fetch 예산이 카테고리마다 새로 잡히면 8배가 되어 워크플로가 취소된다
    (실제 발생). 전역 데드라인이 유지되는지 확인한다.
    """
    original = article_body._deadline
    try:
        article_body._deadline = None
        article_body.enrich([])          # 첫 호출에서 데드라인 설정
        first = article_body._deadline
        assert first is not None, "첫 호출에서 데드라인이 설정되지 않았다"
        article_body.enrich([])          # 두 번째 카테고리
        assert article_body._deadline == first, "카테고리마다 예산이 초기화되고 있다"
    finally:
        article_body._deadline = original


def test_rate_limit_retry_waits_and_gives_up_cleanly():
    """
    429는 1~2초 후 재시도하면 대개 또 걸린다. Retry-After를 따르는지, 그리고
    재시도를 소진하면 network_error가 아니라 http_error(429)로 분류되는지 확인.
    한 번의 429에 대해 대기가 두 번 일어나지 않아야 한다(sleep 후 raise 하면
    except 절에서 또 sleep 하는 버그가 있었다).
    """
    import requests

    class FakeResp:
        status_code = 429
        headers = {"Retry-After": "7"}
        ok = False
        text = "rate limited"

    sleeps = []
    orig_post, orig_sleep = requests.post, llm_client.time.sleep
    orig_deadline = llm_client._deadline
    llm_client.time.sleep = lambda s: sleeps.append(s)
    requests.post = lambda *a, **k: FakeResp()
    os.environ["NVIDIA_API_KEY"] = "test-key"
    try:
        llm_client._deadline = None
        before = llm_client.LLM_STATS["http_error"]
        assert llm_client.call_llm("s", "u", retries=2) is None
        assert sleeps == [7, 7], f"Retry-After(7초)를 따라 2회만 대기해야 하는데 {sleeps}"
        assert llm_client.LLM_STATS["http_error"] == before + 1, "429가 http_error로 집계되지 않았다"
    finally:
        requests.post, llm_client.time.sleep = orig_post, orig_sleep
        llm_client._deadline = orig_deadline
        os.environ.pop("NVIDIA_API_KEY", None)


def test_retry_after_header_is_clamped():
    class R:
        def __init__(self, v): self.headers = {"Retry-After": v} if v is not None else {}
    assert llm_client._retry_after_seconds(R("3")) == 3
    assert llm_client._retry_after_seconds(R("9999")) == llm_client._RATE_LIMIT_MAX_WAIT, "과도한 대기가 제한되지 않음"
    assert llm_client._retry_after_seconds(R("Wed, 21 Oct 2026 07:28:00 GMT")) is None, "날짜 형식은 무시해야 함"
    assert llm_client._retry_after_seconds(R(None)) is None


def test_prose_score_separates_body_from_headline_list():
    """
    본문 추출이 '관련기사 헤드라인 목록'을 본문으로 착각하면 엉뚱한 요약이 나온다.
    실측값: 헤드라인 목록 0.08~0.61 / 실제 본문 0.87~4.25 → 경계 0.75.
    """
    headline_list = (
        "‘폭염’ 기저질환 없는 40대 숨졌다…하루 108명 온열질환"
        "서울·경기에 첫 ‘폭염 중대경보’…야외작업 중단 권고"
        "제주 고물상서 50대 작업자 압축기 사고로 숨져"
        "경산 아파트 방화 용의자 검거…이웃 갈등 추정"
    ) * 3
    body = (
        "더불어민주당 최고위원 후보들이 3일 첫 방송 토론회에서 맞붙었다. "
        "후보들은 당정 관계를 두고 서로 다른 해법을 제시했다. "
        "한 후보는 당이 중심을 잡아야 한다고 말했다. "
        "다른 후보는 정부와의 조율이 우선이라고 반박했다. "
    ) * 3

    assert article_body._prose_score(headline_list) < article_body._MIN_PROSE_SCORE, \
        f"헤드라인 목록이 본문으로 통과됨: {article_body._prose_score(headline_list):.2f}"
    assert article_body._prose_score(body) >= article_body._MIN_PROSE_SCORE, \
        f"실제 본문이 걸러짐: {article_body._prose_score(body):.2f}"


def test_needs_body_targets_short_and_truncated():
    class Fake:
        def __init__(self, summary):
            self.summary = summary

    assert article_body.needs_body(Fake("짧은 요약")), "짧은 요약은 본문을 받아와야 한다"
    assert article_body.needs_body(Fake("가" * 400 + "…")), "…로 잘린 요약도 본문 대상"
    assert not article_body.needs_body(Fake("가" * 400)), "충분히 긴 요약은 그대로 쓴다"


def main():
    test_salvage_truncated_array()
    test_salvage_ignores_braces_inside_strings()
    test_salvage_returns_none_without_array()

    original = llm_client.call_llm
    llm_client.call_llm = lambda s, u, **k: (
        '[{"id": 1, "v": "가"}, {"id": 2, "v": "나"}, {"id": 3, "v'
    )
    try:
        test_call_llm_json_salvages_truncated(None)
    finally:
        llm_client.call_llm = original

    test_chunking_splits_calls()
    test_one_bad_chunk_does_not_kill_the_rest()
    test_parallel_chunks_preserve_article_order()
    test_llm_time_budget_stops_calls()
    test_body_budget_is_global_not_per_category()
    test_rate_limit_retry_waits_and_gives_up_cleanly()
    test_retry_after_header_is_clamped()
    test_prose_score_separates_body_from_headline_list()
    test_needs_body_targets_short_and_truncated()
    print("OK: salvage + chunking + budget + body-extraction self-checks passed")


if __name__ == "__main__":
    main()
