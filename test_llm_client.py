"""
Self-check: call_llm_json()의 파싱/복구/폴백 로직 검증
실제 NVIDIA API도 로컬 LLM 서버도 호출하지 않는다 — llm_client.call_llm과
call_local_llm을 둘 다 몽키패치해서 "LLM이 이런 문자열을 반환했을 때"
시나리오만 테스트한다. API 키도, LM Studio가 떠 있을 필요도 없다.

로컬 폴백까지 반드시 함께 패치해야 한다. call_llm만 가로채면 클라우드 JSON이
깨졌을 때 call_llm_json이 진짜 로컬 서버로 나가버려서, 테스트가 그날 LM Studio가
떠 있는지에 따라 결과가 바뀐다(실제로 겪었다).

python test_llm_client.py 로 실행. 실패 시 AssertionError로 즉시 중단.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import llm_client


def _patch_call_llm(responses, local_responses=()):
    """
    responses: call_llm이 순서대로 반환할 값 (호출될 때마다 하나씩 소비)
    local_responses: call_local_llm이 순서대로 반환할 값 (기본: 항상 None
                     = 로컬을 못 쓰는 상황). 반환값은 (원래 call_llm, 원래 call_local_llm)
    """
    queue = list(responses)
    local_queue = list(local_responses)
    original = llm_client.call_llm
    original_local = llm_client.call_local_llm

    def fake_call_llm(*args, **kwargs):
        return queue.pop(0) if queue else None

    def fake_call_local_llm(*args, **kwargs):
        return local_queue.pop(0) if local_queue else None

    llm_client.call_llm = fake_call_llm
    llm_client.call_local_llm = fake_call_local_llm
    return original, original_local


def _restore(originals):
    llm_client.call_llm, llm_client.call_local_llm = originals


def test_direct_json_pass_through():
    original = _patch_call_llm(['[{"id": 1, "ok": true}]'])
    try:
        result = llm_client.call_llm_json("sys", "user")
        assert result == [{"id": 1, "ok": True}], f"직접 JSON 파싱 실패: {result!r}"
    finally:
        _restore(original)


def test_json_embedded_in_prose_is_extracted():
    original = _patch_call_llm(['물론입니다! 요청하신 결과는 다음과 같습니다:\n[{"id": 2}]\n이상입니다.'])
    try:
        result = llm_client.call_llm_json("sys", "user")
        assert result == [{"id": 2}], f"프롬프트 감싼 JSON 추출 실패: {result!r}"
    finally:
        _restore(original)


def test_repair_reprompt_recovers():
    # 1차 호출은 완전히 깨진 텍스트, 재프롬프트(2차 호출)는 유효 JSON
    original = _patch_call_llm(["이건 JSON이 아닙니다 그냥 텍스트", '[{"id": 3}]'])
    try:
        result = llm_client.call_llm_json("sys", "user")
        assert result == [{"id": 3}], f"재프롬프트 복구 실패: {result!r}"
    finally:
        _restore(original)


def test_persistent_garbage_returns_none_without_raising():
    # 클라우드도 로컬도 못 건지는 상황 — 호출부가 규칙기반으로 넘어가도록 None
    original = _patch_call_llm(["여전히 텍스트", "또 텍스트"], local_responses=[None])
    try:
        result = llm_client.call_llm_json("sys", "user")
        assert result is None, f"복구 불가능한 응답은 None이어야 함: {result!r}"
    finally:
        _restore(original)


def test_local_rescues_unparseable_cloud_json():
    """
    클라우드가 응답은 줬는데 JSON이 아닌 경우. call_llm()의 자동 폴백은 '전송 실패'에만
    걸리므로, 이 경로는 call_llm_json이 명시적으로 로컬을 불러야 건져진다.
    예전에는 여기서 곧장 규칙기반으로 떨어져 지면에 영문 원문이 그대로 노출됐다.
    """
    original = _patch_call_llm(
        ["JSON 아님", "여전히 JSON 아님"],
        local_responses=['[{"id": 9, "summary_250": "로컬이 건져낸 요약"}]'],
    )
    try:
        result = llm_client.call_llm_json("sys", "user")
        assert result == [{"id": 9, "summary_250": "로컬이 건져낸 요약"}], \
            f"로컬 폴백이 JSON을 건져내야 함: {result!r}"
    finally:
        _restore(original)


def test_local_salvages_truncated_json():
    """로컬 응답이 max_tokens에 잘려도 완성된 객체는 건진다."""
    original = _patch_call_llm(
        ["JSON 아님", "여전히 JSON 아님"],
        local_responses=['[{"id": 1, "v": "a"}, {"id": 2, "v": "b"}, {"id": 3, "v'],
    )
    try:
        result = llm_client.call_llm_json("sys", "user")
        assert result == [{"id": 1, "v": "a"}, {"id": 2, "v": "b"}], \
            f"잘린 로컬 응답에서 완성분만 건져야 함: {result!r}"
    finally:
        _restore(original)


def test_missing_api_key_falls_through_to_local():
    """
    키가 없으면 클라우드는 네트워크를 타지 않고 즉시 포기하고, 로컬이 이어받는다.
    (예전에는 곧장 None이었다 — 키 미설정이 곧 규칙기반이었다)
    """
    os.environ.pop("NVIDIA_API_KEY", None)
    original_local = llm_client.call_local_llm
    called = []

    def fake_local(*args, **kwargs):
        called.append(True)
        return "로컬 응답"

    llm_client.call_local_llm = fake_local
    try:
        result = llm_client.call_llm("sys", "user")
        assert called, "키가 없으면 로컬 폴백을 시도해야 함"
        assert result == "로컬 응답", f"로컬 응답을 그대로 반환해야 함: {result!r}"
    finally:
        llm_client.call_local_llm = original_local


def test_local_disabled_returns_none_without_network_call():
    """LOCAL_LLM_ENABLED=0이면 로컬을 아예 안 부른다 — 기존 동작 그대로."""
    os.environ.pop("NVIDIA_API_KEY", None)
    original_flag = os.environ.get("LOCAL_LLM_ENABLED")
    os.environ["LOCAL_LLM_ENABLED"] = "0"
    try:
        assert not llm_client.local_llm_enabled(), "플래그가 반영되지 않음"
        result = llm_client.call_llm("sys", "user")
        assert result is None, \
            f"로컬 비활성 + 키 없음이면 네트워크 없이 None: {result!r}"
    finally:
        if original_flag is None:
            os.environ.pop("LOCAL_LLM_ENABLED", None)
        else:
            os.environ["LOCAL_LLM_ENABLED"] = original_flag


if __name__ == "__main__":
    test_direct_json_pass_through()
    test_json_embedded_in_prose_is_extracted()
    test_repair_reprompt_recovers()
    test_persistent_garbage_returns_none_without_raising()
    test_local_rescues_unparseable_cloud_json()
    test_local_salvages_truncated_json()
    test_missing_api_key_falls_through_to_local()
    test_local_disabled_returns_none_without_network_call()
    print("OK: llm_client self-checks passed")
