"""
Self-check: call_llm_json()의 파싱/복구/폴백 로직 검증
실제 NVIDIA API는 호출하지 않는다 — llm_client.call_llm을 몽키패치해서
"LLM이 이런 문자열을 반환했을 때" 시나리오만 테스트한다. API 키는 필요 없다.

python test_llm_client.py 로 실행. 실패 시 AssertionError로 즉시 중단.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.utils import llm_client


def _patch_call_llm(responses):
    """responses: 순서대로 반환할 값 리스트 (호출될 때마다 하나씩 소비)"""
    queue = list(responses)
    original = llm_client.call_llm

    def fake_call_llm(*args, **kwargs):
        return queue.pop(0) if queue else None

    llm_client.call_llm = fake_call_llm
    return original


def _restore(original):
    llm_client.call_llm = original


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
    original = _patch_call_llm(["여전히 텍스트", "또 텍스트"])
    try:
        result = llm_client.call_llm_json("sys", "user")
        assert result is None, f"복구 불가능한 응답은 None이어야 함: {result!r}"
    finally:
        _restore(original)


def test_missing_api_key_returns_none_without_network_call():
    os.environ.pop("NVIDIA_API_KEY", None)
    result = llm_client.call_llm("sys", "user")
    assert result is None, "API 키가 없으면 네트워크 호출 없이 None을 반환해야 함"


if __name__ == "__main__":
    test_direct_json_pass_through()
    test_json_embedded_in_prose_is_extracted()
    test_repair_reprompt_recovers()
    test_persistent_garbage_returns_none_without_raising()
    test_missing_api_key_returns_none_without_network_call()
    print("OK: llm_client self-checks passed")
