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
import time
from typing import Optional, Union

import requests

from .logger import setup_logger

logger = setup_logger()

NVIDIA_API_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
NVIDIA_MODEL = "google/gemma-4-31b-it"  # NVIDIA NIM 카탈로그에서 모델 폐기/변경 시 갱신 필요


def call_llm(system_prompt: str, user_prompt: str, *, temperature: float = 0.3,
             max_tokens: int = 4096, timeout: int = 60, retries: int = 2) -> Optional[str]:
    """
    NVIDIA NIM chat completions 1회 호출(비스트리밍).
    429/5xx/네트워크 오류 시 지수 백오프로 재시도. 재시도까지 모두 실패하면
    예외를 던지지 않고 None을 반환한다 — 호출부가 규칙기반 폴백으로 넘어가도록.
    """
    api_key = os.getenv("NVIDIA_API_KEY")
    if not api_key:
        logger.warning("NVIDIA_API_KEY not set — skipping LLM call")
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
    }

    for attempt in range(retries + 1):
        try:
            resp = requests.post(NVIDIA_API_URL, headers=headers, json=payload, timeout=timeout)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"retryable status {resp.status_code}")
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"LLM call failed (attempt {attempt + 1}/{retries + 1}): {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)

    return None


def _extract_json_block(text: str) -> Optional[str]:
    match = re.search(r"\[.*\]|\{.*\}", text, re.DOTALL)
    return match.group(0) if match else None


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

    logger.warning("JSON parse failed — retrying with a stricter re-prompt")
    strict_system = system_prompt + "\n\n이전 응답은 유효한 JSON이 아니었습니다. 설명 없이 JSON만 출력하세요."
    raw2 = call_llm(strict_system, user_prompt, retries=0, **llm_kwargs)
    parsed2 = _try_parse(raw2)
    if parsed2 is not None:
        return parsed2

    logger.warning("LLM JSON output could not be parsed after retries — giving up")
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
