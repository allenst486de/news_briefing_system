"""
NVIDIA NIM REST Client
OpenAI 호환 chat completions 엔드포인트에 requests.post 1회로 직접 호출한다.
JSON POST 요청 하나뿐이라 openai/anthropic 같은 SDK는 불필요.

NVIDIA_API_KEY는 환경변수(GitHub Secrets)로만 전달된다 — 이 파일을 포함해
어떤 파일에도 실제 키 값을 하드코딩하지 않는다.
"""
import json
import os
import re
import threading
import time
from typing import Optional, Union

import requests

from .logger import setup_logger

logger = setup_logger()

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "google/gemma-4-31b-it"  # NVIDIA NIM 카탈로그에서 모델 폐기/변경 시 갱신 필요

# LLM이 실패해도 항상 규칙기반으로 조용히 폴백하기 때문에, 며칠씩 "번역이 안 된다"를
# 모르고 지나가는 일이 실제로 있었다. 실행마다 집계해서 main.py가 Actions 실행 요약에
# 찍는다 — 다음 실행에서 원인을 바로 볼 수 있도록.
LLM_STATS = {
    "calls": 0, "ok": 0, "no_key": 0, "http_error": 0,
    "network_error": 0, "parse_fail": 0, "salvaged": 0, "budget": 0, "errors": [],
}

_stats_lock = threading.Lock()

# 실행 전체에서 LLM에 쓸 수 있는 총 시간. 워크플로 30분 제한 안에서 수집·본문·
# HTML 생성까지 끝나야 하므로 LLM이 무한정 잡아먹지 않도록 못을 박는다.
# 초과하면 남은 호출은 즉시 None을 반환하고 호출부가 규칙기반으로 넘어간다 —
# 요약 품질이 일부 떨어져도 사이트는 반드시 발행된다.
LLM_TIME_BUDGET_SECONDS = 900
_deadline = None


def _record(key: str, detail: Optional[str] = None) -> None:
    with _stats_lock:
        LLM_STATS[key] = LLM_STATS.get(key, 0) + 1
        if detail and len(LLM_STATS["errors"]) < 5:
            LLM_STATS["errors"].append(detail)


def _budget_exhausted() -> bool:
    global _deadline
    if _deadline is None:
        _deadline = time.monotonic() + LLM_TIME_BUDGET_SECONDS
        return False
    return time.monotonic() > _deadline


def stats_summary() -> str:
    s = LLM_STATS
    lines = [
        f"호출 {s['calls']}건 · 성공 {s['ok']} · 부분복구 {s['salvaged']} · "
        f"JSON실패 {s['parse_fail']} · HTTP오류 {s['http_error']} · "
        f"네트워크오류 {s['network_error']} · 키없음 {s['no_key']} · "
        f"시간예산초과 {s['budget']}"
    ]
    if s["errors"]:
        lines.append("첫 오류: " + s["errors"][0])
    return "\n".join(lines)


def call_llm(system_prompt: str, user_prompt: str, *, temperature: float = 0.3,
             max_tokens: int = 4096, timeout: int = 60, retries: int = 2) -> Optional[str]:
    """
    NVIDIA NIM chat completions 1회 호출(비스트리밍).
    429/5xx/네트워크 오류 시 지수 백오프로 재시도. 재시도까지 모두 실패하면
    예외를 던지지 않고 None을 반환한다 — 호출부가 규칙기반 폴백으로 넘어가도록.
    """
    with _stats_lock:
        LLM_STATS["calls"] += 1

    if _budget_exhausted():
        _record("budget", f"LLM 시간 예산 {LLM_TIME_BUDGET_SECONDS}초 초과 — 남은 요약은 규칙기반")
        return None

    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA_API_KEY not set — skipping LLM call")
        _record("no_key", "NVIDIA_API_KEY 환경변수가 비어 있음")
        return None

    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {
        "model": NVIDIA_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
        # gemma-4-31b-it은 내장 thinking 모드가 있다 — 켜져 있으면 JSON 앞에
        # 추론 텍스트가 붙어 엄격한 JSON 파싱이 깨질 수 있어 명시적으로 끈다.
        "chat_template_kwargs": {"enable_thinking": False},
    }

    for attempt in range(retries + 1):
        try:
            resp = requests.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"retryable status {resp.status_code}")
            if not resp.ok:
                # 4xx는 재시도해도 안 바뀌므로 응답 본문을 로그로 남기고 바로 포기
                logger.warning(f"LLM call rejected ({resp.status_code}): {resp.text[:500]}")
                _record("http_error", f"HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            _record("ok")
            return content
        except Exception as e:
            logger.warning(f"LLM call failed (attempt {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                _record("network_error", f"{type(e).__name__}: {str(e)[:200]}")

    return None


def _extract_json_block(text: str) -> Optional[str]:
    match = re.search(r"\[.*\]|\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


def _salvage_array(text: str) -> Optional[list]:
    """
    max_tokens에 걸려 배열이 닫히기 전에 잘린 응답에서 '완성된 객체'만 건져낸다.
    닫는 ']'가 없으면 위 정규식이 통째로 실패해 카테고리 전체가 폴백되는데,
    30건 중 22건이 멀쩡히 왔는데 0건으로 취급하는 건 아깝다.
    """
    start = text.find("[")
    if start < 0:
        return None

    items, depth, in_str, escaped, obj_start = [], 0, False, False, None
    for i in range(start + 1, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    items.append(json.loads(text[obj_start:i + 1]))
                except json.JSONDecodeError:
                    pass
                obj_start = None
    return items or None


def call_llm_json(system_prompt: str, user_prompt: str, *, retries: int = 2,
                   **llm_kwargs) -> Optional[Union[dict, list]]:
    """
    call_llm() 응답을 JSON으로 파싱.
    1) 직접 json.loads 시도
    2) 실패 시 첫 {...}/[...] 블록을 정규식으로 추출해 재시도
    3) 그래도 실패하면 "JSON만 출력하라"는 재프롬프트로 1회 더 시도
    4) 그래도 실패하면 None (예외를 던지지 않음 — 호출부가 폴백으로 전환)
    """
    raw = call_llm(system_prompt, user_prompt, retries=retries, **llm_kwargs)
    parsed = _try_parse(raw)
    if parsed is not None:
        return parsed

    if raw is None:
        return None

    # 재프롬프트 전에 먼저 건져본다 — 응답이 잘린 거라면 재요청해도 똑같이 잘린다
    salvaged = _salvage_array(raw)
    if salvaged:
        logger.warning(f"JSON truncated — salvaged {len(salvaged)} complete items")
        _record("salvaged")
        return salvaged

    logger.warning("JSON parse failed — retrying with a stricter re-prompt")
    strict_system = system_prompt + "\n\n이전 응답은 유효한 JSON이 아니었습니다. 설명 없이 JSON만 출력하세요."
    raw2 = call_llm(strict_system, user_prompt, retries=0, **llm_kwargs)
    parsed2 = _try_parse(raw2)
    if parsed2 is not None:
        return parsed2

    salvaged2 = _salvage_array(raw2 or "")
    if salvaged2:
        _record("salvaged")
        return salvaged2

    logger.warning("LLM JSON output could not be parsed after retries — giving up")
    _record("parse_fail", f"JSON 파싱 실패, 응답 앞부분: {(raw or '')[:150]}")
    return None


def _try_parse(raw: Optional[str]) -> Optional[Union[dict, list]]:
    if not raw:
        return None
    for candidate in (raw, _extract_json_block(raw)):
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
    return None
