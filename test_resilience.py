"""
Self-check: 9/18~9/21 장애 재발 방지 장치 검증
  - 주력 모델이 응답 없으면 다음 클라우드 모델로 넘어가는가 (같은 모델 재시도 없이)
  - 연속 실패한 모델은 차단되고, 쿨다운 뒤 시험 호출 하나로 복귀하는가
  - 예산이 바닥나도 마무리 단계(Top10·시사용어)는 몫을 받는가
  - Top10에 같은 기사·같은 사건이 두 장 이상 실리지 않는가
실제 NVIDIA API·로컬 LLM 서버는 부르지 않는다(requests.post·call_local_llm 패치).

python test_resilience.py 로 실행. 실패 시 AssertionError로 즉시 중단.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests

from src.utils import llm_client
from src import summarizer
from src.collectors.base_collector import NewsArticle

GEMMA = llm_client.NVIDIA_MODEL
BACKUP = "meta/muse-glimmer-30b"
BACKUP2 = "deepseek-ai/deepseek-v4.1-flash"
LAST = "nvidia/nemotron-3-ultra-550b-a55b"


class Resp:
    def __init__(self, code, content="응답"):
        self.status_code = code
        self.ok = code == 200
        self.text = "x"
        self.headers = {}
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


class Harness:
    """모델별 반응을 정해 두고 어떤 모델이 불렸는지 기록한다."""

    def __init__(self, behaviour, local=None):
        self.behaviour = behaviour      # model -> Resp | Exception
        self.calls = []
        self.local = local
        self.local_calls = 0

    def __enter__(self):
        self._saved = (requests.post, llm_client.call_local_llm, llm_client._deadline,
                       os.environ.get("NVIDIA_API_KEY"))
        llm_client.reset_model_health()
        llm_client._deadline = None
        os.environ["NVIDIA_API_KEY"] = "test-key"

        def fake_post(url, **kw):
            model = kw["json"]["model"]
            self.calls.append(model)
            outcome = self.behaviour.get(model, Resp(200))
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        def fake_local(*a, **k):
            self.local_calls += 1
            return self.local

        requests.post = fake_post
        llm_client.call_local_llm = fake_local
        return self

    def __exit__(self, *exc):
        requests.post, llm_client.call_local_llm, llm_client._deadline, key = self._saved
        if key is None:
            os.environ.pop("NVIDIA_API_KEY", None)
        else:
            os.environ["NVIDIA_API_KEY"] = key
        llm_client.reset_model_health()


def test_stalled_primary_hands_off_to_backup_without_retrying():
    timeout = requests.exceptions.ReadTimeout("read timed out")
    with Harness({GEMMA: timeout, BACKUP: Resp(200, "백업 응답")}) as h:
        assert llm_client.call_llm("s", "u") == "백업 응답"
        # 9/18에는 막힌 모델을 180초 × 3회 기다렸다 — 이제 한 번만 부르고 넘어간다
        assert h.calls == [GEMMA, BACKUP], f"모델 호출 순서가 이상함: {h.calls}"
        assert h.local_calls == 0, "클라우드 백업이 성공했는데 로컬을 불렀다"


def test_breaker_skips_dead_model_then_probes_after_cooldown():
    timeout = requests.exceptions.ReadTimeout("read timed out")
    with Harness({GEMMA: timeout}) as h:
        for _ in range(llm_client._ModelHealth.FAIL_THRESHOLD):
            llm_client.call_llm("s", "u")
        h.calls.clear()
        llm_client.call_llm("s", "u")
        assert h.calls == [BACKUP], f"차단된 주력 모델을 또 불렀다: {h.calls}"

        # 쿨다운이 지나면 시험 호출 하나만 주력으로 보낸다 — 성공하면 복귀
        llm_client._health._state[GEMMA]["open_until"] = time.monotonic() - 1
        h.behaviour[GEMMA] = Resp(200, "주력 복귀")
        h.calls.clear()
        assert llm_client.call_llm("s", "u") == "주력 복귀"
        h.calls.clear()
        llm_client.call_llm("s", "u")
        assert h.calls == [GEMMA], f"시험 호출 성공 뒤에도 주력으로 돌아오지 않음: {h.calls}"


def test_half_open_lets_only_one_trial_through():
    health = llm_client._ModelHealth()
    for _ in range(health.FAIL_THRESHOLD):
        health.failure("m", "timeout")
    assert not health.try_acquire("m"), "차단 직후인데 통과시켰다"
    health._state["m"]["open_until"] = time.monotonic() - 1
    assert health.try_acquire("m"), "쿨다운이 지났는데 시험 호출을 막았다"
    assert not health.try_acquire("m"), "시험 호출이 진행 중인데 두 번째도 통과시켰다"
    health.failure("m", "timeout")
    assert not health.try_acquire("m"), "시험 호출이 실패했는데 차단이 풀렸다"


def test_gone_model_is_dropped_for_the_run():
    with Harness({GEMMA: Resp(410)}) as h:
        llm_client.call_llm("s", "u")
        h.calls.clear()
        llm_client.call_llm("s", "u")
        assert GEMMA not in h.calls, "내려간(410) 모델을 계속 불렀다"


def test_single_404_is_not_fatal():
    """9/25 muse-glimmer: 시작 직후 404 → 30초 뒤 정상. 404 한 번으로 실행 내내 빼면 안 된다."""
    with Harness({GEMMA: Resp(404)}) as h:
        llm_client.call_llm("s", "u")
        h.calls.clear()
        h.behaviour[GEMMA] = Resp(200, "복구")
        assert llm_client.call_llm("s", "u") == "복구"
        assert h.calls == [GEMMA], f"404 한 번에 모델을 빼 버렸다: {h.calls}"


def test_ladder_order_is_faithful_first_then_local():
    """gemma → muse-glimmer → deepseek → 로컬. 최후 수단 모델은 기본으로 없다."""
    timeout = requests.exceptions.ReadTimeout("read timed out")
    with Harness({GEMMA: timeout, BACKUP: timeout, BACKUP2: Resp(200, "딥시크")}) as h:
        assert llm_client.call_llm("s", "u") == "딥시크"
        assert h.calls == [GEMMA, BACKUP, BACKUP2], f"순서가 틀림: {h.calls}"
        assert h.local_calls == 0

    with Harness({GEMMA: timeout, BACKUP: timeout, BACKUP2: timeout}, local=None) as h:
        assert llm_client.call_llm("s", "u") is None
        assert h.calls == [GEMMA, BACKUP, BACKUP2], f"기본값인데 최후 수단 모델을 불렀다: {h.calls}"
        assert h.local_calls == 1, "클라우드가 모두 실패하면 로컬을 불러야 한다"


def test_last_resort_runs_only_after_local_fails_when_enabled():
    timeout = requests.exceptions.ReadTimeout("read timed out")
    os.environ["LLM_LAST_RESORT_MODELS"] = LAST
    try:
        with Harness({GEMMA: timeout, BACKUP: timeout, BACKUP2: timeout,
                      LAST: Resp(200, "최후")}, local=None) as h:
            assert llm_client.call_llm("s", "u") == "최후"
            assert h.calls == [GEMMA, BACKUP, BACKUP2, LAST], f"순서가 틀림: {h.calls}"
            assert h.local_calls == 1, "최후 수단보다 로컬을 먼저 불러야 한다"

        with Harness({GEMMA: timeout, BACKUP: timeout, BACKUP2: timeout}, local="로컬") as h:
            assert llm_client.call_llm("s", "u") == "로컬"
            assert LAST not in h.calls, "로컬이 건졌는데 최후 수단까지 불렀다"
    finally:
        os.environ.pop("LLM_LAST_RESORT_MODELS", None)


def test_probe_timeouts_open_breaker_before_summaries_start():
    """키 점검이 전부 응답 없음이면 본 요약은 처음부터 백업 모델로 간다."""
    timeout = requests.exceptions.ReadTimeout("read timed out")
    with Harness({GEMMA: timeout}) as h:
        for i in range(8):
            assert llm_client.probe_key("k", f"cat{i}") is True, "타임아웃으로 키를 버리면 안 된다"
        h.calls.clear()
        llm_client.call_llm("s", "u")
        assert h.calls == [BACKUP], f"점검에서 막힌 게 드러났는데 주력부터 불렀다: {h.calls}"
    llm_client.KEY_STATUS.clear()


def test_reserve_budget_reopens_exhausted_budget():
    saved = (llm_client._deadline, llm_client._local_deadline)
    try:
        llm_client._deadline = time.monotonic() - 10       # 요약 단계가 다 써 버린 상태
        llm_client._local_deadline = time.monotonic() - 10
        assert llm_client._budget_exhausted() and llm_client._local_budget_exhausted()
        llm_client.reserve_budget(600)
        assert not llm_client._budget_exhausted(), "클라우드 예산이 확보되지 않았다"
        assert not llm_client._local_budget_exhausted(), "로컬 예산이 확보되지 않았다"

        # 이미 넉넉하면 줄이지 않는다
        far = time.monotonic() + 5000
        llm_client._deadline = far
        llm_client.reserve_budget(600)
        assert llm_client._deadline == far, "남은 예산을 오히려 줄였다"
    finally:
        llm_client._deadline, llm_client._local_deadline = saved


KST = timezone(timedelta(hours=9))


def _art(title, link, important=True, hours=1, failed=False, original=None):
    a = NewsArticle(title=title, link=link,
                    published=datetime.now(KST) - timedelta(hours=hours),
                    summary=title + " 요약", source="테스트", category="x")
    a.is_important = important
    a.llm_failed = failed
    if original:
        a.original_title = original
    return a


def test_top10_fallback_drops_same_article_and_same_event():
    """9/18 실제 제목으로 재현: 같은 기사 두 분야 중복 + 풍계리 4장."""
    same = _art("북한 풍계리 6차 핵실험 후 잠자던 단층 다시 움직였다", "https://x/1")
    news = {
        "politics": [same,
                     _art("북한 풍계리 핵실험, 잠든 단층 깨웠나…지진 8년간 증가", "https://x/2")],
        "society": [same,
                    _art("북한 풍계리 인근 지진 증가···부산대 연구팀 발표", "https://x/3"),
                    _art("국힘, 교육장관 사퇴 요구", "https://x/4")],
        "economy": [_art("미국 8월 잠정 주택 판매 소폭 증가", "https://x/5")],
        "it": [_art("과기정통부, 국가연구개발 AI 윤리 가이드라인", "https://x/6"),
               _art("앤트로픽, AI 기반 생물학 연구 실험실 설립", "https://x/7")],
    }
    saved = summarizer.call_llm_json
    summarizer.call_llm_json = lambda *a, **k: None          # LLM 실패 → 폴백 경로
    try:
        cards = summarizer.select_top10(news)
    finally:
        summarizer.call_llm_json = saved
    links = [c["link"] for c in cards]
    assert len(links) == len(set(links)), f"같은 기사가 두 장 실렸다: {links}"
    heads = [c["card_headline"] for c in cards]
    punggye = [h for h in heads if "풍계리" in h]
    # 후보가 모자라면 중복을 감수하고 채우므로, 서로 다른 사건이 먼저 다 들어갔는지 본다
    first_five = heads[:5]
    assert sum("풍계리" in h for h in first_five) == 1, f"같은 사건이 앞자리를 여러 장 차지: {first_five}"
    assert any("앤트로픽" in h for h in heads) and any("과기정통부" in h for h in heads), \
        f"'AI'만 겹치는 서로 다른 기사를 같은 사건으로 묶었다: {heads}"
    assert len(punggye) >= 1


def test_top10_prefers_translated_cards_and_matches_across_languages():
    ko = _art("메르츠 독일 총리, 지역 선거 참패에도 직무 수행 의지", "https://x/k",
              original="Germany's Merz calls state election a disaster")
    en = _art("German Chancellor Merz calls state election a 'disaster'", "https://x/e",
              failed=True, hours=0)
    other = _art("Houthis push to expand territory", "https://x/h", failed=True)
    news = {"world": [en, other], "economy": [ko]}
    saved = summarizer.call_llm_json
    summarizer.call_llm_json = lambda *a, **k: None
    try:
        cards = summarizer.select_top10(news)
    finally:
        summarizer.call_llm_json = saved
    assert cards[0]["link"] == "https://x/k", f"번역된 카드가 먼저 와야 한다: {cards}"
    assert "https://x/e" not in [c["link"] for c in cards[:2]], \
        "한국어 카드와 같은 사건의 영문 원문 카드가 바로 뒤에 붙었다"


def test_top10_llm_path_also_dedups():
    a = _art("북한 풍계리 인근 지진 증가", "https://x/1")
    b = _art("북한 풍계리 핵실험 단층 깨웠나", "https://x/2")
    c = _art("미국 주택 판매 증가", "https://x/3")
    news = {"politics": [a, b], "economy": [c]}
    saved = summarizer.call_llm_json
    summarizer.call_llm_json = lambda *x, **k: [
        {"id": 1, "rank": 1, "card_headline": "풍계리1", "card_blurb": "."},
        {"id": 2, "rank": 2, "card_headline": "풍계리2", "card_blurb": "."},
        {"id": 3, "rank": 3, "card_headline": "주택", "card_blurb": "."},
    ]
    try:
        cards = summarizer.select_top10(news)
    finally:
        summarizer.call_llm_json = saved
    heads = [c["card_headline"] for c in cards]
    assert heads[:2] == ["풍계리1", "주택"], f"LLM이 같은 사건을 두 번 골랐을 때 걸러야 한다: {heads}"


def test_foreign_script_in_summary_is_rejected():
    """9/26: muse-glimmer가 '앞두고对华 강경 발언'처럼 중국어를 섞었다 — 받지 않고 재요약 대상으로"""
    a = _art("Trump softens China rhetoric", "https://x/cn", important=False)
    a.language = "en"
    saved = summarizer.call_llm_json
    summarizer.call_llm_json = lambda *x, **k: [{
        "id": 1, "paraphrased_title": "트럼프, 중국 발언 누그러뜨려",
        "summary_250": "트럼프 대통령이 중국 지도자 접대를 앞두고对华 강경 발언을 누그러뜨렸다.",
        "is_important": False, "off_topic": False, "exclude": False}]
    try:
        kept = summarizer._summarize_chunk("국제", [a])
    finally:
        summarizer.call_llm_json = saved
    assert kept[0].llm_failed, "중국어가 섞인 요약을 그대로 받았다"

    from src.utils.text_guard import foreign_leak
    assert not foreign_leak("이란 美에 7일 휴전안 재제안"), "신문 한자(美)는 허용해야 한다"
    assert foreign_leak("두 달간同居하며")
    assert not foreign_leak("鄭 의원 발언", "鄭 의원이 말했다"), "원문에 있던 한자는 허용"


def test_terms_keep_one_card_when_names_are_filtered():
    """지명 등을 걸러 10개가 안 되면 예전엔 그날 시사용어를 통째로 버렸다 — 5개 이상이면 1장"""
    from src import terms_extractor
    from src.app_terms import wiki
    arts = [_art(f"기사 {i}", f"https://x/t{i}") for i in range(8)]
    buckets = {"economy": {"domestic": arts, "overseas": []}}
    reply = [{"id": i + 1, "term": f"용어{i}", "definition": "일반적인 뜻을 설명하는 문장이다."} for i in range(8)]
    reply[0]["term"] = "호르무즈 해협"
    reply[1]["term"] = "뜻에 중국어"
    reply[1]["definition"] = "두 달간同居하며 생긴 말이다."
    saved = (terms_extractor.call_llm_json, wiki.lookup)
    terms_extractor.call_llm_json = lambda *x, **k: reply
    wiki.lookup = lambda titles: {"호르무즈 해협": {"entity": True}}
    try:
        terms = terms_extractor.extract_terms(buckets, date_str="2026-09-26")
    finally:
        terms_extractor.call_llm_json, wiki.lookup = saved
    names = [t["term"] for t in terms]
    assert len(names) == 5, f"6개 남으면 1장(5개)을 보내야 한다: {names}"
    assert "호르무즈 해협" not in names and "뜻에 중국어" not in names, names

    # 위키백과를 못 읽어도 시사용어는 나간다
    wiki.lookup = lambda titles: (_ for _ in ()).throw(RuntimeError("down"))
    terms_extractor.call_llm_json = lambda *x, **k: reply
    try:
        terms = terms_extractor.extract_terms(buckets, date_str="2026-09-26")
    finally:
        terms_extractor.call_llm_json, wiki.lookup = saved
    assert len(terms) == 5, "위키백과 장애로 시사용어가 사라지면 안 된다"


def test_card_draws_hanja_with_fallback_font():
    """나눔고딕에 한자가 없어 '이란 美에'가 '이란    에'로 빈칸이 됐다(9/26)"""
    from PIL import ImageFont
    from src.utils import cardnews
    font = ImageFont.truetype(cardnews._FONT_BOLD, 30)
    runs = cardnews._runs("이란 美에", font)
    if cardnews._fallback_for(font) is None:
        print("   (이 환경엔 한자 대체 폰트가 없어 건너뜀)")
        return
    assert any("美" in part and use is not font for part, use in runs), f"美를 대체 폰트로 그리지 않았다: {runs}"
    assert all(use is font for part, use in runs if "이" in part), "한글은 번들 폰트 그대로여야 한다"


if __name__ == "__main__":
    os.environ["LOCAL_LLM_ENABLED"] = "1"
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok  {name}")
    print("OK: resilience self-checks passed")
