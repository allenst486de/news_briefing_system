"""
앱용 시사 용어 작업 전용 NVIDIA NIM 호출기.

브리핑의 llm_client 를 쓰지 않는 이유
    브리핑은 한 실행에서 70여 번을 부르며 시간 예산·동시 호출 슬롯·로컬 폴백을 한 프로세스
    안에서 나눠 쓴다. 이 작업은 GitHub 서버에서 열 번 안팎만 부르고 로컬 모델도 없다.
    그 상태를 끌어오지 않고, 끊김에만 집중한 작은 호출기를 따로 둔다.

NVIDIA 대기열 (2026-09-14 실측)
    gemma-4-31b 는 붐빌 때 요청을 대기열에 세워 두고, 차례가 오기 전까지 응답 헤더조차
    보내지 않는다. 17시대에 잰 대기 시간은 160~170초였고, 차례가 오면 1~3초 만에 답을 끝냈다.
    처음에는 45초 동안 응답이 없으면 끊도록 했는데, 그 때문에 첫 서버 실행에서 14번 모두
    대기열에서 스스로 끊고 한 개도 채우지 못했다. 그래서
      1) 첫 응답은 FIRST_RESPONSE_TIMEOUT(300초)까지 기다린다 — 대기열에서 빠져나오지 않는다.
      2) 그래도 안 오면 대체 모델로 넘어간다(model_chain). 대체 모델은 대기열이 짧지만
         뜻풀이 정확도가 떨어져 기본으로 쓰지 않는다. 어느 모델이 썼는지 결과에 남긴다.
      3) 호출 하나에도 전체 상한(CALL_TIMEOUT)을 둔다 — 조각이 찔끔찔끔 와서 늘어지는 경우.
      4) 429 는 Retry-After 만큼 그 키만 쉬게 하고 같은 모델을 다른 키로 부른다.
      5) 401·403 이 난 키는 이번 실행에서 뺀다. 404(모델이 내려감)·400·422 는 다음 모델로,
         더 넘어갈 모델이 없으면 포기한다.
      6) 작업 전체 마감(deadline)을 넘기면 더 부르지 않는다 — 다음 회차가 이어서 채운다.

실패해도 예외를 던지지 않고 None 을 돌려준다. 호출부는 그 묶음을 건너뛴다.
여러 스레드에서 동시에 불러도 되게 키 목록과 집계는 잠금으로 보호한다.
"""
import json
import os
import random
import threading
import time
from typing import Callable, Dict, List, Optional, Tuple

import requests

from ..utils.llm_client import NVIDIA_API_URL, NVIDIA_MODEL
from ..utils.logger import setup_logger

logger = setup_logger()

CONNECT_TIMEOUT = 10
FIRST_RESPONSE_TIMEOUT = 300
CALL_TIMEOUT = 330
MAX_ATTEMPTS = 4

# 기본 모델이 대기열에서 못 빠져나올 때만 쓴다. 9/14 실측 — glm-5.3-flash 는 바로 받지만 생성이
# 느리고(4개에 약 170초) 뜻풀이가 정확하다. nemotron-3-super 는 5초 안에 끝나지만 뜻이 부정확하거나
# 빈 응답을 줄 때가 있어 마지막에 둔다. APP_TERMS_MODELS(쉼표 구분)로 바꿀 수 있다.
# 9/25 추가 — deepseek-v4.1-flash: 대기열이 짧고(뜻풀이 3개 34초) 뜻이 정확하다. glm 뒤, nemotron 앞.
# nemotron-super 는 9/24 '벤처캐피털'을 it 로 분류하는 등 가장 부정확해 맨 뒤에 둔다.
FALLBACK_MODELS = ["z-ai/glm-5.3-flash", "deepseek-ai/deepseek-v4.1-flash",
                   "nvidia/nemotron-3-super-120b-a12b"]

_RETRY_AFTER_CAP = 60
_FATAL_KEY = (401, 403)
_FATAL_REQUEST = (400, 404, 422)

# 전용 키(NVIDIA_API_KEY_TERMS)가 있으면 맨 앞에 둔다. 없으면 브리핑 키를 함께 쓰는데,
# 브리핑은 03:30 에 시작해 늦어도 05:40 에 끝나고 이 작업은 05:50 부터라 호출 제한이 겹치지 않는다.
KEY_ENV_NAMES = [
    "NVIDIA_API_KEY_TERMS", "NVIDIA_API_KEY",
    "NVIDIA_API_KEY_POLITICS", "NVIDIA_API_KEY_ECONOMY", "NVIDIA_API_KEY_SOCIETY",
    "NVIDIA_API_KEY_LIFE", "NVIDIA_API_KEY_CULTURE", "NVIDIA_API_KEY_IT",
    "NVIDIA_API_KEY_SCIENCE", "NVIDIA_API_KEY_WORLD",
]

STATS: Dict[str, int] = {}
_stats_lock = threading.Lock()


def reset_stats() -> None:
    with _stats_lock:
        STATS.clear()
        STATS.update({"calls": 0, "ok": 0, "fallback": 0, "rate_limited": 0, "stalled": 0,
                      "network": 0, "http": 0, "dropped_keys": 0})


def _count(name: str) -> None:
    with _stats_lock:
        STATS[name] = STATS.get(name, 0) + 1


reset_stats()


def stats_line() -> str:
    s = STATS
    return (f"호출 {s['calls']}건 · 성공 {s['ok']}(대체 모델 {s['fallback']}) · 호출제한(429) {s['rate_limited']} · "
            f"응답없음 {s['stalled']} · 네트워크 {s['network']} · HTTP오류 {s['http']} · 뺀 키 {s['dropped_keys']}")


def model_chain(environ=None) -> List[str]:
    """부를 모델 순서. 앞에서부터 쓰고, 실패하면 다음으로 넘어간다."""
    env = os.environ if environ is None else environ
    configured = [m.strip() for m in (env.get("APP_TERMS_MODELS") or "").split(",") if m.strip()]
    if configured:
        return configured
    return [NVIDIA_MODEL] + [m for m in FALLBACK_MODELS if m != NVIDIA_MODEL]


class KeyPool:
    """키를 돌아가며 쓴다. 429 난 키는 잠시 쉬게 하고, 인증이 거절된 키는 뺀다."""

    def __init__(self, keys: List[Tuple[str, str]], clock: Callable[[], float] = time.monotonic):
        self._keys = list(keys)
        self._cool_until: Dict[str, float] = {}
        self._dropped = set()
        self._next = 0
        self._clock = clock
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls, environ=None, clock: Callable[[], float] = time.monotonic) -> "KeyPool":
        env = os.environ if environ is None else environ
        seen, keys = set(), []
        for name in KEY_ENV_NAMES:
            value = (env.get(name) or "").strip()
            if value and value not in seen:     # 같은 키가 여러 이름으로 들어온 경우 한 번만
                seen.add(value)
                keys.append((name, value))
        return cls(keys, clock)

    def alive(self) -> List[Tuple[str, str]]:
        with self._lock:
            return [(label, key) for label, key in self._keys if label not in self._dropped]

    def __len__(self) -> int:
        return len(self.alive())

    def acquire(self) -> Tuple[Optional[Tuple[str, str]], float]:
        """쓸 수 있는 키 하나. 모두 쉬는 중이면 (None, 가장 빨리 풀리기까지 남은 초)."""
        with self._lock:
            alive = [(label, key) for label, key in self._keys if label not in self._dropped]
            if not alive:
                return None, 0.0
            now = self._clock()
            for offset in range(len(alive)):
                index = (self._next + offset) % len(alive)
                label, key = alive[index]
                if self._cool_until.get(label, 0.0) <= now:
                    self._next = (index + 1) % len(alive)
                    return (label, key), 0.0
            soonest = min(self._cool_until.get(label, 0.0) for label, _ in alive)
            return None, max(soonest - now, 0.0)

    def cool(self, label: str, seconds: float) -> None:
        with self._lock:
            self._cool_until[label] = self._clock() + max(seconds, 0.0)

    def drop(self, label: str) -> None:
        with self._lock:
            self._dropped.add(label)


class _Stalled(Exception):
    """조각은 오는데 호출 전체 상한을 넘긴 경우."""


def _retry_after(resp) -> Optional[float]:
    raw = (getattr(resp, "headers", None) or {}).get("Retry-After")
    try:
        return max(1.0, min(float(raw), _RETRY_AFTER_CAP)) if raw else None
    except (TypeError, ValueError):
        return None


def _backoff(attempt: int) -> float:
    return min(5 * (2 ** attempt), _RETRY_AFTER_CAP) + random.uniform(0, 2)


def _stream_once(post, key: str, payload: Dict, clock) -> Tuple[int, Optional[str], Optional[float]]:
    """한 번 호출해 (상태 코드, 본문, Retry-After) 를 돌려준다. 끊기면 예외."""
    started = clock()
    resp = post(
        NVIDIA_API_URL,
        headers={"Authorization": f"Bearer {key}", "Accept": "text/event-stream"},
        json=payload,
        stream=True,
        # (연결, 읽기 대기). 대기열에 서 있는 동안은 헤더도 안 오므로 읽기 대기를 넉넉히 준다
        timeout=(CONNECT_TIMEOUT, FIRST_RESPONSE_TIMEOUT),
    )
    try:
        if resp.status_code != 200:
            return resp.status_code, None, _retry_after(resp)
        parts = []
        for line in resp.iter_lines():
            if clock() - started > CALL_TIMEOUT:
                raise _Stalled(f"호출 {CALL_TIMEOUT}초 초과")
            if isinstance(line, bytes):
                # 줄 단위로 끊어 받으므로 한글 바이트가 줄 경계에서 잘리지 않는다
                line = line.decode("utf-8", "replace")
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                continue
            for choice in chunk.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content")
                if piece:
                    parts.append(piece)
        return 200, "".join(parts), None
    finally:
        resp.close()


def chat_with_model(pool: KeyPool, system_prompt: str, user_prompt: str, *,
                    max_tokens: int = 1024, temperature: float = 0.2,
                    deadline: Optional[float] = None, models: Optional[List[str]] = None,
                    post=None, sleep: Callable[[float], None] = time.sleep,
                    clock: Callable[[], float] = time.monotonic) -> Tuple[Optional[str], Optional[str]]:
    """NIM chat completions 를 스트리밍으로 부른다. (본문, 답한 모델) — 실패하면 (None, None)."""
    post = post or requests.post
    models = models or model_chain()
    step = 0

    for attempt in range(MAX_ATTEMPTS):
        if deadline is not None and clock() >= deadline:
            logger.warning("작업 마감 시각이 지나 호출하지 않음 — 다음 회차에 이어서")
            return None, None

        picked, wait = pool.acquire()
        if picked is None:
            if not pool.alive():
                logger.warning("쓸 수 있는 NVIDIA 키가 없음")
                return None, None
            if deadline is not None and clock() + wait >= deadline:
                logger.warning("모든 키가 쉬는 중인데 마감 전에 풀리지 않음")
                return None, None
            sleep(wait)
            picked, _ = pool.acquire()
            if picked is None:
                return None, None
        label, key = picked
        model = models[min(step, len(models) - 1)]
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            # 브리핑과 같은 이유로 thinking 을 끈다 — 켜져 있으면 JSON 앞에 추론 글이 붙는다
            "chat_template_kwargs": {"enable_thinking": False},
        }

        _count("calls")
        try:
            status, content, retry_after = _stream_once(post, key, payload, clock)
        except (requests.exceptions.RequestException, _Stalled) as error:
            text = str(error).lower()
            stalled = isinstance(error, (_Stalled, requests.exceptions.Timeout)) or "timed out" in text
            _count("stalled" if stalled else "network")
            logger.warning(f"[{label} · {model}] {'응답 없음' if stalled else '연결 끊김'}"
                           f"({type(error).__name__}) — 다음 모델로 {attempt + 1}/{MAX_ATTEMPTS}")
            pool.cool(label, 20)
            step += 1
            continue

        if status == 200:
            if content:
                _count("ok")
                if model != models[0]:
                    _count("fallback")
                return content, model
            _count("http")
            logger.warning(f"[{label} · {model}] 빈 응답 — 다음 모델로")
            step += 1
            continue
        if status == 429:
            _count("rate_limited")
            wait = retry_after or _backoff(attempt)
            logger.warning(f"[{label} · {model}] 호출 제한(429) — 이 키는 {wait:.0f}초 쉬고 다른 키로")
            pool.cool(label, wait)
            continue
        if status in _FATAL_KEY:
            _count("dropped_keys")
            logger.warning(f"[{label}] 인증 거절({status}) — 이번 실행에서 이 키를 뺌")
            pool.drop(label)
            continue
        if status in _FATAL_REQUEST:
            _count("http")
            if step + 1 < len(models):
                logger.warning(f"[{label} · {model}] 요청 거절({status}) — 모델이 내려갔을 수 있어 다음 모델로")
                step += 1
                continue
            logger.warning(f"[{label} · {model}] 요청 거절({status}) — 넘어갈 모델이 없어 포기")
            return None, None

        _count("http")
        logger.warning(f"[{label} · {model}] 서버 오류({status}) — 다음 모델로")
        pool.cool(label, _backoff(attempt))
        step += 1

    return None, None


def chat(pool: KeyPool, system_prompt: str, user_prompt: str, **kwargs) -> Optional[str]:
    """본문만 필요할 때."""
    return chat_with_model(pool, system_prompt, user_prompt, **kwargs)[0]
