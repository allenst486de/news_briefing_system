"""
앱용 시사 용어 작업 전용 NVIDIA NIM 호출기.

브리핑의 llm_client 를 쓰지 않는 이유
    브리핑은 한 실행에서 70여 번을 부르며 시간 예산·동시 호출 슬롯·로컬 폴백을 한 프로세스
    안에서 나눠 쓴다. 이 작업은 GitHub 서버에서 열 번 안팎만 부르고 로컬 모델도 없다.
    그 상태를 끌어오지 않고, 끊김에만 집중한 작은 호출기를 따로 둔다.
    모델 이름과 주소는 llm_client 의 것을 그대로 쓴다 — 모델을 바꿀 때 한 곳만 고치면 된다.

끊김 대책
    1) 스트리밍으로 받는다. 비스트리밍은 응답이 멈춰도 read timeout(브리핑은 180초)이
       다 찰 때까지 알 수 없다(실측 9/10·9/12 ReadTimeout). 스트리밍은 조각이
       IDLE_TIMEOUT 초 동안 안 오면 곧바로 끊고 다른 키로 다시 시도한다.
    2) 호출 하나에도 전체 상한(CALL_TIMEOUT)을 둔다. 조각이 찔끔찔끔 와서 idle 에는
       안 걸리면서 한없이 늘어지는 경우를 막는다.
    3) 429 는 Retry-After 만큼 그 키만 쉬게 하고 다른 키로 바로 넘어간다.
    4) 401·403 이 난 키는 이번 실행에서 뺀다. 400·404·422 는 요청 자체의 문제라
       다른 키로 바꿔도 똑같으므로 재시도하지 않는다.
    5) 작업 전체 마감(deadline)을 넘기면 더 부르지 않는다 — 다음 회차가 이어서 채운다.

실패해도 예외를 던지지 않고 None 을 돌려준다. 호출부는 그 묶음을 건너뛴다.
"""
import json
import os
import random
import time
from typing import Callable, Dict, List, Optional, Tuple

import requests

from ..utils.llm_client import NVIDIA_API_URL, NVIDIA_MODEL
from ..utils.logger import setup_logger

logger = setup_logger()

CONNECT_TIMEOUT = 10
IDLE_TIMEOUT = 45
CALL_TIMEOUT = 150
MAX_ATTEMPTS = 4

_RETRY_AFTER_CAP = 60
_FATAL_KEY = (401, 403)
_FATAL_REQUEST = (400, 404, 422)

# 전용 키(NVIDIA_API_KEY_TERMS)가 있으면 맨 앞에 둔다. 없으면 브리핑 키를 함께 쓰는데,
# 브리핑은 03:30 에 시작해 늦어도 05:40 에 끝나고 이 작업은 06:20 부터라 호출 제한이 겹치지 않는다.
KEY_ENV_NAMES = [
    "NVIDIA_API_KEY_TERMS", "NVIDIA_API_KEY",
    "NVIDIA_API_KEY_POLITICS", "NVIDIA_API_KEY_ECONOMY", "NVIDIA_API_KEY_SOCIETY",
    "NVIDIA_API_KEY_LIFE", "NVIDIA_API_KEY_CULTURE", "NVIDIA_API_KEY_IT",
    "NVIDIA_API_KEY_SCIENCE", "NVIDIA_API_KEY_WORLD",
]

STATS: Dict[str, int] = {}


def reset_stats() -> None:
    STATS.clear()
    STATS.update({"calls": 0, "ok": 0, "rate_limited": 0, "stalled": 0,
                  "network": 0, "http": 0, "dropped_keys": 0})


reset_stats()


def stats_line() -> str:
    s = STATS
    return (f"호출 {s['calls']}건 · 성공 {s['ok']} · 호출제한(429) {s['rate_limited']} · "
            f"응답멈춤 {s['stalled']} · 네트워크 {s['network']} · HTTP오류 {s['http']} · "
            f"뺀 키 {s['dropped_keys']}")


def model_name() -> str:
    return os.getenv("APP_TERMS_MODEL") or NVIDIA_MODEL


class KeyPool:
    """키를 돌아가며 쓴다. 429 난 키는 잠시 쉬게 하고, 인증이 거절된 키는 뺀다."""

    def __init__(self, keys: List[Tuple[str, str]], clock: Callable[[], float] = time.monotonic):
        self._keys = list(keys)
        self._cool_until: Dict[str, float] = {}
        self._dropped = set()
        self._next = 0
        self._clock = clock

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
        return [(label, key) for label, key in self._keys if label not in self._dropped]

    def __len__(self) -> int:
        return len(self.alive())

    def acquire(self) -> Tuple[Optional[Tuple[str, str]], float]:
        """쓸 수 있는 키 하나. 모두 쉬는 중이면 (None, 가장 빨리 풀리기까지 남은 초)."""
        alive = self.alive()
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
        self._cool_until[label] = self._clock() + max(seconds, 0.0)

    def drop(self, label: str) -> None:
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
        # (연결, 조각 사이 대기) — 스트리밍에서는 두 번째 값이 '응답이 멈춘 시간' 상한이 된다
        timeout=(CONNECT_TIMEOUT, IDLE_TIMEOUT),
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


def chat(pool: KeyPool, system_prompt: str, user_prompt: str, *,
         max_tokens: int = 1024, temperature: float = 0.2,
         deadline: Optional[float] = None,
         post=None, sleep: Callable[[float], None] = time.sleep,
         clock: Callable[[], float] = time.monotonic) -> Optional[str]:
    """NIM chat completions 를 스트리밍으로 부른다. 실패하면 None."""
    post = post or requests.post
    payload = {
        "model": model_name(),
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

    for attempt in range(MAX_ATTEMPTS):
        if deadline is not None and clock() >= deadline:
            logger.warning("작업 마감 시각이 지나 호출하지 않음 — 다음 회차에 이어서")
            return None

        picked, wait = pool.acquire()
        if picked is None:
            if not pool.alive():
                logger.warning("쓸 수 있는 NVIDIA 키가 없음")
                return None
            if deadline is not None and clock() + wait >= deadline:
                logger.warning("모든 키가 쉬는 중인데 마감 전에 풀리지 않음")
                return None
            sleep(wait)
            picked, _ = pool.acquire()
            if picked is None:
                return None
        label, key = picked

        STATS["calls"] += 1
        try:
            status, content, retry_after = _stream_once(post, key, payload, clock)
        except (requests.exceptions.RequestException, _Stalled) as error:
            text = str(error).lower()
            stalled = isinstance(error, (_Stalled, requests.exceptions.Timeout)) or "timed out" in text
            STATS["stalled" if stalled else "network"] += 1
            logger.warning(f"[{label}] 응답 {'멈춤' if stalled else '끊김'}({type(error).__name__}) "
                           f"— 다른 키로 재시도 {attempt + 1}/{MAX_ATTEMPTS}")
            pool.cool(label, 20)
            continue

        if status == 200:
            if content:
                STATS["ok"] += 1
                return content
            STATS["http"] += 1
            logger.warning(f"[{label}] 빈 응답 — 재시도")
            continue
        if status == 429:
            STATS["rate_limited"] += 1
            wait = retry_after or _backoff(attempt)
            logger.warning(f"[{label}] 호출 제한(429) — 이 키는 {wait:.0f}초 쉬고 다른 키로")
            pool.cool(label, wait)
            continue
        if status in _FATAL_KEY:
            STATS["dropped_keys"] += 1
            logger.warning(f"[{label}] 인증 거절({status}) — 이번 실행에서 이 키를 뺌")
            pool.drop(label)
            continue
        if status in _FATAL_REQUEST:
            STATS["http"] += 1
            logger.warning(f"[{label}] 요청 거절({status}) — 모델 이름·요청 형식 문제라 재시도하지 않음")
            return None

        STATS["http"] += 1
        logger.warning(f"[{label}] 서버 오류({status}) — 잠시 뒤 재시도")
        pool.cool(label, _backoff(attempt))

    return None
